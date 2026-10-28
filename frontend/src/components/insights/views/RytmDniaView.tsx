"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Clock, Gauge, Info, Palmtree, Settings2, Sunrise, Sunset } from "lucide-react";
import { StatCard, StatCardGrid } from "@/components/ds";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SectionError } from "@/components/insights/sections/_shared";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import {
  WORK_RHYTHM_HOURS,
  WORK_RHYTHM_KINDS,
  WORK_RHYTHM_KIND_LABELS as KIND_LABELS,
  workRhythmApi,
  workRhythmQueryKeys,
  type WorkRhythmDay,
  type WorkRhythmDiagnosis,
  type WorkRhythmPerson,
  type WorkRhythmResponse,
  type WorkRhythmRules,
} from "@/lib/work-rhythm-api";
import { PanelLoading } from "./ViewKit";
import { RhythmRulesDialog } from "./RhythmRulesDialog";

/**
 * Insights → „Rytm dnia” (decyzje Artura 28–29.10.2026). Kiedy i jak
 * intensywnie rekruterzy pracują w NEXUSIE. Na razie widzą to tylko Head of
 * Recruitment i admin. Pokazujemy rekruterów i TCM, bez Delivery Leadów i HoR,
 * bez formy współpracy, od 12.10. Kolumny wyników i podpowiedzi rysujemy tylko,
 * gdy serwer je przysłał (`with_results`).
 */

type Mode = "dzien" | "okres" | "intensywnosc";

const LEVEL_CLASSES = ["bg-muted", "bg-primary/20", "bg-primary/45", "bg-primary/75", "bg-primary"];
const LEVEL_NAMES = ["brak", "lekka", "robocza", "intensywna", "bardzo intensywna"];

const DIAGNOSIS: Record<
  WorkRhythmDiagnosis,
  { label: string; hint: string; variant: "success" | "warning" | "info" | "danger" }
> = {
  model: { label: "Wzór", hint: "Pracuje dużo i z wynikiem", variant: "success" },
  quality: {
    label: "Pomóż z jakością",
    hint: "Dużo pracy, mało przechodzi: przegląd notatek i doboru z DL",
    variant: "warning",
  },
  more_volume: {
    label: "Skutecznie, ale mało",
    hint: "Wynik jest, czasu w pracy mało: więcej rozmów",
    variant: "info",
  },
  more_work: {
    label: "Za mało pracy",
    hint: "Mało pracy i słabe wyniki: rozmowa i plan dnia",
    variant: "danger",
  },
};

function fmtNumber(value: number): string {
  return String(value).replace(".", ",");
}

export function fmtDay(iso: string, long = false): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("pl-PL", {
    weekday: long ? "long" : "short",
    day: "numeric",
    month: long ? "long" : "2-digit",
  });
}

