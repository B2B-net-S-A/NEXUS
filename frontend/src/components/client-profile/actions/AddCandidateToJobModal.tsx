"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ModalShell } from "./CloseJobAsLostModal";

interface Props {
  jobId: number;
  jobTitle: string;
  clientId: number;
  onClose: () => void;
}

interface CandidateSearchItem {
  id: number;
  name: string;
  lastname: string;
  email?: string | null;
  location?: string | null;
  competence_category?: string | null;
}

export function AddCandidateToJobModal({
  jobId,
  jobTitle,
  clientId,
  onClose,
}: Props) {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");

  // Debounce 300ms to avoid hammering the search on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const { data: candidates = [], isFetching } = useQuery<CandidateSearchItem[]>({
    queryKey: ["client-profile-candidate-search", debouncedQ],
    queryFn: async () => {
      if (!debouncedQ) return [];
      const r = await api.get("/api/candidates", {
        params: { q: debouncedQ, page_size: 15 },
      });
      const payload = r.data;
      return Array.isArray(payload) ? payload : payload?.items ?? [];
    },
    enabled: debouncedQ.length >= 2,
  });

  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const mutation = useMutation({
    mutationFn: (candidateId: number) =>
      api.post(`/api/pipeline/move`, {
        candidate_id: candidateId,
        job_id: jobId,
        stage: "new",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      showSuccess("Kandydat dodany do pipeline");
      onClose();
    },
    onError: () => showError("Nie udało się dodać kandydata"),
  });

  return (
    <ModalShell onClose={onClose} title="Dodaj kandydata do oferty">
      <p className="text-xs text-muted-foreground dark:text-muted-foreground">
        Oferta:{" "}
        <span className="font-medium text-foreground dark:text-muted-foreground">{jobTitle}</span>
      </p>

      <div className="relative">
        <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Szukaj po imieniu, emailu, skillu..."
          className="w-full border border-border dark:border-border dark:bg-muted rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
      </div>

      <div className="max-h-64 overflow-y-auto space-y-1 -mx-1 px-1">
        {debouncedQ.length < 2 ? (
          <p className="text-xs text-muted-foreground text-center py-6">
            Wpisz min. 2 znaki, aby wyszukać kandydata.
          </p>
        ) : isFetching ? (
          <p className="text-xs text-muted-foreground text-center py-6">Szukam...</p>
        ) : candidates.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-6">
            Brak wyników dla „{debouncedQ}".
          </p>
        ) : (
          candidates.map((c) => (
            <button
              key={c.id}
              onClick={() => mutation.mutate(c.id)}
              disabled={mutation.isPending}
              className="w-full text-left px-3 py-2 rounded-lg hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors flex items-center justify-between gap-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground dark:text-muted-foreground truncate">
                  {c.name} {c.lastname}
                </p>
                <p className="text-xs text-muted-foreground dark:text-muted-foreground truncate">
                  {[c.competence_category, c.location, c.email]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </p>
              </div>
              <span className="text-xs text-purple-600 font-semibold flex-shrink-0">
                Dodaj →
              </span>
            </button>
          ))
        )}
      </div>

      <div className="flex justify-end pt-2">
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground dark:text-muted-foreground dark:hover:text-muted-foreground"
        >
          Zamknij
        </button>
      </div>
    </ModalShell>
  );
}
