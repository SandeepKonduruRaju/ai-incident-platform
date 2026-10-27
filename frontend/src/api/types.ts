// Hand-written from the incident-service DTOs (milestone 4B). Source of truth, by file:
//   dto/IncidentResponse, dto/CreateIncidentRequest, dto/PageResponse, dto/InvestigationResponse, dto/Finding,
//   dto/Citation, model/IncidentSeverity, model/IncidentStatus, investigation/InvestigationStatus, security/Role,
//   security/DevTokenController (TokenRequest/TokenResponse), exception/GlobalExceptionHandler (ProblemDetail).
// Hand-written (not generated from OpenAPI) because the API is small and stable, and adding springdoc to a
// Spring Boot 4 service only for this would add a dependency and a public /v3/api-docs endpoint to secure.

export const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const;
export type Severity = (typeof SEVERITIES)[number];

export const INCIDENT_STATUSES = ['OPEN', 'INVESTIGATING', 'MITIGATED', 'RESOLVED'] as const;
export type IncidentStatus = (typeof INCIDENT_STATUSES)[number];

export const ROLES = ['VIEWER', 'RESPONDER', 'ADMIN'] as const;
export type Role = (typeof ROLES)[number];

// NOT_STARTED: no run exists and none is on its way (decided by incident-service); retryable, like FAILED.
export type InvestigationStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'NOT_STARTED';

export interface Incident {
  id: string;
  title: string;
  description: string | null;
  severity: Severity;
  status: IncidentStatus;
  affectedService: string;
  createdAt: string; // ISO-8601 instant
}

export interface CreateIncidentRequest {
  title: string;
  description?: string;
  severity: Severity;
  affectedService: string;
}

export interface Page<T> {
  items: T[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
}

export interface Finding {
  text: string;
  citations: string[]; // evidence labels, e.g. ["C1", "C3"]
}

export interface Citation {
  label: string; // "C1"
  sourceType?: string; // log, metric, runbook, past_incident
  sourceId?: string;
  snippet?: string;
}

/** Null fields are omitted by the API (@JsonInclude NON_NULL): a PENDING answer has only incidentId and status. */
export interface Investigation {
  incidentId: string;
  status: InvestigationStatus;
  summary?: string;
  confidence?: string;
  rootCause?: Finding;
  contributingFactors?: Finding[];
  remediation?: Finding[];
  citations?: Citation[];
  model?: string;
  promptVersion?: string;
  createdAt?: string;
  completedAt?: string;
  failureReason?: string;
}

export interface TokenRequest {
  subject: string;
  tenantId: string;
  roles: Role[];
}

export interface TokenResponse {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
}

/** RFC 9457 Problem Details as produced by GlobalExceptionHandler (application/problem+json). */
export interface ProblemDetail {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  requestId?: string; // 500 and 503
  errors?: { field: string; message: string }[]; // 400 validation
  limitPerMinute?: number; // 429
}
