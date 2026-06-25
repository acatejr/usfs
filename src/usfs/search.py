"""
Semantic search, RAG question-answering, and duplicate detection.

All three operate on the active provider's embedding column (db.active_embedding_column),
using pgvector cosine distance against the HNSW index. ``embed`` must have been
run first so the column is populated.
"""

from sqlalchemy import select, text

from .db import DocumentRecord, active_embedding_column, get_engine, get_session
from .embeddings import EmbeddingsService
from .providers import get_llm


def search(query: str, limit: int = 10) -> list[dict]:
    """Return the datasets most semantically similar to ``query``.

    Returns:
        Dicts with ``id``, ``title``, ``src``, ``summary``, and ``score``
        (cosine similarity in [0, 1], higher is closer), best first.
    """
    col = getattr(DocumentRecord, active_embedding_column())
    query_vec = EmbeddingsService().embed_text(query)

    distance = col.cosine_distance(query_vec)
    stmt = (
        select(DocumentRecord, (1 - distance).label("score"))
        .where(col.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    with get_session() as session:
        return [
            {
                "id": rec.id,
                "title": rec.title,
                "src": rec.src,
                "summary": rec.summary,
                "score": score,
            }
            for rec, score in session.execute(stmt).all()
        ]


def answer(query: str, k: int = 8) -> dict:
    """Answer a question over the catalog with retrieval-augmented generation.

    Returns:
        A dict with ``answer`` (the LLM's text) and ``sources`` (retrieved rows).
    """
    hits = search(query, limit=k)
    if not hits:
        return {"answer": "No datasets are indexed yet. Run embed first.", "sources": []}

    context = "\n\n".join(
        f"[{i + 1}] {h['title']} (src: {h['src']})\n{h['summary'] or ''}"
        for i, h in enumerate(hits)
    )
    prompt = (
        f"Question: {query}\n\n"
        f"Catalog excerpts:\n{context}\n\n"
        "Answer the question using only the datasets above. Cite the datasets "
        "you rely on by their title. If none are relevant, say so."
    )
    system = (
        "You answer questions about a U.S. Forest Service dataset catalog using "
        "only the provided excerpts. Be concise and never invent datasets."
    )
    return {"answer": get_llm().complete(prompt, system=system), "sources": hits}


def find_duplicates(threshold: float = 0.95, limit: int = 100) -> list[dict]:
    """Find near-duplicate dataset pairs by embedding similarity.

    Complements the exact-title-hash dedupe: catches records whose titles differ
    (e.g. trailing "(Map Service)") but whose content is effectively the same.
    """
    column = active_embedding_column()  # from the trusted EMBEDDING_COLUMN set
    max_distance = 1 - threshold

    # a.id < b.id yields each unordered pair once. O(n^2) but fine at this scale.
    sql = text(
        f"SELECT a.id, a.title, a.src, b.id, b.title, b.src, "
        f"       1 - (a.{column} <=> b.{column}) AS sim "
        f"FROM inventory a JOIN inventory b ON a.id < b.id "
        f"WHERE a.{column} IS NOT NULL AND b.{column} IS NOT NULL "
        f"  AND (a.{column} <=> b.{column}) < :max_distance "
        f"ORDER BY sim DESC LIMIT :limit"
    )
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"max_distance": max_distance, "limit": limit}).all()
    return [
        {
            "id_a": r[0],
            "title_a": r[1],
            "src_a": r[2],
            "id_b": r[3],
            "title_b": r[4],
            "src_b": r[5],
            "similarity": r[6],
        }
        for r in rows
    ]
