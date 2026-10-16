import { describe, expect, it } from "vitest";

import {
  acceptanceLine,
  acceptanceTitle,
  acceptedToast,
  contractStepCounts,
  longDay,
  shortDay,
  shortPersonName,
  validateAcceptance,
  type ClientAcceptanceBadge,
} from "@/lib/client-acceptance";

const badge = (patch: Partial<ClientAcceptanceBadge> = {}): ClientAcceptanceBadge => ({
  stage_id: 7,
  accepted_on: "2026-10-16",
  planned_start_on: null,
  marked_at: "2026-10-16T09:30:00Z",
  marked_by_name: "Olga Wzorcowa",
  ...patch,
});

describe("akceptacja klienta — treści na karcie i w panelu (D1–D6, 16.10.2026)", () => {
  it("wiersz na karcie mówi, kiedy i kto zaznaczył", () => {
    expect(acceptanceLine(badge())).toBe("✓ Klient zaakceptował · 16.10 · Olga W.");
    // Bez autora (import, konto usunięte) — sama data.
    expect(acceptanceLine(badge({ marked_by_name: null }))).toBe("✓ Klient zaakceptował · 16.10");
    expect(acceptanceLine(null)).toBeNull();
  });

  it("dymek ma pełną datę, autora i planowany start", () => {
    expect(acceptanceTitle(badge({ planned_start_on: "2026-11-01" }))).toBe(
      "Klient zaakceptował 16.10.2026 — zaznaczył(a) Olga Wzorcowa. Planowany start: 01.11.2026.",
    );
    expect(acceptanceTitle(badge({ accepted_on: null, marked_by_name: null }))).toBe("Klient zaakceptował.");
  });

  it("daty i krótkie imię", () => {
    expect(shortDay("2026-01-05")).toBe("05.01");
    expect(longDay("2026-01-05")).toBe("05.01.2026");
    expect(shortDay("16.10.2026")).toBeNull();
    expect(shortPersonName("Olga Maria Wzorcowa")).toBe("Olga W.");
    expect(shortPersonName("Integracje")).toBe("Integracje");
    expect(shortPersonName("  ")).toBeNull();
  });

  it("dymek po zapisie wymienia, kto dostał dzwonek", () => {
    expect(
      acceptedToast("Karol Wzorcowy", [{ name: "Marta Nowak" }, { name: "Olaf Przykładowy" }]),
    ).toBe("Karol Wzorcowy — klient zaakceptował. Dzwonek: Marta N., Olaf P.");
    expect(acceptedToast("Karol Wzorcowy", [])).toBe("Karol Wzorcowy — klient zaakceptował.");
  });
});

describe("liczniki kroków w kolumnie „Akceptacja i umowa”", () => {
  it("akceptacja, umowa wysłana, podpisana; karta bez odznaki liczy się jako zaakceptowana", () => {
    expect(
      contractStepCounts(["acceptance", "contract_sent", "contract_signed", "contract_signed", null]),
    ).toEqual({ accepted: 2, sent: 1, signed: 2 });
    expect(contractStepCounts([])).toEqual({ accepted: 0, sent: 0, signed: 0 });
  });
});

describe("walidacja okna — lustro `assert_client_acceptance_dates`", () => {
  const today = "2026-10-16";

  it("dziś bez startu jest w porządku", () => {
    expect(validateAcceptance("2026-10-16", "", today)).toEqual({});
    expect(validateAcceptance("2026-10-15", "2026-11-01", today)).toEqual({});
  });

  it("akceptacja z przyszłości i pusta data to błąd", () => {
    expect(validateAcceptance("2026-10-17", "", today).acceptedOn).toBe(
      "Data akceptacji nie może być z przyszłości.",
    );
    expect(validateAcceptance("", "", today).acceptedOn).toBe("Podaj datę akceptacji.");
  });

  it("start przed akceptacją to błąd, start w dniu akceptacji nie", () => {
    expect(validateAcceptance("2026-10-16", "2026-10-15", today).plannedStartOn).toBe(
      "Start nie może wypaść przed akceptacją.",
    );
    expect(validateAcceptance("2026-10-16", "2026-10-16", today)).toEqual({});
  });
});
