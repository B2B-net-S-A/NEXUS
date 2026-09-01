"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Award,
  ChevronDown,
  ChevronUp,
  Clock,
  Crown,
  Loader2,
  Medal,
  TrendingUp,
  Trophy,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { count, money, pct } from "./InsightsFormat";
import { SectionError } from "./_shared";

/**
 * Liga Mistrzów — podium 1-2-3 w układzie oryginału (DynaReporter,
 * `client/src/components/competitions/QuarterlyLeague.tsx`).
 *
 * Trzy rzeczy, które ten ekran robi świadomie:
 *
 * 1. **Niezakwalifikowany NIE znika.** Backend celowo zostawia go w rankingu
 *    z `qualified: false` i powodem (`competitions.py`: „twardy `continue`
 *    sprawiał, że osoba bez wymaganego placementu znikała bez śladu"). Widok,
 *    który by go ukrył, cofałby tę decyzję: brak nazwiska czyta się jak „zero
 *    wyniku", a nie jak „próg jeszcze nie spełniony".
 * 2. **Reguła gry jest na ekranie.** `points_formula` i `requirement` przychodzą
 *    z konfiguracji (D3) i mogą się zmienić bez deployu. Ranking bez widocznej
 *    formuły jest wyrocznią — rozdziela 5000/3000/2000 PLN według zasady, której
 *    uczestnik nie może sprawdzić.
 * 3. **Awaria ≠ pustka.** 403/500 renderuje `SectionError` z ponowieniem;
 *    „brak wyników" to osobny, spokojny stan.
 */

// ── Kontrakt z `/api/competitions/current` ──────────────────────────────

/** Pozycja rankingu: `RankedUser.to_dict()` + `rank`/`prize_pln` dla top3. */
interface LeagueEntry {
  user_id: number;
  name: string;
  /** Punkty (Liga Rekrutacja) albo placementy (Liga DL). */
  metric_value: number;
  hit_ratio?: number | null;
  rank?: number;
  prize_pln?: number | null;
  role?: string | null;
  placements?: number | null;
  interviews?: number | null;
  recommendations?: number | null;
  verifications?: number | null;
  requests?: number | null;
  /** Brak pola = zakwalifikowany (lustro `extras.get("qualified", True)`). */
  qualified?: boolean;
  required_placements?: number | null;
  disqualification_reasons?: string[] | null;
}

interface PointsFormula {
  placement: number;
  interview: number;
  recommendation: number;
}

interface CompetitionPayload {
  type: string;
  period: string;
  top3: LeagueEntry[];
  full_ranking: LeagueEntry[];
  is_frozen: boolean;
  target_pct?: number | null;
  days_remaining?: number | null;
  prize_pool_pln?: number | null;
  requirement?: string | null;
  points_formula?: PointsFormula | null;
  /** Klucze przychodzą z JSON-a jako napisy („1"/„2"/„3"). */
  quarterly_prizes_pln?: Record<string, number> | null;
}

// ── Podium ──────────────────────────────────────────────────────────────

type PodiumRank = 1 | 2 | 3;

/**
 * Złoto/srebro/brąz WYŁĄCZNIE na tokenach (`warning`, `secondary`, `muted`) —
 * oryginał miał `from-yellow-400`/`to-gray-300`, czyli kolory, które nie znają
 * ani trybu ciemnego, ani sześciu pozostałych palet.
 */
const RANK_STYLE: Record<
  PodiumRank,
  {
    icon: typeof Crown;
    iconClass: string;
    medal: string;
    /** Wysokość słupka — 1. miejsce najwyższe, jak w DynaReporterze. */
    height: string;
    pedestal: string;
    value: string;
  }
> = {
  1: {
    icon: Crown,
    iconClass: "text-warning",
    medal: "🥇",
    height: "h-24 sm:h-28",
    pedestal: "bg-warning text-warning-foreground border-warning",
    value: "text-warning-muted-foreground",
  },
  2: {
    icon: Medal,
    iconClass: "text-muted-foreground",
    medal: "🥈",
    height: "h-16 sm:h-20",
    pedestal: "bg-secondary text-secondary-foreground border-border",
    value: "text-foreground",
  },
  3: {
    icon: Medal,
    iconClass: "text-warning-muted-foreground",
    medal: "🥉",
    height: "h-12 sm:h-16",
    pedestal:
      "bg-warning-muted text-warning-muted-foreground border-warning/30",
    value: "text-foreground",
  },
};

/** Kolejność WIZUALNA 2 | 1 | 3 robi CSS; DOM zostaje 1, 2, 3. */
const RANK_FLEX_ORDER: Record<PodiumRank, string> = {
  1: "order-2",
  2: "order-1",
  3: "order-3",
};

