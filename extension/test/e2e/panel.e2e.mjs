// E2E wtyczki w prawdziwym Chromium: rozpakowana wtyczka z `extension/`,
// LinkedIn podstawiony stronami z `test/fixtures/`, NEXUS podstawiony
// fikcyjnymi odpowiedziami `/api/extension/*` (kontrakt w API.md). Nic nie
// wychodzi do sieci, nie trzeba backendu ani danych z produkcji.
//
// Łapie to, czego nie widzą testy w node (linkedom): `innerText` żywej strony,
// wstrzyknięcie `capturePage` przez `chrome.scripting`, panel z `chrome.*`.
// 29.10.2026 jednorazowa wersja tego testu znalazła „InformacjeInformacje”,
// „JavaJava” i „Zobacz profil” przy imieniu (#2798), przy zielonych testach w node.
//
// Uruchomienie: `npm run test:e2e` (z `extension/`); przeglądarka:
// `npx playwright-core install chromium`.

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const EXT_DIR = fileURLToPath(new URL("../../", import.meta.url));
const FIXTURES = fileURLToPath(new URL("../fixtures/", import.meta.url));
const MANIFEST = JSON.parse(readFileSync(join(EXT_DIR, "manifest.json"), "utf8"));

// Id wynikające z pola `key` w manifeście — na nie wskazuje LINKEDIN_EXTENSION_IDS.
const TEAM_EXTENSION_ID = "pmnonjpommkjblgacmpaclgacjmipplm";
// Staging z `config.js` — jest w `host_permissions`, więc panel woła go bez CORS.
// Każde zapytanie pod ten adres przechwytuje route niżej, także gdy na
// laptopie działa prawdziwy staging.
const API_BASE = "http://localhost:8100";
const FRONT_URL = "http://localhost:3100";
const FAKE_KEY = `nxe_v1_${"0".repeat(24)}_${"e2e".repeat(14)}`;
const NEWER_VERSION = MANIFEST.version.replace(/\d+$/, (n) => String(Number(n) + 1));

const PROFILE_URL = "https://www.linkedin.com/in/zofia-testowa-123/";
const SEARCH_URL = "https://www.linkedin.com/search/results/people/?keywords=java";
const OTHER_PROFILE_URL = "https://www.linkedin.com/in/inna-osoba-testowa/";

/** Fikcyjny NEXUS: odpowiedzi zgodne z API.md, zapis zapytań do sprawdzenia. */
function createFakeNexus() {
  const calls = [];
  const unexpected = [];
  const state = { added: false, keyValid: true };
  const usage = { reads_today: 3, reads_limit: 150, adds_today: 0 };
  const candidate = {
    id: 900001,
    name: "Zofia Testowa",
    headline: "Senior Java Developer · Spring | Kotlin",
    city: "Kraków",
    url: `${FRONT_URL}/candidates/900001`,
    in_nexus_since: "2026-10-29",
  };
  const match = { job_id: 700001, title: "Senior Java Developer", client_name: "Fikcyjny Bank", recruiter_name: "Ola Przykładowa", score: 81 };

  const handlers = {
    "GET /me": () => ({
      user: { id: 1, name: "Ola Przykładowa", initials: "OP" },
      usage,
      frontend_url: FRONT_URL,
      latest_version: NEWER_VERSION,
    }),
    "POST /lookup": () =>
      state.added
        ? {
            status: "found",
            matched_by: "linkedin",
            candidate,
            owner: { user_id: 1, name: "Ola Przykładowa", is_me: true, last_contact_at: null },
            processes: [{ job_id: 700001, job_title: "Senior Java Developer", client_name: "Fikcyjny Bank", stage_label: "Screening", recruiter_name: "Ola Przykładowa", closed: false, close_label: null, updated_at: "2026-10-29T10:00:00Z" }],
            contacts: [],
            rate: null,
            rodo: { status: "none", label: "brak zgody" },
            off_limits: null,
            contractor: null,
            job_change: null,
            matches: [match],
            usage,
          }
        : { status: "not_found", matched_by: null, candidate: null, owner: null, processes: [], contacts: [], rate: null, rodo: null, off_limits: null, contractor: null, job_change: null, matches: [match], usage },
    "POST /lookup-batch": (body) => ({
      items: body.people.map((p, index) =>
        index === 0
          ? { index, status: "new", candidate_id: null, label: null, score: null }
          : { index, status: "in_process", candidate_id: 900002, label: "Screening · Fikcyjny Bank · Ola Przykładowa", score: null },
      ),
      usage,
    }),
    "POST /candidates": (body) => {
      state.added = true;
      return [201, { candidate_id: candidate.id, url: candidate.url, created: true, assigned_job_ids: body.job_ids, skipped: [] }];
    },
    "GET /jobs": () => ({ items: [{ id: 700001, title: "Senior Java Developer", client_name: "Fikcyjny Bank", recruiter_name: "Ola Przykładowa" }] }),
  };

  async function handle(route) {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api\/extension/, "");
    const name = `${req.method()} ${path}`;
    const body = req.postData() ? JSON.parse(req.postData()) : null;
    calls.push({ name, body, key: req.headers()["x-extension-key"] });
    const json = (status, data) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (!state.keyValid) return json(401, { detail: "extension_key_invalid" });
    if (req.headers()["x-extension-key"] !== FAKE_KEY) return json(401, { detail: "extension_key_invalid" });
    const handler = handlers[name];
    if (!handler) {
      unexpected.push(name);
      return json(404, { detail: "not_found" });
    }
    const out = handler(body);
    return Array.isArray(out) ? json(out[0], out[1]) : json(200, out);
  }

  return { calls, unexpected, state, handle, callsOf: (name) => calls.filter((c) => c.name === name) };
}

