"""Strict contracts for the legacy export and the destination content platform"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
SourceReference = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TextStyle(StrictModel):
    font_family: str | None = Field(default=None, min_length=1, max_length=80)
    font_size_pt: int | None = Field(default=None, ge=8, le=72)
    color: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)


class ContentBlock(StrictModel):
    type: Literal["heading", "paragraph", "image", "button"]
    text: str | None = Field(default=None, min_length=1, max_length=10_000)
    asset_url: HttpUrl | None = None
    alt: str | None = Field(default=None, min_length=1, max_length=300)
    style: TextStyle | None = None

    @model_validator(mode="after")
    def validate_block_shape(self) -> "ContentBlock":
        if self.type == "image":
            if self.asset_url is None or self.alt is None:
                raise ValueError("image blocks require asset_url and alt")
            if self.text is not None or self.style is not None:
                raise ValueError("image blocks must not include text or text style")
            return self

        if self.text is None or not self.text.strip():
            raise ValueError(f"{self.type} blocks require non-empty text")
        if self.asset_url is not None or self.alt is not None:
            raise ValueError(f"{self.type} blocks must not include image fields")
        return self


class DraftCreate(StrictModel):
    source_reference: SourceReference
    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    blocks: list[ContentBlock] = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value


class DraftResponse(DraftCreate):
    draft_id: str = Field(min_length=1, max_length=64)
    status: Literal["draft", "published"] = "draft"


class PublishedPageCreate(StrictModel):
    source_draft_id: str = Field(min_length=1, max_length=64)
    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    blocks: list[ContentBlock] = Field(min_length=1, max_length=100)


class PublishedPage(PublishedPageCreate):
    status: Literal["published"] = "published"


class PublishResult(StrictModel):
    draft_id: str
    slug: str
    status: Literal["published"] = "published"
    path: str


class LegacyStyle(StrictModel):
    family: str | None = Field(default=None, min_length=1, max_length=80)
    size: int | None = Field(default=None, ge=8, le=72)
    color: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)


class LegacyBlock(StrictModel):
    """A small, intentionally synthetic subset of a legacy page-export format."""

    type: Literal["title", "text", "image", "button"]
    text: str | None = Field(default=None, min_length=1, max_length=10_000)
    asset_url: HttpUrl | None = None
    alt_text: str | None = Field(default=None, min_length=1, max_length=300)
    style: LegacyStyle | None = None

    @model_validator(mode="after")
    def validate_legacy_block(self) -> "LegacyBlock":
        if self.type == "image":
            if self.asset_url is None or self.alt_text is None:
                raise ValueError("legacy image blocks require asset_url and alt_text")
            if self.text is not None or self.style is not None:
                raise ValueError("legacy image blocks must not include text or style")
        else:
            if self.text is None or not self.text.strip():
                raise ValueError(f"legacy {self.type} blocks require non-empty text")
            if self.asset_url is not None or self.alt_text is not None:
                raise ValueError(f"legacy {self.type} blocks must not include image fields")
        return self


class LegacyPage(StrictModel):
    source_id: SourceReference
    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    blocks: list[LegacyBlock] = Field(min_length=1, max_length=100)


class LegacyExport(StrictModel):
    export_format: Literal["synthetic-tilda-export-v1"]
    pages: list[LegacyPage] = Field(min_length=1, max_length=1000)
