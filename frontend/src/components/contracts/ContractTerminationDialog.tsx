"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CONTRACT_TERMINATION_REASONS,
  contractsApi,
  type ContractTerminationReason,
} from "@/lib/api";
import { X } from "lucide-react";

interface Props {
  contractId: number;
  defaultDate?: string;
  onClose: () => void;
  onSuccess: () => void;
}

export function ContractTerminationDialog({
  contractId,
  defaultDate,
  onClose,
  onSuccess,
}: Props) {
  const qc = useQueryClient();
  const [reason, setReason] = useState<ContractTerminationReason>("project_ended");
  const [lessons, setLessons] = useState("");
  const [when, setWhen] = useState(
    defaultDate || new Date().toISOString().slice(0, 10),
  );

  const mut = useMutation({
    mutationFn: () =>
      contractsApi.terminate(contractId, {
        termination_reason: reason,
        termination_lessons: lessons || null,
        terminated_at: when || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contract", contractId] });
      qc.invalidateQueries({ queryKey: ["contracts"] });
      onSuccess();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-lg bg-card dark:bg-card shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border dark:border-border">
          <h2 className="text-base font-semibold">Zakończ współpracę</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <form
          className="p-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            mut.mutate();
          }}
        >
          <label className="block">
            <span className="text-xs text-muted-foreground">Powód zakończenia</span>
            <select
              value={reason}
              onChange={(e) =>
                setReason(e.target.value as ContractTerminationReason)
              }
              className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
            >
              {CONTRACT_TERMINATION_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-muted-foreground">
              Data zakończenia projektu *
            </span>
            {/* required (ticket #5): wyczyszczone pole przechodziło, a backend
                po cichu podstawiał dzisiaj. */}
            <input
              type="date"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              required
              className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
            />
          </label>
          <label className="block">
            <span className="text-xs text-muted-foreground">
              Wnioski / co zrobiliśmy źle albo dobrze (TAC only)
            </span>
            <textarea
              value={lessons}
              onChange={(e) => setLessons(e.target.value)}
              className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
              rows={4}
              placeholder="Np.: klient poprosił o konsultanta na 6 mies., potrzebowali 12 — zbadać wcześniej…"
            />
          </label>
          {mut.isError && (
            <p className="text-xs text-destructive">
              Błąd zapisu. Spróbuj ponownie.
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="text-sm text-muted-foreground hover:underline"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={mut.isPending}
              className="text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-md px-4 py-2"
            >
              {mut.isPending ? "Zapisywanie…" : "Zakończ"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
