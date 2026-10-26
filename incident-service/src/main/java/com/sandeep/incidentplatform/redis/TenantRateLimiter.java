package com.sandeep.incidentplatform.redis;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;

import java.time.Clock;
import java.util.List;

/**
 * Per-tenant FIXED-WINDOW rate limit in Redis: one counter per tenant per minute,
 * key ratelimit:v1:create-incident:{tenantId}:{minute}, incremented atomically by a Lua script (INCR, and
 * EXPIRE on the first hit so the key cleans itself up).
 *
 * Why fixed window (not sliding): one key and one round trip per request, O(1) memory per tenant, and an
 * exact Retry-After (seconds to the end of the window). The known cost is a burst of up to 2x the limit
 * across a window boundary (30 at 12:00:59 + 30 at 12:01:00); for a limit meant to stop runaway clients
 * and protect the worker's queue, that is acceptable. A sliding log (sorted set per tenant) has no burst
 * but stores every request; a sliding-window counter approximates it with two keys. Both add cost for
 * precision this limit does not need.
 *
 * Shared across all incident-service replicas (the counter lives in Redis), unlike an in-memory limiter.
 * Fail-open is handled by RateLimitInterceptor through RedisGuard.
 */
public class TenantRateLimiter {

    static final String KEY_PREFIX = "ratelimit:v1:create-incident:";
    static final long WINDOW_SECONDS = 60;

    private static final RedisScript<Long> INCREMENT = RedisScript.of("""
            local count = redis.call('INCR', KEYS[1])
            if count == 1 then
              redis.call('EXPIRE', KEYS[1], ARGV[1])
            end
            return count
            """, Long.class);

    /** allowed, or not with how many seconds until the window resets (Retry-After). */
    public record Decision(boolean allowed, long retryAfterSeconds) {
        static final Decision ALLOW = new Decision(true, 0);
    }

    private final StringRedisTemplate redis;
    private final int limit;
    private final Clock clock;

    public TenantRateLimiter(StringRedisTemplate redis, int limit, Clock clock) {
        this.redis = redis;
        this.limit = limit;
        this.clock = clock;
    }

    public int limit() {
        return limit;
    }

    /** Counts this request and decides. Throws on any Redis error (the caller fails open). */
    public Decision tryAcquire(String tenantId) {
        long nowSeconds = clock.instant().getEpochSecond();
        long window = nowSeconds / WINDOW_SECONDS;
        // TTL a little longer than the window: the key never expires while its window is still counting.
        Long count = redis.execute(INCREMENT, List.of(KEY_PREFIX + tenantId + ":" + window),
                String.valueOf(WINDOW_SECONDS + 5));
        if (count == null || count <= limit) {
            return Decision.ALLOW;
        }
        return new Decision(false, (window + 1) * WINDOW_SECONDS - nowSeconds);
    }
}
