package com.sandeep.incidentplatform.repository;

import com.sandeep.incidentplatform.model.Incident;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.UUID;

public interface IncidentRepository extends JpaRepository<Incident, UUID> {
}
