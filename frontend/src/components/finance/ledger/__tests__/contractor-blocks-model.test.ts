import { describe, expect, it } from "vitest";

import {
  amountText,
  emptyGarnishmentForm,
  garnishmentInput,
  releasedMessage,
} from "@/components/finance/ledger/contractor-blocks-model";

const base = {
  ...emptyGarnishmentForm("2026-11-23"),
  authority_name: "Komornik Sądowy Testowy",
  case_number: "KM 1/26",
  principal_amount: "1 234,5",
};

describe("contractor-blocks-model", () => {
  it("kwota z przecinkiem i spacją", () => {
    expect(amountText("1 234,5")).toBe("1234.50");
    expect(amountText("12.345")).toBeNull();
    expect(amountText("abc")).toBeNull();
  });

  it("odsetki nieustalone przechodzą — serwer zablokuje płatność do decyzji", () => {
    const result = garnishmentInput(base);
    expect(result).toEqual({
      body: expect.objectContaining({
        principal_amount: "1234.50",
        costs_amount: "0.00",
        interest_mode: "unknown",
        interest_amount: null,
        interest_rate: null,
        authority_account: null,
      }),
    });
  });

  it("stopa wymaga dnia, kwota odsetek wymaga liczby", () => {
    expect(
      garnishmentInput({
        ...base,
        interest_mode: "rate",
        interest_rate: "11,25",
      }),
    ).toEqual({
      error: "Podaj dzień, od którego liczyć odsetki.",
    });
    const rate = garnishmentInput({
      ...base,
      interest_mode: "rate",
      interest_rate: "11,25",
      interest_from: "2026-10-01",
    });
    expect("body" in rate && rate.body.interest_rate).toBe("11.25");
    expect(garnishmentInput({ ...base, interest_mode: "fixed" })).toEqual({
      error: "Wpisz kwotę odsetek z pisma organu.",
    });
  });

  it("odmowa bez organu, sygnatury albo z zerową należnością", () => {
    expect(garnishmentInput({ ...base, case_number: " " })).toEqual({
      error: "Podaj organ i sygnaturę sprawy.",
    });
    expect(garnishmentInput({ ...base, principal_amount: "0" })).toEqual({
      error: "Kwota należności musi być większa od zera.",
    });
  });

  it("komunikat: zdjęte z paczki i zostawione w pobranej paczce", () => {
    expect(releasedMessage([])).toBeNull();
    expect(
      releasedMessage([
        {
          batch_id: 4,
          entry_id: 1,
          file_stale: false,
          released: true,
          reason: null,
        },
        {
          batch_id: 5,
          entry_id: 2,
          file_stale: false,
          released: false,
          reason: "downloaded",
        },
      ]),
    ).toBe(
      "Zdjęto z paczki #4 (1) — podział płatności się zmienił. Paczka #5 ma pobrany plik — jeśli bank go jeszcze nie wykonał, zdejmij fakturę z paczki i utwórz nową.",
    );
  });
});
