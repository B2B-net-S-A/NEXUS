/**
 * Odczyt maila, pliku albo szablonu na stronie `/jobs/new` wypełnia tylko
 * PUSTE pola (decyzja D3, 10.10.2026). Do tej daty każdy odczyt zakładał
 * formularz od nowa i kasował to, co Delivery Lead zdążył wpisać.
 */

import { describe, expect, it } from "vitest";

import {
  acceptIntakeOffer,
  appendRequestText,
  applyIntakeRead,
  isPristineIntake,
  liveIntakeOffers,
  mergeEvidence,
  mergeIntakeOffers,
  restoreIntakeOffers,
  undoIntakeFill,
  type IntakeOffer,
  type IntakeUnit,
} from "@/lib/job-intake-fill";
import {
  EMPTY_INTAKE_FORM,
  applyTemplate,
  formFromIntake,
  type IntakeForm,
  type RequestIntakeResponse,
} from "@/lib/job-request-intake";
import type { RequirementRowForm } from "@/lib/requirement-rows";

const INTAKE: RequestIntakeResponse = {
  role_name: "Senior Java Developer",
  client_title: "Programista Java (ZOB 48213)",
  client_reference: "ZOB 48213",
  must: ["Java", "Spring Boot"],
  nice: ["Kubernetes"],
  seniority_min_years: 5,
  rate_budget_hourly: 170,
  rate_budget_hourly_min: 150,
  rate_quote: "150–170 zł/h",
  rate_note: "Przedział z maila.",
  remote_policy: "hybrid",
  onsite_days_per_week: 2,
  office_city: "Warszawa",
  office_cities: ["Warszawa", "Gdańsk"],
  start_date: "2026-11-01",
  project_about: "Migracja płatności.",
  responsibilities: null,
  screening_questions: [
    { question: "Kafka?", ideal_answer: "Tak.", deal_breaker: "Nie zna Kafki.", from_request: true },
    { question: "Biuro?", ideal_answer: "", deal_breaker: "Tylko zdalnie.", from_request: false },
  ],
  requirements: [
    { words: ["Java"], level: "must" },
    { words: ["Spring Boot", "Spring"], level: "must" },
    { words: ["Kubernetes"], level: "nice" },
  ],
  descriptive_requirements: ["Doświadczenie w bankowości"],
  evidence: ["Java"],
  missing: [],
  language: "PL, EN B2",
  disqualifiers: ["brak polskiego"],
  ask_client: ["Ile etapów ma rekrutacja?"],
  advisories: ["„Ansible” nie stoi w treści — pominięte."],
  experience: { domains: [{ name: "płatności", level: "must", min_years: 2 }] },
  hiring_manager_name: "Anna Nowak",
  hiring_manager_contact_id: 501,
  hiring_manager_contact_name: "Anna Nowak",
  deadline: "2026-10-20",
  deadline_time: "16:00",
  headcount: 2,
  provenance: { role: "request", rate: "request", questions: "ai" },
};

const read = () => formFromIntake(INTAKE);

const form = (patch: Partial<IntakeForm>): IntakeForm => ({ ...EMPTY_INTAKE_FORM, ...patch });

const row = (key: string, words: string[], level: RequirementRowForm["level"] = "must") => ({
  key,
  words,
  level,
});

const offerOf = (offers: IntakeOffer[], unit: IntakeUnit) => offers.find((o) => o.unit === unit);

