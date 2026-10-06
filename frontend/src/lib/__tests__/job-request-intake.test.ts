import { describe, expect, it } from "vitest";

import {
  EMPTY_INTAKE_FORM,
  FORM_SECTIONS,
  MISSING_LABEL,
  MISSING_SECTION,
  applyTemplate,
  approveQuestions,
  buildChampionPayload,
  budgetRangeError,
  buildJobPayload,
  clientReferenceFor,
  clientTitleWithReference,
  droppedRequirementsText,
  editQuestion,
  effectiveWorkingTitle,
  formFromIntake,
  highlightSegments,
  hiringManagerFromIntake,
  jobTitleFor,
  joinCities,
  loadTemplateSource,
  markEdited,
  missingBySection,
  missingFor,
  missingHeadline,
  buildCreateJobPayload,
  parseHeadcount,
  restoreIntakeForm,
  serverBlockerSection,
  serverBlockersFromError,
  mustOf,
  newManualQuestion,
  niceOf,
  sectionAnchor,
  splitCities,
  templateLegacyFields,
  unapprovedQuestions,
  type IntakeForm,
  type MissingCode,
  type RequestIntakeResponse,
  type TemplateRows,
} from "@/lib/job-request-intake";
import type { RowCriticalInfo } from "@/lib/requirement-rows";

/** Odczyt v10 (02.10.2026): wymagania jako wiersze słów kluczowych. */
const INTAKE: RequestIntakeResponse = {
  role_name: "Senior Java Developer",
  // Audyt 06.10.2026, P9: `jobs.title` tylko z dosłownej nazwy od klienta —
  // odczyt, który jej nie podaje, zostawia pole puste.
  client_title: "Senior Java Developer",
  // Etykiety dla starszych ekranów — formularz czyta `requirements`.
  must: ["Java 17+", "Spring Boot"],
  nice: ["Kubernetes"],
  seniority_min_years: 5,
  rate_budget_hourly: 170,
  rate_quote: "do 170 zł/h netto",
  rate_note: null,
  remote_policy: "hybrid",
  onsite_days_per_week: 2,
  office_city: "Warszawa",
  start_date: "2026-11-01",
  project_about: "Migracja płatności.",
  responsibilities: null,
  screening_questions: [
    {
      question: "Kafka?",
      ideal_answer: "partycje",
      deal_breaker: "nie zna Kafki",
      from_request: true,
    },
    {
      question: "Biuro 2 dni?",
      ideal_answer: "",
      deal_breaker: "tylko zdalnie",
      from_request: false,
    },
  ],
  requirements: [
    { words: ["Java"], level: "must" },
    { words: ["Spring Boot", "Spring"], level: "must" },
    { words: ["Kubernetes", "k8s"], level: "nice" },
  ],
  descriptive_requirements: ["Min. 5 lat doświadczenia komercyjnego"],
  evidence: ["Java 17+"],
  missing: [],
  // Od 04.10.2026 hiring manager i termin to wymagana decyzja.
  hiring_manager_name: "Anna Nowak",
  hiring_manager_contact_id: 501,
  hiring_manager_contact_name: "Anna Nowak",
  deadline: "2026-10-20",
  deadline_time: "16:00",
  headcount: 2,
};

/** Odczyt sprzed v10: must, nice i osobne wiersze wyszukiwania, bez deal breakerów. */
const LEGACY_INTAKE: RequestIntakeResponse = {
  ...INTAKE,
  requirements: undefined,
  descriptive_requirements: undefined,
  must: ["Java 17+", "Spring Boot", "Kafka"],
  nice: ["Kubernetes"],
  search_requirements: [["Java 17+"], ["Spring Boot", "Spring"]],
  screening_questions: [
    { question: "Kafka?", ideal_answer: "partycje", from_request: true },
    { question: "Biuro 2 dni?", ideal_answer: "", from_request: false },
  ],
};

/** Formularz gotowy do searchu: pytania zatwierdzone, kategoria potwierdzona. */
const complete = (): IntakeForm => ({
  ...approveQuestions(formFromIntake(INTAKE)),
  competenceCategoryId: 2,
  suggestedCategoryId: 2,
  categoryConfirmed: true,
});

const rowShape = (form: IntakeForm) => form.rows.map((r) => [r.words, r.level]);

/** Serwer mówi, że każdy wiersz obowiązkowy to technologia ze słownika. */
const allEligible = (form: IntakeForm): Record<string, RowCriticalInfo> =>
  Object.fromEntries(
    form.rows
      .filter((r) => r.level !== "nice")
      .map((r) => [r.key, { label: r.words[0], eligible: true, suggested: false }]),
  );

describe("formFromIntake — wymagania jako słowa kluczowe", () => {
  it("v10: wiersze z `requirements`, zdania opisowe osobno, krytycznych nie ustawia", () => {
    const form = formFromIntake(INTAKE);
    expect(rowShape(form)).toEqual([
      [["Java"], "must"],
      [["Spring Boot", "Spring"], "must"],
      [["Kubernetes", "k8s"], "nice"],
    ]);
    expect(mustOf(form)).toEqual(["Java", "Spring Boot"]);
    expect(niceOf(form)).toEqual(["Kubernetes"]);
    expect(form.descriptive).toEqual(["Min. 5 lat doświadczenia komercyjnego"]);
    expect(form.noCritical).toBe(false);
    expect(new Set(form.rows.map((r) => r.key)).size).toBe(3);
  });

  it("v10: pytania niosą odpowiedź, która odpada, i startują niezatwierdzone", () => {
    const form = formFromIntake(INTAKE);
    expect(
      form.questions.map((q) => [q.question, q.dealBreaker, q.origin, q.approved]),
    ).toEqual([
      ["Kafka?", "nie zna Kafki", "request", false],
      ["Biuro 2 dni?", "tylko zdalnie", "ai", false],
    ]);
  });

  it("starszy odczyt: wiersze wyszukiwania zostają, must i nice dochodzą jako pojedyncze słowa", () => {
    const form = formFromIntake(LEGACY_INTAKE);
    // „Java 17+” i „Spring Boot” są już wierszami wyszukiwania — nie dublują się.
    expect(rowShape(form)).toEqual([
      [["Java 17+"], "must"],
      [["Spring Boot", "Spring"], "must"],
      [["Kafka"], "must"],
      [["Kubernetes"], "nice"],
    ]);
    expect(form.descriptive).toEqual([]);
    expect(form.questions.map((q) => q.dealBreaker)).toEqual(["", ""]);
    expect(form.questions.every((q) => !q.approved)).toBe(true);
  });

  it("starszy odczyt bez wierszy wyszukiwania: każde must i nice to jeden wiersz", () => {
    const form = formFromIntake({ ...LEGACY_INTAKE, search_requirements: undefined });
    expect(rowShape(form)).toEqual([
      [["Java 17+"], "must"],
      [["Spring Boot"], "must"],
      [["Kafka"], "must"],
      [["Kubernetes"], "nice"],
    ]);
  });

  it("numer z odczytu to podpowiedź, a kategoria czeka na Delivery Leada", () => {
    const form = formFromIntake({
      ...INTAKE,
      client_title: "Programista Java (ZOB 48213)",
      client_reference: "ZOB 48213",
    });
    expect(form.referenceHint).toBe("ZOB 48213");
    expect(form.referenceOverride).toBeNull();
    expect(form.competenceCategoryId).toBeNull();
    expect(form.suggestedCategoryId).toBeNull();
    expect(form.categoryConfirmed).toBe(false);
  });
});

