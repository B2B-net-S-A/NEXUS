"use client";
// A · Analityka kontraktów — „Co się zmieni”. Zamiast czterech dużych kafli,
// dwunastu prawie równych słupków i dwóch tabel z uciętą kolumną marży:
// rząd czterech liczb z jednym zdaniem, „Najbliższe 3 miesiące” (kto kończy,
// kto startuje i ile marży to zabiera albo dodaje), smukła linia prognozy
// marży z osią przyciętą do zakresu zmian i jedna tabela „Top klienci”.
// Macierz „Rola × Klient” pominięta — rolą jest tytuł rekrutacji, więc to
// setki wierszy po jednej osobie (patrz raport makiety).
import { useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, TrendingDown, TrendingUp } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE, CALM_UNIT } from "@/lib/calm-table";
import { useMkContractList, type MkListItem } from "../shared/data";
import {
  fmtDate,
  fmtMonthShort,
  fmtPln,
  OSOBY,
  plural,
  relDays,
  terminationReasonLabel,
  today,
} from "../shared/format";

// ── Dane (te same trasy co dzisiejszy ekran, tylko GET) ────────────────────

export interface MkMarginTotals {
  clients: number;
  active_contracts: number;
  total_monthly_revenue: number;
  total_monthly_margin: number;
  margin_pct: number | null;
  fx_missing: boolean;
  contracts_without_cost_leg?: number;
  contracts_without_revenue_leg?: number;
}

export interface MkUtilization {
  total_candidates: number;
  candidates_active: number;
  active_contracts: number;
  candidates_on_bench: number;
  utilization_pct: number | null;
  avg_bench_days: number | null;
}

export interface MkForecastMonth {
  month: string;
  month_label: string;
  revenue: number;
  margin: number;
  active_count: number;
}

export interface MkForecast {
  horizon_months: number;
  months: MkForecastMonth[];
  fx_missing?: boolean;
  fx_warnings?: string[];
}

export interface MkMarginRow {
  client_id?: number;
  client_name?: string;
  candidate_id?: number;
  candidate_name?: string;
  active_contracts: number;
  total_monthly_margin: number;
  total_monthly_revenue: number;
  margin_pct: number | null;
  fx_missing?: boolean;
  contracts_without_cost_leg?: number;
  contracts_without_revenue_leg?: number;
}

/** Pozycja listy kontraktów z walutami nóg (lista je zwraca, typ wspólny ich nie ma). */
export type MkWindowContract = MkListItem & {
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
};

const getJson = <T,>(url: string, params?: Record<string, unknown>) =>
  api.get<T>(url, { params }).then((r) => r.data);

export function useMkAnalytics() {
  const totals = useQuery<MkMarginTotals>({
    queryKey: ["mk-ca-margin-totals"],
    queryFn: () => getJson<MkMarginTotals>("/api/contract-analytics/margin-totals"),
  });
  const util = useQuery<MkUtilization>({
    queryKey: ["mk-ca-utilization"],
    queryFn: () => getJson<MkUtilization>("/api/contract-analytics/utilization"),
  });
  const forecast = useQuery<MkForecast>({
    queryKey: ["mk-ca-forecast"],
    queryFn: () => getJson<MkForecast>("/api/contract-analytics/revenue-forecast"),
  });
  // Wszyscy klienci (27), nie ranking 20 — tabela B potrzebuje kompletu,
  // A bierze pierwszą dziesiątkę.
  const clients = useQuery<MkMarginRow[]>({
    queryKey: ["mk-ca-margin-by-client", 100],
    queryFn: () => getJson<MkMarginRow[]>("/api/contract-analytics/margin-by-client", { limit: 100 }),
  });
  return { totals, util, forecast, clients };
}

/** Okno „najbliższe 3 miesiące” — 90 dni, jak filtr „kończy się w 90 dni”. */
export const WINDOW_DAYS = 90;

export function addDays(iso: string, days: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10);
}