describe("isPristineIntake", () => {
  it("pusty formularz jest nietknięty — także z pustym wierszem i pustym pytaniem", () => {
    expect(isPristineIntake(EMPTY_INTAKE_FORM)).toBe(true);
    expect(
      isPristineIntake(
        form({
          rows: [row("r1", [])],
          questions: [
            {
              key: "q1",
              question: " ",
              idealAnswer: "",
              dealBreaker: "",
              origin: "manual",
              approved: true,
            },
          ],
          // Podpowiedź kategorii bez potwierdzenia to nie praca człowieka.
          suggestedCategoryId: 2,
          competenceCategoryId: 2,
        }),
      ),
    ).toBe(true);
  });

  it.each<[string, Partial<IntakeForm>]>([
    ["rola", { title: "Java" }],
    ["wiersz wymagań", { rows: [row("r1", ["Java"])] }],
    ["decyzja „Klient nie podał” (hiring manager)", { hiringManagerNotProvided: true }],
    ["decyzja „Klient nie podał” (termin)", { deadlineNotProvided: true }],
    ["„Brak krytycznych”", { noCritical: true }],
    ["potwierdzona kategoria", { competenceCategoryId: 2, categoryConfirmed: true }],
    ["tryb pracy", { remotePolicy: "remote" }],
    ["numer wpisany ręcznie", { referenceOverride: "" }],
  ])("wpisane: %s → formularz nie jest nietknięty", (_name, patch) => {
    expect(isPristineIntake(form(patch))).toBe(false);
  });
});

describe("applyIntakeRead — nietknięty formularz", () => {
  it("bierze odczyt w całości: wynik jest tym samym, co `formFromIntake`", () => {
    const incoming = read();
    const result = applyIntakeRead(EMPTY_INTAKE_FORM, incoming);
    expect(result.form).toEqual(incoming);
    expect(result.offers).toEqual([]);
    expect(result.filled).toBeGreaterThan(10);
  });

  it("pusty wiersz dodany przyciskiem nie zmienia wyniku", () => {
    const incoming = read();
    const result = applyIntakeRead(form({ rows: [row("blank", [])] }), incoming);
    expect(result.form).toEqual(incoming);
  });

  it("„Cofnij wypełnienie” wraca do pustego formularza", () => {
    const result = applyIntakeRead(EMPTY_INTAKE_FORM, read());
    const undone = undoIntakeFill(result.form, result.undo);
    expect(isPristineIntake(undone)).toBe(true);
    expect(undone.provenance).toEqual({});
  });
});

describe("applyIntakeRead — formularz z wpisanymi polami", () => {
  it("wypełnia tylko puste pola; wpisane zostają, a różnica to propozycja", () => {
    const current = form({ title: "Java Developer", rateBudget: "160", about: "Mój opis." });
    const result = applyIntakeRead(current, read(), { source: "request" });

    // Wpisane przez człowieka — bez zmian.
    expect(result.form.title).toBe("Java Developer");
    expect(result.form.rateBudget).toBe("160");
    expect(result.form.about).toBe("Mój opis.");
    // Puste — wypełnione z odczytu.
    expect(result.form.clientTitle).toBe("Programista Java (ZOB 48213)");
    expect(result.form.referenceHint).toBe("ZOB 48213");
    expect(result.form.language).toBe("PL, EN B2");
    expect(result.form.startDate).toBe("2026-11-01");
    expect(result.form.headcount).toBe("2");
    expect(result.form.seniorityYears).toBe(5);

    expect(offerOf(result.offers, "title")).toMatchObject({
      source: "request",
      label: "Rola",
      text: "Senior Java Developer",
    });
    expect(offerOf(result.offers, "budget")).toMatchObject({ text: "150–170 PLN/h" });
    expect(offerOf(result.offers, "about")).toMatchObject({ text: "Migracja płatności." });
    expect(result.offers.map((o) => o.unit).sort()).toEqual(["about", "budget", "title"]);
    expect(result.filled).toBeGreaterThan(5);
  });

  it("ta sama wartość to ani wypełnienie, ani propozycja (bez wielkości liter i spacji)", () => {
    const current = form({
      title: "senior  java developer",
      rateBudget: "170,0",
      rateBudgetMin: "150",
      city: "gdańsk, Warszawa",
      headcount: "2",
    });
    const result = applyIntakeRead(current, read());
    for (const unit of ["title", "budget", "city", "headcount"] as const) {
      expect(offerOf(result.offers, unit), unit).toBeUndefined();
    }
    expect(result.form.title).toBe("senior  java developer");
    expect(result.form.city).toBe("gdańsk, Warszawa");
  });

  it("wypełnione pole dostaje źródło, wpisane ręcznie go nie traci", () => {
    const current = form({ title: "Java Developer", provenance: { role: "manual" } });
    const result = applyIntakeRead(current, read(), { source: "request" });
    expect(result.form.provenance.role).toBe("manual");
    // Odczyt podał źródło stawki; nazwa od klienta dostaje źródło odczytu.
    expect(result.form.provenance.rate).toBe("request");
    expect(result.form.provenance.client_title).toBe("request");
    // Pytania zaproponowało AI — tak mówi odczyt.
    expect(result.form.provenance.questions).toBe("ai");
  });

  it("nie rusza decyzji człowieka: krytyczne, kategoria, tytuł dla zespołu, numer", () => {
    const current = form({
      title: "Java Developer",
      noCritical: true,
      competenceCategoryId: 4,
      suggestedCategoryId: 2,
      categoryConfirmed: true,
      workingTitle: "Java do płatności",
      workingTitleTouched: true,
      referenceOverride: "REQ-9",
    });
    const result = applyIntakeRead(current, read());
    expect(result.form).toMatchObject({
      noCritical: true,
      competenceCategoryId: 4,
      suggestedCategoryId: 2,
      categoryConfirmed: true,
      workingTitle: "Java do płatności",
      workingTitleTouched: true,
      referenceOverride: "REQ-9",
    });
  });
});

