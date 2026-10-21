/**
 * Okno „Rozmowa” (22.10.2026): ciało zapisu — „Co u klienta” tylko po
 * dotknięciu sekcji, odpowiedzi i sprawy bez treści pomijane, limit 5 spraw,
 * podpowiedź następnego kontaktu z rytmu i zdanie w stopce.
 */
import { describe, expect, it } from "vitest";

import type { ClientQuestion } from "@/lib/api/care";

import {
  buildCases,
  buildClientState,
  buildConversationPayload,
  buildGapAnswers,
  emptyCase,
  emptyClientState,
  emptyGapAnswer,
  emptyTalk,
  questionText,
  saveSummary,
  splitRoles,
  suggestFollowUp,
  validateConversation,
  type PayloadInput,
} from "../conversation-form";

const TODAY = "2026-10-22";

function input(overrides: Partial<PayloadInput> = {}): PayloadInput {
  return {
    talk: emptyTalk(TODAY),
    clientState: emptyClientState(),
    questions: [],
    answers: {},
    cases: [],
    planItemId: null,
    ...overrides,
  };
}

const QUESTIONS: ClientQuestion[] = [
  { key: "reports_to:12", kind: "reports_to", subject: "Anna Kierownik", detail: "QA", contact_id: 12 },
  { key: "area:5", kind: "area_without_source", subject: "Płatności", detail: null, area_id: 5 },
  { key: "single:7", kind: "single_source", subject: "Kafka", detail: "tylko rekrutacje" },
];

describe("buildConversationPayload", () => {
  it("stare ciało bez sekcji klienta: client_state null, puste odpowiedzi i sprawy", () => {
    const payload = buildConversationPayload(input());
    expect(payload).toMatchObject({
      occurred_on: TODAY,
      channel: "phone",
      satisfaction: null,
      note: null,
      attrition_risk: false,
      wants_change: false,
      project_end_on: null,
      client_hiring: false,
      client_hiring_note: null,
      follow_up_on: null,
      plan_item_id: null,
      client_state: null,
      gap_answers: [],
      cases: [],
    });
  });

  it("koniec projektu idzie tylko przy włączonym sygnale; notatka popytu tylko przy „klient zatrudnia”", () => {
    const off = buildConversationPayload(
      input({ talk: { ...emptyTalk(TODAY), projectEndOn: "2026-12-31", hiringNote: "QA" } }),
    );
    expect(off.project_end_on).toBeNull();
    expect(off.client_hiring_note).toBeNull();
    const on = buildConversationPayload(
      input({
        talk: {
          ...emptyTalk(TODAY),
          projectEnd: true,
          projectEndOn: "2026-12-31",
          clientHiring: true,
          hiringNote: "  dwóch testerów ",
          satisfaction: 4,
          note: "  Dobrze. ",
        },
        planItemId: 33,
      }),
    );
    expect(on).toMatchObject({
      project_end_on: "2026-12-31",
      client_hiring: true,
      client_hiring_note: "dwóch testerów",
      satisfaction: 4,
      note: "Dobrze.",
      plan_item_id: 33,
    });
  });
});

