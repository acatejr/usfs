"""
Load the unified catalog JSON into the Postgres ``inventory`` table.

Reads ``data/usfs/usfs_catalog.json`` (the harvest artifact), validates each
record through ``USFSDocument``, and upserts the base columns. The upsert
touches only ``src``/``title``/``raw`` on conflict, so re-loading never clobbers
enrichment or embedding columns produced by later phases.
"""

from pathlib import Path

import click
from sqlalchemy.dialects.postgresql import insert

from .db import DocumentRecord, get_engine
from .lib import load_json
from .schema import USFSDocument

DEFAULT_CATALOG_PATH = "./data/usfs/usfs_catalog.json"


def load_catalog(path: str | Path = DEFAULT_CATALOG_PATH) -> int:
    """Upsert every record from the catalog JSON into the ``inventory`` table.

    Args:
        path: Path to the unified catalog JSON (a list of record dicts).

    Returns:
        The number of records upserted.
    """
    records = load_json(path)
    click.echo(f"Loading {len(records)} records from {path} ...")

    rows = [
        {"id": doc.id, "src": doc.src, "title": doc.title, "raw": doc.raw}
        for doc in (USFSDocument.from_raw(rec) for rec in records)
    ]

    stmt = insert(DocumentRecord)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "src": stmt.excluded.src,
            "title": stmt.excluded.title,
            "raw": stmt.excluded.raw,
        },
    )

    with get_engine().begin() as conn:
        conn.execute(stmt, rows)

    click.echo(f"   Upserted {len(rows)} rows into inventory.")
    return len(rows)