describe("pola, które idą razem", () => {
  it("budżet: „od”, „do” i uwaga wypełniają się razem albo wcale", () => {
    const filled = applyIntakeRead(form({ title: "X" }), read());
    expect(filled.form).toMatchObject({
      rateBudget: "170",
      rateBudgetMin: "150",
      rateNote: "Przedział z maila.",
    });

    // Wpisane samo „do” — odczyt nie dopisuje „od” po cichu.
    const kept = applyIntakeRead(form({ rateBudget: "170" }), read());
    expect(kept.form).toMatchObject({ rateBudget: "170", rateBudgetMin: "", rateNote: null });
    const accepted = acceptIntakeOffer(kept.form, offerOf(kept.offers, "budget")!);
    expect(accepted).toMatchObject({
      rateBudget: "170",
      rateBudgetMin: "150",
      rateNote: "Przedział z maila.",
    });
    expect(accepted.provenance.rate).toBe("request");
  });

  it("tryb pracy: inny tryb to propozycja z dniami; ten sam tryb bez dni — dni się wypełniają", () => {
    const other = applyIntakeRead(form({ remotePolicy: "remote" }), read());
    expect(other.form.remotePolicy).toBe("remote");
    expect(other.form.onsiteDays).toBe("");
    const offer = offerOf(other.offers, "workMode")!;
    expect(offer.text).toBe("Hybrydowo, 2 dni w tygodniu");
    expect(acceptIntakeOffer(other.form, offer)).toMatchObject({
      remotePolicy: "hybrid",
      onsiteDays: "2",
      onsiteDaysPeriod: "week",
    });

    const same = applyIntakeRead(form({ remotePolicy: "hybrid" }), read());
    expect(same.form).toMatchObject({ remotePolicy: "hybrid", onsiteDays: "2" });
    expect(offerOf(same.offers, "workMode")).toBeUndefined();

    const days = applyIntakeRead(form({ remotePolicy: "hybrid", onsiteDays: "3" }), read());
    expect(days.form.onsiteDays).toBe("3");
    expect(offerOf(days.offers, "workMode")?.text).toBe("Hybrydowo, 2 dni w tygodniu");
  });

  it("miasta porównuje jako zbiór", () => {
    const result = applyIntakeRead(form({ city: "Kraków" }), read());
    expect(result.form.city).toBe("Kraków");
    const offer = offerOf(result.offers, "city")!;
    expect(offer.text).toBe("Warszawa, Gdańsk");
    expect(acceptIntakeOffer(result.form, offer).city).toBe("Warszawa, Gdańsk");
  });

  it("termin: przy „Klient nie podał” data z maila jest propozycją, a „Użyj” zdejmuje decyzję", () => {
    const empty = applyIntakeRead(form({ title: "X" }), read());
    expect(empty.form).toMatchObject({
      deadline: "2026-10-20",
      deadlineTime: "16:00",
      deadlineNotProvided: false,
    });

    const decided = applyIntakeRead(form({ deadlineNotProvided: true }), read());
    expect(decided.form).toMatchObject({ deadline: "", deadlineNotProvided: true });
    const offer = offerOf(decided.offers, "deadline")!;
    expect(offer.text).toBe("20.10.2026, 16:00");
    expect(acceptIntakeOffer(decided.form, offer)).toMatchObject({
      deadline: "2026-10-20",
      deadlineTime: "16:00",
      deadlineNotProvided: false,
    });

    // Ta sama data bez godziny: godzina się dopełnia.
    const sameDay = applyIntakeRead(form({ deadline: "2026-10-20" }), read());
    expect(sameDay.form.deadlineTime).toBe("16:00");
    expect(offerOf(sameDay.offers, "deadline")).toBeUndefined();
  });

  it("hiring manager: ta sama osoba to nic, inna — propozycja; „Klient nie podał” zostaje do „Użyj”", () => {
    const same = applyIntakeRead(
      form({ hiringManager: { kind: "new", name: "anna nowak" } }),
      read(),
    );
    expect(offerOf(same.offers, "hiringManager")).toBeUndefined();

    const decided = applyIntakeRead(form({ hiringManagerNotProvided: true }), read());
    expect(decided.form.hiringManager).toBeNull();
    const offer = offerOf(decided.offers, "hiringManager")!;
    expect(offer.text).toBe("Anna Nowak");
    expect(acceptIntakeOffer(decided.form, offer)).toMatchObject({
      hiringManager: { kind: "contact", id: 501, name: "Anna Nowak" },
      hiringManagerNotProvided: false,
    });
  });
});