let ctx;
let profileDir;
let extId;
let li;
let panel;
const nexus = createFakeNexus();
const outsideRequests = [];

/** Czeka, aż `#view` panelu pasuje do `pattern`; przy przekroczeniu czasu pokazuje, co jest na ekranie. */
async function viewMatching(pattern, timeout = 15000) {
  try {
    await panel.waitForFunction((src) => new RegExp(src, "i").test(document.querySelector("#view")?.innerText || ""), pattern.source, { timeout });
  } catch {
    const now = await panel.locator("#view").innerText().catch(() => "(brak #view)");
    assert.fail(`Panel nie pokazał ${pattern} w ${timeout} ms. Na ekranie:\n${now}`);
  }
  return panel.locator("#view").innerText();
}

async function waitForCall(name, count = 1) {
  const deadline = Date.now() + 15000;
  while (nexus.callsOf(name).length < count) {
    if (Date.now() > deadline) assert.fail(`NEXUS nie dostał ${count}× ${name}. Zapytania: ${nexus.calls.map((c) => c.name).join(", ") || "(żadne)"}`);
    await new Promise((r) => setTimeout(r, 100));
  }
  return nexus.callsOf(name).at(-1);
}

before(async () => {
  profileDir = mkdtempSync(join(tmpdir(), "nexus-ext-e2e-"));
  ctx = await chromium.launchPersistentContext(profileDir, {
    // Pełny Chromium w nowym trybie headless — headless shell nie wczytuje wtyczek.
    channel: "chromium",
    headless: true,
    args: [`--disable-extensions-except=${EXT_DIR}`, `--load-extension=${EXT_DIR}`],
    viewport: { width: 1280, height: 800 },
  });

  // Nic nie może wyjść poza podstawione strony — zapytanie w świat oblewa test.
  await ctx.route(/^https?:\/\//, (route) => {
    outsideRequests.push(route.request().url());
    return route.abort();
  });
  await ctx.route(`${API_BASE}/**`, (route) => nexus.handle(route));
  await ctx.route("https://www.linkedin.com/**", (route) => {
    const u = new URL(route.request().url());
    const file = u.pathname.startsWith("/in/") ? "profile-public.html" : u.pathname.startsWith("/search/results/people") ? "search-results.html" : null;
    if (!file) return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: readFileSync(join(FIXTURES, file)) });
  });

  let [sw] = ctx.serviceWorkers();
  if (!sw) sw = await ctx.waitForEvent("serviceworker", { timeout: 15000 });
  extId = new URL(sw.url()).host;

  li = await ctx.newPage();
  await li.goto(PROFILE_URL);

  // Panel boczny otwieramy jako zwykłą kartę. „Aktywna karta” dla panelu to
  // karta LinkedIna — podmiana przed skryptami panelu, bo `init()` czyta ją od razu.
  panel = await ctx.newPage();
  await panel.setViewportSize({ width: 420, height: 800 });
  await panel.addInitScript(() => {
    const query = chrome.tabs.query.bind(chrome.tabs);
    chrome.tabs.query = (q) => (q && q.active ? query({ url: "https://www.linkedin.com/*" }) : query(q));
  });
  await panel.goto(`chrome-extension://${extId}/src/panel/panel.html`);
});

after(async () => {
  await ctx?.close();
  if (profileDir) rmSync(profileDir, { recursive: true, force: true });
});

test("wtyczka wczytana ze stałym id z pola `key`", () => {
  assert.equal(extId, TEAM_EXTENSION_ID);
});

