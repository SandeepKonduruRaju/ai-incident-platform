// Typed API client with central error handling. Every call sends a client-generated X-Request-Id (the backend keeps
// a valid incoming id and echoes it), so even a network failure has an id the user can quote.
import type {
  CreateIncidentRequest,
  Incident,
  Investigation,
  Page,
  ProblemDetail,
  TokenRequest,
  TokenResponse,
} from './types';

export class ApiError extends Error {
  readonly status: number; // 0 = network error (no response)
  readonly problem?: ProblemDetail;
  readonly requestId?: string;
  readonly retryAfterSeconds?: number;
  readonly timedOut: boolean; // no answer within the client timeout (status 0): the server may still have done it

  constructor(
    status: number,
    message: string,
    opts: { problem?: ProblemDetail; requestId?: string; retryAfterSeconds?: number; timedOut?: boolean } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.problem = opts.problem;
    this.requestId = opts.requestId;
    this.retryAfterSeconds = opts.retryAfterSeconds;
    this.timedOut = opts.timedOut ?? false;
  }

  /** 400 field errors keyed by field name. */
  fieldErrors(): Record<string, string> {
    return Object.fromEntries((this.problem?.errors ?? []).map((e) => [e.field, e.message]));
  }
}

export interface ApiClient {
  issueDevToken(request: TokenRequest): Promise<TokenResponse>;
  listIncidents(page: number, size: number): Promise<Page<Incident>>;
  getIncident(id: string): Promise<Incident>;
  /**
   * idempotencyKey: sent as Idempotency-Key, so sending the same report again (e.g. after a timeout) returns the
   * incident the first request created instead of a duplicate. Times out after CREATE_TIMEOUT_MS.
   */
  createIncident(request: CreateIncidentRequest, opts?: { idempotencyKey?: string }): Promise<Incident>;
  /** retryAfterSeconds: present while PENDING/RUNNING (how long to wait before polling again). */
  getInvestigation(id: string): Promise<{ investigation: Investigation; retryAfterSeconds?: number }>;
  /** Re-requests a NOT_STARTED or FAILED investigation (409 otherwise); answers PENDING. */
  retryInvestigation(id: string): Promise<{ investigation: Investigation; retryAfterSeconds?: number }>;
}

export interface ClientOptions {
  baseUrl?: string; // '' = same origin (nginx or the Vite dev proxy forward /api)
  getToken: () => string | null;
  onUnauthorized?: () => void; // 401: token expired or invalid -> back to login
  fetchImpl?: typeof fetch;
}

export function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

/** POST /incidents: after this long without an answer, stop waiting and tell the user what may have happened. */
export const CREATE_TIMEOUT_MS = 15_000;

export const CREATE_TIMEOUT_MESSAGE =
  'The server did not answer within 15 seconds. The incident may have been saved: reporting it again with the same ' +
  'details is safe and will not create a duplicate.';

export function newIdempotencyKey(): string {
  return newRequestId();
}

function newRequestId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const FRIENDLY: Record<number, string> = {
  401: 'Your session has expired. Please sign in again.',
  403: 'You do not have permission to do that.',
  404: 'Not found.',
  429: 'Too many requests.',
  503: 'The investigation service is unavailable.',
};

export function createApiClient({ baseUrl = '', getToken, onUnauthorized, fetchImpl }: ClientOptions): ApiClient {
  const doFetch = fetchImpl ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));

  interface RequestOptions {
    headers?: Record<string, string>;
    timeoutMs?: number; // abort after this long: ApiError with timedOut = true
    timeoutMessage?: string;
  }

  async function request<T>(method: string, path: string, body?: unknown, opts: RequestOptions = {}): Promise<{ data: T; response: Response }> {
    const requestId = newRequestId();
    const headers: Record<string, string> = { Accept: 'application/json', 'X-Request-Id': requestId, ...opts.headers };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';

    const controller = opts.timeoutMs ? new AbortController() : undefined;
    const timer = controller ? setTimeout(() => controller.abort(), opts.timeoutMs) : undefined;
    let response: Response;
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller?.signal,
      });
    } catch {
      if (controller?.signal.aborted) {
        throw new ApiError(0, opts.timeoutMessage ?? 'The server did not answer in time.', { requestId, timedOut: true });
      }
      throw new ApiError(0, 'Cannot reach the server. Check your connection and try again.', { requestId });
    } finally {
      clearTimeout(timer);
    }

    const serverRequestId = response.headers.get('X-Request-Id') ?? requestId;
    if (!response.ok) {
      let problem: ProblemDetail | undefined;
      try {
        problem = (await response.json()) as ProblemDetail;
      } catch {
        problem = undefined; // e.g. an HTML error page from a proxy
      }
      if (response.status === 401) onUnauthorized?.();
      const message = problem?.detail ?? FRIENDLY[response.status] ?? `Request failed (HTTP ${response.status}).`;
      throw new ApiError(response.status, message, {
        problem,
        requestId: problem?.requestId ?? serverRequestId,
        retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')),
      });
    }
    return { data: (await response.json()) as T, response };
  }

  return {
    async issueDevToken(req) {
      return (await request<TokenResponse>('POST', '/api/v1/dev/token', req)).data;
    },
    async listIncidents(page, size) {
      return (await request<Page<Incident>>('GET', `/api/v1/incidents?page=${page}&size=${size}`)).data;
    },
    async getIncident(id) {
      return (await request<Incident>('GET', `/api/v1/incidents/${encodeURIComponent(id)}`)).data;
    },
    async createIncident(req, opts = {}) {
      const headers = opts.idempotencyKey ? { 'Idempotency-Key': opts.idempotencyKey } : undefined;
      return (
        await request<Incident>('POST', '/api/v1/incidents', req, {
          headers,
          timeoutMs: CREATE_TIMEOUT_MS,
          timeoutMessage: CREATE_TIMEOUT_MESSAGE,
        })
      ).data;
    },
    async getInvestigation(id) {
      const { data, response } = await request<Investigation>('GET', `/api/v1/incidents/${encodeURIComponent(id)}/investigation`);
      return { investigation: data, retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')) };
    },
    async retryInvestigation(id) {
      const { data, response } = await request<Investigation>('POST', `/api/v1/incidents/${encodeURIComponent(id)}/investigation/retry`);
      return { investigation: data, retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')) };
    },
  };
}
