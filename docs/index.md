---
icon: lucide/trees
---

# USFS Metadata Inventory

A tool that gathers dataset descriptions from across the U.S. Forest Service,
organizes them into one consistent, searchable inventory, and lets people find
the right data by asking plain-language questions.

## The problem it solves

The Forest Service publishes thousands of datasets across several separate
systems. Each system describes its data differently, the same dataset is
sometimes listed in more than one place, and the descriptions range from
detailed to nearly empty. As a result, finding the right dataset — or even
knowing what exists — is harder than it should be.

This tool brings those scattered descriptions together, makes them consistent,
flags duplicates and gaps, and makes the whole collection searchable by meaning
rather than just by keyword.

## What it does, in four steps

```mermaid
graph LR
  A[Harvest] --> B[Enrich]
  B --> C[Index]
  C --> D[Search & Ask]
```

1. **Harvest** — collects dataset descriptions from three Forest Service
   sources into one place.
2. **Enrich** — uses AI to give every dataset a clear, plain-language summary,
   consistent topic tags, and quality flags noting what the original record was
   missing.
3. **Index** — prepares the enriched descriptions so they can be searched by
   meaning.
4. **Search & Ask** — lets users find datasets by similarity or ask questions
   and get answers drawn only from the inventory.

## Find your path

=== "Administrators & Decision-makers"

    Start with **[What it does, in four steps](#what-it-does-in-four-steps)**
    above. The key takeaways:

    - It creates a **single, authoritative inventory** of Forest Service
      datasets from sources that are otherwise separate.
    - It **does not change or delete source data** — it gathers and describes
      it. Duplicate detection only *reports* overlaps for a person to review.
    - The AI step writes summaries from the agency's own metadata and is
      designed to **never invent information**; factual quality checks run
      without AI.

=== "Data Analysts"

    The inventory is built for discovery. Once it is populated you can:

    - **Search by meaning** — find datasets related to a concept even when the
      words differ.
    - **Ask questions** — get plain-language answers backed by specific
      datasets.
    - **Review duplicates and gaps** — see near-identical datasets and records
      with missing descriptions or keywords.

    See the [Getting started](getting_started.md) guide to run your first
    search.

=== "Programmers"

    The tool is a Python command-line application (Python 3.14+, managed with
    [uv](https://docs.astral.sh/uv/)). It runs as a staged pipeline backed by
    PostgreSQL with the pgvector extension.

    ``` bash
    uv sync                 # install dependencies
    uv run usfs harvest     # collect source metadata
    uv run usfs initdb      # set up the database
    uv run usfs load        # load the inventory
    uv run usfs enrich      # add AI summaries, topics, quality flags
    uv run usfs embed       # index for semantic search
    uv run usfs search "stream crossings"
    ```

    See [Getting started](getting_started.md) for full setup.

## The data sources

| Source | What it provides |
|--------|------------------|
| **FSGeodata Clearinghouse** | Geospatial dataset metadata (FGDC-standard XML). |
| **Geospatial Data Discovery (GDD)** | A catalog feed of dataset records (JSON). |
| **Research Data Archive (RDA)** | Forest Service research dataset records (JSON). |

## Key principles

!!! note "Read-only by design"

    The tool gathers and describes data; it does not modify the original Forest
    Service sources. Duplicate detection reports overlaps for human review
    rather than deleting anything.

!!! note "AI used carefully"

    AI generates summaries and topic tags strictly from the agency's existing
    metadata and is instructed never to invent datasets or facts. Quality flags
    are computed by simple rules, with no AI involved.

## Where to go next

- **[Getting started](getting_started.md)** — install the tool and run the
  pipeline.
- **[Enrichment](enrich.md)** — how dataset summaries, topics, and quality flags
  are produced.
- **[Duplicate detection](dedupe.md)** — how near-duplicate datasets are found
  and read.
