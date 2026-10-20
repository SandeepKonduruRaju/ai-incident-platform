package com.sandeep.incidentplatform.investigation;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import com.sandeep.incidentplatform.observability.PlatformMetrics;
import io.micrometer.observation.ObservationRegistry;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
@EnableConfigurationProperties(WorkerProperties.class)
public class WorkerClientConfig {

    // Short timeouts: a user is waiting on this call. Connect ~1s (is the worker there at all?),
    // read ~3s (the endpoint is a single indexed query). Slower than that becomes a 503 + Retry-After.
    @Bean
    WorkerInvestigationClient workerInvestigationClient(WorkerProperties properties, PlatformMetrics metrics,
                                                        ObservationRegistry observationRegistry) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(properties.connectTimeout());
        requestFactory.setReadTimeout(properties.readTimeout());
        // observationRegistry: a client span per call, and its traceparent header goes to the worker.
        RestClient.Builder builder = RestClient.builder()
                .requestFactory(requestFactory)
                .observationRegistry(observationRegistry);
        return new WorkerInvestigationClient(builder, properties, metrics);
    }
}
