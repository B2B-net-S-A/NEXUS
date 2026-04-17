"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { formatDate } from "@/lib/utils";
import {
  CheckSquare,
  Square,
  Minus,
  Plus,
  Trash2,
  Loader2,
} from "lucide-react";

const DEFAULT_ITEMS = [
  "BHP — szkolenie",
  "Podpisana umowa",
  "Sprzęt (laptop)",
  "Dostępy do VPN klienta",
  "Konto w Slacku klienta",
  "Onboarding u PM klienta",
  "Email firmowy",
  "Dostęp do repozytorium",
];

interface OnboardingItem {
  id: number;
  contract_id: number;
  label: string;
  status: "pending" | "done" | "na";
  assigned_to: number | null;
  due_date: string | null;
  notes: string | null;
  order: number;
  created_at: string;
  updated_at: string;
}

const STATUS_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  pending: Square,
  done: CheckSquare,
  na: Minus,
};

const NEXT_STATUS: Record<string, "pending" | "done" | "na"> = {
  pending: "done",
  done: "na",
  na: "pending",
};

export function ContractOnboardingTab({ contractId }: { contractId: number }) {
  const queryClient = useQueryClient();
  const [newLabel, setNewLabel] = useState("");

  const { data, isLoading } = useQuery<OnboardingItem[]>({
    queryKey: ["contract-onboarding", contractId],
    queryFn: () =>
      api.get(`/api/contracts/${contractId}/onboarding`).then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { label: string; order?: number }) =>
      api.post(`/api/contracts/${contractId}/onboarding`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] });
      setNewLabel("");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: Record<string, unknown>;
    }) => api.patch(`/api/contracts/${contractId}/onboarding/${id}`, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      api.delete(`/api/contracts/${contractId}/onboarding/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] }),
  });

  const handleSeed = () => {
    DEFAULT_ITEMS.forEach((label, idx) => {
      createMutation.mutate({ label, order: idx });
    });
  };

  const items = data ?? [];
  const doneCount = items.filter((i) => i.status === "done").length;
  const activeCount = items.filter((i) => i.status !== "na").length;
  const pct = activeCount > 0 ? Math.round((doneCount / activeCount) * 100) : 0;

  return (
    <div className="space-y-4">
      {items.length === 0 && !isLoading && (
        <RequireRole roles={["admin", "delivery_lead", "tac"]}>
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-900 rounded-2xl p-5">
            <p className="text-sm text-blue-900 dark:text-blue-100 mb-3">
              Brak listy onboardingowej. Zacznij od domyślnego zestawu (BHP,
              sprzęt, dostępy, VPN, Slack klient, email, repo) i dostosuj.
            </p>
            <button
              onClick={handleSeed}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              Wygeneruj domyślny checklist
            </button>
          </div>
        </RequireRole>
      )}

      {items.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-4">
          <div className="flex items-center justify-between mb-3 text-sm">
            <span className="text-gray-500 dark:text-gray-400">
              Postęp: <strong>{doneCount}/{activeCount}</strong>{" "}
              {pct}%
            </span>
          </div>
          <div className="w-full h-2 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      <RequireRole roles={["admin", "delivery_lead", "tac"]}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const label = newLabel.trim();
            if (label) {
              createMutation.mutate({ label, order: items.length });
            }
          }}
          className="flex gap-2"
        >
          <input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="Dodaj pozycję (np. 'Karta dostępu do biura')"
            className="flex-1 px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700"
          />
          <button
            type="submit"
            disabled={createMutation.isPending || !newLabel.trim()}
            className="flex items-center gap-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-3 py-2 rounded-lg text-sm font-medium"
          >
            <Plus className="w-4 h-4" /> Dodaj
          </button>
        </form>
      </RequireRole>

      {isLoading ? (
        <div className="text-sm text-gray-500 flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie…
        </div>
      ) : items.length === 0 ? null : (
        <ul className="space-y-1">
          {items.map((item) => {
            const Icon = STATUS_ICON[item.status] ?? Square;
            const isDone = item.status === "done";
            const isNa = item.status === "na";
            return (
              <li
                key={item.id}
                className={`flex items-center gap-3 bg-white dark:bg-gray-800 rounded-lg px-3 py-2 shadow-sm ${
                  isNa ? "opacity-50" : ""
                }`}
              >
                <RequireRole roles={["admin", "delivery_lead", "tac"]}>
                  <button
                    onClick={() =>
                      updateMutation.mutate({
                        id: item.id,
                        payload: { status: NEXT_STATUS[item.status] },
                      })
                    }
                    className={
                      isDone
                        ? "text-emerald-600"
                        : isNa
                          ? "text-gray-400"
                          : "text-gray-400 hover:text-blue-600"
                    }
                    title={`Zmień status (obecnie: ${item.status})`}
                  >
                    <Icon className="w-5 h-5" />
                  </button>
                </RequireRole>
                <span
                  className={`flex-1 text-sm ${isDone ? "line-through text-gray-500" : ""}`}
                >
                  {item.label}
                </span>
                {item.due_date && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    → {formatDate(item.due_date)}
                  </span>
                )}
                <RequireRole roles={["admin", "delivery_lead", "tac"]}>
                  <button
                    onClick={() => {
                      if (window.confirm(`Usunąć pozycję "${item.label}"?`)) {
                        deleteMutation.mutate(item.id);
                      }
                    }}
                    className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-400 hover:text-red-600"
                    title="Usuń"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </RequireRole>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