describe("numer zapytania z maila poza nazwą od klienta (audyt 05.10.2026)", () => {
  it("dopisuje numer do nazwy, żeby nie przepadł przy utworzeniu", () => {
    const form = formFromIntake({
      ...INTAKE,
      client_title: "Python Developer",
      client_reference: "ZOB-9905",
    });
    expect(form.clientTitle).toBe("Python Developer (ZOB-9905)");
    expect(clientReferenceFor(form)).toBe("ZOB-9905");
    const opts = { clientId: 7, requestText: "", templateJobId: null };
    expect(buildJobPayload(form, opts).client_reference).toBe("ZOB-9905");
  });

  // Audyt 06.10.2026, P9: nazwa od klienta idzie do klienta (CV, nazwa
  // pliku) — nie może jej złożyć model z własnej nazwy roli. Do tej daty
  // „Python Developer (ZOB-9905)” powstawało z `role_name`.
  it("bez nazwy od klienta zostaje pusto — nazwy nie składa się z roli; numer już w nazwie zostawia bez zmian", () => {
    expect(clientTitleWithReference("", "Tester", "ZOB 1")).toBe("");
    expect(clientTitleWithReference("Tester (zob 1)", "Tester", "ZOB 1")).toBe("Tester (zob 1)");
    expect(clientTitleWithReference("Tester", "Tester", "")).toBe("Tester");
    expect(clientTitleWithReference("", "", "ZOB 1")).toBe("");
  });

  it("odczyt bez nazwy od klienta: pole puste, tytuł rekrutacji pusty, numer z odczytu zostaje", () => {
    const form = formFromIntake({
      ...INTAKE,
      role_name: "Python Developer",
      client_title: null,
      client_reference: "ZOB-9905",
    });
    expect(form.clientTitle).toBe("");
    expect(jobTitleFor(form)).toBe("");
    expect(clientReferenceFor(form)).toBe("ZOB-9905");
    const opts = { clientId: 7, requestText: "", templateJobId: null };
    expect(buildJobPayload(form, opts).client_reference).toBe("ZOB-9905");
  });
});

describe("clientReferenceFor — numer u klienta bez osobnego pola", () => {
  const base = (patch: Partial<IntakeForm>): IntakeForm => ({ ...EMPTY_INTAKE_FORM, ...patch });

  it("numer z odczytu obowiązuje, dopóki stoi w nazwie od klienta", () => {
    expect(
      clientReferenceFor(
        base({ clientTitle: "Programista Java (ZOB 48213)", referenceHint: "ZOB 48213" }),
      ),
    ).toBe("ZOB 48213");
    // Nie tylko ZOB — i bez względu na wielkość liter oraz podwójne spacje.
    expect(
      clientReferenceFor(
        base({ clientTitle: "Tester  sap  4500012345 / Kraków", referenceHint: "SAP 4500012345" }),
      ),
    ).toBe("SAP 4500012345");
  });

  it("numer z odczytu, którego nie ma już w nazwie, ustępuje „ZOB <cyfry>” z nazwy", () => {
    expect(
      clientReferenceFor(
        base({ clientTitle: "Programista Java ZOB-777", referenceHint: "ZOB 48213" }),
      ),
    ).toBe("ZOB 777");
    expect(clientReferenceFor(base({ clientTitle: "Analityk (zob_15)" }))).toBe("ZOB 15");
  });

  it("dwa różne numery ZOB w nazwie to brak numeru; ten sam dwa razy — jeden numer", () => {
    expect(
      clientReferenceFor(base({ clientTitle: "Java ZOB 100 / ZOB 200", referenceHint: "ZOB 300" })),
    ).toBe("");
    expect(clientReferenceFor(base({ clientTitle: "Java ZOB 100 (ZOB-100)" }))).toBe("ZOB 100");
  });

  it("bez numeru w nazwie i bez podpowiedzi — pusto", () => {
    expect(clientReferenceFor(base({ clientTitle: "Programista Java" }))).toBe("");
  });

  // Audyt 06.10.2026, P9: bez nazwy od klienta numer z odczytu nie ma się
  // gdzie „schować” — obowiązuje, dopóki DL nie wpisze nazwy.
  it("pusta nazwa od klienta: numer z odczytu", () => {
    expect(clientReferenceFor(base({ referenceHint: "ZOB 48213" }))).toBe("ZOB 48213");
    expect(clientReferenceFor(base({ referenceHint: "  " }))).toBe("");
  });

  it("„To nie ten numer”: wpis ręczny wygrywa, także pusty", () => {
    const titled = { clientTitle: "Programista Java (ZOB 48213)", referenceHint: "ZOB 48213" };
    expect(clientReferenceFor(base({ ...titled, referenceOverride: "  REQ-9  " }))).toBe("REQ-9");
    expect(clientReferenceFor(base({ ...titled, referenceOverride: "" }))).toBe("");
  });
});

