"""Black-box tests against the real local/Compose service stack."""

import os
from uuid import uuid4

import httpx
import pytest

from content_migration_gate.contracts import DraftCreate

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.getenv("CONTENT_GATE_E2E") != "1", reason="service stack is not enabled"),
]
CMS_URL = os.getenv("CMS_BASE_URL", "http://127.0.0.1:8101").rstrip("/")
ADMIN_URL = os.getenv("ADMIN_BASE_URL", "http://127.0.0.1:8102").rstrip("/")
SITE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8103").rstrip("/")


def create_payload(*, blocked: bool = False) -> DraftCreate:
    unique = uuid4().hex[:10]
    text = "internal-only synthetic text" if blocked else "A migrated, synthetic content block"
    return DraftCreate(
        source_reference=f"e2e:{unique}",
        slug=f"e2e-page-{unique}",
        title="End-to-end migration check",
        blocks=[{"type": "paragraph", "text": text}],
    )


def test_draft_passes_admin_validation_and_appears_on_site() -> None:
    payload = create_payload()
    correlation_id = f"e2e-{uuid4().hex[:12]}"
    with httpx.Client(timeout=5.0) as client:
        cms_response = client.post(
            f"{CMS_URL}/v1/drafts",
            json=payload.model_dump(mode="json"),
            headers={"X-Correlation-ID": correlation_id},
        )
        assert cms_response.status_code == 201
        draft = cms_response.json()

        publish_response = client.post(
            f"{ADMIN_URL}/v1/drafts/{draft['draft_id']}/publish",
            headers={"X-Correlation-ID": correlation_id},
        )
        assert publish_response.status_code == 200, publish_response.text
        assert publish_response.headers["X-Correlation-ID"] == correlation_id
        published_draft = client.get(f"{CMS_URL}/v1/drafts/{draft['draft_id']}")
        assert published_draft.status_code == 200
        assert published_draft.json()["status"] == "published"

        page_response = client.get(f"{SITE_URL}/v1/pages/{payload.slug}")
        assert page_response.status_code == 200
        assert page_response.json()["title"] == payload.title
        assert page_response.json()["source_draft_id"] == draft["draft_id"]


def test_restricted_draft_is_not_published() -> None:
    payload = create_payload(blocked=True)
    with httpx.Client(timeout=5.0) as client:
        publish_response = client.post(
            f"{ADMIN_URL}/v1/migrations",
            json=payload.model_dump(mode="json"),
        )
        assert publish_response.status_code == 422
        assert publish_response.json()["error"]["code"] == "content_validation_failed"

        site_response = client.get(f"{SITE_URL}/v1/pages/{payload.slug}")
        assert site_response.status_code == 404
