"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Gift,
  Loader2,
  Mail,
  Target,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
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
import { ClosureNote, PeriodCountdown, SourceNote } from "./CompetitionPeriod";
import { count, pct } from "./InsightsFormat";
import { SectionError } from "./_shared";

/**
 * Wyścig Rekomendacji + Wyścig Placementów — parytet z DynaReporterem
 * (`client/src/components/competitions/MonthlyRaces.tsx`).
 *
 * Cztery rzeczy, które ten ekran robi świadomie inaczej niż oryginał:
 *
 * 1. **Plakietka „X/dzień" mówi, skąd ma mianownik.** Oryginał dzielił przez
 *    sztywną liczbę dni i pokazywał „3.1/dzień" osobie, która połowę miesiąca
 *    była na urlopie. Tu mianownikiem są dni robocze, które upłynęły w tym
 *    miesiącu, minus zatwierdzona nieobecność (`workdays_source: "nexus"`,
 *    urlopy NEXUSA; dawniej `"compass"`). Gdy nieobecności nie znamy
 *    (`"calendar"`), plakietka ma dopisek „bez urlopów" — ta sama liczba bez
 *    dopisku czytałaby się jak ocena osoby na urlopie.
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
 *    „Zakończony" zamiast liczby, a zamrożony (`is_frozen`) — „Zamknięte".
 */

const ROLE_LABEL: Record<string, string> = {
  recruiter: "Rekruter",
  delivery_lead: "Delivery Lead",
  head_of_recruitment: "Head of Recruitment",
  talent_community_manager: "Talent Community Manager",
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
    /**
     * Reguła remisu z regulaminu (decyzja 22.09.2026, `award_order`). Bez
     * kwot — marża jest pieniędzmi, więc ekran mówi tylko, CO rozstrzyga.
     */
    tieRule: string;
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
    tieRule:
      "Remis: wyżej jest wyższa precyzja, a przy równej — osoba, która wcześniej doszła do wyniku.",
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
    tieRule:
      "Remis: rozstrzyga marża na godzinę z placementów w miesiącu; gdy nie da się jej policzyć albo jest równa — decyduje admin przy zamknięciu miesiąca.",
  },
};

/**
 * Próg kwalifikacji Wyścigu Rekomendacji. Przy urlopach NEXUSA
 * (`workdays_source: "nexus"`) `competitions.py` liczy go z dni pracy osoby —
 * tych samych co plakietka „X/dzień" (decyzja Artura 28.10.2026). Przy innym
 * źródle próg jest wspólny i kalendarzowy, a ekran mówi to wprost, żeby nie
 * obiecywać reguły, której backend nie stosuje (audyt B44).
 */
const RACE_THRESHOLD_SHARED =
  "Próg kwalifikacji jest wspólny dla wszystkich: 4 weryfikacje × liczba dni roboczych, które upłynęły w tym miesiącu (Pon–Pt bez świąt). Nie uwzględnia indywidualnych urlopów — te wpływają tylko na plakietkę „/dzień”.";
const RACE_THRESHOLD_PER_PERSON =
  "Próg kwalifikacji liczy się z dni pracy osoby: 4 weryfikacje × dni robocze, które upłynęły w tym miesiącu (Pon–Pt bez świąt), minus jej zatwierdzona nieobecność. Ten sam mianownik ma plakietka „/dzień”, więc urlop nie podnosi wymagania.";

function raceThresholdNote(entry: MonthlyRaceEntry | undefined): string {
  // `threshold_basis` zamraża się z wynikiem — zamknięty miesiąc nie ma
  // `workdays_source`, a próg dalej jest liczony per osoba.
  return entry?.threshold_basis === "workdays" ||
    entry?.workdays_source === "nexus"
    ? RACE_THRESHOLD_PER_PERSON
    : RACE_THRESHOLD_SHARED;
}

/** „15” albo „14,5” — dni pracy mogą mieć połówkę (pół dnia nieobecności). */
function formatWorkdays(days: number): string {
  return Number.isInteger(days)
    ? String(days)
    : days.toFixed(1).replace(".", ",");
}

