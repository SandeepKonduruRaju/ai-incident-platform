import type { IncidentStatus, InvestigationStatus, Severity } from '../api/types';
import styles from './Badges.module.css';

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`${styles.badge} ${styles[`severity_${severity}`]}`}>{severity}</span>;
}

export function StatusBadge({ status }: { status: IncidentStatus | InvestigationStatus }) {
  return <span className={`${styles.badge} ${styles.status} ${styles[`status_${status}`] ?? ''}`}>{status}</span>;
}