describe("missingFor — lustro bramki „Przekaż do searchu”", () => {
  it("kompletny formularz nie ma braków", () => {
    expect(missingFor(complete())).toEqual([]);
  });

  it("świeży odczyt czeka na zatwierdzenie pytań i potwierdzenie kategorii", () => {
    expect(missingFor(formFromIntake(INTAKE))).toEqual(["questions_review", "category"]);
  });

  it("pusty formularz wymienia wszystko poza biurem (tryb nieznany)", () => {
    expect(missingFor(EMPTY_INTAKE_FORM)).toEqual([
      "role",
      "hiring_manager",
      "must",
      "budget",
      "work_mode",
      "deadline",
      // Audyt 06.10.2026, N6: liczby osób nikt nie podaje za DL-a.
      "headcount",
      "context",
      "questions",
      "category",
    ]);
  });

  it("hiring manager i termin: osoba/data albo „Klient nie podał” — puste to brak", () => {
    const form = complete();
    expect(missingFor({ ...form, hiringManager: null })).toEqual(["hiring_manager"]);
    expect(
      missingFor({ ...form, hiringManager: null, hiringManagerNotProvided: true }),
    ).toEqual([]);
    expect(missingFor({ ...form, deadline: "" })).toEqual(["deadline"]);
    expect(missingFor({ ...form, deadline: "", deadlineNotProvided: true })).toEqual([]);
    expect(MISSING_SECTION.hiring_manager).toBe("name");
    expect(MISSING_SECTION.deadline).toBe("terms");
  });

  it("liczba osób: całkowita od 1 do 99", () => {
    const form = complete();
    expect(missingFor({ ...form, headcount: "0" })).toEqual(["headcount"]);
    expect(missingFor({ ...form, headcount: "1.5" })).toEqual(["headcount"]);
    expect(missingFor({ ...form, headcount: "" })).toEqual(["headcount"]);
    expect(missingFor({ ...form, headcount: "3" })).toEqual([]);
    expect(parseHeadcount("100")).toBeNull();
  });

  it("wymagania: same „mile widziane” i puste wiersze to brak", () => {
    const form = complete();
    expect(
      missingFor({
        ...form,
        rows: [
          { key: "a", words: ["Kubernetes"], level: "nice" },
          { key: "b", words: ["  "], level: "must" },
        ],
      }),
    ).toEqual(["must"]);
  });

  it("praca zdalna nie wymaga dni ani miasta", () => {
    const form = {
      ...complete(),
      remotePolicy: "remote" as const,
      city: "",
      onsiteDays: "",
    };
    expect(missingFor(form)).toEqual([]);
  });

  it("hybryda bez dni i miasta blokuje; zero dni to znana wartość", () => {
    const form = { ...complete(), city: "", onsiteDays: "" };
    expect(missingFor(form)).toEqual(["office_days", "office_city"]);
    expect(missingFor({ ...complete(), onsiteDays: "0" })).toEqual([]);
  });

  it("budżet spoza zakresu API nie liczy się jako podany", () => {
    expect(missingFor({ ...complete(), rateBudget: "0" })).toContain("budget");
    expect(missingFor({ ...complete(), rateBudget: "2500" })).toContain(
      "budget",
    );
    expect(missingFor({ ...complete(), rateBudget: "160,5" })).not.toContain(
      "budget",
    );
  });

  it("„od” jest opcjonalne, ale musi być mniejsze niż budżet (0420)", () => {
    expect(budgetRangeError({ rateBudget: "80", rateBudgetMin: "" })).toBeNull();
    expect(budgetRangeError({ rateBudget: "80", rateBudgetMin: "60" })).toBeNull();
    expect(budgetRangeError({ rateBudget: "80", rateBudgetMin: "80" })).toMatch(/mniejsza/);
    expect(budgetRangeError({ rateBudget: "80", rateBudgetMin: "abc" })).toMatch(/liczbą/);
    expect(missingFor({ ...complete(), rateBudget: "80", rateBudgetMin: "90" })).toContain("budget");
    expect(missingFor({ ...complete(), rateBudget: "80", rateBudgetMin: "60" })).not.toContain(
      "budget",
    );
  });

  it("przedział z odczytu maila trafia do obu pól i do zapisu", () => {
    const form = formFromIntake({ ...INTAKE, rate_budget_hourly: 80, rate_budget_hourly_min: 60 });
    expect(form.rateBudget).toBe("80");
    expect(form.rateBudgetMin).toBe("60");
    const payload = buildJobPayload(approveQuestions(form), {
      clientId: 7,
      requestText: "",
      templateJobId: null,
    });
    expect(payload.rate_budget_hourly).toBe(80);
    expect(payload.rate_budget_hourly_min).toBe(60);
  });

  it("stary zapisany formularz bez „od” doczytuje pole puste", () => {
    const { rateBudgetMin: _drop, ...old } = complete();
    void _drop;
    expect(restoreIntakeForm(old as unknown as IntakeForm).rateBudgetMin).toBe("");
  });

  it("krytyczne: brak decyzji blokuje, gdy serwer zna wiersz jako technologię", () => {
    const form = complete();
    const criticalInfo = allEligible(form);
    expect(missingFor(form, { criticalInfo })).toEqual(["critical"]);
    // „Brak krytycznych” i oznaczony wiersz to dwie decyzje — obie zdejmują brak.
    expect(missingFor({ ...form, noCritical: true }, { criticalInfo })).toEqual([]);
    const marked = form.rows.map((r, i) => (i === 0 ? { ...r, level: "critical" as const } : r));
    expect(missingFor({ ...form, rows: marked }, { criticalInfo })).toEqual([]);
  });

  it("krytyczne: nie zgadujemy, dopóki serwer nie odpowie; bez technologii nic nie trzeba", () => {
    const form = complete();
    expect(missingFor(form)).toEqual([]);
    expect(missingFor(form, { criticalInfo: null })).toEqual([]);
    expect(missingFor(form, { criticalInfo: {} })).toEqual([]);
    const notTech = Object.fromEntries(
      Object.entries(allEligible(form)).map(([key, info]) => [key, { ...info, eligible: false }]),
    );
    expect(missingFor(form, { criticalInfo: notTech })).toEqual([]);
  });

  it("krytyczne: przy pustej liście wymagań brakiem są wymagania, nie decyzja", () => {
    const form = complete();
    expect(missingFor({ ...form, rows: [] }, { criticalInfo: allEligible(form) })).toEqual([
      "must",
    ]);
  });

  it("puste pytanie nie liczy się do dwóch wymaganych", () => {
    const form = complete();
    form.questions[1] = { ...form.questions[1], question: "  " };
    expect(missingFor(form)).toEqual(["questions"]);
  });

  it("pytanie bez odpowiedzi, która odpada, blokuje — także zatwierdzone", () => {
    const form = complete();
    form.questions[1] = { ...form.questions[1], dealBreaker: "  " };
    expect(missingFor(form)).toEqual(["deal_breaker"]);
    // Puste pytanie nie potrzebuje deal breakera.
    const blank = complete();
    blank.questions.push({ ...newManualQuestion(), dealBreaker: "" });
    expect(missingFor(blank)).toEqual([]);
  });

  it("zatwierdzenie pytań wchodzi dopiero, gdy każde ma odpowiedź, która odpada", () => {
    const pending = { ...complete(), questions: formFromIntake(INTAKE).questions };
    expect(missingFor(pending)).toEqual(["questions_review"]);
    const noBreaker = {
      ...pending,
      questions: pending.questions.map((q, i) => (i === 0 ? { ...q, dealBreaker: "" } : q)),
    };
    expect(missingFor(noBreaker)).toEqual(["deal_breaker"]);
  });

  it("kategoria: brak wyboru i wybór bez „Potwierdzam” to ten sam brak", () => {
    expect(missingFor({ ...complete(), competenceCategoryId: null })).toEqual(["category"]);
    expect(missingFor({ ...complete(), categoryConfirmed: false })).toEqual(["category"]);
  });

  it("nagłówek odmienia liczebnik", () => {
    expect(missingHeadline(1)).toBe("Brakuje 1 rzeczy do publikacji");
    expect(missingHeadline(3)).toBe("Brakuje 3 rzeczy do publikacji");
  });
});

describe("braki po sekcjach formularza", () => {
  it("każdy brak ma etykietę i sekcję, w której się go usuwa", () => {
    const codes = Object.keys(MISSING_LABEL) as MissingCode[];
    const sections = FORM_SECTIONS.map((s) => s.id);
    expect(FORM_SECTIONS.map((s) => s.label)).toEqual([
      "Nazwa",
      "Wymagania",
      "Warunki",
      "O projekcie",
      "Pytania",
      "Kategoria i zespół",
    ]);
    for (const code of codes) expect(sections).toContain(MISSING_SECTION[code]);
    expect(codes).not.toContain("search");
  });

  it("missingBySection grupuje braki i zostawia puste sekcje", () => {
    expect(
      missingBySection(["role", "critical", "budget", "office_city", "deal_breaker", "category"]),
    ).toEqual({
      name: ["role"],
      requirements: ["critical"],
      terms: ["budget", "office_city"],
      project: [],
      questions: ["deal_breaker"],
      team: ["category"],
    });
    expect(sectionAnchor("team")).toBe("new-job-section-team");
  });
});

