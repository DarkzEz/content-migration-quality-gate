"""Destination-site API with a narrow internal publishing endpoint"""

from threading import RLock

from fastapi import FastAPI, HTTPException, Response, status

from content_migration_gate.contracts import PublishedPage, PublishedPageCreate
from content_migration_gate.observability import install_correlation_middleware

app = FastAPI(title="Destination Site API", version="1.0.0")
install_correlation_middleware(app)
_PAGES_BY_SLUG: dict[str, PublishedPage] = {}
_SLUG_BY_DRAFT: dict[str, str] = {}
_LOCK = RLock()


def reset_state() -> None:
    with _LOCK:
        _PAGES_BY_SLUG.clear()
        _SLUG_BY_DRAFT.clear()


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "destination-site"}


@app.post(
    "/internal/v1/pages",
    response_model=PublishedPage,
    status_code=status.HTTP_201_CREATED,
    tags=["publishing"],
)
def publish_page(payload: PublishedPageCreate, response: Response) -> PublishedPage:
    """Publish idempotently for the same draft and reject slug collisions."""
    with _LOCK:
        existing_slug = _SLUG_BY_DRAFT.get(payload.source_draft_id)
        if existing_slug is not None:
            existing = _PAGES_BY_SLUG[existing_slug]
            existing_payload = PublishedPageCreate(
                source_draft_id=existing.source_draft_id,
                slug=existing.slug,
                title=existing.title,
                blocks=existing.blocks,
            ).model_dump(mode="json")
            if existing_payload != payload.model_dump(mode="json"):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "draft_payload_conflict", "message": "Published draft changed."},
                )
            response.status_code = status.HTTP_200_OK
            return existing

        if payload.slug in _PAGES_BY_SLUG:
            raise HTTPException(
                status_code=409,
                detail={"code": "slug_conflict", "message": "The page slug is already published."},
            )

        page = PublishedPage(**payload.model_dump())
        _PAGES_BY_SLUG[payload.slug] = page
        _SLUG_BY_DRAFT[payload.source_draft_id] = payload.slug
        return page


@app.get("/v1/pages/{slug}", response_model=PublishedPage, tags=["pages"])
def get_page(slug: str) -> PublishedPage:
    with _LOCK:
        page = _PAGES_BY_SLUG.get(slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page
