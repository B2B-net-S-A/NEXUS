"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp } from "lucide-react";
import api from "@/lib/api";
import { QueryStateNotice, type BlockingViewState } from "@/components/ds/QueryStateNotice";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import {
  buildClientReport,
  daysBetweenIso,
  endingByPerson,
  nextSort,
  sortClientReport,
  sortPeopleReport,
  summarizeWindow,
  withoutRevenueNote,
  type ClientReportRow,
  type ClientSortKey,
  type MarginRow,
  type MarginTotals,
  type PersonSortKey,
  type SortState,
  type UtilizationData,
  type WindowContract,
} from "@/lib/contract-analytics";
import { relativeDays } from "@/lib/contract-happening";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { formatPctPl, formatWholeMoney, formatWholeNumber } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import type { WindowQuery } from "./AnalyticsNextQuarter";

type View = "clients" | "people";

/** Pierwsza kolumna przyklejona przy przewijaniu tabeli w bok (reguła responsywności). */
const STICKY_CELL = "sticky left-0 z-[1] bg-card";

function people(n: number): string {
  return countPl(n, "osoba", "osoby", "osób");
}

function SortHead<K extends string>({
  label,
  unit,
  k,
  sort,
  onSort,
  align = "right",
  className,
  tour,
}: {
  label: string;
  unit?: string;
  k: K;
  sort: SortState<K>;
  onSort: (k: K) => void;
  align?: "left" | "right";
  className?: string;
  tour?: boolean;
}) {
  const active = sort.key === k;
  const Arrow = sort.dir === "asc" ? ArrowUp : ArrowDown;
  const arrow = active ? <Arrow className="size-3 shrink-0 text-foreground" aria-hidden /> : null;
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(CALM_HEAD, "py-2 align-top", align === "right" ? "text-right" : "text-left", className)}
    >
      <button
        type="button"
        onClick={() => onSort(k)}
        data-tour={tour ? "contracts.analytics.sort" : undefined}
        className={cn(
          "inline-flex items-start gap-1 whitespace-nowrap uppercase tracking-[0.05em] hover:text-foreground",
          active && "text-foreground",
        )}
      >
        {align === "right" ? <span className="pt-px">{arrow}</span> : null}
        <span className={cn("flex flex-col", align === "right" ? "items-end" : "items-start")}>
          <span>{label}</span>
          {/* Jednostka w drugiej linii nagłówka — raz na kolumnę. */}
          {unit ? (
            <span className="text-[11px] font-normal normal-case tracking-normal text-muted-foreground">{unit}</span>
          ) : null}
        </span>
        {align === "left" ? <span className="pt-px">{arrow}</span> : null}
      </button>
    </th>
  );
}

/**
 * Kwota marży z cienkim paskiem. Klienci: pasek = udział w marży firmy.
 * Konsultanci: udział jednej osoby to ułamek procenta, więc pasek mierzy
 * względem najlepszego w zestawieniu (`scale`), a udział zostaje w dymku.
 */
function MarginCell({ value, total, scale }: { value: number | null; total: number | null; scale?: number | null }) {
  if (value == null) return <span className={CALM_EMPTY}>—</span>;
  const share = total ? Math.max(0, value / total) : 0;
  const width = scale ? Math.max(0, value / scale) : share;
  return (
    <span
      className="inline-flex items-center justify-end gap-3"
      title={total ? `${formatPctPl(share * 100)} marży firmy` : undefined}
    >
      <span className="relative h-1.5 w-16 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-primary/70"
          style={{ width: `${Math.min(100, Math.max(width * 100, value > 0 ? 3 : 0))}%` }}
        />
      </span>
      <span className="min-w-[72px] font-semibold">{formatWholeNumber(value)}</span>
    </span>
  );
}

