import { describe, expect, it } from "vitest";

import {
  startReadiness,
  type StartPart,
  type StartReadinessInput,
} from "@/lib/client-start-readiness";

const hidden = { status: "hidden" } as const;
const ready = <T>(data: T): StartPart<T> => ({ status: "ready", data });

function input(overrides: Partial<StartReadinessInput> = {}): StartReadinessInput {
  return {
    documents: ready({ count: 0, notRequired: false }),
    settlement: ready({ mode: null }),
    pack: ready({ provider: "nieznany", place: null }),
    ...overrides,
  };
}

function shown(value: StartReadinessInput) {
  const result = startReadiness(value);
  if (!result.show) throw new Error("licznik powinien być widoczny");
  return result;
}

describe("startReadiness — co liczy się jako ustalone", () => {
  it("nic nie ustalone: cztery pola, wartości domyślne się nie liczą", () => {
    const result = shown(input());
    expect([result.settled, result.total]).toEqual([0, 4]);
    expect(result.fields.map((f) => [f.label, f.value, f.settled])).toEqual([
      ["Dokumenty do startu", "brak listy", false],
      ["Sposób rozliczania", "nie wybrano", false],
      ["Sprzęt", "nie wiadomo", false],
      ["Pierwszy dzień", "nie wpisano miejsca", false],
    ]);
  });

  it("wszystko ustalone jawnie: 4 z 4", () => {
    const result = shown(
      input({
        documents: ready({ count: 3, notRequired: false }),
        settlement: ready({ mode: "client_report" }),
        pack: ready({ provider: "nasz", place: "ul. Przykładowa 1, recepcja" }),
      }),
    );
    expect([result.settled, result.total]).toEqual([4, 4]);
    expect(result.fields.map((f) => f.value)).toEqual([
      "3 pozycje na liście",
      "Raport od klienta",
      "od nas",
      "ul. Przykładowa 1, recepcja",
    ]);
  });

  it("pusta lista z „Klient nie wymaga dokumentów” jest ustalona", () => {
    const result = shown(input({ documents: ready({ count: 0, notRequired: true }) }));
    expect(result.fields[0]).toMatchObject({ settled: true, value: "klient nie wymaga" });
    expect(result.settled).toBe(1);
  });

  it("lista z pozycjami wygrywa ze starym znacznikiem", () => {
    const result = shown(input({ documents: ready({ count: 1, notRequired: true }) }));
    expect(result.fields[0]).toMatchObject({ settled: true, value: "1 pozycja na liście" });
  });

  it("odmienia liczbę pozycji po polsku", () => {
    const value = (count: number) =>
      shown(input({ documents: ready({ count, notRequired: false }) })).fields[0].value;
    expect(value(5)).toBe("5 pozycji na liście");
    expect(value(12)).toBe("12 pozycji na liście");
    expect(value(22)).toBe("22 pozycje na liście");
  });

  it("sprzęt od klienta jest ustalony, „nie wiadomo” nie", () => {
    expect(
      shown(input({ pack: ready({ provider: "klienta", place: null }) })).fields[2],
    ).toMatchObject({ settled: true, value: "od klienta" });
    expect(
      shown(input({ pack: ready({ provider: "nieznany", place: null }) })).fields[2].settled,
    ).toBe(false);
  });

  it("miejsce z samych spacji to brak miejsca, a wpisane jest przycięte", () => {
    expect(
      shown(input({ pack: ready({ provider: "nieznany", place: "   " }) })).fields[3],
    ).toMatchObject({ settled: false, value: "nie wpisano miejsca" });
    expect(
      shown(input({ pack: ready({ provider: "nieznany", place: "  Recepcja B  " }) })).fields[3],
    ).toMatchObject({ settled: true, value: "Recepcja B" });
  });
});

describe("startReadiness — kto widzi licznik", () => {
  it("jedna widoczna część (DL przy wyłączonym module): bez licznika", () => {
    expect(startReadiness(input({ settlement: hidden, pack: hidden }))).toEqual({ show: false });
  });

  it("nic nie widać: bez licznika", () => {
    expect(
      startReadiness({ documents: hidden, settlement: hidden, pack: hidden }),
    ).toEqual({ show: false });
  });

  it("DL po włączeniu modułu (bez rozliczenia): N z 3", () => {
    const result = shown(input({ settlement: hidden }));
    expect(result.total).toBe(3);
    expect(result.fields.map((f) => f.key)).toEqual(["documents", "equipment", "first_day"]);
  });

  it("bez dokumentów do startu, z pakietem i rozliczeniem: N z 3", () => {
    const result = shown(input({ documents: hidden }));
    expect(result.fields.map((f) => f.key)).toEqual(["settlement", "equipment", "first_day"]);
  });

  it("część w trakcie wczytywania: licznik czeka, nie zaniża mianownika", () => {
    expect(startReadiness(input({ pack: { status: "loading" } }))).toEqual({ show: false });
  });

  it("część z błędem: bez licznika (błąd pokazuje sama część)", () => {
    expect(startReadiness(input({ settlement: { status: "error" } }))).toEqual({ show: false });
  });

  it("niewidoczne rozliczenie nie psuje kompletu tego, co osoba może ustalić", () => {
    const result = shown({
      documents: ready({ count: 2, notRequired: false }),
      settlement: hidden,
      pack: ready({ provider: "klienta", place: "Recepcja" }),
    });
    expect([result.settled, result.total]).toEqual([3, 3]);
  });
});
