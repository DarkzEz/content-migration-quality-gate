"""CLI that maps a legacy export and submits each page to the Admin migration API"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from content_migration_gate.contracts import LegacyExport, PublishResult
from content_migration_gate.mapper import map_legacy_page


def load_export(path: str | Path) -> LegacyExport:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        return LegacyExport.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot load valid legacy export from {path}: {exc}") from exc


def migrate_export(
    export: LegacyExport,
    *,
    admin_url: str,
    dry_run: bool,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    planned = [(page, map_legacy_page(page)) for page in export.pages]
    if dry_run:
        return [
            {
                "source_id": page.source_id,
                "slug": payload.slug,
                "title": payload.title,
                "block_count": len(payload.blocks),
                "status": "planned",
            }
            for page, payload in planned
        ]

    owns_client = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(5.0, connect=2.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        follow_redirects=False,
    )
    results: list[dict[str, Any]] = []
    try:
        for page, payload in planned:
            correlation_id = f"migration-{page.source_id}"[:64]
            try:
                publish_response = http.post(
                    f"{admin_url.rstrip('/')}/v1/migrations",
                    json=payload.model_dump(mode="json"),
                    headers={"X-Correlation-ID": correlation_id},
                )
                if publish_response.is_error:
                    body = (
                        publish_response.json()
                        if "application/json" in publish_response.headers.get("content-type", "")
                        else {}
                    )
                    error = body.get("error", {}) if isinstance(body, dict) else {}
                    raise RuntimeError(
                        f"admin API returned HTTP {publish_response.status_code}: "
                        f"{error.get('code', 'request_failed')}"
                    )
                published = PublishResult.model_validate(publish_response.json())
                if published.slug != payload.slug:
                    raise ValueError("Admin API returned publication details for a different page")
                results.append(
                    {
                        "source_id": page.source_id,
                        "draft_id": published.draft_id,
                        "slug": published.slug,
                        "status": "published",
                        "path": published.path,
                    }
                )
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                results.append(
                    {
                        "source_id": page.source_id,
                        "slug": page.slug,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
    finally:
        if owns_client:
            http.close()
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate a synthetic legacy content export.")
    parser.add_argument("--file", required=True, help="Path to a legacy export JSON file.")
    parser.add_argument("--admin-url", default="http://127.0.0.1:8102", help="Admin API base URL.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate and map without HTTP calls.")
    mode.add_argument("--execute", action="store_true", help="Create CMS drafts and publish valid pages.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        export = load_export(args.file)
        results = migrate_export(
            export,
            admin_url=args.admin_url,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps({"page_count": len(results), "results": results}, indent=2))
    if args.execute and any(result["status"] != "published" for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
