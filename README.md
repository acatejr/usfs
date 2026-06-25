# usfs

`usfs` harvests dataset metadata from three U.S. Forest Service (USFS) sources,
normalizes them into a single catalog JSON file, and loads that catalog into a
Postgres + pgvector database to power an AI metadata inventory: semantic search,
LLM enrichment, retrieval-augmented Q&A, and semantic deduplication.

The project uses [uv](https://docs.astral.sh/uv/) for environment and dependency
management and requires Python >= 3.14.

---

## Architecture

The system runs in two stages.

**Stage 1 — Harvest** (no database or AI required): downloads metadata from
FSGeodata (XML), GDD (DCAT-US JSON), and RDA (JSON), then builds the unified
`data/usfs/usfs_catalog.json`. This is the original pipeline and is unchanged.

**Stage 2 — Inventory** (Postgres + pgvector + an AI provider): loads the
catalog into Postgres, enriches it with an LLM, embeds it into vectors, and
exposes search / ask / dedupe.

```
src/usfs/
  config.py     env-driven config + provider switch (USFS_PROVIDER=local|anthropic)
  schema.py     USFSDocument — one validated pydantic view over the ragged
                source shapes; to_embedding_text() builds the text to embed
  db.py         SQLAlchemy engine/session + DocumentRecord ORM (catalog table,
                pgvector columns, HNSW indexes)
  providers.py  LLM abstraction — local (Ollama) and cloud (Claude); get_llm()
  embeddings.py EmbeddingsService (fastembed / Voyage) + embed_pending()
                orchestrator; vectorizes rows into the active column
  load.py       usfs_catalog.json -> DocumentRecord upsert (base columns only)
  enrich.py     LLM fills summary/topics/data_type; quality_flags computed in code
  search.py     semantic search + RAG ask + semantic dedupe
  main.py       click group wiring all commands
  usfs.py       Stage 1 download + catalog-build logic
  lib.py        stateless helpers (save/load JSON, clean_str, hash_string, dedupe)
tests/
  test_db.py    DB-free logic/schema tests + opt-in Postgres integration test
```

The inventory layer is built on **SQLAlchemy 2.0** (ORM + psycopg 3 driver),
**fastembed** for local embeddings (ONNX runtime — no PyTorch), and **pydantic**
for the `USFSDocument` schema.

### Provider abstraction (local now, cloud later)

Embeddings (`embeddings.py`) and the LLM (`providers.py`) each have a local and a
cloud implementation, chosen by the `USFS_PROVIDER` environment variable so no
other module imports a vendor SDK directly:

| `USFS_PROVIDER` | Embeddings           | LLM            | Vector column      |
| --------------- | -------------------- | -------------- | ------------------ |
| `local`         | fastembed (default)  | Ollama         | `embedding_local`  |
| `anthropic`     | Voyage AI            | Claude         | `embedding_voyage` |

Vendor packages are imported lazily, so the local path runs without the cloud
extras installed (and vice versa).

### Database schema

One `catalog` table holds the raw record, the AI-enrichment fields, and the
embeddings. Because a pgvector column has a fixed dimension, the local and cloud
embeddings live in **separate columns** so both providers can coexist without a
migration; each has its own HNSW cosine index.

```
catalog(
  id            TEXT PRIMARY KEY,    -- SHA-256 hash of the lowercased title
  src           TEXT,               -- fsgeodata | gdd | rda
  title         TEXT,
  raw           JSONB,              -- the full source record, shape preserved
  summary       TEXT,               -- enrichment (NULL until enriched)
  topics        TEXT[],
  data_type     TEXT,
  quality_flags JSONB,
  embed_text    TEXT,               -- the text that was embedded
  embed_model   TEXT,               -- guards against stale/mixed vectors
  embedding_local  VECTOR(384),     -- fastembed (bge-small)
  embedding_voyage VECTOR(1024)     -- Voyage AI
)
```

The table is defined as the `DocumentRecord` ORM model in `db.py`;
`usfs initdb` creates the extensions and runs `Base.metadata.create_all`.

---

## Installation

```bash
# core harvester only
uv sync

# add the local inventory layer (SQLAlchemy, pgvector, fastembed, pydantic)
uv sync --extra ai

# add dev tooling (pytest)
uv sync --extra ai --group dev

# (optional, for the cloud path) add Anthropic + Voyage SDKs
uv sync --extra ai --extra anthropic
```

> `fastembed` uses the ONNX runtime rather than PyTorch, so `--extra ai` is a
> much lighter install than a Torch-based embedding stack. The embedding model
> weights are downloaded on first use.

### Prerequisites for the inventory layer

- A reachable **PostgreSQL** instance with the `vector` (pgvector) extension
  available. The schema also enables PostGIS extensions for the geospatial
  records, so a PostGIS-enabled image (e.g. `postgis/postgis` with pgvector, or
  a database where these extensions are installed) is recommended.
- **[Ollama](https://ollama.com/)** running locally for the `local` provider,
  with a chat model pulled (default `llama3.1`):

  ```bash
  ollama pull llama3.1
  ```

---

## Configuration

All configuration is read from environment variables (see `src/usfs/config.py`).

| Variable                  | Default                     | Purpose                                   |
| ------------------------- | --------------------------- | ----------------------------------------- |
| `DATABASE_URL`            | _(required)_                | Postgres connection string                |
| `USFS_PROVIDER`           | `local`                     | `local` or `anthropic`                    |
| `USFS_LOCAL_EMBED_MODEL`  | `BAAI/bge-small-en-v1.5`    | fastembed model                           |
| `USFS_LOCAL_EMBED_DIM`    | `384`                       | must match `embedding_local` column width |
| `USFS_OLLAMA_HOST`        | `http://localhost:11434`    | Ollama endpoint                           |
| `USFS_LOCAL_LLM_MODEL`    | `llama3.1`                  | Ollama chat model                         |
| `ANTHROPIC_API_KEY`       | _(unset)_                   | required when `USFS_PROVIDER=anthropic`   |
| `USFS_CLAUDE_MODEL`       | `claude-opus-4-8`           | Claude model for enrichment / RAG         |
| `VOYAGE_API_KEY`          | _(unset)_                   | required when `USFS_PROVIDER=anthropic`   |
| `USFS_VOYAGE_EMBED_MODEL` | `voyage-3`                  | Voyage embedding model                    |
| `USFS_VOYAGE_EMBED_DIM`   | `1024`                      | must match `embedding_voyage` column      |

```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/usfs
```

> If you change an embedding model to one with a different dimension, update the
> matching `*_EMBED_DIM` and recreate that vector column — pgvector column widths
> are fixed.

---

## Usage

The CLI is a click group (`usfs <command>`). Run the commands in order.

```bash
# Stage 1 — harvest (downloads sources, builds data/usfs/usfs_catalog.json)
uv run usfs harvest

# Stage 2 — inventory
uv run usfs initdb       # create extensions, catalog table, and HNSW indexes
uv run usfs load         # load usfs_catalog.json into Postgres (idempotent upsert)
uv run usfs enrich       # LLM summaries/topics/data_type (needs Ollama running)
uv run usfs embed        # embed rows into the active provider's vector column

# query
uv run usfs search "wildfire fuel treatments in California"
uv run usfs ask "Which datasets cover riparian vegetation?"
uv run usfs dedupe --threshold 0.95
```

### Command reference

| Command            | Description                                                          |
| ------------------ | ------------------------------------------------------------------- |
| `harvest`          | Download all sources and build `data/usfs/usfs_catalog.json`.       |
| `initdb`           | Create the pgvector/PostGIS extensions, `catalog` table, indexes.   |
| `load [--path]`    | Upsert the catalog JSON into Postgres.                              |
| `enrich`           | Fill `summary`/`topics`/`data_type`/`quality_flags` via the LLM.    |
| `embed`            | Embed rows lacking a current vector into the active column.         |
| `search <query> [--limit]` | Cosine-similarity semantic search; prints scored hits.      |
| `ask <question> [-k]`      | Retrieval-augmented answer with cited source datasets.      |
| `dedupe [--threshold]`     | Report near-duplicate dataset pairs by embedding similarity. |

### Notes on behavior

- **Order matters:** run `enrich` before `embed` so embeddings incorporate the
  generated summaries. Both phases are **resumable** — they only process rows
  that still need work (`summary IS NULL` for enrich; a NULL or stale-model
  vector for embed), so an interrupted run continues cleanly on the next call.
- **Idempotent load:** `load` upserts on `id` (the SHA-256 title hash), so
  re-running refreshes rows rather than duplicating. Records with identical
  titles collapse into one row by design.
- **Switching to the cloud provider:** set `USFS_PROVIDER=anthropic`, export
  `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY`, install the `anthropic` extra, then
  re-run `embed` (it populates `embedding_voyage` independently — local vectors
  are left intact). Embeddings are not portable across models, so the cloud
  column must be embedded separately.

---

## Testing

```bash
uv run pytest tests/test_db.py -v
```

The default suite is **DB-free** (provider→column mapping logic). The
integration test that exercises the live schema and an insert/select roundtrip
is **skipped unless `DATABASE_URL` is set**.

---

## What is Voyage?

**Voyage AI** is a company that builds text **embedding models** (and
rerankers) — the cloud counterpart to local `fastembed` in the `local` provider
path. It matters here because Anthropic doesn't make embedding models, and Voyage
is the embedding provider Anthropic officially recommends. Anthropic acquired
Voyage AI in 2025, so it's now part of Anthropic.

**What an embedding model does:** it turns a piece of text into a fixed-length
vector of numbers that captures meaning, so semantically similar texts land near
each other. That is what powers the `search`, `ask`, and `dedupe` commands — each
dataset's text is embedded, the vector is stored in pgvector, and comparison is
done by cosine distance.

**In this codebase specifically:**

- `EmbeddingsService` in `embeddings.py` calls Voyage's API (when
  `USFS_PROVIDER=anthropic`) and writes to the `embedding_voyage VECTOR(1024)`
  column.
- The default `local` path never touches it (the `voyageai` package isn't
  imported unless you switch).
- The default model is `voyage-3` at **1024 dimensions** — vs. the local
  `bge-small` at 384, which is why the two live in separate columns.

**Local vs. Voyage trade-off:**

|          | Local (fastembed)             | Voyage                          |
| -------- | ----------------------------- | ------------------------------- |
| Runs     | On your machine, offline      | Cloud API (needs `VOYAGE_API_KEY`) |
| Cost     | Free                          | Per-token billing               |
| Quality  | Good                          | Generally higher retrieval quality |
| Setup    | ONNX model download           | Just an API key                 |

For the "local now, cloud later" plan: stay on `bge-small` for free today, and
if you later want better search relevance, flip to Voyage and re-run `embed` to
populate the `embedding_voyage` column. Embeddings are not portable across
models, so switching always requires re-embedding — which is why the schema keeps
both columns.
