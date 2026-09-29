import { describe, expect, it } from "vitest";

import {
  accusativeNamePl,
  boardFunctions,
  boardSummary,
  companyVariantMissing,
  functionAccusativePl,
  representationPl,
  seatLocativePl,
} from "@/lib/b2b-company-variant";

describe("accusativeNamePl", () => {
  it.each([
    ["Jan Kowalski", "m", "Jana Kowalskiego"],
    ["Piotr Nowak", "m", "Piotra Nowaka"],
    ["Marek Wolny", "m", "Marka Wolnego"],
    ["Paweł Zawisza", "m", "Pawła Zawiszę"],
    ["TOMASZ LEWANDOWSKI", "m", "Tomasza Lewandowskiego"],
    ["Anna Nowak", "k", "Annę Nowak"],
    ["Maria Kowalska", "k", "Marię Kowalską"],
    ["Ewa Nowak-Kowalska", "k", "Ewę Nowak-Kowalską"],
  ] as const)("%s (%s) → %s", (name, gender, expected) => {
    expect(accusativeNamePl(name, gender)).toBe(expected);
  });

  it("pusta wartość zostaje pusta", () => {
    expect(accusativeNamePl("  ", "m")).toBe("");
  });
});

describe("functionAccusativePl", () => {
  it("odmienia znane funkcje zarządu", () => {
    expect(functionAccusativePl("Prezes Zarządu", "m")).toBe("Prezesa Zarządu");
    expect(functionAccusativePl("PREZES ZARZĄDU", "k")).toBe("Prezes Zarządu");
    expect(functionAccusativePl("Członek Zarządu", "k")).toBe(
      "Członka Zarządu",
    );
  });

  it("nieznana funkcja zostaje jak wpisana", () => {
    expect(functionAccusativePl("Pełnomocnik", "m")).toBe("Pełnomocnik");
  });
});

describe("representationPl", () => {
  it("składa frazę po „reprezentowaną przez”", () => {
    expect(representationPl("Jan Kowalski", "Prezes Zarządu", "m")).toBe(
      "Pana Jana Kowalskiego – Prezesa Zarządu",
    );
    expect(representationPl("Anna Nowak", "Członek Zarządu", "k")).toBe(
      "Panią Annę Nowak – Członka Zarządu",
    );
  });

  it("bez osoby nie zgaduje frazy", () => {
    expect(representationPl("", "Prezes Zarządu", "m")).toBe("");
  });
});

describe("seatLocativePl", () => {
  it("zna odmianę dużych miast", () => {
    expect(seatLocativePl("Warszawa")).toEqual({
      phrase: "w Warszawie",
      known: true,
    });
    expect(seatLocativePl("Wrocław").phrase).toBe("we Wrocławiu");
  });

  it("nieznaną miejscowość oznacza do sprawdzenia", () => {
    expect(seatLocativePl("Kobyłka")).toEqual({
      phrase: "w Kobyłka",
      known: false,
    });
  });
});

describe("skład zarządu z KRS", () => {
  const people = [
    { name: null, function: "Prezes Zarządu" },
    { name: null, function: "Członek Zarządu" },
    { name: null, function: "Członek Zarządu" },
  ];

  it("podsumowuje funkcje, gdy nazwiska są zamaskowane", () => {
    expect(boardSummary(people)).toBe("Prezes Zarządu, Członek Zarządu ×2");
    expect(boardFunctions(people)).toEqual([
      "Prezes Zarządu",
      "Członek Zarządu",
    ]);
  });

  it("pokazuje osobę, gdy rejestr ją podał", () => {
    expect(
      boardSummary([{ name: "Jan Kowalski", function: "Prezes Zarządu" }]),
    ).toBe("Jan Kowalski (Prezes Zarządu)");
  });
});

describe("companyVariantMissing", () => {
  it("wymienia wszystkie brakujące dane spółki", () => {
    expect(
      companyVariantMissing({
        krs: "",
        seatLocative: "",
        registryCourt: "",
        shareCapital: "",
        representativeName: "",
        representativeFunction: "",
        representation: "",
      }),
    ).toHaveLength(7);
  });
});
