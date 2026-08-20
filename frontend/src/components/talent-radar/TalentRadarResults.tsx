"use client";

/**
 * Prezentacja wyników radaru — bez stanu, bez wywołań API.
 *
 * Wydzielone z `TalentRadarWorkspace` nie dla samego porządku, tylko dlatego, że
 * publiczny harness `/preview/talent-radar` musi renderować dokładnie to, co
 * widzi rekruter, a jednocześnie NIE wolno mu wołać API (patrz komentarz przy
 * `PUBLIC_PATHS` w middleware.ts). Gdyby harness składał własną, podobną
 * wersję listy, weryfikowałby wygląd czegoś, czego nikt nie używa.
 */

import Link from "next/link";
import { SearchX, TriangleAlert, Users } from "lucide-react";

import {
  EmptyState,
  MatchCard,
  MatchList,
  type MatchReason,
} from "@/components/ds";
import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { encodeTalentRadarBackRef } from "@/lib/url-filters";
import { cn } from "@/lib/utils";
import { httpStatusFromError, resolveViewState } from "@/lib/view-state";
import type {
  TalentRadarMeta,
  TalentRadarResult,
} from "@/lib/talent-radar-api";

function candidateName(result: TalentRadarResult): string {
  const c = result.candidate;
  if (!c) return `Kandydat #${result.candidate_id}`;
  const full = [c.name, c.lastname].filter(Boolean).join(" ").trim();
  return full || `Kandydat #${result.candidate_id}`;
}

/** Podpis pod nazwiskiem — kategoria, staż, lokalizacja; tylko to, co jest. */
function candidateRole(result: TalentRadarResult): string | undefined {
  const c = result.candidate;
  if (!c) return undefined;
  const bits: string[] = [];
  if (c.competence_category) bits.push(c.competence_category);
  if (typeof c.years_it_experience === "number") {
    bits.push(`${c.years_it_experience} lat w IT`);
  }
  if (c.location) bits.push(c.location);
  return bits.join(" · ") || undefined;
}

/**
 * Powody: trafione i brakujące wymagania twarde, potem trochę miękkich.
 * Warstwa wynagrodzenia świadomie pominięta — radar nie ma widełek, więc jej
 * `status: "not_applicable"` nie niesie nic dla czytającego.
 */
function matchReasons(result: TalentRadarResult): MatchReason[] {
  return [
    ...result.matching_must.map((label) => ({ label, ok: true })),
    ...result.gap_must.map((label) => ({ label: `brak: ${label}`, ok: false })),
    ...result.matching_nice.slice(0, 3).map((label) => ({ label, ok: true })),
  ].slice(0, 8);
}

export interface TalentRadarResultsProps {
  /** `null` = jeszcze nie szukano (inny stan niż „zero wyników"). */
  meta: TalentRadarMeta | null;
  results: TalentRadarResult[];
  pending: boolean;
  /**
   * Błąd zapytania — `null`, gdy nic nie padło.
   *
   * Bez tego workspace po awarii robił `setResponse(null)` i pokazywał błąd
   * WYŁĄCZNIE w toaście, który po chwili znika. Zostawał ekran startowy
   * „Zacznij od wklejenia requestu" — czyli komunikat, że rekruter jeszcze nic
   * nie zrobił, w sytuacji, w której zrobił i to serwer nie odpowiedział.
   */
  error?: unknown;
  /** Ponowienie wyszukiwania — pokazywane tylko przy awarii serwera. */
  onRetry?: () => void;
  /**
   * Czy pokazać „Otwórz profil". Radar jest dostępny dla KAŻDEJ roli
   * (decyzja 19.08), ale pełny profil kandydata pozostaje za bramkami
   * modułu kandydatów — rola bez `nav.candidates` dostawałaby po kliknięciu
   * przekierowanie/403, więc workspace przekazuje tu capability zamiast
   * renderować martwy przycisk. Default `true`, żeby publiczny harness
   * `/preview/talent-radar` (bez auth store) dalej pokrywał ten wariant.
   */
  canOpenProfile?: boolean;
}

