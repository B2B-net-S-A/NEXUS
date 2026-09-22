"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { formatDate } from "@/lib/utils";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { resolveViewState } from "@/lib/view-state";
import {
  CheckSquare,
  Square,
  Minus,
  Plus,
  Trash2,
  Loader2,
} from "lucide-react";

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

export function ContractOnboardingTab({
  contractId,
  readOnly = false,
}: {
  contractId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [newLabel, setNewLabel] = useState("");

  const { showToast } = useToast();
  const onMutationError = (fallback: string) => (err: unknown) =>
    showToast(apiErrorMessage(err, fallback), "error");

  const onboardingQuery = useQuery<OnboardingItem[]>({
    queryKey: ["contract-onboarding", contractId],
    queryFn: () =>
      api.get(`/api/contracts/${contractId}/onboarding`).then((r) => r.data),
  });

  // Jedno żądanie, lista domyślna po stronie serwera, blokada wiersza
  // kontraktu (audyt FE-04). Dawniej osiem osobnych POST-ów: podwójne
  // kliknięcie dublowało listę, a awaria w środku zostawiała jej połowę.
  const seedMutation = useMutation({
    mutationFn: () =>
      api
        .post<OnboardingItem[]>(`/api/contracts/${contractId}/onboarding/seed`)
        .then((r) => r.data),
    onSuccess: (items) => {
      queryClient.setQueryData(["contract-onboarding", contractId], items);
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] });
    },
    onError: onMutationError("Nie udało się wygenerować listy onboardingowej."),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { label: string; order?: number }) =>
      api.post(`/api/contracts/${contractId}/onboarding`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] });
      setNewLabel("");
    },
    onError: onMutationError("Nie udało się dodać pozycji."),
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
    onError: onMutationError("Nie udało się zmienić statusu pozycji."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      api.delete(`/api/contracts/${contractId}/onboarding/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] }),
    onError: onMutationError("Nie udało się usunąć pozycji."),
  });

  // Blokada synchroniczna: dwa kliknięcia w tej samej klatce (zanim React
  // zdąży wyrenderować `disabled`) nie mogą wysłać dwóch żądań.
  const seedingRef = useRef(false);
  const handleSeed = () => {
    if (seedingRef.current) return;
    seedingRef.current = true;
    seedMutation.mutate(undefined, {
      onSettled: () => {
        seedingRef.current = false;
      },
    });
  };

  const items = onboardingQuery.data ?? [];
  const viewState = resolveViewState({
    isLoading: onboardingQuery.isLoading,
    error: onboardingQuery.error,
    isSuccess: onboardingQuery.isSuccess,
    isEmpty: items.length === 0,
  });
  const isBlocked =
    viewState === "forbidden" ||
    viewState === "not_found" ||
    viewState === "error";
  const doneCount = items.filter((i) => i.status === "done").length;
  const activeCount = items.filter((i) => i.status !== "na").length;
  const pct = activeCount > 0 ? Math.round((doneCount / activeCount) * 100) : 0;

  return (
    <div className="space-y-4">
      {(viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error") && (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void onboardingQuery.refetch()}
        />
      )}

      {viewState === "empty" && !readOnly && (
        <RequireRole roles={["admin", "delivery_lead"]}>
          <div className="bg-primary/10 dark:bg-primary/10 border border-primary/20 dark:border-primary/10 rounded-2xl p-5">
            <p className="text-sm text-primary dark:text-primary mb-3">
              Brak listy onboardingowej. Zacznij od domyślnego zestawu (BHP,
              sprzęt, dostępy, VPN, Slack klient, email, repo) i dostosuj.
            </p>
            <button
              type="button"
              onClick={handleSeed}
              disabled={seedMutation.isPending}
              className="inline-flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              {seedMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Wygeneruj domyślny checklist
            </button>
          </div>
        </RequireRole>
      )}

      {viewState === "empty" && readOnly && (
        <p className="text-sm text-muted-foreground italic">
          Brak listy onboardingowej.
        </p>
      )}

      {items.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-4">
          <div className="flex items-center justify-between mb-3 text-sm">
            <span className="text-muted-foreground dark:text-muted-foreground">
              Postęp: <strong>{doneCount}/{activeCount}</strong>{" "}
              {pct}%
            </span>
          </div>
          <div className="w-full h-2 bg-muted dark:bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      {!readOnly && !isBlocked && (
        <RequireRole roles={["admin", "delivery_lead"]}>
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
              className="flex-1 px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
            />
            <button
              type="submit"
              disabled={createMutation.isPending || !newLabel.trim()}
              className="flex items-center gap-1 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <Plus className="w-4 h-4" /> Dodaj
            </button>
          </form>
        </RequireRole>
      )}

      {viewState === "loading" ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
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
                className={`flex items-center gap-3 bg-card dark:bg-muted rounded-lg px-3 py-2 shadow-xs ${
                  isNa ? "opacity-50" : ""
                }`}
              >
                {!readOnly && (
                  <RequireRole roles={["admin", "delivery_lead"]}>
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
                            ? "text-muted-foreground"
                            : "text-muted-foreground hover:text-primary"
                      }
                      title={`Zmień status (obecnie: ${item.status})`}
                    >
                      <Icon className="w-5 h-5" />
                    </button>
                  </RequireRole>
                )}
                <span
                  className={`flex-1 text-sm ${isDone ? "line-through text-muted-foreground" : ""}`}
                >
                  {item.label}
                </span>
                {item.due_date && (
                  <span className="text-xs text-muted-foreground dark:text-muted-foreground">
                    → {formatDate(item.due_date)}
                  </span>
                )}
                {!readOnly && (
                  <RequireRole roles={["admin", "delivery_lead"]}>
                    <button
                      onClick={() => {
                        if (window.confirm(`Usunąć pozycję "${item.label}"?`)) {
                          deleteMutation.mutate(item.id);
                        }
                      }}
                      className="p-1 rounded hover:bg-destructive/10 dark:hover:bg-red-900/20 text-red-400 hover:text-destructive"
                      title="Usuń"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </RequireRole>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
