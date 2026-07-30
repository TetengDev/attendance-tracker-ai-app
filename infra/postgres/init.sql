-- Local development database bootstrap.
--
-- Revision 2 explicitly removed pgvector from this project. Face embeddings are
-- AES-GCM encrypted bytea values, so pgvector operators cannot inspect them.
-- Duplicate detection and matching run in the in-process NumPy gallery index.
--
-- Do not add:
--   CREATE EXTENSION vector;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
