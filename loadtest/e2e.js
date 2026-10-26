// Scenario (b): end to end at a steady arrival rate. Each iteration creates an incident and polls its investigation
// (every 1 s) until COMPLETED/FAILED: POST -> outbox -> Kafka -> worker -> LangGraph (fake LLM) -> GET.
// RATE = new incidents per MINUTE (default 30): steady and below the worker's capacity (see docs/load-test.md);
// above it, Kafka lag and time-to-finished grow without bound.
import { Counter, Trend } from 'k6/metrics';
import { THRESHOLDS, SUMMARY_TREND_STATS, createIncident, summarize, tenantTokens, waitFinished } from './lib/common.js';

const timeToFinished = new Trend('e2e_time_to_finished', true);
const finished = new Counter('e2e_finished');
const notFinished = new Counter('e2e_not_finished');

export const options = {
  setupTimeout: '2m',
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    e2e: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 30),
      timeUnit: '1m',
      duration: __ENV.DURATION || '5m',
      preAllocatedVUs: 50,
      maxVUs: 400,
    },
  },
  thresholds: {
    ...THRESHOLDS,
    'http_req_duration{endpoint:create}': ['p(95)<300'],
    'http_req_duration{endpoint:poll}': ['p(95)<300'],
    e2e_not_finished: ['count<1'],
  },
};

export function setup() {
  return { tokens: tenantTokens(Number(__ENV.TENANTS || 20)) };
}

export default function (data) {
  const token = data.tokens[Math.floor(Math.random() * data.tokens.length)];
  const started = Date.now();
  const id = createIncident(token);
  if (!id) {
    notFinished.add(1);
    return;
  }
  const status = waitFinished(token, id, Number(__ENV.TIMEOUT_SECONDS || 180));
  if (status) {
    finished.add(1, { status });
    timeToFinished.add(Date.now() - started);
  } else {
    notFinished.add(1);
  }
}

export function handleSummary(data) {
  return summarize(__ENV.RESULT_NAME || 'b-e2e', data);
}
