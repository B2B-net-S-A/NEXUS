/**
 * Wariant 2 „Powtórka” (decyzja Artura 23.11.2026): poprzednia rekrutacja
 * jako baza, z maila tylko różnice (D3), hiring manager do potwierdzenia.
 */

import { describe, expect, it } from "vitest";

import {
  acceptIntakeOffer,
  intakeFillUndo,
  liveIntakeOffers,
  restoreIntakeOffers,
  undoIntakeFill,
} from "@/lib/job-intake-fill";
import {
  mergeRepeat,
  repeatTakeSummary,
  repeatTemplate,
  type RepeatSourceJob,
} from "@/lib/job-intake-repeat";
import {
  EMPTY_INTAKE_FORM,
  formFromIntake,
  type IntakeForm,
  type RequestIntakeResponse,
} from "@/lib/job-request-intake";

const SRC: RepeatSourceJob = {
  id: 43260,
  client_id: 7,
  title: "Backend Java developer - TOR Upgrde (43260)",
  description: "Stary request.",
  location: "Gdańsk, Warszawa",
  rate_budget_hourly: 130,
  rate_budget_hourly_min: 100,
  remote_policy: "hybrid",
  onsite_days_per_week: 3,
  headcount: 1,
  deadline_not_provided: true,
  competence_category_id: 12,
  hiring_manager_contact_id: 501,
  hiring_manager_name: "Anna Nowak",
  champion_profile: {
    stack: {
      rows: [
        { words: ["Java"], level: "must" },
        { words: ["Spring Boot", "Spring"], level: "must" },
        { words: ["Kafka"], level: "nice" },
      ],
      critical: ["Java"],
    },
    project: {
      about: "Stary opis projektu.",
      key_task: "Upgrade Javy 8 → 17 w module podatków.",
    },
    screening_questions: [
      { question: "Upgrade Javy?", ideal_answer: "Tak", deal_breaker: "Nigdy nie robił", key_task: true },
      { question: "Spring?", ideal_answer: "Tak", deal_breaker: "Nie zna Springa" },
    ],
  },
};

const MAIL: RequestIntakeResponse = {
  role_name: "Backend Java Developer",
  client_title: "Backend Java developer - TOR Upgrde (51234)",
  client_reference: "51234",
  must: ["Java", "Spring Boot", "AsyncAPI"],
  nice: [],
  seniority_min_years: 5,
  rate_budget_hourly: 150,
  rate_budget_hourly_min: 120,
  rate_quote: "120–150",
  rate_note: null,
  remote_policy: "hybrid",
  onsite_days_per_week: 3,
  office_city: "Gdańsk",
  office_cities: ["Gdańsk", "Warszawa"],
  start_date: null,
  project_about: "Nowy opis projektu z maila.",
  responsibilities: null,
  screening_questions: [
    { question: "Kafka?", ideal_answer: "Tak.", deal_breaker: "Nie zna Kafki.", from_request: true },
  ],
  requirements: [
    { words: ["Java"], level: "must" },
    { words: ["Spring Boot"], level: "must" },
    { words: ["AsyncAPI"], level: "must" },
  ],
  descriptive_requirements: [],
  evidence: [],
  missing: [],
  hiring_manager_name: null,
  hiring_manager_contact_id: null,
  hiring_manager_contact_name: null,
  deadline: null,
  headcount: null,
  provenance: { role: "request" },
} as unknown as RequestIntakeResponse;

const mail = (patch: Partial<RequestIntakeResponse> = {}): IntakeForm =>
  formFromIntake({ ...MAIL, ...patch });

describe("repeatTemplate", () => {
  it("bierze krytyczne, „Klient nie podał”, kategorię i zadanie z pytaniem; HM osobno", () => {
    const t = repeatTemplate(SRC, null);
    expect(t.form.rows.map((r) => [r.words, r.level])).toEqual([
      [["Java"], "critical"],
      [["Spring Boot", "Spring"], "must"],
      [["Kafka"], "nice"],
    ]);
    expect(t.form.deadlineNotProvided).toBe(true);
    expect(t.form.competenceCategoryId).toBe(12);
    expect(t.form.categoryConfirmed).toBe(true);
    expect(t.form.keyTask).toContain("Upgrade Javy");
    expect(t.form.keyTaskProposed).toBe(false);
    expect(t.form.questions.find((q) => q.keyTask)?.question).toBe("Upgrade Javy?");
    expect(t.form.headcount).toBe("1");
    // Hiring manager NIE trafia do formularza po cichu.
    expect(t.form.hiringManager).toBeNull();
    expect(t.hiringManager).toEqual({ kind: "contact", id: 501, name: "Anna Nowak" });
    expect(t.form.provenance.requirements).toBe("client_history");
    expect(t.form.provenance.rate).toBe("client_history");
  });

  it("`stack.critical: []` = „Brak krytycznych” przechodzi; bez HM nie ma czego potwierdzać", () => {
    const t = repeatTemplate(
      {
        ...SRC,
        hiring_manager_contact_id: null,
        champion_profile: { stack: { rows: [{ words: ["Go"], level: "must" }], critical: [] } },
      },
      null,
    );
    expect(t.form.noCritical).toBe(true);
    expect(t.hiringManager).toBeNull();
  });

  it("termin-data poprzedniej rekrutacji nie przechodzi (należała do starego requestu)", () => {
    const t = repeatTemplate({ ...SRC, deadline_not_provided: false }, null);
    expect(t.form.deadline).toBe("");
    expect(t.form.deadlineNotProvided).toBe(false);
  });

  it("kolumna „Weźmiemy z”: wymagania z krytycznymi, pytania z „odpada, gdy”, zadanie, budżet, tryb", () => {
    expect(repeatTakeSummary(repeatTemplate(SRC, null))).toEqual([
      "3 wymagania (krytyczne: Java)",
      "2 pytania z „odpada, gdy”",
      "najważniejsze zadanie + pytanie",
      "budżet 100–130",
      "hybrydowo 3 dni",
      "Gdańsk, Warszawa",
      "termin: klient nie podał",
      "1 osoba",
      "kategoria",
      "kanały ogłoszenia",
    ]);
  });
});

