"use client";

import { useEffect, useState } from "react";

export interface RejectionReasonOption {
  id: number;
  name: string;
  category: "rejected" | "withdrawn";
}

interface Props {
  open: boolean;
  terminalType: "rejected" | "withdrawn";
  reasons: RejectionReasonOption[];
  onClose: () => void;
  onConfirm: (reasonId: number, notes?: string) => void;
}

export function RejectionReasonModal({
  open,
  terminalType,
  reasons,
  onClose,
  onConfirm,
}: Props) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (open) {
      setSelectedId(null);
      setNotes("");
    }
  }, [open]);

  if (!open) return null;

  const filtered = reasons.filter((r) => r.category === terminalType);

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="rejection-modal-title"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="rejection-modal-title"
          className="text-lg font-semibold text-gray-900 dark:text-gray-100"
        >
          {terminalType === "rejected" ? "Powód odrzucenia" : "Powód wycofania"}
        </h2>
        <p className="text-sm text-gray-500">
          Wybierz powód — zostanie zapisany razem z tym etapem.
        </p>

        {filtered.length === 0 ? (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
            Ten proces nie ma jeszcze zdefiniowanych powodów{" "}
            {terminalType === "rejected" ? "odrzucenia" : "wycofania"}. Dodaj je
            w ustawieniach procesu rekrutacyjnego.
          </p>
        ) : (
          <ul className="max-h-60 overflow-y-auto space-y-1">
            {filtered.map((r) => (
              <li key={r.id}>
                <label className="flex items-center gap-2 p-2 rounded cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50">
                  <input
                    type="radio"
                    name="reason"
                    checked={selectedId === r.id}
                    onChange={() => setSelectedId(r.id)}
                  />
                  <span className="text-sm text-gray-800 dark:text-gray-200">{r.name}</span>
                </label>
              </li>
            ))}
          </ul>
        )}

        <label className="block text-sm text-gray-700 dark:text-gray-300">
          Notatka (opcjonalnie)
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-1 text-sm"
          />
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            Anuluj
          </button>
          <button
            onClick={() => {
              if (selectedId !== null) onConfirm(selectedId, notes || undefined);
            }}
            disabled={selectedId === null}
            className="px-3 py-1.5 rounded-md bg-red-600 text-white text-sm hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Potwierdź
          </button>
        </div>
      </div>
    </div>
  );
}
