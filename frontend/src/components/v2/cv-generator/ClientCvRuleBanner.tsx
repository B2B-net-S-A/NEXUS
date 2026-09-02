"use client";

/**
 * Stan reguł CV wybranego klienta — hook + baner.
 *
 * Trzy stany, świadomie rozróżnione (ten sam wzorzec co `client_policy` przy
 * odczycie PDF zamówień w `NewContractorOrderDialog`):
 *
 * * klient niewybrany → nic nie renderujemy (nie ma o czym informować);
 * * klient wybrany, brak ZATWIERDZONYCH reguł → ostrzeżenie, że plik dostanie
 *   nazwę ogólną. Bez tego niewłączona reguła jest NIEWIDOCZNA: generacja
 *   „działa", a jedynym objawem jest plik nazwany wzorem, którego klient nie
 *   akceptuje — wykryty dopiero przez odbiorcę CV;
 * * reguły obowiązują → co dokładnie zadziała i jak będzie się nazywał plik.
 *
 * Awaria pobrania ma WŁASNĄ gałąź. Cisza po błędzie czytałaby się jak „ten
 * klient nie ma reguł", czyli jak fakt, a nie jak nieudane sprawdzenie.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileCheck2, Info } from "lucide-react";

import api from "@/lib/api";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";
import type { ClientCvRule } from "@/lib/cv-rules";

const MODE_LABEL: Record<string, string> = Object.fromEntries(
  CV_CONTENT_MODES.map((m) => [m.value, m.label]),
);

export type { ClientCvRule } from "@/lib/cv-rules";

export function useClientCvRule(clientId: number | null | undefined) {
  return useQuery({
    queryKey: ["client-cv-rule", clientId ?? null],
    enabled: !!clientId,
    queryFn: async () =>
      (await api.get<ClientCvRule>(`/api/clients/${clientId}/cv-rule`)).data,
    staleTime: 60 * 1000,
  });
}

interface Props {
  clientId: number | null | undefined;
  rule: ClientCvRule | undefined;
  isLoading: boolean;
  isError: boolean;
}

export function ClientCvRuleBanner({
  clientId,
  rule,
  isLoading,
  isError,
}: Props) {
  if (!clientId) return null;

  if (isLoading) {
    return (
      <p className="text-xs text-muted-foreground" role="status">
        Sprawdzam reguły CV tego klienta…
      </p>
    );
  }

  if (isError) {
    return (
      <div
        role="status"
        className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
      >
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Nie udało się sprawdzić reguł CV tego klienta. Zweryfikuj nazwę pliku
          i język przed wysyłką.
        </span>
      </div>
    );
  }

  const active = rule?.is_active === true;

  if (!active) {
    return (
      <div
        role="status"
        className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs text-amber-700 dark:text-amber-400"
      >
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Ten klient nie ma jeszcze zatwierdzonych reguł CV — nazwa pliku
          i&nbsp;język będą ogólne. Sprawdź je przed wysyłką.
        </span>
      </div>
    );
  }

  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-2 text-xs"
    >
      <FileCheck2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
      <span className="space-y-0.5">
        <span className="block">
          Zastosowano reguły klienta
          {rule?.client_policy ? `: ${rule.client_policy}` : ""}.
        </span>
        {rule?.filename_preview ? (
          <span className="block text-muted-foreground">
            Przykładowa nazwa pliku:{" "}
            <span className="font-mono">{rule.filename_preview}</span>
          </span>
        ) : null}
        {rule?.requires_en_copy ? (
          <span className="block text-muted-foreground">
            Ten klient oczekuje CV po polsku <strong>oraz</strong> po angielsku
            {rule.auto_second_language
              ? " — druga wersja wygeneruje się automatycznie po pierwszej."
              : " — pamiętaj o drugiej wersji."}
          </span>
        ) : null}
        {rule?.content_mode && rule.content_mode_locked ? (
          <span className="block text-muted-foreground">
            Tryb obróbki treści: {MODE_LABEL[rule.content_mode] ?? rule.content_mode}{" "}
            — ustalony przez Delivery Leada.
          </span>
        ) : null}
        {rule?.requires_rodo_consent_block ? (
          <span className="block text-muted-foreground">
            Wymagany zrzut ekranu maila ze zgodą kandydata na dole CV —
            uzupełnij dokument po pobraniu.
          </span>
        ) : null}
        {rule?.notes?.trim() ? (
          // Notatka Delivery Leada trafia do CZŁOWIEKA składającego CV, nie do
          // modelu — to jedyne miejsce, w którym „pozostałe standardy klienta"
          // w ogóle docierają do rekrutera; do 09.2026 były widoczne wyłącznie
          // w oknie edycji klienta.
          <details className="text-muted-foreground">
            <summary className="cursor-pointer">
              Standardy klienta (notatka Delivery Leada)
            </summary>
            <span className="mt-1 block whitespace-pre-line">{rule.notes}</span>
          </details>
        ) : null}
        {rule?.generator_instructions?.trim() ? (
          // Rekruter ma wiedzieć, CZYM model kształtował dokument — inaczej
          // pominięta sekcja albo skrócony opis wygląda jak błąd generatora,
          // a nie jak spełnione wymaganie klienta.
          <details className="text-muted-foreground">
            <summary className="cursor-pointer">
              Instrukcje dla generatora AI (zastosowane do treści)
            </summary>
            <span className="mt-1 block whitespace-pre-line">
              {rule.generator_instructions}
            </span>
          </details>
        ) : null}
      </span>
    </div>
  );
}
