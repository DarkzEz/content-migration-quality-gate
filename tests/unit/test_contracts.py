import pytest
from pydantic import ValidationError

from content_migration_gate.contracts import ContentBlock, DraftCreate, LegacyBlock, LegacyPage


def test_content_paragraph_is_valid() -> None:
    block = ContentBlock(type="paragraph", text="Sample content")
    assert block.text == "Sample content"


def test_image_requires_asset_url_and_alt() -> None:
    with pytest.raises(ValidationError):
        ContentBlock(type="image", alt="A photo")


def test_image_rejects_text_fields() -> None:
    with pytest.raises(ValidationError):
        ContentBlock(
            type="image",
            text="not valid for image",
            asset_url="https://assets.example.test/a.jpg",
            alt="A photo",
        )


def test_text_block_rejects_image_fields() -> None:
    with pytest.raises(ValidationError):
        ContentBlock(
            type="paragraph",
            text="A paragraph",
            asset_url="https://assets.example.test/a.jpg",
            alt="unexpected",
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DraftCreate(
            source_reference="tilda:test",
            slug="test-page",
            title="Test",
            blocks=[{"type": "paragraph", "text": "Hello"}],
            published=True,
        )


def test_slug_must_be_url_friendly() -> None:
    with pytest.raises(ValidationError):
        DraftCreate(
            source_reference="tilda:test",
            slug="Not A Slug",
            title="Test",
            blocks=[{"type": "paragraph", "text": "Hello"}],
        )


def test_legacy_image_requires_alternative_text() -> None:
    with pytest.raises(ValidationError):
        LegacyBlock(type="image", asset_url="https://assets.example.test/a.jpg")


def test_legacy_page_rejects_empty_blocks() -> None:
    with pytest.raises(ValidationError):
        LegacyPage(source_id="page-1", slug="page-1", title="Page", blocks=[])


def test_style_color_must_be_hex() -> None:
    with pytest.raises(ValidationError):
        ContentBlock(
            type="heading",
            text="Title",
            style={"color": "blue"},
        )
