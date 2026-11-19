"use client";

import * as React from "react";
import { Pencil } from "lucide-react";

import { AppModal, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBoardBudget,
  useBoardDocuments,
  useSaveBoardBudget,
  type BudgetView,
} from "@/lib/api/supervisory-board";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
type Scenario = "renewed" | "base";

export interface BudgetRow {
  month: number;
  kind: "actual" | "forecast";
  planSales: number | null;
  planCosts: number | null;
  sales: number | null;
  costs: number | null;
  /** Koszty to szacunek (prognoza albo miesiąc, którego faktury kosztowe jeszcze spływają). */
  costsEstimated: boolean;
}

/** Wykonanie + prognoza przy wybranej realizacji i scenariuszu (czysta funkcja). */
export function budgetRows(data: BudgetView, realization: number, scenario: Scenario): BudgetRow[] {
  return data.months.map((m) => {
    if (m.kind === "actual") {
      const estimate = !m.costs_complete && m.sales !== null && data.cost_share !== null;
      return {
        month: m.month,
        kind: m.kind,
        planSales: m.plan_sales,
        planCosts: m.plan_costs,
        sales: m.sales,
        costs: estimate ? (m.sales as number) * (data.cost_share as number) : m.costs,
        costsEstimated: estimate,
      };
    }
    const cap = scenario === "renewed" ? m.potential_renewed : m.potential;
    const sales = cap === null ? null : cap * realization;
    const costs = sales === null || data.cost_share === null ? null : sales * data.cost_share;
    return { month: m.month, kind: m.kind, planSales: m.plan_sales, planCosts: m.plan_costs, sales, costs, costsEstimated: true };
  });
}

function sum(values: (number | null)[]): number | null {
  const present = values.filter((v): v is number => v !== null);
  return present.length ? present.reduce((a, b) => a + b, 0) : null;
}

