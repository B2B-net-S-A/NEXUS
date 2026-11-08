import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { cardScoreState, UnscoredRing } from "../kanban-shared";

// 13.10.2026 rekruter pytał Jarvisa: „Dlaczego nie zawsze przy nazwisku jest
// scoring AI?”. Karta bez wyniku pokazywała pustkę — teraz mówi „niepoliczone”.
describe("cardScoreState", () => {
  it("shows the score when there is one", () => {
    expect(cardScoreState(72, false, true)).toBe("score");
  });
  it("shows the placeholder while scores load", () => {
    expect(cardScoreState(null, true, false)).toBe("loading");
  });
  it("marks a card without a score once scores have loaded", () => {
    expect(cardScoreState(null, false, true)).toBe("unscored");
  });
  it("stays empty when scores never arrived (no access or failed query)", () => {
    expect(cardScoreState(null, false, false)).toBe("none");
  });
});

describe("UnscoredRing", () => {
  it("says the score is not counted yet instead of looking like zero", () => {
    render(
      <TooltipProvider>
        <UnscoredRing />
      </TooltipProvider>,
    );
    expect(screen.getByLabelText("Dopasowanie AI jeszcze niepoliczone")).toBeTruthy();
    expect(screen.getByText("?")).toBeTruthy();
  });
});