describe("pytania do kandydata — zatwierdzanie", () => {
  it("pytanie dopisane ręcznie jest zatwierdzone od razu", () => {
    expect(newManualQuestion()).toMatchObject({
      question: "",
      idealAnswer: "",
      dealBreaker: "",
      origin: "manual",
      approved: true,
    });
    expect(newManualQuestion().key).not.toBe(newManualQuestion().key);
  });

  it("edycja pola zatwierdza to jedno pytanie", () => {
    const form = formFromIntake(INTAKE);
    const next = editQuestion(form, form.questions[1].key, { dealBreaker: "nie dojedzie" });
    expect(next.questions[1]).toMatchObject({
      question: "Biuro 2 dni?",
      dealBreaker: "nie dojedzie",
      approved: true,
    });
    expect(next.questions[0]).toEqual(form.questions[0]);
    expect(unapprovedQuestions(next).map((q) => q.question)).toEqual(["Kafka?"]);
  });

  it("„Zatwierdź wszystkie” pomija pytania bez odpowiedzi, która odpada", () => {
    const form = formFromIntake(INTAKE);
    form.questions[1] = { ...form.questions[1], dealBreaker: " " };
    const next = approveQuestions(form);
    expect(next.questions.map((q) => q.approved)).toEqual([true, false]);
    expect(unapprovedQuestions(next).map((q) => q.question)).toEqual(["Biuro 2 dni?"]);
  });

  it("„Zatwierdź” przy jednym pytaniu nie rusza pozostałych", () => {
    const form = formFromIntake(INTAKE);
    const next = approveQuestions(form, form.questions[1].key);
    expect(next.questions.map((q) => q.approved)).toEqual([false, true]);
  });

  it("puste pytanie nie jest ani zatwierdzane, ani liczone jako niezatwierdzone", () => {
    const form = formFromIntake(INTAKE);
    form.questions.push({
      key: "pusty",
      question: "  ",
      idealAnswer: "",
      dealBreaker: "cokolwiek",
      origin: "ai",
      approved: false,
    });
    expect(approveQuestions(form).questions.at(-1)?.approved).toBe(false);
    expect(unapprovedQuestions(approveQuestions(form))).toEqual([]);
  });
});

describe("payloady zapisu", () => {
  it("POST /api/jobs niesie pola rekrutacji, kategorię i request jako opis", () => {
    const payload = buildJobPayload(complete(), {
      clientId: 7,
      requestText: "  mail klienta  ",
      templateJobId: null,
    });
    expect(payload).toEqual({
      title: "Senior Java Developer",
      client_id: 7,
      auto_suggest_cc: true,
      remote_policy: "hybrid",
      onsite_days_per_week: 2,
      onsite_days_per_month: null,
      description: "mail klienta",
      competence_category_id: 2,
      // Pierwsze słowa wierszy — warianty („Spring”, „k8s”) nie są osobnymi wymaganiami.
      must_skills: ["Java", "Spring Boot"],
      nice_skills: ["Kubernetes"],
      location: "Warszawa",
      rate_budget_hourly: 170,
      deadline: "2026-10-20",
      deadline_time: "16:00",
      deadline_not_provided: false,
      headcount: 2,
    });
    // Pola wycięte z tworzenia nie wracają tylnymi drzwiami.
    for (const gone of [
      "tac_id",
      "priority",
      "recruitment_type",
      "salary_min",
      "train_name",
    ]) {
      expect(payload).not.toHaveProperty(gone);
    }
  });

  it("bez wybranej kategorii i bez numeru pola nie jadą wcale", () => {
    const payload = buildJobPayload(formFromIntake(INTAKE), {
      clientId: 7,
      requestText: "",
      templateJobId: null,
    });
    expect(payload).not.toHaveProperty("competence_category_id");
    expect(payload).not.toHaveProperty("client_reference");
  });

  it("numer u klienta idzie z `clientReferenceFor` — także wpisany ręcznie albo wyczyszczony", () => {
    const form = formFromIntake({
      ...INTAKE,
      client_title: "Programista Java (ZOB 48213)",
      client_reference: "ZOB 48213",
    });
    const opts = { clientId: 7, requestText: "", templateJobId: null };
    expect(buildJobPayload(form, opts).client_reference).toBe("ZOB 48213");
    expect(
      buildJobPayload({ ...form, referenceOverride: "REQ-9" }, opts).client_reference,
    ).toBe("REQ-9");
    // „To nie ten numer” z pustym polem jedzie jako pusty napis — bez pola
    // w żądaniu serwer wziąłby numer z nazwy.
    expect(buildJobPayload({ ...form, referenceOverride: "" }, opts).client_reference).toBe("");
    // Numer usunięty z nazwy przestaje obowiązywać.
    expect(
      buildJobPayload({ ...form, clientTitle: "Programista Java" }, opts),
    ).not.toHaveProperty("client_reference");
  });

  it("trzy nazwy (0380): nazwa od klienta idzie do rekrutacji, tytuł dla rekrutera tylko po ręcznej zmianie", () => {
    const form = formFromIntake({
      ...INTAKE,
      client_title: "Programista Java (ZOB 48213)",
      client_reference: "ZOB 48213",
      working_title_suggestion: "Senior Java Developer · Java, Spring Boot · 5+ lat",
    });
    const opts = { clientId: 7, requestText: "", templateJobId: null };
    const auto = buildJobPayload(form, opts);
    expect(auto.title).toBe("Programista Java (ZOB 48213)");
    expect(auto).not.toHaveProperty("working_title");
    // Podpowiedź liczy się na żywo z pól formularza, dopóki nikt jej nie zmienił.
    expect(effectiveWorkingTitle({ ...form, seniorityYears: 7 })).toBe(
      "Senior Java Developer · Java, Spring Boot · 7+ lat",
    );
    const manual = buildJobPayload(
      { ...form, workingTitle: "Java do płatności", workingTitleTouched: true },
      opts,
    );
    expect(manual.working_title).toBe("Java do płatności");
  });

  it("praca zdalna czyści biuro, szablon dokleja from_job_id", () => {
    const payload = buildJobPayload(
      { ...complete(), remotePolicy: "remote" },
      { clientId: 7, requestText: "", templateJobId: 99 },
    );
    expect(payload.onsite_days_per_week).toBeNull();
    expect(payload).not.toHaveProperty("location");
    expect(payload).not.toHaveProperty("description");
    expect(payload.from_job_id).toBe(99);
    expect(payload.copy_questions).toBe(true);
  });

  it("dni w miesiącu (0407): odczyt maila → formularz → oba zapisy", () => {
    const form = formFromIntake({
      ...INTAKE,
      onsite_days_per_week: 1,
      onsite_days_per_month: 2,
    });
    expect(form.onsiteDays).toBe("2");
    expect(form.onsiteDaysPeriod).toBe("month");
    expect(missingFor(form)).not.toContain("office_days");
    const payload = buildJobPayload(form, {
      clientId: 7,
      requestText: "",
      templateJobId: null,
    });
    expect(payload.onsite_days_per_month).toBe(2);
    expect(payload.onsite_days_per_week).toBe(1);
    const champion = buildChampionPayload(form) as {
      basics: Record<string, unknown>;
    };
    expect(champion.basics).toMatchObject({
      onsite_days_per_week: 1,
      onsite_days_per_month: 2,
    });
    // Miesięcznie tylko przy hybrydzie — przy stacjonarnej to brak.
    expect(missingFor({ ...form, remotePolicy: "onsite" })).toContain("office_days");
  });

  it("profil Championa ma sekcje sprawdzane przez handoff", () => {
    const champion = buildChampionPayload(complete()) as {
      basics: Record<string, unknown>;
      stack: Record<string, unknown>;
      project: { about: string };
      screening_questions: Record<string, string>[];
    };
    expect(champion.basics).toMatchObject({
      role_name: "Senior Java Developer",
      rate_value: 170,
      work_mode: "hybrydowo",
      onsite_days_per_week: 2,
      candidate_location_pref: "Warszawa",
      seniority_min_years: 5,
      start_date: "2026-11-01",
    });
    // Must-have, mile widziane i wiersze wyszukiwania wyprowadza z wierszy serwer.
    expect(champion.stack).toEqual({
      rows: [
        { words: ["Java"], level: "must" },
        { words: ["Spring Boot", "Spring"], level: "must" },
        { words: ["Kubernetes", "k8s"], level: "nice" },
      ],
      critical: null,
      notes: "Min. 5 lat doświadczenia komercyjnego",
    });
    expect(champion.project.about).toBe("Migracja płatności.");
    expect(champion.screening_questions).toEqual([
      { id: "q1", question: "Kafka?", ideal_answer: "partycje", deal_breaker: "nie zna Kafki" },
      { id: "q2", question: "Biuro 2 dni?", ideal_answer: "", deal_breaker: "tylko zdalnie" },
    ]);
  });
});

