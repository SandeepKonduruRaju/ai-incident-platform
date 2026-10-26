// Scenario (c): spike. Same API mix as (a); 10 VUs, then a jump to 200 within 10 s, held for 1 minute, then back
// to 10 to watch recovery. The thresholds are the same targets: the point is to see whether (and where) they break.
import { THRESHOLDS, SUMMARY_TREND_STATS, apiMixIteration, seedFinishedIncidents, summarize, tenantTokens } from './lib/common.js';

export const options = {
  setupTimeout: '10m',
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    spike: {
      executor: 'ramping-vus',
      startVUs: 10,
      stages: [
        { duration: '30s', target: 10 },
        { duration: '10s', target: Number(__ENV.SPIKE_VUS || 200) },
        { duration: '1m', target: Number(__ENV.SPIKE_VUS || 200) },
        { duration: '10s', target: 10 },
        { duration: '1m', target: 10 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    ...THRESHOLDS,
    'http_req_duration{endpoint:create}': ['p(95)<300'],
    'http_req_duration{endpoint:investigation}': ['p(95)<300'],
  },
};

export function setup() {
  const tokens = tenantTokens(Number(__ENV.TENANTS || 20));
  return { seeds: seedFinishedIncidents(tokens, 2) };
}

export default function (data) {
  apiMixIteration(data);
}

export function handleSummary(data) {
  return summarize(__ENV.RESULT_NAME || 'c-spike', data);
}
