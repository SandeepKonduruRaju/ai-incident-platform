// Polls GET /api/v1/incidents/{id}/investigation until it is COMPLETED or FAILED, honouring Retry-After:
//   PENDING/RUNNING -> wait Retry-After (API sends 2 s; default 2 s) and poll again
//   503             -> "investigation service unavailable, retrying": wait Retry-After (API sends 5 s; default 5 s)
//   network error   -> same as 503 (the server may be restarting)
//   other errors    -> stop and show the error (404, 401, 403 do not get better by retrying)
// The loop stops on unmount or when the id changes.
import { useEffect, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { Investigation } from '../api/types';

export const DEFAULT_POLL_SECONDS = 2;
export const DEFAULT_UNAVAILABLE_SECONDS = 5;

export interface InvestigationState {
  investigation: Investigation | null;
  unavailable: ApiError | null; // set while retrying after a 503/network error
  error: ApiError | null; // final, non-retryable error
  done: boolean;
}

export function useInvestigation(api: ApiClient, incidentId: string): InvestigationState {
  const [state, setState] = useState<InvestigationState>({ investigation: null, unavailable: null, error: null, done: false });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setState({ investigation: null, unavailable: null, error: null, done: false });

    const schedule = (seconds: number) => {
      if (!cancelled) timer = setTimeout(poll, seconds * 1000);
    };

    async function poll() {
      try {
        const { investigation, retryAfterSeconds } = await api.getInvestigation(incidentId);
        if (cancelled) return;
        const finished = investigation.status === 'COMPLETED' || investigation.status === 'FAILED';
        setState({ investigation, unavailable: null, error: null, done: finished });
        if (!finished) schedule(retryAfterSeconds ?? DEFAULT_POLL_SECONDS);
      } catch (e) {
        if (cancelled) return;
        const error = e instanceof ApiError ? e : new ApiError(0, String(e));
        if (error.status === 503 || error.status === 0) {
          setState((s) => ({ ...s, unavailable: error }));
          schedule(error.retryAfterSeconds ?? DEFAULT_UNAVAILABLE_SECONDS);
        } else {
          setState((s) => ({ ...s, unavailable: null, error, done: true }));
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [api, incidentId]);

  return state;
}
