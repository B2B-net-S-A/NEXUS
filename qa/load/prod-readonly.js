// Test obciążeniowy produkcji NEXUSA — WYŁĄCZNIE odczyty.
//
// Symuluje zespół pracujący naraz: rekruterzy (lista i wyszukiwanie kandydatów,
// profile, tablice rekrutacji), Delivery Leadzi (klienci, zamówienia, kontrakty)
// i kierownictwo (pulpit, Insights). Każda wirtualna osoba ma przerwy 5–15 s
// między ekranami i odpytywanie w tle jak otwarta karta przeglądarki.
//
// Bezpieczeństwo:
//  - jedyna funkcja wysyłająca żądania to `get()` (metoda GET), bez przekierowań;
//  - lista endpointów to tylko trasy sprawdzone jako czysty odczyt (bez zapisów,
//    bez modeli AI i Graph, bez limitów slowapi); jedyne zewnętrzne wywołanie to
//    osadzenie zapytania Voyage w trybie „auto” wyszukiwania (pamiętane 5 min);
//  - test przerywa się sam przy > 5% błędów albo p95 > 5 s (po 1 min rozgrzewki);
//  - tokeny z `.qa/prod-tokens.json` (0600, poza Gitem, ważne 3 h).
//
// Uruchomienie wieczorem, gdy nikt nie pracuje (procedura: qa/README.md):
//   .qa/bin/k6 run -e QA_CONFIRM=nexus-prod-readonly qa/load/prod-readonly.js
// Najpierw `-e K6_PROFILE=smoke` (1 osoba na personę, 2 min).
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import exec from 'k6/execution';

const API = 'https://api.nexus.dynaminds.pl';
const WEB = 'https://nexus.dynaminds.pl';
if (__ENV.QA_CONFIRM !== 'nexus-prod-readonly') {
  throw new Error('Ustaw QA_CONFIRM=nexus-prod-readonly — to jest test PRODUKCJI (tylko odczyt).');
}
const TOKENS = JSON.parse(open('../../.qa/prod-tokens.json')).sessions;
const byRole = (roles) => TOKENS.filter((s) => roles.includes(s.role));
const POOLS = {
  recruiter: byRole(['recruiter', 'sourcer', 'head_of_recruitment']),
  delivery: byRole(['delivery_lead', 'tac', 'talent_community_manager']),
  management: byRole(['admin', 'finance', 'head_of_recruitment']),
};
for (const [name, pool] of Object.entries(POOLS)) {
  if (pool.length === 0) POOLS[name] = byRole(['admin']);
  if (POOLS[name].length === 0) throw new Error(`Brak tokenów dla puli ${name}`);
}

const profile = __ENV.K6_PROFILE || 'load';
if (!['smoke', 'load'].includes(profile)) throw new Error('K6_PROFILE: smoke albo load');

// Udział person w ruchu: 60% rekrutacja, 25% delivery, 15% kierownictwo.
const SHARES = { recruiter: 0.6, delivery: 0.25, management: 0.15 };
// Rampa: 10 osób (rozgrzewka) → 30 (docelowo) → 50 (zapas) → 0.
const STAGES = [
  { duration: '3m', target: 10 },
  { duration: '4m', target: 10 },
  { duration: '3m', target: 30 },
  { duration: '12m', target: 30 },
  { duration: '3m', target: 50 },
  { duration: '6m', target: 50 },
  { duration: '2m', target: 0 },
];
const scenarios = Object.fromEntries(Object.keys(SHARES).map((persona) => [persona, profile === 'smoke'
  ? { executor: 'constant-vus', vus: 1, duration: '2m', exec: persona, gracefulStop: '30s' }
  : {
      executor: 'ramping-vus', startVUs: 0, exec: persona, gracefulRampDown: '30s', gracefulStop: '30s',
      stages: STAGES.map((s) => ({ duration: s.duration, target: Math.max(s.target ? 1 : 0, Math.round(s.target * SHARES[persona])) })),
    }]));

