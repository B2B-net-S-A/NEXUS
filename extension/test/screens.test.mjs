// Ekrany panelu rysowane na linkedom z wymyślonymi danymi: każdy się rysuje,
// ma właściwe teksty i woła właściwe trasy.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { parseHTML } from "linkedom";

import { loadFixture } from "./helpers.mjs";

let renderAdd, initialAddState, renderPerson, initialPersonState, renderList, initialListState, applyBatch, misc, readPageDom;

before(async () => {
  const { window } = parseHTML("<!doctype html><html><body></body></html>");
  globalThis.document = window.document;
  globalThis.Node = window.Node;
  ({ renderAdd, initialAddState } = await import("../src/panel/screen-add.js"));
  ({ renderPerson, initialPersonState } = await import("../src/panel/screen-person.js"));
  ({ renderList, initialListState, applyBatch } = await import("../src/panel/screen-list.js"));
  misc = await import("../src/panel/screen-misc.js");
  ({ readPageDom } = await import("../src/readers/index.js"));
});

const text = (node) => node.textContent.replace(/\s+/g, " ");
const flush = () => new Promise((r) => setTimeout(r, 0));

function makeCtx(state, apiOverrides = {}) {
  const calls = [];
  const api = new Proxy(
    {},
    {
      get: (_, name) => async (...args) => {
        calls.push([name, ...args]);
        if (apiOverrides[name]) return apiOverrides[name](...args);
        if (name === "jobs") return { items: [] };
        return {};
      },
    },
  );
  const ctx = { state, api, calls, renders: 0, render: () => (ctx.renders += 1), onWrite: () => {}, refreshLookup: () => {}, retry: () => {}, forceAdd: () => {}, checkList: () => {}, startConnect: () => {}, openSettings: () => {}, closeSettings: () => {}, saveServer: () => {} };
  return ctx;
}

const ME = { user: { id: 26, name: "Malwina Testowa", initials: "MT" }, usage: { reads_today: 34, reads_limit: 150 } };

function profileState(lookup) {
  const read = readPageDom(loadFixture("profile-public.html"), "https://www.linkedin.com/in/zofia-testowa-123/");
  return { me: ME, read, lookup, add: initialAddState(read), person: initialPersonState(), tab: { id: 1, url: read.profile.page_url }, page: { kind: "profile", key: "in/zofia-testowa-123" } };
}

const NOT_FOUND = {
  status: "not_found",
  processes: [],
  contacts: [],
  ambiguous: [],
  matches: [
    { job_id: 11, title: "Java Developer", client_name: "Klient Testowy", recruiter_name: "Katarzyna", score: 81 },
    { job_id: 12, title: "Kotlin Developer", client_name: "Inny Klient", recruiter_name: "Igor", score: 55 },
  ],
};

test("ekran 2: „Nie ma w NEXUSIE”, odczyt, dopasowania, stopka", () => {
  const state = profileState(NOT_FOUND);
  const t = text(renderAdd(makeCtx(state)));
  for (const s of ["Nie ma w NEXUSIE", "Odczytane z tej strony", "Zofia Testowa", "Fikcyjna Software · od 03.2022", "Kraków", "Popraw", "Pasuje do otwartych rekrutacji", "Java Developer", "Klient Testowy · Katarzyna", "81%", "Dodaj do NEXUSA", "Tylko do bazy", "Dołącz PDF profilu", "Źródło: LinkedIn · dodaje Malwina"]) {
    assert.ok(t.includes(s), s);
  }
  state.add.selected.add(11);
  assert.ok(text(renderAdd(makeCtx(state))).includes("Dodaj do NEXUSA i do 1 rekrutacji"));
});

test("ekran 2: brakujące pole pokazuje „nie odczytano — wpisz”", () => {
  const state = profileState(NOT_FOUND);
  state.add.profile.location = null;
  assert.ok(text(renderAdd(makeCtx(state))).includes("nie odczytano — wpisz"));
});

