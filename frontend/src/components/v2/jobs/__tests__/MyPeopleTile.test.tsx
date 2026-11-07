import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { MyPeopleTileView } from "../MyPeopleTile";

describe("MyPeopleTileView", () => {
  it("opens the My People panel from the board's sources strip", () => {
    const onOpen = vi.fn();
    render(<MyPeopleTileView onOpen={onOpen} />);
    fireEvent.click(screen.getByTestId("source-tile-my-people"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button").textContent).toContain("Moi ludzie");
  });
});
