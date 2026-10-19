package com.sandeep.incidentplatform.investigation;

public enum InvestigationStatus {
    PENDING, RUNNING, COMPLETED, FAILED;

    /** Still being worked on: the client should poll again (the response carries Retry-After). */
    public boolean inProgress() {
        return this == PENDING || this == RUNNING;
    }
}
