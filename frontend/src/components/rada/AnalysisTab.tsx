"use client";

import * as React from "react";
import Link from "next/link";
import { FileUp, Pencil, Trash2 } from "lucide-react";

import { AppModal, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBoardAnalysis,
  useDeleteBoardStatement,
  useImportBoardStatement,
  useSaveBoardStatement,
  type AnalysisView,
  type RatioNorm,
  type StatementMetrics,
  type StatementYear,
} from "@/lib/api/supervisory-board";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

// ── Czyste wyliczenia (testy) ────────────────────────────────────────────────

/** Ostatni pełny rok (sprawozdanie albo zamknięta księga) — podstawa kredytu i wyceny. */
export function latestFullYear(years: StatementYear[]): StatementYear | null {
  const full = years.filter((y) => y.partial_months === null);
  return full.length ? full[full.length - 1] : null;
}

export interface CreditCapacity {
  maxNetDebt: number;
  headroom: number;
}

/** Dług netto do `multiple` × EBITDA; wolny limit = maks. − obecny dług netto. */
export function creditCapacity(ebitda: number | null, netDebt: number | null, multiple: number): CreditCapacity | null {
  if (ebitda === null || ebitda <= 0) return null;
  const maxNetDebt = ebitda * multiple;
  return { maxNetDebt, headroom: maxNetDebt - (netDebt ?? 0) };
}

export interface EquityValue {
  ev: number;
  equity: number;
}

/** EV = EBITDA × mnożnik; kapitał = EV − dług netto (gotówka netto podnosi wartość). */
export function equityValue(ebitda: number | null, netDebt: number | null, multiple: number): EquityValue | null {
  if (ebitda === null || ebitda <= 0) return null;
  const ev = ebitda * multiple;
  return { ev, equity: ev - (netDebt ?? 0) };
}

export type Tone = "good" | "bad" | "neutral";

/** Wskaźnik w przedziale „zdrowym” z normy → good, poza nim → bad. */
export function ratioTone(value: number | null, norm: RatioNorm | undefined): Tone {
  if (value === null || !norm) return "neutral";
  const [low, high] = norm.good;
  return value >= low && value <= high ? "good" : "bad";
}

export function missingYears(view: AnalysisView): number[] {
  const have = new Set(view.years.filter((y) => y.partial_months === null).map((y) => y.year));
  return view.expected_years.filter((year) => !have.has(year));
}

// ── Formatowanie ─────────────────────────────────────────────────────────────

const PERCENT = new Set(["ebitda_margin", "net_margin", "roe", "roa"]);
const DAYS = new Set(["dso", "dpo"]);
const RATIO_ORDER: (keyof StatementMetrics)[] = [
  "current_ratio",
  "quick_ratio",
  "cash_ratio",
  "debt_ratio",
  "equity_ratio",
  "net_debt_ebitda",
  "dso",
  "dpo",
  "ebitda_margin",
  "net_margin",
  "roe",
  "roa",
];

function mln(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return `${(value / 1_000_000).toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits })} mln`;
}

