import { describe, expect, it, vi } from 'vitest';
import { ApiError, createApiClient } from './client';

function response(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

describe('api client', () => {
  it('sends the bearer token and a request id, and reads Retry-After of an in-progress investigation', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(200, { incidentId: 'i', status: 'RUNNING' }, { 'Retry-After': '2' }));
    const api = createApiClient({ getToken: () => 'tok', fetchImpl });

    const result = await api.getInvestigation('i');

    expect(result).toEqual({ investigation: { incidentId: 'i', status: 'RUNNING' }, retryAfterSeconds: 2 });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('/api/v1/incidents/i/investigation');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(init.headers['X-Request-Id']).toMatch(/.+/);
  });

  it('turns a ProblemDetail into an ApiError with the server request id', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response(503, { title: 'Investigation unavailable', detail: 'Try again shortly.', requestId: 'req-x' }, { 'Retry-After': '5' }));
    const api = createApiClient({ getToken: () => 'tok', fetchImpl });

    const error = await api.getInvestigation('i').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 503, message: 'Try again shortly.', requestId: 'req-x', retryAfterSeconds: 5 });
  });

  it('calls onUnauthorized on 401 and reports network errors as status 0 with the client request id', async () => {
    const onUnauthorized = vi.fn();
    const api401 = createApiClient({ getToken: () => 'old', onUnauthorized, fetchImpl: vi.fn().mockResolvedValue(response(401, undefined)) });
    await expect(api401.listIncidents(0, 20)).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);

    const apiDown = createApiClient({ getToken: () => null, fetchImpl: vi.fn().mockRejectedValue(new TypeError('Failed to fetch')) });
    const error = (await apiDown.listIncidents(0, 20).catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.requestId).toMatch(/.+/);
  });
});
