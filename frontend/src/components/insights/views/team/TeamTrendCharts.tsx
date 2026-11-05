"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { insightsApi, insightsQueryKeys } from "@/lib/insights-api";
import {
  CONVERSIONS,
  monthlySeries,
  niceAxisMax,
  TEAM_STAGES,
  weeklySeries,
  type ConversionKey,
  type TeamStage,
  type TrendSeries,
  type TrendStageKey,
} from "@/lib/insights-team-view";
import { SectionError } from "@/components/insights/sections/_shared";

import { PanelLoading } from "../ViewKit";

export type TrendMode = "week" | "month";

const WEEKS = 26;
const MONTHS = 12;

/**
 * Kolor idzie za serią, nie za pozycją. Trzy odcienie z palety wykresów
 * i kolor tekstu: bursztyn `--chart-3` ma na białym tle kontrast 2,1:1.
 */
const STAGE_COLOR: Record<TrendStageKey, string> = {
  verified: "hsl(var(--chart-1))",
  cv_sent: "hsl(var(--chart-2))",
  client_interview: "hsl(var(--chart-4))",
  acceptance: "hsl(var(--foreground))",
  hired: "hsl(var(--chart-5))",
};

const CONVERSION_COLOR: Record<ConversionKey, string> = {
  verified_cv: "hsl(var(--chart-1))",
  cv_interview: "hsl(var(--chart-2))",
  interview_acceptance: "hsl(var(--chart-4))",
  acceptance_hired: "hsl(var(--foreground))",
};

function useTrendSeries(mode: TrendMode) {
  const weekly = useQuery({
    queryKey: insightsQueryKeys.weeklyTrend(WEEKS),
    queryFn: () => insightsApi.weeklyTrend(WEEKS),
    staleTime: 5 * 60 * 1000,
    enabled: mode === "week",
  });
  const monthly = useQuery({
    queryKey: insightsQueryKeys.monthlyTrend(MONTHS),
    queryFn: () => insightsApi.monthlyTrend(MONTHS),
    staleTime: 5 * 60 * 1000,
    enabled: mode === "month",
  });
  const query = mode === "week" ? weekly : monthly;
  const series = useMemo<TrendSeries | null>(() => {
    if (mode === "week") return weekly.data ? weeklySeries(weekly.data.weeks) : null;
    return monthly.data ? monthlySeries(monthly.data.months) : null;
  }, [mode, weekly.data, monthly.data]);
  return { series, isError: query.isError, error: query.error, refetch: query.refetch };
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

interface Line {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

function lastValueIndex(values: readonly (number | null)[]): number | null {
  for (let i = values.length - 1; i >= 0; i -= 1) {
    if (values[i] !== null) return i;
  }
  return null;
}

/** Jedna oś, cienkie linie, kropka na końcu i na punkcie bez sąsiadów. */
function LineChart({
  series,
  lines,
  height,
  unit = "",
  hover,
  onHover,
  minTop,
}: {
  series: TrendSeries;
  lines: Line[];
  height: number;
  unit?: string;
  hover: number | null;
  onHover: (index: number | null) => void;
  minTop?: number;
}) {
  const { ref, width } = useWidth();
  const { labels, cutoverIndex } = series;
  const pad = { l: 42, r: 8, t: 8, b: 18 };
  const innerW = Math.max(1, width - pad.l - pad.r);
  const innerH = height - pad.t - pad.b;
  const top = niceAxisMax(Math.max(minTop ?? 0, ...lines.flatMap((line) => line.values.map((v) => v ?? 0))));
  const x = (i: number) => pad.l + (labels.length > 1 ? (innerW * i) / (labels.length - 1) : innerW / 2);
  const y = (v: number) => pad.t + innerH * (1 - v / top);
  const every = Math.max(1, Math.ceil(labels.length / Math.max(2, Math.floor(innerW / 44))));
  return (
    <div ref={ref} className="w-full">
      {width > 0 ? (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={lines.map((line) => `${line.label}: ${labels.map((label, i) => `${label} ${line.values[i] ?? "brak danych"}${unit}`).join(", ")}`).join(". ")}
          onMouseLeave={() => onHover(null)}
          onMouseMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const i = Math.round(((event.clientX - box.left - pad.l) / innerW) * (labels.length - 1));
            onHover(Math.max(0, Math.min(labels.length - 1, i)));
          }}
        >
          {[0, top / 2, top].map((tick) => (
            <g key={tick}>
              <line x1={pad.l} x2={width - pad.r} y1={y(tick)} y2={y(tick)} stroke="hsl(var(--border))" strokeWidth={1} />
              <text x={pad.l - 6} y={y(tick) + 3.5} textAnchor="end" fontSize={10.5} fill="hsl(var(--muted-foreground))" style={{ fontVariantNumeric: "tabular-nums" }}>
                {tick.toLocaleString("pl-PL")}{unit}
              </text>
            </g>
          ))}
          {labels.map((label, i) =>
            i % every === (labels.length - 1) % every ? (
              <text key={`${label}-${i}`} x={x(i)} y={height - 4} textAnchor={i === labels.length - 1 ? "end" : "middle"} fontSize={10.5} fill="hsl(var(--muted-foreground))">
                {label}
              </text>
            ) : null,
          )}
          {cutoverIndex !== null ? (
            <line x1={x(cutoverIndex)} x2={x(cutoverIndex)} y1={pad.t} y2={height - pad.b} stroke="hsl(var(--muted-foreground))" strokeWidth={1} strokeDasharray="2 3" />
          ) : null}
          {hover !== null ? <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={height - pad.b} stroke="hsl(var(--foreground))" strokeWidth={1} /> : null}
          {lines.map((line) => (
            <g key={line.key}>
              {line.values.map((v, i) => {
                const next = line.values[i + 1];
                if (v === null || next === null || next === undefined) return null;
                return <line key={i} x1={x(i)} y1={y(v)} x2={x(i + 1)} y2={y(next)} stroke={line.color} strokeWidth={2} strokeLinecap="round" />;
              })}
              {line.values.map((v, i) => {
                if (v === null) return null;
                const alone = (line.values[i - 1] ?? null) === null && (line.values[i + 1] ?? null) === null;
                if (!alone && i !== lastValueIndex(line.values) && hover !== i) return null;
                return <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 4.5 : 3.5} fill={line.color} stroke="hsl(var(--card))" strokeWidth={1.5} />;
              })}
            </g>
          ))}
        </svg>
      ) : (
        <div style={{ height }} />
      )}
    </div>
  );
}

