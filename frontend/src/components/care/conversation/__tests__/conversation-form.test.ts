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
  CASE_TITLE_TOO_SHORT,
  caseAreasFor,
  caseTitleProblem,
  contractDay,
  emptyCase,
  emptyClientState,
  emptyGapAnswer,
  emptyTalk,
  knownRows,
  questionText,
  resolveFollowUp,
  rowModes,
  saveLabel,
  saveSummary,
  splitRoles,
  suggestFollowUp,
  techDiff,
  validateConversation,
  type PayloadInput,
} from "../conversation-form";
import { casesHint } from "../CasesToOpenSection";

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
      hiring_roles: ["dwóch testerów"],
      hiring_source: null,
    });
    expect(off).not.toHaveProperty("hiring_roles");
  });

  it("„klient zatrudnia” wysyła role i źródło na górnym poziomie także bez „Co u klienta”", () => {
    const payload = buildConversationPayload(
      input({
        talk: { ...emptyTalk(TODAY), clientHiring: true, hiringNote: "Java; QA", hiringSource: "slyszal" },
      }),
    );
    expect(payload.client_state).toBeNull();
    expect(payload.hiring_roles).toEqual(["Java", "QA"]);
    expect(payload.hiring_source).toBe("slyszal");
  });
});

describe("buildClientState", () => {
  const noHiring = { clientHiring: false, hiringNote: "", hiringSource: null };

  it("nieruszona sekcja = null (karta technologiczna się nie zapisuje)", () => {
    expect(buildClientState(emptyClientState(), noHiring)).toBeNull();
  });

  it("„bez zmian” potwierdza stan bez zmian", () => {
    const form = { ...emptyClientState(), modes: { area: "same" as const, technologies: "same" as const } };
    expect(buildClientState(form, noHiring, 2)).toEqual({
      confirmed: true,
      changes: {},
      rows: { area: "same", technologies: "same" },
    });
  });

  it("nieruszone wiersze znanego stanu potwierdzają się same; „Nie rozmawialiśmy” — nic", () => {
    const known = ["area", "manager", "technologies"] as const;
    const form = { ...emptyClientState(), modes: { technologies: "change" as const }, skills: [{ id: 1, name: "Java" }] };
    expect(buildClientState(form, noHiring, 2, [...known])).toEqual({
      confirmed: true,
      changes: { skill_ids: [1], new_skill_names: [] },
      rows: { area: "same", manager: "same", technologies: "change" },
    });
    expect(buildClientState(emptyClientState(), noHiring, 2, [...known])?.rows).toEqual({
      area: "same",
      manager: "same",
      technologies: "same",
    });
    expect(buildClientState({ ...form, skipped: true }, noHiring, 2, [...known])).toBeNull();
    expect(rowModes({ ...form, skipped: true }, [...known])).toEqual({});
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
      rows: { area: "change", manager: "same", team: "change", technologies: "change" },
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

  it("bez technologii sama zmiana menedżera idzie bez karty", () => {
    const form = {
      ...emptyClientState(),
      modes: { manager: "change" as const, area: "same" as const },
      managerContactId: 42,
    };
    expect(buildClientState(form, noHiring, 0)).toEqual({
      confirmed: true,
      changes: { manager_contact_id: 42 },
      rows: { area: "same", manager: "change" },
    });
    expect(buildClientState({ ...form, managerContactId: null }, noHiring, 0)).toBeNull();
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
    ).toEqual({
      confirmed: true,
      changes: { hiring_roles: ["Java", "QA"], hiring_source: "slyszal" },
      rows: { area: "same" },
    });
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
    expect(saveSummary(payload)).toBe("Zapisze: rozmowę i stan „co u klienta” (1 zmiana).");
  });

  it("mówi, co się zapisze", () => {
    expect(saveSummary(buildConversationPayload(input()))).toBe("Zapisze: rozmowę.");
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
      "Zapisze: rozmowę, stan „co u klienta” (2 zmiany), 1 odpowiedź do mapy klienta, 2 sprawy, sygnał popytu i wpis „Do przepięcia”.",
    );
    const same = buildConversationPayload(
      input({ clientState: { ...emptyClientState(), modes: { area: "same" } }, knownTechnologies: 1 }),
    );
    expect(saveSummary(same)).toBe("Zapisze: rozmowę i stan „co u klienta” bez zmian.");
    // Makieta P3: zmiana technologii i popyt.
    const p3 = buildConversationPayload(
      input({
        talk: { ...emptyTalk(TODAY), clientHiring: true },
        clientState: { ...emptyClientState(), modes: { technologies: "change" }, skills: [{ id: 9, name: "Azure" }] },
        knownTechnologies: 3,
        knownRows: ["area", "manager", "technologies"],
      }),
    );
    expect(saveSummary(p3)).toBe("Zapisze: rozmowę, stan „co u klienta” (1 zmiana) i sygnał popytu.");
  });
});

