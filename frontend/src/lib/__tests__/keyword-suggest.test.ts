import { describe, expect, it } from "vitest";

import { buildSuggestionOptions, classificationRows, foldKeyword } from "@/lib/keyword-suggest";

const response = {
  items: [
    { label: "Java", kind: "skill" as const, insert: "Java", count: 4120 },
    { label: "JavaScript", kind: "skill" as const, insert: "JavaScript", alias: "js", count: 5310 },
    { label: "java developer", kind: "title" as const, insert: "java developer", count: 210 },
  ],
  wildcard: { label: "jav*", kind: "prefix" as const, insert: "jav*", count: 9100 },
};

describe("keyword-suggest", () => {
  it("kolejność źródeł: rekrutacja → ostatnio używane → baza → wzorzec → dokładnie", () => {
    const options = buildSuggestionOptions({
      query: "jav",
      existing: [],
      context: [{ label: "Java EE", note: "must-have" }],
      recent: ["Javalin", "Kafka"],
      response,
    });
    expect(options.map((o) => [o.group, o.insert])).toEqual([
      ["context", "Java EE"],
      ["recent", "Javalin"],
      ["base", "Java"],
      ["base", "JavaScript"],
      ["base", "java developer"],
      ["pattern", "jav*"],
      ["pattern", "jav"],
    ]);
    expect(options[2]).toMatchObject({ hit: "Jav", rest: "a", count: 4120 });
  });

  it("słowa już w polu nie wracają, bez polskich znaków i wielkości liter", () => {
    const options = buildSuggestionOptions({ query: "jav", existing: ["JAVA"], response });
    expect(options.some((o) => o.insert === "Java")).toBe(false);
    expect(foldKeyword("  Zarządzanie   Łańcuchem ")).toBe("zarzadzanie lancuchem");
  });

  it("alias pokazuje się jako wyjaśnienie, gdy nazwa nie zaczyna się od wpisanego tekstu", () => {
    const options = buildSuggestionOptions({ query: "js", existing: [], response });
    const js = options.find((o) => o.insert === "JavaScript");
    expect(js?.note).toBe("(też: js)");
  });

  it("słowo z pełnej nazwy pokazuje tę nazwę jako wyjaśnienie (Kafka — Apache Kafka)", () => {
    // Serwer wstawia samo „Kafka”, bo fraza „Apache Kafka” zawęża wynik
    // (decyzja 25.09.2026) — pełną nazwę widać obok, choć słowo podświetlone.
    const options = buildSuggestionOptions({
      query: "kafka",
      existing: [],
      response: {
        items: [
          {
            label: "Kafka",
            kind: "skill" as const,
            insert: "Kafka",
            alias: "Apache Kafka",
            count: 4569,
          },
        ],
        wildcard: null,
      },
    });
    expect(options[0]).toMatchObject({
      insert: "Kafka",
      hit: "Kafka",
      note: "(też: Apache Kafka)",
      count: 4569,
    });
    // Alias, który nie zawiera nazwy, dalej milczy przy podświetleniu.
    const js = buildSuggestionOptions({ query: "jav", existing: [], response }).find(
      (o) => o.insert === "JavaScript",
    );
    expect(js?.note).toBe("");
  });

  it("koszyki umiejętności: bez stanowisk i wzorców", () => {
    const options = buildSuggestionOptions({ query: "jav", existing: [], response, skillsOnly: true });
    expect(options.map((o) => o.insert)).toEqual(["Java", "JavaScript", "jav"]);
  });

  it("pusty tekst: tylko rekrutacja i ostatnio używane", () => {
    const options = buildSuggestionOptions({
      query: "",
      existing: [],
      context: [{ label: "Kafka" }],
      recent: ["Spring Boot"],
      response,
    });
    expect(options.map((o) => o.insert)).toEqual(["Kafka", "Spring Boot"]);
  });

  it("umiejętność z wariantami ma drugą pozycję „z wariantami” (decyzja: przycisk, nie automat)", () => {
    const options = buildSuggestionOptions({
      query: "spring",
      existing: ["springboot"],
      response: {
        items: [
          {
            label: "Spring Boot",
            kind: "skill",
            insert: "Spring Boot",
            count: 4812,
            variants: ["Springboot", "spring-boot"],
          },
        ],
        wildcard: null,
      },
    });
    expect(options.map((o) => [o.kindLabel, o.insert, o.variants ?? null])).toEqual([
      ["Technologia", "Spring Boot", null],
      // Wariant, który już jest w polu, odpada.
      ["Z wariantami", "Spring Boot", ["spring-boot"]],
      ["Słowo", "spring", null],
    ]);
    expect(options[1].rest).toBe("Spring Boot + spring-boot");
  });

  it("słowo spoza słownika technologii (term) też ma pozycję „z wariantami”", () => {
    // „bankowość” to nie technologia — serwer podaje odpowiedniki ze słownika
    // (26.09.2026: „banking” znajduje 7 657 osób, których „bankowość” nie widzi).
    const options = buildSuggestionOptions({
      query: "bankowo",
      existing: [],
      response: {
        items: [
          {
            label: "bankowość",
            kind: "term",
            insert: "bankowość",
            count: 832,
            variants: ["bankow*", "banking"],
          },
        ],
        wildcard: { label: "bankowo*", kind: "prefix", insert: "bankowo*", count: 900 },
      },
    });
    expect(options.map((o) => [o.kindLabel, o.insert, o.variants ?? null])).toEqual([
      ["Pojęcie", "bankowość", null],
      ["Z wariantami", "bankowość", ["bankow*", "banking"]],
      ["Początek słowa", "bankowo*", null],
      ["Słowo", "bankowo", null],
    ]);
    expect(options[1].rest).toBe("bankowość + bankow*, banking");
  });

  it("pole tylko umiejętności nie pokazuje pojęć ani ich wariantów", () => {
    const options = buildSuggestionOptions({
      query: "bankowo",
      existing: [],
      skillsOnly: true,
      response: {
        items: [
          { label: "bankowość", kind: "term", insert: "bankowość", variants: ["banking"] },
        ],
        wildcard: null,
      },
    });
    expect(options.some((o) => o.insert === "bankowość")).toBe(false);
  });
});

describe("classificationRows (runda 6 audytu)", () => {
  it("bierze gotowe wiersze z serwera — alias zostaje wariantem", () => {
    expect(
      classificationRows({
        skills: ["Apache Kafka", "PostgreSQL"],
        as_requirements: true,
        rows: [["Kafka"], ["postgres", "PostgreSQL"]],
      }),
    ).toEqual([["Kafka"], ["postgres", "PostgreSQL"]]);
  });

  it("przy starszym backendzie robi jeden wiersz na nazwę", () => {
    expect(classificationRows({ skills: ["Java"], as_requirements: true })).toEqual([["Java"]]);
  });
});