function Legend({
  series,
  lines,
  hover,
  unit = "",
  detail,
}: {
  series: TrendSeries;
  lines: Line[];
  hover: number | null;
  unit?: string;
  detail?: (key: string, index: number) => string | null;
}) {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
      {lines.map((line) => {
        const index = hover ?? lastValueIndex(line.values);
        const value = index === null ? null : line.values[index];
        const extra = index !== null ? detail?.(line.key, index) : null;
        return (
          <li key={line.key} className="flex items-center gap-1.5">
            <span className="h-0.5 w-3.5 rounded-full" style={{ backgroundColor: line.color }} aria-hidden />
            <span className="text-muted-foreground">{line.label}</span>
            <span className="font-semibold tabular-nums text-foreground">{value === null ? "—" : `${value.toLocaleString("pl-PL")}${unit}`}</span>
            {extra ? <span className="tabular-nums text-muted-foreground">({extra})</span> : null}
          </li>
        );
      })}
      {hover !== null ? <li className="tabular-nums text-muted-foreground">{series.labels[hover]}</li> : null}
    </ul>
  );
}

function ModeSwitch({ mode, onChange }: { mode: TrendMode; onChange: (mode: TrendMode) => void }) {
  return (
    <div role="group" aria-label="Przedział" className="inline-flex gap-0.5 rounded-lg bg-muted p-1">
      {(
        [
          ["week", "Tygodnie"],
          ["month", "Miesiące"],
        ] as const
      ).map(([value, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={mode === value}
          onClick={() => onChange(value)}
          className={cn(
            "min-h-7 rounded-md px-3 text-xs font-semibold transition-colors",
            mode === value ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function conversionDetail(series: TrendSeries) {
  return (key: string, index: number) => {
    const p = series.conversions[key as ConversionKey][index];
    return p.num !== null && p.den !== null ? `${p.num} z ${p.den}` : null;
  };
}

function TrendState({ state, height }: { state: ReturnType<typeof useTrendSeries>; height: string }) {
  return state.isError ? (
    <SectionError label="Wykresy" error={state.error} onRetry={() => void state.refetch()} />
  ) : (
    <div className={height}>
      <PanelLoading />
    </div>
  );
}

/** „Cały lejek”: liczby na dwóch wykresach według skali, przejścia na trzecim. */
export function WholeFunnelTrend({ mode, onMode }: { mode: TrendMode; onMode: (mode: TrendMode) => void }) {
  const state = useTrendSeries(mode);
  const [hover, setHover] = useState<number | null>(null);
  const { series } = state;
  const stageLine = (stage: TeamStage): Line | null =>
    series ? { key: stage.stage, label: stage.label, color: STAGE_COLOR[stage.stage], values: series.counts[stage.stage] } : null;
  const groups = [TEAM_STAGES.slice(0, 2), TEAM_STAGES.slice(2)].map((group) => group.map(stageLine).filter((l): l is Line => l !== null));
  const conversions: Line[] = series
    ? CONVERSIONS.map((c) => ({ key: c.key, label: c.short, color: CONVERSION_COLOR[c.key], values: series.conversions[c.key].map((p) => p.value) }))
    : [];
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Jak to się zmienia w czasie</h3>
        <ModeSwitch mode={mode} onChange={(next) => { onMode(next); setHover(null); }} />
      </div>
      {!series ? (
        <TrendState state={state} height="h-64" />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {groups.map((lines) => (
              <figure key={lines[0].key} className="min-w-0 space-y-1.5">
                <Legend series={series} lines={lines} hover={hover} />
                <LineChart series={series} lines={lines} height={170} hover={hover} onHover={setHover} />
              </figure>
            ))}
          </div>
          <figure className="min-w-0 space-y-1.5 border-t border-border pt-3">
            <Legend series={series} lines={conversions} hover={hover} unit="%" detail={conversionDetail(series)} />
            <LineChart series={series} lines={conversions} height={190} unit="%" hover={hover} onHover={setHover} minTop={100} />
          </figure>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Przerywana pionowa linia to 12.10, start pracy w NEXUSIE: wcześniej liczby z DynaReportera, akceptacji nie było, więc te dwa przejścia dopiero się zaczynają.
        Przejście to liczba etapu podzielona przez liczbę poprzedniego w tym samym okresie, nie te same osoby, więc akceptacja → placement może przekroczyć 100%.
        Trwający okres jest w liczbach niżej.
      </p>
    </section>
  );
}

/** Wybrany etap: jego linia i przejście do niego. */
export function StageTrend({ stage, mode, onMode }: { stage: TeamStage; mode: TrendMode; onMode: (mode: TrendMode) => void }) {
  const state = useTrendSeries(mode);
  const [hover, setHover] = useState<number | null>(null);
  const { series } = state;
  const conversion = CONVERSIONS.find((c) => c.to === stage.stage);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{stage.label} w czasie</h3>
        <ModeSwitch mode={mode} onChange={(next) => { onMode(next); setHover(null); }} />
      </div>
      {!series ? (
        <TrendState state={state} height="h-52" />
      ) : (
        <div className="space-y-3">
          {(() => {
            const lines: Line[] = [{ key: stage.stage, label: stage.label, color: "hsl(var(--chart-1))", values: series.counts[stage.stage] }];
            return (
              <figure className="min-w-0 space-y-1.5">
                <Legend series={series} lines={lines} hover={hover} />
                <LineChart series={series} lines={lines} height={conversion ? 104 : 190} hover={hover} onHover={setHover} />
              </figure>
            );
          })()}
          {conversion
            ? (() => {
                const lines: Line[] = [{ key: conversion.key, label: conversion.label, color: "hsl(var(--chart-2))", values: series.conversions[conversion.key].map((p) => p.value) }];
                return (
                  <figure className="min-w-0 space-y-1.5">
                    <Legend series={series} lines={lines} hover={hover} unit="%" detail={conversionDetail(series)} />
                    <LineChart series={series} lines={lines} height={104} unit="%" hover={hover} onHover={setHover} minTop={100} />
                  </figure>
                );
              })()
            : null}
        </div>
      )}
    </div>
  );
}
