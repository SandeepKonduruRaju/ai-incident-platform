package com.sandeep.incidentplatform.exception;

/** The caller's tenant created too many incidents in the current window (429, see GlobalExceptionHandler). */
public class RateLimitExceededException extends RuntimeException {

    private final int limit;
    private final long retryAfterSeconds;

    public RateLimitExceededException(int limit, long retryAfterSeconds) {
        super("Rate limit of " + limit + " incidents per minute exceeded for this tenant.");
        this.limit = limit;
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public int limit() {
        return limit;
    }

    public long retryAfterSeconds() {
        return retryAfterSeconds;
    }
}
