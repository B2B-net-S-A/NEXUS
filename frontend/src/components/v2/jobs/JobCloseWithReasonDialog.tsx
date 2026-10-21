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
import { activeCardsWarningFrom, type ActiveCardsWarning } from "@/lib/job-close";
import { isSelectableCloseReason } from "@/lib/job-close-reasons";
import type { JobCloseReason } from "@/types/client-profile";

import {
  CloseReasonFields,
  closeReasonReady,
  type CloseReasonValue,
} from "./CloseReasonFields";

export interface JobCloseWithReasonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  jobTitle: string;
  clientId?: number | null;
  /**
   * Powód zaproponowany na starcie. Krok 08 podpowiada „Obsadzone przez nas",
   * gdy ktoś jest już zatrudniony — ale wyboru NIE dokonuje za człowieka
   * (automatu zamykania rekrutacji celowo nie ma). `null` = nic nie wybrane.
   */
  defaultReason?: JobCloseReason | null;
  /**
   * `change` (21.10.2026): „Zmień powód zamknięcia” zamkniętej rekrutacji —
   * `PATCH /close-reason`, data zamknięcia zostaje. `initial` = obecny wybór;
   * „Inny” i brak powodu startują bez zaznaczenia.
   */
  mode?: "close" | "change";
  initial?: { reason: JobCloseReason | null; notes: string | null; duplicateOfJobId: number | null };
  onClosed?: () => void;
}

function startValue(
  mode: "close" | "change",
  defaultReason: JobCloseReason | null,
  initial: JobCloseWithReasonDialogProps["initial"],
): CloseReasonValue {
  if (mode === "change" && initial) {
    return {
      reason: isSelectableCloseReason(initial.reason) ? initial.reason : null,
      notes: initial.notes ?? "",
      duplicateOfJobId: initial.duplicateOfJobId,
    };
  }
  return {
    reason: isSelectableCloseReason(defaultReason) ? defaultReason : null,
    notes: "",
    duplicateOfJobId: null,
  };
}

export function JobCloseWithReasonDialog({
  open,
  onOpenChange,
  jobId,
  jobTitle,
  clientId,
  defaultReason = "filled_by_us",
  mode = "close",
  initial,
  onClosed,
}: JobCloseWithReasonDialogProps) {
  const [value, setValue] = useState<CloseReasonValue>(() =>
    startValue(mode, defaultReason, initial),
  );
  // Inicjalizator `useState` odpala się raz, przy montażu zakładki — a
  // `defaultReason` („obsadzone przez nas" przy zatrudnionych) zależy od
  // kanbana, który przy wejściu deep-linkiem `?tab=contract` jeszcze się
  // ładuje. Podpowiedź wchodzi więc przy KAŻDYM otwarciu dialogu.
  // Osoby w toku (13.10.2026): serwer zatrzymuje pierwsze zamknięcie
  // ostrzeżeniem, drugie idzie z potwierdzeniem.
  const [activeCards, setActiveCards] = useState<ActiveCardsWarning | null>(null);
  useEffect(() => {
    if (open) {
      setValue(startValue(mode, defaultReason, initial));
      setActiveCards(null);
    }
    // `initial` to nowy obiekt przy każdym renderze rodzica — wybór startowy
    // liczy się przy otwarciu, nie przy każdej zmianie referencji.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultReason, mode]);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const mutation = useMutation({
    mutationFn: async (): Promise<void> => {
      const reason = value.reason as JobCloseReason;
      if (mode === "change") {
        await jobsApi.changeCloseReason(jobId, {
          reason,
          notes: value.notes,
          duplicateOfJobId: value.duplicateOfJobId,
        });
        return;
      }
      await jobsApi.close(jobId, reason, value.notes, activeCards != null, value.duplicateOfJobId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      if (clientId != null) {
        queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      }
      showSuccess(mode === "change" ? "Powód zamknięcia zmieniony." : "Rekrutacja zamknięta.");
      onOpenChange(false);
      onClosed?.();
    },
    onError: (e) => {
      const warning = activeCardsWarningFrom(e);
      if (warning) {
        setActiveCards(warning);
        return;
      }
      showError(
        extractErrorMsg(e) ||
          (mode === "change" ? "Nie udało się zmienić powodu" : "Nie udało się zamknąć rekrutacji"),
      );
    },
  });

  const ready = closeReasonReady(value);

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={mode === "change" ? "Zmień powód zamknięcia" : "Zamknij rekrutację"}
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
            disabled={!ready}
          >
            {mode === "change"
              ? "Zapisz powód"
              : activeCards
                ? "Zamknij mimo to"
                : "Zamknij rekrutację"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {activeCards ? <ActiveCardsNotice warning={activeCards} /> : null}
        <CloseReasonFields value={value} onChange={setValue} jobId={jobId} clientId={clientId} />
        {mode === "close" ? (
          <p className="text-[11px] text-muted-foreground">
            Zamknięcie nie rusza pipeline'u ani kontraktów — zmienia status
            rekrutacji i zdejmuje ją z alertów terminów oraz digestu dopasowań.
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            Data zamknięcia zostaje. Zmiana trafia do historii rekrutacji; rozliczony
            kwartał Ligi się nie zmienia.
          </p>
        )}
      </div>
    </AppModal>
  );
}

/** Osoby w toku przed zamknięciem — wspólne dla obu okien zamykania. */
export function ActiveCardsNotice({ warning }: { warning: ActiveCardsWarning }) {
  return (
    <div
      role="alert"
      className="space-y-1 rounded-lg border border-warning/40 bg-warning-muted p-3 text-sm text-warning-muted-foreground"
    >
      <p>{warning.message}</p>
      {warning.breakdown ? <p className="font-medium">{warning.breakdown}</p> : null}
      <p>Odrzuć albo przenieś te osoby przed zamknięciem, albo zamknij mimo to.</p>
    </div>
  );
}