describe("mergeRepeat", () => {
  const template = () => repeatTemplate(SRC, null);

  it("z maila zawsze nazwa z numerem i opis projektu; reszta z szablonu", () => {
    const m = mergeRepeat(template(), mail(), { label: "43260" });
    expect(m.form.clientTitle).toBe("Backend Java developer - TOR Upgrde (51234)");
    expect(m.form.referenceHint).toBe("51234");
    expect(m.form.about).toBe("Nowy opis projektu z maila.");
    expect(m.form.provenance.about).toBe("request");
    // Wymagania i krytyczne jak w szablonie — nowe słowo z maila czeka jako propozycja.
    expect(m.form.rows.map((r) => [r.words[0], r.level])).toEqual([
      ["Java", "critical"],
      ["Spring Boot", "must"],
      ["Kafka", "nice"],
    ]);
    expect(m.form.keyTask).toContain("Upgrade Javy");
    expect(m.fromMail).toEqual(expect.arrayContaining(["nazwa i numer", "opis projektu", "rola"]));
  });

  it("puste pola szablonu bierze z maila (D3), inna wartość to propozycja „W mailu”", () => {
    const m = mergeRepeat(template(), mail(), { label: "43260" });
    // Rola i lata — szablon ich nie ma.
    expect(m.form.title).toBe("Backend Java Developer");
    expect(m.form.seniorityYears).toBe(5);
    // Budżet inny niż w szablonie: zostaje 100–130, mail proponuje 120–150.
    expect([m.form.rateBudgetMin, m.form.rateBudget]).toEqual(["100", "130"]);
    const budget = m.offers.find((o) => o.unit === "budget");
    expect(budget?.source).toBe("request");
    expect(budget?.patch).toMatchObject({ rateBudget: "150", rateBudgetMin: "120" });
    const rows = m.offers.find((o) => o.unit === "rows");
    expect(rows?.text).toContain("AsyncAPI");
    expect(m.differences).toEqual(expect.arrayContaining(["budżet PLN/h", "wymagania"]));
    // Pytania: szablon ma dwa, nowe z maila czekają jako propozycja.
    expect(m.form.questions).toHaveLength(2);
    expect(m.offers.some((o) => o.unit === "questions")).toBe(true);
  });

  it("ten sam mail co szablon = brak różnic", () => {
    const m = mergeRepeat(
      template(),
      mail({
        rate_budget_hourly: 130,
        rate_budget_hourly_min: 100,
        requirements: [{ words: ["Java"], level: "must" }],
        screening_questions: [],
        seniority_min_years: null,
      } as Partial<RequestIntakeResponse>),
      { label: "43260" },
    );
    expect(m.differences).toEqual([]);
  });

  it("hiring manager z szablonu czeka jako „Ta sama osoba co w 43260”, a po „Potwierdź” wchodzi", () => {
    const m = mergeRepeat(template(), mail(), { label: "43260" });
    expect(m.form.hiringManager).toBeNull();
    const hm = m.offers.find((o) => o.unit === "hiringManager");
    expect(hm).toMatchObject({ source: "template", sourceLabel: "43260", text: "Anna Nowak" });
    const confirmed = acceptIntakeOffer(m.form, hm!);
    expect(confirmed.hiringManager).toEqual({ kind: "contact", id: 501, name: "Anna Nowak" });
    expect(liveIntakeOffers(confirmed, m.offers).some((o) => o.unit === "hiringManager")).toBe(false);
    // Propozycja przeżywa autozapis razem z numerem szablonu.
    expect(restoreIntakeOffers(JSON.parse(JSON.stringify(m.offers))).find((o) => o.unit === "hiringManager"))
      .toMatchObject({ sourceLabel: "43260" });
  });

  it("hiring manager z maila wygrywa — bez propozycji z szablonu", () => {
    const m = mergeRepeat(
      template(),
      mail({
        hiring_manager_name: "Jan Kowalski",
        hiring_manager_contact_id: 777,
        hiring_manager_contact_name: "Jan Kowalski",
      } as Partial<RequestIntakeResponse>),
      { label: "43260" },
    );
    expect(m.form.hiringManager?.name).toBe("Jan Kowalski");
    expect(m.offers.some((o) => o.unit === "hiringManager")).toBe(false);
    expect(m.fromMail).toContain("hiring manager");
  });

  it("„Cofnij” wraca do formularza z samego odczytu", () => {
    const readOnly = { ...EMPTY_INTAKE_FORM, ...mail() };
    const m = mergeRepeat(template(), mail(), { label: "43260" });
    const back = undoIntakeFill(m.form, intakeFillUndo(readOnly, m.form));
    expect(back.about).toBe(readOnly.about);
    expect(back.rows.map((r) => r.words[0])).toEqual(readOnly.rows.map((r) => r.words[0]));
    expect(back.rateBudget).toBe(readOnly.rateBudget);
    expect(back.competenceCategoryId).toBe(readOnly.competenceCategoryId);
  });
});
