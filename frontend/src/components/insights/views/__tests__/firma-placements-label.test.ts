import { describe, expect, it } from "vitest";
import { placementsDeltaLabel } from "../FirmaView";

// Runda 6 audytu: placementy okresu w toku porównujemy z tym samym odcinkiem
// poprzedniego okresu — podpis nie może obiecywać pełnego poprzedniego okresu.
describe("placementsDeltaLabel", () => {
  it("okres w toku mówi o tym samym odcinku", () => {
    expect(placementsDeltaLabel("quarter", true)).toBe(
      "wobec tego samego odcinka poprzedniego kwartału",
    );
    expect(placementsDeltaLabel("month", true)).toBe(
      "wobec tego samego odcinka poprzedniego miesiąca",
    );
  });

  it("okres zamknięty albo stara odpowiedź — cały poprzedni okres", () => {
    expect(placementsDeltaLabel("month", false)).toBe(
      "wobec poprzedniego miesiąca",
    );
    expect(placementsDeltaLabel("quarter", undefined)).toBe(
      "wobec poprzedniego kwartału",
    );
    expect(placementsDeltaLabel("nieznany", true)).toBe(
      "wobec tego samego odcinka poprzedniego okresu",
    );
  });
});
