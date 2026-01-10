"""In-memory CMS API simulating draft creation by an editor or migration tool"""

from threading import RLock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, status

from content_migration_gate.contracts import DraftCreate, DraftResponse
from content_migration_gate.observability import install_correlation_middleware

app = FastAPI(title="Content Management API", version="1.0.0")
install_correlation_middleware(app)
_DRAFTS: dict[str, DraftResponse] = {}
_SOURCE_INDEX: dict[str, str] = {}
_LOCK = RLock()


def reset_state() -> None:
    """Reset in-memory content. Intended only for isolated tests."""
    with _LOCK:
        _DRAFTS.clear()
        _SOURCE_INDEX.clear()


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cms"}


@app.post(
    "/v1/drafts",
    response_model=DraftResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["content"],
)
def create_draft(payload: DraftCreate, response: Response) -> DraftResponse:
    """Create a draft; repeat submissions of the same source payload are idempotent."""
    payload_fingerprint = payload.model_dump(mode="json")
    with _LOCK:
        existing_id = _SOURCE_INDEX.get(payload.source_reference)
        if existing_id is not None:
            existing = _DRAFTS[existing_id]
            existing_payload = DraftCreate(
                source_reference=existing.source_reference,
                slug=existing.slug,
                title=existing.title,
                blocks=existing.blocks,
            ).model_dump(mode="json")
            if existing_payload != payload_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "source_reference_conflict",
                        "message": "The source reference already exists with different content.",
                    },
                )
            response.status_code = status.HTTP_200_OK
            return existing

        draft_id = uuid4().hex
        draft = DraftResponse(**payload.model_dump(), draft_id=draft_id)
        _DRAFTS[draft_id] = draft
        _SOURCE_INDEX[payload.source_reference] = draft_id
        return draft


@app.get("/v1/drafts/{draft_id}", response_model=DraftResponse, tags=["content"])
def get_draft(draft_id: str) -> DraftResponse:
    with _LOCK:
        draft = _DRAFTS.get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@app.post("/v1/drafts/{draft_id}/mark-published", response_model=DraftResponse, tags=["content"])
def mark_draft_published(draft_id: str) -> DraftResponse:
    """Record the completed publication; repeating this operation is safe."""
    with _LOCK:
        draft = _DRAFTS.get(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if draft.status != "published":
            draft = draft.model_copy(update={"status": "published"})
            _DRAFTS[draft_id] = draft
        return draft
