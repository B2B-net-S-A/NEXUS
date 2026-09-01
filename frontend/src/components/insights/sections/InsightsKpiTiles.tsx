"use client";

import { useQuery } from "@tanstack/react-query";
import { Info, Loader2 } from "lucide-react";
import {
  insightsApi,
  type FunnelStage,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { count } from "./InsightsFormat";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Akcent koloru przypisany ETAPOWI lejka, nie komponentowi.
 *
 * Kontrakt, który ta mapa utrzymuje: ta sama metryka ma ten sam kolor
 * wszędzie na zakładce. Kafel „Weryfikacje" i konwersja „Weryfikacje →
 * Rekomendacje" muszą świecić tym samym akcentem, bo inaczej czytelnik szuka
 * związku między liczbami po treści, a nie po wyglądzie — a to jest dokładnie
 * ta praca, którą kolor miał wykonać za niego. Dlatego mapa jest eksportowana
 * i `RecruitmentConversions` bierze kolor STĄD, zamiast trzymać własną kopię,
 * która rozjedzie się przy pierwszej zmianie palety.
 *
 * Dlaczego trzy pozycje sięgają po `-muted-foreground`, a fiolet po `chart-5`:
 * `--warning` (50% L) i `--success` (45% L) w motywie jasnym mają wobec białej
 * karty kontrast ~2,2:1, czyli poniżej progu 3:1 nawet dla dużego tekstu —
 * wielka liczba w tych kolorach byłaby nieczytelna. Warianty
 * `-muted-foreground` są ciemne w jasnym motywie i jasne w ciemnym, więc
 * działają w obie strony. Fiolet nie ma takiego wariantu w palecie, a sam
 * `--chart-5` przechodzi w obu motywach, więc idzie bez nakładki.
 */
export interface FunnelAccent {
  /** Lewa krawędź kafla — dekoracja, więc wolno tu użyć wersji nasyconej. */
  border: string;
  /** Kolor DUŻEJ liczby / procentu — musi przejść kontrast w obu motywach. */
  value: string;
}

export const FUNNEL_STAGE_ACCENT: Record<string, FunnelAccent> = {
  verified: { border: "border-l-info", value: "text-info-muted-foreground" },
  cv_sent: { border: "border-l-chart-5", value: "text-chart-5" },
  interview: {
    border: "border-l-warning",
    value: "text-warning-muted-foreground",
  },
  hired: {
    border: "border-l-success",
    value: "text-success-muted-foreground",
  },
};

/**
 * Akcent dla etapu spoza mapy. Backend może dołożyć konwersję albo etap bez
 * pytania frontu o zdanie — wtedy kafel ma być neutralny, a nie przypadkowo
 * pożyczyć kolor sąsiada i zasugerować związek, którego nie ma.
 */
export const NEUTRAL_ACCENT: FunnelAccent = {
  border: "border-l-border",
  value: "text-foreground",
};

/**
 * Cztery liczby, od których zaczyna się rozmowa o rekrutacji — te same, które
 * DynaReporter trzyma na samej górze zakładki.
 *
 * `headline` to nazwa, którą zespół wypowiada na głos (żargon z DR).
 * Podpisem jest jednak `stage.label` z SERWERA, bo tylko on mówi, co ta liczba
 * naprawdę zlicza: pierwsze wejście na dany etap w oknie. Dwa różne słowniki
 * w jednym kaflu są celowe — nagłówek nazywa metrykę, podpis ją definiuje.
 */
const KPI_TILES: { stage: string; headline: string }[] = [
  { stage: "verified", headline: "Weryfikacje" },
  { stage: "cv_sent", headline: "Rekomendacje" },
  { stage: "interview", headline: "Interviews" },
  { stage: "hired", headline: "Placements" },
];

interface TileView {
  stage: string;
  headline: string;
  accent: FunnelAccent;
  /** Sformatowana liczba albo „—”. */
  value: string;
  /** Podpis pod liczbą — co ta liczba zlicza albo dlaczego jej nie ma. */
  caption: string;
  /** Etap nieodnotowywany — gwiazdka + przypis pod kaflami. */
  unrecorded: boolean;
}

/**
 * Zamień etapy z odpowiedzi na cztery kafle.
 *
 * Dwie sytuacje, w których kafel POKAZUJE MYŚLNIK zamiast zera:
 *
 * 1. `mapped_from_traffit === false` przy zerowym liczniku — import z Traffita
 *    nie zna tego etapu, więc zero jest brakiem ewidencji, nie obserwacją.
 *    Wielka „0" na kaflu podsumowania czyta się jak werdykt („nikogo nie
 *    zatrudniliśmy"), a to nieprawda: my tego po prostu nie zapisujemy.
 *    Liczbę większą od zera renderujemy normalnie — to realna, choć niepełna
 *    obserwacja, i schowanie jej byłoby drugim kłamstwem.
 * 2. Serwer nie zwrócił etapu w ogóle. Podstawienie zera zamieniłoby zmianę
 *    kontraktu API w cichy, wiarygodnie wyglądający wynik.
 */
export function buildKpiTiles(stages: FunnelStage[]): TileView[] {
  const byStage = new Map(stages.map((s) => [s.stage, s]));
  return KPI_TILES.map(({ stage, headline }) => {
    const accent = FUNNEL_STAGE_ACCENT[stage] ?? NEUTRAL_ACCENT;
    const found = byStage.get(stage);
    if (!found) {
      return {
        stage,
        headline,
        accent,
        value: "—",
        caption: "Serwer nie zwrócił tego etapu w tym oknie",
        unrecorded: false,
      };
    }
    const unrecorded = !found.mapped_from_traffit && found.count === 0;
    return {
      stage,
      headline,
      accent,
      value: unrecorded ? "—" : count(found.count),
      caption: unrecorded
        ? "Nie odnotowujemy tego etapu — import z Traffita go nie zna"
        : `Pierwsze wejście na etap „${found.label}"`,
      unrecorded,
    };
  });
}

/**
 * Podsumowanie lejka — cztery duże kafle nad samym lejkiem (układ DR).
 *
 * Świadomie NIE robi własnego zapytania: klucz react-query jest ten sam, co
 * w `RecruitmentFunnel` i `RecruitmentConversions`, więc trzy sekcje jadą na
 * JEDNEJ odpowiedzi. Osobny endpoint dla kafli oznaczałby czwartą definicję
 * lejka w tej aplikacji i pierwszą okazję, żeby kafel przestał zgadzać się
 * z paskiem pod nim.
 */
export function InsightsKpiTiles({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });

  const stages = data?.stages ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: stages.length === 0,
  });

  if (viewState === "loading") {
    return (
      <div className="bg-card flex items-center justify-center rounded-xl border border-border py-10 shadow-xs">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isBlockingViewState(viewState)) {
    return (
      <div className="bg-card rounded-xl border border-border p-6 shadow-xs">
        <SectionError
          label="Podsumowanie lejka"
          error={error}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (viewState === "empty") {
    return (
      <div className="bg-card rounded-xl border border-border p-6 text-center text-sm text-muted-foreground shadow-xs">
        Brak kamieni milowych w wybranym okresie.
      </div>
    );
  }

  const tiles = buildKpiTiles(stages);
  const hasUnrecorded = tiles.some((t) => t.unrecorded);

  return (
    <section aria-label="Podsumowanie lejka" className="space-y-2">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {tiles.map((tile) => (
          <div
            key={tile.stage}
            // `role="group"` z etykietą: nagłówek kafla („Placements") wraca
            // niżej w etykietach konwersji, więc bez nazwanej grupy ani
            // czytnik ekranu, ani test nie powiążą liczby z jej metryką.
            role="group"
            aria-label={tile.headline}
            className={cn(
              "bg-card rounded-xl border border-border border-l-4 p-5 shadow-xs",
              tile.accent.border,
            )}
          >
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {tile.headline}
              {tile.unrecorded && " *"}
            </p>
            <p
              className={cn(
                "mt-2 text-4xl font-bold tabular-nums",
                // Myślnik jest brakiem danych, nie wynikiem — nie wolno mu
                // świecić kolorem metryki, bo z drugiego końca sali wygląda
                // wtedy dokładnie jak liczba.
                tile.value === "—"
                  ? "text-muted-foreground"
                  : tile.accent.value,
              )}
            >
              {tile.value}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{tile.caption}</p>
          </div>
        ))}
      </div>

      {hasUnrecorded && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            * Etap oznaczony gwiazdką nie jest u nas odnotowywany — import z
            Traffita go nie przenosi. To brak ewidencji, nie zero.
          </span>
        </p>
      )}
    </section>
  );
}
