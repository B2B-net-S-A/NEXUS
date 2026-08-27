"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Award, DollarSign, FileText, TrendingUp, Users } from "lucide-react";
import { reportsApi } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { formatPLN, KpiCard, HorizontalBar, DonutChart, LoadingSpinner } from "./_shared";

const RATE_UNIT_SUFFIX = {
  hourly: "/h",
  daily: "/dzień",
  monthly: "/mies.",
} as const;

interface SalesData {
  total_revenue: number;
  total_margin: number;
  active_consultants: number;
  active_contracts: number;
  new_contracts_this_month: number;
  mrr_trend: Array<{
    month: string;
    month_label: string;
    revenue: number;
    margin: number;
    consultants: number;
    active_contracts: number;
  }>;
  ending_contracts_30days: Array<{
    contract_id: number;
    client_name: string;
    end_date: string;
    rate_client: number | null;
    rate_client_currency: string;
    rate_unit: keyof typeof RATE_UNIT_SUFFIX;
  }>;
  top_clients: Array<{
    client_id: number;
    client_name: string;
    contracts_count: number;
    revenue: number;
    margin: number;
  }>;
  finance_quality?: "complete" | "unavailable";
  finance_warnings?: string[];
}

export function SalesOverview() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["insights-sales"],
    queryFn: () => reportsApi.sales().then((r) => r.data as SalesData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error)
    return <div className="text-sm text-destructive py-4">Błąd ładowania danych sales.</div>;
  if (!data) return null;

  const financeUnavailable = data.finance_quality === "unavailable";
  const financeWarnings = data.finance_warnings ?? [];
  const marginPct =
    financeUnavailable
      ? null
      : data.total_revenue > 0
        ? Math.round((data.total_margin / data.total_revenue) * 100)
        : 0;
  const maxRevenue = Math.max(...data.top_clients.map((c) => c.revenue), 1);
  const mrrValues = (data.mrr_trend || []).map((t) => t.revenue);

  const structureDonut = [
    { label: "Aktywne kontrakty", value: data.active_contracts, color: "#22c55e" },
    { label: "Kończące się (30d)", value: data.ending_contracts_30days.length, color: "#f97316" },
    { label: "Nowe (ten miesiąc)", value: data.new_contracts_this_month, color: "#3b82f6" },
  ];

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <DollarSign className="w-5 h-5 text-green-600" />
        Sprzedaż — przegląd
      </h2>

      {financeUnavailable &&
        (financeWarnings.length > 0
          ? financeWarnings.map((warning) => (
              <div
                key={warning}
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{warning}</span>
              </div>
            ))
          : (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>Dane finansowe są niepełne.</span>
              </div>
            ))}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Przychód MRR" value={formatPLN(data.total_revenue)} icon={DollarSign} color="green" trend="up" />
        <KpiCard
          label="Marża MRR"
          value={formatPLN(data.total_margin)}
          sub={marginPct === null ? "Marża % niedostępna" : `${marginPct}% marży`}
          icon={TrendingUp}
          color="blue"
        />
        <KpiCard
          label="Aktywni konsultanci"
          value={data.active_consultants}
          sub={`${data.active_contracts} aktywnych kontraktów`}
          icon={Users}
          color="purple"
        />
        <KpiCard
          label="Nowe kontrakty"
          value={data.new_contracts_this_month}
          sub="W tym miesiącu"
          icon={FileText}
          color="indigo"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-card rounded-xl border border-border p-6 shadow-xs">
          <h3 className="text-sm font-semibold text-foreground mb-4">Struktura kontraktów</h3>
          <DonutChart segments={structureDonut} />
        </div>

        <div className="bg-card rounded-xl border border-border p-6 shadow-xs">
          <h3 className="text-sm font-semibold text-foreground mb-1">Trend MRR (12 miesięcy)</h3>
          {mrrValues.length > 0 ? (
            <>
              <div className="flex items-end gap-0.5 h-24 mt-3">
                {mrrValues.map((v, i) => {
                  const max = Math.max(...mrrValues, 1);
                  return (
                    <div
                      key={i}
                      className="flex-1 bg-primary rounded-t opacity-80 hover:opacity-100 transition-opacity"
                      style={{ height: `${(v / max) * 100}%` }}
                      title={formatPLN(v)}
                    />
                  );
                })}
              </div>
              <div className="flex gap-0.5 mt-1">
                {(data.mrr_trend || []).map((t, i) => (
                  <div key={i} className="flex-1 text-center">
                    <span className="text-[8px] text-muted-foreground">{t.month_label.slice(0, 3)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="text-sm text-muted-foreground text-center py-8">Brak danych trendu</div>
          )}
        </div>
      </div>

      {data.top_clients.length > 0 && (
        <div className="bg-card rounded-xl border border-border p-6 shadow-xs">
          <div className="flex items-center gap-2 mb-5">
            <Award className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">Przychód wg klienta (MRR)</h3>
          </div>
          <div className="space-y-3">
            {data.top_clients.map((c, i) => {
              const colors = ["bg-primary", "bg-indigo-500", "bg-purple-500", "bg-primary/40", "bg-cyan-500"];
              return (
                <HorizontalBar
                  key={c.client_id}
                  label={c.client_name}
                  value={c.revenue}
                  max={maxRevenue}
                  color={colors[i % colors.length]}
                />
              );
            })}
          </div>
        </div>
      )}

      {data.ending_contracts_30days.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-5 h-5 text-amber-600" />
            <span className="font-semibold text-amber-800 dark:text-amber-400">
              {data.ending_contracts_30days.length} kontrakt
              {data.ending_contracts_30days.length > 1 ? "y" : ""} kończ
              {data.ending_contracts_30days.length > 1 ? "ą" : "y"} się w ciągu 30 dni
            </span>
          </div>
          <div className="space-y-2">
            {data.ending_contracts_30days.map((c) => (
              <div
                key={c.contract_id}
                className="flex items-center justify-between bg-card rounded-lg px-4 py-2.5 text-sm"
              >
                <span className="font-medium text-foreground">{c.client_name}</span>
                <div className="flex items-center gap-4">
                  <span className="text-muted-foreground">{c.end_date}</span>
                  <span className="font-semibold text-foreground">
                    {c.rate_client != null
                      ? `${formatCurrency(c.rate_client, c.rate_client_currency)}${RATE_UNIT_SUFFIX[c.rate_unit]}`
                      : "—"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
