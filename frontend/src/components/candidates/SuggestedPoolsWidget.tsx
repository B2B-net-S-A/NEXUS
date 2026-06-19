"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkles, Check } from "lucide-react";
import { api } from "@/lib/api";
import { ConfidenceBadge } from "@/components/ui/ConfidenceBadge";
import { useToast } from "@/components/Toast";

interface SuggestedPool {
  pool_id: number;
  pool_name: string;
  score: number;
  band: "auto" | "suggest";
  already_member: boolean;
}

interface Props {
  candidateId: number;
}

/**
 * SuggestedPoolsWidget — sidebar card for candidate detail showing talent
 * pools ranked by centroid similarity. Rekruter jednym klikiem dodaje
 * kandydata do puli (akceptacja sugestii AI).
 */
export function SuggestedPoolsWidget({ candidateId }: Props) {
  const qc = useQueryClient();
  const { showError } = useToast();
  const [addedIds, setAddedIds] = useState<Set<number>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["suggested-pools", candidateId],
    queryFn: async () => {
      const { data } = await api.get<SuggestedPool[]>(
        `/api/candidates/${candidateId}/suggested-pools`,
      );
      return data;
    },
    staleTime: 60 * 1000,
  });

  const addMutation = useMutation({
    mutationFn: async (poolId: number) => {
      await api.post(`/api/talent-pools/${poolId}/add`, {
        candidate_id: candidateId,
      });
      return poolId;
    },
    onSuccess: (poolId) => {
      setAddedIds((s) => new Set(s).add(poolId));
      qc.invalidateQueries({ queryKey: ["suggested-pools", candidateId] });
      qc.invalidateQueries({ queryKey: ["talent-pools"] });
    },
    onError: (err: unknown) => {
      // Bez tego błąd (np. 403 dla cudzej puli osobistej) ginął po cichu:
      // kandydat się nie dodawał, a UI nie dawał żadnej informacji zwrotnej.
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      )?.response?.data?.detail;
      showError(detail || "Nie udało się dodać kandydata do puli.");
    },
  });

  const suggestions = data ?? [];

  // Declutter: the candidate panel stacks several AI-suggestion cards, so while
  // loading or when there is nothing to suggest (most candidates have no pool
  // embedding yet) render nothing instead of a "brak sugestii" placeholder that
  // only pushes the profile content further down the drawer.
  if (isLoading || suggestions.length === 0) return null;

  return (
    <div className="rounded-xl border border-border dark:border-border bg-card dark:bg-gray-950 p-4 space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium text-foreground dark:text-muted-foreground">
        <Sparkles className="w-4 h-4 text-primary" />
        Sugerowane pule
        <span className="text-[11px] text-muted-foreground font-normal">
          ({suggestions.length})
        </span>
      </div>
      <ul className="space-y-1.5">
        {suggestions.map((s) => {
          const isMember = s.already_member || addedIds.has(s.pool_id);
          return (
            <li
              key={s.pool_id}
              className="flex items-center gap-2 text-xs bg-muted dark:bg-card rounded-lg px-2 py-1.5"
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium text-foreground dark:text-foreground truncate">
                  {s.pool_name}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <ConfidenceBadge
                    score={s.score}
                    band={
                      s.band === "auto"
                        ? "high"
                        : s.score >= 0.73
                          ? "medium"
                          : "low"
                    }
                    withIcon={false}
                  />
                  <span className="text-muted-foreground">
                    {s.band === "auto" ? "auto-add" : "sugestia"}
                  </span>
                </div>
              </div>
              {isMember ? (
                <span className="text-[11px] text-emerald-700 dark:text-emerald-400 flex items-center gap-1">
                  <Check className="w-3 h-3" />w puli
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => addMutation.mutate(s.pool_id)}
                  disabled={addMutation.isPending}
                  className="text-[11px] text-primary hover:text-primary/80 dark:text-primary flex items-center gap-1 disabled:opacity-50"
                >
                  <Plus className="w-3 h-3" /> Dodaj
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
