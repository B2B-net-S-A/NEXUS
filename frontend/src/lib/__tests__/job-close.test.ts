import { describe, expect, it } from "vitest";

import { activeCardsWarningFrom, closeAnywayLabel, peopleAccusative } from "@/lib/job-close";

function error409(detail: Record<string, unknown>) {
  return { response: { status: 409, data: { detail } } };
}

describe("activeCardsWarningFrom — odbiorcy po zamknięciu (28.10.2026)", () => {
  it("czyta rekruterów z liczbami w kolejności kolumn Tablicy", () => {
    const warning = activeCardsWarningFrom(
      error409({
        code: "active_cards_warning",
        message: "W tej rekrutacji są 3 osoby w toku.",
        columns: { cv_sent: 2, new: 1 },
        recipients: [
          { user_id: 7, name: "Rekruterka A", people: 2, columns: { client_interview: 1, cv_sent: 1 } },
        ],
      }),
    );
    expect(warning?.breakdown).toBe("Nowi 1 · CV wysłane 2");
    expect(warning?.recipients).toEqual([
      { userId: 7, name: "Rekruterka A", people: 2, breakdown: "CV wysłane 1 · Rozmowa u klienta 1" },
    ]);
  });

  it("stary serwer bez listy i śmieci w liście dają pustą listę", () => {
    expect(
      activeCardsWarningFrom(error409({ code: "active_cards_warning", message: "x" }))?.recipients,
    ).toEqual([]);
    expect(
      activeCardsWarningFrom(
        error409({ code: "active_cards_warning", recipients: [null, { name: "bez id" }, "x"] }),
      )?.recipients,
    ).toEqual([]);
  });

  it("inna odmowa to nie ostrzeżenie", () => {
    expect(activeCardsWarningFrom(error409({ code: "job_already_closed" }))).toBeNull();
    expect(activeCardsWarningFrom(new Error("boom"))).toBeNull();
  });
});

describe("napis przycisku", () => {
  it("odmienia liczbę osób", () => {
    expect([1, 2, 4, 5, 12, 14, 22, 25].map(peopleAccusative)).toEqual([
      "1 osobę",
      "2 osoby",
      "4 osoby",
      "5 osób",
      "12 osób",
      "14 osób",
      "22 osoby",
      "25 osób",
    ]);
  });

  it("zapowiada powiadomienie albo zamyka mimo to", () => {
    const base = { message: "", breakdown: "" };
    expect(closeAnywayLabel({ ...base, recipients: [] })).toBe("Zamknij mimo to");
    expect(
      closeAnywayLabel(
        { ...base, recipients: [{ userId: 1, name: "A", people: 3, breakdown: "" }] },
        "Zapisz, zamknij",
      ),
    ).toBe("Zapisz, zamknij i powiadom 1 osobę");
  });
});
