import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const workload = JSON.parse(open('../../.qa/workload.json'));
if (!['http://localhost:8000', 'http://127.0.0.1:8000'].includes(workload.base_url) || __ENV.QA_CONFIRM !== 'nexus-e2e') {
  throw new Error('k6 requires the disposable localhost stack and QA_CONFIRM=nexus-e2e');
}
const profile = __ENV.K6_PROFILE || 'smoke';
if (!['smoke', 'load'].includes(profile)) throw new Error('K6_PROFILE must be smoke or load');
const completed = new Counter('completed_workflows');
const names = ['recruitment', 'operations', 'reporting'];
const shares = [0.6, 0.25, 0.15];
const scenarios = Object.fromEntries(names.map((name, i) => [name, profile === 'smoke'
  ? { executor: 'constant-vus', vus: 1, duration: '20s', exec: name, gracefulStop: '15s' }
  : { executor: 'ramping-vus', startVUs: 0, exec: name, gracefulRampDown: '15s', gracefulStop: '15s',
      stages: [10, 25, 50, 100, 0].map((total) => ({ duration: '60s', target: Math.round(total * shares[i]) })) }]));

export const options = {
  scenarios, maxRedirects: 0,
  thresholds: {
    checks: ['rate==1'], http_req_failed: ['rate<0.01'],
    ...Object.fromEntries(names.flatMap((name) => [
      [`http_req_duration{scenario:${name}}`, ['p(95)<3000']],
      [`completed_workflows{flow:${name}}`, ['count>0']],
    ])),
  },
};

function get(path, name, role, predicate) {
  const res = http.get(workload.base_url + path, {
    headers: { Authorization: `Bearer ${workload.sessions[role].token}` },
    tags: { name }, timeout: '15s', redirects: 0,
  });
  let body;
  try { body = res.json(); } catch (_) { body = null; }
  if (!check(res, { [`${name}: HTTP 200 and expected data`]: (r) => r.status === 200 && body !== null && predicate(body) })) {
    fail(`${name}: status ${res.status}, response contract failed`);
  }
  return body;
}
function pick(values) { return values[(__VU + __ITER) % values.length]; }

export function recruitment() {
  get('/api/candidates?page_size=20', 'candidate list', 'recruiter', (b) => Array.isArray(b.items) && b.total >= 12);
  sleep(0.5);
  get(`/api/candidates?q=${encodeURIComponent(workload.search)}&page_size=20`, 'candidate search', 'recruiter', (b) => b.items.length > 0);
  const id = pick(workload.candidates);
  get(`/api/candidates/${id}`, 'candidate detail', 'recruiter', (b) => b.id === id);
  sleep(0.5);
  get(`/api/pipeline/kanban/${pick(workload.jobs)}`, 'pipeline', 'recruiter', (b) => Array.isArray(b.columns) && b.columns.some((c) => c.items.length > 0));
  completed.add(1, { flow: 'recruitment' });
  sleep(1);
}
export function operations() {
  get('/api/contracts?page_size=20', 'contract list', 'admin', (b) => Array.isArray(b.items) && b.total >= 3);
  sleep(1);
  const id = pick(workload.contracts);
  get(`/api/contracts/${id}`, 'contract detail', 'admin', (b) => b.id === id && b.status === 'active');
  get(`/api/clients/${pick(workload.clients)}/orders`, 'client orders', 'admin', (b) => b.total_contractors > 0 && b.contractors.some((c) => c.orders.length > 0));
  completed.add(1, { flow: 'operations' });
  sleep(1);
}
export function reporting() {
  get('/api/dashboard/v2/my-work', 'my work dashboard', 'recruiter', (b) => b.schema_version === '2' && b.data && b.scope);
  sleep(1);
  get('/api/dashboard/v2/finance', 'finance dashboard', 'admin', (b) => b.schema_version === '2' && b.data && b.scope);
  completed.add(1, { flow: 'reporting' });
  sleep(1);
}
export function handleSummary(data) {
  return { 'qa/reports/k6-summary.json': JSON.stringify({ profile, ...data }, null, 2) };
}
