import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readiness, RING_LENGTH } from "../PlanScene";
import { renderScene } from "./sceneTestUtils";

describe("scena Plan", () => {
  it("gotowość w procentach i łuk pierścienia", () => {
    expect(readiness(0, 5)).toEqual({ pct: 0, arc: 0 });
    expect(readiness(2, 5)).toEqual({ pct: 40, arc: Math.round(RING_LENGTH * 0.4) });
    expect(readiness(1, 3).pct).toBe(33);
    expect(readiness(0, 0).pct).toBe(0);
  });

  it("etap harmonogramu pokazuje opis, zakres podnosi gotowość i wynik", () => {
    const s = renderScene("plan");
    const full = s.full();
    expect(full.getByText(/rozmowa z Martą/, { selector: ".kr-plan-call span" })).toBeInTheDocument();
    fireEvent.click(full.getByRole("button", { name: /04 decyzja i start/ }));
    expect(full.getByRole("button", { name: /04 decyzja i start/ })).toHaveAttribute("aria-pressed", "true");
    expect(full.getByText(/umowa b2b/)).toBeInTheDocument();
    fireEvent.click(full.getByRole("button", { name: /^Kafka/ }));
    fireEvent.click(full.getByRole("button", { name: /^English/ }));
    expect(full.getByText("40%")).toBeInTheDocument();
    expect(s.score().getByText("Zakres pokryty")).toBeInTheDocument();
    expect(s.score().getByText("2/5")).toBeInTheDocument();
    expect(s.compact().getByText("ZAKRES — gotowość 40%")).toBeInTheDocument();
  });

  it("proces ukryty — bez harmonogramu, zakres działa", () => {
    const s = renderScene("plan", { process: false });
    expect(s.full().queryByText("ETAPY — KLIKNIJ, BY ZOBACZYĆ")).toBeNull();
    fireEvent.click(s.full().getByRole("button", { name: /^Kafka/ }));
    expect(s.score().getByText("1/5")).toBeInTheDocument();
  });
});
