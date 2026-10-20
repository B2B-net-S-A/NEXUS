import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RADAR_CENTER, radarReadout } from "../RadarScene";
import { renderScene } from "./sceneTestUtils";

describe("scena Radar", () => {
  it("azymut od północy zgodnie z zegarem, zasięg w % promienia", () => {
    const [cx, cy] = RADAR_CENTER;
    expect(radarReadout(cx, cy - 90)).toEqual({ az: 0, range: 50 });
    expect(radarReadout(cx + 180, cy)).toEqual({ az: 90, range: 100 });
    expect(radarReadout(cx, cy + 400).az).toBe(180);
    expect(radarReadout(cx - 10, cy).az).toBe(270);
    expect(radarReadout(cx, cy + 400).range).toBe(100);
  });

  it("klik namierza cel, dziennik pokazuje ostatnie trzy od najnowszego", () => {
    const s = renderScene("radar");
    const full = s.full();
    for (const name of [/^Java Spring Boot/, /^Kafka/, /^PostgreSQL/, /^English/]) {
      fireEvent.click(full.getByRole("button", { name }));
    }
    const lines = [...s.container.querySelectorAll(".kr-radar-log p")].map((p) => p.textContent);
    expect(lines.slice(1)).toEqual([
      "NAMIERZONO › English",
      "NAMIERZONO › PostgreSQL — schemat i zapytania",
      "NAMIERZONO › Kafka — architektura zdarzeniowa",
    ]);
    expect(full.getByRole("button", { name: /^English/ })).toHaveAttribute("aria-pressed", "true");
    expect(s.container.querySelectorAll(".kr-radar-lock")).toHaveLength(4);
    expect(s.score().getByText("Cele namierzone")).toBeInTheDocument();
    expect(s.score().getByText("4/5")).toBeInTheDocument();
  });

  it("bez myszy (jsdom, dotyk) ruch wskaźnika nie zmienia odczytu", () => {
    const s = renderScene("radar");
    fireEvent.pointerMove(s.container.querySelector(".kr-radar-field") as Element, { clientX: 10, clientY: 10 });
    expect(s.full().getByText("kliknij cel, który znasz")).toBeInTheDocument();
  });
});
