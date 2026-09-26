import { describe, expect, it } from "vitest";

import {
  EMPTY_INTAKE_FORM,
  applyTemplate,
  buildChampionPayload,
  markEdited,
  buildJobPayload,
  effectiveWorkingTitle,
  formFromIntake,
  highlightSegments,
  loadTemplateSource,
  missingFor,
  missingHeadline,
  type IntakeForm,
  type RequestIntakeResponse,
} from "@/lib/job-request-intake";

const INTAKE: RequestIntakeResponse = {
  role_name: "Senior Java Developer",
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
    { question: "Kafka?", ideal_answer: "partycje", from_request: true },
    { question: "Biuro 2 dni?", ideal_answer: "", from_request: false },
  ],
  evidence: ["Java 17+"],
  missing: [],
  // v5 (25.09.2026): wymagania do wyszukiwania w bazie — bez nich handoff ma brak.
  search_requirements: [["Java 17+"], ["Spring Boot"]],
};

const complete = (): IntakeForm => formFromIntake(INTAKE);

describe("missingFor — lustro bramki „Przekaż do searchu”", () => {
  it("kompletny odczyt nie ma braków", () => {
    expect(missingFor(complete())).toEqual([]);
  });

  it("pusty formularz wymienia wszystko poza biurem (tryb nieznany)", () => {
    expect(missingFor(EMPTY_INTAKE_FORM)).toEqual([
      "role",
      "must",
      "budget",
      "work_mode",
      "context",
      "questions",
      "search",
    ]);
  });

  it("wymagania do wyszukiwania: pusty wiersz albo same wykluczenia to brak", () => {
    expect(missingFor({ ...complete(), searchRequirements: [[], ["  "]] })).toEqual(["search"]);
    expect(
      missingFor({ ...complete(), searchRequirements: [], searchExclude: ["junior"] }),
    ).toEqual(["search"]);
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

  it("puste pytanie nie liczy się do dwóch wymaganych", () => {
    const form = complete();
    form.questions[1] = { ...form.questions[1], question: "  " };
    expect(missingFor(form)).toEqual(["questions"]);
  });

  it("nagłówek odmienia liczebnik", () => {
    expect(missingHeadline(1)).toBe("Brakuje 1 rzeczy do searchu");
    expect(missingHeadline(3)).toBe("Brakuje 3 rzeczy do searchu");
  });
});

describe("payloady zapisu", () => {
  it("POST /api/jobs niesie pola rekrutacji i request jako opis", () => {
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
      description: "mail klienta",
      must_skills: ["Java 17+", "Spring Boot"],
      nice_skills: ["Kubernetes"],
      location: "Warszawa",
      rate_budget_hourly: 170,
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

  it("trzy nazwy (0380): nazwa i numer od klienta idą do rekrutacji, tytuł dla rekrutera tylko po ręcznej zmianie", () => {
    const form = formFromIntake({
      ...INTAKE,
      client_title: "Programista Java (ZOB 48213)",
      client_reference: "ZOB 48213",
      working_title_suggestion: "Senior Java Developer · Java 17+, Spring Boot · 5+ lat",
    });
    const opts = { clientId: 7, requestText: "", templateJobId: null };
    const auto = buildJobPayload(form, opts);
    expect(auto.title).toBe("Programista Java (ZOB 48213)");
    expect(auto.client_reference).toBe("ZOB 48213");
    expect(auto).not.toHaveProperty("working_title");
    // Podpowiedź liczy się na żywo z pól formularza, dopóki nikt jej nie zmienił.
    expect(effectiveWorkingTitle({ ...form, seniorityYears: 7 })).toBe(
      "Senior Java Developer · Java 17+, Spring Boot · 7+ lat",
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

  it("profil Championa ma sekcje sprawdzane przez handoff", () => {
    const champion = buildChampionPayload(complete()) as {
      basics: Record<string, unknown>;
      stack: { must: { name: string }[] };
      project: { about: string };
      screening_questions: { id: string; question: string }[];
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
    expect(champion.stack.must).toEqual([
      { name: "Java 17+" },
      { name: "Spring Boot" },
    ]);
    expect(champion.project.about).toBe("Migracja płatności.");
    expect(champion.screening_questions.map((q) => q.id)).toEqual(["q1", "q2"]);
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
          { question: "Q1?", ideal_answer: "A" },
          { question: "Q2?" },
        ],
      },
    });
    expect(next.title).toBe("Nowa rola");
    expect(next.rateBudget).toBe("150");
    expect(next.remotePolicy).toBe("remote");
    expect(next.must).toEqual(["Go", "Kafka"]);
    expect(next.about).toBe("Stary projekt.");
    expect(next.questions.map((q) => [q.question, q.origin])).toEqual([
      ["Q1?", "template"],
      ["Q2?", "template"],
    ]);
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
    search_keywords: "tester, karty",
    target_companies: "Asseco",
    disqualifiers: ["brak polskiego"],
    selling_points: "Greenfield",
    ask_client: ["Ile etapów?", "Kto decyduje?"],
    provenance: { role: "request", search_keywords: "client_history", bogus: "x" },
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
    expect(form.provenance).toEqual({ role: "request", search_keywords: "client_history" });
  });

  it("odpowiedź starszego backendu (bez pól v2) daje pusty, poprawny formularz", () => {
    const form = formFromIntake(INTAKE);
    expect(form.experience.domains).toEqual([]);
    expect(form.askClient).toEqual([]);
    expect(form.provenance).toEqual({});
  });

  it("edycja pola zmienia źródło na „wpisane”, pole bez źródła zostaje bez chipu", () => {
    const form = formFromIntake(V2);
    expect(markEdited(form, "role").provenance.role).toBe("manual");
    expect(markEdited(form, "about").provenance.about).toBeUndefined();
  });

  it("payload profilu niesie doświadczenie, frazy, argumenty i „do dopytania” jako notatki", () => {
    const champion = buildChampionPayload(formFromIntake(V2)) as Record<string, any>;
    expect(champion.experience.domains[0].name).toBe("płatności kartowe");
    expect(champion.search).toEqual({
      keywords: "tester, karty",
      target_companies: "Asseco",
      disqualifiers: ["brak polskiego"],
      requirements: [["Java 17+"], ["Spring Boot"]],
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
  it("przenosi frazy, firmy, dyskwalifikatory, argumenty, język i długość — PUT nie może ich skasować", () => {
    const next = applyTemplate(formFromIntake({ ...INTAKE, search_requirements: [] }), {
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
    expect(champion.search).toEqual({
      keywords: "Java, Spring",
      target_companies: "Asseco",
      disqualifiers: ["brak polskiego"],
      requirements: [["Java"], ["Spring", "Spring Boot"]],
      exclude: ["junior"],
    });
    expect(champion.client.selling_points).toBe("Greenfield");
    expect(champion.basics.language).toBe("PL, EN B2");
    expect(champion.basics.contract_length).toBe("12 mies.");
  });

  it("nie nadpisuje tego, co już jest w formularzu", () => {
    const form = { ...formFromIntake(INTAKE), searchKeywords: "z maila" };
    const next = applyTemplate(form, {
      id: 7,
      champion_profile: {
        search: { keywords: "z szablonu", requirements: [["Python"]] },
      },
    });
    expect(next.searchKeywords).toBe("z maila");
    // Wiersze od Luny z maila zostają — szablon wypełnia tylko puste.
    expect(next.searchRequirements).toEqual([["Java 17+"], ["Spring Boot"]]);
  });
});

describe("hiringManagerFromIntake (25.09.2026)", () => {
  it("dopasowany kontakt → kontakt, inaczej nowa osoba, bez nazwiska → nic", async () => {
    const { hiringManagerFromIntake } = await import("@/lib/job-request-intake");
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
    search: { keywords: "java kafka" },
    client: { selling_points: "Stabilny projekt" },
  };

  it("bierze profil po migracji z GET …/champion-profile", async () => {
    const get = async (url: string) =>
      url === "/api/jobs/7/champion-profile"
        ? { data: { job_id: 7, champion_profile: migrated } }
        : { data: legacyJob };
    const source = await loadTemplateSource(get, 7);
    const next = applyTemplate({ ...EMPTY_INTAKE_FORM }, source);
    expect(next.about).toBe("Projekt płatności");
    expect(next.searchKeywords).toBe("java kafka");
    expect(next.sellingPoints).toBe("Stabilny projekt");
    // PUT z /jobs/new odsyła teraz skopiowaną treść zamiast pustych napisów.
    const payload = buildChampionPayload(next) as {
      project: { about: string };
      search: { keywords: string };
    };
    expect(payload.project.about).toBe("Projekt płatności");
    expect(payload.search.keywords).toBe("java kafka");
  });

  it("bez odczytu profilu zostaje surowa rekrutacja", async () => {
    const get = async (url: string) => {
      if (url.endsWith("/champion-profile")) throw new Error("403");
      return { data: legacyJob };
    };
    const source = await loadTemplateSource(get, 7);
    expect(source.champion_profile).toEqual(legacyJob.champion_profile);
  });

  it("stary kształt bez migracji zostawiał formularz pusty", () => {
    const next = applyTemplate({ ...EMPTY_INTAKE_FORM }, legacyJob);
    expect(next.about).toBe("");
  });
});