export const options = {
  scenarios,
  maxRedirects: 0,
  userAgent: 'nexus-loadtest/k6 (read-only; contact: admin)',
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    // Hamulce bezpieczeństwa — przerywają test.
    http_req_failed: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '1m' }],
    http_req_duration: [{ threshold: 'p(95)<5000', abortOnFail: true, delayAbortEval: '1m' }],
    // Cele (raport, bez przerywania).
    'http_req_duration{kind:api}': ['p(95)<1500', 'p(99)<4000'],
    'http_req_duration{kind:web}': ['p(95)<2000'],
    checks: ['rate>0.99'],
  },
};

const screenTime = new Trend('screen_duration', true);
const screens = new Counter('screens_completed');

function pickFrom(list) { return list[Math.floor(Math.random() * list.length)]; }
function think(min = 5, max = 15) { sleep(min + Math.random() * (max - min)); }
function session(persona) {
  const pool = POOLS[persona];
  return pool[(exec.vu.idInTest - 1) % pool.length];
}

// Jedyna droga wysyłki żądań: GET bez przekierowań.
function get(url, name, token, { kind = 'api', expect = 200, cookie = false } = {}) {
  const headers = { Accept: kind === 'api' ? 'application/json' : 'text/html' };
  if (kind === 'api') headers.Authorization = `Bearer ${token}`;
  if (cookie) headers.Cookie = `nexus_access=${token}`;
  const res = http.get(url, { headers, tags: { name, kind }, timeout: '30s', redirects: 0 });
  check(res, { [`${name}: ${expect}`]: (r) => r.status === expect });
  return res;
}
function api(path, name, token, opts) { return get(API + path, name, token, opts); }
function json(res) { try { return res.json(); } catch (_) { return null; } }

// Ekran = kilka żądań wysłanych równolegle, jak przy wejściu na stronę.
function screen(name, token, requests) {
  const started = Date.now();
  group(name, () => {
    const batch = requests.map(([path, label]) => ['GET', API + path, null, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      tags: { name: label, kind: 'api', screen: name }, timeout: '30s', redirects: 0,
    }]);
    const responses = http.batch(batch);
    responses.forEach((r, i) => check(r, { [`${requests[i][1]}: 200`]: (x) => x.status === 200 }));
    screenTime.add(Date.now() - started, { screen: name });
    screens.add(1, { screen: name });
    return responses;
  });
}

// --- Dane referencyjne (identyfikatory) pobierane raz, przed testem. ---
export function setup() {
  const admin = byRole(['admin'])[0];
  if (!admin) throw new Error('setup wymaga tokenu admina');
  const read = (path, pick) => {
    const res = api(path, 'setup', admin.token);
    if (res.status !== 200) throw new Error(`setup ${path}: HTTP ${res.status}`);
    const ids = pick(json(res)).filter(Boolean);
    if (ids.length === 0) throw new Error(`setup ${path}: pusta lista`);
    return ids;
  };
  return {
    candidates: read('/api/candidates?page=1&page_size=100&sort=newest&semantics_version=2', (b) => b.items.map((c) => c.id)),
    jobs: read('/api/jobs?open_only=true&sort=newest&page=1&page_size=100', (b) => b.items.map((j) => j.id)),
    clients: read('/api/clients/directory?category=active&page=1&page_size=100', (b) => b.items.map((c) => c.client_id)),
    contracts: read('/api/contracts?status=active&status=ending&page=1&page_size=100', (b) => b.items.map((c) => c.id)),
  };
}

// Frazy wyszukiwania: stały, mały zbiór — osadzenia zapytań Voyage są
// pamiętane przez 5 min, więc tryb „auto” kosztuje kilka wywołań, nie setki.
const QUERIES = ['java', 'python', 'tester', 'devops', 'sap', 'react', 'analityk biznesowy', 'kierownik projektu'];

