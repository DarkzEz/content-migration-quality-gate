from fastapi.testclient import TestClient

from content_migration_gate.cms import app, reset_state


def payload(source_reference: str = "tilda:page-a", text: str = "Page content") -> dict:
    return {
        "source_reference": source_reference,
        "slug": "page-a",
        "title": "Page A",
        "blocks": [{"type": "paragraph", "text": text}],
    }


def setup_function() -> None:
    reset_state()


def test_create_and_read_draft() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/drafts", json=payload())
        assert response.status_code == 201
        draft = response.json()
        assert draft["status"] == "draft"
        fetched = client.get(f"/v1/drafts/{draft['draft_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["title"] == "Page A"


def test_repeated_same_source_payload_is_idempotent() -> None:
    with TestClient(app) as client:
        first = client.post("/v1/drafts", json=payload())
        second = client.post("/v1/drafts", json=payload())
        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["draft_id"] == second.json()["draft_id"]


def test_same_source_reference_with_changed_payload_conflicts() -> None:
    with TestClient(app) as client:
        first = client.post("/v1/drafts", json=payload())
        changed = client.post("/v1/drafts", json=payload(text="Changed content"))
        assert first.status_code == 201
        assert changed.status_code == 409


def test_missing_draft_returns_404() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/drafts/not-found")
    assert response.status_code == 404


def test_correlation_id_is_echoed() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Correlation-ID": "check-123"})
    assert response.headers["X-Correlation-ID"] == "check-123"


def test_mark_published_updates_status_idempotently() -> None:
    with TestClient(app) as client:
        created = client.post("/v1/drafts", json=payload())
        draft_id = created.json()["draft_id"]
        first = client.post(f"/v1/drafts/{draft_id}/mark-published")
        second = client.post(f"/v1/drafts/{draft_id}/mark-published")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "published"
    assert second.json()["status"] == "published"
