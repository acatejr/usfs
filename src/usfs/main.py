"""
CLI entry point for the USFS metadata tool.

``main`` is a click group with two families of commands:

  harvest                     download sources + build the unified catalog JSON
  initdb / load / enrich /    the Postgres + pgvector inventory pipeline,
  embed / search / ask /      run in that order after harvest
  dedupe

The inventory commands import their heavy modules lazily, so ``usfs harvest``
works without the optional ``ai`` extras installed.
"""

import click

from .usfs import USFS


@click.group()
def main() -> None:
    """USFS metadata harvesting and inventory tool."""


@main.command()
def harvest() -> None:
    """Download all sources and build data/usfs/usfs_catalog.json."""
    usfs = USFS()
    click.echo("Harvesting metadata from USFS...")
    usfs.download_fsgeodata_metadata()
    usfs.download_gdd_metadata()
    usfs.download_rda_metadata()
    usfs.build_catalog()


@main.command()
def initdb() -> None:
    """Create the pgvector extension, inventory table, and indexes."""
    from . import db

    db.init_schema()
    click.echo("Schema initialized.")


@main.command()
@click.option(
    "--path",
    default="./data/usfs/usfs_catalog.json",
    show_default=True,
    help="Catalog JSON to load.",
)
def load(path: str) -> None:
    """Load the unified catalog JSON into Postgres."""
    from .load import load_catalog

    load_catalog(path)


@main.command()
def enrich() -> None:
    """Fill summary/topics/data_type/quality_flags via the configured LLM."""
    from .enrich import enrich_catalog

    enrich_catalog()


@main.command()
def embed() -> None:
    """Embed catalog rows into the active provider's vector column."""
    from .embeddings import embed_pending

    embed_pending()


@main.command(name="search")
@click.argument("query")
@click.option("--limit", default=10, show_default=True, help="Number of results.")
def search_cmd(query: str, limit: int) -> None:
    """Semantic search over the catalog."""
    from .search import search

    for hit in search(query, limit=limit):
        click.echo(f"{hit['score']:.3f}  [{hit['src']}]  {hit['title']}")


@main.command()
@click.argument("question")
@click.option("-k", default=8, show_default=True, help="Datasets to retrieve.")
def ask(question: str, k: int) -> None:
    """Answer a question over the catalog with RAG."""
    from .search import answer

    result = answer(question, k=k)
    click.echo(result["answer"])
    click.echo("\nSources:")
    for src in result["sources"]:
        click.echo(f"  - [{src['src']}] {src['title']}")


@main.command()
@click.option(
    "--threshold", default=0.95, show_default=True, help="Min cosine similarity."
)
def dedupe(threshold: float) -> None:
    """Report near-duplicate dataset pairs by embedding similarity."""
    from .search import find_duplicates

    pairs = find_duplicates(threshold=threshold)
    if not pairs:
        click.echo("No near-duplicate pairs found above threshold.")
        return
    for p in pairs:
        click.echo(
            f"{p['similarity']:.3f}  "
            f"{p['title_a']} [{p['src_a']}:{p['id_a'][:8]}]  <->  "
            f"{p['title_b']} [{p['src_b']}:{p['id_b'][:8]}]"
        )

@main.command()
def clear_inventory() -> None:
    """Delete all rows from the inventory table."""
    from .db import clear_inventory_table

    clear_inventory_table()
    click.echo("All rows deleted from the inventory table.")