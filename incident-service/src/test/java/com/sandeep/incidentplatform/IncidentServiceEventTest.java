package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.event.IncidentCreatedEvent;
import com.sandeep.incidentplatform.event.KafkaTopics;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.outbox.OutboxEvent;
import com.sandeep.incidentplatform.outbox.OutboxEventRepository;
import com.sandeep.incidentplatform.repository.IncidentRepository;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.when;

// Unit test: both repositories are Mockito mocks, so no Spring, no database, no Kafka.
@ExtendWith(MockitoExtension.class)
class IncidentServiceEventTest {

    private static final String TENANT = "acme";

    private final JsonMapper jsonMapper = JsonMapper.builder().build();

    @Mock
    private IncidentRepository incidentRepository;

    @Mock
    private OutboxEventRepository outboxEventRepository;

    @Test
    void shouldSaveIncidentAndOutboxRowWithTheEvent() {
        // Arrange: save() returns whatever it is given, like a real repository
        when(incidentRepository.save(any(Incident.class))).thenAnswer(call -> call.getArgument(0));
        IncidentService service = new IncidentService(incidentRepository, outboxEventRepository, jsonMapper);
        CreateIncidentRequest request = new CreateIncidentRequest(
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                "payment-service"
        );

        // Act
        Incident incident = service.create(TENANT, request);

        // Assert: the incident is saved, then its outbox row (both in create()'s one transaction)
        InOrder order = inOrder(incidentRepository, outboxEventRepository);
        order.verify(incidentRepository).save(incident);
        ArgumentCaptor<OutboxEvent> captor = ArgumentCaptor.forClass(OutboxEvent.class);
        order.verify(outboxEventRepository).save(captor.capture());

        OutboxEvent row = captor.getValue();
        assertEquals(IncidentCreatedEvent.TYPE, row.eventType());
        assertEquals(incident.id(), row.aggregateId());
        assertEquals(KafkaTopics.INCIDENT_EVENTS, row.topic());
        assertNotNull(row.createdAt());
        assertNull(row.publishedAt(), "a new row is unsent");
        assertEquals(0, row.attempts());

        // The payload is the event as JSON, and its eventId is the row's id
        IncidentCreatedEvent event = jsonMapper.readValue(row.payload(), IncidentCreatedEvent.class);
        assertEquals(row.id(), event.eventId());
        assertNotEquals(incident.id(), event.eventId(), "eventId identifies the event, not the incident");
        assertEquals(IncidentCreatedEvent.TYPE, event.eventType());
        assertEquals(IncidentCreatedEvent.CURRENT_VERSION, event.schemaVersion());
        assertEquals(TENANT, event.tenantId());
        assertEquals(incident.id(), event.payload().incidentId());
        assertEquals("payment-service", event.payload().affectedService());
    }
}
