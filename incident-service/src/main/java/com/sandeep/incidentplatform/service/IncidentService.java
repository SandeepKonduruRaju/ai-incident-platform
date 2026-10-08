package com.sandeep.incidentplatform.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.repository.IncidentRepository;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;
import java.util.Optional;

/**
 * Every method is scoped to a tenant. The tenantId always comes from the caller's verified JWT
 * (see TenantResolver), never from the request body, so one tenant can never read or change
 * another tenant's incidents: such an incident simply looks "not found".
 */
@Service
public class IncidentService {

    private final IncidentRepository incidentRepository;

    public IncidentService(IncidentRepository incidentRepository) {
        this.incidentRepository = incidentRepository;
    }

    public Incident create(String tenantId, CreateIncidentRequest request) {
        Incident incident = new Incident(
                UUID.randomUUID(),
                tenantId,
                request.title(),
                request.description(),
                request.severity(),
                // every new incident starts OPEN
                IncidentStatus.OPEN,
                request.affectedService(),
                // PostgreSQL stores microseconds; truncate so the POST response matches later GETs
                Instant.now().truncatedTo(ChronoUnit.MICROS)
        );

        return incidentRepository.save(incident);
    }

    public Optional<Incident> findById(String tenantId, UUID id) {
        return incidentRepository.findByIdAndTenantId(id, tenantId);
    }

    public List<Incident> findAll(String tenantId) {
        return incidentRepository.findAllByTenantIdOrderByCreatedAtDesc(tenantId);
    }

    // Load -> change -> commit. The loaded entity is managed inside this transaction, so
    // Hibernate's dirty checking writes the new status on commit; no explicit save() needed.
    @Transactional
    public Optional<Incident> updateStatus(String tenantId, UUID id, IncidentStatus status) {
        return incidentRepository.findByIdAndTenantId(id, tenantId)
                .map(incident -> {
                    incident.changeStatus(status);
                    return incident;
                });
    }
}