/** Kontrakty kończące się i startujące w oknie — te same filtry co lista `/contracts`. */
export function useMkNext90() {
  const t = today();
  const ending = useMkContractList(
    { status: ["active", "ending"], expiring_in_days: WINDOW_DAYS, page_size: 100 },
    `analityka-konczace-${WINDOW_DAYS}-${t}`,
  );
  const starting = useMkContractList(
    { status: ["active", "ending"], start_from: addDays(t, 1), start_to: addDays(t, WINDOW_DAYS), page_size: 100 },
    `analityka-startujace-${WINDOW_DAYS}-${t}`,
  );
  return { ending, starting, until: addDays(t, WINDOW_DAYS) };
}

const MD_PER_MONTH = 21;

/**
 * Marża miesięczna kontraktu ze stawek z listy — ta sama reguła co backend
 * (`Contract.monthly_rate`): h × godziny rozliczeniowe (domyślnie 168), MD × 21,
 * miesięczna bez zmian. Inna waluta niż PLN albo brak stawki → `null`
 * (nie przeliczamy kursem i nie udajemy zera).
 */
export function monthlyMargin(c: MkWindowContract): number | null {
  if (c.monthly_margin != null) return c.monthly_margin;
  if (c.rate_client == null || c.rate_candidate == null) return null;
  const cur = (c.rate_client_currency ?? c.currency ?? "PLN").toUpperCase();
  const curCand = (c.rate_candidate_currency ?? c.currency ?? "PLN").toUpperCase();
  if (cur !== "PLN" || curCand !== "PLN") return null;
  const factor =
    c.rate_unit === "monthly" ? 1 : c.rate_unit === "daily" ? MD_PER_MONTH : (c.billing_hours_per_month ?? 168);
  return (c.rate_client - c.rate_candidate) * factor;
}

export function sumKnown(values: (number | null)[]): number {
  return values.reduce<number>((acc, v) => acc + (v ?? 0), 0);
}

// ── Formatowanie ───────────────────────────────────────────────────────────

/** „8 823 958” — kwota bez waluty (jednostka stoi w nagłówku kolumny). */
export function fmtInt(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return fmtPln(value).replace(/\s*zł$/, "");
}

/** „−75 432 zł” / „+47 321 zł” — ze znakiem minus, nie dywizem. */
export function signedPln(value: number): string {
  return `${value < 0 ? "−" : "+"}${fmtPln(Math.abs(value))}`;
}

/** „22,9 %”. */
export function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;
}

function fmtMln(value: number): string {
  return `${(value / 1_000_000).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} mln zł`;
}

// ── Wspólne klocki A i B ───────────────────────────────────────────────────

export function AnalyticsHead({ subtitle, right }: { subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <header className="space-y-1">
      <Link
        href="/contracts"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Kontrakty
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">Analityka kontraktów</h1>
          {subtitle ? <p className="text-[13px] text-muted-foreground">{subtitle}</p> : null}
        </div>
        {right}
      </div>
    </header>
  );
}

export function QueryLine({ error, children }: { error?: boolean; children: ReactNode }) {
  return (
    <p className={cn("px-4 py-6 text-[13px]", error ? "text-destructive" : "text-muted-foreground")}>{children}</p>
  );
}

// ── Rząd czterech liczb ────────────────────────────────────────────────────

function Figure({ label, value, note }: { label: string; value: ReactNode; note: ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <p className="text-[11.5px] leading-4 text-muted-foreground">{label}</p>
      <p className="font-display text-[20px] font-semibold leading-7 tabular-nums text-foreground">{value}</p>
      <p className="text-[11.5px] leading-4 text-muted-foreground">{note}</p>
    </div>
  );
}

