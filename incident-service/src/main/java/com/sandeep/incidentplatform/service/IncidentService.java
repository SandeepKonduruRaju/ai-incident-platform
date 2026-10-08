package com.sandeep.incidentplatform.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.repository.IncidentRepository;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.Optional;

@Service
public class IncidentService {

    private final IncidentRepository incidentRepository;

    public IncidentService(IncidentRepository incidentRepository) {
        this.incidentRepository = incidentRepository;
    }

    public Incident create(CreateIncidentRequest request) {
        Incident incident = new Incident(
                UUID.randomUUID(),
                request.title(),
                request.description(),
                request.severity(),
                // every new incident starts OPEN
                IncidentStatus.OPEN,
                request.affectedService(),
                Instant.now()
        );

        return incidentRepository.save(incident);
    }

    public Optional<Incident> findById(UUID id) {
        return incidentRepository.findById(id);
    }

    public List<Incident> findAll() {
        return incidentRepository.findAll();
    }

    // Load -> change -> commit. The loaded entity is managed inside this transaction, so
    // Hibernate's dirty checking writes the new status on commit; no explicit save() needed.
    @Transactional
    public Optional<Incident> updateStatus(UUID id, IncidentStatus status) {
        return incidentRepository.findById(id)
                .map(incident -> {
                    incident.changeStatus(status);
                    return incident;
                });
    }
}
