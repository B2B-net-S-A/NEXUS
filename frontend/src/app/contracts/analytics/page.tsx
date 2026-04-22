"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import api, {
  contractAnalyticsExpansionApi,
  CONTRACT_TERMINATION_REASONS,
  type RoleClientMix,
  type LocationDistribution,
  type TerminationAnalysis,
} from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { RequireRole } from "@/components/RequireRole";
import {
  TrendingUp,
  Users,
  Building2,
  LineChart,
  ArrowLeft,
  Loader2,
  MapPin,
  AlertTriangle,
  Target,
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

        <RoleClientMixCard />
        <LocationDistributionCard />
        <TerminationAnalysisCard />
      </div>
    </RequireRole>
  );
}

// ── Role × Client heatmap ───────────────────────────────────────────────────


function RoleClientMixCard() {
  const { data, isLoading } = useQuery<RoleClientMix>({
    queryKey: ["contract-analytics-role-client-mix"],
    queryFn: async () =>
      (await contractAnalyticsExpansionApi.roleClientMix()).data,
  });

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin inline" /> Ładowanie rola × klient…
      </div>
    );
  }
  if (!data || data.rows.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 text-sm text-gray-500">
        <div className="flex items-center gap-2 mb-2">
          <Target className="w-4 h-4" />
          <h3 className="font-semibold">Rola × Klient</h3>
        </div>
        Brak aktywnych kontraktów do analizy.
      </div>
    );
  }

  // Build a matrix map: role → clientId → count.
  const matrix: Record<string, Record<number, number>> = {};
  for (const row of data.rows) {
    matrix[row.role] ??= {};
    matrix[row.role][row.client_id] = row.active_count;
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6">
      <div className="flex items-center gap-2 mb-3">
        <Target className="w-4 h-4" />
        <h3 className="font-semibold">Rola × Klient ({data.total_active} aktywnych)</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="text-left text-gray-500">
            <tr>
              <th className="px-2 py-1 sticky left-0 bg-white dark:bg-gray-800">Rola</th>
              {data.clients.map((c) => (
                <th key={c.id} className="px-2 py-1 whitespace-nowrap">
                  {c.name}
                </th>
              ))}
              <th className="px-2 py-1">Σ</th>
            </tr>
          </thead>
          <tbody>
            {data.roles.map((role) => {
              const rowSum = data.clients.reduce(
                (acc, c) => acc + (matrix[role]?.[c.id] ?? 0),
                0,
              );
              return (
                <tr
                  key={role}
                  className="border-t border-gray-100 dark:border-gray-700"
                >
                  <td className="px-2 py-1 font-medium sticky left-0 bg-white dark:bg-gray-800">
                    {role}
                  </td>
                  {data.clients.map((c) => {
                    const cnt = matrix[role]?.[c.id] ?? 0;
                    const intensity = rowSum
                      ? Math.min(1, cnt / rowSum)
                      : 0;
                    return (
                      <td
                        key={c.id}
                        className="px-2 py-1 text-center"
                        style={{
                          backgroundColor:
                            cnt > 0
                              ? `rgba(37, 99, 235, ${0.1 + intensity * 0.4})`
                              : undefined,
                        }}
                      >
                        {cnt || "·"}
                      </td>
                    );
                  })}
                  <td className="px-2 py-1 text-center font-medium">{rowSum}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Consultant location distribution ────────────────────────────────────────


function LocationDistributionCard() {
  const { data, isLoading } = useQuery<LocationDistribution>({
    queryKey: ["contract-analytics-location-distribution"],
    queryFn: async () =>
      (await contractAnalyticsExpansionApi.locationDistribution()).data,
  });

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin inline" /> Ładowanie lokalizacji…
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6">
      <div className="flex items-center gap-2 mb-3">
        <MapPin className="w-4 h-4 text-blue-500" />
        <h3 className="font-semibold">
          Lokalizacja konsultantów ({data.total_with_hub}/{data.total} z hubem)
        </h3>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <h4 className="text-xs font-semibold text-gray-500 mb-2">Huby</h4>
          <ul className="space-y-1 text-sm">
            {data.hubs.map((h) => (
              <li
                key={h.hub_city ?? "unknown"}
                className="flex items-center justify-between"
              >
                <span className="text-gray-700 dark:text-gray-200">
                  {h.hub_city ?? <em className="text-gray-400">Brak hubu</em>}
                </span>
                <span className="font-medium">{h.count}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold text-gray-500 mb-2">Regiony</h4>
          <ul className="space-y-1 text-sm">
            {data.regions.map((r) => (
              <li
                key={r.region ?? "unknown"}
                className="flex items-center justify-between"
              >
                <span className="text-gray-700 dark:text-gray-200">
                  {r.region ?? <em className="text-gray-400">Brak regionu</em>}
                </span>
                <span className="font-medium">{r.count}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ── Termination analysis ────────────────────────────────────────────────────


function TerminationAnalysisCard() {
  const { data, isLoading } = useQuery<TerminationAnalysis>({
    queryKey: ["contract-analytics-termination-analysis"],
    queryFn: async () =>
      (await contractAnalyticsExpansionApi.terminationAnalysis(12)).data,
  });

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin inline" /> Ładowanie analizy
        zakończeń…
      </div>
    );
  }
  if (!data) return null;

  const reasonLabel = (v: string) =>
    CONTRACT_TERMINATION_REASONS.find((r) => r.value === v)?.label ?? v;
  const maxCount = Math.max(1, ...data.by_reason.map((r) => r.count));

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-4 h-4 text-amber-500" />
        <h3 className="font-semibold">
          Analiza zakończeń ({data.total_terminated} w ostatnich{" "}
          {data.window_months} mies.)
        </h3>
      </div>

      {data.by_reason.length === 0 ? (
        <p className="text-sm text-gray-500">Brak zakończeń w oknie.</p>
      ) : (
        <>
          <h4 className="text-xs font-semibold text-gray-500 mt-2 mb-2">
            Powody
          </h4>
          <ul className="space-y-1 mb-5">
            {data.by_reason.map((r) => (
              <li key={r.reason} className="text-sm">
                <div className="flex justify-between text-xs text-gray-500">
                  <span>{reasonLabel(r.reason)}</span>
                  <span>
                    {r.count}
                    {r.avg_contract_days != null && (
                      <> · śr. {Math.round(r.avg_contract_days)} dni</>
                    )}
                  </span>
                </div>
                <div className="h-2 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-500"
                    style={{ width: `${(r.count / maxCount) * 100}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>

          <h4 className="text-xs font-semibold text-gray-500 mb-2">
            Retencja per klient
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-gray-500">
                <tr>
                  <th className="px-2 py-1">Klient</th>
                  <th className="px-2 py-1 text-right">Zakończone</th>
                  <th className="px-2 py-1 text-right">Do końca</th>
                  <th className="px-2 py-1 text-right">Przedwczesne</th>
                  <th className="px-2 py-1 text-right">Retencja</th>
                </tr>
              </thead>
              <tbody>
                {data.client_retention.map((c) => (
                  <tr
                    key={c.client_id}
                    className="border-t border-gray-100 dark:border-gray-700"
                  >
                    <td className="px-2 py-1">{c.client_name}</td>
                    <td className="px-2 py-1 text-right">{c.total_ended}</td>
                    <td className="px-2 py-1 text-right text-green-600">
                      {c.kept_to_end}
                    </td>
                    <td className="px-2 py-1 text-right text-red-600">
                      {c.ended_early}
                    </td>
                    <td className="px-2 py-1 text-right font-medium">
                      {c.retention_pct}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
