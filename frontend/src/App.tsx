import { useEffect, useRef } from 'react';
import { useAuth } from './auth/AuthContext';
import { LogoMark } from './components/Logo';
import { ThemeToggle } from './components/ThemeToggle';
import { useDocumentTitle } from './hooks/useDocumentTitle';
import { ROLE_LABELS } from './labels';
import { IncidentDetailPage } from './pages/IncidentDetailPage';
import { IncidentsPage } from './pages/IncidentsPage';
import { LoginPage } from './pages/LoginPage';
import { NewIncidentPage } from './pages/NewIncidentPage';
import { Link, useRouter } from './router';
import styles from './App.module.css';

export function App() {
  const { session, logout } = useAuth();
  const { route, navigate } = useRouter();
  const mainRef = useRef<HTMLDivElement>(null);

  // Without a session every page is the login page (the token is in memory only, see AuthContext). The requested page
  // goes along as ?next=..., so signing in returns there (LoginPage accepts only same-origin relative paths).
  const needsLogin = !session && route.name !== 'login';
  useEffect(() => {
    if (!needsLogin) return;
    const requested = `${window.location.pathname}${window.location.search}`;
    navigate(requested === '/' ? '/login' : `/login?next=${encodeURIComponent(requested)}`);
  }, [needsLogin, navigate]);

  // Move focus to the new page's content on navigation, so keyboard and screen-reader users start there.
  useEffect(() => {
    mainRef.current?.focus();
  }, [route]);

  let page;
  if (!session || route.name === 'login') page = <LoginPage />;
  else if (route.name === 'incidents') page = <IncidentsPage page={route.page} />;
  else if (route.name === 'new') page = session.role === 'VIEWER' ? <Message text="Viewers cannot report incidents." /> : <NewIncidentPage />;
  else if (route.name === 'detail') page = <IncidentDetailPage id={route.id} />;
  else page = <NotFound />;

  return (
    <>
      <a href="#content" className={styles.skip}>
        Skip to content
      </a>
      <header className={styles.topbar}>
        <Link to={session ? '/incidents' : '/login'} className={styles.brand} aria-label="Incident Platform">
          <LogoMark />
          <span className={styles.brandName}>Incident Platform</span>
        </Link>
        <div className={styles.tools}>
          {session && (
            <span className={styles.user} title={`Signed in as ${session.subject} (${ROLE_LABELS[session.role]})`}>
              <span className={styles.tenantLabel}>Tenant</span> <strong>{session.tenantId}</strong>
            </span>
          )}
          <ThemeToggle />
          {session && (
            <button
              type="button"
              className={styles.signOut}
              onClick={() => {
                logout();
                navigate('/login');
              }}
            >
              Sign out
            </button>
          )}
        </div>
      </header>
      <div id="content" ref={mainRef} tabIndex={-1} className={styles.content}>
        {page}
      </div>
    </>
  );
}

function Message({ text }: { text: string }) {
  useDocumentTitle(null);
  return <p>{text}</p>;
}

function NotFound() {
  useDocumentTitle('Page not found');
  return (
    <main>
      <h1>Page not found</h1>
      <p>
        <Link to="/incidents">Go to incidents</Link>
      </p>
    </main>
  );
}
