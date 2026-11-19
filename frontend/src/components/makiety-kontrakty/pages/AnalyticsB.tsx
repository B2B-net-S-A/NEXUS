"use client";
// B · Analityka kontraktów — „Raport per klient”. Liczby firmy jedną linią
// w nagłówku (`ds/InlineStats`) zamiast kafli, przełącznik „Klienci ·
// Konsultanci” i jedna tabela na całą szerokość: kto ile przynosi, jaki ma
// udział w marży firmy i co się u niego zmieni w 90 dni (kończące się
// i startujące umowy). Sortowanie po kliknięciu w nagłówek, strzałka przy
// aktywnej kolumnie, wiersz sumy na dole. Bez wykresu prognozy i bez macierzy
// rola × klient — to raport do czytania wierszami.
import { useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp } from "lucide-react";
import api from "@/lib/api";
import { InlineStats } from "@/components/ds/InlineStats";
import { cn } from "@/lib/utils";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE, CALM_UNIT } from "@/lib/calm-table";
import { fmtDate, fmtDayMonth, fmtPln, OSOBY, plural, relDays } from "../shared/format";
import {
  AnalyticsHead,
  fmtInt,
  fmtPct,
  monthlyMargin,
  QueryLine,
  signedPln,
  sumKnown,
  useMkAnalytics,
  useMkNext90,
  type MkMarginRow,
  type MkWindowContract,
} from "./AnalyticsA";

type View = "clients" | "people";
type Dir = "asc" | "desc";
type ClientKey = "name" | "people" | "revenue" | "margin" | "pct" | "ending" | "starting";
type PersonKey = "name" | "contracts" | "revenue" | "margin" | "pct" | "ending";

interface Sort<K extends string> {
  key: K;
  dir: Dir;
}

interface ClientReportRow {
  clientId: number;
  name: string;
  people: number | null;
  revenue: number | null;
  margin: number | null;
  pct: number | null;
  partial: number;
  ending: MkWindowContract[];
  starting: MkWindowContract[];
}

/** Puste wartości zawsze na końcu, niezależnie od kierunku. */
function compare(a: string | number | null, b: string | number | null, dir: Dir): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  const r = typeof a === "string" && typeof b === "string" ? a.localeCompare(b, "pl") : Number(a) - Number(b);
  return dir === "asc" ? r : -r;
}

function nextSort<K extends string>(current: Sort<K>, key: K): Sort<K> {
  if (current.key === key) return { key, dir: current.dir === "asc" ? "desc" : "asc" };
  return { key, dir: key === "name" ? "asc" : "desc" };
}

function SortHead<K extends string>({
  label,
  unit,
  k,
  sort,
  onSort,
  align = "right",
  className,
}: {
  label: string;
  unit?: string;
  k: K;
  sort: Sort<K>;
  onSort: (k: K) => void;
  align?: "left" | "right";
  className?: string;
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
        className={cn(
          "inline-flex items-start gap-1 whitespace-nowrap uppercase tracking-[0.05em] hover:text-foreground",
          active && "text-foreground",
        )}
      >
        {align === "right" ? <span className="pt-px">{arrow}</span> : null}
        <span className={cn("flex flex-col", align === "right" ? "items-end" : "items-start")}>
          <span>{label}</span>
          {/* Jednostka w drugiej linii nagłówka — raz na kolumnę, bez łamania w przypadkowym miejscu. */}
          {unit ? <span className={cn(CALM_UNIT, "ml-0")}>{unit}</span> : null}
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
    <span className="inline-flex items-center justify-end gap-3" title={total ? `${fmtPct(share * 100)} marży firmy` : undefined}>
      <span className="relative h-1.5 w-16 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-primary/70"
          style={{ width: `${Math.max(width * 100, value > 0 ? 3 : 0)}%` }}
        />
      </span>
      <span className="min-w-[72px] font-semibold">{fmtInt(value)}</span>
    </span>
  );
}

