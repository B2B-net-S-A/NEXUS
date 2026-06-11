"use client";

/**
 * AI-proposed candidate searches for a job (Champion Profile).
 *
 * The LLM turns the verified Champion Profile into 2-3 concrete searches in
 * the exact shape of the job's "Wyszukaj manualnie" request. The DL reviews
 * each proposal (live result count + filter chips), approves or rejects.
 * Approval materialises a SavedSearch pinned to the job and shared with the
 * team — recruiters activate it in one click from the manual search tab.
 */

import { useMemo } from "react";
import { useMutation, useQueryClient, useQueries } from "@tanstack/react-query";
import {
  CheckCircle2,
  Loader2,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Undo2,
  XCircle,
} from "lucide-react";
import { championApi, type RecommendedSearch } from "@/lib/api";
import {
  candidateSearchApi,
  type CandidateSearchRequest,
} from "@/lib/candidate-search-api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

interface ChampionRecommendedSearchesProps {
  jobId: number;
  searches?: RecommendedSearch[] | null;
  canEdit: boolean;
}

function paramsToRequest(s: RecommendedSearch): CandidateSearchRequest {
  return { ...s.params, page: 1, page_size: 1 } as CandidateSearchRequest;
}

function paramChips(s: RecommendedSearch): string[] {
  const p = s.params;
  const chips: string[] = [];
  for (const skill of p.skills_must ?? []) chips.push(skill);
  if ((p.skills_any ?? []).length > 0) chips.push(`dowolny z: ${p.skills_any!.join(" / ")}`);
  for (const skill of p.skills_none ?? []) chips.push(`NIE ${skill}`);
  for (const phrase of p.q_all ?? []) chips.push(`„${phrase}”`);
  for (const group of p.q_any_groups ?? []) chips.push(`„${group.join("” lub „")}”`);
  for (const phrase of p.q_none ?? []) chips.push(`bez „${phrase}”`);
  if (p.experience_years_min != null || p.experience_years_max != null) {
    chips.push(
      `dośw. ${p.experience_years_min ?? 0}–${p.experience_years_max ?? "∞"} lat`
    );
  }
  for (const city of p.location_cities ?? []) chips.push(city);
  return chips;
}

