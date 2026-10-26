// Shared helpers for the k6 scenarios (milestone 4). Runs inside the grafana/k6 container on the compose network,
// so the API is http://incident-service:8080. Tokens come from the dev-only POST /api/v1/dev/token (dev profile).
import http from 'k6/http';
import { check, sleep } from 'k6';

export const BASE = __ENV.BASE_URL || 'http://incident-service:8080';
const JSON_HEADERS = { 'Content-Type': 'application/json' };

// p95 < 300 ms and < 1% errors for every scenario (the milestone's targets).
export const THRESHOLDS = {
  http_req_duration: ['p(95)<300'],
  http_req_failed: ['rate<0.01'],
};

const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
const SERVICES = ['payment-service', 'checkout-service', 'auth-service', 'search-service'];

/** One RESPONDER token per tenant: lt-<runId>-0 .. lt-<runId>-(n-1). A fresh runId keeps runs apart. */
export function tenantTokens(n) {
  const runId = __ENV.RUN_ID || `${Date.now()}`;
  const tokens = [];
  for (let i = 0; i < n; i++) {
    const res = http.post(`${BASE}/api/v1/dev/token`,
      JSON.stringify({ subject: 'k6', tenantId: `lt-${runId}-${i}`, roles: ['RESPONDER'] }),
      { headers: JSON_HEADERS, tags: { endpoint: 'setup' } });
    if (res.status !== 200) {
      throw new Error(`dev token failed (${res.status}): is incident-service running with SPRING_PROFILES_ACTIVE=dev?`);
    }
    tokens.push(res.json('accessToken'));
  }
  return tokens;
}

export function params(token, endpoint) {
  return { headers: { ...JSON_HEADERS, Authorization: `Bearer ${token}` }, tags: { endpoint } };
}

export function createIncident(token, endpoint = 'create') {
  const body = JSON.stringify({
    title: `k6 incident ${Math.floor(Math.random() * 1e9)}`,
    description: 'Load test: error rate and latency up after a deploy',
    severity: SEVERITIES[Math.floor(Math.random() * SEVERITIES.length)],
    affectedService: SERVICES[Math.floor(Math.random() * SERVICES.length)],
  });
  const res = http.post(`${BASE}/api/v1/incidents`, body, params(token, endpoint));
  check(res, { 'create: 201': (r) => r.status === 201 });
  return res.status === 201 ? res.json('id') : null;
}

export function getInvestigation(token, id, endpoint = 'investigation') {
  return http.get(`${BASE}/api/v1/incidents/${id}/investigation`, params(token, endpoint));
}

/** Polls until COMPLETED/FAILED; returns the final status, or null after timeoutSeconds. */
export function waitFinished(token, id, timeoutSeconds, endpoint = 'poll') {
  const deadline = Date.now() + timeoutSeconds * 1000;
  while (Date.now() < deadline) {
    const res = getInvestigation(token, id, endpoint);
    const status = res.status === 200 ? res.json('status') : null;
    if (status === 'COMPLETED' || status === 'FAILED') {
      return status;
    }
    sleep(1);
  }
  return null;
}

/** Setup for read-heavy scenarios: `perTenant` incidents per token, waited until their investigations finish. */
export function seedFinishedIncidents(tokens, perTenant, timeoutSeconds = 600) {
  const seeds = [];
  for (const token of tokens) {
    for (let i = 0; i < perTenant; i++) {
      const id = createIncident(token, 'setup');
      if (id) seeds.push({ token, id });
    }
  }
  for (const seed of seeds) {
    seed.status = waitFinished(seed.token, seed.id, timeoutSeconds, 'setup');
  }
  return seeds.filter((s) => s.status !== null);
}

/** The API mix of scenarios (a) and (c): 10% create, 30% list, 20% get one, 40% read an investigation. */
export function apiMixIteration(data) {
  const seed = data.seeds[Math.floor(Math.random() * data.seeds.length)];
  const r = Math.random();
  if (r < 0.10) {
    createIncident(seed.token);
  } else if (r < 0.40) {
    const res = http.get(`${BASE}/api/v1/incidents?page=0&size=20`, params(seed.token, 'list'));
    check(res, { 'list: 200': (x) => x.status === 200 });
  } else if (r < 0.60) {
    const res = http.get(`${BASE}/api/v1/incidents/${seed.id}`, params(seed.token, 'get'));
    check(res, { 'get: 200': (x) => x.status === 200 });
  } else {
    const res = getInvestigation(seed.token, seed.id);
    check(res, { 'investigation: 200': (x) => x.status === 200 });
  }
  sleep(0.25 + Math.random() * 0.5); // think time: ~2 requests/s per VU
}

/** Writes the full k6 summary as JSON to /results/<name>.json and prints a short table. */
export function summarize(name, data) {
  const m = data.metrics;
  const d = m.http_req_duration ? m.http_req_duration.values : {};
  const fmt = (v) => (v === undefined ? '-' : v.toFixed(1));
  const lines = [
    `scenario ${name}`,
    `  requests      ${m.http_reqs ? m.http_reqs.values.count : 0} (${fmt(m.http_reqs && m.http_reqs.values.rate)} req/s)`,
    `  latency ms    p50 ${fmt(d.med)}  p95 ${fmt(d['p(95)'])}  p99 ${fmt(d['p(99)'])}  max ${fmt(d.max)}`,
    `  errors        ${fmt(m.http_req_failed ? m.http_req_failed.values.rate * 100 : 0)} %`,
  ];
  for (const [key, metric] of Object.entries(m)) {
    if (key.startsWith('http_req_duration{endpoint:')) {
      const v = metric.values;
      lines.push(`  ${key.slice(18, -1).padEnd(26)} p50 ${fmt(v.med)}  p95 ${fmt(v['p(95)'])}  p99 ${fmt(v['p(99)'])}`);
    }
  }
  for (const key of ['e2e_time_to_finished', 'e2e_finished', 'e2e_not_finished']) {
    if (m[key]) lines.push(`  ${key.padEnd(26)} ${JSON.stringify(m[key].values)}`);
  }
  const thresholds = Object.entries(m)
    .filter(([, metric]) => metric.thresholds)
    .map(([key, metric]) => `  ${Object.values(metric.thresholds).every((t) => t.ok) ? 'PASS' : 'FAIL'}  ${key}`);
  return {
    stdout: `${lines.concat(['  thresholds:'], thresholds).join('\n')}\n`,
    [`/results/${name}.json`]: JSON.stringify(data, null, 2),
  };
}

/** p(99) is not in k6's default trend stats. */
export const SUMMARY_TREND_STATS = ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'];
