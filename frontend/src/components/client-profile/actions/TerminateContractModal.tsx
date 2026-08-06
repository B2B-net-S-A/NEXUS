"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { contractsApi, CONTRACT_TERMINATION_REASONS, type ContractTerminationReason } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ModalShell } from "./CloseJobAsLostModal";

interface Props {
  contractId: number;
  candidateName: string;
  clientId: number;
  onClose: () => void;
  /** Dodatkowa invalidacja wołającej listy (np. contractors-v2) po sukcesie. */
  onTerminated?: () => void;
}

export function TerminateContractModal({
  contractId,
  candidateName,
  clientId,
  onClose,
  onTerminated,
}: Props) {
  const [reason, setReason] = useState<ContractTerminationReason>("project_ended");
  const [lessons, setLessons] = useState("");
  const [terminatedAt, setTerminatedAt] = useState(
    () => new Date().toISOString().slice(0, 10)
  );
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const mutation = useMutation({
    mutationFn: () =>
      contractsApi.terminate(contractId, {
        termination_reason: reason,
        termination_lessons: lessons.trim() || null,
        terminated_at: terminatedAt || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      queryClient.invalidateQueries({ queryKey: ["client-contracts", clientId] });
      // Terminacja synchronizuje też zamówienia kontraktu (ticket #5) —
      // zakładka Zamówienia musi się odświeżyć bez przeładowania.
      queryClient.invalidateQueries({ queryKey: ["dl-orders-grouped", clientId] });
      onTerminated?.();
      showSuccess("Projekt zakończony");
      onClose();
    },
    onError: () => showError("Nie udało się zakończyć kontraktu"),
  });

  return (
    <ModalShell onClose={onClose} title="Zakończ kontrakt">
      <p className="text-xs text-muted-foreground dark:text-muted-foreground">
        Konsultant:{" "}
        <span className="font-medium text-foreground dark:text-muted-foreground">{candidateName}</span>
      </p>

      <div>
        <label className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground block mb-1">
          Powód zakończenia *
        </label>
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value as ContractTerminationReason)}
          className="w-full border border-border dark:border-border dark:bg-muted rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-purple-500"
        >
          {CONTRACT_TERMINATION_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground block mb-1">
          Data zakończenia projektu *
        </label>
        <input
          type="date"
          value={terminatedAt}
          onChange={(e) => setTerminatedAt(e.target.value)}
          required
          aria-label="Data zakończenia projektu"
          className="w-full border border-border dark:border-border dark:bg-muted rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-purple-500"
        />
      </div>

      <div>
        <label className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground block mb-1">
          Lessons learned (TAC-only)
        </label>
        <textarea
          rows={3}
          value={lessons}
          onChange={(e) => setLessons(e.target.value)}
          placeholder="Co zrobilibyśmy inaczej następnym razem..."
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
          onClick={() => {
            // Data jest WYMAGANA (ticket #5) — dotąd wyczyszczone pole
            // przechodziło i backend po cichu podstawiał dzisiaj.
            if (!terminatedAt) {
              showError("Podaj datę zakończenia projektu");
              return;
            }
            mutation.mutate();
          }}
          disabled={mutation.isPending}
          className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50"
        >
          {mutation.isPending ? "Kończę..." : "Zakończ projekt"}
        </button>
      </div>
    </ModalShell>
  );
}
