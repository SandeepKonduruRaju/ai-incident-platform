// A tiny History-API router: four routes do not justify a routing library. Deep links work because nginx (and the
// Vite dev server) serve index.html for every non-/api path.
import { createContext, useCallback, useContext, useEffect, useState, type AnchorHTMLAttributes, type MouseEvent, type ReactNode } from 'react';

export type Route =
  | { name: 'login' }
  | { name: 'incidents'; page: number }
  | { name: 'new' }
  | { name: 'detail'; id: string }
  | { name: 'notFound' };

export function parseRoute(pathname: string, search = ''): Route {
  if (pathname === '/' || pathname === '/login') return { name: 'login' };
  if (pathname === '/incidents') {
    const page = Number(new URLSearchParams(search).get('page') ?? '0');
    return { name: 'incidents', page: Number.isInteger(page) && page >= 0 ? page : 0 };
  }
  if (pathname === '/incidents/new') return { name: 'new' };
  const match = /^\/incidents\/([0-9a-fA-F-]{36})$/.exec(pathname);
  if (match) return { name: 'detail', id: match[1] };
  return { name: 'notFound' };
}

interface RouterValue {
  route: Route;
  navigate: (to: string) => void;
}

const RouterContext = createContext<RouterValue | null>(null);

export function Router({ children }: { children: ReactNode }) {
  const read = () => parseRoute(window.location.pathname, window.location.search);
  const [route, setRoute] = useState<Route>(read);

  useEffect(() => {
    const onPop = () => setRoute(read());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const navigate = useCallback((to: string) => {
    window.history.pushState(null, '', to);
    setRoute(read());
    window.scrollTo?.(0, 0);
  }, []);

  return <RouterContext.Provider value={{ route, navigate }}>{children}</RouterContext.Provider>;
}

export function useRouter(): RouterValue {
  const value = useContext(RouterContext);
  if (!value) throw new Error('useRouter must be used inside <Router>');
  return value;
}

/** A real <a href> (keyboard, middle-click, copy link) that navigates client-side on a plain click. */
export function Link({ to, children, ...rest }: { to: string; children: ReactNode } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  const { navigate } = useRouter();
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  };
  return (
    <a href={to} onClick={onClick} {...rest}>
      {children}
    </a>
  );
}
