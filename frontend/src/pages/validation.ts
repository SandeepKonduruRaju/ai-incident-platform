// Client-side validation, the same rules as CreateIncidentRequest (@NotBlank @Size(max = 255) title, @Size(max = 2000)
// description, @NotNull severity, @NotBlank @Size(max = 255) affectedService). The server still validates: its 400
// field errors are shown the same way.
import { SEVERITIES, type CreateIncidentRequest } from '../api/types';

export interface IncidentForm {
  title: string;
  description: string;
  severity: string;
  affectedService: string;
}

export const LIMITS = { title: 255, description: 2000, affectedService: 255 } as const;

export function validateIncident(form: IncidentForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.title.trim()) errors.title = 'Title is required.';
  else if (form.title.length > LIMITS.title) errors.title = `Title must be at most ${LIMITS.title} characters.`;
  if (form.description.length > LIMITS.description) {
    errors.description = `Description must be at most ${LIMITS.description} characters.`;
  }
  if (!(SEVERITIES as readonly string[]).includes(form.severity)) errors.severity = 'Choose a severity.';
  if (!form.affectedService.trim()) errors.affectedService = 'Affected service is required.';
  else if (form.affectedService.length > LIMITS.affectedService) {
    errors.affectedService = `Affected service must be at most ${LIMITS.affectedService} characters.`;
  }
  return errors;
}

export function toRequest(form: IncidentForm): CreateIncidentRequest {
  return {
    title: form.title.trim(),
    description: form.description.trim() || undefined,
    severity: form.severity as CreateIncidentRequest['severity'],
    affectedService: form.affectedService.trim(),
  };
}
