import { describe, expect, it } from "vitest";

import {
  EMPTY_INTAKE_FORM,
  applyTemplate,
  buildChampionPayload,
  buildJobPayload,
  formFromIntake,
  highlightSegments,
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
    ]);
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
