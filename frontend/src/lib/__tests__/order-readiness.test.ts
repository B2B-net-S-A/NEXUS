import { describe, expect, it } from "vitest";

import {
  buildReadinessChecklist,
  parseBudgetInput,
  READINESS_ACTION,
  READINESS_CHAMPION_ANCHOR,
  READINESS_LABEL,
  READINESS_MESSAGES,
  readinessKeyFor,
} from "@/lib/order-readiness";

describe("order-readiness", () => {
  it("rozpoznaje zdania bramki serwera, a obce zostawia bez klucza", () => {
    expect(readinessKeyFor(READINESS_MESSAGES.budget)).toBe("budget");
    expect(readinessKeyFor(` ${READINESS_MESSAGES.work_mode} `)).toBe("work_mode");
    expect(readinessKeyFor("Konflikt pól Championa.")).toBeNull();
  });

  it("dni i miasto biura liczą się tylko przy hybrydzie/biurze", () => {
    // 7 podstawowych + wymagania do wyszukiwania (25.09.2026).
    expect(buildReadinessChecklist([], "remote").total).toBe(8);
    expect(buildReadinessChecklist([], "hybrid").total).toBe(10);
    // Serwer pyta o dni → pozycje biura wchodzą niezależnie od kolumny.
    const withOffice = buildReadinessChecklist([READINESS_MESSAGES.office_days], null);
    expect(withOffice.total).toBe(10);
    expect(withOffice.done).toContain("office_city");
    expect(withOffice.done).not.toContain("office_days");
  });

  it("zdanie spoza lustra jest brakiem i powiększa mianownik", () => {
    const checklist = buildReadinessChecklist(["Coś innego."], "remote");
    expect(checklist.missing).toEqual([{ key: null, label: "Coś innego.", message: "Coś innego." }]);
    expect(checklist.total).toBe(9);
    expect(checklist.doneCount).toBe(8);
  });

  it("budżet: liczba w (0, 2000], przecinek jak kropka", () => {
    expect(parseBudgetInput("150")).toEqual({ value: 150 });
    expect(parseBudgetInput("152,5")).toEqual({ value: 152.5 });
    expect(parseBudgetInput("")).toHaveProperty("error");
    expect(parseBudgetInput("0")).toHaveProperty("error");
    expect(parseBudgetInput("2001")).toHaveProperty("error");
    expect(parseBudgetInput("150 zł")).toHaveProperty("error");
  });

  it("brak decyzji o krytycznych to wiersz z linkiem do sekcji stacku", () => {
    const checklist = buildReadinessChecklist([READINESS_MESSAGES.critical], "remote");
    expect(checklist.missing).toEqual([
      {
        key: "critical",
        label: "Umiejętności krytyczne",
        message: READINESS_MESSAGES.critical,
      },
    ]);
    // Pozycja liczy się tylko wtedy, gdy serwer o nią pyta.
    expect(checklist.total).toBe(9);
    expect(buildReadinessChecklist([], "remote").done).not.toContain("critical");
    expect(READINESS_CHAMPION_ANCHOR.critical).toBe("champion-section-stack");
  });

  it("brak odpowiedzi dyskwalifikującej to wiersz z linkiem do pytań screeningowych", () => {
    expect(READINESS_MESSAGES.deal_breaker).toBe(
      "Przy każdym pytaniu screeningowym wpisz odpowiedź, która dyskwalifikuje kandydata (Profil Championa).",
    );
    expect(readinessKeyFor(READINESS_MESSAGES.deal_breaker)).toBe("deal_breaker");
    const checklist = buildReadinessChecklist([READINESS_MESSAGES.deal_breaker], "remote");
    expect(checklist.missing).toEqual([
      {
        key: "deal_breaker",
        label: "Odpowiedź dyskwalifikująca przy pytaniach",
        message: READINESS_MESSAGES.deal_breaker,
      },
    ]);
    // Pozycja liczy się tylko wtedy, gdy serwer o nią pyta (pierwsze przekazanie).
    expect(checklist.total).toBe(9);
    expect(checklist.doneCount).toBe(8);
    expect(buildReadinessChecklist([], "remote").done).not.toContain("deal_breaker");
    // To samo miejsce i to samo działanie co przy braku pytań.
    expect(READINESS_CHAMPION_ANCHOR.deal_breaker).toBe(READINESS_CHAMPION_ANCHOR.questions);
    expect(READINESS_ACTION.deal_breaker).toBe(READINESS_ACTION.questions);
  });

  it("decyzje (hiring manager, termin, kategoria, liczba osób) mają nazwę i prowadzą do zakładki Zespół", () => {
    // 08.10.2026: bramka pyta o nie od 04.10, a front nie miał dla nich
    // działania — wiersz bez nazwy odsyłał do Profilu Championa, gdzie tych
    // pól nie ma.
    for (const key of ["hiring_manager", "deadline", "category", "headcount"] as const) {
      expect(readinessKeyFor(READINESS_MESSAGES[key])).toBe(key);
      expect(READINESS_LABEL[key]).toBeTruthy();
      expect(READINESS_ACTION[key]).toBe("team");
      expect(READINESS_CHAMPION_ANCHOR[key]).toBeNull();
    }
    const checklist = buildReadinessChecklist(
      [READINESS_MESSAGES.hiring_manager, READINESS_MESSAGES.deadline],
      "remote",
    );
    expect(checklist.missing.map((m) => m.label)).toEqual(["Hiring manager", "Termin"]);
    // Pozycje liczą się tylko wtedy, gdy serwer o nie pyta.
    expect(checklist.total).toBe(10);
    expect(checklist.doneCount).toBe(8);
    expect(buildReadinessChecklist([], "remote").total).toBe(8);
  });

  it("brak wymagań do wyszukiwania prowadzi do ich karty w Championie", () => {
    const checklist = buildReadinessChecklist([READINESS_MESSAGES.search], "remote");
    expect(checklist.missing).toEqual([
      {
        key: "search",
        label: "Wymagania do wyszukiwania",
        message: READINESS_MESSAGES.search,
      },
    ]);
    expect(READINESS_CHAMPION_ANCHOR.search).toBe("champion-search-requirements");
  });
});
