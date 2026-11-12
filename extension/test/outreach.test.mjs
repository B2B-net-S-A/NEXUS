// Recruiter Lite (1.0.8): podpowiedź przed InMailem, odpowiedź jednym kliknięciem,
// lista „do przejrzenia” i wyszukiwanie do Recruitera. Wymyślone dane.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { parseHTML } from "linkedom";

import { loadFixture } from "./helpers.mjs";
import { degreeFromTexts } from "../src/readers/dom.js";
import { creditsLeft, inmailAdvice, inmailUsageLabel, isTodo, lastContactLine, listForClipboard, replyPrompt, triage } from "../src/view/outreach.js";

let renderPerson, initialPersonState, renderList, initialListState, applyBatch, readPageDom;

before(async () => {
  const { window } = parseHTML("<!doctype html><html><body></body></html>");
  globalThis.document = window.document;
  globalThis.Node = window.Node;
  ({ renderPerson, initialPersonState } = await import("../src/panel/screen-person.js"));
  ({ renderList, initialListState, applyBatch } = await import("../src/panel/screen-list.js"));
  ({ readPageDom } = await import("../src/readers/index.js"));
});

const text = (node) => node.textContent.replace(/\s+/g, " ");
const flush = () => new Promise((r) => setTimeout(r, 0));
const ME = { user: { id: 26, name: "Malwina Testowa", initials: "MT" }, usage: { reads_today: 3, reads_limit: 150 }, inmail: { sent_month: 12, replied_month: 5, credits_month: 30 } };

function makeCtx(state, apiOverrides = {}, extra = {}) {
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
  const ctx = { state, api, calls, render: () => {}, onWrite: () => {}, addLocalContact: () => {}, addLocalProcess: () => {}, refreshLookup: () => {}, applyReply: (o) => calls.push(["applyReply", o]), checkList: () => {}, ...extra };
  return ctx;
}

const FOUND = {
  status: "found",
  candidate: { id: 1, name: "Zofia Testowa", headline: "Analityk", city: "Gdańsk", url: "https://nexus.example.test/candidates/1", in_nexus_since: "2024-03-02" },
  owner: null, processes: [], contacts: [], matches: [], ambiguous: [], rate: null, rodo: { status: "none", label: "brak zgody" },
  off_limits: null, contractor: null, job_change: null, active_job: null,
  outreach: { has_phone: false, recent_contact: null, open_inmail: null, last_reply: null },
};

function personState(outreach, degree = null) {
  const read = readPageDom(loadFixture("profile-public.html"), "https://www.linkedin.com/in/zofia-testowa-123/");
  if (degree) read.profile.degree = degree;
  return { me: ME, read, lookup: { ...FOUND, outreach: { ...FOUND.outreach, ...outreach } }, person: initialPersonState(), tab: { id: 1, url: read.profile.page_url }, page: { kind: "profile", key: "in/zofia-testowa-123" } };
}

// ── Czyste funkcje ──────────────────────────────────────────────────────────

test("stopień kontaktu z linii karty i wiersza wyników", () => {
  assert.equal(degreeFromTexts(["Jan Kowalski • 2nd", "Analityk"]), 2);
  assert.equal(degreeFromTexts(["Jan Kowalski", "· 3rd+"]), 3);
  assert.equal(degreeFromTexts(["Jan Kowalski", "1."]), 1);
  assert.equal(degreeFromTexts(["Jan Kowalski", "Senior, poziom 1."]), null, "„1.” na końcu zdania to nie stopień");
  assert.equal(degreeFromTexts([]), null);
  assert.equal(degreeFromTexts(undefined), null);
});

test("podpowiedź przed InMailem: telefon, 2. stopień, mój otwarty InMail, kolega", () => {
  const advice = inmailAdvice({
    outreach: {
      has_phone: true,
      open_inmail: { note_id: 7, at: "2026-10-21T10:00:00+02:00", refund_until: "2027-01-19" },
      recent_contact: { at: "2026-11-03T10:00:00+01:00", user_name: "Ania", channel_label: "InMail", is_me: false, days_ago: 9 },
    },
    degree: 2,
    inmail: { sent_month: 12, credits_month: 30 },
  });
  const all = advice.checks.map((c) => c.text).join(" | ");
  assert.equal(advice.cheaper, "invitation");
  for (const s of ["W NEXUSIE jest telefon", "2. stopień", "Twój InMail z 21.10.2026 czeka na odpowiedź", "do 19.01.2027", "Ania: InMail 9 dni temu"]) assert.ok(all.includes(s), s);
  assert.ok(!all.includes("Zostało"), "przy 18 wolnych nie ostrzega");
});

test("podpowiedź: mój świeży kontakt i stary kontakt kolegi nie ostrzegają, 1. stopień = wiadomość", () => {
  const advice = inmailAdvice({
    outreach: { has_phone: false, recent_contact: { user_name: "Ania", is_me: true, days_ago: 2 } },
    degree: 1,
  });
  assert.equal(advice.cheaper, "linkedin_message");
  assert.ok(!advice.checks.some((c) => c.text.includes("Uzgodnij")));
  const old = inmailAdvice({ outreach: { recent_contact: { user_name: "Ania", is_me: false, days_ago: 31 } } });
  assert.equal(old.cheaper, null);
  assert.deepEqual(old.checks.map((c) => c.text), ["Nie widzę tańszej drogi: InMail ma tu sens."]);
});