function toMin(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function fromMin(v: number): string {
  return `${String(Math.floor(v / 60)).padStart(2, "0")}:${String(Math.round(v % 60)).padStart(2, "0")}`;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function Initials({ name }: { name: string }) {
  const parts = name.trim().split(/\s+/);
  return (
    <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
      {parts[0]?.[0] ?? ""}
      {parts[1]?.[0] ?? ""}
    </span>
  );
}

function IntensityMeter({
  value,
  rules,
  compact = false,
}: {
  value: number | null;
  rules: WorkRhythmRules;
  compact?: boolean;
}) {
  if (value === null) return <span className="text-xs text-muted-foreground">—</span>;
  const tone =
    value >= rules.level_high ? "bg-success" : value >= rules.level_mid ? "bg-warning" : "bg-destructive";
  const label = value >= rules.level_high ? "wysoka" : value >= rules.level_mid ? "średnia" : "niska";
  return (
    <span className="flex items-center gap-2" title={`Intensywność ${value}/100 (${label})`}>
      <span className={cn("relative h-2 overflow-hidden rounded-full bg-muted", compact ? "w-14" : "w-20")}>
        <span className={cn("absolute inset-y-0 left-0 rounded-full", tone)} style={{ width: `${value}%` }} />
      </span>
      <span className="w-7 text-right text-sm font-semibold tabular-nums text-foreground">{value}</span>
      {!compact ? <span className="text-xs text-muted-foreground">{label}</span> : null}
    </span>
  );
}

function HourCells({ day, compact = false }: { day: WorkRhythmDay; compact?: boolean }) {
  return (
    <div className="grid gap-[3px]" style={{ gridTemplateColumns: `repeat(${WORK_RHYTHM_HOURS.length}, minmax(0,1fr))` }}>
      {day.levels.map((level, i) => (
        <div key={i} className="flex flex-col gap-[2px]">
          <span
            className={cn(compact ? "h-3" : "h-6", "rounded-[3px]", LEVEL_CLASSES[level] ?? LEVEL_CLASSES[0])}
            title={`${WORK_RHYTHM_HOURS[i]}:00 — ${fmtNumber(day.points[i])} pkt, ${day.counts[i]} akcji (${LEVEL_NAMES[level]})${day.meetings[i] ? " · spotkanie" : ""}`}
          />
          <span className={cn("h-[3px] rounded-full", day.meetings[i] ? "bg-warning" : "bg-transparent")} />
        </div>
      ))}
    </div>
  );
}

function OffBand({ day, compact = false }: { day: WorkRhythmDay; compact?: boolean }) {
  const label = day.before_start
    ? compact
      ? "przed startem"
      : "Przed założeniem konta — nie liczy się do wskaźnika"
    : compact
      ? "urlop"
      : "Urlop — dzień nie liczy się do wskaźnika";
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 rounded-[3px] border border-dashed px-2",
        day.before_start
          ? "border-border bg-muted/60 text-muted-foreground"
          : "border-info/40 bg-info-muted text-info-muted-foreground",
        compact ? "h-3 text-[10px]" : "h-6 text-xs",
      )}
    >
      {day.before_start ? null : <Palmtree className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />} {label}
    </span>
  );
}

/** Pełny dzień poza pracą (urlop albo przed kontem) — zamiast godzin pasek. */
function isOff(day: WorkRhythmDay): boolean {
  return day.before_start || day.leave >= 1;
}

function HoursHeader() {
  return (
    <div className="grid gap-[3px]" style={{ gridTemplateColumns: `repeat(${WORK_RHYTHM_HOURS.length}, minmax(0,1fr))` }}>
      {WORK_RHYTHM_HOURS.map((h) => (
        <span key={h} className="text-center text-[11px] tabular-nums text-muted-foreground">
          {h}
        </span>
      ))}
    </div>
  );
}

