-- Rename the `catalog` table to `inventory`, plus its indexes and primary key
-- constraint, to match the ORM definition in src/usfs/db.py.
--
-- Run against an existing/populated database, e.g.:
--   psql "$DATABASE_URL" -f migrations/001_rename_catalog_to_inventory.sql
--
-- Wrapped in a transaction so it either fully applies or rolls back.

BEGIN;

-- The table itself.
ALTER TABLE catalog RENAME TO inventory;

-- Primary key constraint (Postgres named it `catalog_pkey` by default).
ALTER INDEX catalog_pkey RENAME TO inventory_pkey;

-- Secondary indexes (explicitly named in db.py).
ALTER INDEX catalog_embedding_local_idx  RENAME TO inventory_embedding_local_idx;
ALTER INDEX catalog_embedding_voyage_idx RENAME TO inventory_embedding_voyage_idx;
ALTER INDEX catalog_src_idx              RENAME TO inventory_src_idx;

COMMIT;
