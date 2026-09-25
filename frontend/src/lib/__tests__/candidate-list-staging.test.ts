import { describe, expect, it } from "vitest";

import {
  carryImmediate,
  filterChangeCount,
  isBareListQuery,
  listSearchLabel,
  resolveInitialListParams,
} from "@/lib/candidate-list-staging";
import { DEFAULT_FILTERS, type CandidateFilters } from "@/lib/url-filters";

const f = (patch: Partial<CandidateFilters>): CandidateFilters => ({ ...DEFAULT_FILTERS, ...patch });

describe("candidate-list-staging", () => {
  it("liczy każde słowo i wartość osobno, bez strony i sortowania", () => {
    const applied = f({ qAll: ["Kafka"], qNone: ["junior"] });
    expect(filterChangeCount(applied, applied)).toBe(0);
    expect(filterChangeCount(f({ ...applied, page: 3, sort: "name" }), applied)).toBe(0);
    expect(filterChangeCount(f({ qAll: ["Kafka", "Java"], qNone: ["junior"] }), applied)).toBe(1);
    expect(filterChangeCount(f({ qAll: ["Java"] }), applied)).toBe(3);
    expect(filterChangeCount(f({ ...applied, rateMax: 160 }), applied)).toBe(1);
  });

  it("sortowanie przechodzi od razu, reszta czeka na „Szukaj”", () => {
    const applied = f({ qAll: ["Kafka"], page: 2 });
    const draft = f({ qAll: ["Kafka", "Java"], page: 1, sort: "name" });
    expect(carryImmediate(applied, draft)).toMatchObject({ qAll: ["Kafka"], sort: "name", page: 1 });
  });

  it("strona przechodzi od razu przy tych samych kryteriach", () => {
    const applied = f({ qAll: ["Kafka"], page: 1 });
    expect(carryImmediate(applied, f({ qAll: ["Kafka"], page: 4 }))).toMatchObject({ page: 4 });
    const pending = f({ qAll: ["Kafka", "Java"], page: 4 });
    expect(carryImmediate(applied, pending)).toBe(applied);
  });

  it("goły adres bierze wyszukiwanie z pamięci karty", () => {
    expect(isBareListQuery(new URLSearchParams(""))).toBe(true);
    expect(isBareListQuery(new URLSearchParams("mode=list"))).toBe(true);
    expect(isBareListQuery(new URLSearchParams("q_all=Java"))).toBe(false);
    expect(isBareListQuery(new URLSearchParams("ss=4"))).toBe(false);
    const memory = { query: "q_all=Java&page=3", scrollTop: 300, lastOpenedId: 9, savedAt: 1 };
    const restored = resolveInitialListParams(new URLSearchParams(""), memory);
    expect(restored.restored).toBe(true);
    expect(restored.params.get("page")).toBe("3");
    const explicit = resolveInitialListParams(new URLSearchParams("q_all=Kafka"), memory);
    expect(explicit.restored).toBe(false);
    expect(explicit.params.get("q_all")).toBe("Kafka");
    expect(resolveInitialListParams(new URLSearchParams(""), null).restored).toBe(false);
  });

  it("opis do menu „Ostatnie wyszukiwania”", () => {
    expect(
      listSearchLabel(f({ qAll: ["Java", "Kafka"], qAny: [["Spring", "Quarkus"]], qNone: ["junior"], rateMax: 160 })),
    ).toBe("Java + Kafka · (Spring lub Quarkus) · bez junior · do 160 zł/h");
    expect(listSearchLabel(DEFAULT_FILTERS)).toBe("Wszyscy kandydaci");
    expect(listSearchLabel(f({ q: "tester", status: ["active"] }))).toBe("„tester” · +1 filtr");
  });
});
