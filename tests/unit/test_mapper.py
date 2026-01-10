import json
from pathlib import Path

from content_migration_gate.contracts import LegacyExport, LegacyPage
from content_migration_gate.mapper import map_legacy_page

ROOT = Path(__file__).resolve().parents[2]


def test_sample_export_maps_to_cms_content_model() -> None:
    export = LegacyExport.model_validate_json((ROOT / "examples/tilda-export.json").read_text())
    mapped = map_legacy_page(export.pages[0])

    assert mapped.source_reference == "tilda:page-about-center"
    assert mapped.slug == "about-the-center"
    assert [block.type for block in mapped.blocks] == ["heading", "paragraph", "image", "button"]
    assert mapped.blocks[0].style is not None
    assert mapped.blocks[0].style.font_size_pt == 32
    assert str(mapped.blocks[2].asset_url) == "https://assets.example.test/center-building.jpg"
    assert mapped.blocks[2].alt == "Illustrative building photograph"


def test_mapper_does_not_mutate_source_page() -> None:
    page = LegacyPage(
        source_id="source-1",
        slug="sample-page",
        title="Sample",
        blocks=[{"type": "title", "text": "Heading", "style": {"size": 24}}],
    )
    before = page.model_dump(mode="json")
    map_legacy_page(page)
    assert page.model_dump(mode="json") == before


def test_mapper_omits_empty_style() -> None:
    page = LegacyPage(
        source_id="source-2",
        slug="no-style",
        title="No style",
        blocks=[{"type": "text", "text": "Plain text"}],
    )
    mapped = map_legacy_page(page)
    assert mapped.blocks[0].style is None


def test_sample_export_is_valid_json() -> None:
    source = json.loads((ROOT / "examples/tilda-export.json").read_text())
    assert source["export_format"] == "synthetic-tilda-export-v1"
    assert len(source["pages"]) == 2
