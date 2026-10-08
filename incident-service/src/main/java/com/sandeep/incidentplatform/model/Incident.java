package com.sandeep.incidentplatform.model;

import java.time.Instant;
import java.util.UUID;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Version;

@Entity
@Table(name = "incidents")
public class Incident {

    @Id
    private UUID id;

    @Column(nullable = false)
    private String title;

    @Column(length = 2000)
    private String description;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private IncidentSeverity severity;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private IncidentStatus status;

    @Column(nullable = false)
    private String affectedService;

    @Column(nullable = false)
    private Instant createdAt;

    // Optimistic locking: concurrent updates to the same row fail instead of silently overwriting.
    // Also lets Spring Data treat a null version as "new", so save() inserts without a SELECT first.
    @Version
    private Long version;

    protected Incident() {
        // Required by JPA.
    }

    public Incident(UUID id, String title, String description,
                    IncidentSeverity severity, IncidentStatus status,
                    String affectedService, Instant createdAt) {
        this.id = id;
        this.title = title;
        this.description = description;
        this.severity = severity;
        this.status = status;
        this.affectedService = affectedService;
        this.createdAt = createdAt;
    }

    public UUID id() {
        return id;
    }

    public String title() {
        return title;
    }

    public String description() {
        return description;
    }

    public IncidentSeverity severity() {
        return severity;
    }

    public IncidentStatus status() {
        return status;
    }

    public String affectedService() {
        return affectedService;
    }

    public Instant createdAt() {
        return createdAt;
    }

    public void changeStatus(IncidentStatus newStatus) {
        if (newStatus == null) {
            throw new IllegalArgumentException("status must not be null");
        }
        this.status = newStatus;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof Incident incident)) {
            return false;
        }
        return id != null && id.equals(incident.id);
    }

    @Override
    public int hashCode() {
        return id == null ? 0 : id.hashCode();
    }
}
