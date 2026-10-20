package com.sandeep.incidentplatform.outbox;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

/**
 * outbox_backlog: rows not yet sent to Kafka. Evaluated on each Prometheus scrape (one indexed COUNT
 * every scrape interval). A growing backlog means Kafka is down or the relay is stuck.
 */
@Component
public class OutboxMetrics {

    public OutboxMetrics(MeterRegistry registry, OutboxEventRepository repository) {
        Gauge.builder("outbox.backlog", repository, OutboxEventRepository::countByPublishedAtIsNull)
                .description("Outbox rows waiting to be sent to Kafka")
                .register(registry);
    }
}