test("ekran 2: dodanie wysyła profil i zaznaczone rekrutacje, potem PDF", async () => {
  const state = profileState(NOT_FOUND);
  state.add.selected.add(11);
  state.add.pdfFile = { name: "profil.pdf" };
  const ctx = makeCtx(state, { addCandidate: async () => ({ candidate_id: 7, url: "https://nexus.example.test/candidates/7", created: true, assigned_job_ids: [11], skipped: [] }) });
  const node = renderAdd(ctx);
  [...node.querySelectorAll("button")].find((b) => b.textContent.includes("Dodaj do NEXUSA i do 1 rekrutacji")).click();
  await flush();
  await flush();
  assert.deepEqual(ctx.calls.find((c) => c[0] === "addCandidate").slice(2), [[11], null]);
  assert.equal(ctx.calls.find((c) => c[0] === "uploadProfilePdf")[1], 7);
  const after = text(renderAdd(ctx));
  assert.ok(after.includes("Dodano do NEXUSA"));
  assert.ok(after.includes("Rekrutacje: Java Developer"));
});

test("ekran 4: off-limits — pytanie, 7 odpowiedzi, przycisk „Dodaj: sam się zgłosił”", () => {
  const state = profileState({ ...NOT_FOUND, off_limits: { client_name: "Klient Testowy", company: "Fikcyjna Software" } });
  const node = renderAdd(makeCtx(state));
  const t = text(node);
  assert.ok(t.includes("Off-limits"));
  assert.ok(t.includes("Pracuje w Fikcyjna Software, a Klient Testowy ma aktywne zamówienia."));
  assert.equal(node.querySelectorAll("input[type=radio]").length, 7);
  assert.ok(t.includes("Dodaj: sam się zgłosił"));
  assert.ok(!t.includes("Tylko do bazy"));
});

test("409 off_limits przy dodaniu → pytanie z komunikatem NEXUSA, potem ponowny zapis z odpowiedzią", async () => {
  const { ApiError, ERROR_KINDS } = await import("../src/api.js");
  const state = profileState(NOT_FOUND);
  let first = true;
  const ctx = makeCtx(state, {
    addCandidate: async () => {
      if (first) {
        first = false;
        throw new ApiError(ERROR_KINDS.OFF_LIMITS, { status: 409, detail: { code: "off_limits_confirmation_required", message: "Fikcyjna Software jest off-limits dla Klienta Testowego.", candidates: [] } });
      }
      return { candidate_id: 8, created: true, assigned_job_ids: [], skipped: [] };
    },
  });
  [...renderAdd(ctx).querySelectorAll("button")].find((b) => b.textContent === "Dodaj do NEXUSA").click();
  await flush();
  const node = renderAdd(ctx);
  assert.ok(text(node).includes("Fikcyjna Software jest off-limits dla Klienta Testowego."));
  node.querySelector("input[value=linkedin_inbound]").dispatchEvent(new globalThis.document.defaultView.Event("change"));
  [...renderAdd(ctx).querySelectorAll("button")].find((b) => b.textContent === "Dodaj: sam się zgłosił").click();
  await flush();
  assert.equal(ctx.calls.filter((c) => c[0] === "addCandidate").at(-1)[3], "linkedin_inbound");
});

const FOUND = {
  status: "found",
  matched_by: "linkedin",
  candidate: { id: 1, name: "Zofia Testowa", headline: "Senior Java Developer", city: "Kraków", url: "https://nexus.example.test/candidates/1", in_nexus_since: "2024-03-02" },
  ambiguous: [],
  owner: { user_id: 85, name: "Katarzyna", is_me: false, last_contact_at: "2026-10-01T10:00:00Z" },
  processes: [
    { job_id: 1, job_title: "Java Developer", client_name: "Klient Testowy", stage_label: "Screening", recruiter_name: "Katarzyna", closed: false },
    { job_id: 2, job_title: "Tech Lead", client_name: "Inny Klient", stage_label: null, recruiter_name: "Igor", closed: true, close_label: "za wysoka stawka" },
  ],
  contacts: [{ at: "2026-10-01T10:00:00Z", user_name: "Katarzyna", channel_label: "telefon", note: "Oddzwoni po urlopie" }],
  rate: { label: "150 zł/h B2B", as_of: "2025-05-01" },
  rodo: { status: "valid", label: "zgoda do 03.2027" },
  off_limits: null,
  contractor: null,
  job_change: { page_company: "Fikcyjna Software", nexus_company: "Przykładowy Bank SA" },
  matches: [],
};

