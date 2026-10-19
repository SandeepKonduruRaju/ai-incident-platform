package com.sandeep.incidentplatform.exception;

/**
 * The investigation worker could not answer (down, timeout, rejected our token, unreadable reply).
 * Becomes a 503 with Retry-After: the incident exists, the investigation just cannot be read right now.
 */
public class WorkerUnavailableException extends RuntimeException {

    public WorkerUnavailableException(String message) {
        super(message);
    }

    public WorkerUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