describe("buildChampionPayload — wymagania i krytyczne", () => {
  const stackOf = (form: IntakeForm) =>
    buildChampionPayload(form).stack as {
      rows: { words: string[]; level: string }[];
      critical: unknown;
      notes?: string;
    };

  it("null (nie zdecydowano) i [] (Brak krytycznych) jadą jako różne wartości", () => {
    expect(stackOf(complete()).critical).toBeNull();
    expect(stackOf({ ...complete(), noCritical: true }).critical).toEqual([]);
  });

  it("oznaczony wiersz jedzie poziomem „critical”, a `stack.critical` zostaje null", () => {
    const form = complete();
    const rows = form.rows.map((r, i) => (i === 0 ? { ...r, level: "critical" as const } : r));
    // Flaga „Brak krytycznych” przy oznaczonym wierszu nic nie znaczy.
    const stack = stackOf({ ...form, rows, noCritical: true });
    expect(stack.rows[0]).toEqual({ words: ["Java"], level: "critical" });
    expect(stack.critical).toBeNull();
  });

  it("zdania opisowe idą do `stack.notes`, po jednym w linii; bez zdań klucza nie ma", () => {
    expect(
      stackOf({ ...complete(), descriptive: ["Min. 5 lat", "Praca w zespole rozproszonym"] }).notes,
    ).toBe("Min. 5 lat\nPraca w zespole rozproszonym");
    expect(stackOf({ ...complete(), descriptive: [] })).not.toHaveProperty("notes");
  });

  it("puste wiersze i powtórzone wymaganie nie trafiają do zapisu", () => {
    const form = complete();
    const stack = stackOf({
      ...form,
      rows: [
        ...form.rows,
        { key: "pusty", words: [], level: "must" },
        { key: "dubel", words: ["java"], level: "nice" },
      ],
    });
    expect(stack.rows.map((r) => r.words[0])).toEqual(["Java", "Spring Boot", "Kubernetes"]);
  });

  it("stare pola wymagań (must, nice, frazy, wiersze wyszukiwania) nie jadą wcale", () => {
    const champion = buildChampionPayload({
      ...complete(),
      searchExclude: ["junior", "  ", "a|b"],
    }) as { stack: object; search: object };
    expect(Object.keys(champion.stack).sort()).toEqual(["critical", "notes", "rows"]);
    expect(champion.search).toEqual({
      target_companies: "",
      disqualifiers: [],
      exclude: ["junior", "a b"],
    });
  });
});

describe("highlightSegments", () => {
  it("zaznacza fragmenty niezależnie od białych znaków i wielkości liter", () => {
    const text = "Wymagania: Java 17+,\nSpring  Boot. Budżet do 170 zł/h.";
    const marked = highlightSegments(text, ["java 17+", "Spring Boot", "brak"])
      .filter((s) => s.mark)
      .map((s) => s.text);
    expect(marked).toEqual(["Java 17+", "Spring  Boot"]);
  });

  it("scala nachodzące fragmenty i zachowuje cały tekst", () => {
    const text = "Senior Java Developer";
    const segments = highlightSegments(text, ["Senior Java", "Java Developer"]);
    expect(segments).toEqual([{ text: "Senior Java Developer", mark: true }]);
    expect(
      highlightSegments("abc", [])
        .map((s) => s.text)
        .join(""),
    ).toBe("abc");
  });
});

