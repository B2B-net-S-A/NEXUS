/**
 * Wiersz „Odrzuć:” w panelu osoby (decyzja Artura 23.11.2026): które powody
 * trafiają do skrótu, gdzie skrót stoi i co mówi komunikat po kliknięciu.
 */
import { describe, expect, it } from "vitest";

import {
  quickRejectAllowed,
  quickRejectChips,
  quickRejectLearnedFrom,
  quickRejectMessage,
} from "@/lib/quick-reject";

describe("quickRejectChips", () => {
  it("trzy powody z etykietami okna; „Za droga” i tryb pracy otwierają okno", () => {
    const chips = quickRejectChips([
      { key: "missing_skill", count: 108, source: "mine" },
      { key: "too_junior", count: 85, source: "mine" },
      { key: "too_expensive", count: 84, source: "mine" },
      { key: "not_looking", count: 10, source: "mine" },
    ]);
    expect(chips.map((c) => [c.label, c.opensWindow])).toEqual([
      ["Brak kluczowej umiejętności", false],
      ["Za mało doświadczenia", false],
      ["Za droga", true],
    ]);
    expect(quickRejectChips([{ key: "location_mode", count: 1, source: "team" }])[0].opensWindow).toBe(true);
  });

  it("brak historii i awaria = brak chipów", () => {
    expect(quickRejectChips([])).toEqual([]);
    expect(quickRejectChips(undefined)).toEqual([]);
  });

  it("nigdy „Inne”, „Już po rozmowie u HM”, powodów klienta ani kandydata, ani nieznanych kluczy", () => {
    const chips = quickRejectChips([
      { key: "other", count: 50, source: "mine" },
      { key: "hm_already_interviewed", count: 40, source: "mine" },
      { key: "client_chose_other", count: 30, source: "mine" },
      { key: "counter_offer", count: 20, source: "mine" },
      { key: "nieznany", count: 10, source: "mine" },
      { key: "no_answer", count: 1, source: "team" },
    ]);
    expect(chips.map((c) => c.key)).toEqual(["no_answer"]);
  });
});

describe("gdzie stoi skrót", () => {
  it("tylko „Nowi” i „Screening” — od „Zweryfikowanego” mail i powody klienta zostają w oknie", () => {
    expect(quickRejectAllowed("new")).toBe(true);
    expect(quickRejectAllowed("screening")).toBe(true);
    for (const column of ["verified", "qc", "cv_sent", "client_interview", "closed", null, undefined] as const) {
      expect(quickRejectAllowed(column as never)).toBe(false);
    }
  });

  it("„Skąd wiesz” dla osoby od systemu: Nowi — profil, Screening — rozmowa", () => {
    expect(quickRejectLearnedFrom("new")).toBe("profile");
    expect(quickRejectLearnedFrom("screening")).toBe("call");
  });
});

describe("quickRejectMessage", () => {
  it("mówi, kogo odrzucono, z jakim powodem i kto jest otwarty", () => {
    expect(
      quickRejectMessage({ name: "Anna Nowak", reasonLabel: "Za mało doświadczenia", next: "Jan Lis", queueName: "Nowi" }),
    ).toBe("Odrzucono: Anna Nowak · Za mało doświadczenia · otwarta: Jan Lis");
  });

  it("po ostatniej osobie mówi, że kolejka się skończyła", () => {
    expect(
      quickRejectMessage({ name: "Anna Nowak", reasonLabel: "Nie szuka pracy", next: null, queueName: "Nowi" }),
    ).toBe("Odrzucono: Anna Nowak · Nie szuka pracy · to była ostatnia osoba w kolejce „Nowi”");
  });
});
