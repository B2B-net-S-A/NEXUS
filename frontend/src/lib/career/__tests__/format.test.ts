import { describe, expect, it } from "vitest";

import {
  aboutParagraphs,
  genitiveName,
  instrumentalName,
  paramRows,
  paramsSummary,
  requirementHandle,
} from "@/lib/career/format";

const params = {
  city: "Warszawa",
  remote_policy: "hybrid" as const,
  onsite_days_per_week: 2,
  seniority: "Senior",
  contract: "B2B",
  start: "10.2026",
  duration: "12+ mies.",
};

describe("paramRows", () => {
  it("składa wiersze jak w makiecie", () => {
    expect(paramRows(params).map((r) => `${r.label}=[${r.value}]`)).toEqual([
      "lokalizacja=[warszawa]",
      "tryb=[hybryda · 2 dni]",
      "poziom=[senior]",
      "umowa=[b2b]",
      "start=[10.2026 · 12+ mies.]",
    ]);
  });

  it("pomija puste wartości zamiast pokazywać puste nawiasy", () => {
    const rows = paramRows({
      city: null,
      remote_policy: "remote",
      onsite_days_per_week: 3,
      seniority: " ",
      contract: null,
      start: null,
      duration: null,
    });
    expect(rows).toEqual([{ key: "mode", label: "tryb", value: "zdalnie" }]);
    expect(paramRows(null)).toEqual([]);
  });

  it("paramsSummary do grafiki OG", () => {
    expect(paramsSummary(params)).toBe("warszawa · hybryda · b2b · senior");
  });

  it("sekcja parametrów ukryta — API oddaje puste pola, OG i opis meta ich nie mają", () => {
    // Runda 8: wyłączona sekcja „parametry” zeruje wszystko poza stałą umową.
    const hidden = {
      city: null,
      remote_policy: null,
      onsite_days_per_week: null,
      seniority: null,
      contract: "B2B",
      start: null,
      duration: null,
    };
    expect(paramsSummary(hidden)).toBe("b2b");
    expect(paramRows(hidden).map((r) => r.key)).toEqual(["contract"]);
  });
});

describe("teksty", () => {
  it("handle wymagania bez polskich znaków", () => {
    expect(requirementHandle("Java 17+ i Spring Boot")).toBe("java_17+_i_spring_boot");
  });

  it("akapity z podwójnej nowej linii", () => {
    expect(aboutParagraphs("a\n\n b \n\n\nc")).toEqual(["a", "b", "c"]);
    expect(aboutParagraphs(null)).toEqual([]);
  });

  it("odmiana imion w najczęstszych przypadkach", () => {
    expect(instrumentalName("Marta")).toBe("Martą");
    expect(instrumentalName("Tomasz")).toBe("Tomaszem");
    expect(instrumentalName("Marek")).toBe("Markiem");
    expect(genitiveName("Marta")).toBe("Marty");
    expect(genitiveName("Olga")).toBe("Olgi");
    expect(genitiveName("Kasia")).toBe("Kasi");
    expect(genitiveName("Maja")).toBe("Mai");
    // „Zostaw CV u Oli” (strona rekrutera, etap 6): po „l” końcówka „-i”.
    expect(genitiveName("Ola")).toBe("Oli");
    expect(genitiveName("Ela")).toBe("Eli");
    expect(genitiveName("Tomasz")).toBe("Tomasza");
  });
});
