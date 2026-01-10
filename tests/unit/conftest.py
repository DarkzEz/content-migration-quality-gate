from content_migration_gate.contracts import ContentBlock, DraftResponse


def make_block(text: str = "A short synthetic paragraph") -> ContentBlock:
    return ContentBlock(type="paragraph", text=text)


def make_draft(
    *,
    draft_id: str = "draft-test-001",
    source_reference: str = "tilda:test-page",
    slug: str = "test-page",
    title: str = "Test page",
    blocks: list[ContentBlock] | None = None,
) -> DraftResponse:
    return DraftResponse(
        draft_id=draft_id,
        source_reference=source_reference,
        slug=slug,
        title=title,
        blocks=blocks or [make_block()],
        status="draft",
    )
