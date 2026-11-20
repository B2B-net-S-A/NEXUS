import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RateStepChart } from "@/components/contracts/rates/RateStepChart";
import type { ChartAxis, ChartSegment } from "@/components/contracts/rates/rate-steps";

// jsdom nie liczy układu — wykres rysuje się w szerokości zapasowej 640 px.
const WIDTH = 640;

const SEGMENTS: ChartSegment[] = [
  { from: "2026-04-01", to: "2026-07-01", client: 180, candidate: 140 },
  { from: "2026-07-01", to: "2026-12-31", client: 170, candidate: 130 },
];
const AXIS: ChartAxis = {
  start: "2026-04-01",
  end: "2026-12-31",
  startLabel: "pierwsza stawka",
  endLabel: "koniec zamówienia",
};

function renderChart(props: Partial<Parameters<typeof RateStepChart>[0]> = {}) {
  return render(
    <RateStepChart
      segments={SEGMENTS}
      axis={AXIS}
      today="2026-11-20"
      unit="zł/h"
      description="Stawki od 01.04.2026: klient płaci 180,00 zł/h, od 01.07.2026 170,00 zł/h."
      {...props}
    />,
  );
}

describe("RateStepChart", () => {
  it("ma dostępny opis zdaniem o zmianach", () => {
    renderChart();
    expect(
      screen.getByRole("img", { name: /klient płaci 180,00 zł\/h, od 01\.07\.2026 170,00 zł\/h/ }),
    ).toBeInTheDocument();
  });

  it("podpisuje kwoty tylko przy zmianach i trzyma je w granicach SVG", () => {
    renderChart({
      segments: [
        ...SEGMENTS.slice(0, 1),
        { from: "2026-07-01", to: "2026-09-01", client: 170, candidate: 130 },
        // Ten sam poziom co wyżej — bez nowej etykiety.
        { from: "2026-09-01", to: "2026-12-31", client: 170, candidate: 130 },
      ],
    });
    const labels = screen.getAllByTestId("rate-chart-label");
    expect(labels.map((l) => l.textContent)).toEqual(["180,00", "170,00", "140,00", "130,00"]);
    for (const label of labels) {
      const x = Number(label.getAttribute("x"));
      const y = Number(label.getAttribute("y"));
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x + (label.textContent ?? "").length * 11 * 0.6).toBeLessThanOrEqual(WIDTH);
      expect(y).toBeGreaterThan(11);
      expect(y).toBeLessThan(172 - 36);
    }
  });

  it("rysuje kreskę „dziś” tylko w zakresie osi, z napisem w granicach", () => {
    const { unmount } = renderChart({ today: "2026-12-31" });
    const today = screen.getByTestId("rate-chart-today");
    const text = today.querySelector("text");
    expect(text?.textContent).toBe("dziś");
    expect(Number(text?.getAttribute("x"))).toBeLessThanOrEqual(WIDTH - 2 - 12);
    unmount();

    renderChart({ today: "2027-03-01" });
    expect(screen.queryByTestId("rate-chart-today")).not.toBeInTheDocument();
  });

  it("pas marży jest zielony, a ujemna marża — w kolorze błędu", () => {
    const { container, unmount } = renderChart();
    expect(container.querySelectorAll("path.fill-success\\/15")).toHaveLength(1);
    expect(container.querySelector("path.fill-destructive\\/15")).toBeNull();
    unmount();

    const negative = render(
      <RateStepChart
        segments={[
          { from: "2026-04-01", to: "2026-07-01", client: 150, candidate: 140 },
          { from: "2026-07-01", to: "2026-12-31", client: 130, candidate: 140 },
        ]}
        axis={AXIS}
        today="2026-11-20"
        unit="zł/h"
        description="opis"
      />,
    );
    expect(negative.container.querySelector("path.fill-success\\/15")).not.toBeNull();
    expect(negative.container.querySelector("path.fill-destructive\\/15")).not.toBeNull();
  });

  it("daty osi: początek z podpisem, koniec z podpisem, zmiana pomiędzy", () => {
    const { container } = renderChart();
    const texts = Array.from(container.querySelectorAll("text")).map((t) => t.textContent);
    expect(texts).toEqual(
      expect.arrayContaining(["01.04.2026", "pierwsza stawka", "31.12.2026", "koniec zamówienia", "01.07.2026"]),
    );
  });

  it("bez kwot nic nie rysuje", () => {
    const { container } = renderChart({
      segments: [{ from: "2026-04-01", to: "2026-12-31", client: null, candidate: null }],
    });
    expect(container.querySelector("svg")).toBeNull();
  });
});
