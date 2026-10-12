package com.sandeep.incidentplatform.repository;

import com.sandeep.incidentplatform.model.Incident;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

// Application code must use the tenant-scoped methods; Spring Data derives the SQL from the names.
public interface IncidentRepository extends JpaRepository<Incident, UUID> {

    Optional<Incident> findByIdAndTenantId(UUID id, String tenantId);

    // Pageable adds LIMIT/OFFSET and ORDER BY; Page also runs a COUNT query for the totals.
    Page<Incident> findAllByTenantId(String tenantId, Pageable pageable);
}
