"""HTTP clients enforcing contracts at service boundaries"""

from typing import Any

import httpx
from content_migration_gate.contracts import DraftResponse, PublishedPage, PublishedPageCreate
from content_migration_gate.errors import (
    DependencyContractViolation,
    DependencyRejected,
    DependencyUnavailable,
    DraftNotFound,
    PublicationConflict,
)


class ServiceClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=timeout_seconds),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, correlation_id: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["X-Correlation-ID"] = correlation_id
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.TransportError as exc:
            raise DependencyUnavailable("A downstream service could not be reached.") from exc
        if response.status_code >= 500:
            raise DependencyUnavailable("A downstream service returned a server error.")
        if response.status_code >= 400:
            raise DependencyRejected(response.status_code, f"A downstream service returned HTTP {response.status_code}.")
        return response

    @staticmethod
    def _parse(response: httpx.Response, model: type[DraftResponse] | type[PublishedPage]):
        try:
            return model.model_validate(response.json())
        except ValueError as exc:
            raise DependencyContractViolation("A downstream response violated its contract.") from exc


class CmsClient(ServiceClient):
    def get_draft(self, draft_id: str, correlation_id: str) -> DraftResponse:
        try:
            response = self._request("GET", f"/v1/drafts/{draft_id}", correlation_id)
        except DependencyRejected as exc:
            if exc.status_code == 404:
                raise DraftNotFound(draft_id) from exc
            raise
        draft = self._parse(response, DraftResponse)
        if draft.draft_id != draft_id:
            raise DependencyContractViolation("CMS returned a different draft ID than requested.")
        return draft

    def mark_published(self, draft_id: str, correlation_id: str) -> DraftResponse:
        try:
            response = self._request(
                "POST", f"/v1/drafts/{draft_id}/mark-published", correlation_id
            )
        except DependencyRejected as exc:
            if exc.status_code == 404:
                raise DraftNotFound(draft_id) from exc
            raise
        draft = self._parse(response, DraftResponse)
        if draft.draft_id != draft_id or draft.status != "published":
            raise DependencyContractViolation(
                "CMS did not confirm the published state for the requested draft."
            )
        return draft

    def create_draft(self, payload: dict[str, Any], correlation_id: str) -> DraftResponse:
        try:
            response = self._request(
                "POST", "/v1/drafts", correlation_id, json=payload
            )
        except DependencyRejected as exc:
            if exc.status_code == 409:
                raise PublicationConflict("The CMS source reference conflicts with existing data.") from exc
            raise
        return self._parse(response, DraftResponse)


class SiteClient(ServiceClient):
    def publish(self, payload: PublishedPageCreate, correlation_id: str) -> PublishedPage:
        try:
            response = self._request(
                "POST",
                "/internal/v1/pages",
                correlation_id,
                json=payload.model_dump(mode="json"),
            )
        except DependencyRejected as exc:
            if exc.status_code == 409:
                raise PublicationConflict("The destination site rejected a conflicting publication.") from exc
            raise
        page = self._parse(response, PublishedPage)
        if page.source_draft_id != payload.source_draft_id or page.slug != payload.slug:
            raise DependencyContractViolation(
                "The destination site returned a page that does not match the publication request."
            )
        return page
