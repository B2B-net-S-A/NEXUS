"use client";

/**
 * DynaReporter Rekrutacja mega-dashboard.
 *
 * Port `/rekrutacja` z oryginalnego DR (artur-t-96/InfraReporter,
 * `client/src/pages/Rekrutacja.tsx`). Zawiera:
 * - Period picker (Tydzień / Miesiąc / Rok)
 * - KPI cards: Weryfikacje / Rekomendacje / Interviews / Placements
 * - Efektywność lejka: 4 konwersje (Wer→Rek, Rek→Int, Int→Plac, Overall)
 * - Performance per osoba — tabela team
 * - Liga Mistrzów — podium top-3 + ranking
 *
 * Uprawnienia: każdy zalogowany user (widok team-wide).
 */

import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import {
  Users,
  Target,
  Calendar,
  RefreshCw,
  Trophy,
  Award,
  Download,
  Medal,
  Phone,
  Linkedin,
  BarChart3,
} from "lucide-react";
import {
  dynareporterRekrutacjaApi,
  type DrRekrutacjaTeamMember,
} from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const MONTH_NAMES_PL = [
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

// Business thresholds dla Power Calling + LinkedIn Performance.
// Wartości pochodzą z DR `system_config` ale obecnie nie są w response —
// gdy business zmieni progi, modyfikujemy TUTAJ + ewentualnie endpoint
// wraca rzeczywiste wartości. Quality check LOW (single source of truth).
const POWER_CALLING_MIN_PER_DAY = 3;
const LINKEDIN_CV_PER_MD_TARGET = 5;

const ROLE_LABEL_PL: Record<string, string> = {
  sourcer: "Sourcer",
  tac: "TAC",
  recruiter: "Recruiter",
  delivery_lead: "Delivery Lead",
  head_of_recruitment: "Head of Recruitment",
  admin: "Admin",
};

type ViewMode = "week" | "month" | "year";

export default function RekrutacjaPage() {
  const { user, hydrated } = useAuthStore();
  // Stable initial state — bez `new Date()` w render body, żeby uniknąć
  // hydration mismatch między SSR (server timezone) a client (browser
  // timezone). Realne daty ustawiamy w useEffect po hydratacji — query
  // gating `selectedMonth > 0` zapobiega fetch przed inicjalizacją.
  const [viewMode, setViewMode] = useState<ViewMode>("month");
  const [selectedMonth, setSelectedMonth] = useState<number>(0);
  const [selectedYear, setSelectedYear] = useState<number>(0);
  const [selectedWeekNumber, setSelectedWeekNumber] = useState<number | null>(null);

  // Po mount: ustaw aktualny miesiąc + rok z browser timezone.
  useEffect(() => {
    if (selectedMonth === 0) {
      const now = new Date();
      setSelectedMonth(now.getMonth() + 1);
      setSelectedYear(now.getFullYear());
    }
  }, [selectedMonth]);

  // Buduj query params dla endpointu /dashboard.
  const dashboardParams = useMemo(() => {
    if (viewMode === "week" && selectedWeekNumber !== null) {
      return { period: "week" as const, weekNumber: selectedWeekNumber, year: selectedYear };
    }
    if (viewMode === "month") {
      const monthStr = String(selectedMonth).padStart(2, "0");
      return {
        period: "month" as const,
        date: `${selectedYear}-${monthStr}-01`,
      };
    }
    return { period: "year" as const, date: `${selectedYear}-01-01` };
  }, [viewMode, selectedMonth, selectedYear, selectedWeekNumber]);

  // Nie odpalaj query przed inicjalizacją daty (sentinel selectedMonth=0).
  const queryEnabled = hydrated && !!user && selectedMonth > 0;
  const {
    data: dashboard,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["dr-rekrutacja-dashboard", dashboardParams],
    queryFn: () => dynareporterRekrutacjaApi.dashboard(dashboardParams),
    staleTime: 30_000,
    enabled: queryEnabled,
  });

  const { data: availableWeeks } = useQuery({
    queryKey: ["dr-rekrutacja-weeks"],
    queryFn: () => dynareporterRekrutacjaApi.availableWeeks(),
    staleTime: 5 * 60_000,
    enabled: queryEnabled,
  });

  // === Subsection queries (Hall of Fame, Stats Roczne, Wyścig, Power, LinkedIn)
  const { data: hallOfFame } = useQuery({
    queryKey: ["dr-rekrutacja-hof"],
    queryFn: () => dynareporterRekrutacjaApi.hallOfFame(100),
    staleTime: 10 * 60_000,
    enabled: queryEnabled,
  });

  const { data: yearlyStats } = useQuery({
    queryKey: ["dr-rekrutacja-yearly", selectedYear],
    queryFn: () =>
      dynareporterRekrutacjaApi.yearlyStats(
        selectedYear > 0 ? selectedYear : undefined,
      ),
    staleTime: 5 * 60_000,
    enabled: queryEnabled,
  });

  const monthForRaceParam = useMemo(() => {
    if (selectedMonth <= 0) return undefined;
    const mm = String(selectedMonth).padStart(2, "0");
    return `${selectedYear}-${mm}`;
  }, [selectedMonth, selectedYear]);

  const { data: raceRec } = useQuery({
    queryKey: ["dr-rekrutacja-race-rec", monthForRaceParam],
    queryFn: () =>
      dynareporterRekrutacjaApi.monthlyRace("recommendations", monthForRaceParam),
    staleTime: 5 * 60_000,
    enabled: queryEnabled && monthForRaceParam !== undefined,
  });

  const { data: racePlac } = useQuery({
    queryKey: ["dr-rekrutacja-race-plac", monthForRaceParam],
    queryFn: () =>
      dynareporterRekrutacjaApi.monthlyRace("placements", monthForRaceParam),
    staleTime: 5 * 60_000,
    enabled: queryEnabled && monthForRaceParam !== undefined,
  });

  const { data: powerCalling } = useQuery({
    queryKey: ["dr-rekrutacja-pc"],
    queryFn: () => dynareporterRekrutacjaApi.powerCalling(),
    staleTime: 5 * 60_000,
    enabled: queryEnabled,
  });

  const { data: linkedin } = useQuery({
    queryKey: ["dr-rekrutacja-li", dashboardParams],
    queryFn: () => dynareporterRekrutacjaApi.linkedinPerformance(dashboardParams),
    staleTime: 5 * 60_000,
    enabled: queryEnabled,
  });

  const { data: accelerationPath } = useQuery({
    queryKey: ["dr-rekrutacja-accel"],
    queryFn: () => dynareporterRekrutacjaApi.accelerationPath(),
    staleTime: 10 * 60_000,
    enabled: queryEnabled,
  });

  // Year picker: 3 lata wstecz + bieżący + 1 rok naprzód. Derived
  // z `selectedYear` (initialized w useEffect post-mount, defaults
  // do bieżącego). Quality check LOW: nie hardcode `[2024..2027]`.
  const yearOptions = useMemo(() => {
    const base = selectedYear > 0 ? selectedYear : new Date().getFullYear();
    return [base - 2, base - 1, base, base + 1];
  }, [selectedYear]);

  // Early return pattern (mirror body-leasing) — SSR renderuje sam tekst
  // "Ładowanie sesji…", co matchuje client initial render (hydrated=false).
  // Pełna struktura (Cards, Table, etc.) renderuje się dopiero gdy
  // hydration zakończy się klientem, co unika React 19 streaming
  // Activity boundary stuck w `<!--$~-->`.
  if (!hydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie sesji…</div>;
  }
  if (!user) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Zaloguj się żeby zobaczyć dashboard Rekrutacji.
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4 sm:p-6">
      {/* Header + Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center gap-3">
            <h2 className="text-xl font-bold">Rekrutacja</h2>

            {/* View mode tabs */}
            <div className="flex bg-muted rounded-md p-0.5">
              {(["week", "month", "year"] as ViewMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setViewMode(m)}
                  className={`px-3 py-1.5 text-sm font-medium rounded transition-all ${
                    viewMode === m
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {m === "week" ? "Tydzień" : m === "month" ? "Miesiąc" : "Rok"}
                </button>
              ))}
            </div>

            {/* Period selector */}
            {viewMode === "week" && (
              <select
                value={selectedWeekNumber ?? ""}
                onChange={(e) => {
                  const v = e.target.value;
                  if (!v) return;
                  const [wk, yr] = v.split("/").map(Number);
                  setSelectedWeekNumber(wk);
                  setSelectedYear(yr);
                }}
                className="text-sm bg-background border border-input rounded-md px-2 py-1.5"
              >
                <option value="">— wybierz tydzień —</option>
                {(availableWeeks ?? []).map((wk) => (
                  <option
                    key={`${wk.year}-${wk.week_number}`}
                    value={`${wk.week_number}/${wk.year}`}
                  >
                    {wk.label}
                  </option>
                ))}
              </select>
            )}
            {viewMode === "month" && (
              <>
                <select
                  value={selectedMonth}
                  onChange={(e) => setSelectedMonth(Number(e.target.value))}
                  className="text-sm bg-background border border-input rounded-md px-2 py-1.5"
                >
                  {MONTH_NAMES_PL.map((name, i) => (
                    <option key={i + 1} value={i + 1}>
                      {name}
                    </option>
                  ))}
                </select>
                <select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  className="text-sm bg-background border border-input rounded-md px-2 py-1.5"
                >
                  {yearOptions.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </>
            )}
            {viewMode === "year" && (
              <select
                value={selectedYear}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                className="text-sm bg-background border border-input rounded-md px-2 py-1.5"
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            )}

            <div className="sm:ml-auto flex items-center gap-2">
              <Badge variant="neutral" className="gap-1">
                <Calendar className="h-3.5 w-3.5" />
                {dashboard?.period_label ?? "—"}
              </Badge>
              {dashboard && dashboard.users.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => exportPerformanceCsv(dashboard)}
                  title="Eksportuj Performance per osoba do CSV"
                  aria-label="Eksportuj Performance per osoba do CSV"
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  <span className="ml-1 hidden sm:inline">Eksportuj</span>
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => refetch()}
                aria-label="Odśwież dashboard"
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                <span className="ml-1 hidden sm:inline">Odśwież</span>
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {isLoading && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            Ładowanie danych…
          </CardContent>
        </Card>
      )}

      {error && (
        <Card>
          <CardContent className="py-12 text-center text-destructive">
            Błąd ładowania: {String(error)}
          </CardContent>
        </Card>
      )}

      {dashboard && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard
              label="Weryfikacje"
              value={dashboard.team_summary.total_verifications}
              icon={<Users className="h-5 w-5" />}
              accent="border-blue-500"
              accentBg="bg-blue-50 dark:bg-blue-950/30"
            />
            <KpiCard
              label="Rekomendacje"
              value={dashboard.team_summary.total_recommendations}
              icon={<Target className="h-5 w-5" />}
              accent="border-purple-500"
              accentBg="bg-purple-50 dark:bg-purple-950/30"
            />
            <KpiCard
              label="Interviews"
              value={dashboard.team_summary.total_interviews}
              icon={<Target className="h-5 w-5" />}
              accent="border-amber-500"
              accentBg="bg-amber-50 dark:bg-amber-950/30"
            />
            <KpiCard
              label="Placements"
              value={dashboard.team_summary.total_placements}
              icon={<Award className="h-5 w-5" />}
              accent="border-emerald-500"
              accentBg="bg-emerald-50 dark:bg-emerald-950/30"
            />
          </div>

          {/* Efektywność lejka */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Efektywność lejka</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {dashboard.funnel.map((stage) => (
                  <div
                    key={stage.label}
                    className="rounded-md border border-border bg-muted/40 p-3"
                  >
                    <div className="text-xs text-muted-foreground mb-1">
                      {stage.label}
                    </div>
                    <div className="text-2xl font-bold tabular-nums">
                      {stage.percentage}%
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      {stage.numerator} / {stage.denominator}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Liga Mistrzów — Quarterly Podium z gradient + prizes (DR parity) */}
          {dashboard.league_ranking_quarterly.length >= 3 && (
            <Card className="overflow-hidden bg-gradient-to-br from-purple-950/95 via-purple-900/90 to-amber-900/30 dark:from-purple-950 dark:via-purple-900 dark:to-amber-950/40 border-amber-500/30">
              <CardContent className="pt-6">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-3">
                    <Trophy className="h-8 w-8 text-amber-400" />
                    <div>
                      <h3 className="text-2xl font-bold text-amber-100">
                        Liga Mistrzów
                      </h3>
                      <p className="text-sm text-purple-200/80">
                        {dashboard.quarter_label || "Bieżący kwartał"}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Podium top-3 — order: #2, #1, #3 (Olympic podium) */}
                <div className="grid grid-cols-3 gap-3 mt-6 items-end">
                  {(() => {
                    const top3 = dashboard.league_ranking_quarterly.slice(0, 3);
                    const positions = [top3[1], top3[0], top3[2]];
                    const places = [2, 1, 3];
                    return positions.map((m, idx) => {
                      if (!m) return <div key={idx} />;
                      return <QuarterlyPodiumCard key={m.id} member={m} place={places[idx]} />;
                    });
                  })()}
                </div>

                {/* Prizes row — kwoty z system_config (admin editable). */}
                <div className="grid grid-cols-3 gap-3 mt-4">
                  <div className="bg-slate-800/60 border border-slate-400/30 rounded-lg p-3 text-center">
                    <div className="flex items-center justify-center gap-1 mb-1">
                      <Trophy className="w-3.5 h-3.5 text-slate-300" />
                      <span className="text-[10px] uppercase tracking-wider text-slate-300">
                        2. miejsce
                      </span>
                    </div>
                    <div className="text-lg font-bold text-slate-100">
                      {(dashboard.scoring.prize_2 ?? 3000).toLocaleString("pl-PL")} PLN
                    </div>
                  </div>
                  <div className="bg-amber-900/50 border border-amber-400/40 rounded-lg p-3 text-center">
                    <div className="flex items-center justify-center gap-1 mb-1">
                      <Trophy className="w-3.5 h-3.5 text-amber-300" />
                      <span className="text-[10px] uppercase tracking-wider text-amber-200">
                        1. miejsce
                      </span>
                    </div>
                    <div className="text-lg font-bold text-amber-100">
                      {(dashboard.scoring.prize_1 ?? 5000).toLocaleString("pl-PL")} PLN
                    </div>
                  </div>
                  <div className="bg-orange-900/40 border border-orange-500/30 rounded-lg p-3 text-center">
                    <div className="flex items-center justify-center gap-1 mb-1">
                      <Trophy className="w-3.5 h-3.5 text-orange-300" />
                      <span className="text-[10px] uppercase tracking-wider text-orange-200">
                        3. miejsce
                      </span>
                    </div>
                    <div className="text-lg font-bold text-orange-100">
                      {(dashboard.scoring.prize_3 ?? 2000).toLocaleString("pl-PL")} PLN
                    </div>
                  </div>
                </div>

                {/* System punktowy + warunek udziału */}
                <div className="mt-5 pt-4 border-t border-purple-700/50 space-y-2">
                  <p className="text-xs text-purple-200/90">
                    <span className="font-semibold text-amber-300">System punktowy:</span>{" "}
                    Placement = <strong>{dashboard.scoring.placement} pkt</strong> · Interview ={" "}
                    <strong>{dashboard.scoring.interview} pkt</strong> · Rekomendacja ={" "}
                    <strong>{dashboard.scoring.recommendation} pkt</strong>
                  </p>
                  <p className="text-xs text-purple-200/80">
                    <span className="font-semibold text-amber-300/90">⚠ Warunek udziału:</span>{" "}
                    minimum 1 placement miesięcznie (łącznie 3 w kwartale). Osoby poniżej
                    progu są oznaczane jako "brakuje placementu" — nadal w grze, ale muszą
                    nadrobić.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Performance per osoba */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Performance per osoba — {dashboard.period_label}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {dashboard.users.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  Brak danych KPI w wybranym okresie.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Osoba</TableHead>
                        <TableHead>Rola</TableHead>
                        <TableHead className="text-right">Weryfikacje</TableHead>
                        <TableHead className="text-right">Rekomendacje</TableHead>
                        <TableHead className="text-right">Interviews</TableHead>
                        <TableHead className="text-right">Placements</TableHead>
                        <TableHead className="text-right">Punkty</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {dashboard.users.map((m) => (
                        <TableRow key={m.id} className={!m.is_active ? "opacity-60" : ""}>
                          <TableCell className="font-medium">
                            {m.first_name} {m.last_name}
                            {!m.is_active && (
                              <Badge variant="outline" className="ml-2 text-[10px]">
                                nieaktywny
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {ROLE_LABEL_PL[m.role] ?? m.role}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {m.metrics.verifications.value}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {m.metrics.recommendations.value}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {m.metrics.interviews.value}
                          </TableCell>
                          <TableCell className="text-right tabular-nums font-semibold">
                            {m.metrics.placements.value}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            <Badge variant="neutral">{m.league_points} pkt</Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* === Wyścig Rekomendacji + Wyścig Placementów (monthly) ====== */}
          {(raceRec || racePlac) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {raceRec && <MonthlyRaceCard race={raceRec} icon="🎯" />}
              {racePlac && <MonthlyRaceCard race={racePlac} icon="🏁" />}
            </div>
          )}

          {/* === Statystyki Roczne — wykres tygodniowy ==================== */}
          {yearlyStats && yearlyStats.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-indigo-500" />
                  Statystyki Roczne — {selectedYear}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={yearlyStats}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis
                      dataKey="week_label"
                      tick={{ fontSize: 10 }}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <YAxis
                      tick={{ fontSize: 11 }}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <RechartsTooltip
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 6,
                        fontSize: 12,
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line
                      type="monotone"
                      dataKey="verifications"
                      stroke="#3B82F6"
                      strokeWidth={2}
                      name="Weryfikacje"
                    />
                    <Line
                      type="monotone"
                      dataKey="recommendations"
                      stroke="#A855F7"
                      strokeWidth={2}
                      name="Rekomendacje"
                    />
                    <Line
                      type="monotone"
                      dataKey="interviews"
                      stroke="#F59E0B"
                      strokeWidth={2}
                      name="Interviews"
                    />
                    <Line
                      type="monotone"
                      dataKey="placements"
                      stroke="#10B981"
                      strokeWidth={2}
                      name="Placements"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* === Power Calling daily ranking ============================== */}
          {powerCalling && powerCalling.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Phone className="h-5 w-5 text-rose-500" />
                  Power Calling — {powerCalling[0]?.week_label ?? ""}
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  Wymóg: min. {POWER_CALLING_MIN_PER_DAY} weryfikacji/dzień
                  roboczy. Sortowane od najgorszych.
                </p>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Osoba</TableHead>
                        <TableHead>Rola</TableHead>
                        <TableHead className="text-right">Weryfikacje</TableHead>
                        <TableHead className="text-right">Dni</TableHead>
                        <TableHead className="text-right">Wer/dzień</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {powerCalling.map((pc) => {
                        const isUnderTarget =
                          pc.per_day < POWER_CALLING_MIN_PER_DAY &&
                          pc.days_worked > 0;
                        return (
                          <TableRow key={pc.user_id}>
                            <TableCell className="font-medium">{pc.user_name}</TableCell>
                            <TableCell className="text-muted-foreground">
                              {ROLE_LABEL_PL[pc.role] ?? pc.role}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {pc.verifications}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {pc.days_worked}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              <Badge variant={isUnderTarget ? "danger" : "success"} size="sm">
                                {pc.per_day.toFixed(2)}/dzień
                              </Badge>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* === LinkedIn Performance ===================================== */}
          {linkedin && linkedin.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Linkedin className="h-5 w-5 text-blue-600" />
                  LinkedIn Performance (TAC) — {dashboard.period_label}
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  Target: {LINKEDIN_CV_PER_MD_TARGET} CV/MD. Response Rate =
                  responses / messages sent × 100.
                </p>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Osoba</TableHead>
                        <TableHead className="text-right">CV dodane</TableHead>
                        <TableHead className="text-right">CV/MD</TableHead>
                        <TableHead className="text-right">Wiadomości</TableHead>
                        <TableHead className="text-right">Odpowiedzi</TableHead>
                        <TableHead className="text-right">Response Rate</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {linkedin.map((l) => (
                        <TableRow key={l.user_id}>
                          <TableCell className="font-medium">{l.user_name}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {l.cv_added}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            <Badge
                              variant={
                                l.cv_per_md >= LINKEDIN_CV_PER_MD_TARGET
                                  ? "success"
                                  : "neutral"
                              }
                              size="sm"
                            >
                              {l.cv_per_md.toFixed(2)}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {l.messages_sent}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {l.responses_received}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {l.response_rate.toFixed(1)}%
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* === Hall of Fame ============================================= */}
          {hallOfFame && hallOfFame.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Medal className="h-5 w-5 text-amber-500" />
                  Hall of Fame — historyczni zwycięzcy
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Period</TableHead>
                        <TableHead>Typ</TableHead>
                        <TableHead className="text-center">Miejsce</TableHead>
                        <TableHead>Zwycięzca</TableHead>
                        <TableHead className="text-right">Punkty</TableHead>
                        <TableHead className="text-right">Metric</TableHead>
                        <TableHead>Nagroda</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {hallOfFame.map((h, idx) => (
                        <TableRow key={idx}>
                          <TableCell className="font-mono text-xs">{h.period}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {h.competition_type}
                          </TableCell>
                          <TableCell className="text-center">
                            {h.rank === 1 ? "🥇" : h.rank === 2 ? "🥈" : "🥉"}
                          </TableCell>
                          <TableCell className="font-medium">{h.user_name}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {h.points || "–"}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {h.metric_value || "–"}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {h.prize ?? "–"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* === Acceleration Path (Junior→Senior, Senior→Expert) ========= */}
          {accelerationPath &&
            (accelerationPath.junior_to_senior.length > 0 ||
              accelerationPath.senior_to_expert.length > 0) && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                    <Trophy className="h-5 w-5 text-orange-500" />
                    Acceleration Path
                  </CardTitle>
                  <p className="text-xs text-muted-foreground">
                    {(() => {
                      // Progi z server response (threshold_6m/12m per row), bierzemy
                      // z pierwszego dostępnego entry. Quality check: nie hardcode.
                      const j = accelerationPath.junior_to_senior[0];
                      const s = accelerationPath.senior_to_expert[0];
                      const jDesc = j
                        ? `Junior → Senior: ${j.threshold_6m} placement w 6mc LUB ${j.threshold_12m} placement w 12mc`
                        : null;
                      const sDesc = s
                        ? `Senior → Expert: ${s.threshold_6m} placement w 6mc LUB ${s.threshold_12m} placement w 12mc`
                        : null;
                      return [jDesc, sDesc].filter(Boolean).join(" · ");
                    })()}
                    {". "}Łącznie {accelerationPath.junior_count} junior,{" "}
                    {accelerationPath.senior_count} senior,{" "}
                    {accelerationPath.expert_count} expert ·{" "}
                    <strong>
                      {accelerationPath.ready_for_promotion} do awansu
                    </strong>
                    .
                  </p>
                </CardHeader>
                <CardContent className="space-y-4">
                  {accelerationPath.junior_to_senior.length > 0 && (
                    <AccelerationPathTable
                      title={`Junior → Senior (${accelerationPath.junior_to_senior.length} osób)`}
                      entries={accelerationPath.junior_to_senior}
                    />
                  )}
                  {accelerationPath.senior_to_expert.length > 0 && (
                    <AccelerationPathTable
                      title={`Senior → Expert (${accelerationPath.senior_to_expert.length} osób)`}
                      entries={accelerationPath.senior_to_expert}
                    />
                  )}
                </CardContent>
              </Card>
            )}
        </>
      )}
    </div>
  );
}

function AccelerationPathTable({
  title,
  entries,
}: {
  title: string;
  entries: import("@/lib/api").DrAccelerationPathEntry[];
}) {
  return (
    <div>
      <h4 className="text-sm font-semibold mb-2">{title}</h4>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Osoba</TableHead>
              <TableHead>Rola</TableHead>
              <TableHead className="text-center">Start</TableHead>
              <TableHead className="text-right">6mc</TableHead>
              <TableHead className="text-right">12mc</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((e) => {
              const isReady = !!e.next_promotion_date;
              const isBehind = e.status.startsWith("Poniżej");
              return (
                <TableRow key={e.user_id}>
                  <TableCell className="font-medium">{e.user_name}</TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {e.role}
                  </TableCell>
                  <TableCell className="text-center text-xs text-muted-foreground">
                    {e.start_date}
                    <br />
                    <span className="text-[10px]">({e.months_elapsed}mc)</span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-sm">
                    {e.placements_6m}/{e.threshold_6m}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-sm">
                    {e.placements_12m}/{e.threshold_12m}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={isReady ? "success" : isBehind ? "danger" : "neutral"}
                      size="sm"
                    >
                      {e.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/**
 * Pojedyncza karta Wyścig Rekomendacji / Placementów.
 */
function MonthlyRaceCard({
  race,
  icon,
}: {
  race: import("@/lib/api").DrMonthlyRace;
  icon: string;
}) {
  const top = race.entries.slice(0, 5);
  const title =
    race.competition_type === "recommendations"
      ? "Wyścig Rekomendacji"
      : "Wyścig Placementów";
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <span>{icon}</span>
          {title}
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {race.month} · {race.voucher}
        </p>
        <p className="text-xs text-muted-foreground italic">
          {race.requirement} · Lider kwartalny wykluczony z nagrody miesięcznej.
        </p>
      </CardHeader>
      <CardContent>
        {top.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            Brak wpisów w tym miesiącu.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">#</TableHead>
                <TableHead>Osoba</TableHead>
                <TableHead className="text-right">Wartość</TableHead>
                <TableHead className="text-right">/dzień</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {top.map((e, idx) => (
                <TableRow key={e.user_id}>
                  <TableCell>
                    <Badge
                      variant={idx === 0 ? "alert" : "neutral"}
                      size="sm"
                    >
                      {idx + 1}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium">{e.user_name}</TableCell>
                  <TableCell className="text-right tabular-nums font-semibold">
                    {e.metric_value}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {e.per_day.toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function exportPerformanceCsv(
  dashboard: import("@/lib/api").DrRekrutacjaDashboard,
): void {
  const header = [
    "Imie",
    "Nazwisko",
    "Rola",
    "Weryfikacje",
    "Rekomendacje",
    "Interviews",
    "Placements",
    "Punkty Ligi",
  ];
  const rows = dashboard.users.map((m) => [
    m.first_name,
    m.last_name,
    m.role,
    m.metrics.verifications.value,
    m.metrics.recommendations.value,
    m.metrics.interviews.value,
    m.metrics.placements.value,
    m.league_points,
  ]);
  const csv = [header, ...rows]
    .map((row) =>
      row
        .map((cell) => {
          const s = String(cell ?? "");
          return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        })
        .join(","),
    )
    .join("\n");
  // BOM dla Excel (PL znaki)
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `rekrutacja-${dashboard.period}-${dashboard.period_start}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function KpiCard({
  label,
  value,
  icon,
  accent,
  accentBg,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  accent: string;
  accentBg: string;
}) {
  return (
    <div className={`rounded-lg border-t-4 ${accent} ${accentBg} p-3`}>
      <div className="flex items-center gap-2 mb-1">
        <div className="p-1 rounded bg-background/70">{icon}</div>
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
      </div>
      <div className="text-2xl font-bold tabular-nums">{value}</div>
    </div>
  );
}

// PodiumCard usunięty — zastąpiony przez QuarterlyPodiumCard (PR #263).
// ESLint flag'ował go jako dead code w QA review 2026-05-19.

/**
 * Quarterly podium card — full DR-style visual.
 * Place 1 = gold gradient + crown
 * Place 2 = silver, Place 3 = bronze
 * Position-aware height (place 1 taller — Olympic style).
 */
function QuarterlyPodiumCard({
  member,
  place,
}: {
  member: DrRekrutacjaTeamMember;
  place: number;
}) {
  const PLACE_META: Record<
    number,
    {
      bg: string;
      border: string;
      label: string;
      number: string;
      height: string;
      glow: string;
      crown: boolean;
    }
  > = {
    1: {
      bg: "bg-gradient-to-br from-amber-400/95 to-yellow-500/95",
      border: "border-amber-300",
      label: "text-amber-50",
      number: "text-amber-50",
      height: "min-h-[180px]",
      glow: "shadow-[0_0_30px_rgba(251,191,36,0.4)]",
      crown: true,
    },
    2: {
      bg: "bg-gradient-to-br from-slate-300/95 to-slate-400/95",
      border: "border-slate-200",
      label: "text-slate-50",
      number: "text-slate-50",
      height: "min-h-[160px]",
      glow: "",
      crown: false,
    },
    3: {
      bg: "bg-gradient-to-br from-orange-500/90 to-orange-700/90",
      border: "border-orange-400",
      label: "text-orange-50",
      number: "text-orange-50",
      height: "min-h-[150px]",
      glow: "",
      crown: false,
    },
  };
  const meta = PLACE_META[place];
  const fullName = `${member.first_name} ${member.last_name}`.trim() || "—";
  return (
    <div
      className={`rounded-lg ${meta.bg} ${meta.border} ${meta.height} ${meta.glow} border-2 p-4 flex flex-col items-center justify-end text-center relative`}
    >
      {meta.crown && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <span className="text-2xl">👑</span>
        </div>
      )}
      <div className={`text-xs uppercase font-semibold ${meta.label} opacity-80 mb-1`}>
        {ROLE_LABEL_PL[member.role] ?? member.role}
      </div>
      <div className={`text-base font-bold ${meta.label} mb-2 leading-tight`}>
        {fullName}
      </div>
      <div className={`text-3xl font-extrabold tabular-nums ${meta.number}`}>
        {member.league_points}
      </div>
      <div className={`text-[10px] uppercase tracking-wider ${meta.label} opacity-80`}>
        pkt
      </div>
      <div className={`mt-2 text-[11px] tabular-nums ${meta.label} opacity-90`}>
        {member.metrics.placements.value}P / {member.metrics.interviews.value}I /{" "}
        {member.metrics.recommendations.value}R
      </div>
      <div
        className={`mt-3 text-4xl font-black ${meta.number} opacity-30 leading-none`}
      >
        {place}
      </div>
    </div>
  );
}