function fmtMetric(key: string, value: number | null): string {
  if (value === null) return "—";
  if (PERCENT.has(key)) return `${(value * 100).toLocaleString("pl-PL", { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`;
  if (DAYS.has(key)) return `${Math.round(value)} dni`;
  return value.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function growthLabel(value: number | null): string | undefined {
  if (value === null) return undefined;
  return `${value > 0 ? "+" : ""}${value.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}% r/r`;
}

const SOURCE_BADGE: Record<StatementYear["source"], { label: string; variant: "success" | "neutral" | "warning" | "info" }> = {
  xml: { label: "e-Sprawozdanie", variant: "success" },
  xml_prev: { label: "z pliku za rok następny", variant: "info" },
  manual: { label: "wpis ręczny", variant: "neutral" },
  ledger: { label: "księga NEXUSA", variant: "warning" },
};

// ── Widok ────────────────────────────────────────────────────────────────────

export function AnalysisTab() {
  const isAdmin = hasRole(useAuthStore((s) => s.user), "admin");
  const analysis = useBoardAnalysis();
  const [editing, setEditing] = React.useState<StatementYear | "new" | null>(null);
  const state = resolveViewState({
    isLoading: analysis.isLoading,
    isError: analysis.isError,
    error: analysis.error,
    isSuccess: analysis.isSuccess,
  });
  if (isBlockingViewState(state)) {
    return <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => analysis.refetch()} />;
  }
  if (!analysis.data) {
    return <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  }
  const view = analysis.data;
  const missing = missingYears(view);
  const latest = latestFullYear(view.years);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12px] text-muted-foreground">
          Sprawozdania roczne (bilans i RZiS) — z e-Sprawozdań z eKRS, z księgi NEXUSA albo wpisane z PDF. Kwoty w zł.
        </p>
        {isAdmin ? <AdminActions onManual={() => setEditing("new")} /> : null}
      </div>

      {missing.length ? (
        <div className="rounded-lg border border-warning/40 bg-warning-muted px-3.5 py-2.5 text-[12px] text-warning-muted-foreground">
          Brak sprawozdania za {missing.join(", ")}. Plik XML pobiera się z eKRS (Repozytorium Dokumentów Finansowych,
          „Pobierz plik”) i wgrywa przyciskiem „Wgraj e-Sprawozdanie”; kolumna „rok poprzedni” uzupełni rok wcześniejszy.
        </div>
      ) : null}

      {view.years.length === 0 ? (
        <section className="rounded-lg border border-border bg-card p-6 text-center">
          <h2 className="text-sm font-semibold text-foreground">Nie ma jeszcze sprawozdań rocznych</h2>
          <p className="mx-auto mt-1 max-w-xl text-[12px] text-muted-foreground">
            Wskaźniki płynności, zadłużenia, zdolność kredytowa i wycena liczą się z bilansu i rachunku zysków i strat.
            {isAdmin
              ? " Wgraj pliki XML za trzy ostatnie lata albo wpisz kwoty z PDF."
              : " Pojawią się, gdy Zarząd wgra sprawozdania."}
          </p>
        </section>
      ) : (
        <>
          {latest ? <Headline year={latest} /> : null}
          <RatiosTable view={view} />
          {latest ? (
            <div className="grid gap-3 lg:grid-cols-2">
              <CreditCard year={latest} view={view} />
              <ValuationCard year={latest} view={view} />
            </div>
          ) : null}
          <SourcesTable view={view} isAdmin={isAdmin} onEdit={(y) => setEditing(y)} />
        </>
      )}
      {editing ? (
        <ManualDialog view={view} year={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      ) : null}
    </div>
  );
}

function AdminActions({ onManual }: { onManual: () => void }) {
  const { showToast } = useToast();
  const upload = useImportBoardStatement();
  const input = React.useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-2">
      <input
        ref={input}
        type="file"
        accept=".xml,.xades"
        className="hidden"
        data-testid="board-statement-file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          upload.mutate(file, {
            onSuccess: (r) =>
              showToast(
                `Wczytano sprawozdanie za ${r.year}: ${r.fields_found} z ${r.fields_total} pól` +
                  (r.previous_year_filled ? `, uzupełniono też ${r.year - 1}.` : "."),
              ),
            onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wczytać pliku."), "error"),
          });
        }}
      />
      <Button size="sm" variant="outline" onClick={onManual}>
        <Pencil className="mr-1 h-3.5 w-3.5" />
        Wpisz rok ręcznie
      </Button>
      <Button size="sm" onClick={() => input.current?.click()} disabled={upload.isPending}>
        <FileUp className="mr-1 h-3.5 w-3.5" />
        Wgraj e-Sprawozdanie
      </Button>
    </div>
  );
}