describe("wymagania i pytania", () => {
  it("bez wpisanych wierszy bierze wiersze z odczytu", () => {
    const result = applyIntakeRead(form({ title: "X" }), read());
    expect(result.form.rows.map((r) => [r.words, r.level])).toEqual([
      [["Java"], "must"],
      [["Spring Boot", "Spring"], "must"],
      [["Kubernetes"], "nice"],
    ]);
    expect(offerOf(result.offers, "rows")).toBeUndefined();
  });

  it("przy wpisanych wierszach daje JEDNĄ propozycję z nowymi wymaganiami; poziomów nie rusza", () => {
    const current = form({ rows: [row("mine", ["java"], "critical")] });
    const result = applyIntakeRead(current, read());
    expect(result.form.rows).toEqual(current.rows);
    const offer = offerOf(result.offers, "rows")!;
    expect(offer.text).toBe("jeszcze 2 wymagania: Spring Boot, Kubernetes");

    const accepted = acceptIntakeOffer(result.form, offer);
    expect(accepted.rows.map((r) => [r.words, r.level])).toEqual([
      [["java"], "critical"],
      [["Spring Boot", "Spring"], "must"],
      [["Kubernetes"], "nice"],
    ]);
    expect(new Set(accepted.rows.map((r) => r.key)).size).toBe(3);
  });

  it("propozycja wymagań trzyma limity: 10 obowiązkowych, reszta jako „mile widziane”", () => {
    const current = form({
      rows: Array.from({ length: 10 }, (_, i) => row(`m${i}`, [`Tech${i}`])),
    });
    const result = applyIntakeRead(current, read());
    const accepted = acceptIntakeOffer(result.form, offerOf(result.offers, "rows")!);
    const added = accepted.rows.slice(10);
    expect(added.map((r) => r.words[0])).toEqual(["Java", "Spring Boot", "Kubernetes"]);
    expect(added.every((r) => r.level === "nice")).toBe(true);
  });

  it("pytania: mniej niż dwa — dopisuje nowe bez zatwierdzenia; dwa i więcej — propozycja", () => {
    const one = form({
      questions: [
        {
          key: "mine",
          question: "kafka?",
          idealAnswer: "",
          dealBreaker: "Brak.",
          origin: "manual",
          approved: true,
        },
      ],
    });
    const appended = applyIntakeRead(one, read());
    expect(appended.form.questions.map((q) => [q.question, q.approved])).toEqual([
      ["kafka?", true],
      ["Biuro?", false],
    ]);
    expect(offerOf(appended.offers, "questions")).toBeUndefined();

    const two = form({
      questions: ["Umowa B2B?", "Angielski?"].map((question, i) => ({
        key: `m${i}`,
        question,
        idealAnswer: "",
        dealBreaker: "Nie.",
        origin: "manual" as const,
        approved: true,
      })),
    });
    const offered = applyIntakeRead(two, read());
    expect(offered.form.questions).toEqual(two.questions);
    const offer = offerOf(offered.offers, "questions")!;
    expect(offer.text).toBe("jeszcze 2 pytania: Kafka?; Biuro?");
    const accepted = acceptIntakeOffer(offered.form, offer);
    expect(accepted.questions.map((q) => q.question)).toEqual([
      "Umowa B2B?",
      "Angielski?",
      "Kafka?",
      "Biuro?",
    ]);
    expect(accepted.questions.slice(2).every((q) => !q.approved && q.dealBreaker)).toBe(true);
  });

  it("listy dopisuje bez duplikatów", () => {
    const current = form({
      descriptive: ["doświadczenie w bankowości"],
      disqualifiers: ["tylko UoP"],
      askClient: [{ key: "a1", text: "Ile etapów ma rekrutacja?" }],
      intakeNotes: ["Stara uwaga."],
      experience: {
        ...EMPTY_INTAKE_FORM.experience,
        domains: [{ name: "Płatności", level: "nice", min_years: null, note: "" }],
        certifications: [{ name: "AWS SA", level: "nice", min_years: null, note: "" }],
      },
    });
    const result = applyIntakeRead(current, read());
    expect(result.form.descriptive).toEqual(["doświadczenie w bankowości"]);
    expect(result.form.disqualifiers).toEqual(["tylko UoP", "brak polskiego"]);
    expect(result.form.askClient).toEqual(current.askClient);
    expect(result.form.intakeNotes).toEqual([
      "Stara uwaga.",
      "„Ansible” nie stoi w treści — pominięte.",
    ]);
    // Ta sama dziedzina zostaje taka, jak ją wpisał człowiek.
    expect(result.form.experience.domains).toEqual(current.experience.domains);
    expect(result.form.experience.certifications).toEqual(current.experience.certifications);
  });
});