/** „7 osób” + „−48 888 zł” (marża miesięczna); zero → kreska. Nazwiska i daty w dymku. */
function WindowCell({ items, kind }: { items: MkWindowContract[]; kind: "ending" | "starting" }) {
  if (items.length === 0) return <span className={CALM_EMPTY}>—</span>;
  const margin = sumKnown(items.map(monthlyMargin));
  const sorted = [...items].sort((a, b) =>
    ((kind === "ending" ? a.end_date : a.start_date) ?? "").localeCompare((kind === "ending" ? b.end_date : b.start_date) ?? ""),
  );
  const names = sorted
    .map((c) => `${fmtDayMonth(kind === "ending" ? c.end_date : c.start_date)} ${c.candidate_name}`)
    .join("\n");
  return (
    <span title={names}>
      <span className="block font-medium text-foreground">{plural(items.length, OSOBY)}</span>
      <span className={CALM_SUBLINE}>{margin ? signedPln(kind === "ending" ? -margin : margin) : "marża nieznana"}</span>
    </span>
  );
}

function groupByClient(items: MkWindowContract[]): Map<number, MkWindowContract[]> {
  const map = new Map<number, MkWindowContract[]>();
  for (const c of items) map.set(c.client_id, [...(map.get(c.client_id) ?? []), c]);
  return map;
}

// ── Widok „Klienci” ────────────────────────────────────────────────────────

function ClientsTable({
  clients,
  ending,
  starting,
  totalMargin,
  totals,
}: {
  clients: MkMarginRow[];
  ending: MkWindowContract[];
  starting: MkWindowContract[];
  totalMargin: number | null;
  totals: { people: number; revenue: number | null; margin: number | null; pct: number | null };
}) {
  const [sort, setSort] = useState<Sort<ClientKey>>({ key: "margin", dir: "desc" });
  const rows = useMemo(() => {
    const endBy = groupByClient(ending);
    const startBy = groupByClient(starting);
    const list: ClientReportRow[] = clients.map((r) => ({
      clientId: r.client_id ?? 0,
      name: r.client_name ?? "—",
      people: r.active_contracts,
      revenue: r.fx_missing ? null : r.total_monthly_revenue,
      margin: r.fx_missing ? null : r.total_monthly_margin,
      pct: r.margin_pct,
      partial: (r.contracts_without_revenue_leg ?? 0) + (r.contracts_without_cost_leg ?? 0),
      ending: endBy.get(r.client_id ?? 0) ?? [],
      starting: startBy.get(r.client_id ?? 0) ?? [],
    }));
    // Klient, u którego dopiero ktoś startuje, nie ma jeszcze marży — ale
    // w raporcie „co się zmieni” musi być widać, że przybywa.
    const known = new Set(list.map((r) => r.clientId));
    for (const c of [...ending, ...starting]) {
      if (known.has(c.client_id)) continue;
      known.add(c.client_id);
      list.push({
        clientId: c.client_id,
        name: c.client_name,
        people: null,
        revenue: null,
        margin: null,
        pct: null,
        partial: 0,
        ending: endBy.get(c.client_id) ?? [],
        starting: startBy.get(c.client_id) ?? [],
      });
    }
    const value = (r: ClientReportRow): string | number | null => {
      switch (sort.key) {
        case "name":
          return r.name;
        case "people":
          return r.people;
        case "revenue":
          return r.revenue;
        case "margin":
          return r.margin;
        case "pct":
          return r.pct;
        case "ending":
          return r.ending.length || null;
        case "starting":
          return r.starting.length || null;
      }
    };
    return [...list].sort((a, b) => compare(value(a), value(b), sort.dir) || a.name.localeCompare(b.name, "pl"));
  }, [clients, ending, starting, sort]);
  const onlyStarting = rows.filter((r) => r.people == null).length;
  const onSort = (k: ClientKey) => setSort((s) => nextSort(s, k));
  const endingMargin = sumKnown(ending.map(monthlyMargin));
  const startingMargin = sumKnown(starting.map(monthlyMargin));

  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-border">
          <SortHead label="Klient" k="name" sort={sort} onSort={onSort} align="left" className="pl-4 pr-3" />
          <SortHead label="Osoby" k="people" sort={sort} onSort={onSort} className="w-[76px] px-3" />
          <SortHead label="Przychód" unit="zł / mies." k="revenue" sort={sort} onSort={onSort} className="w-[118px] px-3" />
          <SortHead label="Marża" unit="zł / mies." k="margin" sort={sort} onSort={onSort} className="w-[178px] px-3" />
          <SortHead label="Marża %" k="pct" sort={sort} onSort={onSort} className="w-[92px] px-3" />
          <SortHead label="Kończą się" unit="w 90 dni" k="ending" sort={sort} onSort={onSort} className="w-[120px] px-3" />
          <SortHead label="Startują" unit="w 90 dni" k="starting" sort={sort} onSort={onSort} className="w-[112px] pl-3 pr-4" />
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.clientId} className={cn(CALM_ROW, "align-middle")}>
            <td className="py-2 pl-4 pr-3">
              <Link
                href={`/clients/${r.clientId}`}
                title={r.name}
                className="block max-w-[300px] truncate font-medium text-foreground hover:text-primary hover:underline"
              >
                {r.name}
              </Link>
              {r.partial > 0 ? (
                <span className={CALM_SUBLINE}>{plural(r.partial, ["kontrakt", "kontrakty", "kontraktów"])} bez stawki — poza sumą</span>
              ) : r.people == null ? (
                <span className={CALM_SUBLINE}>dziś bez aktywnego kontraktu</span>
              ) : null}
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>
              {r.people ?? <span className={CALM_EMPTY}>—</span>}
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2")}>
              {r.revenue == null ? <span className={CALM_EMPTY}>—</span> : fmtInt(r.revenue)}
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2")}>
              <MarginCell value={r.margin} total={totalMargin} />
            </td>
            <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>{fmtPct(r.pct)}</td>
            <td className="px-3 py-2 text-right tabular-nums">
              <WindowCell items={r.ending} kind="ending" />
            </td>
            <td className="py-2 pl-3 pr-4 text-right tabular-nums">
              <WindowCell items={r.starting} kind="starting" />
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="border-t border-border bg-muted/40 font-semibold">
          <td className="py-2.5 pl-4 pr-3">
            Razem
            <span className={cn(CALM_SUBLINE, "font-normal")}>
              {plural(rows.length - onlyStarting, ["klient", "klientów", "klientów"])} z aktywnym kontraktem
              {onlyStarting ? ` + ${onlyStarting} ze startem` : ""}
            </span>
          </td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{totals.people}</td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{fmtInt(totals.revenue)}</td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
            <span className="inline-block min-w-[76px]">{fmtInt(totals.margin)}</span>
          </td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{fmtPct(totals.pct)}</td>
          <td className="px-3 py-2.5 text-right tabular-nums">
            {plural(ending.length, OSOBY)}
            <span className={cn(CALM_SUBLINE, "font-normal")}>{signedPln(-endingMargin)}</span>
          </td>
          <td className="py-2.5 pl-3 pr-4 text-right tabular-nums">
            {plural(starting.length, OSOBY)}
            <span className={cn(CALM_SUBLINE, "font-normal")}>{signedPln(startingMargin)}</span>
          </td>
        </tr>
      </tfoot>
    </table>
  );
}

