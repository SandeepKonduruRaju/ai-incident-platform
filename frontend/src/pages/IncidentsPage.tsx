import { useEffect, useMemo, useState } from 'react';
import { INCIDENT_STATUSES, SEVERITIES, type Incident, type Page } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { SeverityBadge, StatusBadge } from '../components/Badges';
import { ErrorMessage } from '../components/ErrorMessage';
import { formatFullDateTime, formatRelative } from '../format';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { SEVERITY_LABELS, STATUS_LABELS } from '../labels';
import { Link } from '../router';
import { NO_FILTERS, filterIncidents, isFiltered, type IncidentFilters } from './incidentFilters';
import styles from './Incidents.module.css';
import pages from './Pages.module.css';

/** The API's maximum page size: search and filters run in the browser over the incidents of the loaded page. */
export const PAGE_SIZE = 100;

/** Newest first (the API's order), PAGE_SIZE per page; the page number is in the URL (?page=n). */
export function IncidentsPage({ page }: { page: number }) {
  const { api, session } = useAuth();
  const [data, setData] = useState<Page<Incident> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filters, setFilters] = useState<IncidentFilters>(NO_FILTERS);
  useDocumentTitle('Incidents');

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

  const visible = useMemo(() => (data ? filterIncidents(data.items, filters) : []), [data, filters]);
  const canCreate = session?.role !== 'VIEWER';
  const tenantIsEmpty = data !== null && data.totalElements === 0;

  return (
    <main>
      <div className={pages.titleRow}>
        <h1>Incidents</h1>
        {canCreate && !tenantIsEmpty && (
          <Link to="/incidents/new" className={pages.primaryLink}>
            Report an incident
          </Link>
        )}
      </div>

      {error !== null && <ErrorMessage error={error} />}
      {!data && error === null && (
        <p role="status" className={pages.muted}>
          Loading incidents…
        </p>
      )}

      {tenantIsEmpty && (
        <div className={styles.empty}>
          <h2>No incidents yet</h2>
          <p>Incidents reported for this tenant will appear here, newest first.</p>
          {canCreate && (
            <Link to="/incidents/new" className={pages.primaryLink}>
              Report an incident
            </Link>
          )}
        </div>
      )}

      {data && !tenantIsEmpty && (
        <>
          <Filters filters={filters} onChange={setFilters} />
          <p className={styles.count} role="status">
            {isFiltered(filters)
              ? `${visible.length} of ${data.items.length} incidents on this page match.`
              : `${data.totalElements} incidents, newest first.`}
          </p>

          {visible.length === 0 ? (
            <div className={styles.empty}>
              <h2>No incidents match</h2>
              <p>Try a different search, or clear the filters.</p>
              <button type="button" className={pages.secondary} onClick={() => setFilters(NO_FILTERS)}>
                Clear filters
              </button>
            </div>
          ) : (
            <ul className={styles.list} aria-label="Incidents">
              {visible.map((incident) => (
                <IncidentRow key={incident.id} incident={incident} />
              ))}
            </ul>
          )}

          {data.totalPages > 1 && (
            <nav className={styles.pager} aria-label="Pagination">
              {page > 0 ? (
                <Link to={`/incidents?page=${page - 1}`} className={pages.secondary}>
                  Newer
                </Link>
              ) : (
                <span />
              )}
              <span>
                Page {data.page + 1} of {data.totalPages}
              </span>
              {page + 1 < data.totalPages ? (
                <Link to={`/incidents?page=${page + 1}`} className={pages.secondary}>
                  Older
                </Link>
              ) : (
                <span />
              )}
            </nav>
          )}
        </>
      )}
    </main>
  );
}

/** The whole row is the link target (the title link stretches over it); Tab reaches one link per row. */
function IncidentRow({ incident }: { incident: Incident }) {
  return (
    <li className={`${styles.row} ${styles[`sev_${incident.severity}`]}`}>
      <div className={styles.main}>
        <Link to={`/incidents/${incident.id}`} className={styles.title}>
          {incident.title}
        </Link>
        <span className={styles.service}>{incident.affectedService}</span>
      </div>
      <SeverityBadge severity={incident.severity} />
      <StatusBadge status={incident.status} />
      <time className={styles.time} dateTime={incident.createdAt} title={formatFullDateTime(incident.createdAt)}>
        {formatRelative(incident.createdAt)}
      </time>
    </li>
  );
}

function Filters({ filters, onChange }: { filters: IncidentFilters; onChange: (filters: IncidentFilters) => void }) {
  const set = <K extends keyof IncidentFilters>(key: K, value: IncidentFilters[K]) => onChange({ ...filters, [key]: value });
  return (
    <div className={styles.filters} role="search">
      <div className={styles.field}>
        <label htmlFor="incident-search">Search</label>
        <input
          id="incident-search"
          type="search"
          placeholder="Title or service"
          value={filters.query}
          onChange={(e) => set('query', e.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor="severity-filter">Severity</label>
        <select id="severity-filter" value={filters.severity} onChange={(e) => set('severity', e.target.value as IncidentFilters['severity'])}>
          <option value="">All</option>
          {[...SEVERITIES].reverse().map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.field}>
        <label htmlFor="status-filter">Status</label>
        <select id="status-filter" value={filters.status} onChange={(e) => set('status', e.target.value as IncidentFilters['status'])}>
          <option value="">All</option>
          {INCIDENT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