test("ekran 3: osoba w NEXUSIE — pill, właściciel, zmiana pracy, rekrutacje, kontakty, stawka, RODO, stopka", () => {
  const state = profileState(FOUND);
  const t = text(renderPerson(makeCtx(state)));
  for (const s of [
    "W NEXUSIE od 03.2024",
    "Otwórz w NEXUSIE ↗",
    "Prowadzi ją Katarzyna. Ostatni kontakt 01.10.2026. Zanim napiszesz, daj jej znać.",
    "Zaktualizuj w NEXUSIE",
    "W rekrutacjach",
    "Screening",
    "Odrzucona · za wysoka stawka",
    "Kontakty zespołu",
    "Oddzwoni po urlopie",
    "Stawka od",
    "150 zł/h B2B",
    "zgoda do 03.2027",
    "+ Rekrutacja",
    "Notatka",
    "Kontakt",
    "Wiadomość",
  ]) {
    assert.ok(t.includes(s), s);
  }
});

test("ekran 3: bez ramki właściciela, gdy prowadzę ją ja; kontraktor ma ramkę", () => {
  const state = profileState({ ...FOUND, owner: { ...FOUND.owner, is_me: true }, contractor: { client_name: "Klient Testowy", end_date: "2027-03-31", delivery_lead_name: "Michał" } });
  const t = text(renderPerson(makeCtx(state)));
  assert.ok(!t.includes("Prowadzi ją"));
  assert.ok(t.includes("To nasz kontraktor. Pracuje przez B2B Network w Klient Testowy do 31.03.2027. Delivery Lead: Michał."));
});

test("ekran 3: „Zaktualizuj w NEXUSIE” woła /refresh z odczytanym profilem", async () => {
  const state = profileState(FOUND);
  const ctx = makeCtx(state, { refresh: async () => ({ updated: ["current_company"] }) });
  [...renderPerson(ctx).querySelectorAll("button")].find((b) => b.textContent === "Zaktualizuj w NEXUSIE").click();
  await flush();
  const call = ctx.calls.find((c) => c[0] === "refresh");
  assert.equal(call[1], 1);
  assert.equal(call[2].full_name, "Zofia Testowa");
  assert.ok(text(renderPerson(ctx)).includes("Zaktualizowano firmę i stanowisko w NEXUSIE."));
});

test("ekran 5: wiadomość — szkic z /draft-message, kopiowanie, zapis kontaktu", async () => {
  const state = profileState(FOUND);
  state.person.tab = "message";
  const ctx = makeCtx(state, { draftMessage: async () => ({ text: "Cześć Zofia, mam rekrutację Java Developer.", ai: true }), addContact: async () => ({ id: 3, reminder_id: 4 }) });
  renderPerson(ctx);
  await flush();
  await flush();
  const draftCall = ctx.calls.find((c) => c[0] === "draftMessage");
  assert.deepEqual(draftCall.slice(1, 3), [1, "inmail"]);
  const node = renderPerson(ctx);
  const t = text(node);
  for (const s of ["InMail", "Zaproszenie · 300 zn.", "Napisz inaczej", "Kopiuj tekst", "Wysłałem, zapisz kontakt", "Przypomnij za 3 dni", "Wtyczka niczego nie wysyła sama. Tekst wklejasz i wysyłasz na LinkedInie."]) {
    assert.ok(t.includes(s), s);
  }
  assert.ok(!/RODO/.test(t));
  assert.equal(node.querySelector("textarea").value, "Cześć Zofia, mam rekrutację Java Developer.");
  [...node.querySelectorAll("button")].find((b) => b.textContent === "Wysłałem, zapisz kontakt").click();
  await flush();
  assert.deepEqual(ctx.calls.find((c) => c[0] === "addContact")[2], { channel: "inmail", jobId: 1, note: "Cześć Zofia, mam rekrutację Java Developer.", remindInDays: 3 });
});