// ── Widok „Konsultanci” ────────────────────────────────────────────────────

function PeopleTable({ people, ending, totalMargin }: { people: MkMarginRow[]; ending: MkWindowContract[]; totalMargin: number | null }) {
  const [sort, setSort] = useState<Sort<PersonKey>>({ key: "margin", dir: "desc" });
  const endBy = useMemo(() => {
    const map = new Map<number, MkWindowContract>();
    for (const c of ending) if (c.candidate_id != null) map.set(c.candidate_id, c);
    return map;
  }, [ending]);
  const rows = useMemo(() => {
    const value = (r: MkMarginRow): string | number | null => {
      switch (sort.key) {
        case "name":
          return r.candidate_name ?? null;
        case "contracts":
          return r.active_contracts;
        case "revenue":
          return r.total_monthly_revenue;
        case "margin":
          return r.total_monthly_margin;
        case "pct":
          return r.margin_pct;
        case "ending":
          return endBy.get(r.candidate_id ?? -1)?.end_date ?? null;
      }
    };
    return [...people].sort((a, b) => compare(value(a), value(b), sort.dir));
  }, [people, sort, endBy]);
  const onSort = (k: PersonKey) => setSort((s) => nextSort(s, k));
  const sumRevenue = people.reduce((a, r) => a + r.total_monthly_revenue, 0);
  const sumMargin = people.reduce((a, r) => a + r.total_monthly_margin, 0);
  const topMargin = people.reduce((a, r) => Math.max(a, r.total_monthly_margin), 0);

  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-border">
          <SortHead label="Konsultant" k="name" sort={sort} onSort={onSort} align="left" className="pl-4 pr-3" />
          <SortHead label="Kontrakty" k="contracts" sort={sort} onSort={onSort} className="w-[100px] px-3" />
          <SortHead label="Przychód" unit="zł / mies." k="revenue" sort={sort} onSort={onSort} className="w-[130px] px-3" />
          <SortHead label="Marża" unit="zł / mies." k="margin" sort={sort} onSort={onSort} className="w-[178px] px-3" />
          <SortHead label="Marża %" k="pct" sort={sort} onSort={onSort} className="w-[92px] px-3" />
          <SortHead label="Koniec umowy" unit="w 90 dni" k="ending" sort={sort} onSort={onSort} className="w-[190px] pl-3 pr-4" />
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const end = endBy.get(r.candidate_id ?? -1);
          return (
            <tr key={r.candidate_id} className={CALM_ROW}>
              <td className="py-2.5 pl-4 pr-3">
                <Link href={`/candidates/${r.candidate_id}`} className="font-medium text-foreground hover:text-primary hover:underline">
                  {r.candidate_name}
                </Link>
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2.5 text-muted-foreground")}>{r.active_contracts}</td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{r.fx_missing ? "—" : fmtInt(r.total_monthly_revenue)}</td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
                <MarginCell value={r.fx_missing ? null : r.total_monthly_margin} total={totalMargin} scale={topMargin} />
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2.5 text-muted-foreground")}>{fmtPct(r.margin_pct)}</td>
              <td className="py-2.5 pl-3 pr-4 text-right tabular-nums">
                {end ? (
                  <span title={end.client_name}>
                    {fmtDate(end.end_date)} <span className="text-muted-foreground">· {relDays(end.end_date)}</span>
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
          <td className="py-2.5 pl-4 pr-3">
            Razem
            <span className={cn(CALM_SUBLINE, "font-normal")}>{plural(people.length, OSOBY)} z najwyższą marżą</span>
          </td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{people.reduce((a, r) => a + r.active_contracts, 0)}</td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{fmtInt(sumRevenue)}</td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>
            <span className="inline-block min-w-[76px]">{fmtInt(sumMargin)}</span>
          </td>
          <td className={cn(CALM_AMOUNT, "px-3 py-2.5")}>{sumRevenue ? fmtPct((sumMargin / sumRevenue) * 100) : "—"}</td>
          <td className="py-2.5 pl-3 pr-4 text-right tabular-nums">
            {plural(rows.filter((r) => endBy.has(r.candidate_id ?? -1)).length, OSOBY)}
          </td>
        </tr>
      </tfoot>
    </table>
  );
}

// ── Strona ─────────────────────────────────────────────────────────────────

function ViewSwitch({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const options: { key: View; label: string }[] = [
    { key: "clients", label: "Klienci" },
    { key: "people", label: "Konsultanci" },
  ];
  return (
    <div role="tablist" aria-label="Zestawienie" className="inline-flex rounded-lg bg-muted p-0.5">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          role="tab"
          aria-selected={view === o.key}
          onClick={() => onChange(o.key)}
          className={cn(
            "rounded-md px-3 py-1 text-[12.5px] font-medium transition-colors",
            view === o.key ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Panel({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      {children}
      {footer ? <p className="border-t border-border/60 px-4 py-2 text-[12px] text-muted-foreground">{footer}</p> : null}
    </section>
  );
}

export function AnalyticsB() {
  const [view, setView] = useState<View>("clients");
  const { totals, util, clients } = useMkAnalytics();
  const { ending, starting } = useMkNext90();
  const people = useQuery<MkMarginRow[]>({
    queryKey: ["mk-ca-margin-by-contractor", 100],
    queryFn: () =>
      api.get<MkMarginRow[]>("/api/contract-analytics/margin-by-contractor", { params: { limit: 100 } }).then((r) => r.data),
    enabled: view === "people",
  });
  const t = totals.data;
  const u = util.data;
  const endingItems = (ending.data?.items ?? []) as MkWindowContract[];
  const startingItems = (starting.data?.items ?? []) as MkWindowContract[];
  const totalMargin = t && !t.fx_missing ? t.total_monthly_margin : null;
  const windowsReady = ending.isSuccess && starting.isSuccess;

  const stats = [
    { id: "margin", label: "Marża / mies.", value: t ? fmtPln(t.total_monthly_margin) : "—" },
    { id: "revenue", label: "Przychód / mies.", value: t ? fmtPln(t.total_monthly_revenue) : "—" },
    { id: "pct", label: "Marża z przychodu", value: t ? fmtPct(t.margin_pct) : "—" },
    {
      id: "util",
      label: "Utylizacja",
      value: u ? fmtPct(u.utilization_pct) : "—",
      title: u ? `${u.candidates_active} z ${u.total_candidates} konsultantów pracuje` : undefined,
    },
    {
      id: "bench",
      label: "Na ławce",
      value: u ? plural(u.candidates_on_bench, OSOBY) : "—",
      title: u?.avg_bench_days != null ? `średnio ${Math.round(u.avg_bench_days)} dni bez kontraktu` : undefined,
    },
    {
      id: "ending",
      label: "Kończą się w 90 dni",
      value: windowsReady
        ? `${plural(endingItems.length, OSOBY)} · ${signedPln(-sumKnown(endingItems.map(monthlyMargin)))}`
        : "—",
      title: "Marża miesięczna, która odejdzie z kończącymi się umowami",
    },
    {
      id: "starting",
      label: "Startują w 90 dni",
      value: windowsReady
        ? `${plural(startingItems.length, OSOBY)} · ${signedPln(sumKnown(startingItems.map(monthlyMargin)))}`
        : "—",
      title: "Marża miesięczna, którą dodadzą umowy startujące w 90 dni",
    },
  ];

  const clientsReady = clients.isSuccess && windowsReady && totals.isSuccess;
  return (
    <div className="space-y-4">
      <AnalyticsHead
        subtitle="Raport dla aktywnych i kończących się kontraktów; kwoty miesięczne w złotych."
        right={<ViewSwitch view={view} onChange={setView} />}
      />
      <InlineStats stats={stats} className="gap-x-7 rounded-xl border border-border bg-card px-4 py-3 shadow-xs" />

      {view === "clients" ? (
        <Panel
          footer={
            clientsReady
              ? "„Kończą się” i „Startują” liczą umowy z datą końca albo startu w najbliższych 90 dniach; kwota pod liczbą to marża z bieżących stawek."
              : undefined
          }
        >
          {clients.isError || ending.isError || starting.isError || totals.isError ? (
            <QueryLine error>Nie udało się pobrać raportu — odśwież stronę.</QueryLine>
          ) : !clientsReady || !t ? (
            <QueryLine>Ładowanie raportu…</QueryLine>
          ) : (clients.data ?? []).length === 0 ? (
            <QueryLine>Żaden klient nie ma dziś aktywnego kontraktu.</QueryLine>
          ) : (
            <ClientsTable
              clients={clients.data ?? []}
              ending={endingItems}
              starting={startingItems}
              totalMargin={totalMargin}
              totals={{
                people: t.active_contracts,
                revenue: t.fx_missing ? null : t.total_monthly_revenue,
                margin: t.fx_missing ? null : t.total_monthly_margin,
                pct: t.margin_pct,
              }}
            />
          )}
        </Panel>
      ) : (
        <Panel
          footer={
            people.isSuccess && u
              ? `Pokazano ${plural((people.data ?? []).length, OSOBY)} z najwyższą marżą z ${u.candidates_active} pracujących — sumy całej firmy są w nagłówku.`
              : undefined
          }
        >
          {people.isError ? (
            <QueryLine error>Nie udało się pobrać zestawienia konsultantów.</QueryLine>
          ) : !people.isSuccess ? (
            <QueryLine>Ładowanie…</QueryLine>
          ) : (people.data ?? []).length === 0 ? (
            <QueryLine>Nikt nie ma dziś aktywnego kontraktu.</QueryLine>
          ) : (
            <PeopleTable people={people.data ?? []} ending={endingItems} totalMargin={totalMargin} />
          )}
        </Panel>
      )}
    </div>
  );
}
