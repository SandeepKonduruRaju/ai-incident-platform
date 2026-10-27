import { useEffect, useState } from 'react';
import type { Incident } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { SeverityBadge, StatusBadge } from '../components/Badges';
import { ErrorMessage } from '../components/ErrorMessage';
import { InvestigationPanel } from '../components/InvestigationPanel';
import { formatDateTime, formatFullDateTime } from '../format';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { Link } from '../router';
import styles from './Detail.module.css';
import pages from './Pages.module.css';

export function IncidentDetailPage({ id }: { id: string }) {
  const { api, session } = useAuth();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [error, setError] = useState<unknown>(null);
  useDocumentTitle(incident?.title);

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
    <main>
      <p className={pages.back}>
        <Link to="/incidents" className={pages.secondary}>
          Incidents
        </Link>
      </p>
      {error !== null && <ErrorMessage error={error} />}
      {!incident && error === null && (
        <p role="status" className={pages.muted}>
          Loading incident…
        </p>
      )}
      {incident && (
        <InvestigationPanel
          key={incident.id}
          api={api}
          incidentId={incident.id}
          canRetry={session?.role !== 'VIEWER'}
          intro={<IncidentFacts incident={incident} />}
        />
      )}
    </main>
  );
}

function IncidentFacts({ incident }: { incident: Incident }) {
  return (
    <>
      <h1 className={styles.title}>{incident.title}</h1>
      <dl className={styles.facts}>
        <div>
          <dt>Severity</dt>
          <dd>
            <SeverityBadge severity={incident.severity} />
          </dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <StatusBadge status={incident.status} />
          </dd>
        </div>
        <div>
          <dt>Service</dt>
          <dd>{incident.affectedService}</dd>
        </div>
        <div>
          <dt>Reported</dt>
          <dd>
            <time dateTime={incident.createdAt} title={formatFullDateTime(incident.createdAt)}>
              {formatDateTime(incident.createdAt)}
            </time>
          </dd>
        </div>
      </dl>
      {incident.description && <p className={styles.description}>{incident.description}</p>}
    </>
  );
}
