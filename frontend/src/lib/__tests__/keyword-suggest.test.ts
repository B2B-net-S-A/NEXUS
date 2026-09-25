import { describe, expect, it } from "vitest";

import { buildSuggestionOptions, foldKeyword } from "@/lib/keyword-suggest";

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
});
