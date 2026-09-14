import { describe, expect, it } from "vitest";

import {
  extractedEndDate,
  findConflicts,
  matchExtractedConsultant,
  numberToField,
  OPEN_ENDED_LABEL,
  typedByUser,
} from "@/lib/order-extraction";

describe("findConflicts", () => {
  it("puste pole NIE jest rozbieżnością — wypełnienie pustki nic nie kasuje", () => {
    expect(
      findConflicts([
        { key: "title", label: "Numer", current: "", incoming: "445" },
      ]),
    ).toEqual([]);
  });

  it("brak wartości w dokumencie nie tworzy rozbieżności", () => {
    expect(
      findConflicts([
        { key: "title", label: "Numer", current: "444", incoming: null },
      ]),
    ).toEqual([]);
  });

  it("ta sama wartość nie jest rozbieżnością (także z białymi znakami)", () => {
    expect(
      findConflicts([
        { key: "title", label: "Numer", current: " 445 ", incoming: "445" },
      ]),
    ).toEqual([]);
  });

  it("różnica wypisuje obie wartości — bez tego Tak/Nie jest zgadywanką", () => {
    expect(
      findConflicts([
        { key: "title", label: "Numer zamówienia", current: "444", incoming: "445" },
      ]),
    ).toEqual([
      {
        key: "title",
        label: "Numer zamówienia",
        current: "444",
        incoming: "445",
      },
    ]);
  });
});

describe("numberToField", () => {
  it("null i undefined dają pusty string, zero zostaje zerem", () => {
    expect(numberToField(null)).toBe("");
    expect(numberToField(undefined)).toBe("");
    expect(numberToField(0)).toBe("0");
    expect(numberToField(1200)).toBe("1200");
  });

  it("obcina końcowe zera z Decimala serializowanego jako tekst", () => {
    // Backend zwraca `Decimal` tekstem — pole pokazywało „1200.0".
    expect(numberToField("1200.0")).toBe("1200");
    expect(numberToField("100.00")).toBe("100");
    expect(numberToField("57.500")).toBe("57.5");
    expect(numberToField("0.0")).toBe("0");
    expect(numberToField("1200")).toBe("1200");
  });
});

describe("extractedEndDate — „bezterminowo” z reguły klienta", () => {
  it("data z dokumentu wygrywa", () => {
    expect(extractedEndDate({ end_date: "2031-12-31T00:00:00", open_ended: true })).toEqual({
      value: "2031-12-31",
      display: "2031-12-31",
    });
  });

  it("reguła „bezterminowo” czyści pole zamiast zostawiać starą datę", () => {
    expect(extractedEndDate({ end_date: null, open_ended: true })).toEqual({
      value: "",
      display: OPEN_ENDED_LABEL,
    });
  });

  it("brak daty bez reguły to brak informacji, nie „bezterminowo”", () => {
    expect(extractedEndDate({ end_date: null })).toBeNull();
    expect(extractedEndDate({ end_date: null, open_ended: false })).toBeNull();
  });
});

describe("matchExtractedConsultant — pozycja tej samej osoby", () => {
  const row = (consultant_name: string) => ({
    consultant_name,
    start_date: null,
    end_date: null,
    rate_client: 1000,
    rate_unit: "day",
    md_total: 10,
  });

  it("kolejność imienia i nazwiska oraz polskie znaki nie mają znaczenia", () => {
    const rows = [row("Łęcki Piotr"), row("Anna Nowak")];
    expect(matchExtractedConsultant("Piotr Łęcki", rows)).toBe(rows[0]);
    expect(matchExtractedConsultant("piotr lecki", rows)).toBe(rows[0]);
  });

  it("brak osoby, pusta nazwa albo dwa trafienia → null (bez zgadywania)", () => {
    expect(matchExtractedConsultant("Jan Kowalski", [row("Anna Nowak")])).toBeNull();
    expect(matchExtractedConsultant("Jan Kowalski", [row("")])).toBeNull();
    expect(
      matchExtractedConsultant("Jan Kowalski", [row("Jan Kowalski"), row("Kowalski Jan")]),
    ).toBeNull();
  });
});

describe("typedByUser", () => {
  it("wartość z poprzedniego odczytu dokumentu nie jest „wpisana ręcznie”", () => {
    expect(typedByUser("107000", "107000")).toBe("");
    expect(typedByUser(" 107000 ", "107000")).toBe("");
  });

  it("wartość różna od poprzedniego dokumentu albo bez odczytu jest wpisana", () => {
    expect(typedByUser("5000", "107000")).toBe("5000");
    expect(typedByUser("5000", undefined)).toBe("5000");
    expect(typedByUser("  ", undefined)).toBe("");
  });
});