describe("applyTemplate", () => {
  it("wypełnia tylko puste pola i dokłada pytania, gdy jest ich mniej niż dwa", () => {
    const form: IntakeForm = {
      ...EMPTY_INTAKE_FORM,
      title: "Nowa rola",
      rateBudget: "150",
    };
    const next = applyTemplate(form, {
      id: 5,
      title: "Stara rola",
      rate_budget_hourly: 200,
      remote_policy: "remote",
      must_skills: ["Go", { name: "Kafka" }],
      champion_profile: {
        project: { about: "Stary projekt." },
        screening_questions: [
          { question: "Q1?", ideal_answer: "A", deal_breaker: "nie zna Go" },
          { question: "Q2?" },
        ],
      },
    });
    expect(next.title).toBe("Nowa rola");
    expect(next.rateBudget).toBe("150");
    expect(next.remotePolicy).toBe("remote");
    expect(mustOf(next)).toEqual(["Go", "Kafka"]);
    expect(next.about).toBe("Stary projekt.");
    // Pytania z szablonu przychodzą z deal breakerem, ale czekają na zatwierdzenie.
    expect(
      next.questions.map((q) => [q.question, q.idealAnswer, q.dealBreaker, q.origin, q.approved]),
    ).toEqual([
      ["Q1?", "A", "nie zna Go", "template", false],
      ["Q2?", "", "", "template", false],
    ]);
    expect(missingFor(next)).toContain("deal_breaker");
  });

  it("szablon prowadzony wierszami: wiersze 1:1, decyzja o krytycznych nie przechodzi", () => {
    const src = {
      id: 5,
      must_skills: ["stare pole"],
      champion_profile: {
        stack: {
          rows: [
            { words: ["Go", "Golang"], level: "must" },
            { words: ["Kafka"], level: "critical" },
            { words: ["Docker"], level: "nice" },
          ],
          must: [{ name: "Go lub Golang" }, { name: "Kafka" }],
          critical: ["Go lub Golang"],
        },
      },
    };
    expect(templateLegacyFields(src)).toBeNull();
    const next = applyTemplate({ ...EMPTY_INTAKE_FORM }, src);
    expect(rowShape(next)).toEqual([
      [["Go", "Golang"], "must"],
      [["Kafka"], "must"],
      [["Docker"], "nice"],
    ]);
    expect(next.noCritical).toBe(false);
  });

  describe("szablon ze starymi polami wymagań", () => {
    const src = {
      id: 5,
      must_skills: ["z kolumny rekrutacji"],
      nice_skills: ["Docker"],
      champion_profile: {
        stack: { must: [{ name: "Java" }, { name: "Kafka" }, "Oracle"] },
        search: { requirements: [["Java", "JVM"], ["bankow*", "banking"], [], [" "]] },
      },
    };

    it("templateLegacyFields: profil wygrywa z kolumnami, puste wiersze odpadają", () => {
      expect(templateLegacyFields(src)).toEqual({
        must: ["Java", "Kafka", "Oracle"],
        // Profil nie ma „mile widzianych” — zostają te z kolumny rekrutacji.
        nice: ["Docker"],
        requirements: [
          ["Java", "JVM"],
          ["bankow*", "banking"],
        ],
        critical: null,
      });
    });

    it("z zamianą serwera: wiersze i zdania opisowe z `converted`, krytyczne jako „musi mieć”", () => {
      const converted: TemplateRows = {
        rows: [
          { words: ["Java", "JVM"], level: "critical" },
          { words: ["Kafka"], level: "must" },
          { words: ["Docker"], level: "nice" },
        ],
        descriptive: ["Doświadczenie w bankowości"],
      };
      const next = applyTemplate({ ...EMPTY_INTAKE_FORM }, src, converted);
      expect(rowShape(next)).toEqual([
        [["Java", "JVM"], "must"],
        [["Kafka"], "must"],
        [["Docker"], "nice"],
      ]);
      expect(next.descriptive).toEqual(["Doświadczenie w bankowości"]);
    });

    it("bez zamiany (awaria): wiersze wyszukiwania, potem każde must i nice jako jedno słowo", () => {
      const next = applyTemplate({ ...EMPTY_INTAKE_FORM }, src);
      // „Java” z must-have jest już wierszem wyszukiwania — nie dubluje się.
      expect(rowShape(next)).toEqual([
        [["Java", "JVM"], "must"],
        [["bankow*", "banking"], "must"],
        [["Kafka"], "must"],
        [["Oracle"], "must"],
        [["Docker"], "nice"],
      ]);
      expect(next.descriptive).toEqual([]);
    });

    it("formularz z wymaganiami zostaje nietknięty — także jego zdania opisowe", () => {
      const form = formFromIntake(INTAKE);
      const next = applyTemplate(form, src, {
        rows: [{ words: ["Python"], level: "must" }],
        descriptive: ["z szablonu"],
      });
      expect(next.rows).toEqual(form.rows);
      expect(next.descriptive).toEqual(["Min. 5 lat doświadczenia komercyjnego"]);
    });
  });
});

describe("v2 — cały profil Championa z propozycji Luny", () => {
  const V2: RequestIntakeResponse = {
    ...INTAKE,
    language: "PL, EN B2",
    contract_length: "6 mies.",
    experience: {
      domains: [
        { name: "płatności kartowe", level: "must", min_years: 2, quote: "karty" },
      ],
      certifications: [{ name: "ISTQB Foundation", level: "nice", quote: "ISTQB" }],
    },
    target_companies: "Asseco",
    disqualifiers: ["brak polskiego"],
    selling_points: "Greenfield",
    ask_client: ["Ile etapów?", "Kto decyduje?"],
    provenance: {
      role: "request",
      requirements: "request",
      target_companies: "client_history",
      questions: "ai",
      about: "bogus",
    },
  };

  it("formularz przejmuje sekcje propozycji i znane źródła (nieznane odpada)", () => {
    const form = formFromIntake(V2);
    expect(form.experience.domains[0]).toMatchObject({
      name: "płatności kartowe",
      level: "must",
      min_years: 2,
    });
    expect(form.experience.certifications[0].level).toBe("nice");
    expect(form.askClient.map((a) => a.text)).toEqual(["Ile etapów?", "Kto decyduje?"]);
    expect(form.provenance).toEqual({
      role: "request",
      requirements: "request",
      target_companies: "client_history",
      questions: "ai",
    });
  });

  it("starszy odczyt podawał źródło osobno dla must i wierszy wyszukiwania — zostaje pierwsze", () => {
    const form = formFromIntake({
      ...LEGACY_INTAKE,
      provenance: { must: "request", nice: "ai", search_requirements: "ai" },
    });
    expect(form.provenance).toEqual({ requirements: "request" });
  });

  it("odpowiedź starszego backendu (bez pól v2) daje pusty, poprawny formularz", () => {
    const form = formFromIntake(LEGACY_INTAKE);
    expect(form.experience.domains).toEqual([]);
    expect(form.askClient).toEqual([]);
    expect(form.provenance).toEqual({});
  });

  it("edycja pola zmienia źródło na „wpisane”, pole bez źródła zostaje bez chipu", () => {
    const form = formFromIntake(V2);
    expect(markEdited(form, "role").provenance.role).toBe("manual");
    expect(markEdited(form, "requirements").provenance.requirements).toBe("manual");
    expect(markEdited(form, "about").provenance.about).toBeUndefined();
  });

  it("payload profilu niesie doświadczenie, firmy, argumenty i „do dopytania” jako notatki", () => {
    const champion = buildChampionPayload(formFromIntake(V2)) as Record<string, any>;
    expect(champion.experience.domains[0].name).toBe("płatności kartowe");
    expect(champion.search).toEqual({
      target_companies: "Asseco",
      disqualifiers: ["brak polskiego"],
      exclude: [],
    });
    expect(champion.client).toEqual({ selling_points: "Greenfield" });
    expect(champion.basics.language).toBe("PL, EN B2");
    expect(champion.insights).toHaveLength(2);
    expect(champion.insights[0]).toMatchObject({
      source: "client",
      topic: "ask_client",
      audience: "team",
      origin: "ai_intake",
    });
    expect(champion.insights[0].id.startsWith("new-")).toBe(true);
  });

  it("szablon z podobnej rekrutacji kopiuje doświadczenie tylko do pustej sekcji", () => {
    const empty = { ...complete(), experience: { ...complete().experience, domains: [] } };
    const next = applyTemplate(empty, {
      id: 5,
      champion_profile: {
        experience: { domains: [{ name: "ubezpieczenia", level: "nice" }], certifications: [] },
      },
    });
    expect(next.experience.domains).toEqual([
      { name: "ubezpieczenia", level: "nice", min_years: null, note: "" },
    ]);
  });
});

