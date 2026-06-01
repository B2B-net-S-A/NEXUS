"use client";

/**
 * DynaReporter Rada Nadzorcza (Board) dashboard – full 1:1 port z
 * artur-t-96/InfraReporter `client/src/pages/Board.tsx`.
 *
 * Sekcje:
 * 1. Finanse – 4 YoY tabele (Revenue/Koszty kons./Marża/Zysk) + 2 charts
 * 2. HR – 3 YoY tabele (Konsultanci/Odejścia/Placementy) + 3 charts
 * 3. Dywersyfikacja – 2 YoY tabele + PlacementClientsTable + YearlyClientRanking
 * 4. Wskaźniki operacyjne – 2 YoY tabele (Margin/h, Hit Ratio) + 2 charts
 *
 * Każda YoY tabela ma:
 * - 12 miesięcy × 3 lata (2024/2025/2026) z kolorami per rok
 * - Δ 24→25 i Δ 25→26 (color coded green/red)
 * - Ocena column (Lepiej/Gorzej/=)
 * - Tfoot Suma/Średnia row
 *
 * Uprawnienia: admin / delivery_lead / head_of_recruitment (financials).
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import {
  Shield,
  DollarSign,
  Users,
  Target,
  TrendingUp,
  Briefcase,
  RefreshCw,
} from "lucide-react";
import { dynareporterBoardApi, type DrBoardMonthlyRow } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

const MONTH_NAMES = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
];

const YEARS = [2024, 2025, 2026] as const;
type Year = (typeof YEARS)[number];
const YEAR_COLORS: Record<Year, string> = {
  2024: "#6B7280",
  2025: "#3B82F6",
  2026: "#10B981",
};

function formatPLN(value: number | undefined): string {
  if (value === undefined || value === null) return "–";
  return value.toLocaleString("pl-PL") + " zł";
}

function formatNumber(value: number | undefined): string {
  if (value === undefined || value === null) return "–";
  return value.toLocaleString("pl-PL");
}

function formatPercent(value: number | undefined): string {
  if (value === undefined || value === null) return "–";
  return value.toFixed(1) + "%";
}

function formatMarginPerHour(value: number | undefined): string {
  if (value === undefined || value === null) return "–";
  return `${value.toFixed(2)} zł/h`;
}

type DataByYearMonth = Record<number, Record<number, DrBoardMonthlyRow>>;

function groupByYearMonth(data: DrBoardMonthlyRow[]): DataByYearMonth {
  const result: DataByYearMonth = {};
  for (const year of YEARS) result[year] = {};
  for (const row of data) {
    const [yearStr, monthStr] = row.report_month.split("-");
    const year = parseInt(yearStr);
    const month = parseInt(monthStr);
    if ((YEARS as readonly number[]).includes(year)) {
      result[year][month] = row;
    }
  }
  return result;
}

function calcDelta(
  current: number | undefined,
  previous: number | undefined,
): number | undefined {
  if (current === undefined || previous === undefined || previous === 0)
    return undefined;
  return ((current - previous) / Math.abs(previous)) * 100;
}

function DeltaCell({
  delta,
  lowerIsBetter,
}: {
  delta: number | undefined;
  lowerIsBetter: boolean;
}) {
  if (delta === undefined)
    return (
      <td className="px-3 py-2 text-right text-gray-400 text-xs">–</td>
    );
  const isPositive = delta >= 0;
  const isGood = lowerIsBetter ? !isPositive : isPositive;
  return (
    <td
      className={`px-3 py-2 text-right text-xs font-semibold tabular-nums ${
        isGood
          ? "text-green-600 dark:text-green-400"
          : "text-red-600 dark:text-red-400"
      }`}
    >
      {isPositive ? "+" : ""}
      {delta.toFixed(1)}%
    </td>
  );
}

function RatingCell({
  delta1,
  delta2,
  lowerIsBetter,
}: {
  delta1: number | undefined;
  delta2: number | undefined;
  lowerIsBetter: boolean;
}) {
  if (delta1 === undefined || delta2 === undefined)
    return (
      <td className="px-3 py-2 text-center text-gray-400 text-xs">–</td>
    );
  const newBetter = lowerIsBetter ? delta2 < delta1 : delta2 > delta1;
  const equal = Math.abs(delta2 - delta1) < 0.05;
  if (equal)
    return (
      <td className="px-3 py-2 text-center text-xs text-gray-500">=</td>
    );
  return (
    <td
      className={`px-3 py-2 text-center text-xs font-bold ${
        newBetter
          ? "text-green-600 dark:text-green-400"
          : "text-red-600 dark:text-red-400"
      }`}
    >
      {newBetter ? "Lepiej" : "Gorzej"}
    </td>
  );
}

interface YoYTableProps {
  title: string;
  grouped: DataByYearMonth;
  getValue: (row: DrBoardMonthlyRow) => number | undefined;
  formatter: (v: number | undefined) => string;
  lowerIsBetter?: boolean;
  getCellTooltip?: (row: DrBoardMonthlyRow) => string;
}

function YoYTable({
  title,
  grouped,
  getValue,
  formatter,
  lowerIsBetter = false,
  getCellTooltip,
}: YoYTableProps) {
  const isAvgMetric =
    title.includes("marż") || title.includes("Hit") || title.includes("Marża");

  function getYearTotal(year: Year): number | undefined {
    const values = Object.values(grouped[year] || {})
      .map((r) => getValue(r))
      .filter((v): v is number => v !== undefined && v !== 0);
    if (values.length === 0) return undefined;
    return isAvgMetric
      ? values.reduce((a, b) => a + b, 0) / values.length
      : values.reduce((a, b) => a + b, 0);
  }

  const totals: Record<Year, number | undefined> = {
    2024: getYearTotal(2024),
    2025: getYearTotal(2025),
    2026: getYearTotal(2026),
  };
  const totalDelta1 = calcDelta(totals[2025], totals[2024]);
  const totalDelta2 = calcDelta(totals[2026], totals[2025]);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-600">
        <h4 className="font-semibold text-sm text-gray-800 dark:text-gray-200">
          {title}
        </h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-700">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Miesiąc
              </th>
              <th
                className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wider"
                style={{ color: YEAR_COLORS[2024] }}
              >
                2024
              </th>
              <th
                className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wider"
                style={{ color: YEAR_COLORS[2025] }}
              >
                2025
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                Δ 24→25
              </th>
              <th
                className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wider"
                style={{ color: YEAR_COLORS[2026] }}
              >
                2026
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                Δ 25→26
              </th>
              <th className="px-3 py-2.5 text-center text-xs font-medium text-gray-400 uppercase tracking-wider">
                Ocena
              </th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => {
              const val2024 = grouped[2024]?.[month]
                ? getValue(grouped[2024][month])
                : undefined;
              const val2025 = grouped[2025]?.[month]
                ? getValue(grouped[2025][month])
                : undefined;
              const val2026 = grouped[2026]?.[month]
                ? getValue(grouped[2026][month])
                : undefined;
              const hasVal = (v: number | undefined) =>
                v !== undefined && v !== 0;
              const delta1 =
                hasVal(val2024) && hasVal(val2025)
                  ? calcDelta(val2025, val2024)
                  : undefined;
              const delta2 =
                hasVal(val2025) && hasVal(val2026)
                  ? calcDelta(val2026, val2025)
                  : undefined;

              const tip2024 =
                getCellTooltip && grouped[2024]?.[month]
                  ? getCellTooltip(grouped[2024][month])
                  : "";
              const tip2025 =
                getCellTooltip && grouped[2025]?.[month]
                  ? getCellTooltip(grouped[2025][month])
                  : "";
              const tip2026 =
                getCellTooltip && grouped[2026]?.[month]
                  ? getCellTooltip(grouped[2026][month])
                  : "";

              return (
                <tr
                  key={month}
                  className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                >
                  <td className="px-4 py-2 text-gray-700 dark:text-gray-300 font-medium">
                    {MONTH_NAMES[month - 1]}
                  </td>
                  <td
                    className="px-4 py-2 text-right text-gray-600 dark:text-gray-400 tabular-nums"
                    title={tip2024}
                  >
                    {hasVal(val2024) ? formatter(val2024) : "–"}
                  </td>
                  <td
                    className="px-4 py-2 text-right text-gray-600 dark:text-gray-400 tabular-nums"
                    title={tip2025}
                  >
                    {hasVal(val2025) ? formatter(val2025) : "–"}
                  </td>
                  <DeltaCell delta={delta1} lowerIsBetter={lowerIsBetter} />
                  <td
                    className="px-4 py-2 text-right text-gray-600 dark:text-gray-400 tabular-nums"
                    title={tip2026}
                  >
                    {hasVal(val2026) ? formatter(val2026) : "–"}
                  </td>
                  <DeltaCell delta={delta2} lowerIsBetter={lowerIsBetter} />
                  <RatingCell
                    delta1={delta1}
                    delta2={delta2}
                    lowerIsBetter={lowerIsBetter}
                  />
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="bg-gray-50 dark:bg-gray-700/30 font-semibold">
              <td className="px-4 py-2.5 text-gray-800 dark:text-gray-200">
                Suma / Średnia
              </td>
              <td className="px-4 py-2.5 text-right text-gray-800 dark:text-gray-200 tabular-nums">
                {totals[2024] !== undefined ? formatter(totals[2024]) : "–"}
              </td>
              <td className="px-4 py-2.5 text-right text-gray-800 dark:text-gray-200 tabular-nums">
                {totals[2025] !== undefined ? formatter(totals[2025]) : "–"}
              </td>
              <DeltaCell delta={totalDelta1} lowerIsBetter={lowerIsBetter} />
              <td className="px-4 py-2.5 text-right text-gray-800 dark:text-gray-200 tabular-nums">
                {totals[2026] !== undefined ? formatter(totals[2026]) : "–"}
              </td>
              <DeltaCell delta={totalDelta2} lowerIsBetter={lowerIsBetter} />
              <RatingCell
                delta1={totalDelta1}
                delta2={totalDelta2}
                lowerIsBetter={lowerIsBetter}
              />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

interface YoYChartProps {
  title: string;
  grouped: DataByYearMonth;
  getValue: (row: DrBoardMonthlyRow) => number;
  unit?: string;
}

function YoYChart({ title, grouped, getValue, unit = "" }: YoYChartProps) {
  const chartData = useMemo(() => {
    return Array.from({ length: 12 }, (_, i) => {
      const month = i + 1;
      const point: Record<string, string | number | null> = {
        month: MONTH_NAMES[i].slice(0, 3),
      };
      for (const year of YEARS) {
        const row = grouped[year]?.[month];
        point[String(year)] = row ? getValue(row) || null : null;
      }
      return point;
    });
  }, [grouped, getValue]);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
      <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
        <TrendingUp className="w-4 h-4" />
        {title}
      </h4>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" className="dark:stroke-gray-600" />
            <XAxis
              dataKey="month"
              className="text-xs"
              tick={{ fontSize: 11 }}
            />
            <YAxis
              className="text-xs"
              tick={{ fontSize: 11 }}
              tickFormatter={(v) =>
                unit === "zł" ? `${(v / 1000).toFixed(0)}k` : String(v)
              }
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "rgba(17, 24, 39, 0.95)",
                border: "none",
                borderRadius: "8px",
                color: "#fff",
                fontSize: "12px",
              }}
              formatter={((value: number, name: string) => {
                if (value === undefined || value === null) return ["–", name];
                if (unit === "zł")
                  return [`${value.toLocaleString("pl-PL")} zł`, name];
                if (unit === "%") return [`${value.toFixed(1)}%`, name];
                return [value.toLocaleString("pl-PL"), name];
              }) as never}
            />
            <Legend />
            {YEARS.map((year) => (
              <Line
                key={year}
                type="monotone"
                dataKey={String(year)}
                name={String(year)}
                stroke={YEAR_COLORS[year]}
                strokeWidth={2}
                dot={{ fill: YEAR_COLORS[year], r: 3 }}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PlacementClientsTable({ grouped }: { grouped: DataByYearMonth }) {
  function formatClients(row: DrBoardMonthlyRow | undefined): string {
    if (!row?.placement_clients?.length) return "–";
    return row.placement_clients
      .slice()
      .sort((a, b) => b.count - a.count)
      .map((c) => `${c.client_name} (${c.count})`)
      .join(", ");
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-600">
        <h4 className="font-semibold text-sm text-gray-800 dark:text-gray-200">
          Rozbicie placementów na klientów
        </h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-700">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-28">
                Miesiąc
              </th>
              {YEARS.map((year) => (
                <th
                  key={year}
                  className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider"
                  style={{ color: YEAR_COLORS[year] }}
                >
                  {year}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => (
              <tr
                key={month}
                className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
              >
                <td className="px-4 py-2 text-gray-700 dark:text-gray-300 font-medium">
                  {MONTH_NAMES[month - 1]}
                </td>
                {YEARS.map((year) => (
                  <td
                    key={year}
                    className="px-4 py-2 text-gray-600 dark:text-gray-400 text-xs"
                  >
                    {formatClients(grouped[year]?.[month])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-gray-50 dark:bg-gray-700/30 font-semibold">
              <td className="px-4 py-2.5 text-gray-800 dark:text-gray-200 text-xs uppercase">
                Suma / rok
              </td>
              {YEARS.map((year) => {
                const map: Record<string, number> = {};
                let total = 0;
                for (const month of Object.values(grouped[year] || {})) {
                  total += month.placements || 0;
                  for (const c of month.placement_clients || []) {
                    map[c.client_name] = (map[c.client_name] || 0) + c.count;
                  }
                }
                const sorted = Object.entries(map).sort((a, b) => b[1] - a[1]);
                const summary =
                  sorted.length > 0
                    ? `${total} – ${sorted
                        .map(([name, cnt]) => `${name} (${cnt})`)
                        .join(", ")}`
                    : total > 0
                      ? String(total)
                      : "–";
                return (
                  <td
                    key={year}
                    className="px-4 py-2.5 text-xs text-gray-800 dark:text-gray-200"
                  >
                    {summary}
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function YearlyClientRanking({ grouped }: { grouped: DataByYearMonth }) {
  function getYearClients(
    year: Year,
  ): { clientName: string; total: number }[] {
    const map: Record<string, number> = {};
    for (const month of Object.values(grouped[year] || {})) {
      for (const c of month.placement_clients || []) {
        map[c.client_name] = (map[c.client_name] || 0) + c.count;
      }
    }
    return Object.entries(map)
      .map(([clientName, total]) => ({ clientName, total }))
      .sort((a, b) => b.total - a.total);
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      {YEARS.map((year) => {
        const clients = getYearClients(year);
        const grandTotal = clients.reduce((s, c) => s + c.total, 0);
        const maxCount = clients.length > 0 ? clients[0].total : 1;

        return (
          <div
            key={year}
            className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden"
          >
            <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-600 flex items-center justify-between">
              <h4
                className="font-semibold text-sm"
                style={{ color: YEAR_COLORS[year] }}
              >
                {year}
              </h4>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {clients.length}{" "}
                {clients.length === 1
                  ? "klient"
                  : clients.length < 5
                    ? "klientów"
                    : "klientów"}
              </span>
            </div>
            <div className="p-4">
              {clients.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-4">
                  Brak danych
                </p>
              ) : (
                <div className="space-y-2.5">
                  {clients.map((c) => (
                    <div key={c.clientName}>
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="font-medium text-gray-700 dark:text-gray-300 truncate mr-2">
                          {c.clientName}
                        </span>
                        <span className="text-gray-500 dark:text-gray-400 tabular-nums whitespace-nowrap">
                          {c.total} (
                          {grandTotal > 0
                            ? ((c.total / grandTotal) * 100).toFixed(0)
                            : 0}
                          %)
                        </span>
                      </div>
                      <div className="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-2">
                        <div
                          className="h-2 rounded-full transition-all"
                          style={{
                            width: `${(c.total / maxCount) * 100}%`,
                            backgroundColor: YEAR_COLORS[year],
                          }}
                        />
                      </div>
                    </div>
                  ))}
                  <div className="pt-2 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 text-right tabular-nums">
                    Razem: {grandTotal}
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function BoardDashboardPage() {
  const { user, hydrated } = useAuthStore();
  const queryEnabled = hydrated && !!user;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["dr-board-monthly"],
    queryFn: () => dynareporterBoardApi.monthly(),
    staleTime: 5 * 60_000,
    enabled: queryEnabled,
  });

  const grouped = useMemo(() => groupByYearMonth(data ?? []), [data]);

  if (!hydrated) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Ładowanie sesji…</div>
    );
  }
  if (!user) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Zaloguj się żeby zobaczyć Radę Nadzorczą.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Ładowanie danych…</div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-xl p-4">
          <h3 className="font-semibold text-red-700 dark:text-red-300">
            Błąd ładowania danych
          </h3>
          <p className="text-sm text-red-600 dark:text-red-400 mt-1">
            {String(error)}
          </p>
          <button
            onClick={() => refetch()}
            className="mt-3 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700"
          >
            Spróbuj ponownie
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 sm:p-6">
      {/* Nagłówek */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Shield className="w-6 h-6 text-indigo-600" />
            Rada Nadzorcza – Przegląd 2024–2026
          </h2>
          <button
            onClick={() => refetch()}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors text-sm"
            aria-label="Odśwież dane"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
            <span>Odśwież</span>
          </button>
        </div>
      </div>

      {/* SEKCJA: FINANSE */}
      <section>
        <div className="flex items-center gap-2 mb-3 px-1">
          <DollarSign className="w-5 h-5 text-emerald-600" />
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">
            Finanse
          </h3>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <YoYTable
            title="Przychody"
            grouped={grouped}
            getValue={(r) => r.revenue}
            formatter={formatPLN}
          />
          <YoYTable
            title="Koszty konsultantów"
            grouped={grouped}
            getValue={(r) => r.consultant_costs}
            formatter={formatPLN}
            lowerIsBetter
          />
          <YoYTable
            title="Marża (przychody − koszty kons.)"
            grouped={grouped}
            getValue={(r) => r.margin}
            formatter={formatPLN}
          />
          <YoYTable
            title="Zysk (marża − pozostałe koszty)"
            grouped={grouped}
            getValue={(r) => r.profit}
            formatter={formatPLN}
          />
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mt-4">
          <YoYChart
            title="Przychody – trend"
            grouped={grouped}
            getValue={(r) => r.revenue}
            unit="zł"
          />
          <YoYChart
            title="Zysk – trend"
            grouped={grouped}
            getValue={(r) => r.profit}
            unit="zł"
          />
        </div>
      </section>

      {/* SEKCJA: HR */}
      <section>
        <div className="flex items-center gap-2 mb-3 px-1">
          <Users className="w-5 h-5 text-blue-600" />
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">HR</h3>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <YoYTable
            title="Liczba konsultantów"
            grouped={grouped}
            getValue={(r) => r.active_consultants}
            formatter={formatNumber}
          />
          <YoYTable
            title="Liczba zejść"
            grouped={grouped}
            getValue={(r) => r.departures}
            formatter={formatNumber}
            lowerIsBetter
          />
          <YoYTable
            title="Liczba placementów"
            grouped={grouped}
            getValue={(r) => r.placements}
            formatter={formatNumber}
            getCellTooltip={(r) =>
              r.placement_clients?.length
                ? r.placement_clients
                    .map((c) => `${c.client_name} (${c.count})`)
                    .join(", ")
                : ""
            }
          />
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mt-4">
          <YoYChart
            title="Konsultanci – trend"
            grouped={grouped}
            getValue={(r) => r.active_consultants}
          />
          <YoYChart
            title="Zejścia – trend"
            grouped={grouped}
            getValue={(r) => r.departures}
          />
          <YoYChart
            title="Placementy – trend"
            grouped={grouped}
            getValue={(r) => r.placements}
          />
        </div>
      </section>

      {/* SEKCJA: DYWERSYFIKACJA PLACEMENTÓW */}
      <section>
        <div className="flex items-center gap-2 mb-3 px-1">
          <Briefcase className="w-5 h-5 text-purple-600" />
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">
            Dywersyfikacja placementów
          </h3>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <YoYTable
            title="Liczba unikalnych klientów"
            grouped={grouped}
            getValue={(r) => r.placement_clients?.length || 0}
            formatter={formatNumber}
          />
          <YoYTable
            title="Udział top klienta (%)"
            grouped={grouped}
            getValue={(r) => {
              if (!r.placement_clients?.length || r.placements === 0)
                return undefined;
              const max = Math.max(...r.placement_clients.map((c) => c.count));
              return (max / r.placements) * 100;
            }}
            formatter={formatPercent}
            lowerIsBetter
          />
        </div>
        <div className="mt-4">
          <PlacementClientsTable grouped={grouped} />
        </div>
        <div className="mt-4">
          <YearlyClientRanking grouped={grouped} />
        </div>
        <div className="grid grid-cols-1 gap-4 mt-4">
          <YoYChart
            title="Unikalni klienci – trend"
            grouped={grouped}
            getValue={(r) => r.placement_clients?.length || 0}
          />
        </div>
      </section>

      {/* SEKCJA: WSKAŹNIKI OPERACYJNE */}
      <section>
        <div className="flex items-center gap-2 mb-3 px-1">
          <Target className="w-5 h-5 text-amber-600" />
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">
            Wskaźniki operacyjne
          </h3>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <YoYTable
            title="Średnia marża na konsultancie (PLN/h)"
            grouped={grouped}
            getValue={(r) => r.avg_margin_per_hour}
            formatter={formatMarginPerHour}
          />
          <YoYTable
            title="Hit ratio (%)"
            grouped={grouped}
            getValue={(r) => r.hit_ratio}
            formatter={formatPercent}
          />
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mt-4">
          <YoYChart
            title="Marża PLN/h – trend"
            grouped={grouped}
            getValue={(r) => r.avg_margin_per_hour}
            unit="zł"
          />
          <YoYChart
            title="Hit ratio – trend"
            grouped={grouped}
            getValue={(r) => r.hit_ratio}
            unit="%"
          />
        </div>
      </section>
    </div>
  );
}
