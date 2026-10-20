package com.sandeep.incidentplatform.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/** What an evidence label points at: a log window, metric, runbook section or past incident. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record Citation(String label, String sourceType, String sourceId, String snippet) {
}
