/**
 * Pole „Rekruter” przy przekazaniu do searchu (`lib/recruiter-assignment.ts`):
 * jedna reguła dla `/jobs/new` i okna „Przekaż do searchu”.
 */

import { describe, expect, it } from "vitest";

import {
  AUTOMATIC_DISABLED_TEXT,
  AUTOMATIC_PASSIVE_NOTE,
  RECRUITER_ASSIGNMENT_LABEL,
  automaticAssignmentAvailable,
  automaticAssignmentHint,
  automaticHandoffOutcome,
  automaticTakenText,
  resolveRecruiterAssignment,
} from "@/lib/recruiter-assignment";

describe("automaticAssignmentAvailable", () => {
  it("automat da się wybrać przy włączonej fladze i trybie innym niż „off”", () => {
    expect(automaticAssignmentAvailable(true, "shadow")).toBe(true);
    expect(automaticAssignmentAvailable(true, "auto")).toBe(true);
    // Starszy serwer oddaje samą flagę, bez trybu.
    expect(automaticAssignmentAvailable(true, undefined)).toBe(true);
  });

  it("tryb „off”, wyłączona flaga i brak odpowiedzi = niedostępny", () => {
    expect(automaticAssignmentAvailable(true, "off")).toBe(false);
    expect(automaticAssignmentAvailable(false, "shadow")).toBe(false);
    expect(automaticAssignmentAvailable(undefined, undefined)).toBe(false);
    expect(automaticAssignmentAvailable(null, "auto")).toBe(false);
  });
});

describe("resolveRecruiterAssignment — wybór trójstanowy", () => {
  it("nikt nie wybrał: automat, o ile jest dostępny", () => {
    expect(resolveRecruiterAssignment(null, true)).toBe("automatic");
    expect(resolveRecruiterAssignment(null, false)).toBe("person");
  });

  it("jawny wybór wygrywa, ale automatu nie da się wymusić, gdy jest niedostępny", () => {
    expect(resolveRecruiterAssignment("person", true)).toBe("person");
    expect(resolveRecruiterAssignment("automatic", true)).toBe("automatic");
    // Automat wyłączono po zaznaczeniu — serwer odmówiłby 409.
    expect(resolveRecruiterAssignment("automatic", false)).toBe("person");
  });
});

describe("zdania pola", () => {
  it("nazwy opcji", () => {
    expect(RECRUITER_ASSIGNMENT_LABEL).toEqual({
      automatic: "Zaproponuje automat",
      person: "Wybieram sam",
    });
  });

  it("w trybie „shadow” automat tylko proponuje — do akceptacji nikt nie jest przypisany", () => {
    const hint = automaticAssignmentHint("shadow");
    expect(hint).toContain("zaproponuje osobę");
    expect(hint).toContain("zatwierdza Head of Recruitment");
    expect(hint).toContain("do tego czasu nikt nie jest przypisany");
    // Brak trybu (starszy serwer) traktujemy ostrożnie, jak propozycję.
    expect(automaticAssignmentHint(undefined)).toBe(hint);
  });

  it("w trybie „auto” automat przydziela sam", () => {
    expect(automaticAssignmentHint("auto")).toBe(
      "Automat przydzieli osobę według kategorii i obłożenia.",
    );
    expect(automaticHandoffOutcome("auto")).toBe("Rekrutera przydzieli automat.");
  });

  it("po przekazaniu: kto przydzieli rekrutera", () => {
    expect(automaticHandoffOutcome("shadow")).toBe(
      "Rekrutera zaproponuje automat, a zatwierdzi Head of Recruitment.",
    );
    expect(automaticHandoffOutcome(undefined)).toBe(automaticHandoffOutcome("shadow"));
  });

  it("priorytet „Przyjmujemy kandydatów” nie obiecuje propozycji — w żadnym trybie", () => {
    for (const mode of ["shadow", "auto", undefined] as const) {
      expect(automaticHandoffOutcome(mode, true)).toBe(
        "Rekrutacja zostaje bez rekrutera — przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje.",
      );
    }
    expect(AUTOMATIC_PASSIVE_NOTE).toContain("automat nikogo nie proponuje");
  });

  it("powody, dla których automatu nie da się wybrać", () => {
    expect(AUTOMATIC_DISABLED_TEXT).toBe(
      "Automatyczny przydział jest wyłączony — włącza go administrator.",
    );
    expect(automaticTakenText("Marta Kowalska")).toBe(
      "Do tej rekrutacji jest już przypisana osoba (Marta Kowalska), więc automat nikogo nie zaproponuje. Wybierz rekrutera z listy.",
    );
    // Bez nazwiska zdanie zostaje pełne, bez pustego nawiasu.
    for (const name of [null, undefined, "", "   "]) {
      expect(automaticTakenText(name)).toBe(
        "Do tej rekrutacji jest już przypisana osoba, więc automat nikogo nie zaproponuje. Wybierz rekrutera z listy.",
      );
    }
  });
});
