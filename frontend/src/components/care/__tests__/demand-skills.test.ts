/**
 * „Technologie (z mapy działu — zaznacz)” (R4, 22.10.2026): od razu zaznaczone
 * są technologie, które padły w rolach sygnału popytu. Dane fikcyjne.
 */
import { describe, expect, it } from "vitest";

import { skillsMentionedIn } from "../demand-skills";

const MAP = [
  { id: 1, name: "Java 17" },
  { id: 2, name: "Kafka" },
  { id: 3, name: "Spring Boot" },
  { id: 4, name: "OpenShift" },
  { id: 5, name: "JavaScript" },
  { id: 6, name: ".NET" },
];

describe("skillsMentionedIn", () => {
  it("makieta: „Java Developer (Kafka)” zaznacza Java 17 i Kafka", () => {
    expect(skillsMentionedIn(["Java Developer (Kafka)"], MAP)).toEqual([1, 2]);
  });

  it("całe słowo, bez wielkości liter; „Java” nie wskazuje „JavaScript”", () => {
    expect(skillsMentionedIn(["java", "QA"], MAP)).toEqual([1]);
    expect(skillsMentionedIn(["spring boot developer", ".net"], MAP)).toEqual([3, 6]);
    expect(skillsMentionedIn([], MAP)).toEqual([]);
  });
});
