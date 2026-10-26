import { vi } from 'vitest';
import { ApiError, type ApiClient } from '../api/client';
import type { Investigation } from '../api/types';

export const INCIDENT_ID = '0b9f4d6e-7a1c-4c2e-9d55-2f1e8a3b6c01';

/** Every method a vi.fn(); tests set the ones they need. */
export function fakeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    issueDevToken: vi.fn(),
    listIncidents: vi.fn(),
    getIncident: vi.fn(),
    createIncident: vi.fn(),
    getInvestigation: vi.fn(),
    ...overrides,
  } as ApiClient;
}

export const completed: Investigation = {
  incidentId: INCIDENT_ID,
  status: 'COMPLETED',
  summary: 'Connection pool exhausted after the deploy [C1].',
  confidence: 'medium',
  rootCause: { text: 'HikariPool timeouts in payment-service [C1]', citations: ['C1'] },
  contributingFactors: [{ text: 'Traffic peak at 12:00 [C2]', citations: ['C2'] }],
  remediation: [{ text: 'Raise the pool size per the runbook [C3]', citations: ['C3'] }],
  citations: [
    { label: 'C1', sourceType: 'log', sourceId: 'LOG-acme-db_pool_exhausted-payment-service', snippet: 'HikariPool-1 - Connection is not available' },
    { label: 'C2', sourceType: 'metric', sourceId: 'MET-acme-rps', snippet: 'requests/s doubled at 12:00' },
    { label: 'C3', sourceType: 'runbook', sourceId: 'RB-db-pool', snippet: 'Increase maximumPoolSize' },
  ],
  model: 'claude-haiku-5-5',
  promptVersion: 'v1',
  completedAt: '2026-10-26T12:00:00Z',
};

export const unavailable = () =>
  new ApiError(503, 'The investigation service is temporarily unavailable. Try again shortly.', {
    requestId: 'req-503',
    retryAfterSeconds: 5,
  });