test("bez połączenia panel prosi o połączenie z NEXUSEM i nie woła API", async () => {
  await viewMatching(/Połącz wtyczkę z NEXUSEM/);
  assert.deepEqual(nexus.calls, []);
});

test("po połączeniu: profil odczytany z żywej strony i wysłany do lookup", async () => {
  await panel.evaluate(
    (connection) => chrome.storage.local.set({ server: "staging", connection }),
    { key: FAKE_KEY, apiBase: API_BASE, frontUrl: FRONT_URL, connectedAt: "2026-10-29T08:00:00Z" },
  );
  const lookup = await waitForCall("POST /lookup");
  assert.equal(lookup.key, FAKE_KEY);
  const p = lookup.body;
  assert.equal(p.page_kind, "profile");
  assert.equal(p.public_url, "https://www.linkedin.com/in/zofia-testowa-123");
  assert.equal(p.full_name, "Zofia Testowa");
  assert.equal(p.headline, "Senior Java Developer · Spring | Kotlin");
  assert.equal(p.location, "Kraków, Małopolskie, Polska");
  assert.equal(p.current_company, "Fikcyjna Software");
  assert.equal(p.current_title, "Senior Java Developer");
  assert.deepEqual(p.skills, ["Java", "Spring Boot", "Kotlin"]);
});

test("osoba spoza NEXUSA → ekran dodania bez pól „nie odczytano”", async () => {
  const view = await viewMatching(/Nie ma w NEXUSIE/);
  assert.match(view, /Zofia Testowa/);
  assert.match(view, /Fikcyjna Software/);
  assert.doesNotMatch(view, /nie odczytano/);
  assert.match(view, /Fikcyjny Bank/, "pasująca rekrutacja z lookup");
});

test("baner nowej wersji prowadzi do /wtyczka, pasek pokazuje połączoną osobę", async () => {
  assert.equal((await panel.locator("#update").innerText()).trim(), `Jest nowa wersja wtyczki (${NEWER_VERSION}). Pobierz z NEXUSA ↗`);
  assert.equal(await panel.locator("#update a").getAttribute("href"), `${FRONT_URL}/wtyczka`);
  assert.match(await panel.locator("#user").innerText(), /Ola/);
});

test("„Tylko do bazy” zakłada osobę, potem karta osoby z procesem", async () => {
  await panel.getByRole("button", { name: "Tylko do bazy" }).click();
  const add = await waitForCall("POST /candidates");
  assert.equal(add.body.profile.full_name, "Zofia Testowa");
  assert.deepEqual(add.body.job_ids, []);
  await viewMatching(/Dodano do NEXUSA/);

  await panel.getByRole("button", { name: "Pokaż kartę osoby" }).click();
  await waitForCall("POST /lookup", 2);
  const view = await viewMatching(/Screening/);
  assert.doesNotMatch(view, /Nie ma w NEXUSIE/);
  assert.match(view, /Zofia Testowa/);
});

test("lista wyników: osoby z żywej strony, bez „Członka LinkedIn” i duplikatów", async () => {
  await li.goto(SEARCH_URL);
  await viewMatching(/Sprawdź tę stronę/);
  await panel.getByRole("button", { name: "Sprawdź tę stronę" }).click();
  const batch = await waitForCall("POST /lookup-batch");
  assert.deepEqual(
    batch.body.people.map((p) => [p.full_name, p.public_url, p.headline, p.current_company]),
    [
      ["Marta Fikcyjna", "https://www.linkedin.com/in/marta-fikcyjna", "Frontend Developer at Wymyślone Studio", "Wymyślone Studio"],
      ["Tomasz Testowy", "https://www.linkedin.com/in/tomasz-testowy-77", "Backend Engineer | Go", null],
    ],
  );
  const view = await viewMatching(/Dodaj zaznaczone/);
  assert.match(view, /Marta Fikcyjna/);
  assert.match(view, /Tomasz Testowy/);
  assert.match(view, /Screening · Fikcyjny Bank/);
});

test("unieważniony klucz → panel wraca do połączenia i usuwa klucz", async () => {
  nexus.state.keyValid = false;
  await li.goto(OTHER_PROFILE_URL);
  await viewMatching(/Połącz wtyczkę ponownie|Połącz wtyczkę z NEXUSEM/);
  const stored = await panel.evaluate(() => chrome.storage.local.get("connection"));
  assert.equal(stored.connection, undefined);
});

test("żadne zapytanie nie wyszło poza podstawione strony i znane trasy", () => {
  assert.deepEqual(outsideRequests, []);
  assert.deepEqual(nexus.unexpected, []);
});