function Kpi({ label, value, sub, tone = "neutral" }: { label: string; value: string; sub?: string; tone?: Tone }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3.5 py-3">
      <div className="truncate text-[12px] font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-[22px] font-semibold leading-tight tabular-nums",
          tone === "bad" ? "text-destructive" : tone === "good" ? "text-success" : "text-foreground",
        )}
      >
        {value}
      </div>
      {sub ? <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

function Headline({ year }: { year: StatementYear }) {
  const m = year.metrics;
  const a = year.amounts;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Kpi label={`Przychody ${year.year}`} value={mln(a.revenue)} sub={growthLabel(year.growth.revenue)} />
      <Kpi
        label="EBITDA"
        value={mln(m.ebitda)}
        sub={[m.ebitda_margin !== null ? `marża ${fmtMetric("ebitda_margin", m.ebitda_margin)}` : null, growthLabel(year.growth.ebitda)]
          .filter(Boolean)
          .join(" · ")}
      />
      <Kpi label="Zysk netto" value={mln(a.net_profit)} sub={growthLabel(year.growth.net_profit)} tone={(a.net_profit ?? 0) < 0 ? "bad" : "neutral"} />
      <Kpi
        label={m.net_debt !== null && m.net_debt < 0 ? "Gotówka netto" : "Dług netto"}
        value={mln(m.net_debt === null ? null : Math.abs(m.net_debt))}
        sub={`kredyty, pożyczki i leasing ${mln(m.financial_debt)} · gotówka ${mln(a.cash)}`}
        tone={m.net_debt !== null && m.net_debt < 0 ? "good" : "neutral"}
      />
    </div>
  );
}

