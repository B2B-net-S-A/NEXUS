import { describe, expect, it } from "vitest";

import {
  addToRow,
  cleanRows,
  describeKeywordSearch,
  experienceRangeLabel,
  keywordHints,
  requirementRows,
  sanitizeKeyword,
  seniorityRange,
  splitAlternatives,
  splitWordInRow,
  withoutWord,
} from "@/lib/keyword-requirements";

describe("wiersze wymagań", () => {
  it("stare „wszystkie” to wiersze jednowyrazowe na początku, potem grupy", () => {
    expect(requirementRows(["Java", "Kafka"], [["Spring", "Quarkus"]])).toEqual([
      ["Java"],
      ["Kafka"],
      ["Spring", "Quarkus"],
    ]);
  });

  it("do zapytania idą wiersze bez pustych słów i pustych wierszy", () => {
    expect(cleanRows([["Java", " "], [], ["a|b"]])).toEqual([["Java"], ["a b"]]);
  });

  it("`|` w słowie zamienia się na spację (w adresie rozdziela słowa)", () => {
    expect(sanitizeKeyword("  React|Vue  ")).toBe("React Vue");
  });

  it("dołączanie do wiersza bez duplikatów (wielkość liter bez znaczenia)", () => {
    expect(addToRow([["Spring Boot"]], 0, ["spring boot", "Springboot", "x"])).toEqual([
      ["Spring Boot", "Springboot"],
    ]);
  });

  it("usunięcie ostatniego słowa usuwa wiersz", () => {
    expect(withoutWord([["Java"], ["Warszawa"]], 1, "Warszawa")).toEqual([["Java"]]);
    expect(withoutWord([["Java", "Kotlin"]], 0, "Kotlin")).toEqual([["Java"]]);
  });
});

describe("zdanie podsumowania", () => {
  it("wiersze łączy „i”, warianty „lub”, na końcu wykluczenia i zakres", () => {
    expect(
      describeKeywordSearch({
        rows: [["Java", "Kotlin"], ["Kafka"], []],
        exclude: ["junior"],
        scopeLabel: "cały profil",
      }),
    ).toBe(
      "Szukamy osób, które mają (Java lub Kotlin) i Kafka, bez słów: junior. Szukamy w: cały profil.",
    );
  });

  it("bez słów mówi, że decydują pozostałe filtry — nie „cała baza”", () => {
    expect(describeKeywordSearch({ rows: [[]], exclude: [], scopeLabel: "cały profil" })).toBe(
      "Brak słów kluczowych — o wynikach decydują pozostałe filtry.",
    );
  });

  it("same wykluczenia i bez zakresu (edytor Championa)", () => {
    expect(describeKeywordSearch({ rows: [], exclude: ["junior"], scopeLabel: null })).toBe(
      "Szukamy osób, bez słów: junior.",
    );
  });
});

describe("podpowiedzi przy pomyłkach", () => {
  it("staż zapisany słowem → zakres lat", () => {
    expect(seniorityRange("Senior")).toEqual({ min: 5, max: null });
    expect(seniorityRange("stażysta")).toEqual({ min: null, max: 1 });
    expect(seniorityRange("Java")).toBeNull();
    expect(experienceRangeLabel({ min: 5, max: null })).toBe("5+ lat");
    expect(experienceRangeLabel({ min: 2, max: 5 })).toBe("2–5 lat");
    expect(experienceRangeLabel({ min: null, max: 1 })).toBe("do 1 roku");
  });

  it("warianty w jednym słowie — ukośnik tylko ze spacjami", () => {
    expect(splitAlternatives("React / Vue")).toEqual(["React", "Vue"]);
    expect(splitAlternatives("React lub Vue")).toEqual(["React", "Vue"]);
    expect(splitAlternatives("Kafka OR RabbitMQ")).toEqual(["Kafka", "RabbitMQ"]);
    expect(splitAlternatives("CI/CD")).toBeNull();
    expect(splitAlternatives("PL/SQL")).toBeNull();
  });

  it("rozdzielenie zostawia inne słowa wiersza i nie dubluje", () => {
    expect(splitWordInRow([["Angular", "React / Vue", "vue"]], 0, "React / Vue", ["React", "Vue"])).toEqual([
      ["Angular", "React", "Vue"],
    ]);
  });

  it("zbiera podpowiedzi z numerem wiersza", () => {
    expect(keywordHints([["Java"], ["senior"], ["React / Vue"]])).toEqual([
      { kind: "seniority", row: 1, word: "senior", range: { min: 5, max: null } },
      { kind: "split", row: 2, word: "React / Vue", parts: ["React", "Vue"] },
    ]);
  });
});