describe("szablon z innej rekrutacji", () => {
  const TEMPLATE = {
    id: 55,
    title: "Java Developer (zamknięta)",
    rate_budget_hourly: 160,
    remote_policy: "remote" as const,
    champion_profile: {
      stack: { rows: [{ words: ["Go", "Golang"], level: "must" }] },
      project: { about: "Stary opis." },
    },
  };

  it("propozycja mówi „w szablonie”, a wypełnione pole — „z podobnej rekrutacji”", () => {
    const template = applyTemplate({ ...EMPTY_INTAKE_FORM }, TEMPLATE, null);
    const result = applyIntakeRead(form({ rateBudget: "200" }), template, { source: "template" });
    expect(offerOf(result.offers, "budget")).toMatchObject({
      source: "template",
      text: "160 PLN/h",
    });
    expect(result.form.about).toBe("Stary opis.");
    expect(result.form.provenance.about).toBe("client_history");
    // Rola zostaje pusta: nowa rekrutacja nie udaje starej.
    expect(result.form.title).toBe("");
  });
});

describe("plik Profilu Championa (D4)", () => {
  const extras = {
    search: { keywords: ["java bank"] },
    client: { sectors: ["bankowość"] },
    insights: [{ id: "doc-1", text: "Klient odrzuca osoby bez regulacji.", origin: "document" }],
  };
  const championRead = (): IntakeForm => ({ ...read(), championExtras: extras });

  it("formularz z sekcjami pliku nie jest już nietknięty", () => {
    expect(isPristineIntake(form({ championExtras: extras }))).toBe(false);
  });

  it("nietknięty formularz bierze sekcje pliku razem z polami, a cofnięcie je zdejmuje", () => {
    const result = applyIntakeRead(form({}), championRead(), { source: "file", basis: "document" });
    expect(result.form.championExtras).toEqual(extras);
    expect(undoIntakeFill(result.form, result.undo).championExtras).toBeNull();
  });

  it("w formularzu z wpisanymi polami sekcje pliku dochodzą, a wypełnione pola mówią „z dokumentu”", () => {
    const result = applyIntakeRead(form({ title: "Java Developer" }), championRead(), {
      source: "file",
      basis: "document",
    });
    expect(result.form.championExtras).toEqual(extras);
    // Pole bez źródła w odczycie dostaje podstawę odczytu: dokument, nie mail.
    expect(result.form.provenance.work_mode).toBe("document");
    expect(offerOf(result.offers, "title")?.source).toBe("file");
    expect(undoIntakeFill(result.form, result.undo).championExtras).toBeNull();
  });

  it("drugi plik nie podmienia sekcji pierwszego", () => {
    const first = applyIntakeRead(form({}), championRead(), { source: "file", basis: "document" });
    const other = { ...extras, search: { keywords: ["inne"] } };
    const second = applyIntakeRead(
      first.form,
      { ...read(), championExtras: other },
      { source: "file", basis: "document" },
    );
    expect(second.form.championExtras).toEqual(extras);
  });

  it("zwykły odczyt nie zdejmuje sekcji pliku", () => {
    const first = applyIntakeRead(form({}), championRead(), { source: "file", basis: "document" });
    const second = applyIntakeRead(first.form, read(), { source: "request" });
    expect(second.form.championExtras).toEqual(extras);
  });
});