describe("buildClientState", () => {
  const noHiring = { clientHiring: false, hiringNote: "", hiringSource: null };

  it("nieruszona sekcja = null (karta technologiczna się nie zapisuje)", () => {
    expect(buildClientState(emptyClientState(), noHiring)).toBeNull();
  });

  it("„bez zmian” potwierdza stan bez zmian", () => {
    const form = { ...emptyClientState(), modes: { area: "same" as const, technologies: "same" as const } };
    expect(buildClientState(form, noHiring, 2)).toEqual({ confirmed: true, changes: {} });
  });

  it("„zmień” wnosi tylko pola tego wiersza; nowy dział z nazwą, technologie słownik + tekst", () => {
    const form = {
      ...emptyClientState(),
      modes: { area: "change" as const, technologies: "change" as const, team: "change" as const, manager: "same" as const },
      areaId: "new" as const,
      newAreaName: "  Karty ",
      managerContactId: 99,
      skills: [
        { id: 1, name: "Java" },
        { id: null, name: "Tajny framework" },
      ],
      teamSize: "8",
      teamExternals: "abc",
    };
    expect(buildClientState(form, noHiring, 2)).toEqual({
      confirmed: true,
      changes: {
        new_area_name: "Karty",
        skill_ids: [1],
        new_skill_names: ["Tajny framework"],
        team_size: "8",
      },
    });
  });

  it("bez żadnej technologii w stanie karta się nie zapisuje (serwer odpowiada 422)", () => {
    const same = { ...emptyClientState(), modes: { area: "same" as const } };
    expect(buildClientState(same, noHiring, 0)).toBeNull();
    const cleared = { ...emptyClientState(), modes: { technologies: "change" as const }, skills: [] };
    expect(buildClientState(cleared, noHiring, 5)).toBeNull();
    const added = { ...cleared, skills: [{ id: null, name: "Nowy framework" }] };
    expect(buildClientState(added, noHiring, 0)?.changes).toEqual({ skill_ids: [], new_skill_names: ["Nowy framework"] });
  });

  it("pusty miesiąc końca projektu przy „zmień” czyści koniec (null)", () => {
    const form = { ...emptyClientState(), modes: { project_end: "change" as const }, projectEndMonth: "" };
    expect(buildClientState(form, noHiring, 2)?.changes).toEqual({ project_end_month: null });
    const set = { ...form, projectEndMonth: "2027-03" };
    expect(buildClientState(set, noHiring, 2)?.changes).toEqual({ project_end_month: "2027-03" });
  });

  it("„klient zatrudnia” dopisuje role i źródło do karty, gdy karta się zapisuje", () => {
    const form = { ...emptyClientState(), modes: { area: "same" as const } };
    expect(
      buildClientState(form, { clientHiring: true, hiringNote: "Java; QA", hiringSource: "slyszal" }, 1),
    ).toEqual({ confirmed: true, changes: { hiring_roles: ["Java", "QA"], hiring_source: "slyszal" } });
  });
});

describe("buildGapAnswers", () => {
  it("pomija pytania bez odpowiedzi; reports_to bierze osobę, reszta technologie i notatkę", () => {
    const answers = {
      "reports_to:12": { ...emptyGapAnswer(), reportsToContactId: 40 },
      "area:5": { ...emptyGapAnswer(), skills: [{ id: 3, name: "Kotlin" }], note: " stack z 2026 " },
      "single:7": emptyGapAnswer(),
    };
    expect(buildGapAnswers(QUESTIONS, answers)).toEqual([
      { key: "reports_to:12", reports_to_contact_id: 40 },
      { key: "area:5", skill_ids: [3], new_skill_names: [], note: "stack z 2026" },
    ]);
  });
});

describe("buildCases", () => {
  it("bez tytułu nie ma sprawy; najwyżej 5; puste pola opcjonalne nie idą", () => {
    const drafts = Array.from({ length: 7 }, (_, index) => ({
      ...emptyCase(),
      title: index === 1 ? "   " : `Sprawa ${index}`,
    }));
    drafts[0] = { ...drafts[0], assigneeUserId: 5, dueOn: "2026-10-30", area: "onboarding" };
    const cases = buildCases(drafts);
    expect(cases).toHaveLength(5);
    expect(cases[0]).toEqual({ title: "Sprawa 0", area: "onboarding", assignee_user_id: 5, due_on: "2026-10-30" });
    expect(cases[1]).toEqual({ title: "Sprawa 2", area: "administration" });
  });
});

