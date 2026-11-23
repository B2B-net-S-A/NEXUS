import { describe, expect, it } from "vitest";

import type { CareerBoardJob } from "@/lib/career/api";
import { NO_FILTERS } from "@/lib/career/board";
import {
  bigWord,
  boardCardFor,
  checklistSummary,
  facetCounts,
  jobCities,
  wordEm,
  highlightSkill,
  nextBatch,
  openNowLabel,
  partialMatch,
  pluralForm,
  similarJobs,
} from "@/lib/career/site";

const job = (slug: string, over: Partial<CareerBoardJob> = {}): CareerBoardJob => ({
  slug,
  title: slug,
  subtitle: null,
  city: null,
  remote_policy: "remote",
  category: "development",
  theme: "grafit",
  recruiter_first_name: "Marta",
  must: [],
  nice: [],
  ...over,
});

describe("wielkie słowo nad tytułem oferty", () => {
  it("bierze pierwszą krótką umiejętność z tablicy", () => {
    expect(bigWord(job("a", { must: ["Doświadczenie z Java Spring Boot", "Python", "FastAPI"] }))).toBe("Python");
    expect(bigWord(job("a", { must: ["Power Platform", "Power Apps"] }))).toBe("Power Platform");
  });

  it("bez krótkiej umiejętności — brak słowa, także bez słowa kategorii (bez zmyślania)", () => {
    expect(bigWord(job("a", { must: ["strategia rozwoju rozwiązań AI w firmie"], category: "management" }))).toBeNull();
    expect(bigWord(null)).toBeNull();
  });
});

describe("pogrubienie umiejętności w zdaniu wymagania", () => {
  it("najdłuższa pasująca nazwa, bez polskich znaków i wielkości liter", () => {
    const h = highlightSkill("Doświadczenie w pracy z REST API w Pythonie", ["API", "rest api"]);
    expect(h).toEqual({ before: "Doświadczenie w pracy z ", key: "REST API", after: " w Pythonie" });
    expect(highlightSkill("Znajomość narzędzi Łódzkich", ["lodzkich"]).key).toBe("Łódzkich");
  });

  it("tylko całe słowa: „AI” nie świeci w środku wyrazu", () => {
    expect(highlightSkill("Szczegółowa analiza wymagań", ["AI"]).key).toBeNull();
    expect(highlightSkill("Strategia rozwiązań AI", ["AI"]).key).toBe("AI");
  });

  it("bez trafienia zdanie zostaje całe", () => {
    expect(highlightSkill("Komunikatywność", ["Java"])).toEqual({ before: "Komunikatywność", key: null, after: "" });
  });
});

describe("karta tablicy i podobne oferty", () => {
  const board = [
    job("a", { category: "qa" }),
    job("b", { category: "development" }),
    job("c", { category: "qa" }),
    job("d", { category: "infra" }),
  ];

  it("kartę znajduje po linku z tablicy albo po slugu strony", () => {
    expect(boardCardFor(board, [null, "C"])?.slug).toBe("c");
    expect(boardCardFor(board, ["x"])).toBeNull();
  });

  it("najpierw ta sama kategoria, bez tej rekrutacji, najwyżej trzy", () => {
    expect(similarJobs(board, ["a"], "qa").map((j) => j.slug)).toEqual(["c", "b", "d"]);
    expect(similarJobs(board, ["a", "b"], null, 2).map((j) => j.slug)).toEqual(["c", "d"]);
  });
});

describe("hasło bez trafień", () => {
  const board = [job("krk", { title: "Tester", city: "Kraków", remote_policy: "hybrid" }), job("waw", { city: "Warszawa" })];

  it("podpowiada słowo, które samo coś znajduje („COBOL Kraków” → Kraków)", () => {
    const hit = partialMatch(board, { ...NO_FILTERS, query: "COBOL Kraków" });
    expect(hit?.word).toBe("Kraków");
    expect(hit?.jobs.map((j) => j.slug)).toEqual(["krk"]);
  });

  it("jedno słowo albo nic nie pasuje — brak podpowiedzi", () => {
    expect(partialMatch(board, { ...NO_FILTERS, query: "COBOL" })).toBeNull();
    expect(partialMatch(board, { ...NO_FILTERS, query: "COBOL Fortran" })).toBeNull();
  });
});

describe("odmiana i liczniki", () => {
  it("liczebniki po polsku", () => {
    expect([1, 2, 4, 5, 12, 22, 25].map(pluralForm)).toEqual(["one", "few", "few", "many", "many", "few", "many"]);
    expect(openNowLabel(1)).toBe("jest teraz 1 rekrutacja");
    expect(openNowLabel(3)).toBe("są teraz 3 rekrutacje");
    expect(openNowLabel(5)).toBe("jest teraz 5 rekrutacji");
  });

  it("podsumowanie listy „Co już masz?”", () => {
    expect(checklistSummary(5, 3)).toBe("5 wymaganych, 3 mile widziane");
    expect(checklistSummary(4, 0)).toBe("4 wymagane");
    expect(checklistSummary(1, 2)).toBe("1 wymagane, 2 mile widziane");
  });

  it("„Pokaż kolejne” dokłada pełną paczkę albo resztę", () => {
    expect(nextBatch(30, 12)).toBe(12);
    expect(nextBatch(5, 12)).toBe(5);
    expect(nextBatch(0, 12)).toBe(0);
  });
});

describe("zamiast kategorii: miasta", () => {
  it("rozpoznaje miasta w opisowym polu miejsca", () => {
    expect(jobCities({ city: "Priorytet Gdańsk, ewentualnie Warszawa" })).toEqual(["Warszawa", "Gdańsk"]);
    expect(jobCities({ city: "Gdańsk (preferowana)" })).toEqual(["Gdańsk"]);
    expect(jobCities({ city: "Trójmiasto" })).toEqual(["Gdańsk", "Gdynia", "Sopot"]);
    expect(jobCities({ city: "Cała Polska" })).toEqual([]);
    expect(jobCities({ city: null })).toEqual([]);
  });

  it("liczy miasta od najczęstszego; rekrutacja bez miasta nie liczy się nigdzie", () => {
    const list = [job("a", { city: "Warszawa, Gdańsk" }), job("b", { city: "Tylko Warszawa" }), job("c", { city: null })];
    expect(facetCounts(list).map((f) => [f.label, f.count])).toEqual([["Warszawa", 2], ["Gdańsk", 1]]);
  });

  it("szerokość słowa: wersaliki liczą się szerzej niż małe litery", () => {
    expect(wordEm("BPMN")).toBeGreaterThan(wordEm("bpmn"));
    expect(wordEm("AI")).toBeGreaterThanOrEqual(2.4);
  });
});
