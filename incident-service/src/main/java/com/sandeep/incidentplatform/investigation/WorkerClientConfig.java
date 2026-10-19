package com.sandeep.incidentplatform.investigation;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
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
    WorkerInvestigationClient workerInvestigationClient(WorkerProperties properties) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(properties.connectTimeout());
        requestFactory.setReadTimeout(properties.readTimeout());
        return new WorkerInvestigationClient(RestClient.builder().requestFactory(requestFactory), properties);
    }
}