describe("splitRoles", () => {
  it("przecinek, średnik, nowa linia", () => {
    expect(splitRoles("Java, QA;\n tester ,")).toEqual(["Java", "QA", "tester"]);
  });
});

describe("questionText", () => {
  it("cztery rodzaje pytań", () => {
    expect(
      [
        ...QUESTIONS,
        { key: "category:0", kind: "category_stale", subject: "CI/CD i chmura", detail: "brak źródła" } as ClientQuestion,
      ].map(questionText),
    ).toEqual([
      "Komu podlega Anna Kierownik?",
      "Na czym pracuje dział Płatności?",
      "Czy Kafka jest naprawdę używany?",
      "CI/CD i chmura",
    ]);
  });
});

describe("sprawy z rozmowy: obszary i tytuł", () => {
  it("„Negocjacje” tylko dla obsługi Spraw", () => {
    expect(caseAreasFor(true)).toContain("negotiation");
    expect(caseAreasFor(false)).not.toContain("negotiation");
    expect(caseAreasFor(false)).toContain("administration");
  });

  it("tytuł krótszy niż 3 znaki blokuje zapis z komunikatem przy polu", () => {
    expect(caseTitleProblem({ ...emptyCase(), title: " ab " })).toBe(CASE_TITLE_TOO_SHORT);
    expect(caseTitleProblem({ ...emptyCase(), title: "abc" })).toBeNull();
    expect(caseTitleProblem(emptyCase())).toBeNull();
    expect(validateConversation(input({ cases: [{ ...emptyCase(), title: "VP" }] }), TODAY)).toBe(
      CASE_TITLE_TOO_SHORT,
    );
  });
});

describe("makiety P3 i S5: następny kontakt, technologie, nagłówek, przycisk zapisu", () => {
  it("następny kontakt z rytmu, dopóki opiekun go nie ruszy", () => {
    const talk = emptyTalk(TODAY);
    expect(resolveFollowUp(talk, "2026-11-05")).toBe("2026-11-05");
    expect(resolveFollowUp(talk, null)).toBe("");
    expect(resolveFollowUp({ ...talk, followUpAuto: false, followUp: "" }, "2026-11-05")).toBe("");
    expect(resolveFollowUp({ ...talk, followUpAuto: false, followUp: "2026-11-10" }, "2026-11-05")).toBe("2026-11-10");
  });

  it("znane wiersze stanu", () => {
    expect(knownRows(null)).toEqual([]);
    expect(
      knownRows({
        area: { id: 1, name: "Płatności" },
        manager: null,
        team_size: "9",
        team_externals: null,
        technologies: [{ skill_id: 1, name: "Java" }],
        vendors: [],
        hiring: null,
        project_end_month: "2027-01",
        quote: null,
      }),
    ).toEqual(["area", "team", "technologies", "project_end"]);
  });

  it("różnica technologii: „+ Azure”, usunięte osobno", () => {
    expect(
      techDiff(
        [
          { skill_id: 1, name: "Java 17" },
          { skill_id: 2, name: "Spring Boot" },
        ],
        [
          { id: 1, name: "Java 17" },
          { id: 3, name: "Azure" },
          { id: null, name: "Tajny framework" },
        ],
      ),
    ).toEqual({ kept: ["Java 17"], added: ["Azure", "Tajny framework"], removed: ["Spring Boot"] });
  });

  it("dzień współpracy i przycisk zapisu z liczbą spraw", () => {
    expect(contractDay("2026-09-08", "2026-10-22")).toBe(45);
    expect(contractDay("2026-10-22", "2026-10-22")).toBe(1);
    expect(contractDay("2026-10-23", "2026-10-22")).toBeNull();
    expect(saveLabel(0)).toBe("Zapisz rozmowę");
    expect(saveLabel(1)).toBe("Zapisz rozmowę i 1 sprawę");
    expect(saveLabel(2)).toBe("Zapisz rozmowę i 2 sprawy");
    expect(saveLabel(5)).toBe("Zapisz rozmowę i 5 spraw");
  });

  it("podpowiedź pod sprawami mówi, kto dostanie dzwonek", () => {
    expect(casesHint(["Zofia Recepcyjna"])).toBe(
      "Sprawa dostanie kontrakt, opis z notatki i link do tej rozmowy. Zofia dostanie dzwonek jak przy każdym przypisaniu.",
    );
    expect(casesHint(["Zofia Recepcyjna", "Kamil T.", "Zofia Recepcyjna"])).toMatch(/Zofia i Kamil dostaną dzwonek/);
    expect(casesHint([])).toMatch(/Bez osoby trafi do „Bez osoby”/);
  });
});
