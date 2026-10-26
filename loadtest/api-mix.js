// Scenario (a): API mix, ramping 10 -> 100 virtual users.
// 10% create, 30% list, 20% get one, 40% read an investigation (of incidents seeded and finished in setup()).
import { THRESHOLDS, SUMMARY_TREND_STATS, apiMixIteration, seedFinishedIncidents, summarize, tenantTokens } from './lib/common.js';

export const options = {
  setupTimeout: '10m',
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    api_mix: {
      executor: 'ramping-vus',
      startVUs: 10,
      stages: [
        { duration: '30s', target: 10 },
        { duration: '2m', target: 100 },
        { duration: '2m', target: 100 },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    ...THRESHOLDS,
    // Per-endpoint submetrics (reported in the summary; same target).
    'http_req_duration{endpoint:create}': ['p(95)<300'],
    'http_req_duration{endpoint:list}': ['p(95)<300'],
    'http_req_duration{endpoint:get}': ['p(95)<300'],
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
  return summarize(__ENV.RESULT_NAME || 'a-api-mix', data);
}
