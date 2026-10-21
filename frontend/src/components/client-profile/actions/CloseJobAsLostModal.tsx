"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { activeCardsWarningFrom, type ActiveCardsWarning } from "@/lib/job-close";
import { useToast } from "@/components/Toast";
import {
  CloseReasonFields,
  closeReasonReady,
  type CloseReasonValue,
} from "@/components/v2/jobs/CloseReasonFields";
import { ActiveCardsNotice } from "@/components/v2/jobs/JobCloseWithReasonDialog";
import type { JobCloseReason } from "@/types/client-profile";

interface Props {
  jobId: number;
  jobTitle: string;
  clientId: number;
  onClose: () => void;
}

/**
 * „Zamknij rekrutację” z profilu klienta (Projekty). Do 21.10.2026 „Zamknij
 * jako przegraną” — każde zamknięcie stąd liczyło się jako przegrana, także
 * duplikat. Teraz te same trzy grupy co na stronie rekrutacji
 * (`CloseReasonFields`); start na „Przegraliśmy”, bo stąd zamyka się zwykle
 * rekrutacje bez wyniku.
 */
export function CloseJobAsLostModal({ jobId, jobTitle, clientId, onClose }: Props) {
  const [value, setValue] = useState<CloseReasonValue>({
    reason: "competitor",
    notes: "",
    duplicateOfJobId: null,
  });
  // Osoby w toku: pierwsze zamknięcie serwer zatrzymuje ostrzeżeniem.
  const [activeCards, setActiveCards] = useState<ActiveCardsWarning | null>(null);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const mutation = useMutation({
    mutationFn: () =>
      jobsApi.close(
        jobId,
        value.reason as JobCloseReason,
        value.notes,
        activeCards != null,
        value.duplicateOfJobId,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      queryClient.invalidateQueries({ queryKey: ["client-jobs", clientId] });
      showSuccess("Rekrutacja zamknięta");
      onClose();
    },
    onError: (e) => {
      const warning = activeCardsWarningFrom(e);
      if (warning) {
        setActiveCards(warning);
        return;
      }
      showError(apiErrorMessage(e, "Nie udało się zamknąć rekrutacji"));
    },
  });

  return (
    <ModalShell onClose={onClose} title="Zamknij rekrutację">
      <p className="text-xs text-muted-foreground">
        Rekrutacja: <span className="font-medium text-foreground">{jobTitle}</span>
      </p>

      {activeCards ? <ActiveCardsNotice warning={activeCards} /> : null}

      <CloseReasonFields value={value} onChange={setValue} jobId={jobId} clientId={clientId} />

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          Anuluj
        </button>
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !closeReasonReady(value)}
          className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {mutation.isPending ? "Zamykam..." : activeCards ? "Zamknij mimo to" : "Zamknij rekrutację"}
        </button>
      </div>
    </ModalShell>
  );
}

// ── Reusable shell ────────────────────────────────────────────────────────────

function ModalShell({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onClose}
    >
      {/* `p-4` na tle: na telefonie okno nie dotyka krawędzi ekranu.
          Limit wysokości + przewijanie: „Zakończ kontrakt" ma listę powodów,
          datę i notatkę — z klawiaturą przycisk potwierdzenia był poza ekranem. */}
      <div
        className="bg-card dark:bg-muted rounded-2xl shadow-xl w-full max-w-md max-h-[90dvh] overflow-y-auto p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground dark:text-foreground">{title}</h3>
          <button
            onClick={onClose}
            aria-label="Zamknij"
            className="hit-area text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export { ModalShell };
