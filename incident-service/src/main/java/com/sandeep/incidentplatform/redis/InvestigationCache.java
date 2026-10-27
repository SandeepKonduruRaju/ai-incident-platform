package com.sandeep.incidentplatform.redis;

import com.sandeep.incidentplatform.dto.InvestigationResponse;

import java.util.Optional;
import java.util.UUID;

/**
 * Cache of FINISHED investigations, always keyed by tenant + incident. Only COMPLETED/FAILED answers are
 * ever stored: PENDING/RUNNING change within seconds and must always come from the worker.
 * NONE (no cache) is used when app.redis.cache.enabled=false and in slice tests.
 */
public interface InvestigationCache {

    InvestigationCache NONE = new InvestigationCache() {
        @Override
        public Optional<InvestigationResponse> get(String tenantId, UUID incidentId) {
            return Optional.empty();
        }

        @Override
        public void putIfFinished(String tenantId, InvestigationResponse investigation) {
        }

        @Override
        public void evict(String tenantId, UUID incidentId) {
        }
    };

    Optional<InvestigationResponse> get(String tenantId, UUID incidentId);

    /** Stores the answer only if it is COMPLETED or FAILED; anything else (in progress, NOT_STARTED) is ignored. */
    void putIfFinished(String tenantId, InvestigationResponse investigation);

    /** Drops the cached answer (a retry starts a new run). */
    void evict(String tenantId, UUID incidentId);
}
