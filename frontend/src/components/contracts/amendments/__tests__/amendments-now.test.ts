/**
 * Karta „Obowiązuje teraz” (wariant A, 19.11.2026): stawki z dniem, od
 * którego obowiązują, koniec zamówienia i umowy — liczone z kontraktu.
 */
import { describe, expect, it } from "vitest";

import {
  amendmentsNow,
  rateRun,
  type AmendmentsContract,
} from "@/components/contracts/amendments/amendments-now";

const TODAY = "2026-11-20";

/** Kwota z `formatMoney` ma twardą spację przed walutą — w oczekiwaniach piszemy zwykłą. */
const nb = (text: string) => text.replace(/ (?=zł|EUR)/g, "\u00a0");

const CONTRACT: AmendmentsContract = {
  contract_type: "b2b",
  end_date: null,
  client_order_end_date: "2026-12-31",
  latest_order_end_date: null,
  rate_client: 170,
  rate_candidate: 130,
  currency: "PLN",
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  rate_unit: "hourly",
  client_rate_schedule: [
    { rate: 180, effective_from: "2026-04-01", source_order_id: null },
    { rate: 170, effective_from: "2026-07-01", source_order_id: null },
  ],
  candidate_rate_schedule: [
    { rate: 140, effective_from: "2026-04-01" },
    { rate: 130, effective_from: "2026-07-01" },
    // Ten sam krok zapisany drugi raz (powtórzony aneks).
    { rate: 130, effective_from: "2026-07-01" },
  ],
};

describe("obowiązuje teraz", () => {
  it("obie stawki od tego samego dnia: jedna data z przodu, zamówienie i umowa B2B bezterminowa", () => {
    expect(amendmentsNow(CONTRACT, { today: TODAY, canSeeRates: true })).toEqual({
      since: "2026-07-01",
      rates: [
        { who: "klient", amount: nb("170,00 zł/h"), since: null },
        { who: "kandydat", amount: nb("130,00 zł/h"), since: null },
      ],
      order: { end: "2026-12-31", ended: false },
      facts: ["umowa B2B bezterminowa"],
    });
  });

  it("stawka klienta z zamówienia: zdanie, że nie z aneksu; różne dni przy każdej stawce", () => {
    const now = amendmentsNow(
      {
        ...CONTRACT,
        rate_client: 140,
        client_rate_schedule: [
          { rate: 150, effective_from: "2025-08-04", source_order_id: null },
          { rate: 130, effective_from: "2026-07-01", source_order_id: 11 },
          { rate: 140, effective_from: "2026-09-01", source_order_id: 12 },
        ],
      },
      { today: TODAY, canSeeRates: true },
    );
    expect(now.since).toBeNull();
    expect(now.rates).toEqual([
      { who: "klient", amount: nb("140,00 zł/h"), since: "2026-09-01" },
      { who: "kandydat", amount: nb("130,00 zł/h"), since: "2026-07-01" },
    ]);
    expect(now.facts).toEqual(["umowa B2B bezterminowa", "stawka klienta z zamówienia, nie z aneksu"]);
  });

  it("bez wglądu w kwoty: bez stawek i bez zdania o ich źródle", () => {
    const now = amendmentsNow(
      { ...CONTRACT, client_rate_schedule: [{ rate: 170, effective_from: "2026-07-01", source_order_id: 5 }] },
      { today: TODAY, canSeeRates: false },
    );
    expect(now.rates).toEqual([]);
    expect(now.since).toBeNull();
    expect(now.facts).toEqual(["umowa B2B bezterminowa"]);
    expect(now.order).toEqual({ end: "2026-12-31", ended: false });
  });

  it("umowa z datą końca, zamówienie po terminie, waluta i jednostka stawki klienta", () => {
    const now = amendmentsNow(
      {
        ...CONTRACT,
        contract_type: "uzlecenie",
        end_date: "2027-03-31",
        client_order_end_date: "2026-10-31",
        rate_client: 1050,
        rate_client_currency: "EUR",
        rate_unit: "daily",
        client_rate_schedule: [],
      },
      { today: TODAY, canSeeRates: true },
    );
    expect(now.rates[0]).toEqual({ who: "klient", amount: nb("1050,00 EUR/MD"), since: null });
    expect(now.order).toEqual({ end: "2026-10-31", ended: true });
    expect(now.facts).toEqual(["umowa do 31.03.2027"]);
    expect(amendmentsNow({ ...CONTRACT, contract_type: "uop" }, { today: TODAY, canSeeRates: true }).facts).toEqual([
      "umowa bez daty końca",
    ]);
  });

  it("najnowszy koniec zamówienia wygrywa z końcem bieżącego; brak zamówienia — brak pozycji", () => {
    expect(amendmentsNow({ ...CONTRACT, latest_order_end_date: "2027-06-30" }, { today: TODAY, canSeeRates: true }).order).toEqual({
      end: "2027-06-30",
      ended: false,
    });
    expect(amendmentsNow({ ...CONTRACT, client_order_end_date: null }, { today: TODAY, canSeeRates: true }).order).toBeNull();
  });

  it("kontrakt bez stawki kandydata: brak kwoty i dzień tylko przy stawce klienta", () => {
    const now = amendmentsNow({ ...CONTRACT, rate_candidate: null }, { today: TODAY, canSeeRates: true });
    expect(now.since).toBeNull();
    expect(now.rates).toEqual([
      { who: "klient", amount: nb("170,00 zł/h"), since: "2026-07-01" },
      { who: "kandydat", amount: null, since: null },
    ]);
  });
});

describe("od kiedy obowiązuje kwota", () => {
  it("ciąg kroków z tą samą kwotą liczy się od pierwszego", () => {
    expect(
      rateRun(
        [
          { rate: 150, effective_from: "2025-08-04" },
          { rate: 130, effective_from: "2026-07-01" },
          { rate: 130, effective_from: "2026-07-10" },
        ],
        130,
        TODAY,
      ),
    ).toEqual({ since: "2026-07-01", fromOrder: false });
  });

  it("krok z przyszłości i krok zastąpiony się nie liczą", () => {
    const steps = [
      { rate: 130, effective_from: "2026-07-01" },
      { rate: 125, effective_from: "2026-09-01", superseded: true },
      { rate: 160, effective_from: "2026-12-01" },
    ];
    expect(rateRun(steps, 130, TODAY)).toEqual({ since: "2026-07-01", fromOrder: false });
  });

  it("kwota spoza harmonogramu albo brak kroków — dnia nie zgadujemy", () => {
    expect(rateRun([{ rate: 150, effective_from: "2026-01-01" }], 140, TODAY)).toEqual({ since: null, fromOrder: false });
    expect(rateRun([], 140, TODAY)).toEqual({ since: null, fromOrder: false });
    expect(rateRun(null, 140, TODAY)).toEqual({ since: null, fromOrder: false });
    expect(rateRun([{ rate: 140, effective_from: "2026-01-01" }], null, TODAY)).toEqual({ since: null, fromOrder: false });
  });

  it("z kroków z jednego dnia rozstrzyga ostatni z odpowiedzi (ręczny po zamówieniu)", () => {
    expect(
      rateRun(
        [
          { rate: 130, effective_from: "2026-07-01", source_order_id: 7 },
          { rate: 130, effective_from: "2026-07-01", source_order_id: null },
        ],
        130,
        TODAY,
      ),
    ).toEqual({ since: "2026-07-01", fromOrder: false });
  });
});