export function TalentRadarResults({
  meta,
  results,
  pending,
  error = null,
  onRetry,
  canOpenProfile = true,
}: TalentRadarResultsProps) {
  // Kolejność jak w kanonie widoków (`lib/view-state.ts`): awaria PRZED pustym
  // i przed stanem startowym. 403 rozdzielone od 5xx, bo to dwa różne zdania:
  // „nie wolno ci" kontra „nie udało się".
  if (error) {
    const state = resolveViewState({ isLoading: false, isError: true, error });
    const forbidden = state === "forbidden";
    return (
      <Alert
        variant="error"
        icon={TriangleAlert}
        title={
          forbidden
            ? "Brak uprawnień do tego wyszukiwania"
            : "Wyszukiwanie nie doszło do skutku"
        }
        description={
          <>
            {forbidden
              ? "Twoja rola nie ma dostępu do tego klienta. To nie znaczy, że nikt nie pasuje — znaczy, że nie wolno nam pokazać."
              : httpStatusFromError(error) === undefined
                ? "Nie udało się połączyć z serwerem. Sprawdź internet lub VPN i spróbuj ponownie."
                : "Serwer nie odpowiedział na zapytanie. To nie znaczy, że nikt nie pasuje — znaczy, że nie wiemy."}
            {!forbidden && onRetry ? (
              <>
                {" "}
                <button
                  type="button"
                  onClick={onRetry}
                  className="font-medium underline underline-offset-2"
                >
                  Spróbuj ponownie
                </button>
              </>
            ) : null}
          </>
        }
      />
    );
  }

  if (meta?.degraded) {
    return (
      <Alert
        variant="error"
        icon={TriangleAlert}
        title="Wyszukiwanie nie doszło do skutku"
        description={
          <>
            Warstwa semantyczna jest niedostępna
            {meta.reason ? ` (${meta.reason})` : ""}. To nie znaczy, że nikt nie
            pasuje — znaczy, że nie wiemy. Spróbuj ponownie za chwilę.
          </>
        }
      />
    );
  }

  if (!meta) {
    if (pending) return null;
    return (
      <EmptyState
        icon={Users}
        title="Zacznij od wklejenia requestu"
        description="Wybierz klienta i wklej treść — nie zakładamy rekrutacji, to tylko przeszukanie bazy."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Przejrzeliśmy <strong>{meta.pool_size.toLocaleString("pl-PL")}</strong>{" "}
        kandydatów, z czego{" "}
        <strong>{meta.eligible_size.toLocaleString("pl-PL")}</strong> wolno
        zaproponować temu klientowi. Pokazujemy{" "}
        <strong>{meta.returned.toLocaleString("pl-PL")}</strong> najlepiej
        dopasowanych.
        {(meta.hidden?.over_budget ?? 0) > 0 && (
          <>
            {" "}
            <span
              className="font-medium text-amber-700 dark:text-amber-400"
              data-testid="tr-hidden-over-budget"
            >
              Ukryto {meta.hidden!.over_budget!.toLocaleString("pl-PL")} poza
              budżetem.
            </span>
          </>
        )}
        {(meta.hidden?.remote_only ?? 0) > 0 && (
          <>
            {" "}
            <span
              className="font-medium text-amber-700 dark:text-amber-400"
              data-testid="tr-hidden-remote-only"
            >
              Ukryto {meta.hidden!.remote_only!.toLocaleString("pl-PL")}{" "}
              „wyłącznie zdalnych”.
            </span>
          </>
        )}
      </p>

      {results.length > 0 ? (
        <MatchList layout="grid">
          {results.map((result) => (
            <MatchCard
              key={result.candidate_id}
              name={candidateName(result)}
              role={candidateRole(result)}
              score={result.total}
              reasons={matchReasons(result)}
              actions={
                canOpenProfile ? (
                  // Celowo `Link` ze stylami `buttonVariants`, nie `<Button
                  // asChild>`: Button renderuje slot na spinner obok dziecka,
                  // więc Radix Slot dostaje dwoje dzieci i wywala się w
                  // runtime („Slot failed to slot onto its children"). Ten sam
                  // obchód co w HelpMaterialsSection.tsx.
                  //
                  // `from=talent-radar`: profil pokaże „Wróć do Talent Radaru"
                  // zamiast „Wróć do kandydatów", a radar odtworzy wyszukiwanie
                  // ze snapshotu (lib/talent-radar-session.ts) — bez tego powrót
                  // kasował wyniki i formularz.
                  <Link
                    href={`/candidates/${result.candidate_id}?${encodeTalentRadarBackRef().toString()}`}
                    className={cn(
                      buttonVariants({ variant: "outline", size: "sm" }),
                    )}
                  >
                    Otwórz profil
                  </Link>
                ) : undefined
              }
            />
          ))}
        </MatchList>
      ) : (
        <EmptyState
          icon={SearchX}
          title="Nikt nie przekroczył progu dopasowania"
          description={
            meta.eligible_size === 0
              ? "Żaden kandydat z puli nie może zostać zaproponowany temu klientowi — blokują to blacklisty, NDA lub weto."
              : "Spróbuj opisać rolę szerzej albo mniej sztywno — im więcej konkretów technologicznych, tym lepszy sygnał."
          }
        />
      )}
    </div>
  );
}
