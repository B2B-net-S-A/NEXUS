import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import { DlTrendChart } from "../DlTrendChart";
import type { TrendPoint } from "../types";

/**
 * Kontrakt renderowania recharts. Wykres potrafi zbudować się i zamontować
 * bez błędu, a mimo to narysować PUSTY `<svg>` — dlatego te asercje sprawdzają
 * realną geometrię SVG (ścieżki serii, linie siatki, kreski osi), a nie samo
 * zamontowanie komponentu.
 *
 * `DlTrendChart` jest tu najtańszym reprezentantem: używa tego samego zestawu
 * prymitywów co dashboardy DynaReporter (LineChart/BarChart, CartesianGrid,
 * XAxis, dwa YAxis z `yAxisId`, Tooltip, Legend). Jedyny prymityw spoza tego
 * zestawu — `ReferenceLine` — ma osobny, minimalny test niżej.
 */

const TREND: TrendPoint[] = [
  { month: "2026-01", month_label: "sty", requests: 12, vacancies: 8, placements: 3, hit_ratio: 25, fill_rate: 37.5 },
  { month: "2026-02", month_label: "lut", requests: 18, vacancies: 11, placements: 5, hit_ratio: 27.8, fill_rate: 45.5 },
  { month: "2026-03", month_label: "mar", requests: 9, vacancies: 6, placements: 2, hit_ratio: 22.2, fill_rate: 33.3 },
  { month: "2026-04", month_label: "kwi", requests: 21, vacancies: 15, placements: 7, hit_ratio: 33.3, fill_rate: 46.7 },
];

/**
 * `ResponsiveContainer` mierzy się przez `getBoundingClientRect()`, a jsdom
 * zawsze zwraca 0×0 — bez tego stubu recharts wyrenderowałby pusty kontener
 * i test przechodziłby na fałszywie pustym wykresie.
 *
 * Stub MUSI być zawężony do samego kontenera. Podmiana globalna kłamie także
 * pomiarowi tekstu, z którego `YAxis` liczy swoją szerokość — oś urosłaby wtedy
 * do szerokości całego wykresu, zjadła obszar rysowania i siatka, osie Y oraz
 * serie zniknęłyby bez żadnego błędu.
 */
const REAL_RECT = Element.prototype.getBoundingClientRect;

