"""
Postgres + pgvector storage via SQLAlchemy.

A single ORM model, ``DocumentRecord`` (table ``inventory``), holds each record's
raw source dict, its AI-enrichment fields, and its embeddings. Embeddings live
in two fixed-width columns so the local (fastembed) and cloud (Voyage) providers
can coexist without a migration; each has its own HNSW cosine index.

``get_engine`` / ``get_session`` are the entry points other modules use;
``init_schema`` creates the required extensions and the table + indexes.
"""

from functools import cache

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, String, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from . import config


class Base(DeclarativeBase):
    pass


# Column each provider writes to, keyed by config.PROVIDER. Centralised here so
# the embedding/search code never branches on the provider name itself.
EMBEDDING_COLUMN = {
    "local": "embedding_local",
    "anthropic": "embedding_voyage",
    # Verde is an LLM-only proxy; it reuses local fastembed for embeddings.
    "verde": "embedding_local",
}

# Postgres extensions the schema relies on (pgvector + PostGIS stack).
EXTENSIONS = (
    "vector",
    "postgis",
    "postgis_topology",
    "fuzzystrmatch",
    "postgis_tiger_geocoder",
)


class DocumentRecord(Base):
    """ORM mapping for one normalized inventory record."""

    __tablename__ = "inventory"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    src: Mapped[str] = mapped_column(String, nullable=False, default="")
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Enrichment (NULL until the enrich phase runs).
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    data_type: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Index (NULL until the embed phase runs).
    embed_text: Mapped[str | None] = mapped_column(String, nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_local: Mapped[list[float] | None] = mapped_column(
        Vector(config.LOCAL_EMBED_DIM), nullable=True
    )
    embedding_voyage: Mapped[list[float] | None] = mapped_column(
        Vector(config.VOYAGE_EMBED_DIM), nullable=True
    )

    __table_args__ = (
        Index(
            "inventory_embedding_local_idx",
            "embedding_local",
            postgresql_using="hnsw",
            postgresql_ops={"embedding_local": "vector_cosine_ops"},
        ),
        Index(
            "inventory_embedding_voyage_idx",
            "embedding_voyage",
            postgresql_using="hnsw",
            postgresql_ops={"embedding_voyage": "vector_cosine_ops"},
        ),
        Index("inventory_src_idx", "src"),
    )

    @classmethod
    def from_usfs_document(
        cls, doc, embedding: list[float] | None = None, column: str | None = None
    ) -> "DocumentRecord":
        """Build a record from a USFSDocument, optionally with an embedding.

        Args:
            doc: A ``schema.USFSDocument``.
            embedding: Optional vector to store.
            column: Which embedding column to write the vector to. Defaults to
                the active provider's column.
        """
        record = cls(
            id=doc.id,
            src=doc.src,
            title=doc.title,
            raw=doc.raw,
            summary=doc.summary,
            topics=doc.topics or None,
            data_type=doc.data_type,
            quality_flags=doc.quality_flags,
        )
        if embedding is not None:
            col = column or active_embedding_column()
            record.embed_text = doc.to_embedding_text()
            setattr(record, col, embedding)
        return record


def get_db_url() -> str:
    """Return a SQLAlchemy-style URL using the psycopg 3 driver.

    Accepts the plain ``postgresql://`` form from DATABASE_URL and normalizes it
    to ``postgresql+psycopg://`` so SQLAlchemy uses psycopg 3.
    """
    url = config.require_database_url()
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@cache
def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine (created once)."""
    return create_engine(get_db_url())


def get_session() -> Session:
    """Open a new ORM session bound to the shared engine."""
    return Session(get_engine())


def init_schema() -> None:
    """Create the required extensions, the ``inventory`` table, and indexes.

    Idempotent: extensions use IF NOT EXISTS and ``create_all`` skips existing
    objects.
    """
    engine = get_engine()
    with engine.begin() as conn:
        for ext in EXTENSIONS:
            conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
    Base.metadata.create_all(engine)


def active_embedding_column() -> str:
    """Return the embedding column for the configured provider."""
    try:
        return EMBEDDING_COLUMN[config.PROVIDER]
    except KeyError:
        raise RuntimeError(
            f"Unknown USFS_PROVIDER={config.PROVIDER!r}; "
            f"expected one of {sorted(EMBEDDING_COLUMN)}"
        )

def clear_inventory_table() -> None:
    """Delete all rows from the inventory table."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM inventory"))