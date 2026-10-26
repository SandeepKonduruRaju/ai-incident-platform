package com.sandeep.incidentplatform.redis;

import com.sandeep.incidentplatform.observability.PlatformMetrics;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

/**
 * Runs every Redis call of the service and makes it FAIL OPEN: if Redis errors (down, timeout, bad data),
 * the caller gets its fallback (cache: "miss", rate limit: "allowed") and the request carries on.
 * Circuit breaker: only after app.redis.failure-threshold CONSECUTIVE errors is Redis considered down and skipped
 * for app.redis.failure-cooldown, so an outage costs a few short timeouts per cooldown instead of one per request.
 * A single slow call (a blip) does not open the circuit: in load tests, opening on the first timeout sent every
 * read to the worker for 5 s and overloaded it (docs/load-test.md), which is worse than the blip itself. Logs a WARN once when Redis becomes unavailable and an INFO when it
 * is back (not one line per request); every error is counted in redis_errors_total{operation}.
 */
@Component
public class RedisGuard {

    private static final Logger log = LoggerFactory.getLogger(RedisGuard.class);

    private final PlatformMetrics metrics;
    private final RedisFeatureProperties properties;
    private final Clock clock;
    // Until when Redis is skipped; null = Redis is considered available.
    private final AtomicReference<Instant> skipUntil = new AtomicReference<>();
    private final AtomicInteger consecutiveFailures = new AtomicInteger();

    @Autowired
    public RedisGuard(PlatformMetrics metrics, RedisFeatureProperties properties) {
        this(metrics, properties, Clock.systemUTC());
    }

    RedisGuard(PlatformMetrics metrics, RedisFeatureProperties properties, Clock clock) {
        this.metrics = metrics;
        this.properties = properties;
        this.clock = clock;
    }

    /** operation: low-cardinality label (cache_get, cache_put, rate_limit). */
    public <T> T call(String operation, Supplier<T> redisCall, T fallback) {
        Instant until = skipUntil.get();
        if (until != null && clock.instant().isBefore(until)) {
            return fallback; // cooling down after an error: do not even try
        }
        try {
            T result = redisCall.get();
            consecutiveFailures.set(0);
            if (until != null && skipUntil.compareAndSet(until, null)) {
                log.info("Redis is available again: cache and rate limiting resumed");
            }
            return result;
        } catch (RuntimeException e) {
            metrics.redisError(operation);
            if (consecutiveFailures.incrementAndGet() < properties.failureThreshold() && until == null) {
                return fallback; // a blip: this request falls back, the circuit stays closed
            }
            Instant next = clock.instant().plus(properties.failureCooldown());
            if (skipUntil.getAndSet(next) == null) {
                log.warn("Redis unavailable ({}: {}); failing open for {}: investigations are read from the worker "
                                + "and incident creation is NOT rate limited until Redis is back",
                        operation, e.getClass().getSimpleName(), properties.failureCooldown());
            }
            return fallback;
        }
    }
}