// Stan per wirtualna osoba (moduł jest osobny dla każdego VU).
let shellLoaded = false;
const lastPoll = {};
function poll(token, key, path, everySeconds) {
  const now = Date.now() / 1000;
  if (lastPoll[key] && now - lastPoll[key] < everySeconds) return;
  lastPoll[key] = now;
  api(path, `poll ${key}`, token);
}
// Odpytywanie w tle jak otwarta karta (WebSocket połączony → co 5 min).
function background(token, persona) {
  poll(token, 'notifications', '/api/notifications?limit=20', 300);
  poll(token, 'kpis_today', '/api/kpis/me/today', 300);
  poll(token, 'my_people', '/api/my-people/summary', 300);
  poll(token, 'board_tasks', '/api/board-tasks', 300);
  if (persona !== 'recruiter') poll(token, 'kpis_goals', '/api/kpis/me/goals', 300);
}
function shell(token) {
  if (shellLoaded) return;
  shellLoaded = true;
  get(`${WEB}/dashboard`, 'web /dashboard', token, { kind: 'web', cookie: true });
  get(`${WEB}/version.json`, 'web version.json', token, { kind: 'web' });
  screen('shell', token, [
    ['/api/auth/me', 'auth me'],
    ['/api/notifications?limit=20', 'notifications'],
    ['/api/kpis/me/today', 'kpis today'],
    ['/api/my-people/summary', 'my-people summary'],
    ['/api/jarvis/status', 'jarvis status'],
    ['/api/users/me/preferences', 'user preferences'],
  ]);
}
function dashboard(token, { nextSteps = false } = {}) {
  const reqs = [
    ['/api/users/me/dashboard', 'dashboard layout'],
    ['/api/board-tasks', 'board-tasks'],
  ];
  if (nextSteps) reqs.push(['/api/pipeline/my-next-steps', 'my-next-steps']);
  screen('dashboard', token, reqs);
}
function candidateProfile(token, id) {
  screen('candidate profile', token, [
    [`/api/candidates/${id}`, 'candidate detail'],
    [`/api/candidates/${id}/timeline?limit=50`, 'candidate timeline'],
    [`/api/candidates/${id}/history`, 'candidate history'],
    [`/api/candidates/${id}/documents`, 'candidate documents'],
    [`/api/candidates/${id}/risk`, 'candidate risk'],
    [`/api/candidates/${id}/activity-summary`, 'candidate activity-summary'],
    [`/api/candidates/${id}/recent-recruitments?limit=5`, 'candidate recent-recruitments'],
    [`/api/candidates/${id}/languages`, 'candidate languages'],
    [`/api/candidates/${id}/ai-profile`, 'candidate ai-profile'],
  ]);
}
function jobBoard(token, id) {
  screen('job board', token, [
    [`/api/jobs/${id}`, 'job detail'],
    [`/api/pipeline/kanban/${id}`, 'kanban'],
    [`/api/jobs/${id}/chat/unread-count`, 'job chat unread'],
  ]);
}

export function recruiter(data) {
  const { token } = session('recruiter');
  shell(token);
  dashboard(token, { nextSteps: Math.random() < 0.3 });
  think();
  screen('candidates list', token, [
    ['/api/candidates?page=1&sort=newest&semantics_version=2&page_size=50&include_active_recruitments=true', 'candidates list'],
    ['/api/candidates?page=1&page_size=1&semantics_version=2', 'candidates total'],
  ]);
  think();
  const q = encodeURIComponent(pickFrom(QUERIES));
  const mode = Math.random() < 0.5 ? 'auto' : 'literal';
  screen('candidates search', token, [
    [`/api/candidates?q=${q}&text_mode=${mode}&sort=relevance&semantics_version=2&page=1&page_size=50&include_active_recruitments=true`, `candidates search ${mode}`],
  ]);
  think();
  candidateProfile(token, pickFrom(data.candidates));
  think();
  background(token, 'recruiter');
  screen('jobs list', token, [
    ['/api/jobs?mine=true&sort=attention&page=1&include_stage_counts=true', 'jobs list mine'],
    ['/api/jobs/quick-counts', 'jobs quick-counts'],
  ]);
  think();
  jobBoard(token, pickFrom(data.jobs));
  think();
  candidateProfile(token, pickFrom(data.candidates));
  think();
  screen('calendar', token, [['/api/interview-cycle?scope=mine', 'interview-cycle mine']]);
  think();
}

