"use client";

/**
 * Przełącznik „Rekrutacja prowadzona w NEXUSIE" (0325, decyzja Artura 17.09.2026).
 *
 * Nocny import Traffita dopisuje etapy każdej rekrutacji z Traffita, a tablica
 * czyta najnowszy wiersz pary kandydat/oferta — ruch zrobiony w NEXUSIE przegrywał
 * nazajutrz. Po przełączeniu (`POST /api/jobs/{id}/manage-in-nexus`) import omija
 * etapy tej rekrutacji i nie nadpisuje jej tytułu, statusu ani daty zamknięcia.
 *
 * Dwie powierzchnie, obie w linii odznak nagłówka rekrutacji:
 * - `ManagedInTraffitNotice` — WYŁĄCZNIE dla rekrutacji z Traffita, które nie
 *   są jeszcze przełączone. Ruch na tablicy jest dozwolony zawsze; plakietka
 *   uprzedza, że nocny import go nadpisze. Do 24.09.2026 był to duży baner
 *   nad Tablicą (~110 px), który spychał kolumny pod ekran.
 * - `ManagedInNexusChip` — w nagłówku, WYŁĄCZNIE dla przełączonych. Powrót do
 *   Traffita tylko admin / Delivery Lead (backend odpowiada 403 pozostałym).
 *
 * Teksty mieszkają tutaj, nie w `@/lib/api` — testy komponentów mockują
 * `@/lib/api` w całości.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { jobsApi, type JobManagedInNexus } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatDate } from "@/lib/utils";

export const MANAGED_IN_NEXUS_LABELS = {
  notice: "Prowadzona w Traffit — ruchy nadpisze nocny import",
  noticeHint:
    "Nocny import z Traffita zapisuje etapy tej rekrutacji — ruch zrobiony tutaj przegra nazajutrz. Przełącz do NEXUSA, żeby import ich nie ruszał.",
  switchButton: "Przełącz do NEXUSA",
  enableTitle: "Przełączyć rekrutację do NEXUSA?",
  enableDescription:
    "Od tej chwili etapy tej rekrutacji zmieniasz tylko w NEXUSIE; import z Traffita ich nie ruszy. Tytuł, status i data zamknięcia także przestaną być pobierane z Traffita.",
  enableConfirm: "Przełącz do NEXUSA",
  cancel: "Anuluj",
  chip: (since: string) => `Prowadzona w NEXUSIE od ${since}`,
  chipRevertHint: "Wróć do Traffita",
  revertTitle: "Wrócić do prowadzenia w Traffitcie?",
  revertDescription:
    "Najbliższy nocny import znów zapisze etapy z Traffita i nadpisze ruchy wykonane w NEXUSIE.",
  revertConfirm: "Wróć do Traffita",
  enabledToast: "Rekrutacja jest teraz prowadzona w NEXUSIE.",
  revertedToast: "Rekrutacja wróciła do Traffita.",
  errorFallback: "Nie udało się zmienić sposobu prowadzenia rekrutacji.",
} as const;

type ManagedJob = Pick<
  JobManagedInNexus,
  "id" | "external_source" | "managed_in_nexus" | "managed_in_nexus_at"
>;

function useManagedMutation(jobId: number, onDone: () => void) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  return useMutation({
    mutationFn: (enabled: boolean) => jobsApi.setManagedInNexus(jobId, enabled),
    onSuccess: (_response, enabled) => {
      // Strona rekrutacji trzyma `id` z `useParams` jako string.
      queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      showSuccess(
        enabled
          ? MANAGED_IN_NEXUS_LABELS.enabledToast
          : MANAGED_IN_NEXUS_LABELS.revertedToast,
      );
      onDone();
    },
    onError: (error) =>
      showError(apiErrorMessage(error, MANAGED_IN_NEXUS_LABELS.errorFallback)),
  });
}

export interface ManagedInTraffitNoticeProps {
  job: ManagedJob;
  /** Czy użytkownik może przełączyć rekrutację (zapis pipeline + edycja rekrutacji). */
  canSwitch: boolean;
}

export function ManagedInTraffitNotice({ job, canSwitch }: ManagedInTraffitNoticeProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const mutation = useManagedMutation(job.id, () => setConfirmOpen(false));

  if (job.external_source !== "traffit" || job.managed_in_nexus) return null;

  return (
    <>
      <span
        data-testid="managed-in-traffit-notice"
        title={MANAGED_IN_NEXUS_LABELS.noticeHint}
        className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-warning/25 bg-warning-muted py-0.5 pl-2.5 pr-1 text-xs font-medium text-warning-muted-foreground"
      >
        <span className="min-w-0 truncate">{MANAGED_IN_NEXUS_LABELS.notice}</span>
        {canSwitch ? (
          <button
            type="button"
            data-testid="managed-in-nexus-switch"
            onClick={() => setConfirmOpen(true)}
            className="shrink-0 rounded-full border border-warning/40 bg-background px-2 py-px text-[11px] font-semibold text-foreground transition-colors hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
          >
            {MANAGED_IN_NEXUS_LABELS.switchButton}
          </button>
        ) : null}
      </span>
      <AppModal
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={MANAGED_IN_NEXUS_LABELS.enableTitle}
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
            >
              {MANAGED_IN_NEXUS_LABELS.cancel}
            </Button>
            <Button
              type="button"
              data-testid="managed-in-nexus-confirm"
              loading={mutation.isPending}
              onClick={() => mutation.mutate(true)}
            >
              {MANAGED_IN_NEXUS_LABELS.enableConfirm}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">
          {MANAGED_IN_NEXUS_LABELS.enableDescription}
        </p>
      </AppModal>
    </>
  );
}

export interface ManagedInNexusChipProps {
  job: ManagedJob;
  /** Admin / Delivery Lead (poza trybem podglądu) — jedyne role, które mogą wrócić do Traffita. */
  canRevert: boolean;
}

export function ManagedInNexusChip({ job, canRevert }: ManagedInNexusChipProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const mutation = useManagedMutation(job.id, () => setConfirmOpen(false));

  if (!job.managed_in_nexus) return null;

  const label = MANAGED_IN_NEXUS_LABELS.chip(formatDate(job.managed_in_nexus_at));

  return (
    <>
      <Badge
        variant="success"
        data-testid="managed-in-nexus-chip"
        title={canRevert ? MANAGED_IN_NEXUS_LABELS.chipRevertHint : undefined}
        role={canRevert ? "button" : undefined}
        tabIndex={canRevert ? 0 : undefined}
        className={canRevert ? "cursor-pointer" : undefined}
        onClick={canRevert ? () => setConfirmOpen(true) : undefined}
        onKeyDown={
          canRevert
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setConfirmOpen(true);
                }
              }
            : undefined
        }
      >
        {label}
      </Badge>
      {canRevert ? (
        <AppModal
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title={MANAGED_IN_NEXUS_LABELS.revertTitle}
          footer={
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirmOpen(false)}
              >
                {MANAGED_IN_NEXUS_LABELS.cancel}
              </Button>
              <Button
                type="button"
                variant="destructive"
                data-testid="managed-in-nexus-revert-confirm"
                loading={mutation.isPending}
                onClick={() => mutation.mutate(false)}
              >
                {MANAGED_IN_NEXUS_LABELS.revertConfirm}
              </Button>
            </>
          }
        >
          <p className="text-sm text-muted-foreground">
            {MANAGED_IN_NEXUS_LABELS.revertDescription}
          </p>
        </AppModal>
      ) : null}
    </>
  );
}
