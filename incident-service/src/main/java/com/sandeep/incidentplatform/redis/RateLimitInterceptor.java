package com.sandeep.incidentplatform.redis;

import com.sandeep.incidentplatform.exception.RateLimitExceededException;
import com.sandeep.incidentplatform.observability.PlatformMetrics;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.servlet.HandlerInterceptor;

import static com.sandeep.incidentplatform.security.TenantResolver.TENANT_CLAIM;

/**
 * Applies a TenantRateLimiter to one POST endpoint (POST /api/v1/incidents, and POST .../investigation/retry with its
 * own budget: both enqueue an LLM investigation). Runs after Spring Security (an interceptor sits inside
 * the DispatcherServlet), so only authenticated, authorised callers are counted, by the tenant of their JWT.
 * Over the limit: RateLimitExceededException, which GlobalExceptionHandler turns into 429 + Retry-After.
 *
 * FAILS OPEN: if Redis is unavailable the request is allowed (WARN log + redis_errors_total{operation=
 * "rate_limit"}, see RedisGuard). The limit protects the system from runaway clients; refusing every
 * incident while a cache is down would turn a Redis outage into an outage of the core write path.
 */
public class RateLimitInterceptor implements HandlerInterceptor {

    private final TenantRateLimiter limiter;
    private final RedisGuard guard;
    private final PlatformMetrics metrics;
    private final String endpoint; // metric label: create_incident, retry_investigation

    public RateLimitInterceptor(TenantRateLimiter limiter, RedisGuard guard, PlatformMetrics metrics, String endpoint) {
        this.limiter = limiter;
        this.guard = guard;
        this.metrics = metrics;
        this.endpoint = endpoint;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if (!"POST".equals(request.getMethod())) {
            return true;
        }
        String tenantId = tenantOfCaller();
        if (tenantId == null) {
            return true; // not reachable through security; nothing to count against
        }
        TenantRateLimiter.Decision decision = guard.call("rate_limit", () -> limiter.tryAcquire(tenantId),
                TenantRateLimiter.Decision.ALLOW);
        if (!decision.allowed()) {
            metrics.rateLimited(endpoint);
            throw new RateLimitExceededException(limiter.limit(), decision.retryAfterSeconds());
        }
        return true;
    }

    private static String tenantOfCaller() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof Jwt jwt) {
            String tenantId = jwt.getClaimAsString(TENANT_CLAIM);
            return tenantId == null || tenantId.isBlank() ? null : tenantId;
        }
        return null;
    }
}
