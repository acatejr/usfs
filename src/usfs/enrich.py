"""
AI enrichment pass over the catalog.

For each un-enriched row, an LLM (config.PROVIDER) reads the raw source fields
and returns a compact, uniform summary plus normalized topics and a data-type
label. Quality flags are computed deterministically in Python (no LLM) so they
stay cheap and reliable.

Only rows with a NULL ``summary`` are processed, so the phase is resumable. On a
parse failure the row is left untouched (summary stays NULL) so it is retried on
the next run rather than being stuck with a blank summary.
"""

import json

import click
from sqlalchemy import select

from .db import DocumentRecord, get_session
from .providers import get_llm

SYSTEM_PROMPT = (
    "You are a metadata librarian for a U.S. Forest Service dataset catalog. "
    "Given a dataset's raw metadata, respond with a single JSON object and "
    "nothing else."
)

INSTRUCTION = """\
Return a JSON object with exactly these keys:
  "summary": one or two plain-language sentences describing what the dataset is.
  "topics": 3-7 short lowercase topic tags (controlled, reusable across datasets,
            e.g. "wildfire", "hydrology", "timber harvest", "boundaries").
  "data_type": one of "geospatial vector", "raster", "map service", "tabular",
            "document", or "other".
Respond with only the JSON object."""


def build_source_text(raw: dict) -> str:
    """Flatten a raw source record into the text shown to the LLM."""
    parts = [f"Title: {raw.get('title', '')}", f"Source: {raw.get('src', '')}"]
    for field in ("abstract", "purpose", "description"):
        value = raw.get(field)
        if value:
            parts.append(f"{field.capitalize()}: {value}")
    keywords = raw.get("keywords") or []
    if keywords:
        parts.append("Keywords: " + ", ".join(keywords))
    return "\n".join(parts)


def compute_quality_flags(raw: dict) -> dict:
    """Derive completeness flags from the raw record (no LLM)."""
    has_narrative = bool(
        raw.get("abstract") or raw.get("description") or raw.get("purpose")
    )
    return {
        "missing_narrative": not has_narrative,
        "missing_keywords": not (raw.get("keywords") or []),
        "short_title": len((raw.get("title") or "").strip()) < 10,
    }


def _parse_llm_json(text: str) -> dict:
    """Extract the JSON object from an LLM reply; {} on failure."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def enrich_catalog() -> int:
    """Enrich all rows that have no summary yet.

    Returns:
        The number of rows enriched.
    """
    llm = get_llm()

    with get_session() as session:
        rows = session.scalars(
            select(DocumentRecord)
            .where(DocumentRecord.summary.is_(None))
            .order_by(DocumentRecord.id)
        ).all()

        if not rows:
            click.echo("Nothing to enrich; all rows have summaries.")
            return 0

        click.echo(f"Enriching {len(rows)} rows ...")
        total = 0
        for record in rows:
            prompt = f"{build_source_text(record.raw)}\n\n{INSTRUCTION}"
            parsed = _parse_llm_json(llm.complete(prompt, system=SYSTEM_PROMPT))

            summary = parsed.get("summary")
            if not summary:
                # Parse failed / no summary: leave NULL so it retries next run.
                continue

            topics = parsed.get("topics")
            topics = topics if isinstance(topics, list) else []

            record.summary = summary
            record.topics = [str(t).strip().lower() for t in topics] or None
            record.data_type = parsed.get("data_type") or "other"
            record.quality_flags = compute_quality_flags(record.raw)
            session.commit()

            total += 1
            if total % 25 == 0:
                click.echo(f"   {total}/{len(rows)}")

        click.echo(f"   Enriched {total}/{len(rows)} rows.")

    return total
