"use client";

import * as React from "react";
import { AlertTriangle, Info } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { cn, formatDate } from "@/lib/utils";
import { useBoardSummary, type BoardSummary, type FilingKind } from "@/lib/api/supervisory-board";
import { resolveViewState, isBlockingViewState } from "@/lib/view-state";
import { FinancePanel } from "./PulpitFinance";
import { monthTable, selectableYears, type MonthCell, type MonthTableRow } from "./pulpit-months";

const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
const FILING_LABELS: Record<FilingKind, string> = {
  financial_statement: "sprawozdania",
  activity_report: "sprawozdania z działalności",
  audit_opinion: "opinii biegłego",
  approval: "uchwały zatwierdzającej",
};
// Progi „Do uwagi Rady” — opisane w docs/claude/rada/.
const CONCENTRATION_ALERT = 30;
const ENDING_ALERT = 30;
const RESULT_DROP_ALERT = 1;

export function mln(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits })} mln`;
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function range(months: number): string {
  return months <= 1 ? ROMAN[0] : `${ROMAN[0]}–${ROMAN[months - 1]}`;
}

export interface Attention {
  tone: "bad" | "warn" | "info";
  title: string;
  text: string;
}

/** Sygnały dla Rady z liczb pulpitu (czysta funkcja — test w __tests__). */
export function attentionItems(data: BoardSummary, year: number): Attention[] {
  const items: Attention[] = [];
  const { ytd } = data;
  if (
    ytd.result_pct != null &&
    ytd.result_previous_pct != null &&
    ytd.result_pct < ytd.result_previous_pct - RESULT_DROP_ALERT
  ) {
    items.push({
      tone: "bad",
      title: `Zysk brutto niższy niż rok wcześniej (${range(ytd.result_months)})`,
      text: `${pct(ytd.result_pct)} sprzedaży wobec ${pct(ytd.result_previous_pct)} w ${year - 1}. Do potwierdzenia z RZiS: faktury kosztowe mogą zawierać refaktury.`,
    });
  }
  const { orders } = data;
  if (orders.active > 0 && (100 * orders.ending) / orders.active >= ENDING_ALERT) {
    items.push({
      tone: "warn",
      title: `${orders.ending} z ${orders.active} kontraktów: umowa albo zamówienie kończy się do ${formatDate(orders.year_end)}`,
      text: `To ${mln(orders.ending_potential_month)} miesięcznie z ${mln(orders.potential_month)} potencjału — zależy od przedłużeń na ${year + 1}.`,
    });
  }
  const top = data.top_clients.items[0];
  if (top && top.share >= CONCENTRATION_ALERT) {
    items.push({
      tone: "warn",
      title: `${top.name}: ${pct(top.share)} sprzedaży ${data.top_clients.year}`,
      text: "Jeden klient powyżej 30% sprzedaży — pierwsze pytanie banku i inwestora.",
    });
  }
  for (const gap of data.krs_missing) {
    items.push({
      tone: "warn",
      title: `KRS: brak ${gap.missing.map((k) => FILING_LABELS[k]).join(", ")} za ${gap.year}`,
      text: "Wzmianka o złożeniu nie pojawiła się w odpisie, a sprawozdanie za ten rok jest.",
    });
  }
  if (data.documents_without_file > 0) {
    items.push({
      tone: "info",
      title: `${data.documents_without_file} dokumentów bez skanu`,
      text: "Wiersze założone z KRS czekają na plik od Zarządu (zakładka Dokumenty).",
    });
  }
  return items;
}

export function PulpitTab() {
  const summary = useBoardSummary();
  const state = resolveViewState({
    isLoading: summary.isLoading,
    isError: summary.isError,
    error: summary.error,
    isSuccess: summary.isSuccess,
    isEmpty: (summary.data?.years.length ?? 0) === 0,
  });
  if (isBlockingViewState(state)) {
    return <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => summary.refetch()} />;
  }
  if (state === "loading" || !summary.data) {
    return <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  }
  const data = summary.data;
  const year = new Date().getFullYear();
  return (
    <div className="space-y-3">
      {state === "empty" ? (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Archiwum faktur nie jest jeszcze w NEXUSIE. Po imporcie z eBI24 (Finanse → Archiwum) pulpit pokaże sprzedaż, koszty i wynik za trzy lata.
        </p>
      ) : (
        <Kpis data={data} year={year} />
      )}
      {/* Uwagi Rady z 18.11.2026: obok wyniku finanse spółki (gotówka,
          zdolność kredytowa, wycena, symulacja roku, raporty), „Do uwagi
          Rady” na sam dół. */}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        {state === "empty" ? <div /> : <YearsPanel data={data} />}
        <FinancePanel />
      </div>
      {state === "empty" ? null : <MonthsPanel data={data} year={year} />}
      <AttentionPanel items={attentionItems(data, year)} />
    </div>
  );
}

function Kpis({ data, year }: { data: BoardSummary; year: number }) {
  const { ytd, orders } = data;
  const salesChange =
    ytd.sales && ytd.sales_previous ? (100 * (ytd.sales - ytd.sales_previous)) / ytd.sales_previous : null;
  const lastYear = data.years.find((y) => y.year === year - 1);
  const top = data.top_clients.items[0];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
      <Figure
        label={`Sprzedaż ${range(ytd.sales_months)} ${year}`}
        value={mln(ytd.sales)}
        sub={
          <>
            rok wcześniej {mln(ytd.sales_previous)}
            {salesChange !== null ? (
              <span className={cn(" ml-1", salesChange >= 0 ? "text-success" : "text-destructive")}>
                {salesChange >= 0 ? "+" : ""}
                {pct(salesChange)}
              </span>
            ) : null}
          </>
        }
      />
      <Figure
        label={`Zysk brutto ${range(ytd.result_months)}`}
        value={mln(ytd.result)}
        tone={ytd.result_pct != null && ytd.result_previous_pct != null && ytd.result_pct < ytd.result_previous_pct ? "bad" : "neutral"}
        sub={`${pct(ytd.result_pct)} sprzedaży · rok wcześniej ${pct(ytd.result_previous_pct)}`}
      />
      <Figure
        label={`Sprzedaż ${year - 1}`}
        value={mln(lastYear?.sales)}
        sub={`zysk brutto ${mln(lastYear?.result)} (${pct(lastYear?.result_pct)})`}
      />
      <Figure
        label="Aktywne kontrakty"
        value={String(orders.active)}
        sub={`potencjał ${mln(orders.potential_month)} / mies. (160 h)`}
      />
      <Figure
        label={`Kończą się do ${formatDate(orders.year_end).slice(0, 5)}`}
        value={String(orders.ending)}
        tone={orders.active && (100 * orders.ending) / orders.active >= ENDING_ALERT ? "warn" : "neutral"}
        sub={`${mln(orders.ending_potential_month)} / mies. bez przedłużenia`}
      />
      <Figure
        label="Największy klient"
        value={top ? pct(top.share) : "—"}
        tone={top && top.share >= CONCENTRATION_ALERT ? "warn" : "neutral"}
        sub={top ? `${top.name}, ${data.top_clients.year}` : undefined}
      />
    </div>
  );
}

function Figure({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  tone?: "neutral" | "bad" | "warn";
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3.5 py-3">
      <div className="truncate text-[12px] font-medium text-muted-foreground" title={label}>
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-[22px] font-semibold leading-tight tabular-nums tracking-tight",
          tone === "bad" && "text-destructive",
          tone === "warn" && "text-warning-muted-foreground",
          tone === "neutral" && "text-foreground",
        )}
      >
        {value}
      </div>
      {sub ? <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

// Uwagi Rady z 19.11.2026: słupki nie trafiały w kolumny tabeli — sama tabela.
function YearsPanel({ data }: { data: BoardSummary }) {
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Sprzedaż, koszty i zysk brutto</h2>
        <span className="text-[11px] text-muted-foreground">mln zł netto</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <tr className="text-[11px] text-muted-foreground">
              <th className="py-1 text-left font-medium" />
              {data.years.map((y, i) => (
                <th key={y.year} className={cn("py-1 pl-2 text-right font-medium tabular-nums", phoneHidden(data, i))}>
                  {y.year}
                  {y.complete ? "" : ` (${range(y.result_months ?? 0)})`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border tabular-nums">
            <Row data={data} label="Sprzedaż" values={data.years.map((y) => fmt(y.sales))} />
            <Row data={data} label="Koszty kontraktorów" values={data.years.map((y) => fmt(y.contractors))} />
            <Row
              data={data}
              label="Marża na kontraktorach"
              values={data.years.map((y) => fmt(y.contractor_margin))}
              subs={data.years.map((y) => pct(y.contractor_margin_pct))}
            />
            <Row data={data} label="Koszty biurowe" values={data.years.map((y) => fmt(y.office))} />
            <Row
              data={data}
              label="Zysk brutto"
              values={data.years.map((y) => fmt(y.result))}
              subs={data.years.map((y) => pct(y.result_pct))}
              strong
            />
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        Faktury z archiwum eBI24 według daty sprzedaży
        {data.source.last_date ? `, do ${formatDate(data.source.last_date)}` : ""}. Koszty kontraktorów = folder
        „Kontraktorzy”, koszty biurowe = pozostałe faktury kosztowe. Zysk brutto nie obejmuje płac UoP, ZUS
        i amortyzacji — nie zastępuje RZiS.
        {currentResult(data)}
      </p>
    </section>
  );
}

function currentResult(data: BoardSummary): string {
  const current = data.years.find((y) => !y.complete);
  if (!current?.result_months) return "";
  return ` Rok ${current.year} liczony za ${range(current.result_months)} — koszty kolejnych miesięcy jeszcze spływają.`;
}

/** Na telefonie cztery lata się nie mieszczą — najstarszy rok tylko od `sm`. */
function phoneHidden(data: BoardSummary, index: number): string | false {
  return data.years.length > 3 && index === 0 && "max-sm:hidden";
}

function Row({
  data,
  label,
  values,
  subs,
  strong,
}: {
  data: BoardSummary;
  label: string;
  values: string[];
  subs?: string[];
  strong?: boolean;
}) {
  return (
    <tr>
      <td className={cn("py-1.5 pr-2 text-left", strong && "font-semibold")}>{label}</td>
      {values.map((v, i) => (
        <td key={i} className={cn("py-1.5 pl-2 text-right", strong && "font-semibold", phoneHidden(data, i))}>
          {v}
          {subs ? <div className="text-[11px] font-normal text-muted-foreground">{subs[i]}</div> : null}
        </td>
      ))}
    </tr>
  );
}

function AttentionPanel({ items }: { items: Attention[] }) {
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-foreground">Do uwagi Rady</h2>
      {items.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">Nic nie odbiega od progów.</p>
      ) : (
        <ul className="space-y-2.5 text-[12px] leading-snug">
          {items.map((item) => (
            <li key={item.title} className="flex gap-2">
              {item.tone === "info" ? (
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              ) : (
                <AlertTriangle
                  className={cn(
                    "mt-0.5 h-3.5 w-3.5 shrink-0",
                    item.tone === "bad" ? "text-destructive" : "text-warning-muted-foreground",
                  )}
                />
              )}
              <div>
                <div className="font-medium text-foreground">{item.title}</div>
                <div className="text-muted-foreground">{item.text}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function fmt(value: number | null | undefined, signed = false): string {
  if (value === null || value === undefined) return "—";
  const text = value.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return signed && value > 0 ? `+${text}` : text;
}

function DeltaCell({ cell }: { cell: MonthCell }) {
  if (cell.value === null) return <span className="text-muted-foreground">—</span>;
  const tone = cell.value > 0 ? "text-success-muted-foreground" : cell.value < 0 ? "text-destructive" : "text-foreground";
  return (
    <>
      <div className={tone}>{fmt(cell.value, true)}</div>
      <div className="text-[11px] text-muted-foreground">
        {cell.pct === null || cell.pct === undefined ? "" : `${cell.pct > 0 ? "+" : ""}${pct(cell.pct)}`}
      </div>
    </>
  );
}

function MonthRowView({ row }: { row: MonthTableRow }) {
  const cellClass = "border border-border px-1.5 py-1.5 text-right align-top";
  return (
    <tr className={cn(row.kind === "budget" && "bg-muted/40", row.key === "current" && "font-semibold")}>
      <th
        scope="row"
        className="sticky left-0 z-10 border border-border bg-card px-2 py-1.5 text-left text-[12px] font-medium"
      >
        {row.label}
      </th>
      {row.cells.map((cell, i) => (
        <td key={i} className={cellClass}>
          {row.kind === "delta" ? (
            <DeltaCell cell={cell} />
          ) : (
            <span className={cn(cell.value === null && "text-muted-foreground", cell.partial && "italic text-muted-foreground")}>
              {fmt(cell.value)}
            </span>
          )}
        </td>
      ))}
      <td className={cn(cellClass, "bg-muted/30 font-semibold")}>
        {row.kind === "delta" ? <DeltaCell cell={row.total} /> : fmt(row.total.value)}
      </td>
    </tr>
  );
}

const PHONE_LABELS: Record<string, (row: MonthTableRow) => string> = {
  previous: (r) => r.label.replace("Wykonanie ", ""),
  budget: () => "Budżet",
  current: (r) => r.label.replace("Wykonanie ", ""),
  "vs-budget": () => "Δ budżet",
  "vs-previous": (r) => r.label.replace("Odchylenie od ", "Δ "),
};

/**
 * Telefon (uwagi Rady z 19.11.2026): dwanaście kolumn miesięcy nie mieści się
 * na ekranie — miesiące idą wierszami, a wiersze tabeli kolumnami.
 */
function MonthsPhone({ rows }: { rows: MonthTableRow[] }) {
  const cell = "border border-border px-1 py-1 text-right align-top";
  const body = (pick: (row: MonthTableRow) => MonthCell) =>
    rows.map((row) => (
      <td key={row.key} className={cn(cell, row.kind === "budget" && "bg-muted/40", row.key === "current" && "font-semibold")}>
        {row.kind === "delta" ? (
          <DeltaCell cell={pick(row)} />
        ) : (
          <span className={cn(pick(row).value === null && "text-muted-foreground", pick(row).partial && "italic text-muted-foreground")}>
            {fmt(pick(row).value)}
          </span>
        )}
      </td>
    ));
  return (
    <table className="w-full border-collapse text-[11px] tabular-nums sm:hidden">
      <thead>
        <tr className="text-[10px] text-muted-foreground">
          <th className="border border-border px-1 py-1 text-left font-medium">mln zł</th>
          {rows.map((row) => (
            <th key={row.key} className="border border-border px-1 py-1 text-right font-medium">
              {(PHONE_LABELS[row.key] ?? ((r: MonthTableRow) => r.label))(row)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {ROMAN.map((m, i) => (
          <tr key={m}>
            <th scope="row" className="border border-border px-1 py-1 text-left align-top font-medium">
              {m}
            </th>
            {body((row) => row.cells[i])}
          </tr>
        ))}
        <tr className="bg-muted/30 font-semibold">
          <th scope="row" className="border border-border px-1 py-1 text-left align-top">
            {totalLabel(rows)}
          </th>
          {body((row) => row.total)}
        </tr>
      </tbody>
    </table>
  );
}

/** „Razem I–IX”: suma tylko miesięcy z kompletem faktur roku pokazanego. */
function totalLabel(rows: MonthTableRow[]): string {
  const current = rows.find((r) => r.key === "current");
  const done = current ? current.cells.filter((c) => c.value !== null && !c.partial).length : 0;
  return done === 0 || done === 12 ? "Razem" : `Razem ${range(done)}`;
}

function MonthsPanel({ data, year }: { data: BoardSummary; year: number }) {
  const years = selectableYears(data, year);
  const [shown, setShown] = React.useState(year);
  const rows = monthTable(data, shown);
  const hasBudget = Boolean(data.budgets[String(shown)]);
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Miesiące — sprzedaż, budżet i odchylenia</h2>
        {years.length > 1 ? (
          <SegmentedRadio<string>
            label="Rok"
            size="sm"
            value={String(shown)}
            onChange={(v) => setShown(Number(v))}
            options={years.map((y) => ({ value: String(y), label: String(y) }))}
          />
        ) : null}
      </div>
      <MonthsPhone rows={rows} />
      <div className="overflow-x-auto max-sm:hidden">
        <table className="w-full min-w-[860px] border-collapse text-[12px] tabular-nums">
          <thead>
            <tr className="text-[11px] text-muted-foreground">
              <th className="sticky left-0 z-10 border border-border bg-card px-2 py-1 text-left font-medium">mln zł netto</th>
              {ROMAN.map((m) => (
                <th key={m} className="border border-border px-1.5 py-1 text-right font-medium">
                  {m}
                </th>
              ))}
              <th className="border border-border bg-muted/30 px-1.5 py-1 text-right font-medium">{totalLabel(rows)}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <MonthRowView key={row.key} row={row} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        Sprzedaż według daty sprzedaży z faktur. Kursywa = miesiąc bez kompletu faktur (bieżący i świeżo zamknięty);
        odchylenia i „Razem” liczą tylko miesiące z kompletem.
        {hasBudget ? "" : ` Budżetu na ${shown} nie wpisano — Zarząd wpisuje plan w zakładce Budżet.`}
      </p>
    </section>
  );
}