const ROLE_LABEL: Record<string, string> = {
  sourcer: "Sourcer",
  tac: "TAC",
  recruiter: "Rekruter",
  delivery_lead: "Delivery Lead",
  head_of_recruitment: "Head of Recruitment",
  admin: "Admin",
};

/** Kody z `extras.disqualification_reasons` (`services/competitions.py`). */
const DISQUALIFICATION_REASON: Record<string, string> = {
  MIN_PLACEMENTS_NOT_MET: "Brakuje placementu do progu",
  MIN_VERIFICATIONS_NOT_MET: "Za mało weryfikacji",
  MIN_PRECISION_NOT_MET: "Za niska skuteczność rekomendacji",
};

/**
 * Powód niezakwalifikowania albo `null`, gdy osoba jest w grze o nagrodę.
 *
 * Nieznany kod NADAL musi coś powiedzieć — milczenie w tym miejscu wygląda jak
 * brak powodu, a powód zawsze istnieje, tylko my go (jeszcze) nie znamy.
 */
function describeDisqualification(entry: LeagueEntry): string | null {
  if (entry.qualified !== false) return null;
  const codes = (entry.disqualification_reasons ?? []).filter(Boolean);
  if (codes.length === 0) return "Nie spełnia warunku udziału";
  return codes
    .map((code) => {
      const label =
        DISQUALIFICATION_REASON[code] ?? `Warunek niespełniony: ${code}`;
      return code === "MIN_PLACEMENTS_NOT_MET" &&
        entry.required_placements !== null &&
        entry.required_placements !== undefined
        ? `${label} (wymagane: ${entry.required_placements})`
        : label;
    })
    .join(" · ");
}

type LeagueVariant = "points" | "placements";

/** Rozbicie pod liczbą — „9P / 25I / 60R" w Lidze Rekrutacja, hit ratio w DL. */
function breakdownLabel(entry: LeagueEntry, variant: LeagueVariant): string {
  if (variant === "points") {
    return `${count(entry.placements)}P / ${count(entry.interviews)}I / ${count(
      entry.recommendations,
    )}R`;
  }
  return `hit ratio ${pct(entry.hit_ratio)} · ${count(entry.requests)} zapytań`;
}

/** Polska odmiana — „1 dzień / 2 dni / 5 dni". */
function daysPl(n: number): string {
  return `${n} ${Math.abs(n) === 1 ? "dzień" : "dni"}`;
}

function PodiumColumn({
  rank,
  entry,
  variant,
  metricLabel,
}: {
  rank: PodiumRank;
  entry?: LeagueEntry;
  variant: LeagueVariant;
  metricLabel: string;
}) {
  const style = RANK_STYLE[rank];
  const Icon = style.icon;
  const disqualified = entry ? describeDisqualification(entry) : null;

  return (
    <li
      className={cn(
        "flex min-w-0 flex-1 flex-col items-center",
        RANK_FLEX_ORDER[rank],
      )}
    >
      <div className="mb-2 flex w-full flex-col items-center text-center">
        <Icon
          className={cn(
            "h-6 w-6",
            entry ? style.iconClass : "text-muted-foreground/50",
          )}
          aria-hidden="true"
        />
        <p
          className={cn(
            "mt-1 w-full truncate text-sm font-semibold",
            entry ? "text-foreground" : "text-muted-foreground",
          )}
          title={entry?.name}
        >
          {/* Puste miejsce na podium to „—", nie zero i nie zniknięcie kolumny:
              znikająca kolumna rozjeżdża słupki i sugeruje, że dane się nie
              doczytały. */}
          {entry?.name ?? "—"}
        </p>
        <p className="text-xs text-muted-foreground">
          {entry
            ? (ROLE_LABEL[entry.role ?? ""] ?? entry.role ?? "—")
            : "Wolne miejsce"}
        </p>
        {entry ? (
          <>
            <p className={cn("mt-1 text-2xl font-extrabold", style.value)}>
              {count(entry.metric_value)}{" "}
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {metricLabel}
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              {breakdownLabel(entry, variant)}
            </p>
            {entry.prize_pln ? (
              // Nagroda przy niezakwalifikowanym jest WARUNKOWA: backend dokleja
              // `prize_pln` po samym indeksie, a `qualified_for_award` filtruje
              // dopiero wypłatę. Sucha kwota obok „brakuje placementu" obiecywałaby
              // pieniądze, których ta osoba dziś nie dostaje.
              <p
                className={cn(
                  "mt-1 text-xs font-bold",
                  disqualified
                    ? "text-muted-foreground"
                    : "text-success-muted-foreground",
                )}
              >
                {money(entry.prize_pln)}
                {disqualified ? " (po spełnieniu warunku)" : ""}
              </p>
            ) : null}
            {disqualified ? (
              <p className="mt-1 rounded border border-warning/25 bg-warning-muted px-1.5 py-0.5 text-[11px] font-medium text-warning-muted-foreground">
                {disqualified}
              </p>
            ) : null}
          </>
        ) : null}
      </div>

      <div
        className={cn(
          "flex w-full items-center justify-center rounded-t-lg border text-2xl font-extrabold",
          style.height,
          entry
            ? style.pedestal
            : "border-dashed border-border bg-muted text-muted-foreground",
        )}
      >
        <span aria-hidden="true">{style.medal}</span>
        <span className="ml-1">{rank}</span>
      </div>
    </li>
  );
}

