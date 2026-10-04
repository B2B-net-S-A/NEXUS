"use client";

/**
 * Wysyłka ruchu karty dla ekranów spoza Tablicy (PR 4 ścieżki kandydata).
 *
 * Warsztaty (screening, CV do klienta, rozmowy), przegląd DL, kolejka Cpro
 * i wysyłka zbiorcza wysyłały ruch własną mutacją i każdy znał inny podzbiór
 * odmów serwera. Ten hook robi to raz, tak jak Tablica (`usePipelineMove`):
 * - ostrzeżenie (czarna lista, weto HM) → okno „Przenieś mimo to” i TEN SAM
 *   ruch z `acknowledge_eligibility`;
 * - brak debriefu → okno rozmowy z kandydatem, po zapisie TEN SAM ruch;
 * - bramka „Zweryfikowany” i QC CV → komunikat + wołający otwiera arkusz / QC;
 * - konflikt wersji → komunikat i odświeżenie tablicy, bez ponowienia;
 * - po udanym ruchu odświeżenie tablicy i „Cofnij wysyłkę” maila odrzucenia.
 *
 * `send` czeka na decyzję w oknie: wynik to ruch zapisany albo odmowa.
 */

import { useCallback, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { useEligibilityWarning } from "@/components/v2/jobs/useEligibilityWarning";
import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";
import {
  classifyMoveError,
  postPipelineMove,
  type CvQcFailure,
  type MoveRefusal,
  type PipelineMovePayload,
  type PipelineMoveResult,
} from "@/lib/pipeline-move-core";
import { invalidateAfterPipelineVersionConflict } from "@/lib/pipeline-version-conflict";
import { announceRejectionEmail } from "@/lib/rejection-email";
import type { VerifiedRequirementsMissing } from "@/lib/verified-gate";

export type MoveSendOutcome =
  | { ok: true; data: PipelineMoveResult }
  | { ok: false; refusal: MoveRefusal };

export interface MoveSendHandlers {
  /** Imię i nazwisko — do okna debriefu i ostrzeżenia w pętli zbiorczej. */
  candidateName?: string;
  /** Ruch zbiorczy: ostrzeżenie pyta o konkretną osobę. */
  eligibilitySubject?: string;
  onCvQcFailed?: (failure: CvQcFailure) => void;
  onVerifiedMissing?: (info: VerifiedRequirementsMissing) => void;
  /** `true` = bez komunikatów i okien — wołający zbiera odmowy sam. */
  silent?: boolean;
  /** Komunikat, gdy serwer nie podał powodu. */
  fallbackMessage?: string;
  /**
   * Błąd spoza znanych odmów (limit czasu, 5xx, inne 4xx) wraca wyjątkiem do
   * wołającego zamiast komunikatu — dla przepływów, które mówią „nie wiadomo,
   * czy ruch się zapisał” po swojemu.
   */
  rethrowOther?: boolean;
}

export interface PipelineMoveCore {
  send: (payload: PipelineMovePayload, handlers?: MoveSendHandlers) => Promise<MoveSendOutcome>;
  /** Okna (ostrzeżenie, debrief) — wyrenderuj raz w drzewie wołającego. */
  dialogs: ReactNode;
}

interface DebriefState {
  eventId: number;
  candidateName: string;
  resolve: (saved: boolean) => void;
}

export function usePipelineMoveCore({ jobId }: { jobId: number }): PipelineMoveCore {
  const queryClient = useQueryClient();
  const { showError, showSuccess, showActionToast } = useToast();
  const { intercept: interceptEligibility, dialog: eligibilityDialog } = useEligibilityWarning();
  const [debrief, setDebrief] = useState<DebriefState | null>(null);
  const sendRef = useRef<PipelineMoveCore["send"] | null>(null);

  const syncBoard = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  }, [queryClient, jobId]);

  const send = useCallback<PipelineMoveCore["send"]>(
    async (payload, handlers = {}) => {
      try {
        const res = await postPipelineMove(payload);
        syncBoard();
        announceRejectionEmail(res.data, {
          requested: payload.send_rejection_email,
          reportSkip: !handlers.silent,
          toast: { showActionToast, showSuccess, showError },
          cancel: (id) => api.post(`/api/rejection-emails/${id}/cancel`),
        });
        return { ok: true, data: res.data ?? {} };
      } catch (error) {
        const refusal = classifyMoveError(error, handlers.fallbackMessage);
        if (refusal.kind === "other" && handlers.rethrowOther) throw error;
        if (handlers.silent) return { ok: false, refusal };

        if (refusal.kind === "eligibility" && !payload.acknowledge_eligibility) {
          return new Promise<MoveSendOutcome>((resolve, reject) => {
            interceptEligibility(
              error,
              () => {
                // Ponowienie z `rethrowOther` może rzucić (limit czasu, 5xx) —
                // obietnica musi się wtedy zakończyć błędem, nie wisieć.
                const retry = sendRef.current?.(
                  { ...payload, acknowledge_eligibility: true },
                  handlers,
                );
                if (retry) retry.then(resolve, reject);
                else resolve({ ok: false, refusal });
              },
              () => {
                syncBoard();
                resolve({ ok: false, refusal });
              },
              handlers.eligibilitySubject,
            );
          });
        }
        if (refusal.kind === "debrief_required") {
          const saved = await new Promise<boolean>((resolve) =>
            setDebrief({
              eventId: refusal.eventId,
              candidateName: handlers.candidateName ?? "kandydat",
              resolve,
            }),
          );
          setDebrief(null);
          if (saved) return (await sendRef.current?.(payload, handlers)) ?? { ok: false, refusal };
          syncBoard();
          return { ok: false, refusal };
        }

        showError(refusal.message);
        if (refusal.kind === "version_conflict") {
          invalidateAfterPipelineVersionConflict(queryClient, jobId, payload.candidate_id);
        } else {
          syncBoard();
        }
        if (refusal.kind === "verified_missing") handlers.onVerifiedMissing?.(refusal.info);
        if (refusal.kind === "cv_qc_failed") handlers.onCvQcFailed?.(refusal.failure);
        return { ok: false, refusal };
      }
    },
    [interceptEligibility, jobId, queryClient, showActionToast, showError, showSuccess, syncBoard],
  );
  sendRef.current = send;

  const dialogs = (
    <>
      {eligibilityDialog}
      {debrief && (
        <DebriefRequiredDialog
          open
          onOpenChange={(open) => {
            if (!open) debrief.resolve(false);
          }}
          eventId={debrief.eventId}
          candidateName={debrief.candidateName}
          jobId={jobId}
          onSaved={() => debrief.resolve(true)}
        />
      )}
    </>
  );

  return { send, dialogs };
}
