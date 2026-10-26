import { useRef, useState, type FormEvent } from 'react';
import { ApiError } from '../api/client';
import { SEVERITIES } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ErrorMessage } from '../components/ErrorMessage';
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
  const formRef = useRef<HTMLFormElement>(null);

  const set = (field: keyof IncidentForm) => (event: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [field]: event.target.value }));

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
      const incident = await api.createIncident(toRequest(form));
      navigate(`/incidents/${incident.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 400 && e.problem?.errors?.length) {
        const serverErrors = e.fieldErrors();
        setFieldErrors(serverErrors);
        focusFirstInvalid(serverErrors);
      }
      setError(e); // 400 summary, 429 rate limit (with Retry-After), 403, 5xx: all with the request id
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
    <main className={styles.narrow}>
      <p>
        <Link to="/incidents">← Incidents</Link>
      </p>
      <h1>New incident</h1>
      <form ref={formRef} onSubmit={submit} className={styles.form} noValidate>
        <label htmlFor="title">Title *</label>
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

        <label htmlFor="description">Description</label>
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
          {form.description.length}/{LIMITS.description}
        </span>
        {fieldError('description')}

        <label htmlFor="severity">Severity *</label>
        <select
          id="severity"
          value={form.severity}
          onChange={set('severity')}
          aria-invalid={Boolean(fieldErrors.severity)}
          aria-describedby={describedBy('severity')}
          required
        >
          <option value="">Choose…</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {fieldError('severity')}

        <label htmlFor="affectedService">Affected service *</label>
        <input
          id="affectedService"
          value={form.affectedService}
          onChange={set('affectedService')}
          maxLength={LIMITS.affectedService}
          placeholder="payment-service"
          aria-invalid={Boolean(fieldErrors.affectedService)}
          aria-describedby={describedBy('affectedService')}
          required
        />
        {fieldError('affectedService')}

        {error !== null && <ErrorMessage error={error} />}
        <button type="submit" className={styles.primary} disabled={busy}>
          {busy ? 'Creating…' : 'Create incident'}
        </button>
      </form>
    </main>
  );
}