/** Ile miejsc wyścigu widać bez klikania. */
const DEFAULT_VISIBLE_ROWS = 5;

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
        title={`Weryfikacje na dzień pracy: ${label}. Mianownik to dni robocze, które upłynęły w tym miesiącu, minus zatwierdzona nieobecność.`}
      >
        <span className="font-semibold">—</span>
        <span>/dzień</span>
        <span className="hidden sm:inline">· {label}</span>
      </span>
    );
  }
  const withoutLeave = entry.workdays_source === "calendar";
  // Miesiąc rozliczony w DynaReporterze: mianownik to dni przepracowane
  // zgłoszone tam, zapisane przy rozliczeniu — nie dni z COMPASSA.
  const fromDynaReporter = entry.workdays_source === "dynareporter";
  const fromNexus = entry.workdays_source === "nexus";
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-info-muted px-1.5 py-0.5 text-[11px] font-semibold text-info-muted-foreground"
      title={
        fromDynaReporter
          ? "Weryfikacje na dzień przepracowany: liczba dni przepracowanych zgłoszona w DynaReporterze, zapisana przy rozliczeniu miesiąca."
          : fromNexus
            ? "Weryfikacje na dzień pracy: dni robocze, które upłynęły w tym miesiącu, minus zatwierdzona nieobecność tej osoby."
            : withoutLeave
              ? "Weryfikacje na dzień roboczy liczone z dni kalendarzowych, które upłynęły w tym miesiącu (Pon–Pt bez świąt), bez urlopów — nieobecności z tego okresu nie są znane."
              : "Weryfikacje na dzień roboczy: dni robocze, które upłynęły w tym miesiącu, minus urlop z COMPASSA."
      }
    >
      {perDay.value.toFixed(1)}/dzień
      {fromDynaReporter ? (
        <span className="font-normal">· dni przepracowane (DynaReporter)</span>
      ) : withoutLeave ? (
        <span className="font-normal">· bez urlopów</span>
      ) : null}
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
  isMe = false,
  fullWorkdays = null,
}: {
  entry: MonthlyRaceEntry;
  variant: RaceVariant;
  isMe?: boolean;
  /** Najwięcej dni pracy w tym rankingu — dopisek „liczone z N dni pracy”
   *  stoi tylko przy osobach, które miały ich mniej (makieta 28.10.2026). */
  fullWorkdays?: number | null;
}) {
  const copy = RACE_COPY[variant];
  const disqualified = describeDisqualification(entry);

  return (
    <li
      aria-current={isMe ? "true" : undefined}
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3 py-2",
        isMe ? "border-primary/40 bg-primary/10" : "border-border bg-card",
      )}
    >
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
            {isMe ? <span className="ml-1 text-primary">(Ty)</span> : null}
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
              <span
                title={raceThresholdNote(entry)}
                className="underline decoration-dotted underline-offset-2"
                data-testid="race-threshold"
              >
                {count(entry.verifications)} /{" "}
                {count(entry.required_verifications)} wymaganych weryfikacji
              </span>
              {entry.workdays_source === "nexus" &&
              typeof entry.workdays === "number" &&
              fullWorkdays !== null &&
              entry.workdays < fullWorkdays ? (
                <span className="whitespace-nowrap">
                  {" · "}liczone z {formatWorkdays(entry.workdays)} dni pracy
                </span>
              ) : null}
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
  const meId = useAuthStore((state) => state.user?.id ?? null);
  const copy = RACE_COPY[variant];
  const Icon = copy.icon;
  const ranking = race.ranking ?? [];
  const workdayCounts = ranking
    .map((entry) => entry.workdays)
    .filter((days): days is number => typeof days === "number");
  const fullWorkdays =
    workdayCounts.length > 0 ? Math.max(...workdayCounts) : null;
  // Pierwsza piątka i własny wiersz widać od razu (przebudowa 24.09.2026).
  const visible = showAll
    ? ranking
    : ranking.filter(
        (entry, index) => index < DEFAULT_VISIBLE_ROWS || entry.user_id === meId,
      );
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
          <PeriodCountdown
            frozen={race.is_frozen === true}
            closed={closed}
            daysRemaining={race.days_remaining}
          />
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <SourceNote closure={race} />
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
              {race.closure_status === "no_winner"
                ? "Brak zwycięzcy w tym okresie"
                : "Brak wyników w tym miesiącu"}
            </p>
            <p className="max-w-sm text-xs text-muted-foreground">
              {copy.emptyText}
            </p>
          </div>
        ) : (
          <>
            {/* Remis do decyzji admina i miesiąc bez zwycięzcy stoją NAD
                listą: bez tego zdania pierwsze miejsce czyta się jak wygrana. */}
            <ClosureNote closure={race} />
            <ol className="space-y-2">
              {visible.map((entry) => (
                <RaceRow
                  key={entry.user_id}
                  entry={entry}
                  variant={variant}
                  isMe={entry.user_id === meId}
                  fullWorkdays={fullWorkdays}
                />
              ))}
            </ol>

            {ranking.length > visible.length || showAll ? (
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

        {/* Zasady zwinięte (22.10.2026) — treść bez zmian, dostępna kliknięciem
            także na dotyku (to było powodem przeniesienia jej spod `title`). */}
        <details className="group mt-auto border-t border-border pt-2 text-[11px] text-muted-foreground">
          <summary className="flex min-h-9 cursor-pointer items-center justify-between gap-2 font-semibold text-foreground">
            Zasady: kto na liście, próg i remisy
            <span className="text-primary group-open:hidden">Pokaż ▾</span>
            <span className="hidden text-primary group-open:inline">Zwiń ▴</span>
          </summary>
          <div className="space-y-1 pt-1">
            {copy.populationNote ? <p>{copy.populationNote}</p> : null}
            {/* Wyjaśnienie progu także bez hovera — `title` przy liczbie
                weryfikacji jest nieosiągalny dotykiem (audyt 23.09.2026). */}
            {variant === "recommendations" && ranking.length > 0 ? (
              <p>{raceThresholdNote(ranking[0])}</p>
            ) : null}
            <p>{copy.tieRule}</p>
          </div>
        </details>
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
