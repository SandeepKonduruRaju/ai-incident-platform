package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.controller.HealthController;
import com.sandeep.incidentplatform.dto.HealthResponse;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

public class HealthControllerTest {

        @Test
        void shouldReturnApplicationHealth() {
            // Arrange
            HealthController controller = new HealthController();

            // Act
            HealthResponse response = controller.health();

            // Assert
            assertEquals("UP", response.status());
            assertEquals("Application is running", response.message());
        }
}

