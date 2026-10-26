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

        private final RateLimitInterceptor interceptor;

        RateLimitWebConfig(StringRedisTemplate redis, RedisGuard guard, PlatformMetrics metrics,
                           RedisFeatureProperties properties) {
            TenantRateLimiter limiter = new TenantRateLimiter(redis,
                    properties.rateLimit().createIncidentPerMinute(), Clock.systemUTC());
            this.interceptor = new RateLimitInterceptor(limiter, guard, metrics);
        }

        @Override
        public void addInterceptors(InterceptorRegistry registry) {
            registry.addInterceptor(interceptor).addPathPatterns("/api/v1/incidents");
        }
    }
}
