import { describe, expect, it } from "vitest";

import type { CareerBoardJob } from "@/lib/career/api";
import {
  NO_FILTERS,
  boardTagLine,
  categoryCounts,
  filterBoard,
  openCountLabel,
} from "@/lib/career/board";

const job = (over: Partial<CareerBoardJob>): CareerBoardJob => ({
  slug: "x",
  title: "Developer",
  subtitle: null,
  city: null,
  remote_policy: null,
  category: null,
  theme: "terminal",
  recruiter_first_name: "Marta",
  ...over,
});

const JOBS = [
  job({ slug: "a", title: "Senior Java Developer", city: "Kraków", remote_policy: "hybrid", category: "development" }),
  job({ slug: "b", title: "Tester automatyzujący", subtitle: "Kafka i API", remote_policy: "remote", category: "qa" }),
  job({ slug: "c", title: "DevOps Engineer", city: "Łódź", remote_policy: "onsite", category: "infra" }),
  job({ slug: "d", title: "Analityk", remote_policy: null, category: null }),
];

const slugs = (jobs: CareerBoardJob[]) => jobs.map((j) => j.slug);

describe("filterBoard", () => {
  it("bez filtrów zwraca wszystko w kolejności z API", () => {
    expect(slugs(filterBoard(JOBS, NO_FILTERS))).toEqual(["a", "b", "c", "d"]);
  });

  it("szuka bez polskich znaków i wielkości liter, każde słowo musi wystąpić", () => {
    expect(slugs(filterBoard(JOBS, { ...NO_FILTERS, query: "java krakow" }))).toEqual(["a"]);
    expect(slugs(filterBoard(JOBS, { ...NO_FILTERS, query: "lodz" }))).toEqual(["c"]);
    expect(slugs(filterBoard(JOBS, { ...NO_FILTERS, query: "kafka," }))).toEqual(["b"]);
    expect(slugs(filterBoard(JOBS, { ...NO_FILTERS, query: "java, kafka" }))).toEqual([]);
  });

  it("szuka też po wymaganiach z karty (etap 7), a karta bez nich nie psuje szukania", () => {
    const withSkills = [
      job({ slug: "k", title: "Backend Developer", must: ["Kafka", "Spring Boot"], nice: ["Kubernetes"] }),
      job({ slug: "n", title: "Backend Developer" }),
    ];
    expect(slugs(filterBoard(withSkills, { ...NO_FILTERS, query: "kafka" }))).toEqual(["k"]);
    expect(slugs(filterBoard(withSkills, { ...NO_FILTERS, query: "kubernetes backend" }))).toEqual(["k"]);
    expect(slugs(filterBoard(withSkills, { ...NO_FILTERS, query: "backend" }))).toEqual(["k", "n"]);
  });

  it("tryb pracy: kilka naraz to „lub”, rekrutacja bez trybu wypada przy filtrze", () => {
    expect(slugs(filterBoard(JOBS, { ...NO_FILTERS, modes: ["remote", "onsite"] }))).toEqual(["b", "c"]);
  });

  it("kategoria", () => {
    expect(slugs(filterBoard(JOBS, { ...NO_FILTERS, category: "qa" }))).toEqual(["b"]);
  });
});

describe("categoryCounts", () => {
  it("liczy po szukaniu i trybie, ale bez samej kategorii", () => {
    const counts = categoryCounts(JOBS, { category: "qa", query: "", modes: ["remote", "hybrid"] });
    expect(counts).toEqual({ all: 2, development: 1, infra: 0, qa: 1, management: 0 });
  });
});

describe("openCountLabel", () => {
  it.each([
    [1, "1 otwarta"],
    [2, "2 otwarte"],
    [4, "4 otwarte"],
    [5, "5 otwartych"],
    [12, "12 otwartych"],
    [14, "14 otwartych"],
    [22, "22 otwarte"],
    [24, "24 otwarte"],
    [25, "25 otwartych"],
    [0, "0 otwartych"],
  ])("%i → %s", (n, label) => {
    expect(openCountLabel(n)).toBe(label);
  });
});

describe("boardTagLine", () => {
  it("zdalnie bez miasta, hybryda z miastem, brak trybu = samo miasto", () => {
    expect(boardTagLine({ city: "Warszawa", remote_policy: "remote" })).toBe("Zdalnie");
    expect(boardTagLine({ city: "Kraków", remote_policy: "hybrid" })).toBe("Kraków · Hybryda");
    expect(boardTagLine({ city: "Gdańsk", remote_policy: null })).toBe("Gdańsk");
    expect(boardTagLine({ city: null, remote_policy: null })).toBe("");
  });
});
