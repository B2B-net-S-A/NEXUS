import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { floorSpeed, horizonHud } from "../HorizonScene";
import { renderScene } from "./sceneTestUtils";

describe("scena Horyzont", () => {
  it("wynik, poziom i szybkość siatki rosną z power-upami", () => {
    expect(horizonHud(0, 5)).toEqual({ score: "0000", level: "0/5" });
    expect(horizonHud(3, 5)).toEqual({ score: "0900", level: "3/5" });
    expect(floorSpeed(0)).toBe(2.6);
    expect(floorSpeed(5)).toBe(0.6);
  });

  it("zebrany kartridż zostaje przyciskiem (fokus nie ginie) i trafia do ekwipunku", () => {
    const s = renderScene("horyzont");
    const cart = s.full().getByRole("button", { name: /^Kafka/ });
    cart.focus();
    fireEvent.click(cart);
    expect(cart).toHaveAttribute("aria-pressed", "true");
    expect(cart).toHaveTextContent("ZEBRANE ✓");
    expect(document.activeElement).toBe(cart);
    expect(s.full().getByText("+ Kafka")).toBeInTheDocument();
    expect(s.full().getByText("WYNIK 0300")).toBeInTheDocument();
    expect(s.score().getByText("Power-upy")).toBeInTheDocument();
    fireEvent.click(cart);
    expect(s.full().getByText("pusto — kliknij kartridż")).toBeInTheDocument();
  });
});
