import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { rackStats, unitHost } from "../RackScene";
import { renderScene } from "./sceneTestUtils";

describe("scena Szafa serwerowa", () => {
  it("statystyki szafy z liczby włączonych modułów", () => {
    expect(rackStats(0, 5)).toEqual({ temp: "19°C · 0 W", uptime: "—", services: 0, alerts: 5 });
    expect(rackStats(2, 5)).toEqual({ temp: "21°C · 360 W", uptime: "99,92 %", services: 14, alerts: 3 });
    expect(unitHost(0)).toBe("srv-01");
  });

  it("włączony moduł startuje, alerty maleją, wynik rośnie", () => {
    const s = renderScene("szafa");
    const unit = s.full().getByRole("button", { name: /^PostgreSQL/ });
    expect(unit).toHaveTextContent("srv-03 · PostgreSQL");
    fireEvent.click(unit);
    expect(unit).toHaveAttribute("aria-pressed", "true");
    expect(unit.querySelector(".kr-rack-boot")).not.toBeNull();
    expect(s.full().getByText("20°C · 180 W")).toBeInTheDocument();
    expect(s.container.querySelector(".kr-rack-alert")).toHaveTextContent("4");
    expect(s.score().getByText("Serwery online")).toBeInTheDocument();
    expect(s.compact().getByText("RACK A-07 · 1 z 5 online")).toBeInTheDocument();
  });
});
