# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`usfs` is a metadata-harvesting tool that downloads dataset metadata from three
distinct U.S. Forest Service (USFS) sources and normalizes them into a single
unified catalog JSON file. The end artifact (`data/usfs/usfs_catalog.json`) is
intended for downstream search / AI retrieval.

## Commands

The project uses [uv](https://docs.astral.sh/uv/) for environment and dependency management. Requires Python >= 3.14.

```bash
uv sync                       # install dependencies into .venv
uv run usfs                   # run the full harvest pipeline (entry point: usfs.main:main)
uv run python -m usfs.main    # equivalent invocation
```

There is no test suite, linter, or build step configured. The console script
`usfs` is defined in `pyproject.toml` and maps to `usfs.main:main`.

## Architecture

The pipeline has two phases — **download** then **build** — both orchestrated by
`harvest_metadata()` in `src/usfs/main.py`, which calls the `USFS` service class
(`src/usfs/usfs.py`).

**Phase 1 — Download** (one method per source, each idempotent: skips files that
already exist on disk, so repeat runs are safe and incremental):
- `download_fsgeodata_metadata` — scrapes the Geodata Clearinghouse listing page
  and fetches one FGDC-standard **XML** file per dataset into `data/usfs/fsgeodata/`.
- `download_gdd_metadata` — fetches a single DCAT-US 1.1 **JSON** feed into `data/usfs/gdd/gdd_metadata.json`.
- `download_rda_metadata` — fetches a single Research Data Archive **JSON** feed into `data/usfs/rda/rda_metadata.json`.

**Phase 2 — Build** (`build_catalog` runs all three, concatenates results, writes
`data/usfs/usfs_catalog.json`):
- `build_fsgeodata_catalog` parses each XML file with BeautifulSoup (`xml` parser).
- `build_gdd_catalog` / `build_rda_catalog` parse the `dataset` array of each JSON feed.

Each build method reads from its source directory and returns a list of
normalized document dicts. **The dict shapes are intentionally NOT uniform across
sources** — FSGeodata docs have `abstract`/`purpose`/`lineage`; GDD/RDA docs have
`description`/`themes`. All share `id`, `title`, `keywords`, and `src`.

### Key conventions
- **`id` is derived, not stored**: every document's `id` is `hash_string(title.lower().strip())`
  (SHA-256). Two records with the same title collide by design — `lib.dedupe_catalog`
  exists to collapse them. Do not assume `id` is a stable source identifier.
- **`self.output_dir`** is `./data/usfs` relative to the **current working directory**,
  so the tool must be run from the repo root.
- Text from remote sources is run through `lib.clean_str` (strips HTML via
  BeautifulSoup + collapses whitespace); keyword lists go through
  `clean_keywords` (lowercase, strip punctuation, dedupe preserving order).

### Module layout
- `src/usfs/usfs.py` — the `USFS` class; all download + build logic.
- `src/usfs/lib.py` — stateless helpers: `save_json`, `load_json`, `clean_str`,
  `strip_html`, `hash_string`, `dedupe_catalog`.
- `src/usfs/main.py` — CLI entry point wiring the pipeline together.

## Notes
- Docstrings in `usfs.py` reference a `schema.USFSDocument` type, but no `schema`
  module exists — documents are plain dicts. Treat those references as aspirational.
- `download_fsgeodata_metadata` uses `os.path.exists`-based skipping, while the
  build methods read whatever XML files are present; the `data/usfs/` directory is
  committed to the repo and acts as a cache.

## Rules
- Never guess answers.  If you don't know something just say you don't know.
- Never read the contents of the .env file
- Always honor .gitignore
- Always ignore the .venv file
