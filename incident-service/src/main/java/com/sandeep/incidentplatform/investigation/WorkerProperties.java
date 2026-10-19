package com.sandeep.incidentplatform.investigation;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.net.URI;
import java.time.Duration;

/**
 * Where the investigation worker's internal API is and how to call it (investigation.worker.*).
 * The token is the shared secret sent as X-Internal-Token; it comes from the INTERNAL_API_TOKEN
 * environment variable and has no default, so the app fails fast without it (like JWT_SECRET).
 */
@ConfigurationProperties("investigation.worker")
public record WorkerProperties(URI baseUrl, String token, Duration connectTimeout, Duration readTimeout) {

    private static final Duration DEFAULT_CONNECT_TIMEOUT = Duration.ofSeconds(1);
    private static final Duration DEFAULT_READ_TIMEOUT = Duration.ofSeconds(3);

    public WorkerProperties {
        if (baseUrl == null) {
            throw new IllegalStateException("investigation.worker.base-url must be set");
        }
        if (token == null || token.isBlank()) {
            throw new IllegalStateException("investigation.worker.token (INTERNAL_API_TOKEN) must be set");
        }
        connectTimeout = connectTimeout != null ? connectTimeout : DEFAULT_CONNECT_TIMEOUT;
        readTimeout = readTimeout != null ? readTimeout : DEFAULT_READ_TIMEOUT;
    }

    // A record's default toString() prints every field: never let the token reach a log line.
    @Override
    public String toString() {
        return "WorkerProperties[baseUrl=" + baseUrl + ", token=****, connectTimeout=" + connectTimeout
                + ", readTimeout=" + readTimeout + "]";
    }
}
