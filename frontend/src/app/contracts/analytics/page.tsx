"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { RequireRole } from "@/components/RequireRole";
import {
  TrendingUp,
  Users,
  Building2,
  LineChart,
  ArrowLeft,
  Loader2,
} from "lucide-react";

interface MarginRow {
  candidate_id?: number;
  candidate_name?: string;
  client_id?: number;
  client_name?: string;
  active_contracts: number;
  total_monthly_margin: number;
  total_monthly_revenue: number;
  margin_pct: number | null;
}

interface UtilizationData {
  total_candidates: number;
  candidates_active: number;
  candidates_on_bench: number;
  utilization_pct: number;
  avg_bench_days: number | null;
}

interface ForecastMonth {
  month: string;
  month_label: string;
  revenue: number;
  margin: number;
  active_count: number;
}

interface Forecast {
  horizon_months: number;
  months: ForecastMonth[];
}

function MetricCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-5">
      <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-bold">{value}</div>
      {sub && (
        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">{sub}</div>
      )}
    </div>
  );
}

function MarginLeaderboard({
  title,
  rows,
  isLoading,
  nameKey,
  linkPrefix,
}: {
  title: string;
  rows: MarginRow[] | undefined;
  isLoading: boolean;
  nameKey: "candidate_name" | "client_name";
  linkPrefix: string;
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden">
      <h2 className="px-4 py-3 text-sm font-semibold border-b border-gray-100 dark:border-gray-700">
        {title}
      </h2>
      {isLoading ? (
        <div className="p-6 text-sm text-gray-500 flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie…
        </div>
      ) : !rows || rows.length === 0 ? (
        <div className="p-6 text-sm text-gray-500 italic">Brak danych.</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-700/40 text-xs uppercase text-gray-500 dark:text-gray-400">
            <tr>
              <th className="text-left px-3 py-2">#</th>
              <th className="text-left px-3 py-2">
                {nameKey === "candidate_name" ? "Kontraktor" : "Klient"}
              </th>
              <th className="text-right px-3 py-2">Aktywne</th>
              <th className="text-right px-3 py-2">Przychód / mies.</th>
              <th className="text-right px-3 py-2">Marża / mies.</th>
              <th className="text-right px-3 py-2">Marża %</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const linkId = (r.candidate_id ?? r.client_id) as number;
              const name = (r[nameKey] ?? "—") as string;
              return (
                <tr key={linkId} className="border-t border-gray-100 dark:border-gray-700">
                  <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                  <td className="px-3 py-2">
                    <Link
                      href={`${linkPrefix}${linkId}`}
                      className="text-blue-600 hover:underline dark:text-blue-400"
                    >
                      {name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-right">{r.active_contracts}</td>
                  <td className="px-3 py-2 text-right">
                    {formatCurrency(r.total_monthly_revenue, "PLN")}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold text-emerald-600">
                    {formatCurrency(r.total_monthly_margin, "PLN")}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500 dark:text-gray-400">
                    {r.margin_pct !== null ? `${r.margin_pct}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ForecastChart({ forecast }: { forecast: Forecast | undefined }) {
  if (!forecast || forecast.months.length === 0) {
    return (
      <div className="p-6 text-sm text-gray-500 italic">Brak danych prognozy.</div>
    );
  }
  const maxRev = Math.max(...forecast.months.map((m) => m.revenue), 1);
  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-4 overflow-x-auto">
      <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
        <LineChart className="w-4 h-4" /> Prognoza przychodu i marży (12 mies.)
      </h2>
      <div className="flex items-end gap-2 h-60 min-w-fit">
        {forecast.months.map((m) => {
          const revHeight = (m.revenue / maxRev) * 100;
          const marHeight = m.revenue
            ? (m.margin / maxRev) * 100
            : 0;
          return (
            <div key={m.month} className="flex flex-col items-center gap-1 min-w-16">
              <div className="text-[10px] text-gray-400 mb-1">{m.active_count} cnt</div>
              <div className="relative w-full h-48 bg-gray-50 dark:bg-gray-900/30 rounded-t">
                <div
                  className="absolute bottom-0 left-0 right-0 bg-blue-200 dark:bg-blue-900/40 rounded-t"
                  style={{ height: `${revHeight}%` }}
                  title={`Przychód: ${formatCurrency(m.revenue, "PLN")}`}
                />
                <div
                  className="absolute bottom-0 left-0 right-0 bg-emerald-500 rounded-t"
                  style={{ height: `${marHeight}%` }}
                  title={`Marża: ${formatCurrency(m.margin, "PLN")}`}
                />
              </div>
              <div className="text-[11px] text-gray-500 whitespace-nowrap">
                {m.month_label}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 bg-blue-200 dark:bg-blue-900/40 rounded" />
          Przychód
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 bg-emerald-500 rounded" />
          Marża
        </span>
      </div>
    </div>
  );
}

export default function ContractAnalyticsPage() {
  const { data: byContractor, isLoading: l1 } = useQuery<MarginRow[]>({
    queryKey: ["contract-analytics-margin-contractor"],
    queryFn: () =>
      api.get("/api/contract-analytics/margin-by-contractor").then((r) => r.data),
  });
  const { data: byClient, isLoading: l2 } = useQuery<MarginRow[]>({
    queryKey: ["contract-analytics-margin-client"],
    queryFn: () =>
      api.get("/api/contract-analytics/margin-by-client").then((r) => r.data),
  });
  const { data: util } = useQuery<UtilizationData>({
    queryKey: ["contract-analytics-utilization"],
    queryFn: () =>
      api.get("/api/contract-analytics/utilization").then((r) => r.data),
  });
  const { data: forecast } = useQuery<Forecast>({
    queryKey: ["contract-analytics-forecast"],
    queryFn: () =>
      api
        .get("/api/contract-analytics/revenue-forecast")
        .then((r) => r.data),
  });

  const totalMonthlyMargin = (byClient ?? []).reduce(
    (acc, r) => acc + r.total_monthly_margin,
    0,
  );
  const totalMonthlyRevenue = (byClient ?? []).reduce(
    (acc, r) => acc + r.total_monthly_revenue,
    0,
  );

  return (
    <RequireRole roles={["admin", "delivery_lead"]}>
      <div className="space-y-6">
        <div>
          <Link
            href="/contracts"
            className="inline-flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Kontrakty
          </Link>
          <h1 className="text-2xl font-bold mt-1">Analityka kontraktów</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Marża, utylizacja i prognoza dla aktywnych kontraktów.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard
            icon={TrendingUp}
            label="Miesięczna marża"
            value={formatCurrency(totalMonthlyMargin, "PLN")}
            sub={
              totalMonthlyRevenue
                ? `${((totalMonthlyMargin / totalMonthlyRevenue) * 100).toFixed(1)}% z przychodu`
                : undefined
            }
          />
          <MetricCard
            icon={LineChart}
            label="Miesięczny przychód"
            value={formatCurrency(totalMonthlyRevenue, "PLN")}
          />
          <MetricCard
            icon={Users}
            label="Utylizacja"
            value={util ? `${util.utilization_pct}%` : "—"}
            sub={
              util
                ? `${util.candidates_active}/${util.total_candidates} kandydatów aktywnych`
                : undefined
            }
          />
          <MetricCard
            icon={Building2}
            label="Śr. dni na bench"
            value={util?.avg_bench_days !== null && util?.avg_bench_days !== undefined ? `${util.avg_bench_days}` : "—"}
            sub={util ? `${util.candidates_on_bench} kandydatów bez kontraktu` : undefined}
          />
        </div>

        <ForecastChart forecast={forecast} />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <MarginLeaderboard
            title="Top kontraktorzy wg marży"
            rows={byContractor}
            isLoading={l1}
            nameKey="candidate_name"
            linkPrefix="/candidates/"
          />
          <MarginLeaderboard
            title="Top klienci wg marży"
            rows={byClient}
            isLoading={l2}
            nameKey="client_name"
            linkPrefix="/clients/"
          />
        </div>
      </div>
    </RequireRole>
  );
}
