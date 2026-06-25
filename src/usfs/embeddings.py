"""Embeddings generation with PostgreSQL persistence.

``EmbeddingsService`` produces vectors with the configured provider — fastembed
locally (no PyTorch) or Voyage in the cloud — and writes them to the matching
``inventory`` column via SQLAlchemy. ``embed_pending`` is the orchestrator the CLI
calls: it embeds only rows that still need a current vector, so it is resumable.
"""

from typing import List

from sqlalchemy import or_, select

from . import config
from .db import DocumentRecord, active_embedding_column, get_session
from .schema import USFSDocument

# Rows are embedded in batches this size (one model call + one DB commit each).
BATCH_SIZE = 64


class EmbeddingsService:
    """Generates embeddings with the provider chosen by config.PROVIDER."""

    def __init__(self):
        """Initialize the embedding backend for the active provider."""
        self.provider = config.PROVIDER
        self.column = active_embedding_column()

        # Verde is an LLM-only proxy, so it reuses the local fastembed backend.
        if self.provider in ("local", "verde"):
            from fastembed import TextEmbedding

            self.model_name = config.LOCAL_EMBED_MODEL
            self.embedding_dim = config.LOCAL_EMBED_DIM
            self._model = TextEmbedding(self.model_name)
            self._client = None
        elif self.provider == "anthropic":
            import voyageai

            self.model_name = config.VOYAGE_EMBED_MODEL
            self.embedding_dim = config.VOYAGE_EMBED_DIM
            self._model = None
            self._client = voyageai.Client(api_key=config.VOYAGE_API_KEY)
        else:
            raise RuntimeError(f"Unknown USFS_PROVIDER={self.provider!r}")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        if self.provider in ("local", "verde"):
            return [emb.tolist() for emb in self._model.embed(texts)]
        # Voyage: input_type="document" optimises vectors for a retrieval corpus.
        result = self._client.embed(
            texts, model=self.model_name, input_type="document"
        )
        return result.embeddings

    def embed_text(self, text: str) -> List[float]:
        """Generate an embedding for a single text."""
        return self.embed_texts([text])[0]

    def embed_batch(self, docs: List[USFSDocument]) -> List[List[float]]:
        """Generate embeddings for multiple documents."""
        return self.embed_texts([doc.to_embedding_text() for doc in docs])

    def store_in_postgres(
        self, docs: List[USFSDocument], embeddings: List[List[float]]
    ) -> int:
        """Upsert documents together with their embeddings.

        Convenience for a combined load+embed; the staged pipeline uses
        ``embed_pending`` instead.
        """
        with get_session() as session:
            for doc, embedding in zip(docs, embeddings):
                record = DocumentRecord.from_usfs_document(
                    doc, embedding, column=self.column
                )
                record.embed_model = self.model_name
                session.merge(record)  # upsert on primary key
            session.commit()
        return len(docs)


def _row_to_document(record: DocumentRecord) -> USFSDocument:
    """Reconstruct a USFSDocument from a stored row, including enrichment."""
    doc = USFSDocument.from_raw(record.raw)
    doc.summary = record.summary
    doc.topics = record.topics or []
    return doc


def embed_pending(batch_size: int = BATCH_SIZE) -> int:
    """Embed every row lacking a current vector for the active provider.

    A row is (re)embedded when its provider column is NULL or its ``embed_model``
    differs from the active model, so the phase is resumable and cheap to re-run.

    Returns:
        The number of rows embedded.
    """
    service = EmbeddingsService()
    col = getattr(DocumentRecord, service.column)

    with get_session() as session:
        stmt = select(DocumentRecord).where(
            or_(col.is_(None), DocumentRecord.embed_model.is_distinct_from(service.model_name))
        )
        rows = session.scalars(stmt).all()
        if not rows:
            print("Nothing to embed; all rows current.")
            return 0

        print(f"Embedding {len(rows)} rows with {service.model_name} -> {service.column} ...")
        total = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            docs = [_row_to_document(r) for r in batch]
            texts = [d.to_embedding_text() for d in docs]
            vectors = service.embed_texts(texts)

            for record, text, vector in zip(batch, texts, vectors):
                setattr(record, service.column, vector)
                record.embed_text = text
                record.embed_model = service.model_name
            session.commit()

            total += len(batch)
            print(f"   {total}/{len(rows)}")

    return total
