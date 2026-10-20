package com.sandeep.incidentplatform.dto;

import java.util.List;

/** One statement of the investigation and the evidence labels (C1, C2, ...) it is based on. */
public record Finding(String text, List<String> citations) {
}