export function ChampionRecommendedSearches({
  jobId,
  searches,
  canEdit,
}: ChampionRecommendedSearchesProps) {
  const qc = useQueryClient();
  const toast = useToast();
  const items = useMemo(() => searches ?? [], [searches]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
  };

  const generateMutation = useMutation({
    mutationFn: () => championApi.generateRecommendedSearches(jobId),
    onSuccess: invalidate,
    onError: (e: unknown) => {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Nie udało się wygenerować propozycji.";
      toast.showError(detail);
    },
  });

  const decisionMutation = useMutation({
    mutationFn: ({
      searchId,
      action,
    }: {
      searchId: string;
      action: "approve" | "reject" | "reset";
    }) => championApi.decideRecommendedSearch(jobId, searchId, action),
    onSuccess: invalidate,
    onError: () => toast.showError("Nie udało się zapisać decyzji."),
  });

  // Live result count per proposal — same endpoint the manual search uses,
  // so the number matches what the recruiter will see 1:1.
  const countQueries = useQueries({
    queries: items.map((s) => ({
      queryKey: ["recommended-search-count", jobId, s.id],
      queryFn: () =>
        candidateSearchApi.search(paramsToRequest(s)).then((r) => r.total),
      staleTime: 5 * 60 * 1000,
    })),
  });

  return (
    <section
      className="rounded-xl border border-border dark:border-border p-4 bg-card dark:bg-muted"
      data-testid="champion-recommended-searches"
    >
      <header className="flex items-center justify-between mb-2 gap-2">
        <h3 className="text-[11px] uppercase tracking-wide text-purple-700 dark:text-purple-300 font-bold inline-flex items-center gap-1.5">
          <Search className="w-3.5 h-3.5" />
          Rekomendowane wyszukiwania (AI)
        </h3>
        {canEdit && (
          <button
            type="button"
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-60"
            data-testid="generate-recommended-searches"
          >
            {generateMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            {generateMutation.isPending
              ? "Generuję…"
              : items.length > 0
                ? "Wygeneruj ponownie"
                : "Zaproponuj wyszukiwania"}
          </button>
        )}
      </header>
      <p className="text-xs text-muted-foreground mb-3">
        AI zamienia profil championa w konkretne strategie wyszukiwania w bazie.
        Zatwierdzona strategia trafia jako zapisane wyszukiwanie przypięte do
        rekrutacji — każdy rekruter aktywuje ją jednym klikiem w zakładce
        „Wyszukaj manualnie”.
      </p>

      {items.length === 0 && (
        <div className="rounded border border-dashed border-border p-4 text-xs text-muted-foreground text-center">
          Brak propozycji. Uzupełnij profil championa i kliknij „Zaproponuj
          wyszukiwania”.
        </div>
      )}

      <div className="space-y-2">
        {items.map((s, idx) => {
          const count = countQueries[idx]?.data;
          const countLoading = countQueries[idx]?.isLoading;
          return (
            <div
              key={s.id}
              className={cn(
                "rounded-lg border p-3 space-y-2",
                s.status === "approved"
                  ? "border-emerald-300 dark:border-emerald-900 bg-emerald-50/40 dark:bg-emerald-950/20"
                  : s.status === "rejected"
                    ? "border-border bg-muted/40 opacity-70"
                    : "border-border dark:border-border bg-muted/50 dark:bg-card/30"
              )}
              data-testid={`recommended-search-${idx}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-xs font-medium text-foreground flex items-center gap-2 flex-wrap">
                    {s.name}
                    {s.status === "approved" && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-emerald-700 dark:text-emerald-400 font-medium">
                        <CheckCircle2 className="w-3 h-3" /> Zatwierdzone •{" "}
                        {s.decided_by_name}
                      </span>
                    )}
                    {s.status === "rejected" && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground font-medium">
                        <XCircle className="w-3 h-3" /> Odrzucone
                      </span>
                    )}
                  </div>
                  {s.rationale && (
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {s.rationale}
                    </p>
                  )}
                </div>
                <span
                  className="shrink-0 text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
                  data-testid={`recommended-search-count-${idx}`}
                >
                  {countLoading ? (
                    <Loader2 className="w-3 h-3 animate-spin inline" />
                  ) : count != null ? (
                    `${count} kandydatów dziś`
                  ) : (
                    "—"
                  )}
                </span>
              </div>

              <div className="flex flex-wrap gap-1">
                {paramChips(s).map((chip, i) => (
                  <span
                    key={i}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-card dark:bg-muted border border-border text-foreground"
                  >
                    {chip}
                  </span>
                ))}
              </div>

              {canEdit && (
                <div className="flex items-center gap-2 justify-end">
                  {s.status === "proposed" ? (
                    <>
                      <button
                        type="button"
                        onClick={() =>
                          decisionMutation.mutate({
                            searchId: s.id,
                            action: "reject",
                          })
                        }
                        disabled={decisionMutation.isPending}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium border border-border text-muted-foreground hover:bg-muted disabled:opacity-60"
                        data-testid={`reject-search-${idx}`}
                      >
                        <ThumbsDown className="w-3 h-3" /> Odrzuć
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          decisionMutation.mutate({
                            searchId: s.id,
                            action: "approve",
                          })
                        }
                        disabled={decisionMutation.isPending}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium bg-primary hover:bg-primary/90 text-white disabled:opacity-60"
                        data-testid={`approve-search-${idx}`}
                      >
                        <ThumbsUp className="w-3 h-3" /> Zatwierdź dla zespołu
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        decisionMutation.mutate({
                          searchId: s.id,
                          action: "reset",
                        })
                      }
                      disabled={decisionMutation.isPending}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium border border-border text-muted-foreground hover:bg-muted disabled:opacity-60"
                      data-testid={`reset-search-${idx}`}
                    >
                      <Undo2 className="w-3 h-3" /> Cofnij decyzję
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
