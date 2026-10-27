package com.sandeep.incidentplatform.service;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.exception.IdempotencyKeyReusedException;
import com.sandeep.incidentplatform.model.Incident;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import java.util.Objects;
import java.util.Optional;

/**
 * POST /api/v1/incidents with an Idempotency-Key: a client that retries after a timeout (it cannot know whether the
 * first request was saved) gets the incident the first request created, not a second incident and a second paid
 * investigation.
 *
 *   no key                         -> create (201), as before
 *   key new for this tenant        -> create (201), the key is stored with the incident
 *   key seen, same request body    -> the original incident (replayed = true; 200), no new row, no new outbox event
 *   key seen, different body       -> IdempotencyKeyReusedException (422)
 *
 * Race: two requests with the same new key both miss the lookup; the unique (tenant_id, idempotency_key) index lets
 * one insert win, the other's transaction fails as a whole (incident AND outbox event rolled back) and it answers
 * with the winner's incident. Deliberately NOT @Transactional: the failed insert's transaction must be over (rolled
 * back) before the winner is read.
 */
@Service
public class IdempotentIncidentCreator {

    private final IncidentService incidentService;

    public IdempotentIncidentCreator(IncidentService incidentService) {
        this.incidentService = incidentService;
    }

    public record Result(Incident incident, boolean replayed) {
    }

    public Result create(String tenantId, CreateIncidentRequest request, String idempotencyKey) {
        if (idempotencyKey == null) {
            return new Result(incidentService.create(tenantId, request), false);
        }
        Optional<Incident> existing = incidentService.findByIdempotencyKey(tenantId, idempotencyKey);
        if (existing.isPresent()) {
            return replay(existing.get(), request);
        }
        try {
            return new Result(incidentService.create(tenantId, request, idempotencyKey), false);
        } catch (DataIntegrityViolationException raceLost) {
            Incident winner = incidentService.findByIdempotencyKey(tenantId, idempotencyKey).orElseThrow(() -> raceLost);
            return replay(winner, request);
        }
    }

    private static Result replay(Incident original, CreateIncidentRequest request) {
        if (!sameRequest(original, request)) {
            throw new IdempotencyKeyReusedException();
        }
        return new Result(original, true);
    }

    private static boolean sameRequest(Incident incident, CreateIncidentRequest request) {
        return Objects.equals(incident.title(), request.title())
                && Objects.equals(incident.description(), request.description())
                && incident.severity() == request.severity()
                && Objects.equals(incident.affectedService(), request.affectedService());
    }
}
