import { useEffect, useState } from 'react';
import type { Incident } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { SeverityBadge, StatusBadge } from '../components/Badges';
import { ErrorMessage } from '../components/ErrorMessage';
import { InvestigationPanel } from '../components/InvestigationPanel';
import { Link } from '../router';
import styles from './Pages.module.css';

export function IncidentDetailPage({ id }: { id: string }) {
  const { api } = useAuth();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setIncident(null);
    setError(null);
    api
      .getIncident(id)
      .then((result) => !cancelled && setIncident(result))
      .catch((e: unknown) => !cancelled && setError(e));
    return () => {
      cancelled = true;
    };
  }, [api, id]);

  return (
    <main className={styles.page}>
      <p>
        <Link to="/incidents">← Incidents</Link>
      </p>
      {error !== null && <ErrorMessage error={error} />}
      {!incident && error === null && <p role="status">Loading incident…</p>}
      {incident && (
        <>
          <h1>{incident.title}</h1>
          <dl className={styles.facts}>
            <dt>Severity</dt>
            <dd>
              <SeverityBadge severity={incident.severity} />
            </dd>
            <dt>Status</dt>
            <dd>
              <StatusBadge status={incident.status} />
            </dd>
            <dt>Service</dt>
            <dd>{incident.affectedService}</dd>
            <dt>Created</dt>
            <dd>
              <time dateTime={incident.createdAt}>{new Date(incident.createdAt).toLocaleString()}</time>
            </dd>
          </dl>
          {incident.description && <p className={styles.description}>{incident.description}</p>}
          <InvestigationPanel api={api} incidentId={incident.id} />
        </>
      )}
    </main>
  );
}
