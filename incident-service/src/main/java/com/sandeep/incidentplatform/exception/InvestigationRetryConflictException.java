package com.sandeep.incidentplatform.exception;

/** A retry of the investigation is not allowed now (409, see GlobalExceptionHandler). */
public class InvestigationRetryConflictException extends RuntimeException {

    public InvestigationRetryConflictException(String message) {
        super(message);
    }
}
