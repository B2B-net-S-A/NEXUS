"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Clock,
  Gift,
  Loader2,
  Mail,
  Target,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import {
  PER_DAY_REASON_LABEL,
  formatMonthPl,
  isClosedMonth,
  perDayVerifications,
  precisionOf,
  racesApi,
  type MonthlyRace,
  type MonthlyRaceEntry,
  type MonthlyRacesResponse,
} from "@/lib/insights-races-api";
import { count, pct } from "./InsightsFormat";
import { SectionError } from "./_shared";

/**
 * Wyścig Rekomendacji + Wyścig Placementów — parytet z DynaReporterem
 * (`client/src/components/competitions/MonthlyRaces.tsx`).
 *
 * Cztery rzeczy, które ten ekran robi świadomie inaczej niż oryginał:
 *
 * 1. **Plakietka „X/dzień" nie zgaduje mianownika.** Oryginał dzielił przez
 *    sztywną liczbę dni i pokazywał „3.1/dzień" osobie, która połowę miesiąca
 *    była na urlopie. Mianownik jest INDYWIDUALNY i pochodzi z COMPASSA
 *    (`insights_workdays.working_days_for`); dopóki go nie ma, plakietka mówi
 *    „—" i podpisuje się „brak danych o dniach roboczych". Ekran, który w tym
 *    miejscu podstawia stałą, wygląda dokładnie tak samo jak ten, który wie —
 *    i to jest cała różnica.
 * 2. **Niezakwalifikowany zostaje na liście.** Backend celowo zwraca go
 *    z `qualified: false` i powodem (`competitions.py`); ukrycie zamieniłoby
 *    „próg niespełniony" w „zero wyniku".
 * 3. **Stopka mówi PRAWDZIWĄ regułę remisu.** DynaReporter pisał „Remis:
 *    Wyższa sumaryczna marża". Silnik NEXUSA rozstrzyga remis po `u.id`
 *    (patrz komentarze w `competitions.py`), więc przepisanie tamtej stopki
 *    byłoby napisem o zasadzie, której ten ranking nie stosuje — a ranking
 *    rozdziela voucher 1 500 PLN.
 * 4. **Odliczanie tylko dla trwającego miesiąca.** `days_remaining` backend
 *    liczy z „dzisiaj", nie z `period`, więc dla sierpnia oglądanego we
 *    wrześniu opisywałoby wrzesień. Zamknięty miesiąc dostaje chip
 *    „Zakończony" zamiast liczby.
 */

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
  MIN_VERIFICATIONS_NOT_MET: "Za mało weryfikacji",
  MIN_PRECISION_NOT_MET: "Za niska skuteczność rekomendacji",
  MIN_PLACEMENTS_NOT_MET: "Brakuje placementu do progu",
};

type RaceVariant = "recommendations" | "placements";

const RACE_COPY: Record<
  RaceVariant,
  {
    icon: typeof Mail;
    title: string;
    /** Jednostka przy liczbie — „rek." / „plac.", jak w oryginale. */
    unit: string;
    /** Akcent nagłówka: niebieski (rekomendacje) / zielony (placementy). */
    accent: string;
    iconClass: string;
    emptyText: string;
    /**
     * Przypis o tym, kogo NA LIŚCIE NIE MA. Wyścig Placementów tnie próg
     * dwóch placementów w `HAVING`, więc osoba z jednym nie wraca z bazy —
     * bez tego zdania jej nieobecność czyta się jak zero placementów.
     */
    populationNote: string | null;
  }
> = {
  recommendations: {
    icon: Mail,
    title: "Wyścig Rekomendacji",
    unit: "rek.",
    accent: "from-info/15 via-info/5 to-transparent",
    iconClass: "text-info",
    emptyText:
      "Nikt nie odnotował jeszcze rekomendacji w tym miesiącu. To pusty ranking, nie błąd pobierania.",
    populationNote:
      "Lista pokazuje też osoby, które nie spełniły warunków — z powodem przy nazwisku.",
  },
  placements: {
    icon: Target,
    title: "Wyścig Placementów",
    unit: "plac.",
    accent: "from-success/15 via-success/5 to-transparent",
    iconClass: "text-success",
    emptyText:
      "Nikt nie ma jeszcze dwóch placementów w tym miesiącu. To pusty ranking, nie błąd pobierania.",
    populationNote:
      "Lista zawiera wyłącznie osoby z min. 2 placementami — próg jest w zapytaniu do bazy, więc pozostali w ogóle nie wracają. Nieobecność nie znaczy zera.",
  },
};

/** Polska odmiana — „1 dzień / 2 dni / 5 dni". */
function daysPl(n: number): string {
  return `${n} ${Math.abs(n) === 1 ? "dzień" : "dni"}`;
}

