import { describe, expect, it } from "vitest";

import { findConflicts, numberToField } from "@/lib/order-extraction";

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
});