describe("szablon z podobnej rekrutacji — przegląd kodu 23.09", () => {
  it("przenosi wykluczenia, firmy, dyskwalifikatory, argumenty, język i długość — PUT nie może ich skasować", () => {
    const next = applyTemplate(formFromIntake(INTAKE), {
      id: 7,
      champion_profile: {
        search: {
          keywords: "Java, Spring",
          target_companies: "Asseco",
          disqualifiers: ["brak polskiego"],
          requirements: [["Java"], ["Spring", "Spring Boot"], []],
          exclude: ["junior"],
        },
        client: { selling_points: "Greenfield" },
        basics: { language: "PL, EN B2", contract_length: "12 mies." },
      },
    });
    const champion = buildChampionPayload(next) as {
      search: Record<string, unknown>;
      client: Record<string, unknown>;
      basics: Record<string, unknown>;
    };
    // Frazy do LinkedIna i wiersze wyszukiwania szablonu nie mają już swoich pól.
    expect(champion.search).toEqual({
      target_companies: "Asseco",
      disqualifiers: ["brak polskiego"],
      exclude: ["junior"],
    });
    expect(champion.client.selling_points).toBe("Greenfield");
    expect(champion.basics.language).toBe("PL, EN B2");
    expect(champion.basics.contract_length).toBe("12 mies.");
  });

  it("nie nadpisuje tego, co już jest w formularzu", () => {
    const form = { ...formFromIntake(INTAKE), targetCompanies: "z maila" };
    const next = applyTemplate(form, {
      id: 7,
      champion_profile: {
        search: { target_companies: "z szablonu", requirements: [["Python"]] },
      },
    });
    expect(next.targetCompanies).toBe("z maila");
    // Wiersze od Luny z maila zostają — szablon wypełnia tylko puste.
    expect(mustOf(next)).toEqual(["Java", "Spring Boot"]);
  });
});

describe("hiringManagerFromIntake (25.09.2026)", () => {
  it("dopasowany kontakt → kontakt, inaczej nowa osoba, bez nazwiska → nic", () => {
    const base = { hiring_manager_name: "Anna Nowak" } as Parameters<
      typeof hiringManagerFromIntake
    >[0];
    expect(hiringManagerFromIntake({ ...base, hiring_manager_contact_id: 5 })).toEqual({
      kind: "contact",
      id: 5,
      name: "Anna Nowak",
    });
    // Pisownia z bazy wygrywa z pisownią z maila.
    expect(
      hiringManagerFromIntake({
        ...base,
        hiring_manager_contact_id: 5,
        hiring_manager_contact_name: "Anna Nowak-Kowalska",
      }),
    ).toMatchObject({ kind: "contact", id: 5, name: "Anna Nowak-Kowalska" });
    expect(
      hiringManagerFromIntake({ ...base, hiring_manager_position: "Kierownik" }),
    ).toEqual({ kind: "new", name: "Anna Nowak", position: "Kierownik", email: null });
    expect(
      hiringManagerFromIntake({ ...base, hiring_manager_name: "  " }),
    ).toBeNull();
  });
});

describe("„Skopiuj jako szablon” nie kasuje pól spoza formularza (runda 6 audytu)", () => {
  const template = {
    id: 7,
    champion_profile: {
      basics: { seniority_min_years: 6 },
      screening_questions: [
        { question: "Kafka w produkcji?", ideal_answer: "tak", deal_breaker: "brak Kafki" },
        { question: "Umowa B2B?", ideal_answer: "tak", deal_breaker: "tylko UoP" },
      ],
    },
  };

  it("lata z szablonu i dealbreakery pytań wracają w PUT Championa bez zmian", () => {
    const empty = { ...formFromIntake({ ...INTAKE, seniority_min_years: null, screening_questions: [] }) };
    const next = applyTemplate(empty, template);
    const champion = buildChampionPayload(next) as {
      basics: Record<string, unknown>;
      screening_questions: { question: string; deal_breaker: string }[];
    };
    expect(champion.basics.seniority_min_years).toBe(6);
    expect(champion.screening_questions.map((q) => q.deal_breaker)).toEqual([
      "brak Kafki",
      "tylko UoP",
    ]);
    // Kopia pytań czeka na zatwierdzenie — sam deal breaker nie wystarcza.
    expect(missingFor(next)).toContain("questions_review");
  });

  it("brak lat w formularzu nie wysyła `null` (serwer scala `basics` płytko)", () => {
    const form = formFromIntake({ ...INTAKE, seniority_min_years: null });
    const champion = buildChampionPayload(form) as { basics: Record<string, unknown> };
    expect(champion.basics).not.toHaveProperty("seniority_min_years");
  });

  it("lata odczytane z maila wygrywają z szablonem", () => {
    const next = applyTemplate(formFromIntake(INTAKE), template);
    expect(next.seniorityYears).toBe(5);
  });
});


describe("loadTemplateSource (R8-N12-1)", () => {
  const legacyJob = {
    id: 7,
    title: "Stara rola",
    // Surowy JSONB sprzed 09.2026 — `applyTemplate` go nie czyta.
    champion_profile: {
      project_context: { about: "Projekt płatności" },
      sourcing: { keywords: "java kafka" },
    },
  };
  const migrated = {
    project: { about: "Projekt płatności", responsibilities: "" },
    search: { target_companies: "Asseco" },
    client: { selling_points: "Stabilny projekt" },
  };

  it("bierze profil po migracji z GET …/champion-profile", async () => {
    const get = async (url: string) =>
      url === "/api/jobs/7/champion-profile?mark_read=false"
        ? { data: { job_id: 7, champion_profile: migrated } }
        : { data: legacyJob };
    const source = await loadTemplateSource(get, 7);
    const next = applyTemplate({ ...EMPTY_INTAKE_FORM }, source);
    expect(next.about).toBe("Projekt płatności");
    expect(next.targetCompanies).toBe("Asseco");
    expect(next.sellingPoints).toBe("Stabilny projekt");
    // PUT z /jobs/new odsyła teraz skopiowaną treść zamiast pustych napisów.
    const payload = buildChampionPayload(next) as {
      project: { about: string };
      search: { target_companies: string };
    };
    expect(payload.project.about).toBe("Projekt płatności");
    expect(payload.search.target_companies).toBe("Asseco");
  });

  it("bez odczytu profilu zostaje surowa rekrutacja", async () => {
    const get = async (url: string) => {
      if (url.includes("/champion-profile")) throw new Error("403");
      return { data: legacyJob };
    };
    const source = await loadTemplateSource(get, 7);
    expect(source.champion_profile).toEqual(legacyJob.champion_profile);
  });

  it("R9-V2-4: czyta profil bez oznaczania powiadomień jako przeczytanych", async () => {
    const urls: string[] = [];
    const get = async (url: string) => {
      urls.push(url);
      return { data: url.includes("/champion-profile") ? {} : legacyJob };
    };
    await loadTemplateSource(get, 7);
    expect(urls).toContain("/api/jobs/7/champion-profile?mark_read=false");
    expect(urls).not.toContain("/api/jobs/7/champion-profile");
  });

  it("stary kształt bez migracji zostawiał formularz pusty", () => {
    const next = applyTemplate({ ...EMPTY_INTAKE_FORM }, legacyJob);
    expect(next.about).toBe("");
  });
});

