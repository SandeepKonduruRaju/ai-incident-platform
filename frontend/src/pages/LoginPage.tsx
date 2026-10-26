import { useState, type FormEvent } from 'react';
import { ROLES, type Role } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ErrorMessage } from '../components/ErrorMessage';
import { useRouter } from '../router';
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

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const token = await api.issueDevToken({ subject: subject.trim(), tenantId: tenantId.trim(), roles: [role] });
      login({ token: token.accessToken, subject: subject.trim(), tenantId: tenantId.trim(), role });
      navigate('/incidents');
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.narrow}>
      <h1>Sign in (development)</h1>
      <p className={styles.muted}>
        Issues a short-lived token from the dev-only endpoint. The token is kept in memory: refreshing the page signs you
        out.
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
              {r}
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