describe("validateConversation", () => {
  it("data z przyszłości, następny kontakt przed rozmową, koniec projektu bez daty, sprawa bez tytułu", () => {
    expect(validateConversation(input({ talk: { ...emptyTalk(TODAY), occurredOn: "2026-10-23" } }), TODAY)).toMatch(
      /najpóźniej dzisiejszą/,
    );
    expect(validateConversation(input({ talk: { ...emptyTalk(TODAY), followUp: "2026-10-01" } }), TODAY)).toMatch(
      /po dacie rozmowy/,
    );
    expect(validateConversation(input({ talk: { ...emptyTalk(TODAY), projectEnd: true } }), TODAY)).toMatch(
      /końca projektu/,
    );
    expect(
      validateConversation(input({ cases: [{ ...emptyCase(), dueOn: "2026-10-30" }] }), TODAY),
    ).toMatch(/tytułu/);
    expect(validateConversation(input({ cases: [emptyCase()] }), TODAY)).toBeNull();
    const six = Array.from({ length: 6 }, (_, i) => ({ ...emptyCase(), title: `S${i}` }));
    expect(validateConversation(input({ cases: six }), TODAY)).toMatch(/najwyżej 5/);
  });
});

describe("suggestFollowUp", () => {
  it("data rozmowy + odstęp rytmu; kamienie i wstrzymany bez podpowiedzi", () => {
    expect(suggestFollowUp("biweekly", "2026-10-22")).toBe("2026-11-05");
    expect(suggestFollowUp("monthly", "2026-10-22")).toBe("2026-11-21");
    expect(suggestFollowUp("quarterly", "2026-12-31")).toBe("2027-04-01");
    expect(suggestFollowUp("milestones", "2026-10-22")).toBeNull();
    expect(suggestFollowUp("paused", "2026-10-22")).toBeNull();
    expect(suggestFollowUp(null, "2026-10-22")).toBeNull();
    expect(suggestFollowUp("monthly", "")).toBeNull();
  });
});

describe("saveSummary", () => {
  it("zmiana technologii to jedna zmiana, choć niesie dwa pola", () => {
    const payload = buildConversationPayload(
      input({
        clientState: {
          ...emptyClientState(),
          modes: { technologies: "change" },
          skills: [
            { id: 1, name: "Java" },
            { id: null, name: "Nowe" },
          ],
        },
      }),
    );
    expect(saveSummary(payload)).toBe("Zapiszemy: rozmowę · stan u klienta (1 zmiana).");
  });

  it("mówi, co się zapisze", () => {
    expect(saveSummary(buildConversationPayload(input()))).toBe("Zapiszemy: rozmowę.");
    const payload = buildConversationPayload(
      input({
        talk: { ...emptyTalk(TODAY), clientHiring: true, wantsChange: true },
        clientState: {
          ...emptyClientState(),
          modes: { manager: "change", project_end: "change", area: "same" },
          managerContactId: 4,
          projectEndMonth: "2027-01",
        },
        questions: QUESTIONS,
        answers: { "single:7": { ...emptyGapAnswer(), note: "potwierdzone" } },
        cases: [
          { ...emptyCase(), title: "Laptop" },
          { ...emptyCase(), title: "Aneks" },
        ],
        knownTechnologies: 3,
      }),
    );
    expect(saveSummary(payload)).toBe(
      "Zapiszemy: rozmowę · stan u klienta (2 zmiany) · 1 odpowiedź do mapy klienta · 2 sprawy · sygnał popytu do Delivery Leada · wpis „Do przepięcia”.",
    );
    const same = buildConversationPayload(
      input({ clientState: { ...emptyClientState(), modes: { area: "same" } }, knownTechnologies: 1 }),
    );
    expect(saveSummary(same)).toBe("Zapiszemy: rozmowę · stan u klienta bez zmian.");
  });
});

describe("splitRoles", () => {
  it("przecinek, średnik, nowa linia", () => {
    expect(splitRoles("Java, QA;\n tester ,")).toEqual(["Java", "QA", "tester"]);
  });
});

describe("questionText", () => {
  it("trzy rodzaje pytań", () => {
    expect(QUESTIONS.map(questionText)).toEqual([
      "Komu podlega Anna Kierownik?",
      "Na czym pracuje dział Płatności?",
      "Czy Kafka jest naprawdę używany?",
    ]);
  });
});
