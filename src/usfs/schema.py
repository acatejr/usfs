"""
The ``USFSDocument`` schema — one validated, uniform view over the three
intentionally-ragged source shapes.

The harvest catalog stores records with source-specific keys (FSGeodata has
``abstract``/``purpose``/``lineage``; GDD/RDA have ``description``/``themes``).
``USFSDocument`` normalizes those into a single pydantic model with optional
fields, plus the AI-enrichment fields filled later. ``to_embedding_text`` builds
the string that gets embedded, preferring the enriched ``summary`` when present.
"""

from pydantic import BaseModel, Field


class USFSDocument(BaseModel):
    """A normalized catalog record.

    Source-specific and enrichment fields are all optional, so the same model
    represents a record at every pipeline stage (loaded, enriched, embedded).
    The original source dict is preserved in ``raw``.
    """

    id: str
    src: str = ""
    title: str = ""
    keywords: list[str] = Field(default_factory=list)

    # Source-specific narrative fields (optional; depends on src).
    abstract: str | None = None
    purpose: str | None = None
    description: str | None = None
    themes: list[str] = Field(default_factory=list)
    lineage: list[dict] = Field(default_factory=list)

    # AI enrichment (filled by the enrich phase).
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    data_type: str | None = None
    quality_flags: dict | None = None

    # The untouched source record.
    raw: dict = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, rec: dict) -> "USFSDocument":
        """Build a document from a raw catalog record dict.

        Unknown keys are ignored by the typed fields but retained in ``raw`` so
        nothing is lost.
        """
        return cls(
            id=rec["id"],
            src=rec.get("src", ""),
            title=rec.get("title", ""),
            keywords=rec.get("keywords") or [],
            abstract=rec.get("abstract"),
            purpose=rec.get("purpose"),
            description=rec.get("description"),
            themes=rec.get("themes") or [],
            lineage=rec.get("lineage") or [],
            summary=rec.get("summary"),
            topics=rec.get("topics") or [],
            data_type=rec.get("data_type"),
            quality_flags=rec.get("quality_flags"),
            raw=rec,
        )

    def to_embedding_text(self) -> str:
        """Assemble the text to embed for this document.

        Prefers the AI-generated ``summary`` when available; otherwise falls
        back to the source narrative fields. Title, keywords, and normalized
        topics are always appended for lexical signal.
        """
        parts = [self.title]
        if self.summary:
            parts.append(self.summary)
        else:
            parts.extend(p for p in (self.abstract, self.purpose, self.description) if p)
        if self.keywords:
            parts.append("Keywords: " + ", ".join(self.keywords))
        if self.topics:
            parts.append("Topics: " + ", ".join(self.topics))
        return "\n".join(p for p in parts if p).strip()
