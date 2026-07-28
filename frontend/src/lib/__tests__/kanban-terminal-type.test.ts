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
 *   skutki uboczne (draft kontraktu + zamówienie klienta) — najbardziej
 *   nieodwracalna operacja w module szła bez pytania.
 *
 * Test importuje PRAWDZIWĄ `terminalOf`; wcześniejsza wersja odtwarzała ją
 * inline i przez to sprawdzała własną kopię.
 */

import { describe, expect, it } from "vitest";

import { terminalOf } from "@/lib/kanban-terminal";

describe("terminalOf", () => {
  it("rozpoznaje własny etap odrzucenia mimo stage='new'", () => {
    // To jest dokładnie ten przypadek, który dawał 422.
    expect(terminalOf({ stage: "new", terminal_type: "rejected" })).toBe("rejected");
  });

  it("rozpoznaje własny etap zatrudnienia mimo stage='new'", () => {
    expect(terminalOf({ stage: "new", terminal_type: "hired" })).toBe("hired");
  });

  it("działa bez terminal_type (odpowiedzi sprzed dodania pola)", () => {
    expect(terminalOf({ stage: "rejected" })).toBe("rejected");
    expect(terminalOf({ stage: "hired" })).toBe("hired");
    expect(terminalOf({ stage: "withdrawn" })).toBe("withdrawn");
  });

  it("kolumna nieterminalna zwraca null", () => {
    expect(terminalOf({ stage: "new" })).toBeNull();
    expect(terminalOf({ stage: "screening" })).toBeNull();
    expect(terminalOf({ stage: "cv_sent" })).toBeNull();
  });

  it("terminal_type wygrywa z legacy stage", () => {
    // Gdyby kiedyś się rozjechały, wiążąca jest definicja etapu — bo to ona
    // rządzi zachowaniem backendu.
    expect(terminalOf({ stage: "rejected", terminal_type: "withdrawn" })).toBe(
      "withdrawn",
    );
  });

  it("null/undefined w terminal_type spada na fallback", () => {
    expect(terminalOf({ stage: "hired", terminal_type: null })).toBe("hired");
    expect(terminalOf({ stage: "new", terminal_type: null })).toBeNull();
  });
});
