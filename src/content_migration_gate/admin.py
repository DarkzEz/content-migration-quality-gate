"""Admin/publishing API: load CMS drafts, apply policy validation, publish to the site."""

import os
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from content_migration_gate.clients import CmsClient, SiteClient
from content_migration_gate.contracts import DraftCreate, DraftResponse, PublishResult, PublishedPageCreate
from content_migration_gate.errors import (
    DependencyError,
    DraftNotFound,
    PublicationConflict,
)
from content_migration_gate.observability import install_correlation_middleware


class CmsClientProtocol(Protocol):
    def create_draft(self, payload: dict, correlation_id: str) -> DraftResponse: ...
    def get_draft(self, draft_id: str, correlation_id: str) -> DraftResponse: ...
    def mark_published(self, draft_id: str, correlation_id: str) -> DraftResponse: ...
    def close(self) -> None: ...


class SiteClientProtocol(Protocol):
    def publish(self, payload: PublishedPageCreate, correlation_id: str): ...
    def close(self) -> None: ...


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list[str] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


def _blocked_terms() -> tuple[str, ...]:
    raw_terms = os.getenv("BLOCKED_TERMS", "do-not-publish,internal-only")
    return tuple(term.strip().casefold() for term in raw_terms.split(",") if term.strip())


def validate_content(draft: DraftResponse) -> list[str]:
    """Apply illustrative publication policy; terms are configurable for the demo."""
    terms = _blocked_terms()
    issues: list[str] = []
    fields = [("title", draft.title)]
    for index, block in enumerate(draft.blocks):
        if block.text is not None:
            fields.append((f"blocks[{index}].text", block.text))
        if block.alt is not None:
            fields.append((f"blocks[{index}].alt", block.alt))

    for field_name, value in fields:
        folded_value = value.casefold()
        for term in terms:
            if term in folded_value:
                issues.append(f"{field_name} contains a restricted demo term: {term}")
    return issues


def create_app(
    cms_client: CmsClientProtocol | None = None,
    site_client: SiteClientProtocol | None = None,
) -> FastAPI:
    injected_cms = cms_client
    injected_site = site_client

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned_clients: list[CmsClient | SiteClient] = []
        app.state.cms_client = injected_cms
        app.state.site_client = injected_site
        if app.state.cms_client is None:
            app.state.cms_client = CmsClient(
                os.getenv("CMS_BASE_URL", "http://cms:8000"),
                timeout_seconds=float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "2.0")),
            )
            owned_clients.append(app.state.cms_client)
        if app.state.site_client is None:
            app.state.site_client = SiteClient(
                os.getenv("SITE_BASE_URL", "http://site:8000"),
                timeout_seconds=float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "2.0")),
            )
            owned_clients.append(app.state.site_client)
        try:
            yield
        finally:
            for client in owned_clients:
                client.close()

    app = FastAPI(title="Content Admin and Publishing API", version="1.0.0", lifespan=lifespan)
    install_correlation_middleware(app)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "correlation_id": request.state.correlation_id,
                }
            },
        )

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "admin"}

    @app.post("/v1/migrations", response_model=PublishResult, tags=["migration"])
    def migrate_content(payload: DraftCreate, request: Request) -> PublishResult:
        """Accept mapped legacy content and orchestrate CMS validation/publication."""
        correlation_id = request.state.correlation_id
        try:
            created_draft = request.app.state.cms_client.create_draft(
                payload.model_dump(mode="json"), correlation_id
            )
        except PublicationConflict as exc:
            raise ApiError(
                409,
                "source_reference_conflict",
                "The source reference already exists with different content.",
            ) from exc
        except DependencyError as exc:
            raise ApiError(
                502,
                "cms_create_failure",
                "The CMS could not accept the migration payload.",
            ) from exc

        created_payload = DraftCreate(
            source_reference=created_draft.source_reference,
            slug=created_draft.slug,
            title=created_draft.title,
            blocks=created_draft.blocks,
        ).model_dump(mode="json")
        if created_payload != payload.model_dump(mode="json"):
            raise ApiError(
                502,
                "cms_create_contract_violation",
                "The CMS returned a draft that does not match the migration payload.",
            )
        return publish_draft(created_draft.draft_id, request)

    @app.post(
        "/v1/drafts/{draft_id}/publish",
        response_model=PublishResult,
        tags=["publishing"],
    )
    def publish_draft(draft_id: str, request: Request) -> PublishResult:
        correlation_id = request.state.correlation_id
        try:
            draft = request.app.state.cms_client.get_draft(draft_id, correlation_id)
        except DraftNotFound as exc:
            raise ApiError(404, "draft_not_found", "The requested draft does not exist.") from exc
        except DependencyError as exc:
            raise ApiError(
                502,
                "cms_dependency_failure",
                "The CMS could not provide a valid draft response.",
            ) from exc

        issues = validate_content(draft)
        if issues:
            raise ApiError(
                422,
                "content_validation_failed",
                "The draft did not pass publication policy checks.",
                issues,
            )

        publish_payload = PublishedPageCreate(
            source_draft_id=draft.draft_id,
            slug=draft.slug,
            title=draft.title,
            blocks=draft.blocks,
        )
        try:
            page = request.app.state.site_client.publish(publish_payload, correlation_id)
        except PublicationConflict as exc:
            raise ApiError(409, "publication_conflict", str(exc)) from exc
        except DependencyError as exc:
            raise ApiError(
                502,
                "site_dependency_failure",
                "The destination site could not publish the validated page.",
            ) from exc

        try:
            confirmed_draft = request.app.state.cms_client.mark_published(
                draft.draft_id, correlation_id
            )
            if confirmed_draft.draft_id != draft.draft_id or confirmed_draft.status != "published":
                raise ApiError(
                    502,
                    "cms_status_update_failure",
                    "The CMS did not confirm the published state.",
                )
        except (DependencyError, DraftNotFound) as exc:
            raise ApiError(
                502,
                "cms_status_update_failure",
                "The page is on the destination site, but the CMS status could not be confirmed.",
            ) from exc

        return PublishResult(
            draft_id=draft.draft_id,
            slug=page.slug,
            path=f"/v1/pages/{page.slug}",
        )

    return app


app = create_app()
