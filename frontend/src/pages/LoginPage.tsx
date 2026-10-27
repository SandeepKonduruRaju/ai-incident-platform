import { useState, type FormEvent } from 'react';
import { ROLES, type Role } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ErrorMessage } from '../components/ErrorMessage';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { ROLE_LABELS } from '../labels';
import { useRouter } from '../router';
import { safeNextPath } from '../text';
import styles from './Pages.module.css';

/**
 * DEV MODE login: asks incident-service for a signed token (POST /api/v1/dev/token, only with the "dev" Spring
 * profile). A real deployment would redirect to an identity provider instead.
 */
export function LoginPage() {
  const { api, login } = useAuth();
  const { navigate } = useRouter();
  const [subject, setSubject] = useState('alice');
  const [tenantId, setTenantId] = useState('acme');
  const [role, setRole] = useState<Role>('RESPONDER');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useDocumentTitle('Sign in');

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const token = await api.issueDevToken({ subject: subject.trim(), tenantId: tenantId.trim(), roles: [role] });
      login({ token: token.accessToken, subject: subject.trim(), tenantId: tenantId.trim(), role });
      // Back to the page that sent us here; never anywhere off this site (open redirect).
      navigate(safeNextPath(new URLSearchParams(window.location.search).get('next')));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.narrow}>
      <h1>Sign in</h1>
      <p className={styles.muted}>
        Development sign-in: issues a short-lived token from the dev-only endpoint. The token is kept in memory, so
        refreshing the page signs you out.
      </p>
      <form onSubmit={submit} className={styles.form} noValidate>
        <label htmlFor="subject">User</label>
        <input id="subject" value={subject} onChange={(e) => setSubject(e.target.value)} required autoComplete="username" />

        <label htmlFor="tenant">Tenant</label>
        <input id="tenant" value={tenantId} onChange={(e) => setTenantId(e.target.value)} required />

        <label htmlFor="role">Role</label>
        <select id="role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </select>

        {error !== null && <ErrorMessage error={error} />}
        <button type="submit" className={styles.primary} disabled={busy || !subject.trim() || !tenantId.trim()}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  );
}
