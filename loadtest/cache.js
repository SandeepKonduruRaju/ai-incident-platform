// Scenario (d): cache effect. Only GET /api/v1/incidents/{id}/investigation of FINISHED investigations, at a fixed
// arrival rate, so the two runs differ only in the cache. Run it twice (see loadtest/README.md):
//   REDIS_CACHE_ENABLED=true  -> RESULT_NAME=d-cache-on   (hits served from Redis, no worker call)
//   REDIS_CACHE_ENABLED=false -> RESULT_NAME=d-cache-off  (every read calls the worker)
import { check } from 'k6';
import { THRESHOLDS, SUMMARY_TREND_STATS, getInvestigation, seedFinishedIncidents, summarize, tenantTokens } from './lib/common.js';

export const options = {
  setupTimeout: '10m',
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    cache: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 200),
      timeUnit: '1s',
      duration: __ENV.DURATION || '2m',
      preAllocatedVUs: 50,
      maxVUs: 300,
    },
  },
  thresholds: {
    ...THRESHOLDS,
    'http_req_duration{endpoint:investigation}': ['p(95)<300'],
  },
};

export function setup() {
  const tokens = tenantTokens(Number(__ENV.TENANTS || 10));
  return { seeds: seedFinishedIncidents(tokens, 5) };
}

export default function (data) {
  const seed = data.seeds[Math.floor(Math.random() * data.seeds.length)];
  const res = getInvestigation(seed.token, seed.id);
  check(res, { 'investigation: 200': (r) => r.status === 200 });
}

export function handleSummary(data) {
  return summarize(__ENV.RESULT_NAME || 'd-cache', data);
}
