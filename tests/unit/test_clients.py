import httpx
import pytest

from content_migration_gate.clients import CmsClient, SiteClient
from content_migration_gate.contracts import PublishedPageCreate
from content_migration_gate.errors import (
    DependencyContractViolation,
    DependencyRejected,
    DependencyUnavailable,
    DraftNotFound,
    PublicationConflict,
)
from tests.unit.conftest import make_draft


def test_cms_client_validates_draft_id() -> None:
    draft = make_draft(draft_id="other-draft")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=draft.model_dump(mode="json"))
    )
    client = CmsClient("http://cms", transport=transport)
    try:
        with pytest.raises(DependencyContractViolation):
            client.get_draft("expected-draft", "corr-1")
    finally:
        client.close()


def test_cms_client_maps_404_to_draft_not_found() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, json={"detail": "missing"}))
    client = CmsClient("http://cms", transport=transport)
    try:
        with pytest.raises(DraftNotFound):
            client.get_draft("missing", "corr-2")
    finally:
        client.close()


def test_cms_client_rejects_invalid_response_contract() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"draft_id": "incomplete"}))
    client = CmsClient("http://cms", transport=transport)
    try:
        with pytest.raises(DependencyContractViolation):
            client.get_draft("incomplete", "corr-3")
    finally:
        client.close()


def test_site_client_checks_returned_slug_and_draft() -> None:
    payload = PublishedPageCreate(
        source_draft_id="draft-1",
        slug="expected-page",
        title="Expected",
        blocks=[{"type": "paragraph", "text": "Body"}],
    )
    response_data = {
        "source_draft_id": "draft-1",
        "slug": "different-page",
        "title": "Expected",
        "blocks": [{"type": "paragraph", "text": "Body"}],
        "status": "published",
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(201, json=response_data))
    client = SiteClient("http://site", transport=transport)
    try:
        with pytest.raises(DependencyContractViolation):
            client.publish(payload, "corr-4")
    finally:
        client.close()


def test_downstream_server_failure_maps_to_unavailable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"detail": "offline"}))
    client = CmsClient("http://cms", transport=transport)
    try:
        with pytest.raises(DependencyUnavailable):
            client.get_draft("draft-1", "corr-5")
    finally:
        client.close()


def test_cms_client_sends_correlation_id() -> None:
    seen = {}
    draft = make_draft()

    def handler(request):
        seen["correlation_id"] = request.headers.get("X-Correlation-ID")
        return httpx.Response(200, json=draft.model_dump(mode="json"))

    client = CmsClient("http://cms", transport=httpx.MockTransport(handler))
    try:
        client.get_draft(draft.draft_id, "corr-6")
    finally:
        client.close()
    assert seen["correlation_id"] == "corr-6"


def test_cms_conflict_maps_to_publication_conflict() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(409, json={"detail": "conflict"}))
    client = CmsClient("http://cms", transport=transport)
    try:
        with pytest.raises(PublicationConflict):
            client.create_draft({"source_reference": "tilda:a"}, "corr-7")
    finally:
        client.close()


def test_downstream_400_maps_to_rejected() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"detail": "bad"}))
    client = CmsClient("http://cms", transport=transport)
    try:
        with pytest.raises(DependencyRejected):
            client.get_draft("draft-1", "corr-8")
    finally:
        client.close()


def test_cms_client_marks_draft_published() -> None:
    published_draft = make_draft().model_copy(update={"status": "published"})
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=published_draft.model_dump(mode="json"))
    )
    client = CmsClient("http://cms", transport=transport)
    try:
        result = client.mark_published(published_draft.draft_id, "corr-mark")
    finally:
        client.close()
    assert result.status == "published"


def test_cms_client_rejects_unconfirmed_published_status() -> None:
    draft = make_draft()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=draft.model_dump(mode="json"))
    )
    client = CmsClient("http://cms", transport=transport)
    try:
        with pytest.raises(DependencyContractViolation):
            client.mark_published(draft.draft_id, "corr-mark-bad")
    finally:
        client.close()


def test_cms_client_create_draft_returns_valid_contract() -> None:
    draft = make_draft()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(201, json=draft.model_dump(mode="json"))
    )
    client = CmsClient("http://cms", transport=transport)
    try:
        result = client.create_draft(
            {
                "source_reference": draft.source_reference,
                "slug": draft.slug,
                "title": draft.title,
                "blocks": [block.model_dump(mode="json") for block in draft.blocks],
            },
            "corr-create",
        )
    finally:
        client.close()
    assert result.draft_id == draft.draft_id


def test_site_client_maps_slug_conflict() -> None:
    payload = PublishedPageCreate(
        source_draft_id="draft-1",
        slug="page-a",
        title="Page A",
        blocks=[{"type": "paragraph", "text": "Body"}],
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(409, json={"detail": "conflict"}))
    client = SiteClient("http://site", transport=transport)
    try:
        with pytest.raises(PublicationConflict):
            client.publish(payload, "corr-conflict")
    finally:
        client.close()


def test_network_error_maps_to_dependency_unavailable() -> None:
    def handler(request):
        raise httpx.ConnectError("unreachable", request=request)

    client = CmsClient("http://cms", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DependencyUnavailable):
            client.get_draft("draft-1", "corr-offline")
    finally:
        client.close()