// ── Karta jednej ligi ───────────────────────────────────────────────────

function LeagueCard({
  competitionType,
  title,
  subtitle,
  variant,
  metricLabel,
}: {
  competitionType: string;
  title: string;
  subtitle: string;
  variant: LeagueVariant;
  /** Jednostka pod liczbą: „pkt" (punkty) albo „placementów" (Liga DL). */
  metricLabel: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const { data, isPending, isSuccess, isError, error, refetch } =
    useQuery<CompetitionPayload>({
      // Prefiks `insights` — żeby „Odśwież" z paska narzędzi (invalidacja po
      // prefiksie) obejmowało także Ligę.
      queryKey: ["insights", "champions", competitionType],
      queryFn: () =>
        api
          .get(`/api/competitions/current?type=${competitionType}`)
          .then((r) => r.data),
      staleTime: 5 * 60 * 1000,
    });

  const top3 = data?.top3 ?? [];
  const fullRanking = data?.full_ranking ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: top3.length === 0 && fullRanking.length === 0,
  });

  const byRank = new Map<number, LeagueEntry>(
    top3.map((entry, index) => [entry.rank ?? index + 1, entry]),
  );
  const podiumIds = new Set(top3.map((entry) => entry.user_id));
  // `full_ranking` nie niesie `rank` — numer bierzemy z pozycji, tak jak
  // backend przy budowie podium.
  const rest = fullRanking
    .map((entry, index) => ({ entry, rank: index + 1 }))
    .filter((row) => !podiumIds.has(row.entry.user_id));

  const prizes = data?.quarterly_prizes_pln ?? null;

  return (
    <article className="flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <header className="flex items-start justify-between gap-3 border-b border-border bg-linear-to-r from-primary/10 via-primary/5 to-transparent px-4 py-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-base font-bold text-foreground">
            <Trophy className="h-5 w-5 text-warning" aria-hidden="true" />
            <span className="truncate">{title}</span>
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-xs font-semibold uppercase tracking-wider text-primary">
            {data?.period ?? "—"}
          </p>
          <p className="mt-0.5 flex items-center justify-end gap-1 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5" aria-hidden="true" />
            {/* `null` to „nie wiemy, ile zostało", nie „zero dni". */}
            {data?.days_remaining === null || data?.days_remaining === undefined
              ? "—"
              : `Zostało ${daysPl(data.days_remaining)}`}
          </p>
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-4 p-4">
        {viewState === "loading" ? (
          <div className="flex items-center justify-center py-10">
            <Loader2
              className="h-5 w-5 animate-spin text-muted-foreground"
              aria-label="Ładowanie"
            />
          </div>
        ) : isBlockingViewState(viewState) ? (
          <SectionError
            label={title}
            error={error}
            onRetry={() => void refetch()}
          />
        ) : viewState === "empty" ? (
          <div className="flex flex-col items-center justify-center gap-1 py-10 text-center">
            <Trophy
              className="h-9 w-9 text-muted-foreground opacity-40"
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-foreground">
              Brak wyników w tym kwartale
            </p>
            <p className="max-w-sm text-xs text-muted-foreground">
              Nikt nie odnotował jeszcze punktowanych zdarzeń. To pusty ranking,
              nie błąd pobierania.
            </p>
            {data?.requirement ? (
              <p className="max-w-sm text-xs text-muted-foreground">
                {data.requirement}
              </p>
            ) : null}
          </div>
        ) : (
          <>
            <ol className="flex list-none items-end justify-center gap-2 sm:gap-3">
              {([1, 2, 3] as PodiumRank[]).map((rank) => (
                <PodiumColumn
                  key={rank}
                  rank={rank}
                  entry={byRank.get(rank)}
                  variant={variant}
                  metricLabel={metricLabel}
                />
              ))}
            </ol>

            {prizes ? (
              <div className="grid grid-cols-3 gap-2">
                {([1, 2, 3] as PodiumRank[]).map((rank) => (
                  <div
                    key={rank}
                    className="rounded-lg border border-border bg-muted/40 p-2 text-center"
                  >
                    <p className="text-[11px] text-muted-foreground">
                      {rank}. miejsce
                    </p>
                    <p className="text-sm font-semibold text-foreground">
                      {money(prizes[String(rank)])}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="rounded-lg border border-border bg-muted/40 p-3">
              <p className="flex items-center gap-2 text-xs font-medium text-foreground">
                <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />
                {/* Liga DL nie ma formuły punktowej — nagłówek „System
                    punktowy" nad zdaniem „bez przeliczania na punkty" sam
                    sobie przeczy. */}
                {data?.points_formula ? "System punktowy" : "Zasada rankingu"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {data?.points_formula ? (
                  <>
                    Placement{" "}
                    <strong className="text-foreground">
                      {data.points_formula.placement} pkt
                    </strong>{" "}
                    · Interview{" "}
                    <strong className="text-foreground">
                      {data.points_formula.interview} pkt
                    </strong>{" "}
                    · Rekomendacja{" "}
                    <strong className="text-foreground">
                      {data.points_formula.recommendation} pkt
                    </strong>
                  </>
                ) : (
                  // Liga DL nie przelicza na punkty — milczący kafel sugerowałby,
                  // że formuła istnieje, tylko się nie doczytała.
                  "Ranking liczy placementy — bez przeliczania na punkty."
                )}
              </p>
              {data?.prize_pool_pln ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Pula nagród: {money(data.prize_pool_pln)}
                </p>
              ) : null}
            </div>

            {data?.requirement ? (
              <div className="rounded-lg border border-warning/25 bg-warning-muted p-3 text-warning-muted-foreground">
                <p className="flex items-center gap-2 text-xs font-medium">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                  Warunek udziału
                </p>
                <p className="mt-1 text-xs">{data.requirement}</p>
                <p className="mt-1 text-[11px] opacity-90">
                  Osoby poniżej progu ZOSTAJĄ w rankingu — oznaczamy je, nie
                  ukrywamy.
                </p>
              </div>
            ) : null}

            {rest.length > 0 ? (
              <div>
                <button
                  type="button"
                  onClick={() => setShowAll((open) => !open)}
                  aria-expanded={showAll}
                  className="flex w-full items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
                >
                  {showAll ? (
                    <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {showAll
                    ? "Zwiń ranking"
                    : `Zobacz pełny ranking (${rest.length} więcej)`}
                </button>
                {showAll ? (
                  <ul className="mt-2 space-y-1.5">
                    {rest.map(({ entry, rank }) => {
                      const disqualified = describeDisqualification(entry);
                      return (
                        <li
                          key={entry.user_id}
                          className={cn(
                            "flex items-center justify-between gap-3 rounded-lg border px-3 py-2",
                            disqualified
                              ? "border-warning/25 bg-warning-muted"
                              : "border-border bg-muted/40",
                          )}
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <span className="w-7 shrink-0 text-xs font-semibold text-muted-foreground">
                              #{rank}
                            </span>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-foreground">
                                {entry.name}
                                {disqualified ? (
                                  <span className="ml-2 text-xs font-normal text-warning-muted-foreground">
                                    ({disqualified})
                                  </span>
                                ) : null}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {ROLE_LABEL[entry.role ?? ""] ??
                                  entry.role ??
                                  "—"}
                              </p>
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            <p className="text-sm font-bold text-foreground">
                              {count(entry.metric_value)} {metricLabel}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {breakdownLabel(entry, variant)}
                            </p>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </div>
    </article>
  );
}

// ── Sekcja ──────────────────────────────────────────────────────────────

export function ChampionsSection() {
  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Award className="h-5 w-5 text-warning" aria-hidden="true" />
        Liga Mistrzów — kwartalni championi
      </h2>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <LeagueCard
          competitionType="quarterly_champions_recruiter"
          title="Liga Mistrzów Rekrutacja"
          subtitle="Kwartalny ranking punktowy zespołu rekrutacji"
          variant="points"
          // Ranking rekruterów liczy PUNKTY (placement/interview/rekomendacja
          // z konfiguracji D3), nie liczbę placementów — label „placementów"
          // kłamał przy `metric_value` będącym sumą punktów.
          metricLabel="pkt"
        />
        <LeagueCard
          competitionType="quarterly_champions_dl"
          title="Liga Mistrzów DL"
          subtitle="Kwartalne podium Delivery Leadów"
          variant="placements"
          metricLabel="placementów"
        />
      </div>
    </section>
  );
}