test("licznik InMaili: ostrzeżenie przy ≤ 5 wolnych i po wyczerpaniu", () => {
  assert.equal(creditsLeft({ sent_month: 27, credits_month: 30 }), 3);
  assert.equal(creditsLeft({ sent_month: 33, credits_month: 30 }), 0);
  assert.equal(creditsLeft(null), null);
  assert.ok(inmailAdvice({ inmail: { sent_month: 27, credits_month: 30 } }).checks.some((c) => c.text === "Zostało 3 InMaili w tym miesiącu."));
  assert.ok(inmailAdvice({ inmail: { sent_month: 30, credits_month: 30 } }).checks.some((c) => c.text.includes("się skończyły")));
  assert.equal(inmailUsageLabel({ sent_month: 12, replied_month: 5, credits_month: 30 }), "InMaile w tym miesiącu: 12 z 30 · odpowiedzi 5");
  assert.equal(inmailUsageLabel({ sent_month: 0, replied_month: 0, credits_month: 30 }), "InMaile w tym miesiącu: 0 z 30");
  assert.equal(inmailUsageLabel(undefined), "", "starszy NEXUS bez pola");
});

test("pytanie o odpowiedź tylko przy moim otwartym InMailu", () => {
  assert.equal(replyPrompt(null), null);
  assert.equal(replyPrompt({ open_inmail: null }), null);
  const p = replyPrompt({ open_inmail: { note_id: 77, at: "2026-10-21T10:00:00+02:00", job_title: "Analityk biznesowy", refund_until: "2027-01-19" } });
  assert.equal(p.noteId, 77);
  assert.equal(p.title, "Twój InMail z 21.10.2026 · Analityk biznesowy");
  assert.ok(p.refund.includes("19.01.2027"));
});

test("lista: do przejrzenia = nowi i „w bazie” bez kontaktu zespołu w 30 dni", () => {
  const items = [
    { index: 0, status: "new" },
    { index: 1, status: "in_base", last_contact: { days_ago: 9, user_name: "Ania", channel_label: "InMail" }, has_phone: true },
    { index: 2, status: "in_base", last_contact: { days_ago: 400, at: "2025-03-14T10:00:00+01:00", channel_label: "telefon" } },
    { index: 3, status: "in_process", has_phone: true },
    { index: 4, status: "off_limits" },
    { index: 5, status: "contractor" },
  ];
  assert.deepEqual(items.map(isTodo), [true, false, true, false, false, false]);
  assert.deepEqual(triage(items), { total: 6, todo: 2, inBase: 3, withPhone: 2, recent: 1, offLimits: 1, contractors: 1 });
  assert.deepEqual(lastContactLine(items[1].last_contact), { tone: "warning", text: "Ania: InMail 9 dni temu" });
  assert.deepEqual(lastContactLine(items[2].last_contact), { tone: "muted", text: "Ostatni kontakt: 03.2025 · telefon" });
  assert.deepEqual(lastContactLine({ is_me: true, days_ago: 0, channel_label: "InMail" }), { tone: "warning", text: "Ty: InMail dziś" });
  assert.equal(lastContactLine(null), null);
  assert.equal(listForClipboard(["A", "", "B"]), "A\nB");
});

// ── Ekrany ──────────────────────────────────────────────────────────────────

test("wiadomość: „Zanim wydasz InMail” z licznikiem i przejściem na zaproszenie", async () => {
  const state = personState({ has_phone: true }, 2);
  state.person.tab = "message";
  state.person.message = { job: { id: 11, title: "Analityk" }, kind: "inmail", text: "Cześć", ai: true, busy: false, error: null, notice: null, remind: "3", requested: true };
  const ctx = makeCtx(state, { draftMessage: () => ({ text: "Zaproszenie", ai: true }) });
  const node = renderPerson(ctx);
  const t = text(node);
  for (const s of ["Zanim wydasz InMail", "12 z 30", "W NEXUSIE jest telefon", "2. stopień", "Napisz zaproszenie"]) assert.ok(t.includes(s), s);
  [...node.querySelectorAll("button")].find((b) => b.textContent === "Napisz zaproszenie").click();
  await flush();
  assert.equal(state.person.message.kind, "invitation");
  const draft = ctx.calls.find((c) => c[0] === "draftMessage");
  assert.equal(draft[2], "invitation");
  assert.ok(!text(renderPerson(ctx)).includes("Zanim wydasz InMail"), "przy zaproszeniu bloku nie ma");
});

