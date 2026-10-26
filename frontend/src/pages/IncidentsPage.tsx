import { useEffect, useState } from 'react';
import type { Incident, Page } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { SeverityBadge, StatusBadge } from '../components/Badges';
import { ErrorMessage } from '../components/ErrorMessage';
import { Link } from '../router';
import styles from './Pages.module.css';

export const PAGE_SIZE = 20;

/** Newest first (the API's order), PAGE_SIZE per page; the page number is in the URL (?page=n). */
export function IncidentsPage({ page }: { page: number }) {
  const { api, session } = useAuth();
  const [data, setData] = useState<Page<Incident> | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .listIncidents(page, PAGE_SIZE)
      .then((result) => !cancelled && setData(result))
      .catch((e: unknown) => !cancelled && setError(e));
    return () => {
      cancelled = true;
    };
  }, [api, page]);

  const canCreate = session?.role !== 'VIEWER';
  return (
    <main className={styles.page}>
      <div className={styles.titleRow}>
        <h1>Incidents</h1>
        {canCreate && (
          <Link to="/incidents/new" className={styles.primaryLink}>
            New incident
          </Link>
        )}
      </div>

      {error !== null && <ErrorMessage error={error} />}
      {!data && error === null && <p role="status">Loading incidents…</p>}
      {data && data.items.length === 0 && <p>No incidents yet{canCreate ? ': create the first one.' : '.'}</p>}

      {data && data.items.length > 0 && (
        <>
          <table className={styles.table}>
            <caption className={styles.visuallyHidden}>Incidents, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Title</th>
                <th scope="col">Severity</th>
                <th scope="col">Status</th>
                <th scope="col" className={styles.hideSmall}>Service</th>
                <th scope="col" className={styles.hideSmall}>Created</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((incident) => (
                <tr key={incident.id}>
                  <td>
                    <Link to={`/incidents/${incident.id}`}>{incident.title}</Link>
                  </td>
                  <td>
                    <SeverityBadge severity={incident.severity} />
                  </td>
                  <td>
                    <StatusBadge status={incident.status} />
                  </td>
                  <td className={styles.hideSmall}>{incident.affectedService}</td>
                  <td className={styles.hideSmall}>
                    <time dateTime={incident.createdAt}>{new Date(incident.createdAt).toLocaleString()}</time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <nav className={styles.pager} aria-label="Pagination">
            {page > 0 ? <Link to={`/incidents?page=${page - 1}`}>← Newer</Link> : <span />}
            <span>
              Page {data.page + 1} of {Math.max(data.totalPages, 1)} · {data.totalElements} incidents
            </span>
            {page + 1 < data.totalPages ? <Link to={`/incidents?page=${page + 1}`}>Older →</Link> : <span />}
          </nav>
        </>
      )}
    </main>
  );
}
