"use client";
// A · Pieniądze — łączy dawną kartę „Stawki finansowe” ze „Szczegółów”,
// zakładkę „Historia stawek” (pusta, odsyłała do „Szczegółów”) i „Faktury”.
// Na górze trzy liczby z odpowiednikiem miesięcznym, pod nimi stawki w czasie
// (wykres schodkowy + zwarta tabela kroków bez wpisów zastąpionych tego samego
// dnia), umowa ramowa i porównanie jednym zdaniem w tej samej jednostce co
// liczby, potem faktury konsultanta z KSeF i wcześniejsze stawki u klienta.
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Plus } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ds/StatusDot";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE, CALM_UNIT } from "@/lib/calm-table";
import { currencySymbol, rateUnitSuffix } from "@/lib/money";
import { cn } from "@/lib/utils";
import {
  useMkAmendments,
  useMkBenchmark,
  useMkContract,
  useMkRateHistory,
  type MkAmendment,
  type MkContract,
  type MkRateStep,
} from "../shared/data";
import { fmtDate, fmtPln, plural, today } from "../shared/format";
import { KsefChecks, KsefInvoiceTable, KSEF_EMPTY, useKsefInvoices } from "./FakturyB";
import type { TabProps } from "./types";

type MoneyContract = MkContract & {
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
};

type Benchmark = {
  contract_rate_monthly?: number | null;
  internal_median_monthly?: number | null;
  internal_sample_size?: number | null;
  market_median?: number | null;
  role_used?: string | null;
};

interface RateHistoryRow {
  id: number;
  rate: number | null;
  currency: string | null;
  contract_type: string;
  start_date: string;
  end_date: string | null;
  notes: string | null;
}

interface CompetenceCategory {
  slug: string;
  name_pl: string;
}

// ── Liczby i daty ────────────────────────────────────────────────────────────

