// The session lives in React state ONLY (memory), never in localStorage/sessionStorage.
// Trade-off: a page refresh logs you out. In exchange, an XSS bug cannot read a persisted token from storage
// (anything injected could still act while the page is open, but cannot exfiltrate a long-lived token later).
// A production setup would use an identity provider with an HttpOnly, SameSite cookie or a BFF instead.
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import type { Role } from '../api/types';

export interface Session {
  token: string;
  tenantId: string;
  subject: string;
  role: Role;
}

interface AuthValue {
  session: Session | null;
  api: ApiClient;
  login: (session: Session) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children, apiFactory = createApiClient }: { children: ReactNode; apiFactory?: typeof createApiClient }) {
  const [session, setSession] = useState<Session | null>(null);
  // The client reads the token through a ref, so it never needs to be recreated when the session changes.
  const tokenRef = useRef<string | null>(null);

  const logout = useCallback(() => {
    tokenRef.current = null;
    setSession(null);
  }, []);
  const login = useCallback((next: Session) => {
    tokenRef.current = next.token;
    setSession(next);
  }, []);

  const api = useMemo(() => apiFactory({ getToken: () => tokenRef.current, onUnauthorized: logout }), [apiFactory, logout]);
  const value = useMemo(() => ({ session, api, login, logout }), [session, api, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
