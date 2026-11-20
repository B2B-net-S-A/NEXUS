"use client";
// Wykres schodkowy stawek w „Stawkach w czasie” (wariant A z 19.11.2026):
// stawka klienta (`stroke-primary`), kandydata (`stroke-muted-foreground`), pas
// marży między nimi, kreska „dziś”, kwoty tylko przy zmianach. Rysowany 1 : 1
// w zmierzonej szerokości, więc tekst się nie skaluje, a każdy napis mieści się
// w granicach SVG. Kwoty są też w tabeli pod wykresem — podpowiedź ich nie
// zastępuje.
import { useState, type PointerEvent as ReactPointerEvent } from "react";

import { formatIsoDatePl } from "@/lib/date-pl";
import { useElementWidth } from "@/lib/use-element-width";
import { formatPercent, formatRateNumber } from "./rate-format";
import { DAY_MS, isoToMs, msToIso, type ChartAxis, type ChartSegment } from "./rate-steps";

const HEIGHT = 172;
const PAD = { left: 2, right: 2, top: 26, bottom: 36 };
/** Szerokość do pierwszego pomiaru (i w testach, gdzie jsdom nie liczy układu). */
const FALLBACK_WIDTH = 640;
const VALUE_FONT = 11;
const TICK_FONT = 10.5;
const SUB_FONT = 10;
const TOOLTIP_WIDTH = 240;