function num(value: number | null, digits = 2): string {
  if (value === null) return "—";
  return value.toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function BudgetTab() {
  const thisYear = new Date().getFullYear();
  const [year, setYear] = React.useState(thisYear);
  const [scenario, setScenario] = React.useState<Scenario>("renewed");
  const [realization, setRealization] = React.useState<number | null>(null);
  const [editing, setEditing] = React.useState(false);
  const isAdmin = hasRole(useAuthStore((s) => s.user), "admin");
  const budget = useBoardBudget(year);
  const state = resolveViewState({
    isLoading: budget.isLoading,
    isError: budget.isError,
    error: budget.error,
    isSuccess: budget.isSuccess,
  });
  if (isBlockingViewState(state)) {
    return <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => budget.refetch()} />;
  }
  if (!budget.data) {
    return <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  }
  const data = budget.data;
  const real = realization ?? data.realization ?? 0.8;
  const rows = budgetRows(data, real, scenario);
  const planSales = sum(rows.map((r) => r.planSales));
  const planCosts = sum(rows.map((r) => r.planCosts));
  const yearSales = sum(rows.map((r) => r.sales));
  const yearCosts = sum(rows.map((r) => r.costs));
  const baseSales = sum(budgetRows(data, real, "base").map((r) => r.sales));
  const renewedSales = sum(budgetRows(data, real, "renewed").map((r) => r.sales));
  const hasForecast = rows.some((r) => r.kind === "forecast");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentedRadio<string>
          label="Rok budżetu"
          size="sm"
          value={String(year)}
          onChange={(v) => {
            setYear(Number(v));
            setRealization(null);
          }}
          options={[thisYear - 1, thisYear, thisYear + 1].map((y) => ({ value: String(y), label: String(y) }))}
        />
        <div className="flex items-center gap-2">
          {data.budget ? (
            <Badge variant={data.budget.status === "adopted" ? "success" : "neutral"} size="sm">
              {data.budget.status === "adopted" ? "przyjęty uchwałą" : "szkic"}
            </Badge>
          ) : (
            <Badge variant="warning" size="sm">
              bez planu
            </Badge>
          )}
          {isAdmin ? (
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              <Pencil className="mr-1 h-3.5 w-3.5" />
              {data.budget ? "Popraw plan" : "Wpisz plan"}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label={`Plan sprzedaży ${year}`} value={planSales === null ? "brak planu" : `${num(planSales, 1)} mln`} sub={planCosts === null ? undefined : `koszty ${num(planCosts, 1)} mln`} />
        <Kpi
          label={hasForecast ? "Wykonanie + prognoza" : "Wykonanie"}
          value={`${num(yearSales, 1)} mln`}
          sub={planSales && yearSales !== null ? `${num((100 * yearSales) / planSales, 1)}% planu` : undefined}
          tone={planSales && yearSales !== null && yearSales < planSales ? "bad" : "neutral"}
        />
        <Kpi
          label="Wynik z faktur — rok"
          value={yearSales !== null && yearCosts !== null ? `${num(yearSales - yearCosts, 1)} mln` : "—"}
          sub={planSales !== null && planCosts !== null ? `plan ${num(planSales - planCosts, 1)} mln` : undefined}
        />
        <Kpi
          label="Bez przedłużeń"
          value={baseSales !== null && renewedSales !== null ? `−${num(renewedSales - baseSales, 1)} mln` : "—"}
          sub="sprzedaży, gdy kończące się umowy i zamówienia nie zostaną przedłużone"
          tone={baseSales !== null && renewedSales !== null && renewedSales - baseSales > 0.05 * renewedSales ? "warn" : "neutral"}
        />
      </div>

      <section className="min-w-0 rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-foreground">Plan, wykonanie i prognoza (mln zł netto)</h2>
          {hasForecast ? (
            <div className="flex flex-wrap items-center gap-3 text-[12px] text-muted-foreground">
              <SegmentedRadio<Scenario>
                label="Scenariusz"
                size="sm"
                value={scenario}
                onChange={setScenario}
                options={[
                  { value: "renewed", label: "Przedłużone" },
                  { value: "base", label: "Bez przedłużeń" },
                ]}
              />
              <label className="flex items-center gap-2" htmlFor="board-budget-realization">
                Realizacja godzin
                <input
                  id="board-budget-realization"
                  type="range"
                  min={50}
                  max={100}
                  step={1}
                  value={Math.round(real * 100)}
                  onChange={(e) => setRealization(Number(e.target.value) / 100)}
                  className="w-28 accent-[hsl(var(--primary))]"
                />
                <span className="w-9 font-semibold tabular-nums text-foreground">{Math.round(real * 100)}%</span>
              </label>
            </div>
          ) : null}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[12px] tabular-nums">
            <thead>
              <tr className="border-b border-border text-[11px] text-muted-foreground">
                <th className="sticky left-0 z-10 min-w-[120px] bg-card py-1.5 pr-2 text-left font-medium" />
                {ROMAN.map((m) => (
                  <th key={m} className="px-1.5 py-1.5 text-right font-medium">
                    {m}
                  </th>
                ))}
                <th className="py-1.5 pl-2 text-right font-medium">Rok</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              <Line label="Sprzedaż — plan" values={rows.map((r) => r.planSales)} total={planSales} muted />
              <Line label="Sprzedaż — wyk./progn." values={rows.map((r) => r.sales)} forecast={rows.map((r) => r.kind === "forecast")} total={yearSales} />
              <Line label="Koszty z faktur" values={rows.map((r) => r.costs)} forecast={rows.map((r) => r.costsEstimated)} total={yearCosts} />
              <tr>
                <td className="sticky left-0 z-10 bg-card py-1.5 pr-2 text-left font-semibold">Wynik — odchylenie od planu</td>
                {rows.map((r) => {
                  if (r.planSales === null || r.planCosts === null || r.sales === null || r.costs === null) {
                    return (
                      <td key={r.month} className="px-1.5 py-1.5 text-right text-muted-foreground">
                        —
                      </td>
                    );
                  }
                  const d = r.sales - r.costs - (r.planSales - r.planCosts);
                  return (
                    <td key={r.month} className={cn("px-1.5 py-1.5 text-right", d < 0 ? "text-destructive" : "text-success")}>
                      {d > 0 ? "+" : ""}
                      {num(d)}
                    </td>
                  );
                })}
                <td className="py-1.5 pl-2 text-right font-semibold">
                  {planSales !== null && planCosts !== null && yearSales !== null && yearCosts !== null
                    ? num(yearSales - yearCosts - (planSales - planCosts))
                    : "—"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
          Wykonanie: faktury z archiwum wg daty wystawienia (przesunięcia między miesiącami się znoszą w roku). Prognoza (kursywa):
          {` ${data.contracts}`} aktywnych kontraktów × stawki po kursie NBP × dni robocze miesiąca × realizacja
          {data.realization !== null
            ? ` (domyślnie ${Math.round(data.realization * 100)}% — faktury do potencjału w ${data.realization_months.join(", ")})`
            : ""}
          ; koszty prognozy i miesięcy, których faktury kosztowe jeszcze spływają = {data.cost_share !== null ? `${num(data.cost_share * 100, 1)}% sprzedaży` : "brak danych"} z 12 miesięcy kroczących.
        </p>
      </section>
      {editing ? <PlanDialog data={data} onClose={() => setEditing(false)} /> : null}
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "bad" | "warn";
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3.5 py-3">
      <div className="truncate text-[12px] font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-[22px] font-semibold leading-tight tabular-nums",
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

function Line({
  label,
  values,
  total,
  forecast,
  muted,
}: {
  label: string;
  values: (number | null)[];
  total: number | null;
  forecast?: boolean[];
  muted?: boolean;
}) {
  return (
    <tr className={cn(muted && "text-muted-foreground")}>
      <td className="sticky left-0 z-10 bg-card py-1.5 pr-2 text-left font-semibold">{label}</td>
      {values.map((v, i) => (
        <td key={i} className={cn("px-1.5 py-1.5 text-right", forecast?.[i] && "italic text-info")}>
          {num(v)}
        </td>
      ))}
      <td className="py-1.5 pl-2 text-right font-semibold">{num(total)}</td>
    </tr>
  );
}

// ── Plan (admin) ─────────────────────────────────────────────────────────────

const NO_RESOLUTION = "none";

function PlanDialog({ data, onClose }: { data: BudgetView; onClose: () => void }) {
  const { showToast } = useToast();
  const save = useSaveBoardBudget(data.year);
  const resolutions = useBoardDocuments("resolution_supervisory");
  const [status, setStatus] = React.useState<"draft" | "adopted">(data.budget?.status ?? "draft");
  const [resolution, setResolution] = React.useState<number | null>(data.budget?.resolution_document_id ?? null);
  const [cells, setCells] = React.useState(() =>
    data.months.map((m) => ({
      sales: m.plan_sales === null ? "" : String(m.plan_sales).replace(".", ","),
      costs: m.plan_costs === null ? "" : String(m.plan_costs).replace(".", ","),
    })),
  );
  const parse = (raw: string): number | null => {
    const value = Number(raw.replace(/\s/g, "").replace(",", "."));
    return raw.trim() === "" || !Number.isFinite(value) || value < 0 ? null : value;
  };
  const invalid = cells.some((c) => (c.sales.trim() && parse(c.sales) === null) || (c.costs.trim() && parse(c.costs) === null));

  const onSave = () =>
    save.mutate(
      {
        status,
        resolution_document_id: resolution,
        note: data.budget?.note ?? null,
        months: cells.map((c, i) => ({
          month: i + 1,
          sales: parse(c.sales) === null ? null : Math.round((parse(c.sales) as number) * 1_000_000),
          costs: parse(c.costs) === null ? null : Math.round((parse(c.costs) as number) * 1_000_000),
        })),
      },
      {
        onSuccess: () => {
          showToast("Zapisano plan.");
          onClose();
        },
        onError: (e) => showToast(apiErrorMessage(e, "Nie udało się zapisać planu."), "error"),
      },
    );

  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title={`Plan na ${data.year}`}
      description="Kwoty w mln zł netto (np. 9,85). Puste pole usuwa miesiąc z planu."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Anuluj
          </Button>
          <Button onClick={onSave} disabled={save.isPending || invalid}>
            Zapisz plan
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="board-budget-status">Status</Label>
          <Select value={status} onValueChange={(v) => setStatus(v as "draft" | "adopted")}>
            <SelectTrigger id="board-budget-status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="draft">Szkic</SelectItem>
              <SelectItem value="adopted">Przyjęty uchwałą Rady</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-budget-resolution">Uchwała Rady</Label>
          <Select
            value={resolution === null ? NO_RESOLUTION : String(resolution)}
            onValueChange={(v) => setResolution(v === NO_RESOLUTION ? null : Number(v))}
          >
            <SelectTrigger id="board-budget-resolution">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_RESOLUTION}>—</SelectItem>
              {(resolutions.data?.items ?? []).map((doc) => (
                <SelectItem key={doc.id} value={String(doc.id)}>
                  {doc.number ? `nr ${doc.number} · ` : ""}
                  {doc.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-[48px_1fr_1fr] items-center gap-x-2 gap-y-1.5 text-[12px]">
        <span />
        <span className="text-muted-foreground">Sprzedaż</span>
        <span className="text-muted-foreground">Koszty z faktur</span>
        {cells.map((c, i) => (
          <React.Fragment key={i}>
            <span className="font-medium">{ROMAN[i]}</span>
            <Input
              aria-label={`Sprzedaż ${ROMAN[i]}`}
              inputMode="decimal"
              value={c.sales}
              onChange={(e) => setCells((prev) => prev.map((p, j) => (j === i ? { ...p, sales: e.target.value } : p)))}
              className="h-8"
            />
            <Input
              aria-label={`Koszty ${ROMAN[i]}`}
              inputMode="decimal"
              value={c.costs}
              onChange={(e) => setCells((prev) => prev.map((p, j) => (j === i ? { ...p, costs: e.target.value } : p)))}
              className="h-8"
            />
          </React.Fragment>
        ))}
      </div>
    </AppModal>
  );
}
