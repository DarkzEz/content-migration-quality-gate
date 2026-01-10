import json
from pathlib import Path

import httpx
import pytest

from content_migration_gate.migration import load_export, migrate_export

ROOT = Path(__file__).resolve().parents[2]


def test_load_export_reports_two_pages() -> None:
    export = load_export(ROOT / "examples/tilda-export.json")
    assert len(export.pages) == 2


def test_load_export_rejects_unknown_fields(tmp_path: Path) -> None:
    bad_export = {
        "export_format": "synthetic-tilda-export-v1",
        "unexpected": True,
        "pages": [{"source_id": "a", "slug": "a", "title": "A", "blocks": [{"type": "text", "text": "x"}]}],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad_export), encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot load valid legacy export"):
        load_export(path)


def test_dry_run_maps_without_http_calls() -> None:
    export = load_export(ROOT / "examples/tilda-export.json")

    class ForbiddenClient:
        def post(self, *args, **kwargs):
            raise AssertionError("dry-run must not issue HTTP calls")

    results = migrate_export(
        export,
        admin_url="http://admin",
        dry_run=True,
        client=ForbiddenClient(),  # type: ignore[arg-type]
    )
    assert all(result["status"] == "planned" for result in results)
    assert results[0]["block_count"] == 4


def test_execute_posts_mapped_payload_to_admin_api() -> None:
    export = load_export(ROOT / "examples/tilda-export.json")
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("X-Correlation-ID")))
        payload = json.loads(request.content)
        draft_id = f"draft-{payload['slug']}"
        return httpx.Response(
            200,
            json={
                "draft_id": draft_id,
                "slug": payload["slug"],
                "status": "published",
                "path": f"/v1/pages/{payload['slug']}",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        results = migrate_export(
            export,
            admin_url="http://admin",
            dry_run=False,
            client=client,
        )
    finally:
        client.close()

    assert [result["status"] for result in results] == ["published", "published"]
    assert [path for path, _ in seen] == ["/v1/migrations", "/v1/migrations"]
    assert seen[0][1] == "migration-page-about-center"
    assert seen[1][1] == "migration-page-admissions"


def test_execute_continues_when_one_admin_migration_fails() -> None:
    export = load_export(ROOT / "examples/tilda-export.json")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        if payload["slug"] == "about-the-center":
            return httpx.Response(422, json={"error": {"code": "content_validation_failed"}})
        return httpx.Response(
            200,
            json={"draft_id": "draft-admissions", "slug": payload["slug"], "status": "published", "path": f"/v1/pages/{payload['slug']}"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        results = migrate_export(export, admin_url="http://admin", dry_run=False, client=client)
    finally:
        client.close()
    assert calls == 2
    assert [result["status"] for result in results] == ["failed", "published"]


def test_cli_missing_file_returns_configuration_error(capsys) -> None:
    from content_migration_gate.migration import main

    exit_code = main(["--file", str(ROOT / "not-found.json"), "--dry-run"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Cannot load valid legacy export" in captured.err


def test_cli_returns_nonzero_when_execute_has_partial_failure(monkeypatch, capsys) -> None:
    from content_migration_gate import migration

    export = load_export(ROOT / "examples/tilda-export.json")
    monkeypatch.setattr(migration, "load_export", lambda path: export)
    monkeypatch.setattr(
        migration,
        "migrate_export",
        lambda *args, **kwargs: [
            {"source_id": "page-1", "status": "failed", "error": "simulated"}
        ],
    )
    exit_code = migration.main(["--file", "ignored.json", "--execute"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"status": "failed"' in captured.out


def test_execute_detects_admin_result_for_different_page() -> None:
    export = load_export(ROOT / "examples/tilda-export.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"draft_id": "wrong-draft", "slug": "other-page", "status": "published", "path": "/v1/pages/other-page"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        results = migrate_export(export, admin_url="http://admin", dry_run=False, client=client)
    finally:
        client.close()
    assert results[0]["status"] == "failed"
    assert "different page" in results[0]["error"]
