-- Multi-tenancy: every incident belongs to exactly one tenant (organisation).
-- Existing rows are assigned to a 'default' tenant; the default is then dropped so the
-- application must always set tenant_id explicitly.
ALTER TABLE incidents ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default';
ALTER TABLE incidents ALTER COLUMN tenant_id DROP DEFAULT;

-- Every query filters by tenant; listing also sorts by newest first.
CREATE INDEX idx_incidents_tenant_created_at ON incidents (tenant_id, created_at DESC);
