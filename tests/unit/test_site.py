from fastapi.testclient import TestClient

from content_migration_gate.site import app, reset_state


def page_payload(draft_id: str = "draft-1", slug: str = "page-a") -> dict:
    return {
        "source_draft_id": draft_id,
        "slug": slug,
        "title": "A published page",
        "blocks": [{"type": "paragraph", "text": "Published content"}],
    }


def setup_function() -> None:
    reset_state()


def test_publish_and_read_page() -> None:
    with TestClient(app) as client:
        published = client.post("/internal/v1/pages", json=page_payload())
        public = client.get("/v1/pages/page-a")
    assert published.status_code == 201
    assert public.status_code == 200
    assert public.json()["status"] == "published"


def test_republishing_same_draft_is_idempotent() -> None:
    with TestClient(app) as client:
        first = client.post("/internal/v1/pages", json=page_payload())
        second = client.post("/internal/v1/pages", json=page_payload())
    assert first.status_code == 201
    assert second.status_code == 200


def test_slug_collision_from_different_draft_is_rejected() -> None:
    with TestClient(app) as client:
        client.post("/internal/v1/pages", json=page_payload())
        collision = client.post("/internal/v1/pages", json=page_payload(draft_id="draft-2"))
    assert collision.status_code == 409


def test_missing_public_page_returns_404() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/pages/does-not-exist")
    assert response.status_code == 404
