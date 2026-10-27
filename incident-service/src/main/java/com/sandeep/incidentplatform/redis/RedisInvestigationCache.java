package com.sandeep.incidentplatform.redis;

import com.sandeep.incidentplatform.dto.InvestigationResponse;
import com.sandeep.incidentplatform.investigation.InvestigationStatus;
import com.sandeep.incidentplatform.observability.PlatformMetrics;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

import java.util.Optional;
import java.util.UUID;

/**
 * Cache-aside in Redis for GET /api/v1/incidents/{id}/investigation (InvestigationService decides when to
 * read and write it). Value: the public InvestigationResponse as JSON, so a hit needs no mapping.
 *
 * Key: investigation:v1:{tenantId}:{incidentId}. The tenant is part of the key, so even a bug that skipped
 * the database tenant check could not serve one tenant's investigation to another. "v1" lets a change of
 * the JSON shape start from an empty cache instead of reading old entries.
 * TTL (default 1 h) bounds memory and how long a re-run investigation (app.rerun) can be served stale.
 * Every call goes through RedisGuard: an unreachable Redis is a miss and the read goes to the worker.
 */
@Component
@ConditionalOnProperty(name = "app.redis.cache.enabled", havingValue = "true")
public class RedisInvestigationCache implements InvestigationCache {

    static final String KEY_PREFIX = "investigation:v1:";

    private final StringRedisTemplate redis;
    private final JsonMapper json;
    private final RedisGuard guard;
    private final PlatformMetrics metrics;
    private final RedisFeatureProperties properties;

    public RedisInvestigationCache(StringRedisTemplate redis, JsonMapper json, RedisGuard guard,
                                   PlatformMetrics metrics, RedisFeatureProperties properties) {
        this.redis = redis;
        this.json = json;
        this.guard = guard;
        this.metrics = metrics;
        this.properties = properties;
    }

    static String key(String tenantId, UUID incidentId) {
        return KEY_PREFIX + tenantId + ":" + incidentId;
    }

    @Override
    public Optional<InvestigationResponse> get(String tenantId, UUID incidentId) {
        Optional<InvestigationResponse> cached = guard.call("cache_get", () -> {
            String value = redis.opsForValue().get(key(tenantId, incidentId));
            return Optional.ofNullable(value).map(v -> json.readValue(v, InvestigationResponse.class));
        }, null);
        if (cached == null) {
            return Optional.empty(); // Redis unavailable: neither hit nor miss, counted in redis_errors_total
        }
        if (cached.isPresent()) {
            metrics.cacheHit("investigation");
        } else {
            metrics.cacheMiss("investigation");
        }
        return cached;
    }

    @Override
    public void putIfFinished(String tenantId, InvestigationResponse investigation) {
        InvestigationStatus status = investigation.status();
        if (status != InvestigationStatus.COMPLETED && status != InvestigationStatus.FAILED) {
            return; // PENDING/RUNNING/NOT_STARTED are never cached
        }
        guard.call("cache_put", () -> {
            redis.opsForValue().set(key(tenantId, investigation.incidentId()), json.writeValueAsString(investigation),
                    properties.cache().ttl());
            return Boolean.TRUE;
        }, Boolean.FALSE);
    }

    @Override
    public void evict(String tenantId, UUID incidentId) {
        guard.call("cache_evict", () -> redis.delete(key(tenantId, incidentId)), Boolean.FALSE);
    }
}
