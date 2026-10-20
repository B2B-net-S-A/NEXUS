/**
 * Terminy z wklejonego maila → wiersze okna „Terminy od klienta” (20.10.2026).
 */
import { describe, expect, it } from "vitest";

import {
  isoToLocalInput,
  noteFromMail,
  readSummary,
  rowsFromMail,
  type SlotsFromMail,
  warningLabel,
} from "@/lib/interview-slot-mail";

function result(over: Partial<SlotsFromMail> = {}): SlotsFromMail {
  return {
    status: "ok",
    message: null,
    slots: [
      { start: "2026-10-22T08:00:00Z", end: "2026-10-22T08:45:00Z", window: false, quote: "czwartek o 10:00", warning: null },
      { start: "2026-10-23T07:00:00Z", end: "2026-10-23T10:00:00Z", window: true, quote: "piątek między 9 a 12", warning: "weekday_mismatch" },
    ],
    extra_slots: 0,
    dropped: 0,
    duration_minutes: 45,
    respond_by: null,
    format: "online",
    location_note: "Teams",
    people: "Marta (HM), Tomek",
    unclear: [],
    ...over,
  };
}

describe("interview-slot-mail", () => {
  it("ISO wraca jako wartość pola datetime-local w czasie przeglądarki", () => {
    const iso = "2026-10-22T08:00:00Z";
    expect(new Date(isoToLocalInput(iso)).toISOString()).toBe(new Date(iso).toISOString());
    expect(isoToLocalInput(iso)).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  });

  it("wiersze niosą cytat, ostrzeżenie i koniec okna tylko dla okna", () => {
    const rows = rowsFromMail(result());
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ quote: "czwartek o 10:00", warning: null, windowEnd: undefined });
    expect(rows[1]).toMatchObject({ warning: "weekday_mismatch", windowEnd: "2026-10-23T10:00:00Z" });
  });

  it("notatka: forma, ludzie po stronie klienta i okna do ustalenia", () => {
    const note = noteFromMail(result());
    const lines = note.split("\n");
    expect(lines[0]).toBe("Online · Teams");
    expect(lines[1]).toBe("Po stronie klienta: Marta (HM), Tomek");
    expect(lines[2]).toMatch(/^Okno klienta: .* — godzinę ustal z kandydatem\.$/);
  });

  it("pusta notatka, gdy mail mówi tylko o terminach", () => {
    expect(
      noteFromMail(result({ format: null, location_note: null, people: null, slots: [result().slots[0]] })),
    ).toBe("");
  });

  it("podsumowanie mówi o limicie i terminach bez godziny", () => {
    expect(readSummary(result({ extra_slots: 2, unclear: ["w czwartek rano"] }))).toBe(
      "Odczytane terminy: 2. Sprawdź je przed wysłaniem. Pominięte ponad limit 6: 2. Bez godziny: w czwartek rano.",
    );
    expect(readSummary(result({ status: "unavailable", message: "Nie udało się", slots: [] }))).toBe("Nie udało się");
  });

  it("ostrzeżenia po polsku", () => {
    expect(warningLabel("weekday_mismatch")).toMatch(/Dzień tygodnia/);
    expect(warningLabel(null)).toBeNull();
  });
});
