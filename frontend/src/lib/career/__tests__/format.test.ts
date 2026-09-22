import { describe, expect, it } from "vitest";

import {
  aboutParagraphs,
  genitiveName,
  instrumentalName,
  jobHandle,
  paramRows,
  paramsSummary,
  recruiterLogin,
  requirementHandle,
  splitTitle,
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
});

describe("teksty", () => {
  it("dzieli tytuł na dwie linie z kropką", () => {
    expect(splitTitle("Senior Java Developer")).toEqual({ first: "Senior Java", second: "Developer." });
    expect(splitTitle("DevOps")).toEqual({ first: "", second: "DevOps." });
    expect(splitTitle("Kto?")).toEqual({ first: "", second: "Kto?" });
  });

  it("handle z tytułu, bez polskich znaków", () => {
    expect(jobHandle({ slug: "x-ab12", title: "Analityk biznesowy — Łódź" })).toBe(
      "analityk-biznesowy-lodz",
    );
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
    expect(genitiveName("Tomasz")).toBe("Tomasza");
    expect(recruiterLogin("Łucja")).toBe("lucja@dynaminds");
  });
});