test("ekran 6: lista — przed sprawdzeniem tylko przycisk, po sprawdzeniu liczniki i zaznaczanie", () => {
  const read = readPageDom(loadFixture("search-results.html"), "https://www.linkedin.com/search/results/people/?keywords=java");
  const state = { me: ME, list: initialListState(), page: { kind: "search_results", source: "search" }, tab: { id: 1, url: "https://www.linkedin.com/search/results/people/?keywords=java" } };
  let t = text(renderList(makeCtx(state)));
  assert.ok(t.includes("Sprawdź tę stronę"));
  assert.ok(t.includes("Odczyt tylko po kliknięciu „Sprawdź”, najwyżej jedna strona wyników naraz."));

  applyBatch(state.list, read, { items: [{ index: 0, status: "new", score: null }, { index: 1, status: "off_limits", label: "Off-limits · Klient Testowy", score: null }] });
  const node = renderList(makeCtx(state));
  t = text(node);
  for (const s of ["Nowi: 1", "W procesie: 0", "W bazie: 0", "Off-limits: 1", "Dodaj zaznaczone (1)", "Off-limits · Klient Testowy"]) assert.ok(t.includes(s), s);
  assert.ok(!t.includes("%"), "lista bez procentów");
  const boxes = node.querySelectorAll(".results input[type=checkbox]");
  assert.equal(boxes[0].checked, true);
  assert.equal(boxes[1].disabled, true);
});

test("ekran 6: „Dodaj zaznaczone” wysyła POST /candidates z profilem z listy", async () => {
  const read = readPageDom(loadFixture("search-results.html"), "https://www.linkedin.com/search/results/people/?keywords=java");
  const state = { me: ME, list: initialListState(), page: { kind: "search_results", source: "search" }, tab: { id: 1, url: "https://www.linkedin.com/search/results/people/?keywords=java" } };
  applyBatch(state.list, read, { items: [{ index: 0, status: "new" }, { index: 1, status: "new" }] });
  const ctx = makeCtx(state, { addCandidate: async () => ({ candidate_id: 5, created: true, assigned_job_ids: [], skipped: [] }) });
  [...renderList(ctx).querySelectorAll("button")].find((b) => b.textContent.startsWith("Dodaj zaznaczone")).click();
  await flush();
  await flush();
  const adds = ctx.calls.filter((c) => c[0] === "addCandidate");
  assert.equal(adds.length, 2);
  assert.equal(adds[0][1].full_name, "Marta Fikcyjna");
  assert.equal(adds[0][1].public_url, "https://www.linkedin.com/in/marta-fikcyjna");
  assert.deepEqual(adds[0][2], []);
});

test("ekrany 1 i stany: połączenie, błąd, limit, nieobsługiwana strona, kilka osób", () => {
  const ctx = makeCtx({ serverId: "production", me: ME, error: { message: "Nie udało się połączyć z NEXUSEM. Spróbuj ponownie." }, read: { profile: { full_name: "Zofia Testowa" } }, lookup: { ambiguous: [{ id: 2, name: "Zofia Testowa", company: "Inna Firma", url: "https://nexus.example.test/candidates/2" }] } });
  assert.ok(text(misc.renderConnect(ctx)).includes("Połącz wtyczkę z NEXUSEM"));
  assert.ok(text(misc.renderConnect(ctx)).includes("Zaloguj przez NEXUS"));
  assert.ok(text(misc.renderConnect(ctx)).includes("Serwer: Produkcja"));
  assert.ok(text(misc.renderError(ctx)).includes("Spróbuj ponownie"));
  assert.ok(text(misc.renderLimit(ctx)).includes("Dziś: 34 / 150 odczytów"));
  assert.ok(text(misc.renderUnsupported()).includes("Otwórz profil albo wyniki wyszukiwania na LinkedInie"));
  assert.ok(text(misc.renderAmbiguous(ctx)).includes("To nikt z nich — dodaj nową osobę"));
  assert.ok(text(misc.renderSettings(ctx)).includes("Staging na laptopie"));
});
