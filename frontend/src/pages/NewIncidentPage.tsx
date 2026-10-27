import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, newIdempotencyKey } from '../api/client';
import { SEVERITIES } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ErrorMessage } from '../components/ErrorMessage';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { SEVERITY_LABELS } from '../labels';
import { Link, useRouter } from '../router';
import styles from './Pages.module.css';
import { LIMITS, toRequest, validateIncident, type IncidentForm } from './validation';

const EMPTY: IncidentForm = { title: '', description: '', severity: '', affectedService: '' };
const FIELD_ORDER = ['title', 'description', 'severity', 'affectedService'] as const;

export function NewIncidentPage() {
  const { api } = useAuth();
  const { navigate } = useRouter();
  const [form, setForm] = useState<IncidentForm>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const services = useKnownServices();
  const formRef = useRef<HTMLFormElement>(null);
  // One Idempotency-Key per report: sending the same form again (after a timeout or a network error) reuses it, so
  // the server returns the incident it already created instead of a duplicate. Any edit makes it a new report.
  const idempotencyKey = useRef(newIdempotencyKey());
  useDocumentTitle('Report an incident');

  const set = (field: keyof IncidentForm) => (event: { target: { value: string } }) => {
    idempotencyKey.current = newIdempotencyKey();
    setForm((f) => ({ ...f, [field]: event.target.value }));
  };

  function focusFirstInvalid(errors: Record<string, string>) {
    const first = FIELD_ORDER.find((f) => errors[f]);
    if (first) formRef.current?.querySelector<HTMLElement>(`#${first}`)?.focus();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const errors = validateIncident(form);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      focusFirstInvalid(errors);
      return;
    }
    setBusy(true);
    try {
      const incident = await api.createIncident(toRequest(form), { idempotencyKey: idempotencyKey.current });
      navigate(`/incidents/${incident.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 400 && e.problem?.errors?.length) {
        const serverErrors = e.fieldErrors();
        setFieldErrors(serverErrors);
        focusFirstInvalid(serverErrors);
      }
      setError(e); // 400 summary, 429 rate limit (with Retry-After), 403, 5xx, timeout: all with the request id
    } finally {
      setBusy(false);
    }
  }

  const describedBy = (field: string, hint?: string) =>
    [hint, fieldErrors[field] ? `${field}-error` : undefined].filter(Boolean).join(' ') || undefined;
  const fieldError = (field: string) =>
    fieldErrors[field] && (
      <span id={`${field}-error`} className={styles.fieldError}>
        {fieldErrors[field]}
      </span>
    );

  return (
    <main>
      <div className={styles.formLayout}>
        <p className={styles.formBack}>
          <Link to="/incidents" className={styles.secondary}>
            Incidents
          </Link>
        </p>
        <h1>Report an incident</h1>
        <form ref={formRef} onSubmit={submit} className={styles.form} noValidate>
          <label htmlFor="title">Title</label>
          <input
            id="title"
            value={form.title}
            onChange={set('title')}
            maxLength={LIMITS.title}
            aria-invalid={Boolean(fieldErrors.title)}
            aria-describedby={describedBy('title')}
            required
          />
          {fieldError('title')}

          <label htmlFor="description">
            Description <span className={styles.optional}>(optional)</span>
          </label>
          <textarea
            id="description"
            rows={4}
            value={form.description}
            onChange={set('description')}
            maxLength={LIMITS.description}
            aria-invalid={Boolean(fieldErrors.description)}
            aria-describedby={describedBy('description', 'description-hint')}
          />
          <span id="description-hint" className={styles.hint}>
            {form.description.length} of {LIMITS.description} characters
          </span>
          {fieldError('description')}

          <label htmlFor="severity">Severity</label>
          <select
            id="severity"
            value={form.severity}
            onChange={set('severity')}
            aria-invalid={Boolean(fieldErrors.severity)}
            aria-describedby={describedBy('severity')}
            required
          >
            <option value="">Choose…</option>
            {[...SEVERITIES].reverse().map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABELS[s]}
              </option>
            ))}
          </select>
          {fieldError('severity')}

          <label htmlFor="affectedService">Affected service</label>
          <input
            id="affectedService"
            value={form.affectedService}
            onChange={set('affectedService')}
            maxLength={LIMITS.affectedService}
            placeholder="payment-service"
            list={services.length > 0 ? 'known-services' : undefined}
            autoComplete="off"
            aria-invalid={Boolean(fieldErrors.affectedService)}
            aria-describedby={describedBy('affectedService')}
            required
          />
          {services.length > 0 && (
            <datalist id="known-services">
              {services.map((service) => (
                <option key={service} value={service} />
              ))}
            </datalist>
          )}
          {fieldError('affectedService')}

          {error !== null && <ErrorMessage error={error} />}
          <button type="submit" className={styles.primary} disabled={busy}>
            {busy ? 'Reporting…' : 'Report incident'}
          </button>
        </form>

        <aside className={styles.sideNote} aria-labelledby="next-heading">
          <h2 id="next-heading">What happens next</h2>
          <p>An AI investigation starts automatically and usually finishes in under a minute.</p>
          <p>It reads recent logs, metrics, runbooks and past incidents, and every finding links to the evidence it used.</p>
        </aside>
      </div>
    </main>
  );
}

/** Service names seen in this tenant's recent incidents, as suggestions (the field stays free text). */
function useKnownServices(): string[] {
  const { api } = useAuth();
  const [services, setServices] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    Promise.resolve(api.listIncidents(0, 100))
      .then((page) => {
        if (cancelled || !page?.items) return;
        setServices([...new Set(page.items.map((i) => i.affectedService))].sort());
      })
      .catch(() => {}); // suggestions only: the form works without them
    return () => {
      cancelled = true;
    };
  }, [api]);
  return services;
}
