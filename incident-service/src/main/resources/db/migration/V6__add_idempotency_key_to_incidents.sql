-- Idempotency-Key of POST /api/v1/incidents (optional header): a retried request with the same key returns the
-- incident it created instead of creating a second one (and a second investigation). Unique per tenant: two tenants
-- may use the same key. NULL for incidents created without a key (NULLs never collide in a unique index).
ALTER TABLE incidents ADD COLUMN idempotency_key VARCHAR(255);
CREATE UNIQUE INDEX uq_incidents_tenant_idempotency_key ON incidents (tenant_id, idempotency_key);
