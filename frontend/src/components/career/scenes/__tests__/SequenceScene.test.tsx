import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { activationHeight } from "../SequenceScene";
import { renderScene } from "./sceneTestUtils";

describe("scena Diagram sekwencji", () => {
  it("komunikat → 200 OK z notatką, pasek aktywacji rośnie", () => {
    const s = renderScene("sekwencja");
    const full = s.full();
    const msg = full.getByRole("button", { name: "Kafka — architektura zdarzeniowa" });
    expect(msg).toHaveTextContent("2: kafka()");
    expect(msg).toHaveTextContent("200 OK · architektura zdarzeniowa");
    fireEvent.click(msg);
    expect(msg).toHaveAttribute("aria-pressed", "true");
    expect(msg).toHaveAttribute("data-on");
    const act = s.container.querySelector(".kr-seq-act") as HTMLElement;
    expect(act.style.height).toBe(`${activationHeight(1)}px`);
    expect(s.score().getByText("Komunikaty obsłużone")).toBeInTheDocument();
    expect(s.score().getByText("1/5")).toBeInTheDocument();
  });

  it("komplet → „Pełne dopasowanie”, odznaczenie cofa wynik", () => {
    const s = renderScene("sekwencja");
    const buttons = s.full().getAllByRole("button");
    expect(buttons).toHaveLength(5);
    buttons.forEach((b) => fireEvent.click(b));
    expect(s.score().getByText("Pełne dopasowanie — czekamy na Ciebie.")).toBeInTheDocument();
    expect(s.score().getByRole("link", { name: "Aplikuj — masz 5 z 5" })).toBeInTheDocument();
    fireEvent.click(buttons[0]);
    expect(s.score().getByText("4/5")).toBeInTheDocument();
    expect(s.compact().getAllByRole("button")[0]).toHaveAttribute("aria-pressed", "false");
  });

  it("wymaganie bez notatki odpowiada swoją nazwą", () => {
    const s = renderScene("sekwencja");
    expect(s.full().getByRole("button", { name: "English" })).toHaveTextContent("200 OK · English");
  });
});
