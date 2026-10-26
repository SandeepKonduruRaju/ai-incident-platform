import { useEffect, useRef } from 'react';
import { useAuth } from './auth/AuthContext';
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

  // Without a session every page is the login page (the token is in memory only, see AuthContext).
  const needsLogin = !session && route.name !== 'login';
  useEffect(() => {
    if (needsLogin) navigate('/login');
  }, [needsLogin, navigate]);

  // Move focus to the new page's content on navigation, so keyboard and screen-reader users start there.
  useEffect(() => {
    mainRef.current?.focus();
  }, [route]);

  let page;
  if (!session || route.name === 'login') page = <LoginPage />;
  else if (route.name === 'incidents') page = <IncidentsPage page={route.page} />;
  else if (route.name === 'new') page = session.role === 'VIEWER' ? <p>Viewers cannot create incidents.</p> : <NewIncidentPage />;
  else if (route.name === 'detail') page = <IncidentDetailPage id={route.id} />;
  else page = <p>Page not found. <Link to="/incidents">Go to incidents</Link></p>;

  return (
    <>
      <a href="#content" className={styles.skip}>
        Skip to content
      </a>
      <header className={styles.topbar}>
        <Link to={session ? '/incidents' : '/login'} className={styles.brand}>
          Incident Platform
        </Link>
        {session && (
          <div className={styles.user}>
            <span>
              {session.subject} · <strong>{session.tenantId}</strong> · {session.role}
            </span>
            <button
              type="button"
              onClick={() => {
                logout();
                navigate('/login');
              }}
            >
              Sign out
            </button>
          </div>
        )}
      </header>
      <div id="content" ref={mainRef} tabIndex={-1} className={styles.content}>
        {page}
      </div>
    </>
  );
}
