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
                  {[2024, 2025, 2026, 2027].map((y) => (
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
                {[2024, 2025, 2026, 2027].map((y) => (
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
                >
                  <Download className="h-4 w-4" />
                  <span className="ml-1 hidden sm:inline">Eksportuj</span>
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                <RefreshCw className="h-4 w-4" />
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

          {/* Liga Mistrzów — Podium */}
          {dashboard.league_ranking.length >= 3 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Trophy className="h-5 w-5 text-amber-500" />
                  Liga Mistrzów — Podium
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  Punktacja: placement = {dashboard.scoring.placement} pkt · interview ={" "}
                  {dashboard.scoring.interview} pkt · rekomendacja ={" "}
                  {dashboard.scoring.recommendation} pkt
                </p>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {dashboard.league_ranking.slice(0, 3).map((m, idx) => (
                    <PodiumCard key={m.id} member={m} place={idx + 1} />
                  ))}
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
                  Wymóg: min. 3 weryfikacji/dzień roboczy. Sortowane od najgorszych.
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
                        const isUnderTarget = pc.per_day < 3 && pc.days_worked > 0;
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
                  Target: 5 CV/MD. Response Rate = responses / messages sent × 100.
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
                              variant={l.cv_per_md >= 5 ? "success" : "neutral"}
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
        </>
      )}
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

function PodiumCard({ member, place }: { member: DrRekrutacjaTeamMember; place: number }) {
  const PLACE_META: Record<number, { emoji: string; ring: string }> = {
    1: { emoji: "🥇", ring: "ring-amber-400" },
    2: { emoji: "🥈", ring: "ring-slate-300" },
    3: { emoji: "🥉", ring: "ring-orange-400" },
  };
  const meta = PLACE_META[place];
  return (
    <div className={`rounded-lg border bg-card p-4 ring-2 ring-offset-2 ${meta.ring}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-2xl">{meta.emoji}</span>
        <div className="text-xs text-muted-foreground uppercase">Miejsce {place}</div>
      </div>
      <div className="font-semibold text-base">
        {member.first_name} {member.last_name}
      </div>
      <div className="text-xs text-muted-foreground mb-2">
        {ROLE_LABEL_PL[member.role] ?? member.role}
      </div>
      <div className="text-2xl font-bold tabular-nums">{member.league_points}</div>
      <div className="text-xs text-muted-foreground">punktów</div>
      <div className="mt-2 text-[11px] text-muted-foreground">
        {member.metrics.placements.value}P / {member.metrics.interviews.value}I /{" "}
        {member.metrics.recommendations.value}R
      </div>
    </div>
  );
}
