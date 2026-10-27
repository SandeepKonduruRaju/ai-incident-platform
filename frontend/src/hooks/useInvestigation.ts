// Polls GET /api/v1/incidents/{id}/investigation until it is COMPLETED, FAILED or NOT_STARTED, honouring Retry-After:
//   PENDING/RUNNING -> wait Retry-After (API sends 2 s; default 2 s) and poll again
//   NOT_STARTED     -> stop: nothing will happen until the user retries (retry() below)
//   503             -> "investigation service unavailable, retrying": wait Retry-After (API sends 5 s; default 5 s)
//   network error   -> same as 503 (the server may be restarting)
//   other errors    -> stop and show the error (404, 401, 403 do not get better by retrying)
// The loop stops on unmount or when the id changes; retry() re-requests the investigation and polls again.
import { useCallback, useEffect, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { Investigation } from '../api/types';

export const DEFAULT_POLL_SECONDS = 2;
export const DEFAULT_UNAVAILABLE_SECONDS = 5;
const FINAL = new Set(['COMPLETED', 'FAILED', 'NOT_STARTED']);

export interface InvestigationState {
  investigation: Investigation | null;
  unavailable: ApiError | null; // set while retrying after a 503/network error
  error: ApiError | null; // final, non-retryable error
  done: boolean;
}

export interface InvestigationControls extends InvestigationState {
  retry: () => Promise<void>;
  retrying: boolean;
  retryError: ApiError | null;
}

export function useInvestigation(api: ApiClient, incidentId: string): InvestigationControls {
  const [state, setState] = useState<InvestigationState>({ investigation: null, unavailable: null, error: null, done: false });
  const [generation, setGeneration] = useState(0); // bumped by retry(): restarts the polling loop
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (generation === 0) setState({ investigation: null, unavailable: null, error: null, done: false });

    const schedule = (seconds: number) => {
      if (!cancelled) timer = setTimeout(poll, seconds * 1000);
    };

    async function poll() {
      try {
        const { investigation, retryAfterSeconds } = await api.getInvestigation(incidentId);
        if (cancelled) return;
        const finished = FINAL.has(investigation.status);
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
  }, [api, incidentId, generation]);

  const retry = useCallback(async () => {
    setRetrying(true);
    setRetryError(null);
    try {
      const { investigation } = await api.retryInvestigation(incidentId);
      setState({ investigation, unavailable: null, error: null, done: false });
      setGeneration((g) => g + 1);
    } catch (e) {
      setRetryError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      setRetrying(false);
    }
  }, [api, incidentId]);

  return { ...state, retry, retrying, retryError };
}