/** „7 osób” + „−48 888 zł” (marża miesięczna); nic → kreska. Nazwiska i daty w dymku. */
function WindowCell({ items, kind }: { items: WindowContract[]; kind: "ending" | "starting" }) {
  if (items.length === 0) return <span className={CALM_EMPTY}>—</span>;
  const summary = summarizeWindow(items);
  const known = items.length - summary.withoutRates - summary.otherCurrency;
  const dateOf = (c: WindowContract) => (kind === "ending" ? c.end_date : c.start_date) ?? "";
  const names = [...items]
    .sort((a, b) => dateOf(a).localeCompare(dateOf(b)))
    .map((c) => `${formatDayMonthPl(dateOf(c))} ${c.candidate_name ?? "—"}`)
    .join("\n");
  return (
    <span title={names}>
      <span className="block font-medium text-foreground">{people(summary.people)}</span>
      <span className={CALM_SUBLINE}>
        {known > 0
          ? formatWholeMoney(kind === "ending" ? -summary.margin : summary.margin, "PLN", true)
          : "marża nieznana"}
      </span>
    </span>
  );
}

/** Druga linia nazwy: kwoty częściowe albo klient dopiero ze startem. */
function RowNote({ row }: { row: ClientReportRow }) {
  if (row.fxMissing) {
    return (
      <span
        role="alert"
        className="mt-0.5 flex items-center gap-1 text-[11.5px] font-medium text-warning-muted-foreground"
        title="Kwoty pomijają pozycje bez dostępnego kursu FX"
      >
        <AlertTriangle className="size-3.5" aria-hidden />
        Brak kursu FX
      </span>
    );
  }
  const parts = [
    withoutRevenueNote(row.withoutRevenue),
    row.withoutCost > 0
      ? `${countPl(row.withoutCost, "kontrakt", "kontrakty", "kontraktów")} bez stawki kosztowej poza marżą`
      : undefined,
  ].filter(Boolean);
  if (parts.length > 0) {
    return (
      <span className={cn(CALM_SUBLINE, "flex items-center gap-1 text-warning-muted-foreground")} title={parts.join(" · ")}>
        <AlertTriangle className="size-3 shrink-0" aria-hidden />
        <span className="truncate">{row.withoutRevenue > 0 ? "Niepełne" : parts[0]}</span>
      </span>
    );
  }
  if (row.contracts == null) return <span className={CALM_SUBLINE}>dziś bez aktywnego kontraktu</span>;
  return null;
}