/** Szacunek szerokości napisu (Inter ≈ 0,6 em na znak) — wystarcza do mieszczenia i odstępów. */
function textWidth(text: string, fontPx: number): number {
  return text.length * fontPx * 0.6;
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

interface BandPiece {
  from: string;
  to: string;
  top: number;
  bottom: number;
}

interface Tick {
  x: number;
  text: string;
  sub: string;
  anchor: "start" | "middle" | "end";
}

export interface RateStepChartProps {
  segments: ChartSegment[];
  axis: ChartAxis;
  today: string;
  /** Jednostka obu stawek („zł/h”) — do podpowiedzi. */
  unit: string;
  /** Zdanie o zmianach dla czytnika ekranu (`aria-label`). */
  description: string;
}

export function RateStepChart({ segments, axis, today, unit, description }: RateStepChartProps) {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const width = useElementWidth(node) || FALLBACK_WIDTH;
  const [hover, setHover] = useState<{ x: number; segment: ChartSegment } | null>(null);

  const values = segments.flatMap((s) => [s.client, s.candidate]).filter((v): v is number => v != null);
  if (values.length === 0) return null;

  const t0 = isoToMs(axis.start);
  const t1 = Math.max(isoToMs(axis.end), t0 + DAY_MS);
  const right = width - PAD.right;
  const plotWidth = Math.max(right - PAD.left, 10);
  const baseY = HEIGHT - PAD.bottom;
  const xOf = (iso: string) => PAD.left + ((isoToMs(iso) - t0) / (t1 - t0)) * plotWidth;

  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.max(Math.abs(hi) * 0.1, 1);
  const yLo = lo - span * 0.5;
  const yHi = hi + span * 0.32;
  const yOf = (value: number) => PAD.top + (1 - (value - yLo) / (yHi - yLo)) * (baseY - PAD.top);

  const stepPath = (key: "client" | "candidate") => {
    let d = "";
    let open = false;
    for (const s of segments) {
      const value = s[key];
      if (value == null) {
        open = false;
        continue;
      }
      const y = yOf(value).toFixed(1);
      d += open
        ? ` V${y} H${xOf(s.to).toFixed(1)}`
        : ` M${xOf(s.from).toFixed(1)} ${y} H${xOf(s.to).toFixed(1)}`;
      open = true;
    }
    return d.trim();
  };

  // Pas marży: ciągłe odcinki z obiema stawkami; ujemna marża w kolorze błędu.
  const runs: { negative: boolean; pieces: BandPiece[] }[] = [];
  let run: { negative: boolean; pieces: BandPiece[] } | null = null;
  for (const s of segments) {
    if (s.client == null || s.candidate == null || s.client === s.candidate) {
      run = null;
      continue;
    }
    const negative = s.client < s.candidate;
    const piece = {
      from: s.from,
      to: s.to,
      top: Math.max(s.client, s.candidate),
      bottom: Math.min(s.client, s.candidate),
    };
    if (run && run.negative === negative) run.pieces.push(piece);
    else {
      run = { negative, pieces: [piece] };
      runs.push(run);
    }
  }
  const bandPath = (pieces: BandPiece[]) => {
    const top = pieces.map(
      (p, i) =>
        `${i === 0 ? "M" : "L"}${xOf(p.from).toFixed(1)} ${yOf(p.top).toFixed(1)} L${xOf(p.to).toFixed(1)} ${yOf(p.top).toFixed(1)}`,
    );
    const bottom = [...pieces]
      .reverse()
      .map(
        (p) =>
          `L${xOf(p.to).toFixed(1)} ${yOf(p.bottom).toFixed(1)} L${xOf(p.from).toFixed(1)} ${yOf(p.bottom).toFixed(1)}`,
      );
    return `${top.join(" ")} ${bottom.join(" ")} Z`;
  };

  // Kwoty tylko tam, gdzie stawka się zmienia; bez nakładania i w granicach SVG.
  const labels: { key: string; x: number; y: number; text: string }[] = [];
  for (const key of ["client", "candidate"] as const) {
    let previous: number | null = null;
    let lastEnd = -Infinity;
    for (const s of segments) {
      const value = s[key];
      if (value != null && value !== previous) {
        const text = formatRateNumber(value);
        const w = textWidth(text, VALUE_FONT);
        const x = Math.min(xOf(s.from) + 4, right - w);
        if (x >= lastEnd + 6) {
          labels.push({ key: `${key}-${s.from}`, x, y: key === "client" ? yOf(value) - 6 : yOf(value) + 13, text });
          lastEnd = x + w;
        }
      }
      previous = value;
    }
  }

  // Daty na osi: początek, koniec, a pomiędzy dni zmian, które się mieszczą.
  const extent = (t: Tick): [number, number] => {
    const w = Math.max(textWidth(t.text, TICK_FONT), textWidth(t.sub, SUB_FONT));
    if (t.anchor === "start") return [t.x, t.x + w];
    if (t.anchor === "end") return [t.x - w, t.x];
    return [t.x - w / 2, t.x + w / 2];
  };
  const ticks: Tick[] = [];
  const tryTick = (tick: Tick) => {
    const [a, b] = extent(tick);
    if (a < 0 || b > width) return;
    const free = ticks.every((other) => {
      const [c, e] = extent(other);
      return b + 8 < c || a - 8 > e;
    });
    if (free) ticks.push(tick);
  };
  tryTick({ x: PAD.left, text: formatIsoDatePl(axis.start), sub: axis.startLabel, anchor: "start" });
  tryTick({ x: right, text: formatIsoDatePl(axis.end), sub: axis.endLabel, anchor: "end" });
  for (const s of segments.slice(1)) {
    tryTick({ x: xOf(s.from), text: formatIsoDatePl(s.from), sub: "", anchor: "middle" });
  }

  const todayMs = isoToMs(today);
  const todayX = todayMs >= t0 && todayMs <= t1 ? xOf(today) : null;
  const todayHalf = textWidth("dziś", TICK_FONT) / 2 + 1;

  const onMove = (event: ReactPointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!box) return;
    const x = clamp(event.clientX - box.left, PAD.left, right);
    const date = msToIso(t0 + ((x - PAD.left) / plotWidth) * (t1 - t0));
    const segment = [...segments].reverse().find((s) => s.from <= date) ?? segments[0];
    if (segment) setHover({ x, segment });
  };

  const hovered = hover?.segment ?? null;
  const hoverMargin =
    hovered && hovered.client != null && hovered.candidate != null ? hovered.client - hovered.candidate : null;
  const tooltipLeft = hover
    ? clamp(
        hover.x + 12 + TOOLTIP_WIDTH > width ? hover.x - 12 - TOOLTIP_WIDTH : hover.x + 12,
        0,
        Math.max(width - TOOLTIP_WIDTH, 0),
      )
    : 0;

  return (
    <div ref={setNode} className="relative overflow-hidden">
      <svg
        width={width}
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="img"
        aria-label={description}
        className="block"
        data-testid="rate-step-chart"
      >
        <line x1={PAD.left} x2={right} y1={baseY + 0.5} y2={baseY + 0.5} className="stroke-border" strokeWidth={1} />
        {runs.map((r) => (
          <path
            key={`${r.negative ? "neg" : "pos"}-${r.pieces[0].from}`}
            d={bandPath(r.pieces)}
            className={r.negative ? "fill-destructive/15" : "fill-success/15"}
          />
        ))}
        <path
          d={stepPath("candidate")}
          fill="none"
          className="stroke-muted-foreground"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <path
          d={stepPath("client")}
          fill="none"
          className="stroke-primary"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {labels.map((label) => (
          <text
            key={label.key}
            x={label.x}
            y={label.y}
            className="fill-foreground text-[11px] font-medium tabular-nums"
            data-testid="rate-chart-label"
          >
            {label.text}
          </text>
        ))}

        {ticks.map((tick) => (
          <g key={`${tick.anchor}-${tick.text}`}>
            {tick.anchor === "middle" ? (
              <line x1={tick.x} x2={tick.x} y1={baseY} y2={baseY + 4} className="stroke-border" />
            ) : null}
            <text
              x={tick.x}
              y={baseY + 15}
              textAnchor={tick.anchor}
              className="fill-muted-foreground text-[10.5px] tabular-nums"
            >
              {tick.text}
            </text>
            {tick.sub ? (
              <text x={tick.x} y={baseY + 28} textAnchor={tick.anchor} className="fill-muted-foreground text-[10px]">
                {tick.sub}
              </text>
            ) : null}
          </g>
        ))}

        {todayX != null ? (
          <g data-testid="rate-chart-today">
            <line x1={todayX} x2={todayX} y1={15} y2={baseY} className="stroke-foreground/45" strokeWidth={1} />
            <text
              x={clamp(todayX, PAD.left + todayHalf, right - todayHalf)}
              y={11}
              textAnchor="middle"
              className="fill-foreground text-[10.5px] font-medium"
            >
              dziś
            </text>
          </g>
        ) : null}

        {hover && hovered ? (
          <g pointerEvents="none">
            <line x1={hover.x} x2={hover.x} y1={PAD.top - 4} y2={baseY} className="stroke-foreground/30" strokeWidth={1} />
            {hovered.client != null ? (
              <circle cx={hover.x} cy={yOf(hovered.client)} r={4} className="fill-primary stroke-card" strokeWidth={2} />
            ) : null}
            {hovered.candidate != null ? (
              <circle
                cx={hover.x}
                cy={yOf(hovered.candidate)}
                r={4}
                className="fill-muted-foreground stroke-card"
                strokeWidth={2}
              />
            ) : null}
          </g>
        ) : null}

        <rect
          x={PAD.left}
          y={PAD.top - 12}
          width={plotWidth}
          height={baseY - PAD.top + 12}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>

      {hover && hovered ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-0 z-10 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-md"
          style={{ left: tooltipLeft, width: TOOLTIP_WIDTH }}
        >
          <p className="mb-1 text-[11px] text-muted-foreground">
            od {formatIsoDatePl(hovered.from)}
            {hovered.to !== axis.end ? ` do ${formatIsoDatePl(msToIso(isoToMs(hovered.to) - DAY_MS))}` : ""} · {unit}
          </p>
          <ul className="space-y-0.5">
            <li className="flex items-center gap-2">
              <span className="h-0.5 w-3 rounded-full bg-primary" />
              <span className="w-14 text-right font-semibold tabular-nums text-foreground">
                {formatRateNumber(hovered.client)}
              </span>
              <span className="text-muted-foreground">klient</span>
            </li>
            <li className="flex items-center gap-2">
              <span className="h-0.5 w-3 rounded-full bg-muted-foreground" />
              <span className="w-14 text-right font-semibold tabular-nums text-foreground">
                {formatRateNumber(hovered.candidate)}
              </span>
              <span className="text-muted-foreground">kandydat</span>
            </li>
            {hoverMargin != null && hovered.client ? (
              <li className="flex items-center gap-2">
                <span className="h-2 w-3 rounded-sm bg-success/25" />
                <span className="w-14 text-right font-semibold tabular-nums text-foreground">
                  {formatRateNumber(hoverMargin)}
                </span>
                <span className="text-muted-foreground">
                  marża · {formatPercent((hoverMargin / hovered.client) * 100)}
                </span>
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
