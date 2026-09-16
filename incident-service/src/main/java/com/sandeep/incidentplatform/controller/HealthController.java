package com.sandeep.incidentplatform.controller;

import com.sandeep.incidentplatform.dto.HealthResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

    @GetMapping("/api/v1/health")
    public HealthResponse health() {
        return new HealthResponse("UP", "Application is running");
    }
}
