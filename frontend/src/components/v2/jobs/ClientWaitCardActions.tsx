"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { apiErrorMessage } from "@/lib/api-error";
import { clientWaitKey, markClientResponded, workdaysLabel } from "@/lib/api/clientWait";
import type { RejectionReasonOption } from "@/lib/rejection-reasons";

import { ClientReminderDialog } from "./ClientReminderDialog";

/** Klucz powodu „Klient nie odpowiedział” — lustro `rejection_reason_labels`. */
const CLIENT_NO_RESPONSE_REASON = "client_no_response";

export interface ClientWaitCardActionsProps {
  jobId: number;
  candidateId: number;
  candidateName: string;
  workdays: number;
  /** Etap „Odrzucony” szablonu tej rekrutacji. */
  rejectedStageDefId?: number;
  reasons: Pick<RejectionReasonOption, "id" | "name">[];
  /** Ruch na „Rozmowę u klienta”: Tablica otwiera swoje okno. */
  onInterview: () => void;
  /** Odrzucenie przez klienta: Tablica otwiera okno odrzucenia. */
  onRejected: () => void;
  /** Po zapisie: Tablica odświeża karty. */
  onChanged?: () => void;
  readOnly?: boolean;
}

/**
 * Trzy ruchy DL-a na karcie od 6. dnia roboczego ciszy klienta (S-C2, 08.11.2026):
 * przypomnij, klient odpowiedział, zamknij. Jeden przycisk w wierszu ruchu, bo
 * karta ma stałe trzy wiersze. „Zamknij — brak odpowiedzi” idzie przez
 * `usePipelineMoveCore`.
 */
export function ClientWaitCardActions({
  jobId,
  candidateId,
  candidateName,
  workdays,
  rejectedStageDefId,
  reasons,
  onInterview,
  onRejected,
  onChanged,
  readOnly = false,
}: ClientWaitCardActionsProps) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [reminderOpen, setReminderOpen] = useState(false);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const core = usePipelineMoveCore({ jobId });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: clientWaitKey(jobId) });
    onChanged?.();
  };

  const responded = useMutation({
    mutationFn: () => markClientResponded(jobId, candidateId),
    onSuccess: () => {
      refresh();
      showSuccess("Zapisano odpowiedź klienta. Licznik liczy się od nowa.");
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać odpowiedzi klienta.")),
  });

  const closeSilent = async () => {
    const reason = reasons.find((r) => r.name?.trim() === CLIENT_NO_RESPONSE_REASON);
    if (!reason || rejectedStageDefId == null) {
      showError("Brakuje powodu „Klient nie odpowiedział” w tym szablonie. Zgłoś to administratorowi.");
      return;
    }
    const confirmed = await askConfirm({
      title: "Zamknąć proces?",
      description: `${candidateName}: klient nie odpowiada od ${workdaysLabel(workdays)}. Kandydat nie dostanie maila.`,
      confirmLabel: "Zamknij — brak odpowiedzi",
    });
    if (!confirmed) return;
    const outcome = await core.send(
      {
        candidate_id: candidateId,
        job_id: jobId,
        stage_def_id: rejectedStageDefId,
        rejection_reason_id: reason.id,
        ended_by: "client_silent",
        send_rejection_email: false,
      },
      { candidateName },
    );
    if (outcome.ok) refresh();
  };

  if (readOnly) return null;
  // Menu i okna są w portalu, ale ich zdarzenia i tak bąbelkują przez drzewo
  // Reacta do karty, a klik w kartę otwiera panel osoby.
  return (
    <span className="contents" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="client-wait-card-actions"
            className="h-5 shrink-0 px-1.5 text-[10px] font-semibold pointer-coarse:min-h-8"
          >
            Co z klientem?
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setReminderOpen(true)}>Przypomnij klientowi</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Klient odpowiedział</DropdownMenuLabel>
          <DropdownMenuItem onSelect={onInterview}>Zaprosił na rozmowę</DropdownMenuItem>
          <DropdownMenuItem onSelect={onRejected}>Odrzucił</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => responded.mutate()}>Jeszcze się zastanawia</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => void closeSilent()}>Zamknij — brak odpowiedzi</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ClientReminderDialog
        open={reminderOpen}
        onOpenChange={setReminderOpen}
        jobId={jobId}
        candidateIds={[candidateId]}
        onPrepared={refresh}
      />
      {confirmDialog}
      {core.dialogs}
    </span>
  );
}