describe("undoIntakeFill", () => {
  it("cofa wypełnienie, a późniejsze poprawki zostają", () => {
    const current = form({ title: "Java Developer", provenance: { role: "manual" } });
    const result = applyIntakeRead(current, read());

    // Po odczycie Delivery Lead poprawia opis, dopisuje wiersz i zatwierdza pytanie.
    const edited: IntakeForm = {
      ...result.form,
      about: "Poprawiony opis.",
      sellingPoints: "Greenfield.",
      rows: [...result.form.rows, row("later", ["Kafka"])],
      questions: result.form.questions.map((q, i) => (i === 0 ? { ...q, approved: true } : q)),
    };
    const undone = undoIntakeFill(edited, result.undo);

    expect(undone.title).toBe("Java Developer");
    expect(undone.provenance.role).toBe("manual");
    // Wypełnione i nieruszone — puste jak przed odczytem.
    expect(undone).toMatchObject({
      clientTitle: "",
      referenceHint: "",
      rateBudget: "",
      rateBudgetMin: "",
      rateNote: null,
      remotePolicy: "",
      onsiteDays: "",
      city: "",
      deadline: "",
      deadlineTime: "",
      headcount: "",
      hiringManager: null,
      language: "",
      descriptive: [],
      disqualifiers: [],
      askClient: [],
      intakeNotes: [],
    });
    expect(undone.experience.domains).toEqual([]);
    // Poprawione po odczycie — zostają.
    expect(undone.about).toBe("Poprawiony opis.");
    expect(undone.sellingPoints).toBe("Greenfield.");
    expect(undone.rows.map((r) => r.key)).toEqual(["later"]);
    expect(undone.questions.map((q) => q.question)).toEqual(["Kafka?"]);
    expect(undone.provenance.client_title).toBeUndefined();
  });
});

