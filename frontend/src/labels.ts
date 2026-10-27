// Display labels for API enums: sentence case, never the raw upper-case values.
import type { IncidentStatus, InvestigationStatus, Role, Severity } from './api/types';

export const SEVERITY_LABELS: Record<Severity, string> = { CRITICAL: 'Critical', HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' };

export const STATUS_LABELS: Record<IncidentStatus | InvestigationStatus, string> = {
  OPEN: 'Open',
  INVESTIGATING: 'Investigating',
  MITIGATED: 'Mitigated',
  RESOLVED: 'Resolved',
  PENDING: 'Pending',
  RUNNING: 'Running',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  NOT_STARTED: 'Not started',
};

export const ROLE_LABELS: Record<Role, string> = { VIEWER: 'Viewer', RESPONDER: 'Responder', ADMIN: 'Admin' };

const SOURCE_TYPE_LABELS: Record<string, string> = {
  log: 'Log',
  metric: 'Metric',
  runbook: 'Runbook',
  past_incident: 'Past incident',
};

export function sourceTypeLabel(type: string | undefined): string {
  if (!type) return 'Evidence';
  return SOURCE_TYPE_LABELS[type] ?? type.charAt(0).toUpperCase() + type.slice(1).replace(/_/g, ' ');
}
