"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { JOB_CLOSE_REASONS, type JobCloseReason } from "@/types/client-profile";

interface Props {
  jobId: number;
  jobTitle: string;
  clientId: number;
  onClose: () => void;
}

export function CloseJobAsLostModal({ jobId, jobTitle, clientId, onClose }: Props) {
  const [reason, setReason] = useState<JobCloseReason>("budget");
  const [notes, setNotes] = useState("");
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/api/jobs/${jobId}/close`, {
        reason,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      queryClient.invalidateQueries({ queryKey: ["client-jobs", clientId] });
      showSuccess("Oferta zamknięta jako przegrana");
      onClose();
    },
    onError: () => showError("Nie udało się zamknąć oferty"),
  });

  return (
    <ModalShell onClose={onClose} title="Zamknij jako przegraną">
      <p className="text-xs text-muted-foreground dark:text-muted-foreground">
        Oferta:{" "}
        <span className="font-medium text-foreground dark:text-muted-foreground">{jobTitle}</span>
      </p>

      <div>
        <label className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground block mb-1">
          Powód zamknięcia *
        </label>
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value as JobCloseReason)}
          className="w-full border border-border dark:border-border dark:bg-muted rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-purple-500"
        >
          {JOB_CLOSE_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground block mb-1">
          Notatki (opcjonalnie)
        </label>
        <textarea
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Kontekst, co konkretnie się wydarzyło..."
          className="w-full border border-border dark:border-border dark:bg-muted rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-purple-500 resize-none"
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground dark:text-muted-foreground dark:hover:text-muted-foreground"
        >
          Anuluj
        </button>
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50"
        >
          {mutation.isPending ? "Zamykam..." : "Zamknij jako lost"}
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="bg-card dark:bg-muted rounded-2xl shadow-xl w-full max-w-md p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground dark:text-foreground">{title}</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground">
            <X className="w-4 h-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export { ModalShell };
