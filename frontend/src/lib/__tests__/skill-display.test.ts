import { describe, expect, it } from "vitest";

import {
  displaySkills,
  skillDictionaryIndex,
  skillNameParts,
} from "@/lib/skill-display";

const dictionary = skillDictionaryIndex([
  { name: "Kafka", aliases: ["Apache Kafka"] },
  { name: "Spring Boot", aliases: ["springboot"] },
  { name: "Spring", aliases: ["Spring Framework"] },
  { name: "Java", aliases: [] },
]);

describe("skillNameParts", () => {
  it("splits compound names and drops the vendor prefix", () => {
    expect(skillNameParts("Clean Code / SOLID")).toEqual(["clean code", "solid"]);
    expect(skillNameParts("Clean Code i SOLID")).toEqual(["clean code", "solid"]);
    expect(skillNameParts("Apache Kafka")).toEqual(["kafka"]);
  });
});

describe("displaySkills", () => {
  it("merges dictionary variants and keeps the canonical name", () => {
    const out = displaySkills(
      [
        { name: "Kafka" },
        { name: "Apache Kafka", level: "mid", years: 3 },
      ],
      { dictionary },
    );
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      name: "Kafka",
      level: "mid",
      years: 3,
      variants: ["Kafka", "Apache Kafka"],
    });
  });

  it("merges compound names with the same parts without a dictionary", () => {
    const out = displaySkills([
      { name: "Clean Code i SOLID" },
      { name: "Clean Code / SOLID" },
      { name: "SOLID, Clean Code" },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].variants).toHaveLength(3);
  });

  it("keeps names whose parts point at different skills apart", () => {
    const out = displaySkills(
      [{ name: "Spring Boot" }, { name: "Spring Boot / Spring Framework" }],
      { dictionary },
    );
    expect(out.map((s) => s.name)).toEqual([
      "Spring Boot",
      "Spring Boot / Spring Framework",
    ]);
  });

  it("takes the highest level and the longest experience", () => {
    const out = displaySkills(
      [
        { name: "Java", level: "mid", years: 4 },
        { name: "java", level: "senior", years: 2 },
      ],
      { dictionary },
    );
    expect(out[0]).toMatchObject({ name: "Java", level: "senior", years: 4 });
  });

  it("sorts by level, then experience, then profile order", () => {
    const out = displaySkills([
      { name: "Docker" },
      { name: "Angular", level: "mid", years: 7 },
      { name: "Java", level: "senior", years: 11 },
      { name: "Git", level: "mid", years: 8 },
    ]);
    expect(out.map((s) => s.name)).toEqual(["Java", "Git", "Angular", "Docker"]);
  });

  it("marks screening-confirmed skills and adds ones missing from the CV", () => {
    const out = displaySkills([{ name: "Apache Kafka" }], {
      dictionary,
      confirmed: ["kafka", "RabbitMQ"],
    });
    expect(out.find((s) => s.name === "Kafka")?.confirmed).toBe(true);
    expect(out.find((s) => s.name === "RabbitMQ")).toMatchObject({ confirmed: true });
  });

  it("keeps C, C++ and C# apart without a dictionary", () => {
    const out = displaySkills([{ name: "C" }, { name: "C++" }, { name: "C#" }, { name: "c++" }]);
    expect(out.map((s) => s.name)).toEqual(["C", "C++", "C#"]);
    expect(out.find((s) => s.name === "C++")?.variants).toEqual(["C++", "c++"]);
  });

  it("ignores empty and non-text names", () => {
    expect(
      displaySkills([{ name: "" }, { name: null }, { name: "  " }] as never),
    ).toEqual([]);
  });
});
