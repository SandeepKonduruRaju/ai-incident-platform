import { useEffect } from 'react';

export const APP_NAME = 'Incident Platform';

/** Per-page <title>: "<page> — Incident Platform" (just the app name while the page title is unknown). */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} — ${APP_NAME}` : APP_NAME;
  }, [title]);
}
