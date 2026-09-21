package com.sandeep.incidentplatform.service;

import org.springframework.stereotype.Service;
import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentStatus;


import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.Optional;

@Service
public class IncidentService {

    private final Map<UUID, Incident> incidents = new ConcurrentHashMap<>();

    public Incident create(CreateIncidentRequest request) {
        Incident incident = new Incident(
                // generated ID,
                UUID.randomUUID(),
                // request title,
                request.title(),
                // request description,
                request.description(),
                // request severity,
                request.severity(),
                // initial status,
                IncidentStatus.OPEN,
                // request affected service,
                request.affectedService(),
                // current timestamp
                Instant.now()
        );

        incidents.put(incident.id(), incident);

        return incident;
    }

    public Optional<Incident> findById(UUID id) {
        return Optional.ofNullable(incidents.get(id));
    }
}