function RatiosTable({ view }: { view: AnalysisView }) {
  const years = view.years;
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h2 className="mb-2 text-sm font-semibold text-foreground">Wyniki i wskaźniki</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px] tabular-nums">
          <thead>
            <tr className="border-b border-border text-[11px] text-muted-foreground">
              <th className="py-1.5 pr-2 text-left font-medium" />
              {years.map((y) => (
                <th key={y.year} className="py-1.5 pl-3 text-right font-medium">
                  {y.year}
                  {y.partial_months !== null ? ` (I–${y.partial_months})` : ""}
                </th>
              ))}
              <th className="py-1.5 pl-3 text-left font-medium">Zdrowy przedział</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            <AmountRow label="Przychody netto" values={years.map((y) => y.amounts.revenue)} />
            <AmountRow label="EBITDA" values={years.map((y) => y.metrics.ebitda)} />
            <AmountRow label="Zysk operacyjny" values={years.map((y) => y.amounts.operating_profit)} />
            <AmountRow label="Zysk netto" values={years.map((y) => y.amounts.net_profit)} />
            <AmountRow label="Kapitał własny" values={years.map((y) => y.amounts.equity)} />
            {RATIO_ORDER.map((key) => {
              const norm = view.norms[key];
              return (
                <tr key={key}>
                  <td className="py-1.5 pr-2 text-left font-medium" title={norm?.formula}>
                    {norm?.label ?? key}
                  </td>
                  {years.map((y) => {
                    const value = y.metrics[key];
                    const tone = y.partial_months === null ? ratioTone(value, norm) : "neutral";
                    return (
                      <td
                        key={y.year}
                        className={cn(
                          "py-1.5 pl-3 text-right",
                          tone === "bad" && "text-destructive",
                          tone === "good" && "text-success",
                          value === null && "text-muted-foreground",
                        )}
                      >
                        {fmtMetric(key, value)}
                      </td>
                    );
                  })}
                  <td className="py-1.5 pl-3 text-left text-[11px] text-muted-foreground">{normLabel(key, norm)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        Wzór wskaźnika w podpowiedzi przy nazwie. Rok z księgi w trakcie (I–n) nie jest oceniany — RZiS obejmuje tylko część roku.
        Kolor: w przedziale typowym dla spółki usługowej bez majątku (zielony) albo poza nim (czerwony).
      </p>
    </section>
  );
}

function normLabel(key: string, norm: RatioNorm | undefined): string {
  if (!norm) return "";
  const [low, high] = norm.good;
  if (key === "net_debt_ebitda") return `do ${fmtMetric(key, high)}`;
  if (low <= 0) return `do ${fmtMetric(key, high)}`;
  if (high >= 10 || (PERCENT.has(key) && high >= 1)) return `od ${fmtMetric(key, low)}`;
  return `${fmtMetric(key, low)} – ${fmtMetric(key, high)}`;
}

function AmountRow({ label, values }: { label: string; values: (number | null | undefined)[] }) {
  return (
    <tr>
      <td className="py-1.5 pr-2 text-left font-semibold">{label}</td>
      {values.map((v, i) => (
        <td key={i} className={cn("py-1.5 pl-3 text-right", (v ?? null) === null && "text-muted-foreground")}>
          {mln(v)}
        </td>
      ))}
      <td />
    </tr>
  );
}

function Slider({
  id,
  label,
  value,
  min,
  max,
  step,
  onChange,
  suffix = "×",
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  suffix?: string;
}) {
  return (
    <label className="flex items-center gap-2 whitespace-nowrap text-[12px] text-muted-foreground" htmlFor={id}>
      {label}
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 min-w-0 accent-[hsl(var(--primary))]"
      />
      <span className="w-10 font-semibold tabular-nums text-foreground">
        {value.toLocaleString("pl-PL", { maximumFractionDigits: 2 })}
        {suffix}
      </span>
    </label>
  );
}

function Fact({ label, value, strong, tone }: { label: string; value: string; strong?: boolean; tone?: Tone }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-[12px]">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={cn(
          "tabular-nums",
          strong ? "text-[15px] font-semibold" : "font-medium",
          tone === "good" && "text-success",
          tone === "bad" && "text-destructive",
          !tone && "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function CreditCard({ year, view }: { year: StatementYear; view: AnalysisView }) {
  const [multiple, setMultiple] = React.useState(view.defaults.debt_to_ebitda);
  const capacity = creditCapacity(year.metrics.ebitda, year.metrics.net_debt, multiple);
  const receivables = year.amounts.trade_receivables;
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Zdolność kredytowa ({year.year})</h2>
        <Slider id="board-credit-multiple" label="Dług netto / EBITDA do" value={multiple} min={1.5} max={4.5} step={0.25} onChange={setMultiple} />
      </div>
      {capacity ? (
        <div className="divide-y divide-border">
          <Fact label="Maksymalny dług netto" value={mln(capacity.maxNetDebt)} />
          <Fact label="Dług netto dziś (ze sprawozdania)" value={mln(year.metrics.net_debt)} />
          <Fact label="Wolny limit zadłużenia" value={mln(capacity.headroom)} strong tone={capacity.headroom > 0 ? "good" : "bad"} />
          <Fact
            label={`Faktoring (do ${Math.round(view.defaults.factoring_share * 100)}% należności z tytułu dostaw)`}
            value={receivables ? mln(receivables * view.defaults.factoring_share) : "—"}
          />
          <Fact label="Rotacja należności" value={fmtMetric("dso", year.metrics.dso)} />
        </div>
      ) : (
        <p className="text-[12px] text-muted-foreground">EBITDA ujemna albo nieznana — bank oceni spółkę po zabezpieczeniach, nie po wyniku.</p>
      )}
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        Orientacyjnie: banki finansują spółki usługowe bez majątku zwykle do 2,5–3,5× EBITDA długu netto, a faktoring pod
        należności od dużych klientów do 80–90% ich wartości. Ostateczny limit zależy od kowenantów i zabezpieczeń.
      </p>
    </section>
  );
}

function ValuationCard({ year, view }: { year: StatementYear; view: AnalysisView }) {
  const d = view.defaults;
  const [financial, setFinancial] = React.useState(d.financial_multiple);
  const [strategic, setStrategic] = React.useState(d.strategic_multiple);
  const fin = equityValue(year.metrics.ebitda, year.metrics.net_debt, financial);
  const str = equityValue(year.metrics.ebitda, year.metrics.net_debt, strategic);
  const revenue = year.amounts.revenue;
  const evToSales = (ev: number | undefined) =>
    ev !== undefined && revenue ? `${(ev / revenue).toLocaleString("pl-PL", { maximumFractionDigits: 2 })}×` : "—";
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h2 className="mb-2 text-sm font-semibold text-foreground">Wartość firmy ({year.year}, EBITDA {mln(year.metrics.ebitda)})</h2>
      {fin && str ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Investor
            title="Inwestor finansowy (fundusz)"
            id="board-valuation-financial"
            multiple={financial}
            range={d.financial_range}
            onChange={setFinancial}
            value={fin}
            check={evToSales(fin.ev)}
          />
          <Investor
            title="Inwestor branżowy"
            id="board-valuation-strategic"
            multiple={strategic}
            range={d.strategic_range}
            onChange={setStrategic}
            value={str}
            check={evToSales(str.ev)}
          />
        </div>
      ) : (
        <p className="text-[12px] text-muted-foreground">Bez dodatniej EBITDA wycena mnożnikowa nie ma sensu.</p>
      )}
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        EV — wartość przedsiębiorstwa = EBITDA × mnożnik; wartość kapitału (dla udziałowców) = EV − dług netto. Fundusz płaci za przepływy, które może zadłużyć (domyślnie{" "}
        {d.financial_multiple}×), inwestor branżowy dopłaca za klientów i ludzi, których przejmuje ({d.strategic_multiple}×). W body
        leasingu przy niskiej marży sprawdzaj kontrolę: zwykle 0,3–0,6× przychodów. To nie jest wycena biegłego.
      </p>
    </section>
  );
}

