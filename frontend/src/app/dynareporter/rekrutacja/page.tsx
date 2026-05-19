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
import { Users, Target, Calendar, RefreshCw, Trophy, Award } from "lucide-react";
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

          <p className="text-xs text-muted-foreground text-center py-2">
            Faza port-do-Nexusa. Brakuje jeszcze: Wyścig Rek/Plac, Power Calling, Hall of
            Fame, Statystyki Roczne chart, LinkedIn Performance, Acceleration Path. Pełna
            wersja z drag-and-drop sekcji + eksport CSV — w kolejnych iteracjach.
          </p>
        </>
      )}
    </div>
  );
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
