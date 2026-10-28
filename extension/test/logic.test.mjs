import { test } from "node:test";
import assert from "node:assert/strict";

import { ApiError, ERROR_KINDS } from "../src/api.js";
import {
  OFF_LIMITS_HOW,
  SCREENS,
  addButtonLabel,
  batchCounters,
  chooseScreen,
  companySinceLabel,
  contractorText,
  defaultJobId,
  formatDate,
  formatMonthYear,
  formatTenure,
  inNexusSinceLabel,
  isSelectable,
  jobIdsForHow,
  ownerText,
  pluralYears,
  processPill,
  profileFromListPerson,
  scoreTone,
  screenForError,
  tenureMonths,
  todayLabel,
  usageLabel,
} from "../src/view/logic.js";

const NOW = new Date("2026-10-28T10:00:00Z");

test("chooseScreen: found → osoba, not_found → dodaj, ambiguous → wybór", () => {
  assert.equal(chooseScreen({ status: "found", candidate: { id: 1 } }).screen, SCREENS.PERSON);
  assert.equal(chooseScreen({ status: "not_found" }).screen, SCREENS.ADD);
  assert.equal(chooseScreen({ status: "ambiguous" }).screen, SCREENS.AMBIGUOUS);
  const off = chooseScreen({ status: "not_found", off_limits: { client_name: "Klient X", company: "Firma Y" } });
  assert.equal(off.screen, SCREENS.ADD);
  assert.deepEqual(off.offLimits, { client_name: "Klient X", company: "Firma Y" });
  assert.ok(chooseScreen({ status: "found", candidate: {}, contractor: { client_name: "K" } }).contractor);
});

test("screenForError: awaria nigdy nie daje ekranu „Nie ma w NEXUSIE”", () => {
  for (const kind of Object.values(ERROR_KINDS)) {
    const s = screenForError(new ApiError(kind, { message: "x" }));
    assert.notEqual(s.screen, SCREENS.ADD, kind);
    assert.notEqual(s.screen, SCREENS.PERSON, kind);
  }
  assert.equal(screenForError(new ApiError(ERROR_KINDS.KEY_INVALID)).screen, SCREENS.CONNECT);
  assert.equal(screenForError(new ApiError(ERROR_KINDS.DAILY_LIMIT)).screen, SCREENS.LIMIT);
  assert.equal(screenForError(new ApiError(ERROR_KINDS.NETWORK, { message: "Nie udało się połączyć z NEXUSEM. Spróbuj ponownie." })).screen, SCREENS.ERROR);
  assert.equal(screenForError(new TypeError("x")).screen, SCREENS.ERROR);
  assert.equal(screenForError(new ApiError(ERROR_KINDS.FORBIDDEN, { message: "Brak uprawnień" })).retryable, false);
});

test("formatowanie dat: „W NEXUSIE od 03.2024”", () => {
  assert.equal(inNexusSinceLabel({ in_nexus_since: "2024-03-02" }), "W NEXUSIE od 03.2024");
  assert.equal(inNexusSinceLabel({ in_nexus_since: null }), "W NEXUSIE");
  assert.equal(formatMonthYear("2027-03-31"), "03.2027");
  assert.equal(formatDate("2026-10-27T21:30:00Z"), "27.10.2026");
  assert.equal(formatDate(""), "");
  assert.equal(todayLabel(new Date("2026-10-28T23:30:00Z")), "29.10.2026"); // kalendarz Warszawy
});

test("staż z historii pracy: nakładające się role liczone raz, „obecnie” do dziś", () => {
  const exp = [
    { start: "2022-03", end: null, current: true }, // 2022-03..2026-10 = 56 mies.
    { start: "2019-01", end: "2022-02", current: false }, // 38
    { start: "2020-01", end: "2020-12", current: false }, // w środku poprzedniej — nic nie dodaje
    { start: "2017-01", end: "2017-12", current: false }, // 12
  ];
  assert.equal(tenureMonths(exp, NOW), 56 + 38 + 12);
  assert.equal(formatTenure(tenureMonths(exp, NOW)), "8 lat 10 mies.");
  assert.equal(tenureMonths([{ start: null, end: null }], NOW), 0);
  assert.equal(tenureMonths([], NOW), 0);
  assert.equal(formatTenure(0), "");
  assert.equal(formatTenure(12), "1 rok");
  assert.equal(formatTenure(5), "5 mies.");
  assert.equal(formatTenure(26), "2 lata 2 mies.");
});

test("odmiana lat", () => {
  assert.deepEqual([1, 2, 4, 5, 11, 12, 14, 21, 22, 25].map(pluralYears), ["rok", "lata", "lata", "lat", "lat", "lat", "lat", "lat", "lata", "lat"]);
});

