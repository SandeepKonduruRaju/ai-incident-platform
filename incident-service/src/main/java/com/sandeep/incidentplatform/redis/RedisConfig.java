package com.sandeep.incidentplatform.redis;

import com.sandeep.incidentplatform.observability.PlatformMetrics;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.time.Clock;

@Configuration
@EnableConfigurationProperties(RedisFeatureProperties.class)
public class RedisConfig {

    /** Only with app.redis.rate-limit.enabled=true (the default in application.properties; off in tests). */
    @Configuration
    @ConditionalOnProperty(name = "app.redis.rate-limit.enabled", havingValue = "true")
    static class RateLimitWebConfig implements WebMvcConfigurer {

        private final RateLimitInterceptor createIncident;
        private final RateLimitInterceptor retryInvestigation;

        // Both endpoints enqueue an LLM investigation; each gets its own per-tenant budget of the same size.
        RateLimitWebConfig(StringRedisTemplate redis, RedisGuard guard, PlatformMetrics metrics,
                           RedisFeatureProperties properties) {
            int perMinute = properties.rateLimit().createIncidentPerMinute();
            this.createIncident = new RateLimitInterceptor(new TenantRateLimiter(redis,
                    TenantRateLimiter.CREATE_INCIDENT, perMinute, Clock.systemUTC()), guard, metrics, "create_incident");
            this.retryInvestigation = new RateLimitInterceptor(new TenantRateLimiter(redis,
                    TenantRateLimiter.RETRY_INVESTIGATION, perMinute, Clock.systemUTC()), guard, metrics,
                    "retry_investigation");
        }

        @Override
        public void addInterceptors(InterceptorRegistry registry) {
            registry.addInterceptor(createIncident).addPathPatterns("/api/v1/incidents");
            registry.addInterceptor(retryInvestigation).addPathPatterns("/api/v1/incidents/*/investigation/retry");
        }
    }
}