function ClientsTable({
  clients,
  ending,
  starting,
  windowsReady,
  totals,
}: {
  clients: MarginRow[];
  ending: WindowContract[];
  starting: WindowContract[];
  windowsReady: boolean;
  /** Sumy firmy; `null` = jeszcze się wczytują albo padły — wiersz „Razem” ma wtedy „—”. */
  totals: MarginTotals | null;
}) {
  const [sort, setSort] = useState<SortState<ClientSortKey>>({ key: "margin", dir: "desc" });
  const rows = useMemo(
    () => sortClientReport(buildClientReport(clients, windowsReady ? ending : [], windowsReady ? starting : []), sort),
    [clients, ending, starting, windowsReady, sort],
  );
  const onSort = (k: ClientSortKey) => setSort((s) => nextSort(s, k));
  const known = totals && !totals.fx_missing ? totals : null;
  const totalMargin = known ? known.total_monthly_margin : null;
  const onlyStarting = rows.filter((r) => r.contracts == null).length;
  const endingSummary = summarizeWindow(ending);
  const startingSummary = summarizeWindow(starting);

  return (
    <div className="relative overflow-x-auto">
      <table className={cn("w-full text-[13px]", windowsReady ? "min-w-[880px]" : "min-w-[640px]")}>
        <thead>
          <tr className="border-b border-border">
            <SortHead label="Klient" k="name" sort={sort} onSort={onSort} align="left" className={cn("pl-4 pr-3", STICKY_CELL)} />
            <SortHead label="Kontrakty" k="contracts" sort={sort} onSort={onSort} className="w-[88px] px-3" />
            <SortHead label="Przychód" unit="zł / mies." k="revenue" sort={sort} onSort={onSort} className="w-[118px] px-3" />
            <SortHead label="Marża" unit="zł / mies." k="margin" sort={sort} onSort={onSort} className="w-[178px] px-3" tour />
            <SortHead label="Marża %" k="pct" sort={sort} onSort={onSort} className="w-[92px] px-3" />
            {windowsReady ? (
              <>
                <SortHead label="Kończą się" unit="w 90 dni" k="ending" sort={sort} onSort={onSort} className="w-[118px] px-3" />
                <SortHead label="Startują" unit="w 90 dni" k="starting" sort={sort} onSort={onSort} className="w-[112px] pl-3 pr-4" />
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.clientId} className={cn(CALM_ROW, "align-middle")}>
              <td className={cn("max-w-[320px] py-2 pl-4 pr-3", STICKY_CELL)}>
                <Link
                  href={`/clients/${r.clientId}`}
                  title={r.name}
                  className="block truncate font-medium text-foreground hover:text-primary hover:underline"
                >
                  {r.name}
                </Link>
                <RowNote row={r} />
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>
                {r.contracts ?? <span className={CALM_EMPTY}>—</span>}
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2")}>
                {r.revenue == null ? <span className={CALM_EMPTY}>—</span> : formatWholeNumber(r.revenue)}
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2")}>
                <MarginCell value={r.margin} total={totalMargin} />
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>
                {r.pct == null ? <span className={CALM_EMPTY}>—</span> : formatPctPl(r.pct)}
              </td>
              {windowsReady ? (
                <>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <WindowCell items={r.ending} kind="ending" />
                  </td>
                  <td className="py-2 pl-3 pr-4 text-right tabular-nums">
                    <WindowCell items={r.starting} kind="starting" />
                  </td>
                </>
              ) : null}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-border bg-muted/40 font-semibold">
            <td className={cn("py-2.5 pl-4 pr-3", STICKY_CELL, "bg-muted")}>
              Razem
              <span className={cn(CALM_SUBLINE, "font-normal")}>
                {totals
                  ? `${countPl(totals.clients, "klient", "klientów", "klientów")} z aktywnym kontraktem`
                  : "sumy firmy niedostępne"}
                {onlyStarting ? ` + ${onlyStarting} ze startem` : ""}
              </span>
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
              {totals ? totals.active_contracts : <span className={CALM_EMPTY}>—</span>}
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
              {known ? formatWholeNumber(known.total_monthly_revenue) : <span className={CALM_EMPTY}>—</span>}
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
              <span className="inline-block min-w-[76px]">
                {known ? formatWholeNumber(known.total_monthly_margin) : <span className={CALM_EMPTY}>—</span>}
              </span>
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
              {known && known.margin_pct != null ? (
                formatPctPl(known.margin_pct)
              ) : (
                <span className={CALM_EMPTY}>—</span>
              )}
            </td>
            {windowsReady ? (
              <>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {people(endingSummary.people)}
                  <span className={cn(CALM_SUBLINE, "font-normal")}>
                    {formatWholeMoney(-endingSummary.margin, "PLN", true)}
                  </span>
                </td>
                <td className="py-2.5 pl-3 pr-4 text-right tabular-nums">
                  {people(startingSummary.people)}
                  <span className={cn(CALM_SUBLINE, "font-normal")}>
                    {formatWholeMoney(startingSummary.margin, "PLN", true)}
                  </span>
                </td>
              </>
            ) : null}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function PeopleTable({
  rows,
  ending,
  totalMargin,
  today,
}: {
  rows: MarginRow[];
  ending: WindowContract[];
  totalMargin: number | null;
  today: string;
}) {
  const [sort, setSort] = useState<SortState<PersonSortKey>>({ key: "margin", dir: "desc" });
  const endBy = useMemo(() => endingByPerson(ending), [ending]);
  const sorted = useMemo(() => sortPeopleReport(rows, sort, endBy), [rows, sort, endBy]);
  const onSort = (k: PersonSortKey) => setSort((s) => nextSort(s, k));
  const complete = rows.filter((r) => r.fx_missing !== true);
  const sumRevenue = complete.reduce((a, r) => a + r.total_monthly_revenue, 0);
  const sumMargin = complete.reduce((a, r) => a + r.total_monthly_margin, 0);
  const topMargin = complete.reduce((a, r) => Math.max(a, r.total_monthly_margin), 0);

  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[820px] text-[13px]">
        <thead>
          <tr className="border-b border-border">
            <SortHead label="Konsultant" k="name" sort={sort} onSort={onSort} align="left" className={cn("pl-4 pr-3", STICKY_CELL)} />
            <SortHead label="Kontrakty" k="contracts" sort={sort} onSort={onSort} className="w-[100px] px-3" />
            <SortHead label="Przychód" unit="zł / mies." k="revenue" sort={sort} onSort={onSort} className="w-[130px] px-3" />
            <SortHead label="Marża" unit="zł / mies." k="margin" sort={sort} onSort={onSort} className="w-[178px] px-3" />
            <SortHead label="Marża %" k="pct" sort={sort} onSort={onSort} className="w-[92px] px-3" />
            <SortHead label="Koniec umowy" unit="w 90 dni" k="ending" sort={sort} onSort={onSort} className="w-[190px] pl-3 pr-4" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const end = endBy.get(r.candidate_id ?? -1);
            const fx = r.fx_missing === true;
            return (
              <tr key={r.candidate_id} className={CALM_ROW}>
                <td className={cn("py-2.5 pl-4 pr-3", STICKY_CELL)}>
                  <Link
                    href={`/candidates/${r.candidate_id}`}
                    className="font-medium text-foreground hover:text-primary hover:underline"
                  >
                    {r.candidate_name ?? "—"}
                  </Link>
                  {fx ? (
                    <span
                      role="alert"
                      className="mt-0.5 flex items-center gap-1 text-[11.5px] font-medium text-warning-muted-foreground"
                      title="Kwoty pomijają pozycje bez dostępnego kursu FX"
                    >
                      <AlertTriangle className="size-3.5" aria-hidden />
                      Brak kursu FX
                    </span>
                  ) : (r.contracts_without_revenue_leg ?? 0) > 0 ? (
                    <span className={cn(CALM_SUBLINE, "text-warning-muted-foreground")} title={withoutRevenueNote(r.contracts_without_revenue_leg)}>
                      Niepełne
                    </span>
                  ) : null}
                </td>
                <td className={cn(CALM_AMOUNT, "px-3 py-2.5 text-muted-foreground")}>{r.active_contracts}</td>
                <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
                  {fx ? <span className={CALM_EMPTY}>—</span> : formatWholeNumber(r.total_monthly_revenue)}
                </td>
                <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
                  <MarginCell value={fx ? null : r.total_monthly_margin} total={totalMargin} scale={topMargin} />
                </td>
                <td className={cn(CALM_AMOUNT, "px-3 py-2.5 text-muted-foreground")}>
                  {fx || r.margin_pct == null ? <span className={CALM_EMPTY}>—</span> : formatPctPl(r.margin_pct)}
                </td>
                <td className="py-2.5 pl-3 pr-4 text-right tabular-nums">
                  {end?.end_date ? (
                    <span title={end.client_name ?? undefined}>
                      {formatIsoDatePl(end.end_date)}{" "}
                      <span className="text-muted-foreground">· {relativeDays(daysBetweenIso(today, end.end_date))}</span>
                    </span>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-border bg-muted/40 font-semibold">
            <td className={cn("py-2.5 pl-4 pr-3", STICKY_CELL, "bg-muted")}>
              Razem
              <span className={cn(CALM_SUBLINE, "font-normal")}>{people(rows.length)} z najwyższą marżą</span>
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{rows.reduce((a, r) => a + r.active_contracts, 0)}</td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{formatWholeNumber(sumRevenue)}</td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
              <span className="inline-block min-w-[76px]">{formatWholeNumber(sumMargin)}</span>
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
              {sumRevenue ? formatPctPl((sumMargin / sumRevenue) * 100) : <span className={CALM_EMPTY}>—</span>}
            </td>
            <td className="py-2.5 pl-3 pr-4 text-right tabular-nums">
              {people(sorted.filter((r) => endBy.has(r.candidate_id ?? -1)).length)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function Message({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "error" }) {
  return (
    <p className={cn("px-4 py-6 text-[13px]", tone === "error" ? "text-destructive" : "text-muted-foreground")}>
      {children}
    </p>
  );
}

/**
 * Tabela na całą szerokość (z wariantu B): kto ile przynosi, udział w marży
 * firmy i co się zmieni w 90 dni. Sortowanie kliknięciem w nagłówek, wiersz
 * sumy z `margin-totals`, przełącznik „Klienci · Konsultanci”. Gdy okno
 * 90 dni się nie wczyta, tabela zostaje bez dwóch ostatnich kolumn.
 */
export function AnalyticsReport({
  clients,
  totals,
  util,
  ending,
  starting,
  today,
}: {
  clients: UseQueryResult<MarginRow[]>;
  totals: UseQueryResult<MarginTotals>;
  util: UseQueryResult<UtilizationData>;
  ending: WindowQuery;
  starting: WindowQuery;
  today: string;
}) {
  const [view, setView] = useState<View>("clients");
  const peopleQ = useQuery<MarginRow[]>({
    queryKey: ["contract-analytics-margin-contractor", 100],
    queryFn: () =>
      api.get("/api/contract-analytics/margin-by-contractor", { params: { limit: 100 } }).then((r) => r.data),
    enabled: view === "people",
  });
  const windowsReady = ending.isSuccess && starting.isSuccess;
  const windowsFailed = ending.isError || starting.isError;
  const endingItems = ending.data?.items ?? [];
  const startingItems = starting.data?.items ?? [];
  const t = totals.data;
  const totalMargin = t && !t.fx_missing ? t.total_monthly_margin : null;
  const clientsState = resolveViewState({
    isLoading: clients.isLoading,
    isError: clients.isError,
    error: clients.error,
  });
  const peopleState = resolveViewState({
    isLoading: peopleQ.isLoading,
    isError: peopleQ.isError,
    error: peopleQ.error,
  });
  const failed = (state: string): state is BlockingViewState =>
    state === "forbidden" || state === "not_found" || state === "error";

  let body: React.ReactNode;
  let footer: string | null = null;
  if (view === "clients") {
    if (failed(clientsState)) {
      body = <QueryStateNotice state={clientsState} className="border-0" onRetry={() => void clients.refetch()} />;
    } else if (!clients.isSuccess) {
      body = <Message>Ładowanie zestawienia…</Message>;
    } else if ((clients.data ?? []).length === 0 && endingItems.length + startingItems.length === 0) {
      body = <Message>Żaden klient nie ma dziś aktywnego kontraktu.</Message>;
    } else {
      body = (
        <ClientsTable
          clients={clients.data ?? []}
          ending={endingItems}
          starting={startingItems}
          windowsReady={windowsReady}
          totals={t ?? null}
        />
      );
      footer = windowsReady
        ? "„Kończą się” i „Startują” liczą umowy z datą końca albo startu w najbliższych 90 dniach; kwota pod liczbą to marża z bieżących stawek (tylko PLN). Pasek przy marży to udział w marży firmy."
        : windowsFailed
          ? "Kolumny „Kończą się” i „Startują” są ukryte — nie udało się pobrać listy kontraktów na 90 dni."
          : "Kolumny 90 dni dołączą po wczytaniu listy kontraktów.";
    }
  } else if (failed(peopleState)) {
    body = <QueryStateNotice state={peopleState} className="border-0" onRetry={() => void peopleQ.refetch()} />;
  } else if (!peopleQ.isSuccess) {
    body = <Message>Ładowanie…</Message>;
  } else if ((peopleQ.data ?? []).length === 0) {
    body = <Message>Nikt nie ma dziś aktywnego kontraktu.</Message>;
  } else {
    body = (
      <PeopleTable rows={peopleQ.data ?? []} ending={windowsReady ? endingItems : []} totalMargin={totalMargin} today={today} />
    );
    const shown = (peopleQ.data ?? []).length;
    footer = util.data
      ? `Pokazano ${people(shown)} z najwyższą marżą z ${util.data.candidates_active} pracujących — sumy firmy są w liczbach na górze.`
      : `Pokazano ${people(shown)} z najwyższą marżą — sumy firmy są w liczbach na górze.`;
  }

  return (
    <section aria-label="Kto ile przynosi" className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border/60 px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-[14px] font-semibold text-foreground">Kto ile przynosi</h2>
          <p className="text-[12px] leading-4 text-muted-foreground">
            Marża miesięczna, udział w marży firmy i co się zmieni w 90 dni.
          </p>
        </div>
        <span data-tour="contracts.analytics.view">
          <SegmentedRadio<View>
            label="Zestawienie"
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: "clients", label: "Klienci" },
              { value: "people", label: "Konsultanci" },
            ]}
          />
        </span>
      </header>
      {body}
      {footer ? <p className="border-t border-border/60 px-4 py-2 text-[12px] text-muted-foreground">{footer}</p> : null}
    </section>
  );
}