export function delivery(data) {
  const { token } = session('delivery');
  shell(token);
  dashboard(token);
  think();
  screen('clients directory', token, [
    ['/api/clients/directory?category=active&page=1&page_size=50&mine=true', 'clients directory mine'],
  ]);
  think();
  const client = pickFrom(data.clients);
  screen('client profile', token, [
    [`/api/clients/${client}`, 'client detail'],
    [`/api/clients/${client}/profile`, 'client profile'],
  ]);
  think();
  screen('client orders', token, [[`/api/clients/${client}/orders`, 'client orders']]);
  think();
  background(token, 'delivery');
  screen('contracts list', token, [
    ['/api/contracts?status=active&status=ending&group_by_candidate=true&page=1', 'contracts list'],
    ['/api/contracts/expiring', 'contracts expiring'],
    ['/api/clients-lookup', 'clients lookup'],
  ]);
  think();
  const contract = pickFrom(data.contracts);
  screen('contract detail', token, [
    [`/api/contracts/${contract}`, 'contract detail'],
    [`/api/contracts/${contract}/documents`, 'contract documents'],
    [`/api/contracts/${contract}/benchmark`, 'contract benchmark'],
  ]);
  think();
  screen('jobs list', token, [
    ['/api/jobs?mine=true&sort=attention&page=1&include_stage_counts=true', 'jobs list mine'],
  ]);
  think();
  jobBoard(token, pickFrom(data.jobs));
  think();
  screen('calendar', token, [['/api/interview-cycle?scope=jobs', 'interview-cycle jobs']]);
  think();
}

export function management(data) {
  const { token } = session('management');
  shell(token);
  dashboard(token);
  think();
  screen('insights rywalizacja', token, [
    ['/api/insights/campaigns/active', 'insights campaign'],
    ['/api/competitions/current?type=quarterly_champions_recruiter', 'competition recruiter'],
    ['/api/competitions/current?type=quarterly_champions_dl', 'competition dl'],
    ['/api/competitions/current?type=hall_of_fame', 'competition hall of fame'],
    ['/api/competitions/monthly-races', 'monthly races'],
    ['/api/insights/recruitment/seniority', 'insights seniority'],
  ]);
  think(10, 20);
  screen('insights zespol', token, [
    ['/api/insights/recruitment/funnel?period=month&offset=0', 'insights funnel'],
    ['/api/insights/team/attention', 'insights team attention'],
    ['/api/insights/team/people?period=month&offset=0', 'insights team people'],
    ['/api/insights/performance-flags', 'insights performance flags'],
  ]);
  think(10, 20);
  background(token, 'management');
  screen('jobs list', token, [
    ['/api/jobs?open_only=true&sort=newest&page=1&include_stage_counts=true', 'jobs list open'],
    ['/api/jobs/quick-counts', 'jobs quick-counts'],
  ]);
  think();
  jobBoard(token, pickFrom(data.jobs));
  think();
  candidateProfile(token, pickFrom(data.candidates));
  think();
}

export function handleSummary(data) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  return {
    [`.qa/loadrun/k6-summary-${profile}-${stamp}.json`]: JSON.stringify({ profile, ...data }, null, 2),
    stdout: textSummary(data),
  };
}

// Zwięzłe podsumowanie: p95 per endpoint (tag `name`) i błędy.
function textSummary(data) {
  const lines = [`\nProfil: ${profile}`];
  const m = data.metrics;
  const pct = (v) => (v * 100).toFixed(2) + '%';
  if (m.http_reqs) lines.push(`Żądania: ${m.http_reqs.values.count} (${m.http_reqs.values.rate.toFixed(1)}/s)`);
  if (m.http_req_failed) lines.push(`Błędy HTTP: ${pct(m.http_req_failed.values.rate)}`);
  if (m.checks) lines.push(`Poprawne odpowiedzi: ${pct(m.checks.values.rate)}`);
  for (const [k, v] of Object.entries(m)) {
    if (k.startsWith('http_req_duration{') && v.values) {
      lines.push(`${k}: p95=${Math.round(v.values['p(95)'])} ms, max=${Math.round(v.values.max)} ms`);
    }
  }
  return lines.join('\n') + '\n';
}
