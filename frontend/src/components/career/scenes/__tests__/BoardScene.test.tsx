import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BOARD_STEP, BOARD_TOP, notePosition } from "../BoardScene";
import { renderScene } from "./sceneTestUtils";

describe("scena Tablica warsztatowa", () => {
  it("karteczka idzie do „Mam to” na kolejne wolne miejsce, cofnięta wraca na swoje", () => {
    expect(notePosition(3, [])).toEqual({ column: "todo", top: BOARD_TOP + 3 * BOARD_STEP });
    expect(notePosition(3, [1, 3])).toEqual({ column: "done", top: BOARD_TOP + BOARD_STEP });
  });

  it("klik przenosi karteczkę, licznik kolumn i wynik się zgadzają", () => {
    const s = renderScene("tablica");
    const note = s.full().getByRole("button", { name: /^PostgreSQL/ });
    expect(note.style.left).toBe("16px");
    fireEvent.click(note);
    expect(note).toHaveAttribute("aria-pressed", "true");
    expect(note.style.left).toBe("240px");
    expect(note.style.top).toBe(`${BOARD_TOP}px`);
    expect(note).toHaveTextContent("MUST · MAM");
    expect(s.full().getByText("MAM TO · 1")).toBeInTheDocument();
    expect(s.full().getByText("DO OMÓWIENIA · 4")).toBeInTheDocument();
    expect(s.score().getByText("W „Mam to”")).toBeInTheDocument();
    fireEvent.click(s.full().getByRole("button", { name: "Kubernetes (mile widziane)" }));
    expect(s.full().getByRole("button", { name: "Kubernetes (mile widziane)" })).toHaveTextContent(/^Kubernetes · mile widziane ?MAM$/);
    fireEvent.click(note);
    expect(note.style.left).toBe("16px");
    expect(s.score().getByText("1/5")).toBeInTheDocument();
  });
});