beforeAll(() => {
  // recharts 3 pomija animację wejścia przy `prefers-reduced-motion: reduce`.
  // Bez tego `Bar` zostaje w jsdom na pierwszej klatce animacji (wysokość 0),
  // a `Rectangle` o zerowej wysokości renderuje `null` — grupy
  // `.recharts-bar-rectangle` istnieją, ale są PUSTE. Zliczanie samych grup
  // byłoby więc asercją pustą; stub pozwala sprawdzić realną geometrię słupków.
  window.matchMedia = ((query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;

  Element.prototype.getBoundingClientRect = function (this: Element) {
    if (this.classList?.contains("recharts-responsive-container")) {
      return { width: 800, height: 400, top: 0, left: 0, right: 800, bottom: 400, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    }
    return REAL_RECT.call(this);
  };
});

afterAll(() => {
  Element.prototype.getBoundingClientRect = REAL_RECT;
});

/** Ścieżka SVG z prawdziwą geometrią, a nie pusty/degenerowany `d`. */
function expectDrawnPath(path: Element | null, minPoints: number) {
  expect(path).not.toBeNull();
  const d = path?.getAttribute("d") ?? "";
  expect(d.startsWith("M")).toBe(true);
  // Każdy punkt danych to jedna komenda z współrzędnymi — degenerowana ścieżka
  // ("M0,0" albo pusty string) tego progu nie przejdzie.
  expect(d.match(/[-\d.]+,[-\d.]+/g)?.length ?? 0).toBeGreaterThanOrEqual(minPoints);
}

describe("DlTrendChart — kontrakt renderowania recharts", () => {
  it("rysuje wykres liniowy: powierzchnię SVG, siatkę, osie i ścieżkę każdej serii", () => {
    const { container } = render(<DlTrendChart trend={TREND} />);

    // 1. Powierzchnia wykresu w ogóle powstała. Selektor musi być na
    //    bezpośrednim dzieciu `.recharts-wrapper` — ikony legendy to również
    //    `svg.recharts-surface`, a w recharts 3 legenda jest w DOM PRZED
    //    wykresem, więc samo `.recharts-surface` trafiłoby w ikonę 14×14.
    const surface = container.querySelector(
      ".recharts-wrapper > svg.recharts-surface"
    );
    expect(surface).not.toBeNull();
    expect(Number(surface?.getAttribute("width"))).toBeGreaterThan(0);

    // 2. Siatka. W recharts 3 CartesianGrid dobiera osie po `xAxisId`/`yAxisId`;
    //    przy niedopasowaniu linie siatki po cichu znikają.
    expect(
      container.querySelectorAll(".recharts-cartesian-grid line").length
    ).toBeGreaterThan(0);

    // 3. Obie osie Y (yAxisId="left" i "right") oraz oś X mają wyrenderowane kreski.
    expect(
      container.querySelectorAll(".recharts-cartesian-axis-tick").length
    ).toBeGreaterThan(0);
    expect(screen.getByText("sty")).toBeInTheDocument();
    expect(screen.getByText("kwi")).toBeInTheDocument();

    // 4. Pięć serii liniowych, każda z realną geometrią (4 punkty danych).
    const curves = container.querySelectorAll("path.recharts-curve.recharts-line-curve");
    expect(curves).toHaveLength(5);
    curves.forEach((curve) => expectDrawnPath(curve, TREND.length));

    // 5. Legenda z nazwami serii — dowód, że `name` nadal dociera do Legend.
    expect(screen.getByText("Zapytania")).toBeInTheDocument();
    expect(screen.getByText("Hit Ratio %")).toBeInTheDocument();
  });

  it("po przełączeniu na słupkowy rysuje prostokąty serii zamiast linii", async () => {
    const user = userEvent.setup();
    const { container } = render(<DlTrendChart trend={TREND} />);

    await user.click(screen.getByRole("button", { name: "Słupkowy" }));

    expect(container.querySelectorAll("path.recharts-line-curve")).toHaveLength(0);

    // 3 serie × 4 punkty danych. Sprawdzamy ŚCIEŻKI, nie grupy
    // `.recharts-bar-rectangle` — puste grupy renderują się także wtedy, gdy
    // słupek ma zerową wysokość, więc ich zliczanie niczego nie dowodzi.
    const barPaths = container.querySelectorAll(".recharts-bar-rectangle path");
    expect(barPaths).toHaveLength(3 * TREND.length);

    // Każdy słupek ma niezerową szerokość i wysokość: "M x,y h W v H h -W Z".
    barPaths.forEach((bar) => {
      const [, width, height] =
        bar.getAttribute("d")?.match(/h\s*(-?[\d.]+)\s*v\s*(-?[\d.]+)/) ?? [];
      expect(Math.abs(Number(width))).toBeGreaterThan(0);
      expect(Math.abs(Number(height))).toBeGreaterThan(0);
    });

    expect(container.querySelector(".recharts-cartesian-grid line")).not.toBeNull();
  });
});

describe("ReferenceLine — kontrakt renderowania recharts", () => {
  it("rysuje linię odniesienia z etykietą", () => {
    const { container } = render(
      <div style={{ width: 800, height: 400 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={TREND}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month_label" />
            <YAxis />
            <Line type="monotone" dataKey="hit_ratio" />
            <ReferenceLine y={30} strokeDasharray="5 5" label="Target" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );

    const refLine = container.querySelector(".recharts-reference-line line");
    expect(refLine).not.toBeNull();
    // Pozioma linia o niezerowej długości — nie zdegenerowany punkt.
    const x1 = Number(refLine?.getAttribute("x1"));
    const x2 = Number(refLine?.getAttribute("x2"));
    expect(Math.abs(x2 - x1)).toBeGreaterThan(0);
    expect(screen.getByText("Target")).toBeInTheDocument();
  });
});
