package com.sandeep.incidentplatform.repository;

import com.sandeep.incidentplatform.model.Incident;
import jakarta.persistence.LockModeType;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;
import java.util.UUID;

// Application code must use the tenant-scoped methods; Spring Data derives the SQL from the names.
public interface IncidentRepository extends JpaRepository<Incident, UUID> {

    Optional<Incident> findByIdAndTenantId(UUID id, String tenantId);

    Optional<Incident> findByTenantIdAndIdempotencyKey(String tenantId, String idempotencyKey);

    // SELECT ... FOR UPDATE: serialises concurrent investigation retries of one incident (IncidentService).
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select i from Incident i where i.id = :id and i.tenantId = :tenantId")
    Optional<Incident> lockByIdAndTenantId(@Param("id") UUID id, @Param("tenantId") String tenantId);

    // Pageable adds LIMIT/OFFSET and ORDER BY; Page also runs a COUNT query for the totals.
    Page<Incident> findAllByTenantId(String tenantId, Pageable pageable);
}
