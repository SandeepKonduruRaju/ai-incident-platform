-- "Latest investigation request for an incident": newest outbox row per aggregate. Read by
-- IncidentService.latestInvestigationRequest (NOT_STARTED status, retry) and by the worker's superseded check
-- (investigation-worker/app/request_check.py). Without it both scan the whole, ever-growing outbox.
CREATE INDEX idx_outbox_events_aggregate ON outbox_events (aggregate_id, created_at);
