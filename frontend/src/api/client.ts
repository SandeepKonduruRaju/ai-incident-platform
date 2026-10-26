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

  constructor(status: number, message: string, opts: { problem?: ProblemDetail; requestId?: string; retryAfterSeconds?: number } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.problem = opts.problem;
    this.requestId = opts.requestId;
    this.retryAfterSeconds = opts.retryAfterSeconds;
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
  createIncident(request: CreateIncidentRequest): Promise<Incident>;
  /** retryAfterSeconds: present while PENDING/RUNNING (how long to wait before polling again). */
  getInvestigation(id: string): Promise<{ investigation: Investigation; retryAfterSeconds?: number }>;
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

  async function request<T>(method: string, path: string, body?: unknown): Promise<{ data: T; response: Response }> {
    const requestId = newRequestId();
    const headers: Record<string, string> = { Accept: 'application/json', 'X-Request-Id': requestId };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';

    let response: Response;
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, 'Cannot reach the server. Check your connection and try again.', { requestId });
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
    async createIncident(req) {
      return (await request<Incident>('POST', '/api/v1/incidents', req)).data;
    },
    async getInvestigation(id) {
      const { data, response } = await request<Investigation>('GET', `/api/v1/incidents/${encodeURIComponent(id)}/investigation`);
      return { investigation: data, retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')) };
    },
  };
}