describe("propozycje między odczytami i w zapisie", () => {
  const offers = () => applyIntakeRead(form({ title: "Java Developer", rateBudget: "160" }), read()).offers;

  it("nowy odczyt zastępuje propozycję tego samego pola, inne zostają", () => {
    const first = offers();
    const second: IntakeOffer[] = [{ ...offerOf(first, "title")!, text: "Lead Java Developer" }];
    const merged = mergeIntakeOffers(first, second);
    expect(merged.filter((o) => o.unit === "title")).toHaveLength(1);
    expect(offerOf(merged, "title")?.text).toBe("Lead Java Developer");
    expect(offerOf(merged, "budget")).toBeDefined();
  });

  it("propozycja znika, gdy pole ma już tę wartość", () => {
    const list = offers();
    const typed = form({ title: "Senior Java Developer", rateBudget: "160" });
    expect(liveIntakeOffers(typed, list).map((o) => o.unit)).toEqual(["budget"]);
  });

  it("propozycje przeżywają zapis formularza; śmieci z zapisu są pomijane", () => {
    const list = offers();
    expect(restoreIntakeOffers(JSON.parse(JSON.stringify(list)))).toEqual(list);
    expect(restoreIntakeOffers(undefined)).toEqual([]);
    expect(restoreIntakeOffers([{ unit: "nieznane", text: "x" }, null, "tekst"])).toEqual([]);
  });

  // Przegląd kodu 11.10.2026: zapis z zepsutym wnętrzem propozycji wywracał
  // render strony (`row.words` na `null`) — formularza nie dało się wznowić.
  it("propozycja z zepsutym wnętrzem jest pomijana, a nie wywraca formularza", () => {
    const base = { source: "request", label: "x", text: "x", basis: "request" };
    const broken = [
      { ...base, id: "rows", unit: "rows", rows: [null] },
      { ...base, id: "rows", unit: "rows", rows: [{ words: "java", level: "must" }] },
      { ...base, id: "questions", unit: "questions", questions: [{}] },
      { ...base, id: "title", unit: "title", patch: "Java" },
      { ...base, id: "city", unit: "city", patch: ["Warszawa"] },
    ];
    const restored = restoreIntakeOffers(broken);
    expect(restored).toEqual([]);
    expect(() => liveIntakeOffers(form({ title: "Java" }), restored)).not.toThrow();

    const good = [
      { ...base, id: "rows", unit: "rows", rows: [{ words: ["Java"], level: "must" }, null] },
      {
        ...base,
        id: "questions",
        unit: "questions",
        questions: [{ question: "Kafka?", idealAnswer: "", dealBreaker: "", origin: "request" }, 7],
      },
    ];
    const kept = restoreIntakeOffers(good);
    expect(kept.map((offer) => offer.unit)).toEqual(["rows", "questions"]);
    expect(kept[0].rows).toEqual([{ words: ["Java"], level: "must" }]);
    expect(kept[1].questions).toHaveLength(1);
    expect(() => liveIntakeOffers(form({}), kept)).not.toThrow();
  });
});

describe("treść requestu przy kolejnym odczycie", () => {
  it("drugi odczyt dopisuje treść pod kreską, ten sam tekst się nie dubluje", () => {
    expect(appendRequestText("", "Pierwszy mail.")).toBe("Pierwszy mail.");
    const both = appendRequestText("Pierwszy mail.", "Drugi mail.");
    expect(both.startsWith("Pierwszy mail.")).toBe(true);
    expect(both.endsWith("Drugi mail.")).toBe(true);
    expect(both.split("\n").some((line) => /^[—–-]{3,}/.test(line.trim()))).toBe(true);
    expect(appendRequestText(both, "Drugi mail.")).toBe(both);
  });

  it("podświetlenia to suma z obu odczytów", () => {
    expect(mergeEvidence(["Java", "170 zł/h"], ["java", "Kafka"])).toEqual([
      "Java",
      "170 zł/h",
      "Kafka",
    ]);
  });
});
