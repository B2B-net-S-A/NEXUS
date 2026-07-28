/**
 * Własne etapy terminalne były nierozpoznawalne dla frontendu.
 *
 * Kolumna bez mapowania na legacy enum raportowała `stage: "new"`, a
 * `category` mówiło najwyżej „terminal" — nie KTÓRY. Kanban rozpoznawał
 * hired/rejected/withdrawn po `stage`, więc dla własnego etapu terminalnego:
 *
 * - „odrzucony" nie otwierał modala powodu, a backend wymaga
 *   `rejection_reason_id` przy terminalu → ruch kończył się 422;
 * - „zatrudniony" pomijał potwierdzenie, mimo że backend i tak uruchamiał
 *   skutki uboczne (draft kontraktu + zamówienie klienta) — czyli najbardziej
 *   nieodwracalna operacja szła bez pytania.
 *
 * Reguła odtworzona 1:1 z `terminalOf` w KanbanBoardV2.
 */

import { describe, expect, it } from "vitest";

interface Col {
  stage: string;
  category?: "internal" | "external" | "terminal";
  terminal_type?: "hired" | "rejected" | "withdrawn" | null;
}

function terminalOf(col: Col): "hired" | "rejected" | "withdrawn" | null {
  if (col.terminal_type) return col.terminal_type;
  if (
    col.stage === "hired" ||
    col.stage === "rejected" ||
    col.stage === "withdrawn"
  ) {
    return col.stage;
  }
  return null;
}

describe("terminalOf", () => {
  it("rozpoznaje własny etap odrzucenia mimo stage='new'", () => {
    // To jest dokładnie ten przypadek, który dawał 422.
    const col: Col = {
      stage: "new",
      category: "terminal",
      terminal_type: "rejected",
    };
    expect(terminalOf(col)).toBe("rejected");
  });

  it("rozpoznaje własny etap zatrudnienia mimo stage='new'", () => {
    const col: Col = {
      stage: "new",
      category: "terminal",
      terminal_type: "hired",
    };
    expect(terminalOf(col)).toBe("hired");
  });

  it("działa bez terminal_type (odpowiedzi sprzed dodania pola)", () => {
    expect(terminalOf({ stage: "rejected", category: "terminal" })).toBe("rejected");
    expect(terminalOf({ stage: "hired", category: "terminal" })).toBe("hired");
    expect(terminalOf({ stage: "withdrawn", category: "terminal" })).toBe("withdrawn");
  });

  it("kolumna nieterminalna zwraca null", () => {
    expect(terminalOf({ stage: "new", category: "internal" })).toBeNull();
    expect(terminalOf({ stage: "screening", category: "internal" })).toBeNull();
    expect(terminalOf({ stage: "cv_sent", category: "external" })).toBeNull();
  });

  it("terminal_type wygrywa z legacy stage", () => {
    // Gdyby kiedyś rozjechały się, wiążące jest to, co mówi definicja etapu —
    // bo to ona rządzi zachowaniem backendu.
    const col: Col = {
      stage: "rejected",
      category: "terminal",
      terminal_type: "withdrawn",
    };
    expect(terminalOf(col)).toBe("withdrawn");
  });

  it("category='terminal' samo w sobie nie wystarcza", () => {
    // Właśnie dlatego istnieje `terminal_type`: „terminal" nie mówi, czy
    // pytać o powód, czy o potwierdzenie zatrudnienia.
    expect(terminalOf({ stage: "new", category: "terminal" })).toBeNull();
  });
});
