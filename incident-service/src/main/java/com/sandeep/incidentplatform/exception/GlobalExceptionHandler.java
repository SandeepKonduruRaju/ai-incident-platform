package com.sandeep.incidentplatform.exception;

import com.sandeep.incidentplatform.observability.RequestIdFilter;
import com.sandeep.incidentplatform.security.MissingTenantException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import java.util.List;
import java.util.Map;

/**
 * Turns every error into an RFC 9457 Problem Details body (application/problem+json).
 * Spring MVC's own errors (malformed JSON, wrong types, unsupported media type, ...) are
 * handled by ResponseEntityExceptionHandler; this class adds the application-specific ones.
 */
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    static final String WORKER_RETRY_AFTER_SECONDS = "5";

    // 400: @Valid failed. Adds a per-field "errors" list so clients can show messages next to inputs.
    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(MethodArgumentNotValidException ex,
                                                                  HttpHeaders headers,
                                                                  HttpStatusCode status,
                                                                  WebRequest request) {
        ProblemDetail problem = ex.getBody();
        problem.setTitle("Validation failed");
        problem.setDetail("One or more fields are invalid.");
        List<Map<String, String>> errors = ex.getBindingResult().getFieldErrors().stream()
                .map(error -> Map.of(
                        "field", error.getField(),
                        "message", String.valueOf(error.getDefaultMessage())))
                .toList();
        problem.setProperty("errors", errors);
        return handleExceptionInternal(ex, problem, headers, status, request);
    }

    @ExceptionHandler(IncidentNotFoundException.class)
    public ProblemDetail handleIncidentNotFound(IncidentNotFoundException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, ex.getMessage());
        problem.setTitle("Incident not found");
        return problem;
    }

    // 403: authenticated, but the token does not say which tenant the caller belongs to.
    @ExceptionHandler(MissingTenantException.class)
    public ProblemDetail handleMissingTenant(MissingTenantException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.FORBIDDEN, ex.getMessage());
        problem.setTitle("Missing tenant");
        return problem;
    }

    // 409: two requests updated the same incident concurrently and @Version detected it.
    @ExceptionHandler(OptimisticLockingFailureException.class)
    public ProblemDetail handleConcurrentUpdate(OptimisticLockingFailureException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT,
                "The incident was modified by another request. Reload it and try again.");
        problem.setTitle("Concurrent update");
        return problem;
    }

    // 503: the investigation worker is down, slow or misconfigured. The incident itself is fine;
    // Retry-After tells the client when to try again. The cause was already logged by the client class.
    @ExceptionHandler(WorkerUnavailableException.class)
    public ResponseEntity<ProblemDetail> handleWorkerUnavailable(WorkerUnavailableException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.SERVICE_UNAVAILABLE,
                "The investigation service is temporarily unavailable. Try again shortly.");
        problem.setTitle("Investigation unavailable");
        problem.setProperty("requestId", MDC.get(RequestIdFilter.MDC_KEY));
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .header(HttpHeaders.RETRY_AFTER, WORKER_RETRY_AFTER_SECONDS)
                .body(problem);
    }

    // 500: anything unexpected. Log the details server-side; never leak them to the client.
    @ExceptionHandler(Exception.class)
    public ProblemDetail handleUnexpected(Exception ex) {
        log.error("Unexpected error", ex);
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.INTERNAL_SERVER_ERROR,
                "An unexpected error occurred.");
        problem.setTitle("Internal server error");
        // Lets a user quote the id so the matching server log lines can be found.
        problem.setProperty("requestId", MDC.get(RequestIdFilter.MDC_KEY));
        return problem;
    }
}
