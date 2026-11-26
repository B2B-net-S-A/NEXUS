"use client";

import { useCallback, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import type { JobHold } from "@/lib/job-hold";
import {
  invalidateAfterHoldChange,
  jobHoldKey,
  reportJobHold,
  resumeJobHold,
} from "@/lib/job-hold-api";

export interface JobHoldActions {
  /** „Wznów rekrutację” — pyta (`useConfirmV2`), potem `DELETE …/hold`. */
  resume: () => Promise<void>;
  resuming: boolean;
  /** „Zgłoś DL-owi” / „Zapytaj DL” — `POST …/hold/report`; `true` = zapisane. */
  report: (note: string) => Promise<boolean>;
  reporting: boolean;
  /** Okno potwierdzenia — wyrenderuj raz u wołającego. */
  confirmDialog: ReactNode;
}

/** Wspólne akcje pasa nad Tablicą i dymka pigułki statusu. */
export function useJobHoldActions(jobId: number, hold: JobHold | null | undefined): JobHoldActions {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();

  const resumeMutation = useMutation({
    mutationFn: () => resumeJobHold(jobId),
    onSuccess: (next) => {
      invalidateAfterHoldChange(queryClient, jobId, next);
      toast.showSuccess("Rekrutacja wznowiona — wraca do „Szukamy”.");
    },
    onError: (error) => {
      toast.showError(apiErrorMessage(error, "Nie udało się wznowić rekrutacji."));
      void queryClient.invalidateQueries({ queryKey: jobHoldKey(jobId) });
    },
  });

  const reportMutation = useMutation({
    mutationFn: (note: string) => reportJobHold(jobId, note.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: jobHoldKey(jobId) });
      toast.showSuccess("Zgłoszone. DL dostał pytanie i odpowie jednym kliknięciem.");
    },
    onError: (error) => {
      toast.showError(apiErrorMessage(error, "Nie udało się wysłać zgłoszenia do DL."));
      // 409 `already_reported`: druga karta już zgłosiła — pokaż to samo co tam.
      void queryClient.invalidateQueries({ queryKey: jobHoldKey(jobId) });
    },
  });

  const recipients = hold?.recipients.length ?? 0;
  const resume = useCallback(async () => {
    const ok = await askConfirm({
      title: "Wznowić rekrutację?",
      description:
        recipients > 0
          ? `Wraca do „Szukamy”. ${recipients} ${recipients === 1 ? "rekruter dostanie" : "rekruterów dostanie"} wiadomość, że można dzwonić z tym projektem.`
          : "Wraca do „Szukamy” — rekruterzy znowu mogą proponować ten projekt.",
      confirmLabel: "Wznów rekrutację",
      cancelLabel: "Anuluj",
    });
    if (ok) await resumeMutation.mutateAsync().catch(() => undefined);
  }, [askConfirm, recipients, resumeMutation]);

  const report = useCallback(
    async (note: string) => {
      try {
        await reportMutation.mutateAsync(note);
        return true;
      } catch {
        return false;
      }
    },
    [reportMutation],
  );

  return {
    resume,
    resuming: resumeMutation.isPending,
    report,
    reporting: reportMutation.isPending,
    confirmDialog,
  };
}
