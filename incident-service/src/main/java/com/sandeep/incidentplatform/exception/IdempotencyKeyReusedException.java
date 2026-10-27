package com.sandeep.incidentplatform.exception;

/** The Idempotency-Key was already used by this tenant for a DIFFERENT request body (422). */
public class IdempotencyKeyReusedException extends RuntimeException {

    public IdempotencyKeyReusedException() {
        super("This Idempotency-Key was already used for a different request. Use a new key for a new incident.");
    }
}
