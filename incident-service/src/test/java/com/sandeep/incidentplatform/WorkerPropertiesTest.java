package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.investigation.WorkerProperties;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class WorkerPropertiesTest {

    private static final URI BASE_URL = URI.create("http://localhost:8001");

    @Test
    void missingOrBlankTokenStopsTheAppAtStartup() {
        assertThatThrownBy(() -> new WorkerProperties(BASE_URL, null, null, null))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("INTERNAL_API_TOKEN");
        assertThatThrownBy(() -> new WorkerProperties(BASE_URL, "  ", null, null))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void timeoutsDefaultToOneAndThreeSeconds() {
        WorkerProperties properties = new WorkerProperties(BASE_URL, "dev-token", null, null);

        assertThat(properties.connectTimeout()).isEqualTo(Duration.ofSeconds(1));
        assertThat(properties.readTimeout()).isEqualTo(Duration.ofSeconds(3));
    }

    @Test
    void toStringNeverShowsTheToken() {
        WorkerProperties properties = new WorkerProperties(BASE_URL, "super-secret-token", null, null);

        assertThat(properties.toString()).doesNotContain("super-secret-token").contains("token=****");
    }
}
