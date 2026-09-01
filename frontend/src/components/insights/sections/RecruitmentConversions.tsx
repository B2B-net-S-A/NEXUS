"use client";

import { useQuery } from "@tanstack/react-query";
import { Percent, Loader2 } from "lucide-react";
import { insightsApi, type InsightsPeriodParams } from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { count, pct } from "./InsightsFormat";
import { FUNNEL_STAGE_ACCENT, NEUTRAL_ACCENT } from "./InsightsKpiTiles";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Etap, od którego zaczyna się dana konwersja (mianownik ułamka).
 *
 * Kolor konwersji bierzemy z tego etapu, nie z docelowego: „Weryfikacje →
 * Rekomendacje" świeci kolorem weryfikacji, bo to weryfikacje są tu populacją
 * wyjściową i to ich kafel czytelnik ma znaleźć wzrokiem nad tą liczbą.
 *
 * Mapa jest jawna, a nie wyprowadzana z prefiksu klucza (`verified_to_…`):
 * klucz jest kontraktem API, nie schematem nazewniczym, i pierwsza konwersja
 * nazwana inaczej dawałaby cicho zły kolor. Klucz spoza mapy dostaje akcent
 * neutralny — patrz `NEUTRAL_ACCENT`.
 */
const CONVERSION_SOURCE_STAGE: Record<string, string> = {
  verified_to_cv_sent: "verified",
  cv_sent_to_interview: "cv_sent",
  interview_to_hired: "interview",
  verified_to_hired: "verified",
};

/**
 * Konwersje lejka, liczone z TYCH SAMYCH liczników co kafle nad nimi
 * (`InsightsKpiTiles` jedzie na tym samym kluczu react-query).
 *
 * Dwie rzeczy, których ten komponent świadomie NIE robi:
 * - nie przycina wyniku do 100%. Konwersja powyżej stu procent jest sygnałem,
 *   że kolejność etapów się nie trzyma (a w danych z importu się nie trzyma) —
 *   ma być widoczna, nie schowana pod sufitem osi;
 * - nie renderuje zera przy pustym mianowniku. `pct === null` to luka.
 */
export function RecruitmentConversions({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });

  const rows = data?.conversions ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <Percent className="w-5 h-5 text-primary" />
        Efektywność lejka
      </h2>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Efektywność lejka"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        // Gałąź jawna: bez niej sukces z zerem konwersji renderował pustą
        // siatkę, czyli sekcję z samym nagłówkiem — nie do odróżnienia od
        // widoku, który się nie doczytał.
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak konwersji do policzenia w tym oknie.
        </p>
      ) : (
        <div className="space-y-3">
          {rows.map((c) => {
            const accent =
              FUNNEL_STAGE_ACCENT[CONVERSION_SOURCE_STAGE[c.key] ?? ""] ??
              NEUTRAL_ACCENT;
            return (
              <div
                key={c.key}
                role="group"
                aria-label={c.label}
                className={cn(
                  "flex items-center justify-between gap-4 rounded-lg border border-border border-l-4 p-4",
                  accent.border,
                )}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">
                    {c.label}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {c.pct === null
                      ? "Brak mianownika w tym oknie"
                      : `${count(c.numerator)} z ${count(c.denominator)}`}
                  </p>
                </div>
                <p
                  className={cn(
                    "shrink-0 text-3xl font-bold tabular-nums",
                    // Myślnik to brak wyniku — w kolorze metryki udawałby
                    // policzoną wartość.
                    c.pct === null ? "text-muted-foreground" : accent.value,
                  )}
                >
                  {pct(c.pct)}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