function describeDisqualification(entry: MonthlyRaceEntry): string | null {
  if (entry.qualified !== false) return null;
  const codes = (entry.disqualification_reasons ?? []).filter(Boolean);
  if (codes.length === 0) return "Nie spełnia warunku udziału";
  // Nieznany kod renderujemy dosłownie — milczenie wyglądałoby jak brak
  // powodu, a powód zawsze istnieje, tylko my go (jeszcze) nie znamy.
  return codes
    .map(
      (code) =>
        DISQUALIFICATION_REASON[code] ?? `Warunek niespełniony: ${code}`,
    )
    .join(" · ");
}

/** Plakietka „3.1/dzień" albo uczciwe „—" z etykietą powodu. */
function PerDayBadge({ entry }: { entry: MonthlyRaceEntry }) {
  const perDay = perDayVerifications(entry);
  if (perDay.value === null) {
    const label = PER_DAY_REASON_LABEL[perDay.reason as "no_workday_data"];
    return (
      <span
        className="inline-flex items-center gap-1 rounded border border-dashed border-border bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground"
        title={`Weryfikacje na dzień roboczy: ${label}. Mianownik jest indywidualny (urlop też) i pochodzi z COMPASSA — nie zastępujemy go stałą liczbą dni.`}
      >
        <span className="font-semibold">—</span>
        <span>/dzień</span>
        <span className="hidden sm:inline">· {label}</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded bg-info-muted px-1.5 py-0.5 text-[11px] font-semibold text-info-muted-foreground">
      {perDay.value.toFixed(1)}/dzień
    </span>
  );
}

/**
 * Precision rate. Świadomie z JEDNYM miejscem po przecinku: zaokrąglenie do
 * pełnych procent pokazywałoby 74,9% jako „75%", czyli dokładnie próg, którego
 * ta osoba nie osiągnęła.
 */
function PrecisionBadge({ entry }: { entry: MonthlyRaceEntry }) {
  const value = precisionOf(entry);
  const missed = entry.disqualification_reasons?.includes(
    "MIN_PRECISION_NOT_MET",
  );
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-semibold",
        value === null
          ? "border border-dashed border-border bg-muted text-muted-foreground"
          : missed
            ? "bg-warning-muted text-warning-muted-foreground"
            : "bg-success-muted text-success-muted-foreground",
      )}
      title={
        value === null
          ? "Brak weryfikacji w tym oknie — nie ma z czego policzyć skuteczności."
          : "Precision rate = rekomendacje / weryfikacje"
      }
    >
      {pct(value)}
    </span>
  );
}

function RaceRow({
  entry,
  variant,
}: {
  entry: MonthlyRaceEntry;
  variant: RaceVariant;
}) {
  const copy = RACE_COPY[variant];
  const disqualified = describeDisqualification(entry);

  return (
    <li className="flex items-start gap-3 rounded-lg border border-border bg-card px-3 py-2">
      <span
        className={cn(
          "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
          entry.rank <= 3
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        )}
        aria-hidden="true"
      >
        {entry.rank}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate text-sm font-semibold text-foreground">
            {entry.name}
          </span>
          {variant === "recommendations" ? (
            <>
              <PerDayBadge entry={entry} />
              <PrecisionBadge entry={entry} />
            </>
          ) : null}
        </div>

        <p className="mt-0.5 text-xs text-muted-foreground">
          {ROLE_LABEL[entry.role ?? ""] ?? entry.role ?? "—"}
          {variant === "recommendations" &&
          entry.required_verifications !== null &&
          entry.required_verifications !== undefined ? (
            // Liczby SUROWE, bez przeliczania na tempo dzienne: to jest próg,
            // który backend naprawdę stosuje, a nie nasza rekonstrukcja.
            <>
              {" · "}
              {count(entry.verifications)} /{" "}
              {count(entry.required_verifications)} wymaganych weryfikacji
            </>
          ) : null}
        </p>

        {entry.excluded ? (
          <p className="mt-1 inline-flex rounded border border-info/25 bg-info-muted px-1.5 py-0.5 text-[11px] font-medium text-info-muted-foreground">
            Lider kwartału — w rankingu zostaje, nagrody miesięcznej nie bierze
          </p>
        ) : null}

        {disqualified ? (
          <p className="mt-1 inline-flex rounded border border-warning/25 bg-warning-muted px-1.5 py-0.5 text-[11px] font-medium text-warning-muted-foreground">
            {disqualified}
          </p>
        ) : null}
      </div>

      <span className="shrink-0 text-right text-sm font-extrabold text-foreground">
        {count(entry.metric_value)}
        <span className="ml-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {copy.unit}
        </span>
      </span>
    </li>
  );
}