test("firma od…, przycisk dodania, procent", () => {
  assert.equal(
    companySinceLabel({ current_company: "Fikcyjna Software", experience: [{ company: "Fikcyjna Software", start: "2022-03", current: true }] }),
    "Fikcyjna Software · od 03.2022",
  );
  assert.equal(companySinceLabel({ current_company: "Firma", experience: [] }), "Firma");
  assert.equal(companySinceLabel({ current_company: null }), "");
  assert.equal(addButtonLabel(0), "Dodaj do NEXUSA");
  assert.equal(addButtonLabel(2), "Dodaj do NEXUSA i do 2 rekrutacji");
  assert.equal(scoreTone(70), "success");
  assert.equal(scoreTone(69), "warning");
});

test("ramki: właściciel, kontraktor", () => {
  assert.equal(ownerText({ name: "Katarzyna", last_contact_at: "2026-10-01T10:00:00Z" }), "Prowadzi ją Katarzyna. Ostatni kontakt 01.10.2026. Zanim napiszesz, daj jej znać.");
  assert.match(ownerText({ name: "Katarzyna", last_contact_at: null }), /Brak zapisanego kontaktu/);
  assert.equal(
    contractorText({ client_name: "Klient Testowy", end_date: "2027-03-31", delivery_lead_name: "Michał" }),
    "To nasz kontraktor. Pracuje przez B2B Network w Klient Testowy do 31.03.2027. Delivery Lead: Michał. Nie proponuj mu innych projektów bez rozmowy z Michał.",
  );
});

test("off-limits: 6 odpowiedzi „sam się zgłosił” + „Nie, to my” bez rekrutacji", () => {
  assert.deepEqual(OFF_LIMITS_HOW.map((o) => o.value), ["linkedin_inbound", "sent_cv_before", "job_ad", "phone_or_email", "referral", "left_company", "skip"]);
  assert.deepEqual(jobIdsForHow("skip", [1, 2]), []);
  assert.deepEqual(jobIdsForHow("linkedin_inbound", [1, 2]), [1, 2]);
});

test("pill procesu: etap albo „Odrzucona · powód”", () => {
  assert.deepEqual(processPill({ closed: false, stage_label: "Screening" }), { text: "Screening", tone: "info" });
  assert.deepEqual(processPill({ closed: true, close_label: "za wysoka stawka" }), { text: "Odrzucona · za wysoka stawka", tone: "error" });
});

test("domyślna rekrutacja do wiadomości: otwarty proces, potem najlepsze dopasowanie", () => {
  assert.equal(defaultJobId({ processes: [{ job_id: 1, closed: true }, { job_id: 2, closed: false }], matches: [{ job_id: 9, score: 99 }] }), 2);
  assert.equal(defaultJobId({ processes: [], matches: [{ job_id: 8, score: 60 }, { job_id: 9, score: 81 }] }), 9);
  assert.equal(defaultJobId({ processes: [], matches: [] }), null);
});

test("lista wyników: liczniki i zaznaczanie (off-limits i kontraktora nie da się zaznaczyć)", () => {
  const items = [
    { index: 0, status: "new" },
    { index: 1, status: "new" },
    { index: 2, status: "in_process" },
    { index: 3, status: "in_base" },
    { index: 4, status: "off_limits" },
    { index: 5, status: "contractor" },
  ];
  assert.deepEqual(batchCounters(items), { new: 2, in_process: 1, in_base: 1, off_limits: 1, contractor: 1 });
  assert.deepEqual(items.map(isSelectable), [true, true, true, true, false, false]);
});

test("profil z pozycji listy zawiera tylko to, co widać w wynikach", () => {
  const p = profileFromListPerson({ full_name: "Marta Fikcyjna", public_url: "https://www.linkedin.com/in/marta-fikcyjna", headline: "Dev", current_company: "Studio", location: "Poznań" }, "https://www.linkedin.com/search/results/people/?k=1", "search");
  assert.equal(p.page_kind, "profile");
  assert.equal(p.full_name, "Marta Fikcyjna");
  assert.equal(p.current_company, "Studio");
  assert.equal(p.location, null);
  assert.deepEqual(p.experience, []);
  assert.equal(profileFromListPerson({ full_name: "X" }, "u", "recruiter_search").page_kind, "recruiter_profile");
});

test("licznik odczytów w menu", () => {
  assert.equal(usageLabel({ reads_today: 34, reads_limit: 150 }), "Dziś: 34 / 150 odczytów");
  assert.equal(usageLabel(null), "");
});

test("kontakt zapisany w panelu trafia od razu na oś osoby (bez nowego odczytu)", async () => {
  const { withLocalContact } = await import("../src/view/logic.js");
  const lookup = { status: "found", contacts: [{ at: "2026-10-01T10:00:00Z", user_name: "Anna Fikcyjna", channel_label: "telefon", note: null }] };
  const next = withLocalContact(lookup, { channel: "inmail", note: "rekrutacja: Java Developer", userName: "Jan Testowy", at: "2026-10-28T12:00:00Z" });
  assert.equal(next.contacts.length, 2);
  assert.deepEqual(next.contacts[0], { at: "2026-10-28T12:00:00Z", user_name: "Jan Testowy", channel_label: "InMail", note: "rekrutacja: Java Developer" });
  assert.equal(lookup.contacts.length, 1, "bez mutacji wejścia");
});