function KeyFigures({ totals, util }: { totals: ReturnType<typeof useMkAnalytics>["totals"]; util: ReturnType<typeof useMkAnalytics>["util"] }) {
  const t = totals.data;
  const u = util.data;
  const waiting = (failed: boolean) => (failed ? "Nie udało się pobrać" : "Ładowanie…");
  const withoutRevenue = t?.contracts_without_revenue_leg ?? 0;
  return (
    <section
      aria-label="Najważniejsze liczby"
      className="grid grid-cols-4 divide-x divide-border/60 rounded-xl border border-border bg-card shadow-xs"
    >
      <Figure
        label="Marża miesięcznie"
        value={t && !t.fx_missing ? fmtPln(t.total_monthly_margin) : "—"}
        note={
          t ? (
            <>
              {fmtPct(t.margin_pct)} przychodu
              {withoutRevenue > 0 ? (
                <span className="block" title="Kontrakty bez stawki klienta nie wchodzą do przychodu ani marży">
                  {plural(withoutRevenue, ["kontrakt", "kontrakty", "kontraktów"])} bez stawki poza sumą
                </span>
              ) : null}
            </>
          ) : (
            waiting(totals.isError)
          )
        }
      />
      <Figure
        label="Przychód miesięcznie"
        value={t && !t.fx_missing ? fmtPln(t.total_monthly_revenue) : "—"}
        note={t ? `${plural(t.active_contracts, ["kontrakt", "kontrakty", "kontraktów"])} u ${plural(t.clients, ["klienta", "klientów", "klientów"])}` : waiting(totals.isError)}
      />
      <Figure
        label="Utylizacja"
        value={u ? fmtPct(u.utilization_pct) : "—"}
        note={u ? `${u.candidates_active} z ${u.total_candidates} konsultantów pracuje` : waiting(util.isError)}
      />
      <Figure
        label="Ławka"
        value={u ? plural(u.candidates_on_bench, OSOBY) : "—"}
        note={
          u
            ? u.avg_bench_days != null
              ? `średnio ${Math.round(u.avg_bench_days)} dni bez kontraktu`
              : "bez danych o czasie na ławce"
            : waiting(util.isError)
        }
      />
    </section>
  );
}

// ── Najbliższe 3 miesiące ──────────────────────────────────────────────────

type WindowQuery = ReturnType<typeof useMkNext90>["ending"];

function sortWindow(items: MkWindowContract[], dateKey: "end_date" | "start_date"): MkWindowContract[] {
  return [...items].sort(
    (a, b) =>
      (a[dateKey] ?? "").localeCompare(b[dateKey] ?? "") || (monthlyMargin(b) ?? -1) - (monthlyMargin(a) ?? -1),
  );
}

function endingNote(c: MkWindowContract): string {
  const reason = terminationReasonLabel(c.termination_reason);
  if (reason) return reason.toLowerCase();
  if (c.prolongation_status === "yes") return "klient przedłuża";
  if (c.prolongation_status === "negotiate") return "w negocjacjach";
  return "bez decyzji o przedłużeniu";
}

function WindowRow({ c, kind }: { c: MkWindowContract; kind: "ending" | "starting" }) {
  const date = kind === "ending" ? c.end_date : c.start_date;
  const margin = monthlyMargin(c);
  const note = kind === "ending" ? endingNote(c) : margin == null ? "brak stawek w kontrakcie" : null;
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_96px_88px] items-center gap-3 py-2">
      <div className="min-w-0">
        <Link
          href={`/contracts/${c.id}/makieta?w=a`}
          className="text-[13px] font-medium text-foreground hover:text-primary hover:underline"
        >
          {c.candidate_name}
        </Link>
        <span className={cn(CALM_SUBLINE, "truncate")} title={c.client_name}>
          {c.client_name}
          {note ? ` · ${note}` : ""}
        </span>
      </div>
      <span className="text-right text-[12.5px] tabular-nums text-muted-foreground">
        {margin == null ? "—" : signedPln(kind === "ending" ? -margin : margin)}
      </span>
      <span className="text-right">
        <span className="block text-[12.5px] tabular-nums text-foreground">{fmtDate(date)}</span>
        <span className="block text-[11.5px] text-muted-foreground">{relDays(date)}</span>
      </span>
    </li>
  );
}

