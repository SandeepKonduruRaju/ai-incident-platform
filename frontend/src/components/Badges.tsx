// Severity and status as words with a small indicator (never colour alone), in sentence case.
import type { IncidentStatus, InvestigationStatus, Severity } from '../api/types';
import { SEVERITY_LABELS, STATUS_LABELS } from '../labels';
import styles from './Badges.module.css';

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`${styles.severity} ${styles[`severity_${severity}`]}`}>
      <span className={styles.bar} aria-hidden="true" />
      {SEVERITY_LABELS[severity]}
    </span>
  );
}

export function StatusBadge({ status }: { status: IncidentStatus | InvestigationStatus }) {
  return (
    <span className={`${styles.status} ${styles[`status_${status}`] ?? ''}`}>
      <span className={styles.dot} aria-hidden="true" />
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