function RaceCard({
  race,
  variant,
}: {
  race: MonthlyRace;
  variant: RaceVariant;
}) {
  const [showAll, setShowAll] = useState(false);
  const copy = RACE_COPY[variant];
  const Icon = copy.icon;
  const ranking = race.ranking ?? [];
  const visible = showAll ? ranking : ranking.slice(0, 3);
  const closed = isClosedMonth(race.period);

  return (
    <article className="flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <header
        className={cn(
          "flex items-start justify-between gap-3 border-b border-border bg-linear-to-r px-4 py-3",
          copy.accent,
        )}
      >
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-base font-bold text-foreground">
            <Icon
              className={cn("h-5 w-5", copy.iconClass)}
              aria-hidden="true"
            />
            <span className="truncate">{copy.title}</span>
          </h3>
          <p className="mt-0.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {formatMonthPl(race.period)}
          </p>
        </div>
        <div className="shrink-0 text-right">
          {closed ? (
            <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
              Zakończony
            </span>
          ) : (
            <p className="flex items-center justify-end gap-1 text-xs text-muted-foreground">
              <Clock className="h-3.5 w-3.5" aria-hidden="true" />
              {/* `null` to „nie wiemy, ile zostało", nie „zero dni". */}
              {race.days_remaining === null || race.days_remaining === undefined
                ? "—"
                : `Zostało ${daysPl(race.days_remaining)}`}
            </p>
          )}
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <p className="flex items-start gap-2 rounded-lg border border-warning/25 bg-warning-muted px-3 py-2 text-xs font-semibold text-warning-muted-foreground">
          <Gift className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{race.prize.name}</span>
        </p>

        {/* Reguła gry przychodzi z serwera i tam jest jedynym źródłem prawdy —
            przepisana we froncie rozjechałaby się z silnikiem przy pierwszej
            zmianie progu. */}
        {race.requirements?.length ? (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {race.requirements.map((req) => (
              <li key={req}>{req}</li>
            ))}
          </ul>
        ) : null}

        {ranking.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1 py-8 text-center">
            <Icon
              className="h-9 w-9 text-muted-foreground opacity-40"
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-foreground">
              Brak wyników w tym miesiącu
            </p>
            <p className="max-w-sm text-xs text-muted-foreground">
              {copy.emptyText}
            </p>
          </div>
        ) : (
          <>
            <ol className="space-y-2">
              {visible.map((entry) => (
                <RaceRow key={entry.user_id} entry={entry} variant={variant} />
              ))}
            </ol>

            {ranking.length > 3 ? (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="inline-flex items-center justify-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
              >
                {showAll ? (
                  <>
                    <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
                    Zwiń
                  </>
                ) : (
                  <>
                    <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
                    Pokaż wszystkich ({ranking.length})
                  </>
                )}
              </button>
            ) : null}
          </>
        )}

        <div className="mt-auto space-y-1 border-t border-border pt-2 text-[11px] text-muted-foreground">
          {copy.populationNote ? <p>{copy.populationNote}</p> : null}
          <p>
            Remis: przy tej samej liczbie wyżej jest osoba z wcześniej założonym
            kontem. NEXUS nie rozstrzyga remisu marżą.
          </p>
        </div>
      </div>
    </article>
  );
}

export function InsightsRaces({ month }: { month?: string | null }) {
  const { data, isPending, isSuccess, isError, error, refetch } =
    useQuery<MonthlyRacesResponse>({
      // Prefiks `insights` — „Odśwież" z paska narzędzi unieważnia po prefiksie.
      queryKey: ["insights", "monthly-races", month ?? "current"],
      queryFn: () => racesApi.monthlyRaces(month),
      staleTime: 5 * 60 * 1000,
    });

  const recommendations = data?.recommendations;
  const placements = data?.placements;
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    // Pustka DOPIERO gdy zabrakło obu kopert — pojedynczy pusty ranking to
    // normalny stan miesiąca, obsłużony wewnątrz karty.
    isEmpty: !recommendations && !placements,
  });

  if (viewState === "loading") {
    return (
      <section aria-label="Wyścigi miesięczne">
        <div className="flex items-center justify-center rounded-xl border border-border bg-card py-12">
          <Loader2
            className="h-5 w-5 animate-spin text-muted-foreground"
            aria-label="Ładowanie"
          />
        </div>
      </section>
    );
  }

  if (isBlockingViewState(viewState)) {
    return (
      <section aria-label="Wyścigi miesięczne">
        <SectionError
          label="Wyścigi miesięczne"
          error={error}
          onRetry={() => void refetch()}
        />
      </section>
    );
  }

  if (viewState === "empty" || !recommendations || !placements) {
    return (
      <section aria-label="Wyścigi miesięczne">
        <div className="rounded-xl border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm font-medium text-foreground">
            Brak danych o wyścigach
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Serwer nie zwrócił żadnego z dwóch wyścigów. To pusta odpowiedź, nie
            błąd pobierania.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section aria-label="Wyścigi miesięczne" className="space-y-3">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <RaceCard race={recommendations} variant="recommendations" />
        <RaceCard race={placements} variant="placements" />
      </div>
    </section>
  );
}