function WindowCard({ kind, query }: { kind: "ending" | "starting"; query: WindowQuery }) {
  const [all, setAll] = useState(false);
  const items = useMemo(
    () => sortWindow((query.data?.items ?? []) as MkWindowContract[], kind === "ending" ? "end_date" : "start_date"),
    [query.data, kind],
  );
  const margins = items.map(monthlyMargin);
  const total = sumKnown(margins);
  const unknown = margins.filter((m) => m == null).length;
  const Icon = kind === "ending" ? TrendingDown : TrendingUp;

  let summary: string;
  if (kind === "ending") {
    const decided = items.filter((c) => c.termination_reason || c.prolongation_status === "no").length;
    const extending = items.filter((c) => !c.termination_reason && c.prolongation_status === "yes").length;
    const open = items.length - decided - extending;
    summary = [
      decided ? `${decided} z zapisanym powodem końca` : null,
      open ? `${open} bez decyzji o przedłużeniu` : null,
      extending ? `${extending} klient przedłuża` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  } else {
    summary = unknown
      ? `${plural(unknown, ["kontrakt", "kontrakty", "kontraktów"])} bez stawek — ich marży nie liczymy`
      : "Wszystkie mają stawki klienta i konsultanta";
  }
  const shown = all ? items : items.slice(0, 5);

  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-xs">
      <div className="border-b border-border/60 px-4 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="flex items-center gap-1.5 self-center text-[13.5px] font-semibold text-foreground">
            <Icon className={cn("size-4", kind === "ending" ? "text-warning" : "text-success")} aria-hidden />
            {kind === "ending" ? "Kończą się" : "Startują"}
          </h3>
          {query.isSuccess ? (
            <p className="whitespace-nowrap text-right">
              <span className="font-display text-[20px] font-semibold leading-7 tabular-nums text-foreground">
                {plural(items.length, OSOBY)}
              </span>
              <span className="ml-2 text-[12.5px] tabular-nums text-muted-foreground">
                {items.length ? `${signedPln(kind === "ending" ? -total : total)} marży / mies.` : "bez zmian w marży"}
              </span>
            </p>
          ) : null}
        </div>
        {query.isSuccess && items.length > 0 ? (
          <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{summary}</p>
        ) : null}
      </div>
      {query.isError ? (
        <QueryLine error>Nie udało się pobrać listy kontraktów.</QueryLine>
      ) : !query.isSuccess ? (
        <QueryLine>Ładowanie…</QueryLine>
      ) : items.length === 0 ? (
        <QueryLine>
          {kind === "ending"
            ? "Nikomu nie kończy się umowa w najbliższych 90 dniach."
            : "W najbliższych 90 dniach nie startuje żadna umowa."}
        </QueryLine>
      ) : (
        <>
          <ul className="flex-1 divide-y divide-border/60 px-4">
            {shown.map((c) => (
              <WindowRow key={c.id} c={c} kind={kind} />
            ))}
          </ul>
          {items.length > 5 ? (
            <div className="border-t border-border/60 px-4 py-1.5">
              <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => setAll((v) => !v)}>
                {all ? "Pokaż 5 najbliższych" : `Pokaż wszystkie (${items.length})`}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function NextQuarter() {
  const { ending, starting, until } = useMkNext90();
  const lost = sumKnown(((ending.data?.items ?? []) as MkWindowContract[]).map(monthlyMargin));
  const gained = sumKnown(((starting.data?.items ?? []) as MkWindowContract[]).map(monthlyMargin));
  const ready = ending.isSuccess && starting.isSuccess;
  return (
    <section aria-label="Najbliższe 3 miesiące" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 className="text-[14px] font-semibold text-foreground">
          Najbliższe 3 miesiące <span className="font-normal text-muted-foreground">· do {fmtDate(until)}</span>
        </h2>
        {ready ? (
          <p className="text-[12.5px] text-muted-foreground">
            Bilans marży:{" "}
            <span className="font-semibold tabular-nums text-foreground">{signedPln(gained - lost)} / mies.</span>{" "}
            (z bieżących stawek kontraktów)
          </p>
        ) : null}
      </div>
      <div className="grid grid-cols-2 items-start gap-4">
        <WindowCard kind="ending" query={ending} />
        <WindowCard kind="starting" query={starting} />
      </div>
    </section>
  );
}

// ── Prognoza: smukła linia marży ───────────────────────────────────────────

const PLOT_H = 104;

function ForecastLine({ months }: { months: MkForecastMonth[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const values = months.map((m) => m.margin);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || Math.max(1, Math.abs(max) * 0.01);
  // Oś przycięta do zakresu zmian: najwyższy punkt na 30 % wysokości,
  // najniższy na 80 % — zmiana o 2–3 % nie jest płaską kreską.
  const hi = max + range * 0.6;
  const lo = hi - range * 2;
  const n = months.length;
  const xPct = (i: number) => (n === 1 ? 50 : (i / (n - 1)) * 100);
  const yPx = (v: number) => ((hi - v) / (hi - lo)) * PLOT_H;
  const path = months
    .map((m, i) => `${i === 0 ? "M" : "L"}${(xPct(i) * 10).toFixed(1)},${yPx(m.margin).toFixed(1)}`)
    .join(" ");
  const first = months[0];
  const last = months[n - 1];
  const step = n > 1 ? 100 / (n - 1) : 100;
  const h = hover != null ? months[hover] : null;
  const prev = hover != null && hover > 0 ? months[hover - 1] : null;
  const hx = hover != null ? xPct(hover) : 0;

  return (
    <div className="relative mx-2 mt-2" style={{ height: PLOT_H + 24 }} onMouseLeave={() => setHover(null)}>
      <svg
        viewBox={`0 0 1000 ${PLOT_H}`}
        preserveAspectRatio="none"
        className="absolute inset-x-0 top-0 w-full overflow-visible"
        style={{ height: PLOT_H }}
        aria-hidden
      >
        <path
          d={path}
          fill="none"
          className="stroke-primary"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {/* Oś czasu: kreska, znaczniki miesięcy, podpis tylko pierwszego i ostatniego. */}
      <div className="absolute inset-x-0 border-t border-border" style={{ top: PLOT_H }} />
      {months.map((m, i) => (
        <span
          key={m.month}
          className="absolute h-1 w-px bg-border"
          style={{ left: `${xPct(i)}%`, top: PLOT_H }}
          aria-hidden
        />
      ))}
      <span className="absolute left-0 text-[11.5px] text-muted-foreground" style={{ top: PLOT_H + 6 }}>
        {fmtMonthShort(`${first.month}-01`)}
      </span>
      <span className="absolute right-0 text-[11.5px] text-muted-foreground" style={{ top: PLOT_H + 6 }}>
        {fmtMonthShort(`${last.month}-01`)}
      </span>
      {/* Etykiety tylko na początku i na końcu linii. */}
      {[0, n - 1].map((i) => (
        <span
          key={`dot-${i}`}
          className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-card"
          style={{ left: `${xPct(i)}%`, top: yPx(months[i].margin) }}
          aria-hidden
        />
      ))}
      <span
        className="absolute left-0 whitespace-nowrap text-[12.5px] font-semibold tabular-nums text-foreground"
        style={{ top: yPx(first.margin) - 24 }}
      >
        {fmtPln(first.margin)}
      </span>
      <span
        className="absolute right-0 whitespace-nowrap text-[12.5px] font-semibold tabular-nums text-foreground"
        style={{ top: yPx(last.margin) - 24 }}
      >
        {fmtPln(last.margin)}
      </span>
      {/* Warstwa najechania: kolumna na miesiąc, kreska, kropka i dymek. */}
      {months.map((m, i) => {
        const left = Math.max(0, xPct(i) - step / 2);
        const right = Math.min(100, xPct(i) + step / 2);
        return (
          <span
            key={`hit-${m.month}`}
            className="absolute top-0 cursor-default"
            style={{ left: `${left}%`, width: `${right - left}%`, height: PLOT_H }}
            onMouseEnter={() => setHover(i)}
            aria-hidden
          />
        );
      })}
      {h ? (
        <>
          <span
            className="pointer-events-none absolute top-0 w-px bg-foreground/25"
            style={{ left: `${hx}%`, height: PLOT_H }}
            aria-hidden
          />
          <span
            className="pointer-events-none absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-card"
            style={{ left: `${hx}%`, top: yPx(h.margin) }}
            aria-hidden
          />
          <div
            role="status"
            className={cn(
              "pointer-events-none absolute z-10 w-max rounded-md border border-border bg-popover px-2.5 py-1.5 text-[12px] leading-4 text-popover-foreground shadow-md",
              hx < 15 ? "translate-x-2" : hx > 85 ? "-translate-x-[calc(100%+8px)]" : "-translate-x-1/2",
            )}
            style={{ left: `${hx}%`, top: hx < 15 || hx > 85 ? 0 : -8 }}
          >
            <p className="font-semibold text-foreground">{fmtMonthShort(`${h.month}-01`)}</p>
            <p className="tabular-nums">
              Marża {fmtPln(h.margin)}
              {prev ? (
                <span className="text-muted-foreground"> ({signedPln(h.margin - prev.margin)} wobec poprzedniego)</span>
              ) : null}
            </p>
            <p className="tabular-nums text-muted-foreground">
              Przychód {fmtPln(h.revenue)} · {plural(h.active_count, ["kontrakt", "kontrakty", "kontraktów"])}
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}

function ForecastCard({ query }: { query: ReturnType<typeof useMkAnalytics>["forecast"] }) {
  const f = query.data;
  const months = f?.months ?? [];
  const first = months[0];
  const last = months[months.length - 1];
  const change = first && last ? last.margin - first.margin : null;
  const pct = first && last && first.margin ? ((last.margin - first.margin) / first.margin) * 100 : null;
  const values = months.map((m) => m.margin);
  const scaleFrom = values.length ? Math.max(...values) - (Math.max(...values) - Math.min(...values) || 1) * 1.4 : null;
  return (
    <section className="rounded-xl border border-border bg-card px-4 pb-3 pt-3 shadow-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 className="text-[14px] font-semibold text-foreground">Marża miesięczna — prognoza na 12 miesięcy</h2>
        {change != null && last ? (
          <p className="text-[12.5px] text-muted-foreground">
            Do {fmtMonthShort(`${last.month}-01`)}:{" "}
            <span className="font-semibold tabular-nums text-foreground">{signedPln(change)} / mies.</span>{" "}
            <span className="tabular-nums">({pct != null ? `${pct > 0 ? "+" : "−"}${fmtPct(Math.abs(pct))}` : "—"})</span>
          </p>
        ) : null}
      </div>
      {query.isError ? (
        <QueryLine error>Nie udało się pobrać prognozy.</QueryLine>
      ) : !query.isSuccess ? (
        <QueryLine>Ładowanie prognozy…</QueryLine>
      ) : months.length === 0 ? (
        <QueryLine>Brak żywych kontraktów — nie ma czego prognozować.</QueryLine>
      ) : (
        <>
          {f?.fx_missing ? (
            <p className="mt-1 text-[12px] text-warning-muted-foreground">
              Część kwot w obcej walucie pominięta — brak kursu NBP.
            </p>
          ) : null}
          <ForecastLine months={months} />
          <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">
            Liczy znane daty startu i końca umów; umowy bez daty końca trwają dalej, nowej sprzedaży nie zakłada.
            {scaleFrom != null ? ` Oś pionowa zaczyna się od ${fmtMln(scaleFrom)}, nie od zera.` : ""}
          </p>
        </>
      )}
    </section>
  );
}

// ── Top klienci ────────────────────────────────────────────────────────────

function TopClients({ query, totals }: { query: ReturnType<typeof useMkAnalytics>["clients"]; totals?: MkMarginTotals }) {
  const [all, setAll] = useState(false);
  const rows = query.data ?? [];
  const shown = all ? rows : rows.slice(0, 10);
  const topShare =
    totals && totals.total_monthly_margin
      ? (rows.slice(0, 10).reduce((a, r) => a + r.total_monthly_margin, 0) / totals.total_monthly_margin) * 100
      : null;
  return (
    <section className="rounded-xl border border-border bg-card shadow-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 px-4 pb-1 pt-3">
        <h2 className="text-[14px] font-semibold text-foreground">Top klienci wg marży</h2>
        {query.isSuccess && rows.length > 0 ? (
          <p className="text-[12.5px] text-muted-foreground">
            {all ? `Wszyscy klienci (${rows.length})` : `10 z ${rows.length} klientów`}
            {topShare != null && !all ? ` · razem ${fmtPct(topShare)} marży firmy` : ""}
          </p>
        ) : null}
      </div>
      {query.isError ? (
        <QueryLine error>Nie udało się pobrać zestawienia klientów.</QueryLine>
      ) : !query.isSuccess ? (
        <QueryLine>Ładowanie…</QueryLine>
      ) : rows.length === 0 ? (
        <QueryLine>Żaden klient nie ma dziś aktywnego kontraktu.</QueryLine>
      ) : (
        <>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border">
                <th className={cn(CALM_HEAD, "py-2 pl-4 pr-3 text-left")}>Klient</th>
                <th className={cn(CALM_HEAD, "w-[90px] px-3 py-2 text-right")}>Osoby</th>
                <th className={cn(CALM_HEAD, "w-[170px] px-3 py-2 text-right")}>
                  Przychód<span className={CALM_UNIT}>zł / mies.</span>
                </th>
                <th className={cn(CALM_HEAD, "w-[170px] px-3 py-2 text-right")}>
                  Marża<span className={CALM_UNIT}>zł / mies.</span>
                </th>
                <th className={cn(CALM_HEAD, "w-[110px] py-2 pl-3 pr-4 text-right")}>Marża %</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => {
                const partial = (r.contracts_without_revenue_leg ?? 0) + (r.contracts_without_cost_leg ?? 0);
                return (
                  <tr key={r.client_id} className={cn(CALM_ROW, "last:border-b-0")}>
                    <td className="py-2.5 pl-4 pr-3">
                      <Link
                        href={`/clients/${r.client_id}`}
                        title={r.client_name}
                        className="block max-w-[420px] truncate font-medium text-foreground hover:text-primary hover:underline"
                      >
                        {r.client_name}
                      </Link>
                      {partial > 0 ? (
                        <span className={CALM_SUBLINE}>
                          {plural(partial, ["kontrakt", "kontrakty", "kontraktów"])} bez stawki — poza sumą
                        </span>
                      ) : null}
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-3 py-2.5 text-muted-foreground")}>{r.active_contracts}</td>
                    <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{r.fx_missing ? "—" : fmtInt(r.total_monthly_revenue)}</td>
                    <td className={cn(CALM_AMOUNT, "px-3 py-2.5 font-semibold")}>{r.fx_missing ? "—" : fmtInt(r.total_monthly_margin)}</td>
                    <td className={cn(CALM_AMOUNT, "py-2.5 pl-3 pr-4 text-muted-foreground")}>{fmtPct(r.margin_pct)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length > 10 ? (
            <div className="border-t border-border/60 px-4 py-1.5">
              <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => setAll((v) => !v)}>
                {all ? "Pokaż pierwszą dziesiątkę" : `Pokaż wszystkich klientów (${rows.length})`}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

// ── Strona ─────────────────────────────────────────────────────────────────

export function AnalyticsA() {
  const { totals, util, forecast, clients } = useMkAnalytics();
  return (
    <div className="space-y-4">
      <AnalyticsHead
        subtitle="Ile zarabiamy dziś i co zmieni się w najbliższych 3 miesiącach — aktywne i kończące się kontrakty."
        right={<p className="text-[12.5px] text-muted-foreground">Stan na {fmtDate(today())}</p>}
      />
      <KeyFigures totals={totals} util={util} />
      <NextQuarter />
      <ForecastCard query={forecast} />
      <TopClients query={clients} totals={totals.data} />
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1 text-[12.5px] text-muted-foreground">
        <span className="mr-1">Więcej zestawień:</span>
        <Button type="button" variant="ghost" size="sm">
          Konsultanci wg marży
        </Button>
        <Button type="button" variant="ghost" size="sm">
          Lokalizacja konsultantów
        </Button>
        <Button type="button" variant="ghost" size="sm">
          Powody zakończeń (12 mies.)
        </Button>
      </div>
    </div>
  );
}
