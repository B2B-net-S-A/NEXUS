import { describe, expect, it } from "vitest";

import {
  m365ProfileSyncView,
  m365ReasonLabel,
  m365SecretView,
  m365StatusView,
  type M365JobRun,
} from "@/lib/api/hr-m365";

function run(overrides: Partial<M365JobRun>): M365JobRun {
  return {
    day: "2026-10-20",
    status: "done",
    finished_at: "2026-10-20T04:02:00+00:00",
    counts: {},
    error: null,
    ...overrides,
  };
}

describe("hr-m365 labels", () => {
  it("translates error categories and keeps the HTTP code", () => {
    expect(m365ReasonLabel("forbidden (403)")).toBe("Brak uprawnień aplikacji w Exchange (403)");
    expect(m365ReasonLabel("user_custom")).toBe("Osoba ma własną autoodpowiedź");
    expect(m365ReasonLabel("waiting_for_window")).toBe("Czeka na pierwszy dzień urlopu");
    expect(m365ReasonLabel("user_exited")).toBe("Osoba odeszła — skrzynka poza zakresem aplikacji");
    expect(m365ReasonLabel(null)).toBeNull();
    // Nieznany kod zostaje widoczny, zamiast zniknąć.
    expect(m365ReasonLabel("nowy_powod")).toBe("nowy_powod");
  });

  it("tells waiting operations from queued ones", () => {
    expect(m365StatusView({ status: "pending", deferred: true })).toEqual({ label: "Czeka", tone: "neutral" });
    expect(m365StatusView({ status: "pending", deferred: false }).label).toBe("W kolejce");
    expect(m365StatusView({ status: "failed", deferred: false }).tone).toBe("danger");
    expect(m365StatusView({ status: "simulated", deferred: false }).label).toBe("Zasymulowano");
  });

  it("warns about the secret 30 days ahead and after the date", () => {
    expect(m365SecretView({ expires_on: "2027-04-30", days_left: 120, state: "ok" })).toEqual({
      label: "Ważny do 30.04.2027",
      tone: "success",
    });
    expect(m365SecretView({ expires_on: "2027-04-30", days_left: 12, state: "expiring" })).toEqual({
      label: "Wygasa za 12 dni",
      tone: "warning",
      note: "30.04.2027",
    });
    expect(m365SecretView({ expires_on: "2027-04-30", days_left: 1, state: "expiring" }).label).toBe(
      "Wygasa jutro",
    );
    expect(m365SecretView({ expires_on: "2027-04-30", days_left: 0, state: "expired" }).label).toBe(
      "Wygasa dziś",
    );
    expect(m365SecretView({ expires_on: "2027-04-30", days_left: -3, state: "expired" })).toMatchObject({
      label: "Wygasł",
      tone: "danger",
    });
    expect(m365SecretView({ expires_on: null, days_left: null, state: "missing" }).tone).toBe("warning");
    expect(m365SecretView({ expires_on: null, days_left: null, state: "not_set" }).tone).toBe("neutral");
  });

  it("summarises the last profile read without hiding a failure", () => {
    expect(m365ProfileSyncView(null)).toEqual({ label: "Jeszcze się nie odbył", tone: "neutral" });
    expect(
      m365ProfileSyncView(run({ counts: { mode: "live", read: 41, updated: 3, kept_manual: 1, not_found: 2 } })),
    ).toEqual({
      label: "20.10.2026 · zakończony",
      tone: "success",
      note: "zaktualizowano 3 z 41 · zostawione zmiany Kadr: 1 · bez konta w Microsoft 365: 2",
    });
    expect(m365ProfileSyncView(run({ counts: { mode: "simulate", read: 41 } }))).toMatchObject({
      label: "20.10.2026 · symulacja",
      note: "Kont do odczytu: 41 · kartoteka bez zmian",
    });
    expect(m365ProfileSyncView(run({ status: "failed", error: "forbidden" }))).toEqual({
      label: "20.10.2026 · nie udał się",
      tone: "danger",
      note: "aplikacja nie ma uprawnienia User.Read.All",
    });
    // Nieznany błąd nie znika — dostaje ogólny opis.
    expect(m365ProfileSyncView(run({ status: "failed", error: "ValueError" })).note).toBe(
      "błąd po stronie NEXUSA",
    );
    expect(m365ProfileSyncView(run({ status: "claimed" })).tone).toBe("info");
  });
});
