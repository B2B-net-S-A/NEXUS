import { describe, expect, it } from "vitest";

import { people, returnedLine, returnedTitle, returnedToViewer, screeningWarning } from "@/lib/screening-returned";

const card = (holder: number | null, extra: object = {}) => ({
  returned_from_screening: {
    at: "2026-11-25T23:06:41Z",
    holder_user_id: holder,
    holder_name: "Ola Testowa",
    screening_since: "2026-11-23T09:15:00Z",
    ...extra,
  },
});

describe("napis pod kartą, która wróciła ze Screeningu", () => {
  it("osobie, od której wróciła: dzień powrotu, a w podpowiedzi od kiedy stała w Screeningu", () => {
    expect(returnedToViewer(card(261), 261)).toBe(true);
    expect(returnedLine(card(261), 261)).toBe("Wróciła 26.11");
    expect(returnedTitle(card(261))).toMatch(/^W Screeningu od 23\.11\. 2 dni robocze/);
    expect(returnedTitle(card(261, { screening_since: null }))).toMatch(/^2 dni robocze/);
  });

  it("pozostałym: od kogo wróciła", () => {
    expect(returnedToViewer(card(261), 5)).toBe(false);
    expect(returnedLine(card(261), 5)).toBe("Wróciła ze Screeningu od: Ola Testowa");
    expect(returnedLine(card(null, { holder_name: null }), 5)).toBe("Wróciła ze Screeningu");
  });

  it("karta bez powrotu nie ma napisu", () => {
    expect(returnedLine({}, 261)).toBeNull();
    expect(returnedLine({ returned_from_screening: null }, 261)).toBeNull();
  });

  it("zły termin nie psuje napisu", () => {
    expect(returnedLine(card(261, { at: "x", screening_since: null }), 261)).toBe("Wróciła");
  });
});

describe("pasek nad Screeningiem", () => {
  it("liczy karty z napisem i bierze dzień z napisu, gdy jest jeden", () => {
    expect(screeningWarning([null, "Wraca do „Nowych” jutro", "Wraca do „Nowych” jutro"])).toBe(
      "Wraca do „Nowych” jutro: 2 osoby",
    );
  });

  it("różne dni dają „Wkrótce”", () => {
    expect(screeningWarning(["Wraca do „Nowych” dziś", "Wraca do „Nowych” jutro"])).toBe(
      "Wkrótce wraca do „Nowych”: 2 osoby",
    );
  });

  it("bez napisów nie ma paska", () => {
    expect(screeningWarning([null, null])).toBeNull();
  });

  it("odmienia osoby", () => {
    expect([1, 2, 5, 12, 22, 25].map(people)).toEqual([
      "1 osoba",
      "2 osoby",
      "5 osób",
      "12 osób",
      "22 osoby",
      "25 osób",
    ]);
  });
});

describe("wrócona karta, którą ktoś już wziął „Biorę” (przegląd 26.11)", () => {
  it("cudza aktywna blokada: nie moja grupa i bez napisu „od: …”", () => {
    const taken = { ...card(261), claim_user_id: 5, claim_until: "2999-01-01T00:00:00Z" };
    expect(returnedToViewer(taken, 261)).toBe(false);
    expect(returnedLine(taken, 261)).toBeNull();
    expect(returnedLine(taken, 9)).toBeNull();
  });

  it("własne „Biorę” po „Cofnij”: karta dalej w mojej grupie", () => {
    const mine = { ...card(261), claim_user_id: 261, claim_until: "2999-01-01T00:00:00Z" };
    expect(returnedToViewer(mine, 261)).toBe(true);
    expect(returnedLine(mine, 261)).toBe("Wróciła 26.11");
  });
});
