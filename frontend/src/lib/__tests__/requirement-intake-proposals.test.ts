import { describe, expect, it } from "vitest";

import {
  addNiceRows,
  applyCriticalProposal,
  missingTechnologies,
  proposalRowKeys,
  type RequirementRowForm,
} from "../requirement-rows";

const ROWS: RequirementRowForm[] = [
  { key: "d", words: ["Dynamics 365", "D365"], level: "must" },
  { key: "c", words: ["C#", ".NET"], level: "must" },
  { key: "k", words: ["Apache Kafka"], level: "nice" },
];

describe("propozycje z odczytu maila (M1, M2, 07.11.2026)", () => {
  it("„Zatwierdź krytyczne” oznacza wiersze po pierwszym słowie", () => {
    const out = applyCriticalProposal(ROWS, [{ label: "dynamics 365", reason: "minimum 5 lat" }]);
    expect(out.map((r) => r.level)).toEqual(["critical", "must", "nice"]);
  });

  it("propozycja bez pasującego wiersza „musi mieć” nic nie zmienia", () => {
    expect(proposalRowKeys(ROWS, [{ label: "Apache Kafka", reason: "" }])).toEqual([]);
    expect(applyCriticalProposal(ROWS, [{ label: "Java", reason: "" }])).toEqual(ROWS);
  });

  it("technologie z maila bez tych, które już są w wierszach", () => {
    expect(missingTechnologies(ROWS, ["Dataverse", "d365", "Jenkins", "jenkins"])).toEqual([
      "Dataverse",
      "Jenkins",
    ]);
  });

  it("„+ Technologia” dokłada osobne wiersze „mile widziane”", () => {
    const out = addNiceRows(ROWS, ["Dataverse", "Apache Kafka"]);
    expect(out.slice(3).map((r) => [r.words, r.level])).toEqual([[["Dataverse"], "nice"]]);
  });
});