test("wiadomość: starszy NEXUS bez `outreach` i `inmail` — blok bez licznika, bez błędu", () => {
  const state = personState({});
  state.lookup.outreach = null;
  state.me = { ...ME, inmail: undefined };
  state.person.tab = "message";
  state.person.message = { job: { id: 11, title: "Analityk" }, kind: "inmail", text: "Cześć", ai: true, busy: false, error: null, notice: null, remind: "3", requested: true };
  const t = text(renderPerson(makeCtx(state)));
  assert.ok(t.includes("Nie widzę tańszej drogi"));
  assert.ok(!t.includes(" z 30"));
});

test("osoba: „Tak, chce rozmawiać” zapisuje odpowiedź na mój InMail", async () => {
  const state = personState({ open_inmail: { note_id: 77, at: "2026-10-21T10:00:00+02:00", job_title: "Analityk biznesowy", refund_until: "2027-01-19" } });
  const ctx = makeCtx(state, { replyToContact: () => ({ id: 90, closed_reminders: 1 }) });
  const node = renderPerson(ctx);
  const t = text(node);
  for (const s of ["Twój InMail z 21.10.2026 · Analityk biznesowy", "Tak, chce rozmawiać", "Tak, nie teraz", "Bez odpowiedzi", "do 19.01.2027"]) assert.ok(t.includes(s), s);
  [...node.querySelectorAll("button")].find((b) => b.textContent === "Tak, chce rozmawiać").click();
  await flush();
  assert.deepEqual(ctx.calls.find((c) => c[0] === "replyToContact"), ["replyToContact", 1, 77, "interested"]);
  assert.deepEqual(ctx.calls.find((c) => c[0] === "applyReply"), ["applyReply", "interested"]);
  assert.equal(state.person.notice, "Zapisane: chce rozmawiać.");
});

test("osoba: bez otwartego InMaila nie ma pytania o odpowiedź", () => {
  assert.ok(!text(renderPerson(makeCtx(personState({})))).includes("Odpowiedź przyszła?"));
});

function listState(source = "recruiter_project") {
  const read = readPageDom(loadFixture("search-results.html"), "https://www.linkedin.com/search/results/people/?keywords=java");
  const state = { me: ME, list: initialListState(), page: { kind: "search_results", source }, tab: { id: 1, url: "https://www.linkedin.com/talent/hire/555/manage/all" } };
  return { state, read };
}

test("lista: podsumowanie, filtr „do przejrzenia” i dopiski w wierszach", () => {
  const { state, read } = listState();
  read.people[0].degree = 2;
  applyBatch(state.list, read, {
    items: [
      { index: 0, status: "new" },
      { index: 1, status: "in_base", candidate_id: 5, has_phone: true, last_contact: { user_name: "Ania", channel_label: "InMail", is_me: false, days_ago: 9 } },
    ],
  });
  state.list.selected.add(1);
  const ctx = makeCtx(state);
  let node = renderList(ctx);
  let t = text(node);
  for (const s of ["Z 2 osób do przejrzenia 1.", "kontakt zespołu < 30 dni: 1", "☎ telefon w NEXUSIE", "Ania: InMail 9 dni temu", "2. stopień · zaproszenie zamiast InMaila"]) assert.ok(t.includes(s), s);
  assert.equal(node.querySelectorAll(".result").length, 2);
  [...node.querySelectorAll(".segmented__item")].find((b) => b.textContent.startsWith("Do przejrzenia")).click();
  assert.equal(state.list.filter, "todo");
  assert.ok(!state.list.selected.has(1), "ukryta osoba odznaczona");
  node = renderList(ctx);
  assert.equal(node.querySelectorAll(".result").length, 1);
});

test("wyszukiwanie: zestaw do Recruitera przy rekrutacji z paska, nie w projekcie", () => {
  const kit = { busy: false, error: null, data: { job_id: 11, title: "Analityk", keywords: '("Analityk biznesowy") AND BPMN', titles: ["Analityk biznesowy"], skills_must: ["BPMN"], skills_nice: ["UML"], locations: ["Gdańsk"], remote: null, exclude_companies: ["Klient Testowy", "Bank Północny"] } };
  const job = { id: 11, title: "Analityk" };
  const { state } = listState("recruiter_search");
  state.activeJob = job;
  const asked = [];
  const t = text(renderList(makeCtx(state, {}, { searchKit: (id) => (asked.push(id), kit) })));
  for (const s of ["Wyszukiwanie do Recruitera · Analityk", '("Analityk biznesowy") AND BPMN', "UML", "Gdańsk", "Wyklucz obecną firmę: off-limits (2)", "Kopiuj 2", "Sprawdź tę stronę"]) assert.ok(t.includes(s), s);
  assert.deepEqual(asked, [11]);

  const project = listState("recruiter_project").state;
  project.activeJob = job;
  assert.ok(!text(renderList(makeCtx(project, {}, { searchKit: () => kit }))).includes("Wyszukiwanie do Recruitera"));

  const failed = listState("recruiter_search").state;
  failed.activeJob = job;
  assert.ok(text(renderList(makeCtx(failed, {}, { searchKit: () => ({ busy: false, data: null, error: "Nie ma takiej rekrutacji." }) }))).includes("Nie ma takiej rekrutacji."));
});
