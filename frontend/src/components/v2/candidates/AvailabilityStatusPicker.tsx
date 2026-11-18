"use client";

/**
 * „Szuka aktywnie” zmieniane jednym kliknięciem (18.11.2026, decyzja Artura,
 * makiety: https://claude.ai/artifact/Lk3LqawjifGhmJwn59Wrg3).
 *
 * Pigułka przy nazwisku (lista kandydatów, profil) otwiera okienko „Czy szuka
 * pracy?” z czterema wyborami zapisywanymi od razu. Wcześniej ta sama zmiana
 * wymagała „Do propozycji” → „Edytuj” → ołówek przy „Dostępność”, a rekruter
 * pytał na czacie, jak to zrobić. Uprawnienie jak w tamtym oknie: fakty
 * profilu + zapis kandydata (PATCH /api/candidates/{id}); bez niego zostaje
 * sama pigułka. Wybór człowieka zostaje — nocny odczyt notatek zmienia tylko
 * „Nie ustalono” (`notes_profile_fill`).
 */

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AvailabilityPill } from "@/components/ds/AvailabilityPill";
import { useToast } from "@/components/Toast";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { useCapability } from "@/hooks/useCapability";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

export const AVAILABILITY_STATUS_CHOICES = [
  { value: "actively_looking", hint: "dzwonimy z projektami" },
  { value: "open_to_offers", hint: "tylko z dobrym projektem" },
  { value: "not_looking", hint: "nie dzwonimy z nowymi projektami" },
  { value: "unknown", hint: "bez pigułki przy nazwisku" },
] as const;

const UNKNOWN_LABEL = "Nie ustalono";

export function AvailabilityStatusPicker({
  candidateId,
  status,
  appearance = "pill",
}: {
  candidateId: number;
  status: string | null | undefined;
  /** `pill` — profil; `text` — wiersz listy. */
  appearance?: "pill" | "text";
}) {
  // Oba hooki zawsze — `&&` pominąłby drugi przy pierwszym `false`.
  const canManageFacts = useCapability("candidate.profile_fact.manage");
  const canWriteCandidate = useCapability("candidate.write");
  const canEdit = canManageFacts && canWriteCandidate;
  const [open, setOpen] = React.useState(false);
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const current = status && status !== "unknown" ? status : "unknown";

  const mutation = useMutation({
    mutationFn: (next: string) =>
      api.patch(`/api/candidates/${candidateId}`, { availability_status: next }),
    onSuccess: () => {
      invalidateCandidateMutation(queryClient, candidateId, "edit");
      setOpen(false);
      showSuccess("Zapisano, czy szuka pracy");
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać, czy szuka pracy")),
  });

  if (!canEdit) {
    return current === "unknown" ? null : <AvailabilityPill status={current} appearance={appearance} />;
  }

  // Lista: klik w pigułkę nie otwiera profilu (wiersz ma własny klik).
  const stop = (event: React.SyntheticEvent) => event.stopPropagation();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={stop}
          aria-label="Czy szuka pracy — zmień"
          className="inline-flex min-w-0 shrink-0 items-center rounded-full hover:underline focus-visible:outline-2 focus-visible:outline-ring"
        >
          {current === "unknown" ? (
            <span
              className={cn(
                "inline-flex items-center whitespace-nowrap font-semibold text-muted-foreground",
                appearance === "pill"
                  ? "h-5 rounded-full border border-dashed border-border px-2 text-[11px]"
                  : "text-xs",
              )}
            >
              + Czy szuka?
            </span>
          ) : (
            <AvailabilityPill status={current} appearance={appearance} />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-96" onClick={stop}>
        <p className="text-sm font-semibold text-foreground">Czy szuka pracy?</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          Zapisuje się od razu. Po tym polu filtruje lista kandydatów.
        </p>
        <div role="radiogroup" aria-label="Czy szuka pracy" className="mt-3 grid gap-1">
          {AVAILABILITY_STATUS_CHOICES.map((choice) => {
            const active = choice.value === current;
            return (
              <button
                key={choice.value}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={mutation.isPending}
                onClick={() => (active ? setOpen(false) : mutation.mutate(choice.value))}
                className={cn(
                  "flex min-h-11 items-center justify-between gap-3 rounded-lg border px-3 text-left text-sm",
                  active
                    ? "border-primary bg-primary/5 font-semibold text-foreground"
                    : "border-border hover:bg-muted",
                )}
              >
                {choice.value === "unknown" ? (
                  <span className="text-xs font-semibold text-muted-foreground">{UNKNOWN_LABEL}</span>
                ) : (
                  <AvailabilityPill status={choice.value} appearance="text" className="pointer-events-none" />
                )}
                <span className="text-xs font-normal text-muted-foreground">{choice.hint}</span>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
