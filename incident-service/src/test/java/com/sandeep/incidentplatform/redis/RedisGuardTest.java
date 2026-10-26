package com.sandeep.incidentplatform.redis;

import com.sandeep.incidentplatform.observability.PlatformMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.dao.QueryTimeoutException;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(OutputCaptureExtension.class)
class RedisGuardTest {

    private final SimpleMeterRegistry meters = new SimpleMeterRegistry();
    private final MutableClock clock = new MutableClock();
    // Down after 3 consecutive errors, then skipped for 5 s.
    private final RedisGuard guard = new RedisGuard(new PlatformMetrics(meters),
            new RedisFeatureProperties(null, null, 3, Duration.ofSeconds(5)), clock);
    private final AtomicInteger redisCalls = new AtomicInteger();

    private final Supplier<String> down = () -> {
        redisCalls.incrementAndGet();
        throw new QueryTimeoutException("Redis command timed out");
    };
    private final Supplier<String> up = () -> {
        redisCalls.incrementAndGet();
        return "value";
    };

    @Test
    void aSingleSlowCallFallsBackForThatRequestOnlyAndDoesNotOpenTheCircuit(CapturedOutput output) {
        assertThat(guard.call("cache_get", down, "fallback")).isEqualTo("fallback");
        assertThat(guard.call("cache_get", down, "fallback")).isEqualTo("fallback");
        assertThat(guard.call("cache_get", up, "fallback")).isEqualTo("value"); // still tried: circuit closed
        assertThat(guard.call("cache_get", down, "fallback")).isEqualTo("fallback"); // count restarted at 1
        assertThat(guard.call("cache_get", up, "fallback")).isEqualTo("value");

        assertThat(redisCalls).hasValue(5);
        assertThat(meters.counter("redis.errors", "operation", "cache_get").count()).isEqualTo(3);
        assertThat(output.getOut()).doesNotContain("Redis unavailable");
    }

    @Test
    void afterConsecutiveErrorsRedisIsSkippedForTheCooldownThenProbedAgain(CapturedOutput output) {
        for (int i = 0; i < 3; i++) {
            guard.call("cache_get", down, "fallback"); // the third opens the circuit
        }
        clock.advance(Duration.ofSeconds(2));
        assertThat(guard.call("cache_get", up, "fallback")).isEqualTo("fallback"); // open: not even tried
        assertThat(redisCalls).hasValue(3);

        clock.advance(Duration.ofSeconds(4)); // cooldown over: one probe, still down -> open again at once
        assertThat(guard.call("rate_limit", down, "fallback")).isEqualTo("fallback");
        assertThat(guard.call("cache_get", up, "fallback")).isEqualTo("fallback");
        assertThat(redisCalls).hasValue(4);

        clock.advance(Duration.ofSeconds(6));
        assertThat(guard.call("cache_get", up, "fallback")).isEqualTo("value"); // recovered

        assertThat(meters.counter("redis.errors", "operation", "cache_get").count()).isEqualTo(3);
        assertThat(meters.counter("redis.errors", "operation", "rate_limit").count()).isEqualTo(1);
        // One WARN for the outage (not one per failure), one INFO when Redis is back.
        assertThat(output.getOut().split("Redis unavailable", -1)).hasSize(2);
        assertThat(output.getOut()).contains("Redis is available again");
    }

    private static final class MutableClock extends Clock {
        private Instant now = Instant.parse("2026-10-26T12:00:00Z");

        void advance(Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public Instant instant() {
            return now;
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }
    }
}