function Investor({
  title,
  id,
  multiple,
  range,
  onChange,
  value,
  check,
}: {
  title: string;
  id: string;
  multiple: number;
  range: [number, number];
  onChange: (v: number) => void;
  value: EquityValue;
  check: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[12px] font-semibold text-foreground">{title}</div>
      <Slider id={id} label="EV / EBITDA" value={multiple} min={range[0]} max={range[1]} step={0.5} onChange={onChange} />
      <div className="mt-1 divide-y divide-border">
        <Fact label="EV" value={mln(value.ev)} />
        <Fact label="Wartość kapitału" value={mln(value.equity)} strong />
        <Fact label="EV / przychody" value={check} />
      </div>
    </div>
  );
}

function SourcesTable({ view, isAdmin, onEdit }: { view: AnalysisView; isAdmin: boolean; onEdit: (y: StatementYear) => void }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const remove = useDeleteBoardStatement();
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h2 className="mb-2 text-sm font-semibold text-foreground">Źródła</h2>
      <table className="w-full text-[12px]">
        <tbody className="divide-y divide-border">
          {view.years.map((y) => (
            <tr key={y.year}>
              <td className="py-1.5 pr-3 font-semibold tabular-nums">{y.year}</td>
              <td className="py-1.5 pr-3">
                <Badge variant={SOURCE_BADGE[y.source].variant} size="sm">
                  {SOURCE_BADGE[y.source].label}
                </Badge>
              </td>
              <td className="py-1.5 pr-3 text-muted-foreground">
                {y.source_label}
                {y.raw_count ? ` · ${y.raw_count} pozycji w pliku` : ""}
                {y.note ? ` · ${y.note}` : ""}
              </td>
              <td className="py-1.5 text-right">
                <div className="flex items-center justify-end gap-1">
                  {y.document_id ? (
                    <Link className="text-[12px] text-primary hover:underline" href="/rada?tab=dokumenty">
                      plik w Dokumentach
                    </Link>
                  ) : null}
                  {isAdmin && y.source !== "ledger" ? (
                    <>
                      <Button size="sm" variant="ghost" aria-label={`Popraw ${y.year}`} onClick={() => onEdit(y)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Usuń ${y.year}`}
                        onClick={async () => {
                          const ok = await askConfirm({
                            title: `Usunąć sprawozdanie za ${y.year}?`,
                            description: "Kwoty znikną z analizy. Plik w Dokumentach zostaje.",
                            confirmLabel: "Usuń",
                            variant: "destructive",
                          });
                          if (!ok) return;
                          remove.mutate(y.year, {
                            onSuccess: () => showToast(`Usunięto sprawozdanie za ${y.year}.`),
                            onError: (e) => showToast(apiErrorMessage(e, "Nie udało się usunąć."), "error"),
                          });
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {confirmDialog}
    </section>
  );
}

// ── Wpis ręczny (admin) ──────────────────────────────────────────────────────

const GROUP_LABELS = { income: "Rachunek zysków i strat", assets: "Aktywa", liabilities: "Pasywa" } as const;

export function parseAmount(raw: string): number | null | "invalid" {
  const text = raw.replace(/\s/g, "").replace(",", ".");
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : "invalid";
}

function ManualDialog({ view, year, onClose }: { view: AnalysisView; year: StatementYear | null; onClose: () => void }) {
  const { showToast } = useToast();
  const save = useSaveBoardStatement();
  const firstMissing = missingYears(view)[0] ?? new Date().getFullYear() - 1;
  const [yearText, setYearText] = React.useState(String(year?.year ?? firstMissing));
  const taken = year === null && view.years.some((y) => String(y.year) === yearText && y.source !== "ledger");
  const [note, setNote] = React.useState(year?.note ?? "");
  const [cells, setCells] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(
      view.fields.map((f) => {
        const v = year?.amounts[f.key];
        return [f.key, v === null || v === undefined ? "" : String(v).replace(".", ",")];
      }),
    ),
  );
  const parsed = Object.fromEntries(Object.entries(cells).map(([k, v]) => [k, parseAmount(v)]));
  const invalid = Object.values(parsed).some((v) => v === "invalid") || !/^\d{4}$/.test(yearText);

  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title={year ? `Sprawozdanie za ${year.year}` : "Sprawozdanie roczne — wpis ręczny"}
      description="Kwoty w złotych z PDF sprawozdania (np. 120 450 300,12). Puste pole = pozycji nie ma."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Anuluj
          </Button>
          <Button
            disabled={save.isPending || invalid}
            onClick={() =>
              save.mutate(
                {
                  year: Number(yearText),
                  amounts: Object.fromEntries(Object.entries(parsed).map(([k, v]) => [k, v === "invalid" ? null : v])),
                  note: note.trim() || null,
                },
                {
                  onSuccess: () => {
                    showToast("Zapisano sprawozdanie.");
                    onClose();
                  },
                  onError: (e) => showToast(apiErrorMessage(e, "Nie udało się zapisać."), "error"),
                },
              )
            }
          >
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-[120px_1fr]">
        <div className="space-y-1">
          <Label htmlFor="board-statement-year">Rok</Label>
          <Input id="board-statement-year" inputMode="numeric" value={yearText} disabled={year !== null} onChange={(e) => setYearText(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-statement-note">Uwagi</Label>
          <Input id="board-statement-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      </div>
      {taken ? (
        <p className="mt-2 text-[12px] text-warning-muted-foreground">
          Za {yearText} jest już sprawozdanie — zapis zastąpi je wpisem ręcznym.
        </p>
      ) : null}
      {(["income", "assets", "liabilities"] as const).map((group) => (
        <fieldset key={group} className="mt-3">
          <legend className="mb-1 text-[12px] font-semibold text-foreground">{GROUP_LABELS[group]}</legend>
          <div className="grid gap-x-3 gap-y-1.5 sm:grid-cols-2">
            {view.fields
              .filter((f) => f.group === group)
              .map((f) => (
                <label key={f.key} className="flex items-center justify-between gap-2 text-[12px]">
                  <span className="min-w-0 leading-tight text-muted-foreground">{f.label}</span>
                  <Input
                    aria-label={f.label}
                    inputMode="decimal"
                    value={cells[f.key]}
                    onChange={(e) => setCells((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    className={cn("h-8 w-32 shrink-0 text-right tabular-nums", parsed[f.key] === "invalid" && "border-destructive")}
                  />
                </label>
              ))}
          </div>
        </fieldset>
      ))}
    </AppModal>
  );
}
