"use client";

/**
 * „Zamknij rekrutację z powodem" — krok 08 „Umowa" (flow C2, PR 7/7).
 *
 * `POST /api/jobs/{id}/close` istnieje od dawna; jedynym ekranem, który go
 * wołał, był „Zamknij jako przegraną" w profilu klienta. Ta powierzchnia jest
 * potrzebna osobno, bo w kroku 08 powód jest zwykle „Obsadzone przez nas" —
 * czyli WYGRANA. Tamten modal (`client-profile/actions/CloseJobAsLostModal`)
 * ZOSTAJE nietknięty: ma inny kontekst, inne unieważnienia cache'u i jest
 * osadzony w profilu klienta.
 *
 * Słownik powodów jest wspólny (`types/client-profile`), więc dwie
 * powierzchnie nie mogą się rozjechać co do wartości wysyłanych na backend.
 */

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { extractErrorMsg, jobsApi } from "@/lib/api";
import { JOB_CLOSE_REASONS, type JobCloseReason } from "@/types/client-profile";

export interface JobCloseWithReasonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  jobTitle: string;
  clientId?: number | null;
  /**
   * Powód zaproponowany na starcie. Krok 08 podpowiada „Obsadzone przez nas",
   * gdy ktoś jest już zatrudniony — ale wyboru NIE dokonuje za człowieka
   * (automatu zamykania rekrutacji celowo nie ma).
   */
  defaultReason?: JobCloseReason;
  onClosed?: () => void;
}

export function JobCloseWithReasonDialog({
  open,
  onOpenChange,
  jobId,
  jobTitle,
  clientId,
  defaultReason = "filled_by_us",
  onClosed,
}: JobCloseWithReasonDialogProps) {
  const [reason, setReason] = useState<JobCloseReason>(defaultReason);
  const [notes, setNotes] = useState("");
  // Inicjalizator `useState` odpala się raz, przy montażu zakładki — a
  // `defaultReason` („obsadzone przez nas" przy zatrudnionych) zależy od
  // kanbana, który przy wejściu deep-linkiem `?tab=contract` jeszcze się
  // ładuje. Podpowiedź wchodzi więc przy KAŻDYM otwarciu dialogu.
  useEffect(() => {
    if (open) setReason(defaultReason);
  }, [open, defaultReason]);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const mutation = useMutation({
    mutationFn: () => jobsApi.close(jobId, reason, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      if (clientId != null) {
        queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      }
      showSuccess("Rekrutacja zamknięta z powodem.");
      onOpenChange(false);
      onClosed?.();
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się zamknąć rekrutacji"),
  });

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zamknij rekrutację z powodem"
      description={jobTitle}
      footer={
        <>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
          >
            Zamknij rekrutację
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="space-y-1">
          <label
            htmlFor="job-close-reason"
            className="text-xs font-semibold text-foreground"
          >
            Powód zamknięcia
          </label>
          <select
            id="job-close-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value as JobCloseReason)}
            className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:ring-2 focus:ring-primary focus:outline-hidden"
          >
            {JOB_CLOSE_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-muted-foreground">
            Powód zasila raport wygranych i przegranych. Zamknięcie BEZ powodu
            (przez edycję statusu) zostawia go pustym.
          </p>
        </div>

        <div className="space-y-1">
          <label
            htmlFor="job-close-notes"
            className="text-xs font-semibold text-foreground"
          >
            Notatka (opcjonalnie)
          </label>
          <textarea
            id="job-close-notes"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Kontekst — co konkretnie się wydarzyło…"
            className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-sm focus:ring-2 focus:ring-primary focus:outline-hidden"
          />
        </div>

        <p className="text-[11px] text-muted-foreground">
          Zamknięcie nie rusza pipeline'u ani kontraktów — zmienia status
          rekrutacji i zdejmuje ją z alertów terminów oraz digestu dopasowań.
        </p>
      </div>
    </AppModal>
  );
}