/** Stawka z groszami; po przeliczeniu MD ÷ 8 bywają trzy miejsca („34,625”). */
function rateNum(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const digits = Math.round(Math.abs(value) * 1000) % 10 === 0 ? 2 : 3;
  return new Intl.NumberFormat("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

function pct(client: number | null, cand: number | null): string | null {
  if (!client || cand == null) return null;
  return `${(((client - cand) / client) * 100).toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;
}

const ms = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
const DAY = 86_400_000;
const isoOf = (t: number) => new Date(t).toISOString().slice(0, 10);

// ── Harmonogram ──────────────────────────────────────────────────────────────

interface LiveStep {
  date: string;
  rate: number;
  sourceOrderId: number | null;
  /** Notatki wszystkich wpisów z tą datą (także zastąpionych) — mówią, skąd zmiana. */
  notes: string[];
}

/** Kroki obowiązujące: przy tej samej dacie wygrywa wpis dodany jako ostatni (jak w backendzie). */
function liveSteps(steps: MkRateStep[] | undefined): { live: LiveStep[]; superseded: number } {
  const sorted = [...(steps ?? [])]
    .filter((s): s is MkRateStep & { effective_from: string } => Boolean(s.effective_from))
    .sort((a, b) => a.effective_from.localeCompare(b.effective_from) || a.id - b.id);
  const byDate = new Map<string, LiveStep>();
  for (const s of sorted) {
    const prev = byDate.get(s.effective_from);
    const notes = [...(prev?.notes ?? []), ...(s.note ? [s.note] : [])];
    byDate.set(s.effective_from, { date: s.effective_from, rate: s.rate, sourceOrderId: s.source_order_id ?? null, notes });
  }
  return { live: [...byDate.values()], superseded: sorted.length - byDate.size };
}

/** Stawka w dniu `date`: ostatni krok nie później; pusty harmonogram → stawka z kontraktu. */
function valueAt(steps: LiveStep[], date: string, fallback: number | null): number | null {
  if (steps.length === 0) return fallback;
  let v: number | null = null;
  for (const s of steps) if (s.date <= date) v = s.rate;
  return v;
}

interface Segment {
  from: string;
  to: string;
  client: number | null;
  cand: number | null;
}

interface StepRow {
  date: string;
  client: number | null;
  cand: number | null;
  clientChanged: boolean;
  candChanged: boolean;
  source: string;
  note: string | null;
  state: "past" | "current" | "planned";
}

function sourceLabel(date: string, client: LiveStep[], amendments: MkAmendment[], hasSteps: boolean): string {
  if (!hasSteps) return "stawka z kontraktu";
  if (client.some((s) => s.date === date && s.sourceOrderId != null)) return "zamówienie";
  if (amendments.some((a) => !a.withdrawn && a.effective_date === date && a.amendment_type.includes("rate"))) return "aneks";
  return "ręcznie";
}

// ── Wykres schodkowy ─────────────────────────────────────────────────────────

function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.round(el.getBoundingClientRect().width));
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.round(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

interface ChartProps {
  segments: Segment[];
  axisStart: string;
  axisEnd: string;
  axisStartLabel: string;
  axisEndLabel: string | null;
  /** Pierwszy krok harmonogramu, gdy zaczyna się po starcie umowy. */
  gapUntil: string | null;
  showMargin: boolean;
}

const H = 184;
const M = { l: 12, r: 12, t: 30, b: 38 };

function RateChart({ segments, axisStart, axisEnd, axisStartLabel, axisEndLabel, gapUntil, showMargin }: ChartProps) {
  const { ref, width: W } = useWidth<HTMLDivElement>(940);
  const [hover, setHover] = useState<{ x: number; seg: Segment } | null>(null);
  const t0 = ms(axisStart);
  const t1 = Math.max(ms(axisEnd), t0 + DAY);
  const plotW = Math.max(W - M.l - M.r, 10);
  const X = (iso: string) => M.l + ((ms(iso) - t0) / (t1 - t0)) * plotW;

  const values = segments.flatMap((s) => [s.client, s.cand]).filter((v): v is number => v != null);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.max(hi * 0.1, 1);
  const yLo = lo - span * 0.5;
  const yHi = hi + span * 0.32;
  const Y = (v: number) => M.t + (1 - (v - yLo) / (yHi - yLo)) * (H - M.t - M.b);
  const baseY = H - M.b;

  const stepPath = (key: "client" | "cand") => {
    let d = "";
    let open = false;
    for (const s of segments) {
      const v = s[key];
      if (v == null) {
        open = false;
        continue;
      }
      d += open ? ` V${Y(v).toFixed(1)} H${X(s.to).toFixed(1)}` : ` M${X(s.from).toFixed(1)} ${Y(v).toFixed(1)} H${X(s.to).toFixed(1)}`;
      open = true;
    }
    return d.trim();
  };

  const bandPath = () => {
    const runs: Segment[][] = [];
    let cur: Segment[] = [];
    for (const s of segments) {
      if (s.client != null && s.cand != null) cur.push(s);
      else if (cur.length) {
        runs.push(cur);
        cur = [];
      }
    }
    if (cur.length) runs.push(cur);
    return runs
      .map((run) => {
        const top = run.map((s, i) => `${i === 0 ? "M" : "L"}${X(s.from).toFixed(1)} ${Y(s.client ?? 0).toFixed(1)} L${X(s.to).toFixed(1)} ${Y(s.client ?? 0).toFixed(1)}`);
        const bottom = [...run].reverse().map((s) => `L${X(s.to).toFixed(1)} ${Y(s.cand ?? 0).toFixed(1)} L${X(s.from).toFixed(1)} ${Y(s.cand ?? 0).toFixed(1)}`);
        return `${top.join(" ")} ${bottom.join(" ")} Z`;
      })
      .join(" ");
  };

  // Etykiety wartości tylko przy zmianach, bez nakładania się.
  const valueLabels: { key: string; x: number; y: number; text: string }[] = [];
  for (const key of ["client", "cand"] as const) {
    let prev: number | null = null;
    let lastX = -Infinity;
    for (const s of segments) {
      const v = s[key];
      if (v != null && v !== prev) {
        const x = Math.min(X(s.from) + 6, W - M.r - 44);
        if (x - lastX >= 56) {
          valueLabels.push({ key: `${key}-${s.from}`, x, y: key === "client" ? Y(v) - 8 : Y(v) + 16, text: rateNum(v) });
          lastX = x;
        }
      }
      prev = v;
    }
  }

  // Daty na osi: start, koniec, a pomiędzy tylko dni zmian (bez kolizji).
  type Tick = { x: number; text: string; sub?: string; anchor: "start" | "middle" | "end" };
  const ticks: Tick[] = [{ x: M.l, text: fmtDate(axisStart), sub: axisStartLabel, anchor: "start" }];
  if (axisEndLabel !== null) ticks.push({ x: W - M.r, text: fmtDate(axisEnd), sub: axisEndLabel, anchor: "end" });
  const span0 = (t: Tick) => (t.anchor === "start" ? [t.x, t.x + 70] : t.anchor === "end" ? [t.x - 70, t.x] : [t.x - 36, t.x + 36]);
  const changeDates = [...new Set(segments.slice(1).map((s) => s.from))];
  for (const d of changeDates) {
    const tick: Tick = { x: X(d), text: fmtDate(d), anchor: "middle" };
    const [a, b] = span0(tick);
    const free = ticks.every((t) => {
      const [c, e] = span0(t);
      return b + 8 < c || a - 8 > e;
    });
    if (free) ticks.push(tick);
  }

  const todayIso = today();
  const todayX = ms(todayIso) >= t0 && ms(todayIso) <= t1 ? X(todayIso) : null;
  const gapW = gapUntil ? X(gapUntil) - M.l : 0;

  const onMove = (e: ReactPointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!box) return;
    const x = Math.min(Math.max(e.clientX - box.left, M.l), W - M.r);
    const date = isoOf(t0 + ((x - M.l) / plotW) * (t1 - t0));
    const seg = [...segments].reverse().find((s) => s.from <= date) ?? segments[0];
    if (seg) setHover({ x, seg });
  };

  const hoverMargin = hover && hover.seg.client != null && hover.seg.cand != null ? hover.seg.client - hover.seg.cand : null;

  return (
    <div ref={ref} className="relative">
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Stawka klienta i kandydata w czasie; wartości w tabeli pod wykresem"
        className="block overflow-visible"
      >
        {gapUntil && gapW > 0 ? <rect x={M.l} y={M.t - 4} width={gapW} height={baseY - M.t + 4} rx={4} className="fill-muted/70" /> : null}
        <line x1={M.l} x2={W - M.r} y1={baseY + 0.5} y2={baseY + 0.5} className="stroke-border" strokeWidth={1} />
        {showMargin ? <path d={bandPath()} className="fill-success/15" /> : null}
        <path d={stepPath("cand")} fill="none" className="stroke-muted-foreground" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <path d={stepPath("client")} fill="none" className="stroke-primary" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {gapUntil && gapW > 150 ? (
          <text x={M.l + gapW / 2} y={(M.t + baseY) / 2 + 4} textAnchor="middle" className="fill-muted-foreground text-[11px]">
            harmonogram bez stawek
          </text>
        ) : null}

        {valueLabels.map((l) => (
          <text key={l.key} x={l.x} y={l.y} className="fill-foreground text-[11px] font-medium tabular-nums">
            {l.text}
          </text>
        ))}

        {ticks.map((t) => (
          <g key={`${t.text}-${t.anchor}`}>
            {t.anchor === "middle" ? <line x1={t.x} x2={t.x} y1={baseY} y2={baseY + 4} className="stroke-border" /> : null}
            <text x={t.x} y={baseY + 15} textAnchor={t.anchor} className="fill-muted-foreground text-[10.5px] tabular-nums">
              {t.text}
            </text>
            {t.sub ? (
              <text x={t.x} y={baseY + 28} textAnchor={t.anchor} className="fill-muted-foreground/80 text-[10px]">
                {t.sub}
              </text>
            ) : null}
          </g>
        ))}

        {todayX != null ? (
          <g>
            <line x1={todayX} x2={todayX} y1={M.t - 12} y2={baseY} className="stroke-foreground/45" strokeWidth={1} />
            <text x={todayX} y={M.t - 16} textAnchor="middle" className="fill-foreground text-[10.5px] font-medium">
              dziś
            </text>
          </g>
        ) : null}

        {hover ? (
          <g pointerEvents="none">
            <line x1={hover.x} x2={hover.x} y1={M.t - 4} y2={baseY} className="stroke-foreground/30" strokeWidth={1} />
            {hover.seg.client != null ? (
              <circle cx={hover.x} cy={Y(hover.seg.client)} r={4} className="fill-primary stroke-card" strokeWidth={2} />
            ) : null}
            {hover.seg.cand != null ? (
              <circle cx={hover.x} cy={Y(hover.seg.cand)} r={4} className="fill-muted-foreground stroke-card" strokeWidth={2} />
            ) : null}
          </g>
        ) : null}

        <rect
          x={M.l}
          y={M.t - 12}
          width={plotW}
          height={baseY - M.t + 12}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>

      {hover ? (
        <div
          className="pointer-events-none absolute top-0 z-10 w-[208px] rounded-lg border border-border bg-card px-3 py-2 text-[12px] shadow-md"
          style={{ left: Math.min(Math.max(hover.x + 12, 0), W - 216) }}
        >
          <p className="mb-1 text-[11px] text-muted-foreground">
            od {fmtDate(hover.seg.from)}
            {hover.seg.to !== axisEnd ? ` do ${fmtDate(isoOf(ms(hover.seg.to) - DAY))}` : ""}
          </p>
          {hover.seg.client == null && hover.seg.cand == null ? (
            <p className="text-muted-foreground">Harmonogram nie ma tu stawek.</p>
          ) : (
            <ul className="space-y-0.5">
              <li className="flex items-center gap-2">
                <span aria-hidden className="h-0.5 w-3 rounded-full bg-primary" />
                <span className="w-14 text-right font-semibold tabular-nums text-foreground">{rateNum(hover.seg.client)}</span>
                <span className="text-muted-foreground">klient płaci</span>
              </li>
              <li className="flex items-center gap-2">
                <span aria-hidden className="h-0.5 w-3 rounded-full bg-muted-foreground" />
                <span className="w-14 text-right font-semibold tabular-nums text-foreground">{rateNum(hover.seg.cand)}</span>
                <span className="text-muted-foreground">konsultant</span>
              </li>
              {showMargin && hoverMargin != null ? (
                <li className="flex items-center gap-2">
                  <span aria-hidden className="h-2 w-3 rounded-sm bg-success/25" />
                  <span className="w-14 text-right font-semibold tabular-nums text-foreground">{rateNum(hoverMargin)}</span>
                  <span className="text-muted-foreground">marża · {pct(hover.seg.client, hover.seg.cand)}</span>
                </li>
              ) : null}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ── Klocki ───────────────────────────────────────────────────────────────────

function Card({ title, aside, children, className }: { title: string; aside?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-xl border border-border bg-card p-4 shadow-xs", className)}>
      <div className="mb-2 flex min-h-8 items-center justify-between gap-3">
        <h2 className="text-[13.5px] font-semibold text-foreground">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Figure({ label, value, unit, monthly, accent = false }: { label: string; value: string; unit: string; monthly: string; accent?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-[12px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 flex items-baseline gap-1.5">
        <span className={cn("text-[26px] font-semibold leading-8 tracking-tight", accent ? "text-success" : "text-foreground")}>{value}</span>
        <span className="text-[12px] text-muted-foreground">{unit}</span>
      </p>
      <p className="text-[13px] text-foreground">
        {monthly}
        <span className="text-muted-foreground"> / mies.</span>
      </p>
    </div>
  );
}

// ── Zakładka ─────────────────────────────────────────────────────────────────

export function PieniadzeA({ contractId }: TabProps) {
  const contract = useMkContract(contractId).data as MoneyContract | undefined;
  const benchQ = useMkBenchmark(contractId);
  const historyQ = useMkRateHistory(contractId);
  const amendments = useMkAmendments(contractId).data ?? [];
  const categories = useQuery<CompetenceCategory[]>({
    queryKey: ["mk-competence-categories"],
    queryFn: () => api.get<CompetenceCategory[]>("/api/competence-categories").then((r) => r.data),
    staleTime: Infinity,
  }).data;
  const ksef = useKsefInvoices(contractId, contract?.start_date, Boolean(contract));
  if (!contract) return null;
  const c = contract;

  const clientCur = c.rate_client_currency || c.currency || "PLN";
  const candCur = c.rate_candidate_currency || c.currency || "PLN";
  const sameCurrency = clientCur.toUpperCase() === candCur.toUpperCase();
  const unit = (cur: string) => `${currencySymbol(cur)}${rateUnitSuffix(c.rate_unit)}`;
  const hours = c.billing_hours_per_month ?? 168;
  const hourly = c.rate_unit === "hourly";
  const monthly = (fromApi: number | null | undefined, rate: number | null) => fromApi ?? (hourly && rate != null ? rate * hours : null);
  const margin = sameCurrency && c.rate_client != null && c.rate_candidate != null ? c.rate_client - c.rate_candidate : null;

  // Harmonogram → kroki obowiązujące, wiersze tabeli i odcinki wykresu.
  const client = liveSteps(c.client_rate_schedule);
  const cand = liveSteps(c.candidate_rate_schedule);
  const framework = liveSteps(c.framework_rate_schedule);
  const hasSteps = client.live.length + cand.live.length > 0;
  const start = c.start_date ?? [...client.live, ...cand.live].map((s) => s.date).sort()[0] ?? today();
  const firstStep = hasSteps ? [...client.live, ...cand.live].map((s) => s.date).sort()[0] : null;
  const gapUntil = firstStep && firstStep > start && client.live.length > 0 && cand.live.length > 0 ? firstStep : null;
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
  const todayIso = today();
  const stepDates = [...new Set([...client.live, ...cand.live].map((s) => s.date))].sort();
  const lastStep = stepDates[stepDates.length - 1];
  const axisStart = start < (firstStep ?? start) ? start : (firstStep ?? start);
  const axisEnd = [todayIso, orderEnd, lastStep && lastStep > todayIso ? isoOf(ms(lastStep) + 31 * DAY) : null]
    .filter((d): d is string => Boolean(d))
    .sort()
    .reverse()[0];
  const breaks = [...new Set([axisStart, ...stepDates.filter((d) => d > axisStart && d < axisEnd)])].sort();
  const segments: Segment[] = breaks.map((from, i) => ({
    from,
    to: breaks[i + 1] ?? axisEnd,
    client: valueAt(client.live, from, c.rate_client),
    cand: valueAt(cand.live, from, c.rate_candidate),
  }));

  const rowDates = stepDates.length ? stepDates : [start];
  const currentDate = [...rowDates].reverse().find((d) => d <= todayIso) ?? null;
  const rows: StepRow[] = rowDates.map((date, i): StepRow => {
    const prev = i > 0 ? rowDates[i - 1] : null;
    const cl = valueAt(client.live, date, c.rate_client);
    const ca = valueAt(cand.live, date, c.rate_candidate);
    const notes = [...new Set([...client.live, ...cand.live].filter((s) => s.date === date).flatMap((s) => s.notes))].filter(
      (n) => n !== "Z zamówienia klienta",
    );
    return {
      date,
      client: cl,
      cand: ca,
      clientChanged: !prev || valueAt(client.live, prev, c.rate_client) !== cl,
      candChanged: !prev || valueAt(cand.live, prev, c.rate_candidate) !== ca,
      source: sourceLabel(date, client.live, amendments, hasSteps),
      note: notes.join(" · ") || null,
      state: date > todayIso ? "planned" : date === currentDate ? "current" : "past",
    };
  });
  const superseded = client.superseded + cand.superseded;
  const supersededWhere = [
    client.superseded ? "klient" : null,
    cand.superseded ? "kandydat" : null,
  ].filter(Boolean).join(", ");
  const currentFrom = currentDate && hasSteps ? currentDate : null;

  // Umowa ramowa: jedna linia, ostrzeżenie tylko gdy klient płaci więcej niż ramowa.
  const fwNow = [...framework.live].reverse().find((s) => s.date <= todayIso) ?? framework.live[0];
  const fwRate = c.framework_rate ?? fwNow?.rate ?? null;
  const fwTo = c.framework_rate_schedule?.find((s) => s.effective_from === fwNow?.date)?.effective_to ?? null;
  const fwOver = fwRate != null && c.rate_client != null && sameCurrency && c.rate_client > fwRate ? c.rate_client - fwRate : null;

  // Porównanie: jedno zdanie, w złotych miesięcznie jak druga linia liczb.
  const bench = benchQ.data as Benchmark | undefined;
  const role = bench?.role_used ? categories?.find((k) => k.slug === bench.role_used)?.name_pl ?? null : null;
  let benchLine: string;
  if (benchQ.isLoading) benchLine = "Ładowanie porównania…";
  else if (benchQ.isError || !bench) benchLine = "Porównania nie udało się pobrać.";
  else if (!bench.internal_median_monthly || !bench.internal_sample_size || !bench.contract_rate_monthly)
    benchLine = "Do porównania nie ma jeszcze innych naszych umów z tą rolą.";
  else {
    const diff = Math.round(((bench.contract_rate_monthly - bench.internal_median_monthly) / bench.internal_median_monthly) * 100);
    const forRole = role ? ` dla roli ${role}` : " dla tej roli";
    const sample = plural(bench.internal_sample_size, ["umowy", "umów", "umów"]);
    const market = bench.market_median ? `; rynek ${fmtPln(bench.market_median)}/mies.` : "; danych rynkowych brak";
    benchLine =
      diff === 0
        ? `Stawka klienta (${fmtPln(bench.contract_rate_monthly)}/mies.) jest równa naszej medianie${forRole} z ${sample}${market}.`
        : `Stawka klienta (${fmtPln(bench.contract_rate_monthly)}/mies.) jest o ${Math.abs(diff)} % ${diff > 0 ? "wyższa od" : "niższa od"} naszej mediany${forRole}: ${fmtPln(
            bench.internal_median_monthly,
          )}/mies. z ${sample}${market}.`;
  }

  const history = (historyQ.data ?? []) as unknown as RateHistoryRow[];
  const cell = "py-2 pr-4";

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,330px)] gap-6">
          <div>
            <div className="grid grid-cols-3 gap-4">
              <Figure label="Klient płaci" value={rateNum(c.rate_client)} unit={unit(clientCur)} monthly={fmtPln(monthly(c.monthly_rate_client, c.rate_client))} />
              <Figure label="Konsultant dostaje" value={rateNum(c.rate_candidate)} unit={unit(candCur)} monthly={fmtPln(monthly(c.monthly_rate_candidate, c.rate_candidate))} />
              <Figure
                label="Marża"
                value={rateNum(margin)}
                unit={margin != null ? `${unit(clientCur)} · ${pct(c.rate_client, c.rate_candidate)}` : "różne waluty"}
                monthly={fmtPln(margin != null ? monthly(c.monthly_margin, margin) : null)}
                accent={margin != null && margin > 0}
              />
            </div>
            <p className="mt-3 text-[12px] text-muted-foreground">
              {hourly ? `Miesięcznie przy ${hours} h` : "Miesięcznie wg jednostki kontraktu"}
              {currentFrom ? ` · stawki obowiązują od ${fmtDate(currentFrom)}` : ""}
            </p>
          </div>
          <dl className="space-y-2.5 border-l border-border/70 pl-5 text-[12.5px] leading-5">
            <div>
              <dt className="text-[11.5px] text-muted-foreground">Umowa ramowa</dt>
              <dd className="text-foreground">
                {fwRate != null ? (
                  <>
                    <span className="font-medium tabular-nums">
                      {rateNum(fwRate)} {unit(clientCur)}
                    </span>
                    {fwTo ? <span className="text-muted-foreground"> do {fmtDate(fwTo)}</span> : null}
                    {fwOver != null ? (
                      <span className="mt-0.5 flex items-center gap-1 font-medium text-warning-muted-foreground">
                        <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
                        Stawka klienta wyższa o {rateNum(fwOver)} {unit(clientCur)}
                      </span>
                    ) : c.rate_client != null ? (
                      <span className="text-muted-foreground"> · stawka klienta w limicie</span>
                    ) : null}
                  </>
                ) : (
                  <span className="text-muted-foreground">bez stawki ramowej</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-[11.5px] text-muted-foreground">Porównanie</dt>
              <dd className="text-foreground">{benchLine}</dd>
            </div>
          </dl>
        </div>
      </section>

      <Card
        title="Stawki w czasie"
        aside={
          <ul className="flex items-center gap-4 text-[12px] text-muted-foreground">
            <li className="flex items-center gap-1.5">
              <span aria-hidden className="h-0.5 w-4 rounded-full bg-primary" />
              klient płaci
            </li>
            <li className="flex items-center gap-1.5">
              <span aria-hidden className="h-0.5 w-4 rounded-full bg-muted-foreground" />
              konsultant dostaje
            </li>
            {sameCurrency ? (
              <li className="flex items-center gap-1.5">
                <span aria-hidden className="h-2.5 w-4 rounded-sm bg-success/15" />
                marża
              </li>
            ) : null}
          </ul>
        }
      >
        {sameCurrency && segments.some((s) => s.client != null || s.cand != null) ? (
          <RateChart
            segments={segments}
            axisStart={axisStart}
            axisEnd={axisEnd}
            axisStartLabel={axisStart === c.start_date ? "start umowy" : "pierwsza stawka"}
            axisEndLabel={axisEnd === orderEnd ? "koniec zamówienia" : axisEnd === todayIso ? "dziś" : ""}
            gapUntil={gapUntil}
            showMargin
          />
        ) : (
          <p className="mb-2 text-[12.5px] text-muted-foreground">
            {sameCurrency
              ? "Kontrakt nie ma jeszcze stawek — wejdą z zamówienia klienta albo z aneksu."
              : `Klient płaci w ${clientCur}, konsultant dostaje w ${candCur} — wykres na jednej osi byłby mylący, kroki są w tabeli.`}
          </p>
        )}

        <table className="mt-2 w-full text-[13px]">
          <thead>
            <tr className="border-b border-border">
              <th className={cn(CALM_HEAD, cell, "text-left")}>Od</th>
              <th className={cn(CALM_HEAD, cell, "text-right")}>
                Klient płaci<span className={CALM_UNIT}>{unit(clientCur)}</span>
              </th>
              <th className={cn(CALM_HEAD, cell, "text-right")}>
                Konsultant<span className={CALM_UNIT}>{unit(candCur)}</span>
              </th>
              <th className={cn(CALM_HEAD, cell, "text-right")}>
                Marża<span className={CALM_UNIT}>{sameCurrency ? unit(clientCur) : ""}</span>
              </th>
              <th className={cn(CALM_HEAD, "py-2 pl-4 text-left")}>Źródło</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const m = sameCurrency && r.client != null && r.cand != null ? r.client - r.cand : null;
              return (
                <tr key={r.date} className={cn(CALM_ROW, "align-middle")}>
                  <td className={cn(cell, "whitespace-nowrap")}>
                    <span className={cn("tabular-nums", r.state === "current" ? "font-medium text-foreground" : "text-foreground")}>{fmtDate(r.date)}</span>
                    {r.state === "current" ? (
                      <StatusDot tone="success" className="mt-0.5 flex">
                        obowiązuje
                      </StatusDot>
                    ) : r.state === "planned" ? (
                      <StatusDot tone="info" className="mt-0.5 flex">
                        zaplanowana
                      </StatusDot>
                    ) : null}
                  </td>
                  <td className={cn(cell, CALM_AMOUNT, r.clientChanged ? "font-medium text-foreground" : "text-muted-foreground")}>{rateNum(r.client)}</td>
                  <td className={cn(cell, CALM_AMOUNT, r.candChanged ? "font-medium text-foreground" : "text-muted-foreground")}>{rateNum(r.cand)}</td>
                  <td className={cn(cell, CALM_AMOUNT, "text-foreground")}>
                    {rateNum(m)}
                    {m != null ? <span className={CALM_SUBLINE}>{pct(r.client, r.cand)}</span> : null}
                  </td>
                  <td className="max-w-[360px] py-2 pl-4">
                    <span className="text-foreground">{r.source}</span>
                    {r.note ? (
                      <span className={cn(CALM_SUBLINE, "truncate")} title={r.note}>
                        {r.note}
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {superseded > 0 || gapUntil ? (
          <p className="mt-2 text-[12px] text-muted-foreground">
            {superseded > 0
              ? `Pominięto ${plural(superseded, ["wpis zastąpiony", "wpisy zastąpione", "wpisów zastąpionych"])} tego samego dnia (${supersededWhere}).`
              : null}
            {superseded > 0 && gapUntil ? " " : null}
            {gapUntil ? `Umowa trwa od ${fmtDate(start)}, a harmonogram stawek zaczyna się ${fmtDate(gapUntil)}.` : null}
          </p>
        ) : null}
      </Card>

      <Card
        title="Faktury konsultanta"
        aside={
          <Button type="button" variant="ghost" size="sm">
            <Plus className="mr-1 size-3.5" aria-hidden />
            Dodaj fakturę
          </Button>
        }
      >
        {ksef.isLoading ? (
          <p className="text-[13px] text-muted-foreground">Ładowanie faktur z KSeF…</p>
        ) : ksef.error ? (
          <p role="alert" className="text-[13px] text-destructive">
            {ksef.error}
          </p>
        ) : ksef.invoices.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{KSEF_EMPTY}</p>
        ) : (
          <>
            <KsefInvoiceTable invoices={ksef.invoices} candidateName={c.candidate_name} />
            <KsefChecks checks={ksef.checks} />
          </>
        )}
      </Card>

      <section className="rounded-xl border border-border bg-card px-4 py-3 shadow-xs">
        <h2 className="text-[13.5px] font-semibold text-foreground">Inne kontrakty tej osoby u klienta</h2>
        {historyQ.isLoading ? (
          <p className="mt-1 text-[13px] text-muted-foreground">Ładowanie…</p>
        ) : historyQ.isError ? (
          <p role="alert" className="mt-1 text-[13px] text-destructive">
            Nie udało się pobrać wcześniejszych stawek.
          </p>
        ) : history.length === 0 ? (
          <p className="mt-1 text-[13px] text-muted-foreground">Wcześniejszych stawek tej osoby u {c.client_name} nie zapisano.</p>
        ) : (
          <ul className="mt-1 divide-y divide-border/60">
            {history.map((h) => (
              <li key={h.id} className="flex items-baseline gap-4 py-2 text-[13px]">
                <span className="w-[190px] shrink-0 tabular-nums text-foreground">
                  {fmtDate(h.start_date)} – {h.end_date ? fmtDate(h.end_date) : "dziś"}
                </span>
                <span className="w-16 shrink-0 uppercase text-muted-foreground">{h.contract_type}</span>
                <span className="w-28 shrink-0 text-right tabular-nums text-foreground">
                  {rateNum(h.rate)} {currencySymbol(h.currency)}
                </span>
                <span className="min-w-0 truncate text-muted-foreground" title={h.notes ?? undefined}>
                  {h.notes ?? ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
