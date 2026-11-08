import { describe, expect, it } from "vitest";

import {
  activeCardsWarningFrom,
  clientEndCount,
  closeAnywayLabel,
  peopleAccusative,
} from "@/lib/job-close";

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
    const base = { message: "", breakdown: "", clientEnd: null };
    expect(closeAnywayLabel({ ...base, recipients: [] })).toBe("Zamknij mimo to");
    expect(
      closeAnywayLabel(
        { ...base, recipients: [{ userId: 1, name: "A", people: 3, breakdown: "" }] },
        "Zapisz, zamknij",
      ),
    ).toBe("Zapisz, zamknij i powiadom 1 osobę");
  });
});

describe("pary u klienta przy zamknięciu (08.11.2026)", () => {
  const warning = activeCardsWarningFrom(
    error409({
      code: "active_cards_warning",
      message: "x",
      columns: { cv_sent: 1 },
      client_end: {
        reason: "competitor",
        reason_label: "Klient wybrał kogoś innego",
        people: 1,
        columns: { cv_sent: 1 },
        message: "1 osoba jest u klienta.",
      },
    }),
  );

  it("czyta podgląd z serwera", () => {
    expect(warning?.clientEnd).toEqual({
      reason: "competitor",
      reasonLabel: "Klient wybrał kogoś innego",
      people: 1,
      message: "1 osoba jest u klienta.",
      breakdown: "CV wysłane 1",
    });
  });

  it("zero, gdy powód jest inny albo ktoś wybrał „Nie”", () => {
    expect(clientEndCount(warning, "competitor", true)).toBe(1);
    expect(clientEndCount(warning, "budget", true)).toBe(0);
    expect(clientEndCount(warning, "competitor", false)).toBe(0);
    expect(clientEndCount(null, "competitor", true)).toBe(0);
  });

  it("przycisk mówi o zakończeniu tylko wtedy, gdy coś kończy", () => {
    expect(closeAnywayLabel(warning!, "Zamknij", 3)).toBe("Zamknij i zakończ 3 osoby u klienta");
    expect(closeAnywayLabel(warning!, "Zamknij", 0)).toBe("Zamknij mimo to");
  });

  it("stary serwer bez `client_end` = brak pytania", () => {
    expect(
      activeCardsWarningFrom(error409({ code: "active_cards_warning", message: "x" }))?.clientEnd,
    ).toBeNull();
  });
});
