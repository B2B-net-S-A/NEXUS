import { describe, expect, it } from "vitest";
import { goalReference, placementsGoalDelta } from "../MojMiesiacView";

// Audyt statystyk 15.10.2026: Delivery Lead nie ma miesięcznego celu
// placementów (jego cel to 30% hit ratio w kwartale), więc panel oddaje 0.
// Kafel pokazywał wtedy „cel: 0” i „Cel osiągnięty” także przy zerze
// placementów. Brak celu to sam wynik, nie cel zrobiony.
describe("placementsGoalDelta", () => {
  it("bez celu nie ocenia wyniku", () => {
    expect(placementsGoalDelta(0, 0)).toBeNull();
    expect(placementsGoalDelta(2, 0)).toBeNull();
  });

  it("z celem mówi, czy jest zrobiony albo ile brakuje", () => {
    expect(placementsGoalDelta(1, 1)).toEqual({ text: "Cel osiągnięty", tone: "good" });
    expect(placementsGoalDelta(0, 2)).toEqual({ text: "Brakuje 2", tone: "bad" });
  });
});

describe("goalReference", () => {
  it("cel zero albo brak celu to brak odniesienia", () => {
    expect(goalReference(0)).toBeNull();
    expect(goalReference(0, "%")).toBeNull();
  });

  it("cel dodatni to „cel: N”", () => {
    expect(goalReference(4)).toBe("cel: 4");
    expect(goalReference(75, "%")).toBe("cel: 75%");
  });
});
