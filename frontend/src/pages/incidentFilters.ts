import type { Incident, IncidentStatus, Severity } from '../api/types';

export interface IncidentFilters {
  query: string; // matched against title and service, case-insensitive
  severity: Severity | '';
  status: IncidentStatus | '';
}

export const NO_FILTERS: IncidentFilters = { query: '', severity: '', status: '' };

export function filterIncidents(items: Incident[], { query, severity, status }: IncidentFilters): Incident[] {
  const needle = query.trim().toLowerCase();
  return items.filter(
    (incident) =>
      (!severity || incident.severity === severity) &&
      (!status || incident.status === status) &&
      (!needle || incident.title.toLowerCase().includes(needle) || incident.affectedService.toLowerCase().includes(needle)),
  );
}

export function isFiltered(filters: IncidentFilters): boolean {
  return Boolean(filters.query.trim() || filters.severity || filters.status);
}
