package com.sandeep.incidentplatform.investigation;

import com.sandeep.incidentplatform.exception.WorkerUnavailableException;
import com.sandeep.incidentplatform.observability.PlatformMetrics;
import com.sandeep.incidentplatform.observability.PlatformMetrics.WorkerErrorKind;
import com.sandeep.incidentplatform.observability.RequestIdFilter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.HttpStatusCode;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClient.RequestHeadersSpec.ConvertibleClientHttpResponse;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientException;

import java.io.IOException;
import java.net.SocketTimeoutException;
import java.util.Optional;
import java.util.UUID;

/**
 * Calls the investigation worker's internal read API. Each service owns its data: this service
 * never reads the worker's schema, it asks the worker over HTTP.
 * <ul>
 *   <li>tenantId always comes from the caller's JWT (the controller passes it), never from the client;</li>
 *   <li>the shared secret goes in X-Internal-Token and is never logged;</li>
 *   <li>the request id is forwarded, so the worker's log lines can be matched with ours.</li>
 * </ul>
 */
public class WorkerInvestigationClient {

    static final String TOKEN_HEADER = "X-Internal-Token";
    static final String PATH = "/internal/v1/investigations";

    private static final Logger log = LoggerFactory.getLogger(WorkerInvestigationClient.class);

    private final RestClient restClient;
    private final PlatformMetrics metrics;

    // Takes a builder (timeouts already set by the caller) so tests can bind a mock server to it.
    public WorkerInvestigationClient(RestClient.Builder builder, WorkerProperties properties, PlatformMetrics metrics) {
        this.metrics = metrics;
        this.restClient = builder
                .baseUrl(properties.baseUrl().toString())
                .defaultHeader(TOKEN_HEADER, properties.token())
                .build();
    }

    /**
     * The latest investigation of the incident, or empty if the worker has none yet (its 404).
     * Any other failure throws WorkerUnavailableException (mapped to 503).
     */
    public Optional<WorkerInvestigation> fetch(String tenantId, UUID incidentId) {
        try {
            return restClient.get()
                    .uri(uri -> uri.path(PATH)
                            .queryParam("tenantId", tenantId)
                            .queryParam("incidentId", incidentId)
                            .build())
                    .headers(headers -> {
                        String requestId = MDC.get(RequestIdFilter.MDC_KEY);
                        if (requestId != null) {
                            headers.set(RequestIdFilter.HEADER, requestId);
                        }
                    })
                    .exchange((request, response) -> handle(response));
        } catch (WorkerUnavailableException ex) {
            throw ex;
        } catch (RestClientException ex) {
            // Connection refused, timeout (ResourceAccessException) or an unreadable body.
            metrics.workerClientError(kindOf(ex));
            log.warn("Investigation worker call failed: {}", ex.getMessage());
            throw new WorkerUnavailableException("Investigation worker unreachable", ex);
        }
    }

    private Optional<WorkerInvestigation> handle(ConvertibleClientHttpResponse response) throws IOException {
        HttpStatusCode status = response.getStatusCode();
        if (status.is2xxSuccessful()) {
            return Optional.ofNullable(response.bodyTo(WorkerInvestigation.class));
        }
        if (status.value() == 404) {
            return Optional.empty();
        }
        metrics.workerClientError(status.value() == 401 || status.value() == 403 ? WorkerErrorKind.UNAUTHORIZED
                : status.is5xxServerError() ? WorkerErrorKind.SERVER_ERROR : WorkerErrorKind.HTTP_ERROR);
        if (status.value() == 401 || status.value() == 403) {
            // Not the user's fault and not transient: the two services disagree on the shared secret.
            log.error("Investigation worker rejected the internal token (HTTP {}): misconfiguration, "
                    + "check investigation.worker.token / INTERNAL_API_TOKEN on both services", status.value());
        } else {
            log.warn("Investigation worker returned HTTP {}", status.value());
        }
        throw new WorkerUnavailableException("Investigation worker returned HTTP " + status.value());
    }

    private static WorkerErrorKind kindOf(RestClientException ex) {
        if (!(ex instanceof ResourceAccessException)) {
            return WorkerErrorKind.BAD_RESPONSE;
        }
        return ex.getMostSpecificCause() instanceof SocketTimeoutException
                ? WorkerErrorKind.TIMEOUT : WorkerErrorKind.CONNECTION;
    }
}
