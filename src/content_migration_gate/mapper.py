"""Convert a synthetic legacy page export into the destination CMS content model"""

from content_migration_gate.contracts import (
    ContentBlock,
    DraftCreate,
    LegacyPage,
    TextStyle,
)

LEGACY_TYPE_MAP = {
    "title": "heading",
    "text": "paragraph",
    "image": "image",
    "button": "button",
}


def map_legacy_page(page: LegacyPage) -> DraftCreate:
    """Map the supported legacy block subset while preserving useful formatting"""

    mapped_blocks: list[ContentBlock] = []
    for block in page.blocks:
        destination_type = LEGACY_TYPE_MAP[block.type]
        if block.type == "image":
            mapped_blocks.append(
                ContentBlock(
                    type="image",
                    asset_url=block.asset_url,
                    alt=block.alt_text,
                )
            )
            continue

        legacy_style = block.style
        style = None
        if legacy_style is not None and any(
            value is not None
            for value in (legacy_style.family, legacy_style.size, legacy_style.color)
        ):
            style = TextStyle(
                font_family=legacy_style.family,
                font_size_pt=legacy_style.size,
                color=legacy_style.color,
            )

        mapped_blocks.append(
            ContentBlock(type=destination_type, text=block.text, style=style)
        )

    return DraftCreate(
        source_reference=f"tilda:{page.source_id}",
        slug=page.slug,
        title=page.title,
        blocks=mapped_blocks,
    )