describe("v7 (27.09.2026): miasta biura i uwagi z odczytu", () => {
  it("lista miast z odczytu trafia do formularza jako jeden napis", () => {
    const form = formFromIntake({
      ...INTAKE,
      office_city: "Warszawa, Gdańsk",
      office_cities: ["Warszawa", "Gdańsk"],
      advisories: ["„bankowość” przeniesiona do mile widzianych — to nie technologia."],
    });
    expect(form.city).toBe("Warszawa, Gdańsk");
    expect(splitCities(form.city)).toEqual(["Warszawa", "Gdańsk"]);
    expect(form.intakeNotes).toHaveLength(1);
    expect(
      buildJobPayload(form, { clientId: 1, requestText: "", templateJobId: null })
        .location,
    ).toBe("Warszawa, Gdańsk");
  });

  it("stary odczyt bez listy miast czyta office_city", () => {
    const form = formFromIntake(INTAKE);
    expect(form.city).toBe("Warszawa");
    expect(form.intakeNotes).toEqual([]);
  });

  it("chipy miast: bez pustych i bez powtórzeń", () => {
    expect(splitCities(" Warszawa ;  warszawa, Kraków,, ")).toEqual([
      "Warszawa",
      "Kraków",
    ]);
    expect(joinCities(["Gdańsk", "Gdynia", "gdańsk"])).toBe("Gdańsk, Gdynia");
    expect(splitCities("")).toEqual([]);
  });
});

describe("utworzenie jednym żądaniem (04.10.2026)", () => {
  const opts = {
    clientId: 7,
    requestText: "mail",
    templateJobId: null,
    priority: "medium",
    handoff: { recruiter_id: 31, channel: "linkedin" } as const,
    similarJobIds: [4556],
    intakeFormId: 12,
  };

  it("niesie profil, hiring managera, przekazanie, podobne i formularz — bez statusu", () => {
    const payload = buildCreateJobPayload(complete(), opts);
    expect(payload).toMatchObject({
      title: "Senior Java Developer",
      priority: "medium",
      hiring_manager: { contact_id: 501 },
      handoff: { recruiter_id: 31, channel: "linkedin" },
      similar_job_ids: [4556],
      cc_override: null,
      intake_form_id: 12,
    });
    expect(payload).not.toHaveProperty("status");
    expect(payload.champion_profile).toMatchObject({ project: { about: "Migracja płatności." } });
  });

  it("„Klient nie podał” zamiast osoby i terminu", () => {
    const payload = buildCreateJobPayload(
      {
        ...complete(),
        hiringManager: null,
        hiringManagerNotProvided: true,
        deadline: "",
        deadlineTime: "",
        deadlineNotProvided: true,
      },
      opts,
    );
    expect(payload).toMatchObject({
      hiring_manager: { not_provided: true },
      deadline: null,
      deadline_time: null,
      deadline_not_provided: true,
    });
  });

  it("inna kategoria niż podpowiedź jedzie jako cc_override", () => {
    const payload = buildCreateJobPayload({ ...complete(), competenceCategoryId: 4 }, opts);
    expect(payload.cc_override).toEqual({ suggested_cc_id: 2, suggested_score: null });
  });
});

describe("braki z serwera (422 `job_not_ready`)", () => {
  it("czyta kody i zdania; kod formularza prowadzi do sekcji, `champion:` i nieznane nie", () => {
    const blockers = serverBlockersFromError({
      response: {
        status: 422,
        data: {
          detail: {
            code: "job_not_ready",
            message: "x",
            blockers: [
              { code: "budget", message: "Uzupełnij budżet." },
              { code: "champion:rate", message: "Stawka." },
              { code: "x", message: "" },
            ],
          },
        },
      },
    });
    expect(blockers).toEqual([
      { code: "budget", message: "Uzupełnij budżet." },
      { code: "champion:rate", message: "Stawka." },
    ]);
    expect(serverBlockerSection("budget")).toBe("terms");
    expect(serverBlockerSection("hiring_manager")).toBe("name");
    expect(serverBlockerSection("search")).toBe("requirements");
    expect(serverBlockerSection("champion:rate")).toBeNull();
    expect(serverBlockerSection("client")).toBeNull();
  });

  it("inny błąd to nie lista braków", () => {
    expect(serverBlockersFromError({ response: { status: 409, data: { detail: "nie" } } })).toBeNull();
    expect(serverBlockersFromError(new Error("x"))).toBeNull();
  });
});

describe("restoreIntakeForm — formularz z konta", () => {
  it("zapis sprzed nowych pól dostaje wartości domyślne", () => {
    const form = restoreIntakeForm({ title: "Java", rows: [] });
    expect(form.title).toBe("Java");
    // Audyt 06.10.2026, N6: bez domyślnej „1” — liczbę osób wpisuje DL.
    expect(form.headcount).toBe("");
    expect(form.deadlineNotProvided).toBe(false);
    expect(form.experience).toEqual(EMPTY_INTAKE_FORM.experience);
  });

  it("śmieci zamiast formularza dają pusty formularz", () => {
    expect(restoreIntakeForm(null)).toEqual(EMPTY_INTAKE_FORM);
    expect(restoreIntakeForm("x")).toEqual(EMPTY_INTAKE_FORM);
  });
});

// Audyt 06.10.2026, N6: liczba osób bez domyślnej „1”.
describe("liczba osób — wpisuje DL albo podaje mail", () => {
  it("odczyt bez liczby osób zostawia pole puste, a to brak", () => {
    const form = formFromIntake({ ...INTAKE, headcount: null });
    expect(form.headcount).toBe("");
    expect(missingFor({ ...complete(), headcount: form.headcount })).toEqual(["headcount"]);
    expect(EMPTY_INTAKE_FORM.headcount).toBe("");
  });

  it("puste pole jedzie jako `headcount: null` — serwer odmawia zamiast wpisać 1", () => {
    const opts = { clientId: 7, requestText: "", templateJobId: null };
    expect(buildJobPayload({ ...complete(), headcount: "" }, opts).headcount).toBeNull();
    expect(buildJobPayload({ ...complete(), headcount: "abc" }, opts).headcount).toBeNull();
    expect(buildJobPayload({ ...complete(), headcount: "3" }, opts).headcount).toBe(3);
  });

  it("szablon (`?from=`) podstawia liczbę osób rekrutacji źródłowej do pustego pola", () => {
    expect(applyTemplate({ ...EMPTY_INTAKE_FORM }, { id: 5, headcount: 4 }).headcount).toBe("4");
    expect(
      applyTemplate({ ...EMPTY_INTAKE_FORM, headcount: "2" }, { id: 5, headcount: 4 }).headcount,
    ).toBe("2");
    expect(applyTemplate({ ...EMPTY_INTAKE_FORM }, { id: 5 }).headcount).toBe("");
  });
});

// Audyt 06.10.2026, N3: wiersze, które nie zmieściły się nawet w „mile widziane”.
describe("odczyt: wiersze, które się nie zmieściły", () => {
  it("`dropped` z odczytu trafia do formularza i przeżywa zapis na koncie", () => {
    const form = formFromIntake({ ...INTAKE, dropped: ["Ansible", "Terraform"] });
    expect(form.droppedRequirements).toEqual(["Ansible", "Terraform"]);
    expect(formFromIntake(INTAKE).droppedRequirements).toEqual([]);
    expect(restoreIntakeForm({ title: "x" }).droppedRequirements).toEqual([]);
    expect(
      restoreIntakeForm({ title: "x", droppedRequirements: ["Ansible"] }).droppedRequirements,
    ).toEqual(["Ansible"]);
  });

  it("zdanie dla Delivery Leada", () => {
    expect(droppedRequirementsText(["Ansible", "Terraform"])).toBe(
      "Nie zmieściło się w wymaganiach: Ansible, Terraform.",
    );
    expect(droppedRequirementsText([])).toBeNull();
  });
});
