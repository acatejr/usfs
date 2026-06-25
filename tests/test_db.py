"""Tests for usfs.db and usfs.schema.

The default suite is DB-free: it exercises the provider→column mapping, the URL
normalization, and the USFSDocument schema. The integration test at the bottom
is skipped unless DATABASE_URL points at a Postgres with pgvector available.
"""

import os

import pytest

from usfs import config, db
from usfs.schema import USFSDocument


# --- Pure logic (no database needed) --------------------------------------

def test_embedding_column_map_has_both_providers():
    assert db.EMBEDDING_COLUMN["local"] == "embedding_local"
    assert db.EMBEDDING_COLUMN["anthropic"] == "embedding_voyage"


def test_active_embedding_column_follows_provider(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "local")
    assert db.active_embedding_column() == "embedding_local"

    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    assert db.active_embedding_column() == "embedding_voyage"


def test_active_embedding_column_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "bogus")
    with pytest.raises(RuntimeError):
        db.active_embedding_column()


def test_get_db_url_uses_psycopg_driver(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://u:p@localhost/usfs")
    assert db.get_db_url() == "postgresql+psycopg://u:p@localhost/usfs"


# --- Schema (no database needed) ------------------------------------------

def test_embedding_text_prefers_summary():
    doc = USFSDocument(
        id="x", title="A Dataset", description="long raw description",
        summary="short summary", keywords=["fire"], topics=["wildfire"],
    )
    text = doc.to_embedding_text()
    assert "short summary" in text
    assert "long raw description" not in text
    assert "Keywords: fire" in text
    assert "Topics: wildfire" in text


def test_embedding_text_falls_back_to_source_fields():
    doc = USFSDocument(id="x", title="T", abstract="the abstract")
    assert "the abstract" in doc.to_embedding_text()


def test_from_raw_preserves_unknown_keys_in_raw():
    rec = {"id": "x", "title": "T", "src": "rda", "extra": 1}
    doc = USFSDocument.from_raw(rec)
    assert doc.raw["extra"] == 1


# --- Integration (requires a live Postgres + pgvector) --------------------

@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; skipping live Postgres test",
)
def test_schema_init_and_roundtrip():
    from sqlalchemy import delete, select

    db.init_schema()  # idempotent: creates extensions, table, indexes

    doc = USFSDocument(id="test-db-roundtrip", src="test", title="Roundtrip Title",
                       raw={"hello": "world"})
    record = db.DocumentRecord.from_usfs_document(doc)

    with db.get_session() as session:
        session.merge(record)
        session.commit()

        fetched = session.get(db.DocumentRecord, "test-db-roundtrip")
        assert fetched.title == "Roundtrip Title"
        assert fetched.raw == {"hello": "world"}

        session.execute(
            delete(db.DocumentRecord).where(db.DocumentRecord.id == "test-db-roundtrip")
        )
        session.commit()
