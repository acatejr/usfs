"""
Central configuration for the inventory layer.

Everything that varies by environment — the Postgres connection string, which
AI provider to use, and the model names / dimensions — is read from environment
variables here, so no other module hard-codes a secret or a host. Defaults are
tuned for the fully-local path (Ollama + fastembed); switching to the cloud path
is a matter of setting ``USFS_PROVIDER=anthropic`` and the two API keys.
"""

from dotenv import load_dotenv
import os


load_dotenv()  # read .env file if present

# --- Database -------------------------------------------------------------

# psycopg-style connection string, e.g.
#   postgresql://user:pass@localhost:5432/usfs
# Read from the environment so credentials never live in the repo.
DATABASE_URL = os.environ.get("DATABASE_URL", "")


# --- Provider selection ---------------------------------------------------

# "local"     -> Ollama LLM + fastembed embeddings
# "anthropic" -> Claude LLM + Voyage embeddings
# "verde"     -> VerdeLLM via a LiteLLM proxy
PROVIDER = os.environ.get("USFS_PROVIDER", "local").lower()


# --- Local provider settings ----------------------------------------------

# fastembed model + its output dimension. If you change the model,
# update LOCAL_EMBED_DIM to match (bge-small-en-v1.5 and all-MiniLM-L6-v2 are
# both 384). This dimension must equal the embedding_local column width in db.py.
LOCAL_EMBED_MODEL = os.environ.get("USFS_LOCAL_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
LOCAL_EMBED_DIM = int(os.environ.get("USFS_LOCAL_EMBED_DIM", "384"))

# Ollama HTTP endpoint + the local chat model used for enrichment / RAG.
OLLAMA_HOST = os.environ.get("USFS_OLLAMA_HOST", "http://localhost:11434")
LOCAL_LLM_MODEL = os.environ.get("USFS_LOCAL_LLM_MODEL", "llama3.1")


# --- Anthropic / Voyage settings (used only when PROVIDER == "anthropic") --

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Quality model for enrichment/RAG; Haiku is a cheaper bulk option.
CLAUDE_MODEL = os.environ.get("USFS_CLAUDE_MODEL", "claude-opus-4-8")

VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
VOYAGE_EMBED_MODEL = os.environ.get("USFS_VOYAGE_EMBED_MODEL", "voyage-3")
VOYAGE_EMBED_DIM = int(os.environ.get("USFS_VOYAGE_EMBED_DIM", "1024"))


# --- Verde settings (used only when PROVIDER == "verde") ------------------

# A LiteLLM proxy endpoint exposing a chat model. The model name is passed
# through as ``litellm_proxy/<VERDE_MODEL>``.
VERDE_API_KEY = os.environ.get("VERDE_API_KEY", "")
VERDE_URL = os.environ.get("VERDE_URL", "")
VERDE_MODEL = os.environ.get("VERDE_MODEL", "")


def require_database_url() -> str:
    """Return DATABASE_URL or raise a clear error if it is unset.

    Called by db.py before connecting so a missing env var fails loudly with a
    helpful message instead of a confusing libpq connection error.
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Export a Postgres connection string, e.g.\n"
            "  export DATABASE_URL=postgresql://user:pass@localhost:5432/usfs"
        )
    return DATABASE_URL
