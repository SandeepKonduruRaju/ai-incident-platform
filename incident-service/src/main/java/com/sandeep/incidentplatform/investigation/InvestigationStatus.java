package com.sandeep.incidentplatform.investigation;

/**
 * PENDING/RUNNING/COMPLETED/FAILED come from the worker. NOT_STARTED is decided by incident-service: no investigation
 * was ever requested for the incident (e.g. created before the outbox existed), or the request was published long
 * ago and the worker has no run for it. It is final until someone retries (POST .../investigation/retry).
 */
public enum InvestigationStatus {
    PENDING, RUNNING, COMPLETED, FAILED, NOT_STARTED;

    /** Still being worked on: the client should poll again (the response carries Retry-After). */
    public boolean inProgress() {
        return this == PENDING || this == RUNNING;
    }

    /** States a user may retry from (POST .../investigation/retry); anything else is 409. */
    public boolean retryable() {
        return this == NOT_STARTED || this == FAILED;
    }
}
