import { describe, expect, it } from "vitest";

import { processSteps, sceneItems } from "../requirementItems";

describe("pozycje wymagań i kroki procesu", () => {
  it("pozycje: najpierw wymagania, potem mile widziane, najwyżej pięć", () => {
    const items = sceneItems(
      [
        { name: "Java", note: " 5 lat " },
        { name: "  ", note: "pusta nazwa odpada" },
        { name: "Kafka", note: null },
      ],
      ["AWS", "", "Docker", "Go", "Rust"],
    );
    expect(items.map((i) => [i.name, i.kind])).toEqual([
      ["Java", "must"],
      ["Kafka", "must"],
      ["AWS", "nice"],
      ["Docker", "nice"],
      ["Go", "nice"],
    ]);
    expect(items[0].note).toBe("5 lat");
    expect(new Set(items.map((i) => i.key)).size).toBe(5);
  });

  it("więcej niż pięć wymagań — podgląd bierze pierwsze pięć", () => {
    const must = Array.from({ length: 7 }, (_, i) => ({ name: `W${i}`, note: null }));
    const items = sceneItems(must, ["AWS"]);
    expect(items).toHaveLength(5);
    expect(items.every((i) => i.kind === "must")).toBe(true);
  });

  it("brak wymagań i mile widzianych = pusta lista", () => {
    expect(sceneItems([], [])).toEqual([]);
  });

  it("cztery kroki procesu z imieniem rekrutera i umową", () => {
    expect(processSteps("Marta", "B2B").map((s) => s.title)).toEqual([
      "rozmowa z Martą",
      "weryfikacja techniczna",
      "spotkanie z zespołem",
      "decyzja i start",
    ]);
    expect(processSteps("Marta", "B2B")[3].note).toBe("umowa b2b");
    expect(processSteps("Marta", null)[3].note).toBe("umowa i wdrożenie");
  });
});