function Legend({ rules }: { rules: WorkRhythmRules }) {
  const [low, mid, high] = rules.hour_levels;
  const ranges = ["0 pkt", `< ${fmtNumber(low)} pkt`, `${fmtNumber(low)}–${fmtNumber(mid)} pkt`, `${fmtNumber(mid)}–${fmtNumber(high)} pkt`, `${fmtNumber(high)}+ pkt`];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {LEVEL_NAMES.map((name, i) => (
        <span key={name} className="flex items-center gap-1.5">
          <span className={cn("h-3 w-4 rounded-[3px]", LEVEL_CLASSES[i])} />
          {name}
          <span className="tabular-nums">{ranges[i]}</span>
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span className="h-[3px] w-5 rounded-full bg-warning" /> spotkanie ≥ 30 min
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-3 w-5 rounded-[3px] border border-dashed border-info/40 bg-info-muted" /> urlop
      </span>
    </div>
  );
}

function RulesPanel({ rules, onEdit }: { rules: WorkRhythmRules; onEdit?: () => void }) {
  const [low, mid, high] = rules.hour_levels;
  return (
    <Card className="min-w-0 space-y-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Info className="h-4 w-4 text-primary" /> Jak liczymy intensywność
        </p>
        {onEdit ? (
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Settings2 className="mr-1 h-3.5 w-3.5" />
            Zmień reguły
          </Button>
        ) : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="min-w-0 space-y-1.5 text-sm">
          <p className="font-medium text-foreground">1. Punkty pracy za akcję</p>
          <table className="w-full text-xs">
            <tbody>
              {WORK_RHYTHM_KINDS.map((kind) => (
                <tr key={kind} className="border-b border-border/60 last:border-0">
                  <td className="py-1 pr-2 text-muted-foreground">{KIND_LABELS[kind]}</td>
                  <td className="py-1 text-right font-semibold tabular-nums text-foreground">{fmtNumber(rules.weights[kind])}</td>
                </tr>
              ))}
              <tr>
                <td className="py-1 pr-2 text-muted-foreground">Autozapis edycji CV, Jarvis, importy i synchronizacje</td>
                <td className="py-1 text-right font-semibold tabular-nums text-foreground">0</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="min-w-0 space-y-1.5 text-xs text-muted-foreground">
          <p className="text-sm font-medium text-foreground">2. Godzina i dzień</p>
          <p>
            <b className="text-foreground">Poziom godziny</b> = suma punktów w tej godzinie: lekka poniżej {fmtNumber(low)}, robocza od {fmtNumber(low)}, intensywna od {fmtNumber(mid)}, bardzo intensywna od {fmtNumber(high)}.
          </p>
          <p>
            <b className="text-foreground">Godzina pracy</b> = co najmniej {fmtNumber(rules.work_hour_min_points)} pkt albo spotkanie w kalendarzu ≥ 30 min, liczona 8:00–18:00.
          </p>
          <p>
            <b className="text-foreground">Intensywność dnia (0–100)</b> = ½ × godziny pracy / {fmtNumber(rules.norm_work_hours)} + ½ × punkty dnia / {fmtNumber(rules.norm_day_points)}, każda część najwyżej 1.
          </p>
        </div>
        <div className="min-w-0 space-y-1.5 text-xs text-muted-foreground">
          <p className="text-sm font-medium text-foreground">3. Okres, urlop, poziomy</p>
          <p>
            <b className="text-foreground">Okres</b> = średnia z zakończonych dni pracy (dzisiejszy dzień się nie liczy). Dzień urlopu z kartoteki i dni przed założeniem konta nie liczą się; pół dnia urlopu obniża obie normy o połowę.
          </p>
          <p>
            <b className="text-foreground">Poziom:</b> wysoka ≥ {rules.level_high}, średnia {rules.level_mid}–{rules.level_high - 1}, niska &lt; {rules.level_mid}.
          </p>
          <p>
            <b className="text-foreground">Podpowiedź dla lidera:</b> intensywność ≥ {rules.diag_intensity} i CV do klienta ≥ {rules.diag_results_pct}% mediany zespołu → wzór; dużo pracy i mało CV → pomóż z jakością; mało pracy i dobre CV → więcej rozmów; mało i mało → plan dnia.
          </p>
          <p>Rozmowy z telefonu i praca na LinkedIn poza wtyczką nie są widoczne.</p>
        </div>
      </div>
    </Card>
  );
}

function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const opts: [Mode, string][] = [
    ["dzien", "Dzień"],
    ["okres", "2 tygodnie"],
    ["intensywnosc", "Intensywność"],
  ];
  return (
    <div className="inline-flex rounded-lg border border-border bg-card p-0.5 text-sm" role="tablist" aria-label="Widok rytmu dnia">
      {opts.map(([id, label]) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={mode === id}
          onClick={() => onChange(id)}
          className={cn(
            "rounded-md px-3 py-1.5 font-medium",
            mode === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// ── Widok „Dzień” ───────────────────────────────────────────────────────────

const DAY_COLS = "170px 1fr 54px 54px 60px 150px";

function DayTable({ data, date }: { data: WorkRhythmResponse; date: string }) {
  return (
    <Card className="min-w-0 p-4">
      <div className="overflow-x-auto">
        <div className="min-w-[900px]">
          <div className="grid items-end gap-3 border-b border-border pb-2 text-xs text-muted-foreground" style={{ gridTemplateColumns: DAY_COLS }}>
            <span>Rekruter</span>
            <HoursHeader />
            <span className="text-right">Start</span>
            <span className="text-right">Koniec</span>
            <span className="text-right">Godz. pracy</span>
            <span>Intensywność dnia</span>
          </div>
          {data.people.map((p) => {
            const d = p.days.find((x) => x.date === date);
            if (!d) return null;
            const off = isOff(d);
            return (
              <div key={p.user_id} className="grid items-center gap-3 border-b border-border/60 py-1.5 last:border-0" style={{ gridTemplateColumns: DAY_COLS }}>
                <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
                  <Initials name={p.name} />
                  <span className="truncate">{p.name}</span>
                </span>
                {off ? <OffBand day={d} /> : <HourCells day={d} />}
                <span className="text-right text-sm tabular-nums text-foreground">{off ? "—" : d.first ?? "—"}</span>
                <span className="text-right text-sm tabular-nums text-foreground">{off ? "—" : d.last ?? "—"}</span>
                <span className="text-right text-sm tabular-nums text-foreground">{off ? "—" : d.work_hours ?? "—"}</span>
                <span className="flex items-center gap-2">
                  <IntensityMeter value={d.index} rules={data.rules} compact />
                  {d.leave > 0 && d.leave < 1 ? <span className="text-[11px] text-info-muted-foreground">½ urlopu</span> : null}
                  {d.in_progress ? <span className="text-[11px] text-muted-foreground">dzień trwa</span> : null}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

// ── Widok „2 tygodnie” ──────────────────────────────────────────────────────

function PersonPeriod({ p, rules }: { p: WorkRhythmPerson; rules: WorkRhythmRules }) {
  const work = p.days.filter((d) => !isOff(d) && d.first && d.last);
  const start = median(work.map((d) => toMin(d.first!)));
  const end = median(work.map((d) => toMin(d.last!)));
  return (
    <Card className="min-w-0 p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Initials name={p.name} />
        <span className="text-sm font-semibold text-foreground">{p.name}</span>
        <span className="ml-auto">
          <IntensityMeter value={p.index} rules={rules} compact />
        </span>
      </div>
      <p className="mb-2 text-xs tabular-nums text-muted-foreground">
        {start !== null && end !== null ? `zwykle ${fromMin(start)}–${fromMin(end)} · ` : ""}
        {p.avg_work_hours !== null ? `${fmtNumber(p.avg_work_hours)} h pracy dziennie · ` : ""}
        {p.median_points !== null ? `${p.median_points} pkt` : "brak dni pracy"}
        {p.leave_days > 0 ? (
          <span className="ml-1 inline-flex items-center gap-1 text-info-muted-foreground">
            · <Palmtree className="h-3 w-3" /> urlop {fmtNumber(p.leave_days)} d., liczone z {fmtNumber(p.worked_days)} dni
          </span>
        ) : null}
        {p.days_before_start > 0 ? <span className="ml-1">· konto od {fmtDay(p.days.find((d) => !d.before_start)?.date ?? p.days[0].date)}</span> : null}
      </p>
      <div className="grid items-center gap-x-2 gap-y-[3px]" style={{ gridTemplateColumns: "64px 1fr 30px" }}>
        <span />
        <HoursHeader />
        <span />
        {p.days.map((d) => (
          <React.Fragment key={d.date}>
            <span className="whitespace-nowrap text-[11px] text-muted-foreground">{fmtDay(d.date)}</span>
            {isOff(d) ? <OffBand day={d} compact /> : <HourCells day={d} compact />}
            <span className="text-right text-[11px] tabular-nums text-muted-foreground" title={d.in_progress ? "Dzień trwa — nie liczy się do wskaźnika okresu" : undefined}>
              {d.in_progress ? "trwa" : d.index ?? ""}
            </span>
          </React.Fragment>
        ))}
      </div>
    </Card>
  );
}

// ── Widok „Intensywność” ────────────────────────────────────────────────────

function IntensityBoard({ data }: { data: WorkRhythmResponse }) {
  const leader = data.with_results;
  const rows = [...data.people].sort((a, b) => (b.index ?? -1) - (a.index ?? -1));
  const cols = leader ? "170px 190px 80px 70px 70px 110px 1fr" : "170px 190px 80px 70px 70px";
  return (
    <div className="grid gap-4">
      <Card className="min-w-0 p-4">
        <div className="overflow-x-auto">
          <div className={leader ? "min-w-[940px]" : "min-w-[640px]"}>
            <div className="grid items-end gap-3 border-b border-border pb-2 text-xs text-muted-foreground" style={{ gridTemplateColumns: cols }}>
              <span>Rekruter</span>
              <span>Intensywność ({fmtDay(data.from)} – {fmtDay(data.to)})</span>
              <span className="text-right">Godz. pracy / dzień</span>
              <span className="text-right">Pkt / dzień</span>
              <span className="text-right">Urlop</span>
              {leader ? <span className="text-right">CV do klienta / dzień</span> : null}
              {leader ? <span>Podpowiedź dla lidera</span> : null}
            </div>
            {rows.map((p) => {
              const dg = p.diagnosis ? DIAGNOSIS[p.diagnosis] : null;
              return (
                <div key={p.user_id} className="grid items-center gap-3 border-b border-border/60 py-2 last:border-0" style={{ gridTemplateColumns: cols }}>
                  <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
                    <Initials name={p.name} />
                    <span className="truncate">{p.name}</span>
                  </span>
                  <IntensityMeter value={p.index} rules={data.rules} />
                  <span className="text-right text-sm tabular-nums text-foreground">{p.avg_work_hours !== null ? fmtNumber(p.avg_work_hours) : "—"}</span>
                  <span className="text-right text-sm tabular-nums text-foreground">{p.median_points ?? "—"}</span>
                  <span className="text-right text-sm tabular-nums text-muted-foreground">{p.leave_days > 0 ? `${fmtNumber(p.leave_days)} d.` : "—"}</span>
                  {leader ? (
                    <span className="text-right text-sm tabular-nums text-foreground">
                      {p.cv_per_day !== null && p.cv_per_day !== undefined ? p.cv_per_day.toFixed(1).replace(".", ",") : "—"}
                      {p.results_pct !== null && p.results_pct !== undefined ? <span className="ml-1 text-xs text-muted-foreground">({p.results_pct}%)</span> : null}
                    </span>
                  ) : null}
                  {leader ? (
                    dg ? (
                      <span className="flex min-w-0 flex-col">
                        <Badge variant={dg.variant} size="sm" className="w-fit">
                          {dg.label}
                        </Badge>
                        <span className="truncate text-[11px] text-muted-foreground" title={dg.hint}>
                          {dg.hint}
                        </span>
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {leader
            ? `Intensywność i CV do klienta z tego samego okresu. W nawiasie % mediany zespołu${data.team_cv_per_day_median !== null ? ` (${data.team_cv_per_day_median.toFixed(2).replace(".", ",")} CV dziennie)` : ""}.`
            : "Bez wyników w tym widoku."}
        </p>
      </Card>
      {leader ? (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <Quadrant data={data} />
          <Card className="min-w-0 space-y-3 p-4 text-sm">
            <p className="font-semibold text-foreground">Co robi lider z każdą ćwiartką</p>
            <p>
              <Badge variant="success" size="sm">Wzór</Badge>{" "}
              <span className="text-muted-foreground">nic nie zmieniać; dobry materiał na wspólny przegląd notatek dla zespołu.</span>
            </p>
            <p>
              <Badge variant="warning" size="sm">Pomóż z jakością</Badge>{" "}
              <span className="text-muted-foreground">pracuje dużo, a CV nie przechodzą: DL przegląda 3 ostatnie notatki i odrzucenia, sprawdza dobór kandydatów do wymagań.</span>
            </p>
            <p>
              <Badge variant="info" size="sm">Skutecznie, ale mało</Badge>{" "}
              <span className="text-muted-foreground">wynik jest, czasu w pracy mało: więcej rozmów, kandydaci z „Propozycji z bazy”.</span>
            </p>
            <p>
              <Badge variant="danger" size="sm">Za mało pracy</Badge>{" "}
              <span className="text-muted-foreground">rozmowa 1:1, wspólny plan dnia, sprawdzenie po tygodniu.</span>
            </p>
          </Card>
        </div>
      ) : null}
    </div>
  );
}

function Quadrant({ data }: { data: WorkRhythmResponse }) {
  const W = 640;
  const H = 320;
  const pad = 34;
  const rules = data.rules;
  const resultsCap = 200;
  const x = (v: number) => pad + (v / 100) * (W - pad * 2);
  const y = (v: number) => H - pad - (Math.min(v, resultsCap) / resultsCap) * (H - pad * 2);
  const dots = data.people.filter((p) => p.index !== null && p.results_pct !== null && p.results_pct !== undefined);
  return (
    <Card className="min-w-0 p-4">
      <p className="text-sm font-semibold text-foreground">Intensywność × wyniki</p>
      <p className="mb-2 text-xs text-muted-foreground">Oś X: intensywność. Oś Y: CV do klienta wobec mediany zespołu.</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Intensywność a wyniki">
        <rect x={x(rules.diag_intensity)} y={y(rules.diag_results_pct)} width={W - pad - x(rules.diag_intensity)} height={H - pad - y(rules.diag_results_pct)} className="fill-warning/15" />
        <rect x={pad} y={y(rules.diag_results_pct)} width={x(rules.diag_intensity) - pad} height={H - pad - y(rules.diag_results_pct)} className="fill-destructive/10" />
        <rect x={pad} y={pad} width={x(rules.diag_intensity) - pad} height={y(rules.diag_results_pct) - pad} className="fill-info/10" />
        <rect x={x(rules.diag_intensity)} y={pad} width={W - pad - x(rules.diag_intensity)} height={y(rules.diag_results_pct) - pad} className="fill-success/10" />
        <line x1={pad} x2={W - pad} y1={H - pad} y2={H - pad} className="stroke-muted-foreground/40" />
        <line x1={pad} x2={pad} y1={pad} y2={H - pad} className="stroke-muted-foreground/40" />
        <text x={W - pad - 4} y={pad + 12} textAnchor="end" className="fill-success-muted-foreground text-[11px] font-semibold">wzór</text>
        <text x={pad + 4} y={pad + 12} className="fill-info-muted-foreground text-[10px] font-semibold">skutecznie, ale mało</text>
        <text x={W - pad - 4} y={H - pad - 6} textAnchor="end" className="fill-warning-muted-foreground text-[10px] font-semibold">pomóż z jakością</text>
        <text x={pad + 4} y={H - pad - 6} className="fill-destructive-muted-foreground text-[10px] font-semibold">za mało pracy</text>
        {[0, 50, 100].map((t) => (
          <text key={t} x={x(t)} y={H - pad + 13} textAnchor="middle" className="fill-muted-foreground text-[10px]">{t}</text>
        ))}
        {[0, 50, 100, 150, 200].map((t) => (
          <text key={t} x={pad - 5} y={y(t) + 3} textAnchor="end" className="fill-muted-foreground text-[10px]">{t}%</text>
        ))}
        {dots.map((p) => {
          const pct = p.results_pct as number;
          const idx = p.index as number;
          const right = idx > 85;
          return (
            <g key={p.user_id}>
              <circle cx={x(idx)} cy={y(pct)} r={4} className="fill-primary" />
              <text x={x(idx) + (right ? -6 : 6)} y={y(pct) + 3} textAnchor={right ? "end" : "start"} className="fill-foreground text-[10px]">
                {p.name}
                {pct > resultsCap ? ` (${pct}%)` : ""}
              </text>
            </g>
          );
        })}
      </svg>
    </Card>
  );
}

function shiftIso(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Okno o 2 tygodnie wcześniej / później; „Dziś” wraca do domyślnego. */
function WindowNav({ data, onChange }: { data: WorkRhythmResponse; onChange: (end: string | null) => void }) {
  const atStart = data.from <= "2026-10-12";
  return (
    <div className="inline-flex items-center gap-1 text-sm">
      <Button size="sm" variant="outline" disabled={atStart} onClick={() => onChange(shiftIso(data.from, -1))} aria-label="Wcześniejsze dni">
        ‹
      </Button>
      <span className="px-1 text-xs tabular-nums text-muted-foreground">
        {fmtDay(data.from)} – {fmtDay(data.to)}
      </span>
      <Button size="sm" variant="outline" onClick={() => onChange(shiftIso(data.to, 14))} aria-label="Późniejsze dni">
        ›
      </Button>
      <Button size="sm" variant="ghost" onClick={() => onChange(null)}>
        Dziś
      </Button>
    </div>
  );
}

// ── Zakładka ────────────────────────────────────────────────────────────────

export function RytmDniaView() {
  const params = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [editing, setEditing] = React.useState(false);
  // `do` = ostatni dzień okna; serwer bierze 10 dni roboczych wstecz, nie przed 12.10.
  const windowEnd = /^\d{4}-\d{2}-\d{2}$/.test(params.get("do") ?? "") ? params.get("do") : null;
  const { data, isPending, isError, isSuccess, error, refetch } = useQuery({
    queryKey: workRhythmQueryKeys.window(null, windowEnd),
    queryFn: () => workRhythmApi.get(windowEnd ? { date_to: windowEnd } : {}),
  });

  const raw = params.get("widok");
  const mode: Mode = raw === "okres" || raw === "intensywnosc" ? raw : "dzien";
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params.toString());
    next.set("tab", "rytm");
    if (value === null) next.delete(key);
    else next.set(key, value);
    if (key === "do") next.delete("dzien");
    replaceUrl(`/insights?${next.toString()}`);
  };

  if (isPending) return <PanelLoading />;
  if (isError || !data) {
    return <SectionError label="Rytm dnia" error={error} onRetry={() => void refetch()} />;
  }

  const days = data.days;
  const date = days.includes(params.get("dzien") ?? "") ? (params.get("dzien") as string) : days[days.length - 1];
  const today = data.people.map((p) => p.days.find((d) => d.date === date)).filter((d): d is WorkRhythmDay => Boolean(d));
  const counted = today.filter((d) => !isOff(d));
  const working = counted.filter((d) => d.first);
  const onLeave = today.filter((d) => !d.before_start && d.leave >= 1).length;
  const medStart = median(working.map((d) => toMin(d.first!)));
  const medEnd = median(working.map((d) => toMin(d.last!)));
  const medIdx = median(counted.map((d) => d.index ?? 0));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-bold tracking-tight text-foreground">Kiedy i jak intensywnie zespół pracuje w NEXUSIE</h2>
          <p className="text-sm text-muted-foreground">
            Punkty pracy godzina po godzinie i wskaźnik intensywności przy każdej osobie. Widzą to tylko Head of Recruitment i admin.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <WindowNav data={data} onChange={(end) => setParam("do", end)} />
          <ModeSwitch mode={mode} onChange={(m) => setParam("widok", m)} />
        </div>
      </div>

      {isSuccess && data.people.length === 0 ? (
        <p className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
          Brak aktywnych rekruterów w tym okresie.
        </p>
      ) : null}

      {data.people.length > 0 && mode === "dzien" ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <CalendarDays className="mr-1 h-4 w-4 text-muted-foreground" />
            {days.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setParam("dzien", d)}
                aria-pressed={d === date}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs tabular-nums",
                  d === date ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:bg-muted",
                )}
              >
                {fmtDay(d)}
              </button>
            ))}
          </div>
          <StatCardGrid>
            <StatCard label="Pracowało w NEXUSIE" value={`${working.length} / ${counted.length}`} sub={onLeave ? `na urlopie: ${onLeave}` : fmtDay(date, true)} icon={Clock} />
            <StatCard label="Start dnia (mediana)" value={medStart !== null ? fromMin(medStart) : "—"} sub="pierwsza akcja z punktami" icon={Sunrise} />
            <StatCard label="Koniec dnia (mediana)" value={medEnd !== null ? fromMin(medEnd) : "—"} sub="ostatnia akcja z punktami" icon={Sunset} />
            <StatCard label="Intensywność zespołu" value={medIdx !== null ? Math.round(medIdx) : "—"} sub="mediana dnia, 0–100" icon={Gauge} />
          </StatCardGrid>
          <Legend rules={data.rules} />
          <DayTable data={data} date={date} />
        </>
      ) : null}

      {data.people.length > 0 && mode === "okres" ? (
        <>
          <Legend rules={data.rules} />
          <div className="grid gap-4 lg:grid-cols-2">
            {data.people.map((p) => (
              <PersonPeriod key={p.user_id} p={p} rules={data.rules} />
            ))}
          </div>
        </>
      ) : null}

      {data.people.length > 0 && mode === "intensywnosc" ? <IntensityBoard data={data} /> : null}

      <RulesPanel rules={data.rules} onEdit={data.can_edit_rules ? () => setEditing(true) : undefined} />
      <p className="text-xs text-muted-foreground">
        Liczymy od 12.10.2026 (start pracy w NEXUSIE), dni robocze {fmtDay(data.from)} – {fmtDay(data.to)}. Bez importów
        i synchronizacji. Spotkania widać u osób z podpiętym kalendarzem Microsoft 365; L4 nie ma w kartotece, więc dzień
        zwolnienia wygląda jak dzień bez pracy.
      </p>
      {data.can_edit_rules ? (
        <RhythmRulesDialog open={editing} onOpenChange={setEditing} rules={data.rules} />
      ) : null}
    </div>
  );
}
