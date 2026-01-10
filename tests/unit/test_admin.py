from fastapi.testclient import TestClient

from content_migration_gate.admin import create_app
from content_migration_gate.contracts import PublishedPage
from content_migration_gate.errors import (
    DependencyUnavailable,
    DraftNotFound,
    PublicationConflict,
)
from tests.unit.conftest import make_draft


class FakeCms:
    def __init__(self, draft=None, error=None):
        self.draft = draft or make_draft()
        self.error = error
        self.calls = []

    def create_draft(self, payload, correlation_id):
        if self.error:
            raise self.error
        from content_migration_gate.contracts import DraftResponse
        self.draft = DraftResponse(**payload, draft_id=self.draft.draft_id, status="draft")
        return self.draft

    def get_draft(self, draft_id, correlation_id):
        self.calls.append((draft_id, correlation_id))
        if self.error:
            raise self.error
        return self.draft

    def mark_published(self, draft_id, correlation_id):
        if self.error:
            raise self.error
        if self.draft.draft_id != draft_id:
            raise DraftNotFound(draft_id)
        self.draft = self.draft.model_copy(update={"status": "published"})
        return self.draft

    def close(self):
        pass


class FakeSite:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def publish(self, payload, correlation_id):
        self.calls.append((payload, correlation_id))
        if self.error:
            raise self.error
        return PublishedPage(**payload.model_dump(), status="published")

    def close(self):
        pass


def test_valid_draft_is_published_and_correlation_id_propagates() -> None:
    cms, site = FakeCms(), FakeSite()
    with TestClient(create_app(cms, site)) as client:
        response = client.post(
            "/v1/drafts/draft-test-001/publish",
            headers={"X-Correlation-ID": "run-42"},
        )
    assert response.status_code == 200
    assert response.json()["path"] == "/v1/pages/test-page"
    assert cms.calls == [("draft-test-001", "run-42")]
    assert site.calls[0][1] == "run-42"
    assert cms.draft.status == "published"
    assert response.headers["X-Correlation-ID"] == "run-42"


def test_restricted_content_is_not_published() -> None:
    cms = FakeCms(draft=make_draft(title="Internal-only page"))
    site = FakeSite()
    with TestClient(create_app(cms, site)) as client:
        response = client.post("/v1/drafts/draft-test-001/publish")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "content_validation_failed"
    assert site.calls == []


def test_draft_not_found_maps_to_404() -> None:
    with TestClient(create_app(FakeCms(error=DraftNotFound("missing")), FakeSite())) as client:
        response = client.post("/v1/drafts/missing/publish")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "draft_not_found"


def test_cms_outage_maps_to_502() -> None:
    with TestClient(create_app(FakeCms(error=DependencyUnavailable()), FakeSite())) as client:
        response = client.post("/v1/drafts/draft-test-001/publish")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "cms_dependency_failure"


def test_site_outage_maps_to_502_after_validation() -> None:
    with TestClient(create_app(FakeCms(), FakeSite(error=DependencyUnavailable()))) as client:
        response = client.post("/v1/drafts/draft-test-001/publish")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "site_dependency_failure"


def test_slug_conflict_maps_to_409() -> None:
    with TestClient(create_app(FakeCms(), FakeSite(error=PublicationConflict("conflict")))) as client:
        response = client.post("/v1/drafts/draft-test-001/publish")
    assert response.status_code == 409


def test_invalid_correlation_id_is_rejected() -> None:
    with TestClient(create_app(FakeCms(), FakeSite())) as client:
        response = client.post(
            "/v1/drafts/draft-test-001/publish",
            headers={"X-Correlation-ID": "bad id with spaces"},
        )
    assert response.status_code == 400


def test_cms_status_failure_is_reported_after_site_publish() -> None:
    class FailingStatusCms(FakeCms):
        def mark_published(self, draft_id, correlation_id):
            raise DependencyUnavailable("CMS status endpoint unavailable")

    site = FakeSite()
    with TestClient(create_app(FailingStatusCms(), site)) as client:
        response = client.post("/v1/drafts/draft-test-001/publish")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "cms_status_update_failure"
    assert len(site.calls) == 1


def test_missing_cms_record_during_status_update_maps_to_502() -> None:
    class MissingStatusCms(FakeCms):
        def mark_published(self, draft_id, correlation_id):
            raise DraftNotFound(draft_id)

    site = FakeSite()
    with TestClient(create_app(MissingStatusCms(), site)) as client:
        response = client.post("/v1/drafts/draft-test-001/publish")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "cms_status_update_failure"


def test_migration_endpoint_creates_cms_draft_then_publishes() -> None:
    cms, site = FakeCms(), FakeSite()
    payload = {
        "source_reference": "tilda:new-page",
        "slug": "new-page",
        "title": "New page",
        "blocks": [{"type": "paragraph", "text": "Migrated content"}],
    }
    with TestClient(create_app(cms, site)) as client:
        response = client.post("/v1/migrations", json=payload, headers={"X-Correlation-ID": "migration-88"})
    assert response.status_code == 200
    assert response.json()["slug"] == "new-page"
    assert cms.draft.source_reference == "tilda:new-page"
    assert cms.draft.status == "published"
    assert site.calls[0][1] == "migration-88"


def test_migration_endpoint_maps_source_conflict_to_409() -> None:
    cms = FakeCms(error=PublicationConflict("source conflict"))
    with TestClient(create_app(cms, FakeSite())) as client:
        response = client.post(
            "/v1/migrations",
            json={
                "source_reference": "tilda:new-page",
                "slug": "new-page",
                "title": "New page",
                "blocks": [{"type": "paragraph", "text": "Migrated content"}],
            },
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_reference_conflict"
