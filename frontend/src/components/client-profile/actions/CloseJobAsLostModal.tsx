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
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Oferta:{" "}
        <span className="font-medium text-gray-700 dark:text-gray-200">{jobTitle}</span>
      </p>

      <div>
        <label className="text-xs font-semibold text-gray-600 dark:text-gray-300 block mb-1">
          Powód zamknięcia *
        </label>
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value as JobCloseReason)}
          className="w-full border border-gray-200 dark:border-gray-700 dark:bg-gray-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        >
          {JOB_CLOSE_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs font-semibold text-gray-600 dark:text-gray-300 block mb-1">
          Notatki (opcjonalnie)
        </label>
        <textarea
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Kontekst, co konkretnie się wydarzyło..."
          className="w-full border border-gray-200 dark:border-gray-700 dark:bg-gray-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
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
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export { ModalShell };
