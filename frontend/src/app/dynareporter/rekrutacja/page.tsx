"use client";

/**
 * DynaReporter Rekrutacja mega-dashboard.
 *
 * Port `/rekrutacja` z oryginalnego DR (artur-t-96/InfraReporter,
 * `client/src/pages/Rekrutacja.tsx`). Zawiera:
 * - Period picker (Tydzień / Miesiąc / Rok)
 * - KPI cards: Weryfikacje / Rekomendacje / Interviews / Placements
 * - Efektywność lejka: 4 konwersje (Wer→Rek, Rek→Int, Int→Plac, Overall)
 * - Performance per osoba – tabela team
 * - Liga Mistrzów – podium top-3 + ranking
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

// Business thresholds dla Power Calling + LinkedIn Performance – DEFAULTS.
// Aktualne wartości pochodzą z `dashboard.scoring.power_calling_min_per_day` +
// `dashboard.scoring.linkedin_cv_per_md_target` (admin editable w ScoringConfig
// → Admin → Ustawienia). Te defaults są używane gdy dashboard jeszcze nie
// załadowany (1st render fallback).
const POWER_CALLING_MIN_PER_DAY_DEFAULT = 3;
const LINKEDIN_CV_PER_MD_TARGET_DEFAULT = 5;

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
  // Stable initial state – bez `new Date()` w render body, żeby uniknąć
  // hydration mismatch między SSR (server timezone) a client (browser
  // timezone). Realne daty ustawiamy w useEffect po hydratacji – query
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

  const { data: placementAnalysis } = useQuery({
    queryKey: ["dr-rekrutacja-plac-analysis", dashboardParams],
    queryFn: () => dynareporterRekrutacjaApi.placementAnalysis(dashboardParams),
    staleTime: 5 * 60_000,
    enabled: queryEnabled,
  });

  const { data: teamPanel } = useQuery({
    queryKey: ["dr-rekrutacja-team-panel"],
    queryFn: () => dynareporterRekrutacjaApi.teamPanel(),
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

  // Early return pattern (mirror body-leasing) – SSR renderuje sam tekst
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
                <option value="">– wybierz tydzień –</option>
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
                {dashboard?.period_label ?? "–"}
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

          {/* Liga Mistrzów – Quarterly League (full DR port) */}
          {dashboard.league_ranking_quarterly.length > 0 && (
            <QuarterlyLeagueSection dashboard={dashboard} />
          )}

          {/* Performance per osoba */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Performance per osoba – {dashboard.period_label}
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
              {raceRec && (
                <MonthlyRaceCard race={raceRec} currentUserId={user.id} />
              )}
              {racePlac && (
                <MonthlyRaceCard race={racePlac} currentUserId={user.id} />
              )}
            </div>
          )}

          {/* === Statystyki Roczne – wykres tygodniowy ==================== */}
          {yearlyStats && yearlyStats.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-indigo-500" />
                  Statystyki Roczne – {selectedYear}
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
                  Power Calling – {powerCalling[0]?.week_label ?? ""}
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  Wymóg: min.{" "}
                  {dashboard.scoring.power_calling_min_per_day ??
                    POWER_CALLING_MIN_PER_DAY_DEFAULT}{" "}
                  weryfikacji/dzień roboczy. Sortowane od najgorszych.
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
                        const threshold =
                          dashboard.scoring.power_calling_min_per_day ??
                          POWER_CALLING_MIN_PER_DAY_DEFAULT;
                        const isUnderTarget =
                          pc.per_day < threshold && pc.days_worked > 0;
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
                  LinkedIn Performance (TAC) – {dashboard.period_label}
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  Target:{" "}
                  {dashboard.scoring.linkedin_cv_per_md_target ??
                    LINKEDIN_CV_PER_MD_TARGET_DEFAULT}{" "}
                  CV/MD. Response Rate = responses / messages sent × 100.
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
                                l.cv_per_md >=
                                (dashboard.scoring.linkedin_cv_per_md_target ??
                                  LINKEDIN_CV_PER_MD_TARGET_DEFAULT)
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
                  Hall of Fame – historyczni zwycięzcy
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

          {/* === Analiza Placementów (wg osób + wg klientów) ============== */}
          {placementAnalysis && placementAnalysis.total > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Award className="h-5 w-5 text-emerald-500" />
                  Analiza Placementów – {dashboard.period_label} (
                  {placementAnalysis.total})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* By person */}
                  <div>
                    <h4 className="text-sm font-semibold mb-2">
                      Placementy wg osób
                    </h4>
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Osoba</TableHead>
                            <TableHead>Rola</TableHead>
                            <TableHead className="text-right">Plac.</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {placementAnalysis.by_person.map((p) => (
                            <TableRow key={p.user_id}>
                              <TableCell className="font-medium">
                                {p.user_name}
                              </TableCell>
                              <TableCell className="text-muted-foreground text-xs">
                                {ROLE_LABEL_PL[p.role] ?? p.role}
                              </TableCell>
                              <TableCell className="text-right tabular-nums font-semibold">
                                {p.count}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                  {/* By client */}
                  <div>
                    <h4 className="text-sm font-semibold mb-2">
                      Placementy wg klientów
                    </h4>
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Klient</TableHead>
                            <TableHead className="text-right">Plac.</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {placementAnalysis.by_client.map((c) => (
                            <TableRow key={c.client_id}>
                              <TableCell className="font-medium">
                                {c.client_name}
                              </TableCell>
                              <TableCell className="text-right tabular-nums font-semibold">
                                {c.count}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* === Zespół Rekrutacji - Przypisania (read-only display) ====== */}
          {teamPanel &&
            (teamPanel.sourcer_categories.length > 0 ||
              teamPanel.tac_dl.length > 0) && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                    <Users className="h-5 w-5 text-teal-500" />
                    Zespół Rekrutacji – Przypisania
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  {/* Sourcerzy wg Kategorii Kompetencji */}
                  {teamPanel.sourcer_categories.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold mb-2 flex items-center gap-1">
                        👥 Sourcerzy wg Kategorii Kompetencji
                      </h4>
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Kategoria kompetencji</TableHead>
                              <TableHead>1st priority</TableHead>
                              <TableHead>2nd priority</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {teamPanel.sourcer_categories.map((cat) => (
                              <TableRow key={cat.category_id}>
                                <TableCell className="font-medium">
                                  {cat.category_name}
                                </TableCell>
                                <TableCell>
                                  <div className="flex flex-wrap gap-1">
                                    {cat.first_priority.map((s) => (
                                      <Badge
                                        key={s.user_id}
                                        variant="success"
                                        size="sm"
                                      >
                                        {s.name}
                                      </Badge>
                                    ))}
                                  </div>
                                </TableCell>
                                <TableCell>
                                  <div className="flex flex-wrap gap-1">
                                    {cat.second_priority.map((s) => (
                                      <Badge
                                        key={s.user_id}
                                        variant="neutral"
                                        size="sm"
                                      >
                                        {s.name}
                                      </Badge>
                                    ))}
                                  </div>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  )}

                  {/* TAC - Delivery Lead */}
                  {teamPanel.tac_dl.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold mb-2 flex items-center gap-1">
                        🔗 TAC – Delivery Lead
                      </h4>
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Delivery Lead</TableHead>
                              <TableHead>TAC</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {teamPanel.tac_dl.map((dl) => (
                              <TableRow key={dl.dl_user_id}>
                                <TableCell className="font-medium">
                                  {dl.dl_name}
                                </TableCell>
                                <TableCell>
                                  <div className="flex flex-wrap gap-1">
                                    {dl.tac_names.map((tac, i) => (
                                      <Badge key={i} variant="warning" size="sm">
                                        {tac}
                                      </Badge>
                                    ))}
                                  </div>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  )}
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
 * Wyścig Rekomendacji / Placementów – full DR port z
 * artur-t-96/InfraReporter `client/src/components/competitions/MonthlyRace.tsx`.
 *
 * Features:
 * - Gradient bg per competition type (blue rekomendacje / emerald placementy)
 * - Header: emoji + title + miesiąc/rok + days remaining countdown
 * - Prize banner (Gift icon)
 * - Verification rate requirement warning (yellow)
 * - Precision rate requirement warning (cyan, od 2026-04)
 * - Exclusion warning (purple) jeśli last month of quarter
 * - Top 3 z rank badges + per-row badges (verification/dzień ✓/✗, precision ✓/✗)
 * - Current user "Ty" highlight
 * - "Wykluczony" badge na lider kwartalnym
 * - Show all standings collapse
 * - Tie breaker footer
 */
function MonthlyRaceCard({
  race,
  currentUserId,
}: {
  race: import("@/lib/api").DrMonthlyRace;
  currentUserId?: number | null;
}) {
  const [showAll, setShowAll] = useState(false);
  const isRecommendations = race.competition_type === "recommendations";
  const icon = isRecommendations ? "📨" : "🎯";
  const title = isRecommendations ? "Wyścig Rekomendacji" : "Wyścig Placementów";
  const bgGradient = isRecommendations
    ? "from-blue-600 to-indigo-700"
    : "from-emerald-600 to-teal-700";

  const top3 = race.entries.slice(0, 3);
  const rest = race.entries.slice(3);
  const currentUserEntry = race.entries.find((e) => e.user_id === currentUserId);
  const leader = race.entries[0];

  const getValue = (
    e: import("@/lib/api").DrMonthlyRaceEntry,
  ): number => e.metric_value;

  return (
    <div
      className={`bg-gradient-to-br ${bgGradient} rounded-xl overflow-hidden shadow-lg`}
    >
      {/* Header */}
      <div className="px-3 py-3 sm:px-5 sm:py-4 border-b border-white/10">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 sm:gap-3">
            <span className="text-2xl sm:text-3xl">{icon}</span>
            <div>
              <h3 className="text-base sm:text-lg font-bold text-white">
                {title}
              </h3>
              <p className="text-white/70 text-xs sm:text-sm">
                {race.month_name} {race.year}
              </p>
            </div>
          </div>
          <div className="text-right">
            {race.is_completed ? (
              <div className="flex items-center gap-1 text-green-300">
                <span className="text-base">✓</span>
                <span className="font-bold text-sm">Zakończony</span>
              </div>
            ) : (
              <div className="flex items-center gap-1 text-white/80">
                <Calendar className="w-4 h-4" />
                <span className="font-bold text-white">{race.days_remaining}</span>
                <span className="text-xs sm:text-sm">dni</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Prize banner */}
      <div className="px-3 py-2 sm:px-5 sm:py-3 bg-white/10 flex items-center gap-2">
        <span className="text-lg">🎁</span>
        <span className="text-white/90 text-xs sm:text-sm">{race.prize}</span>
      </div>

      {/* Min qualification banner (placements) */}
      {!isRecommendations && race.min_qualification != null && (
        <div className="px-3 py-2 sm:px-5 bg-amber-500/20 flex items-center gap-2">
          <span className="text-amber-300">⚠</span>
          <span className="text-amber-200 text-xs sm:text-sm">
            Minimum {race.min_qualification} placementy do kwalifikacji!
          </span>
        </div>
      )}

      {/* Verification requirement (recommendations) */}
      {isRecommendations && race.verification_requirement != null && (
        <div className="px-3 py-2 sm:px-5 bg-amber-500/20 flex items-center gap-2">
          <span className="text-amber-300">⚠</span>
          <span className="text-amber-200 text-xs sm:text-sm">
            Wymóg: min. {race.verification_requirement} weryfikacji/dzień
            roboczy w tym miesiącu
          </span>
        </div>
      )}

      {/* Precision rate requirement (recommendations, 2026-04+) */}
      {isRecommendations &&
        race.is_precision_rate_active &&
        race.precision_rate_requirement != null && (
          <div className="px-3 py-2 sm:px-5 bg-cyan-500/20 flex items-center gap-2">
            <span className="text-cyan-300">⚠</span>
            <span className="text-cyan-200 text-xs sm:text-sm">
              Wymóg: min. {race.precision_rate_requirement}% precision rate
              (rekomendacje / weryfikacje)
            </span>
          </div>
        )}

      {/* Exclusion warning */}
      {race.is_last_month_of_quarter && race.excluded_user_id && (
        <div className="px-3 py-2 sm:px-5 bg-purple-500/20 flex items-center gap-2">
          <span className="text-purple-300">⚠</span>
          <span className="text-purple-200 text-xs sm:text-sm">
            Lider kwartalny wykluczony z nagrody miesięcznej
          </span>
        </div>
      )}

      {/* Top 3 */}
      <div className="px-3 py-3 sm:px-5 sm:py-4">
        {top3.length === 0 ? (
          <p className="text-white/70 text-sm py-4 text-center">
            Brak wpisów w tym miesiącu.
          </p>
        ) : (
          <div className="space-y-2">
            {top3.map((entry, index) => {
              const value = getValue(entry);
              const isCurrentUser = entry.user_id === currentUserId;
              const isFullyEligible =
                entry.meets_verification_requirement &&
                entry.meets_precision_requirement;
              const showVerifBadge = isRecommendations;
              const showPrecisionBadge =
                isRecommendations && race.is_precision_rate_active;
              return (
                <div
                  key={entry.user_id}
                  className={`flex items-center justify-between px-3 py-2 sm:px-4 sm:py-3 rounded-lg transition-all ${
                    isCurrentUser
                      ? "bg-white/20 ring-2 ring-white/50"
                      : "bg-white/10 hover:bg-white/15"
                  } ${entry.is_excluded ? "opacity-60" : ""}`}
                >
                  <div className="flex items-center gap-2 sm:gap-3">
                    {/* Rank badge */}
                    <div
                      className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center font-bold text-xs sm:text-sm ${
                        index === 0
                          ? "bg-yellow-400 text-yellow-900"
                          : index === 1
                            ? "bg-gray-300 text-gray-700"
                            : "bg-amber-600 text-amber-100"
                      }`}
                    >
                      {index + 1}
                    </div>
                    <div>
                      <div className="flex items-center gap-1 sm:gap-2 flex-wrap">
                        <span className="text-white font-medium text-sm sm:text-base">
                          {entry.user_name}
                        </span>
                        {isCurrentUser && (
                          <span className="text-xs bg-white/20 px-2 py-0.5 rounded">
                            Ty
                          </span>
                        )}
                        {entry.is_excluded && (
                          <span className="text-xs bg-purple-500/30 text-purple-200 px-2 py-0.5 rounded">
                            Wykluczony
                          </span>
                        )}
                        {showVerifBadge && (
                          <span
                            className={`text-xs px-2 py-0.5 rounded flex items-center gap-1 ${
                              entry.meets_verification_requirement
                                ? "bg-green-500/30 text-green-200"
                                : "bg-orange-500/30 text-orange-200"
                            }`}
                          >
                            {entry.meets_verification_requirement ? "✓" : "⚠"}{" "}
                            {entry.verifications_per_day.toFixed(1)}/dzień
                          </span>
                        )}
                        {showPrecisionBadge && (
                          <span
                            className={`text-xs px-2 py-0.5 rounded flex items-center gap-1 ${
                              entry.meets_precision_requirement
                                ? "bg-green-500/30 text-green-200"
                                : "bg-cyan-500/30 text-cyan-200"
                            }`}
                          >
                            {entry.meets_precision_requirement ? "✓" : "⚠"}{" "}
                            {entry.precision_rate}%
                          </span>
                        )}
                      </div>
                      <span className="text-white/60 text-xs">
                        {ROLE_LABEL_PL[entry.role] ?? entry.role}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 sm:gap-3">
                    {!isRecommendations && (
                      <div
                        className={`flex items-center gap-1 ${entry.is_qualified ? "text-green-300" : "text-red-300"}`}
                      >
                        {entry.is_qualified ? "✓" : "✗"}
                      </div>
                    )}
                    {isRecommendations && (
                      <div
                        className={`flex items-center gap-1 ${isFullyEligible ? "text-green-300" : "text-orange-300"}`}
                      >
                        {isFullyEligible ? "✓" : "⚠"}
                      </div>
                    )}
                    <div className="text-right">
                      <span className="text-xl sm:text-2xl font-bold text-white">
                        {value}
                      </span>
                      <span className="text-white/60 text-xs sm:text-sm ml-1">
                        {isRecommendations ? "rek." : "plac."}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Current user if not in top 3 */}
        {currentUserEntry &&
          !top3.some((e) => e.user_id === currentUserEntry.user_id) && (
            <div className="mt-4 pt-4 border-t border-white/10">
              <div className="flex items-center justify-between px-4 py-3 bg-white/20 rounded-lg ring-2 ring-white/50">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center font-bold text-sm text-white">
                    {race.entries.findIndex((e) => e.user_id === currentUserId) +
                      1}
                  </div>
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-white font-medium">
                        {currentUserEntry.user_name}
                      </span>
                      <span className="text-xs bg-white/20 px-2 py-0.5 rounded">
                        Ty
                      </span>
                    </div>
                    <span className="text-white/60 text-xs">
                      {ROLE_LABEL_PL[currentUserEntry.role] ??
                        currentUserEntry.role}
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="text-2xl font-bold text-white">
                    {getValue(currentUserEntry)}
                  </span>
                  <span className="text-white/60 text-sm ml-1">
                    {isRecommendations ? "rek." : "plac."}
                  </span>
                  {leader && (
                    <p className="text-white/60 text-xs">
                      Do lidera: {getValue(leader) - getValue(currentUserEntry)}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

        {/* Show more button */}
        {rest.length > 0 && (
          <button
            onClick={() => setShowAll(!showAll)}
            className="w-full mt-4 flex items-center justify-center gap-2 py-2 text-white/70 hover:text-white transition-colors"
          >
            {showAll ? "▲ Zwiń" : `▼ Pokaż wszystkich (${rest.length})`}
          </button>
        )}

        {/* Full standings */}
        {showAll && rest.length > 0 && (
          <div className="mt-2 space-y-1">
            {rest.map((entry, idx) => {
              const isCurrentUser = entry.user_id === currentUserId;
              return (
                <div
                  key={entry.user_id}
                  className={`flex items-center justify-between px-4 py-2 bg-white/5 rounded-lg text-sm ${
                    isCurrentUser ? "ring-1 ring-white/30" : ""
                  }`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-white/50 w-6">#{idx + 4}</span>
                    <span className="text-white/80">{entry.user_name}</span>
                    {isCurrentUser && (
                      <span className="text-xs bg-white/10 px-1.5 py-0.5 rounded">
                        Ty
                      </span>
                    )}
                    {isRecommendations && (
                      <span
                        className={`text-xs px-1.5 py-0.5 rounded ${
                          entry.meets_verification_requirement
                            ? "bg-green-500/30 text-green-200"
                            : "bg-orange-500/30 text-orange-200"
                        }`}
                      >
                        {entry.meets_verification_requirement ? "✓" : "⚠"}{" "}
                        {entry.verifications_per_day.toFixed(1)}/d
                      </span>
                    )}
                  </div>
                  <span className="text-white font-medium">{getValue(entry)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer – tie breaker */}
      <div className="px-3 py-2 sm:px-5 sm:py-3 bg-black/20 text-center">
        <p className="text-white/60 text-xs">Remis: {race.tie_breaker}</p>
      </div>
    </div>
  );
}

/**
 * Liga Mistrzów – full DR port z `client/src/components/competitions/QuarterlyLeague.tsx`.
 *
 * Sections:
 * - Header: Trophy + quarter label + days_remaining countdown z progress bar
 * - Olympic podium top-3 (#2/#1/#3 z height variation + gradient bg)
 * - Prizes row (1st/2nd/3rd PLN)
 * - System punktowy display
 * - Entry requirement warning
 * - Full standings collapse (#4+)
 */
function QuarterlyLeagueSection({
  dashboard,
}: {
  dashboard: import("@/lib/api").DrRekrutacjaDashboard;
}) {
  const [showAll, setShowAll] = useState(false);
  const standings = dashboard.league_ranking_quarterly;
  const top3 = standings.slice(0, 3);
  const rest = standings.slice(3);

  const getPodiumHeight = (rank: number) => {
    switch (rank) {
      case 1:
        return "h-32";
      case 2:
        return "h-24";
      case 3:
        return "h-20";
      default:
        return "h-16";
    }
  };
  const getPodiumColor = (rank: number) => {
    switch (rank) {
      case 1:
        return "bg-gradient-to-t from-yellow-600 to-yellow-400";
      case 2:
        return "bg-gradient-to-t from-gray-500 to-gray-300";
      case 3:
        return "bg-gradient-to-t from-amber-700 to-amber-500";
      default:
        return "bg-gray-600";
    }
  };
  const getRankIcon = (rank: number) => {
    if (rank === 1) return "👑";
    if (rank === 2) return "🥈";
    if (rank === 3) return "🥉";
    return `#${rank}`;
  };

  return (
    <div className="bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 rounded-2xl overflow-hidden shadow-2xl">
      {/* Header */}
      <div className="relative px-3 py-3 sm:px-6 sm:py-5 bg-gradient-to-r from-amber-500/20 via-yellow-500/20 to-amber-500/20 border-b border-amber-500/30">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="p-1.5 sm:p-2 bg-amber-500/30 rounded-xl">
              <Trophy className="w-6 h-6 sm:w-8 sm:h-8 text-amber-400" />
            </div>
            <div>
              <h2 className="text-lg sm:text-2xl font-bold text-white">
                Liga Mistrzów
              </h2>
              <p className="text-amber-300 text-xs sm:text-sm">
                {dashboard.quarter_label || "Bieżący kwartał"}
              </p>
            </div>
          </div>

          {/* Countdown / Zakończony */}
          <div className="text-right">
            {dashboard.quarter_is_completed ? (
              <div className="flex items-center gap-1 sm:gap-2 text-green-400">
                <span className="text-base sm:text-lg">✓</span>
                <span className="text-sm sm:text-base font-bold">
                  Zakończony
                </span>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-1 sm:gap-2 text-amber-300">
                  <Calendar className="w-4 h-4 sm:w-5 sm:h-5" />
                  <span className="text-lg sm:text-2xl font-bold text-white">
                    {dashboard.quarter_days_remaining}
                  </span>
                  <span className="text-xs sm:text-sm">dni</span>
                </div>
                <div className="mt-1 w-20 sm:w-32 h-1.5 sm:h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-amber-500 to-yellow-400 transition-all duration-500"
                    style={{ width: `${dashboard.quarter_progress}%` }}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Podium top-3 – visual Olympic blocks */}
      <div className="px-3 py-4 sm:px-6 sm:py-8">
        {top3.length === 0 ? (
          <p className="text-amber-200/70 text-center py-6">
            Za mało danych – pojawi się top 3 gdy ktoś zacznie zdobywać punkty.
          </p>
        ) : (
          <div className="flex items-end justify-center gap-2 sm:gap-4 mb-6 sm:mb-8">
            {/* 2nd Place */}
            {top3[1] && (
              <PodiumColumn
                member={top3[1]}
                rank={2}
                heightClass={getPodiumHeight(2)}
                colorClass={getPodiumColor(2)}
                rankIcon={getRankIcon(2)}
              />
            )}
            {/* 1st Place */}
            {top3[0] && (
              <PodiumColumn
                member={top3[0]}
                rank={1}
                heightClass={getPodiumHeight(1)}
                colorClass={getPodiumColor(1)}
                rankIcon={getRankIcon(1)}
                star={top3[0].is_qualified}
              />
            )}
            {/* 3rd Place */}
            {top3[2] && (
              <PodiumColumn
                member={top3[2]}
                rank={3}
                heightClass={getPodiumHeight(3)}
                colorClass={getPodiumColor(3)}
                rankIcon={getRankIcon(3)}
              />
            )}
          </div>
        )}

        {/* Prizes row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-3 mb-4 sm:mb-6">
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 text-center">
            <span className="text-yellow-400 mx-auto mb-1 block text-xl">
              👑
            </span>
            <p className="text-xs text-yellow-300">1. miejsce</p>
            <p className="text-sm text-white font-medium">
              {(dashboard.scoring.prize_1 ?? 5000).toLocaleString("pl-PL")} PLN
            </p>
          </div>
          <div className="bg-gray-500/10 border border-gray-500/30 rounded-lg p-3 text-center">
            <span className="text-gray-300 mx-auto mb-1 block text-xl">🥈</span>
            <p className="text-xs text-gray-400">2. miejsce</p>
            <p className="text-sm text-white font-medium">
              {(dashboard.scoring.prize_2 ?? 3000).toLocaleString("pl-PL")} PLN
            </p>
          </div>
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 text-center">
            <span className="text-amber-500 mx-auto mb-1 block text-xl">🥉</span>
            <p className="text-xs text-amber-400">3. miejsce</p>
            <p className="text-sm text-white font-medium">
              {(dashboard.scoring.prize_3 ?? 2000).toLocaleString("pl-PL")} PLN
            </p>
          </div>
        </div>

        {/* Point system */}
        <div className="bg-white/5 rounded-lg p-3 sm:p-4 mb-4">
          <h4 className="text-sm font-medium text-gray-300 mb-2 flex items-center gap-2">
            <span>📊</span>
            System punktowy
          </h4>
          <div className="flex flex-wrap gap-2 sm:gap-4 text-xs sm:text-sm">
            <span className="text-green-400">
              Placement: <strong>{dashboard.scoring.placement} pkt</strong>
            </span>
            <span className="text-blue-400">
              Interview: <strong>{dashboard.scoring.interview} pkt</strong>
            </span>
            <span className="text-purple-400">
              Rekomendacja:{" "}
              <strong>{dashboard.scoring.recommendation} pkt</strong>
            </span>
          </div>
        </div>

        {/* Entry requirement */}
        {dashboard.quarter_entry_requirement && (
          <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-4 mb-4">
            <h4 className="text-sm font-medium text-orange-300 mb-1 flex items-center gap-2">
              ⚠ Warunek udziału w Lidze Mistrzów
            </h4>
            <p className="text-sm text-gray-300">
              {dashboard.quarter_entry_requirement.description}
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Osoby poniżej progu są oznaczone jako &quot;brakuje
              placementu&quot; – nadal w grze, ale muszą nadrobić.
            </p>
          </div>
        )}

        {/* Full standings */}
        {rest.length > 0 && (
          <div>
            <button
              onClick={() => setShowAll(!showAll)}
              className="w-full flex items-center justify-center gap-2 py-2 text-gray-400 hover:text-white transition-colors"
            >
              {showAll
                ? "▲ Zwiń ranking"
                : `▼ Zobacz pełny ranking (${rest.length} więcej)`}
            </button>
            {showAll && (
              <div className="mt-4 space-y-2">
                {rest.map((standing, idx) => (
                  <div
                    key={standing.id}
                    className={`flex items-center justify-between px-4 py-3 rounded-lg ${
                      standing.is_qualified
                        ? "bg-white/5"
                        : "bg-orange-900/20 border border-orange-500/20"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-medium w-8 text-gray-400">
                        #{idx + 4}
                      </span>
                      <div>
                        <p className="font-medium text-white">
                          {standing.first_name} {standing.last_name}
                          {!standing.is_qualified && (
                            <span className="ml-2 text-xs text-orange-400">
                              (brakuje placementu)
                            </span>
                          )}
                        </p>
                        <p className="text-gray-500 text-xs">
                          {ROLE_LABEL_PL[standing.role] ?? standing.role}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-bold text-white">
                        {standing.league_points} pkt
                      </p>
                      <p className="text-xs text-gray-500 tabular-nums">
                        {standing.metrics.placements.value}P /{" "}
                        {standing.metrics.interviews.value}I /{" "}
                        {standing.metrics.recommendations.value}R
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Olympic podium column – 1 osoba.
 */
function PodiumColumn({
  member,
  rank,
  heightClass,
  colorClass,
  rankIcon,
  star = false,
}: {
  member: DrRekrutacjaTeamMember;
  rank: number;
  heightClass: string;
  colorClass: string;
  rankIcon: string;
  star?: boolean;
}) {
  const fullName = `${member.first_name} ${member.last_name}`.trim() || "–";
  return (
    <div className="flex flex-col items-center">
      <div className="mb-2 text-center">
        <div className="relative inline-block">
          <span className="text-3xl">{rankIcon}</span>
          {rank === 1 && star && (
            <span className="absolute -top-1 -right-1 text-yellow-300 animate-pulse">
              ⭐
            </span>
          )}
        </div>
        <p
          className={`font-${rank === 1 ? "bold" : "semibold"} mt-1 text-white ${rank === 1 ? "text-lg" : ""}`}
        >
          {fullName}
        </p>
        <p
          className={`text-xs ${rank === 1 ? "text-amber-300" : "text-gray-400"}`}
        >
          {ROLE_LABEL_PL[member.role] ?? member.role}
        </p>
        <p
          className={`font-bold mt-1 ${
            rank === 1
              ? "text-2xl sm:text-3xl text-yellow-400"
              : rank === 2
                ? "text-lg sm:text-2xl text-gray-300"
                : "text-lg sm:text-2xl text-amber-400"
          }`}
        >
          {member.league_points} pkt
        </p>
        <p
          className={`text-xs tabular-nums ${
            rank === 1
              ? "text-yellow-300/70"
              : rank === 2
                ? "text-gray-400"
                : "text-amber-400/70"
          }`}
        >
          {member.metrics.placements.value}P /{" "}
          {member.metrics.interviews.value}I /{" "}
          {member.metrics.recommendations.value}R
        </p>
        {!member.is_qualified && (
          <p className="text-xs text-orange-400 mt-1">Brakuje placementu</p>
        )}
      </div>
      <div
        className={`${rank === 1 ? "w-20 sm:w-28" : "w-16 sm:w-24"} ${heightClass} ${colorClass} rounded-t-lg flex items-center justify-center ${
          rank === 1 ? "shadow-lg shadow-yellow-500/30" : ""
        }`}
      >
        <span
          className={`font-bold text-white/80 ${
            rank === 1 ? "text-3xl sm:text-4xl" : "text-2xl sm:text-3xl"
          }`}
        >
          {rank}
        </span>
      </div>
    </div>
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

// QuarterlyPodiumCard removed – replaced by `PodiumColumn` (inline w
// QuarterlyLeagueSection) zgodnie z DR layout: Olympic blocks z varying height.
