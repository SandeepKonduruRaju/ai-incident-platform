package com.sandeep.incidentplatform.exception;

/** The Idempotency-Key header is not 1-255 visible ASCII characters (400). */
public class InvalidIdempotencyKeyException extends RuntimeException {

    public InvalidIdempotencyKeyException() {
        super("Idempotency-Key must be 1 to 255 visible ASCII characters (no spaces), e.g. a UUID.");
    }
}
