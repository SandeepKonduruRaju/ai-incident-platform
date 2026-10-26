package com.sandeep.incidentplatform.redis;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * What the service uses Redis for (app.redis.*), milestone 4. The connection itself is Spring Boot's
 * spring.data.redis.* (host, port, short timeouts). Redis is an optimisation, never a dependency:
 * every feature here falls back to the behaviour without Redis when it is unreachable (see RedisGuard).
 *
 * @param cache           cache-aside for finished (COMPLETED/FAILED) investigations
 * @param rateLimit       per-tenant limit on POST /api/v1/incidents
 * @param failureThreshold consecutive Redis errors before Redis is considered down (default 5). Fewer = a blip:
 *                         only the failing request falls back, the next one uses Redis again
 * @param failureCooldown  once down, how long to skip Redis entirely (so an outage costs a few timeouts per
 *                         cooldown, not one per request)
 */
@ConfigurationProperties("app.redis")
public record RedisFeatureProperties(Cache cache, RateLimit rateLimit, int failureThreshold, Duration failureCooldown) {

    public RedisFeatureProperties {
        cache = cache != null ? cache : new Cache(false, null);
        rateLimit = rateLimit != null ? rateLimit : new RateLimit(false, 0);
        failureThreshold = failureThreshold > 0 ? failureThreshold : 5;
        failureCooldown = failureCooldown != null ? failureCooldown : Duration.ofSeconds(5);
    }

    /** ttl: how long a finished investigation is served from Redis (default 1 h). */
    public record Cache(boolean enabled, Duration ttl) {
        public Cache {
            ttl = ttl != null ? ttl : Duration.ofHours(1);
        }
    }

    /** createIncidentPerMinute: incidents one tenant may create per (fixed, one-minute) window. Default 30. */
    public record RateLimit(boolean enabled, int createIncidentPerMinute) {
        public RateLimit {
            createIncidentPerMinute = createIncidentPerMinute > 0 ? createIncidentPerMinute : 30;
        }
    }
}
