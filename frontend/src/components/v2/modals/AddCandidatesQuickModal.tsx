"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Loader2, UserPlus, X, AlertCircle, Check } from "lucide-react";
import {
  candidateSearchApi,
  proposalsBulkApi,
  type CandidateSearchItem,
  type BulkProposalsResponse,
} from "@/lib/candidate-search-api";
import { useToast } from "@/components/Toast";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { AVATAR_COLORS } from "@/lib/colors";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";
import { assignErrorMessage } from "@/lib/assign-error";

interface Props {
  open: boolean;
  onClose: () => void;
  jobId: number;
  jobTitle: string;
}

function initialsOf(name: string, lastname: string): string {
  const first = (name || "").trim()[0] ?? "";
  const second = (lastname || "").trim()[0] ?? "";
  return (first + second).toUpperCase() || "?";
}

function avatarColorFor(seed: string): string {
  const code = (seed.charCodeAt(0) || 0) + (seed.charCodeAt(1) || 0);
  return AVATAR_COLORS[code % AVATAR_COLORS.length];
}

export function AddCandidatesQuickModal({ open, onClose, jobId, jobTitle }: Props) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [addError, setAddError] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query.trim(), 300);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setSelected(new Set());
      setAddError(null);
    }
  }, [open]);

  const { data, isFetching, isError } = useQuery({
    queryKey: ["add-candidates-quick", jobId, debouncedQuery],
    queryFn: () =>
      candidateSearchApi.search({
        q: debouncedQuery || undefined,
        exclude_in_job_id: jobId,
        sort: debouncedQuery ? "relevance" : "recent",
        page: 1,
        page_size: 25,
      }),
    enabled: open,
    staleTime: 30_000,
  });

  const items: CandidateSearchItem[] = data?.items ?? [];
  const total = data?.total ?? 0;

  const selectedCount = selected.size;
  const allOnPageSelected = useMemo(
    () => items.length > 0 && items.every((c) => selected.has(c.id)),
    [items, selected],
  );

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllOnPage = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        for (const c of items) next.delete(c.id);
      } else {
        for (const c of items) next.add(c.id);
      }
      return next;
    });
  };

  const addMutation = useMutation({
    mutationFn: () => {
      setAddError(null);
      return proposalsBulkApi.add(jobId, {
        candidate_ids: Array.from(selected),
      });
    },
    onSuccess: (result: BulkProposalsResponse) => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      queryClient.invalidateQueries({
        queryKey: ["add-candidates-quick", jobId],
      });
      const skippedSummary =
        result.total_skipped > 0
          ? ` (pominięto ${result.total_skipped})`
          : "";
      if (result.total_added > 0) {
        showSuccess(
          `Dodano ${result.total_added} ${result.total_added === 1 ? "kandydata" : "kandydatów"} do pipeline${skippedSummary}`,
        );
      } else if (result.total_skipped > 0) {
        showError(
          `Nie dodano nikogo — wszyscy zostali pominięci (${result.total_skipped})`,
        );
      }
      setSelected(new Set());
      if (result.total_added > 0) onClose();
    },
    onError: (error: unknown) => {
      const message = assignErrorMessage(error);
      setAddError(message);
      showError(message);
    },
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-card rounded-2xl shadow-xl w-full max-w-2xl max-h-[88vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2 min-w-0">
            <UserPlus className="w-5 h-5 text-primary shrink-0" />
            <div className="min-w-0">
              <h2 className="text-lg font-bold text-foreground truncate">
                Dodaj kandydatów do pipeline
              </h2>
              <p className="text-xs text-muted-foreground truncate">
                Rekrutacja: {jobTitle}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Zamknij"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search input */}
        <div className="px-6 py-3 border-b border-border">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Wpisz imię i nazwisko..."
              className="w-full pl-9 pr-9 py-2.5 border border-border rounded-lg text-sm bg-card focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            />
            {isFetching && (
              <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground animate-spin" />
            )}
          </div>
          <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
            <span>
              {debouncedQuery
                ? `Znaleziono ${total} ${total === 1 ? "wynik" : total >= 2 && total <= 4 ? "wyniki" : "wyników"} (już dodani do tej rekrutacji są ukryci)`
                : `Najnowsi kandydaci — wpisz frazę, by przefiltrować (${total} łącznie)`}
            </span>
            {items.length > 0 && (
              <button
                onClick={toggleAllOnPage}
                className="text-primary hover:underline font-medium"
              >
                {allOnPageSelected ? "Odznacz wszystkich" : "Zaznacz wszystkich"}
              </button>
            )}
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-3 py-2">
          {addError && (
            <div
              role="alert"
              className="flex items-start gap-2 px-4 py-3 m-3 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive"
            >
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">Nie można dodać kandydatów</p>
                <p className="mt-0.5 text-xs">{addError}</p>
              </div>
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-2 px-4 py-3 m-3 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
              <AlertCircle className="w-4 h-4 shrink-0" />
              Błąd wyszukiwania. Spróbuj ponownie.
            </div>
          )}

          {!isError && items.length === 0 && !isFetching && (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
              <Search className="w-10 h-10 opacity-30" />
              <p className="text-sm">
                {debouncedQuery
                  ? "Brak wyników dla tej frazy"
                  : "Wpisz imię lub nazwisko kandydata"}
              </p>
            </div>
          )}

          {items.map((c) => {
            const isSelected = selected.has(c.id);
            const fullName = `${c.name} ${c.lastname}`.trim();
            const initials = initialsOf(c.name, c.lastname);
            const color = avatarColorFor(fullName || String(c.id));
            const candidateLocation = formatCandidateLocation(c.location);
            return (
              <button
                key={c.id}
                onClick={() => toggle(c.id)}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors mb-1",
                  isSelected
                    ? "bg-primary/10 ring-1 ring-primary/30"
                    : "hover:bg-muted",
                )}
                data-testid={`add-candidate-row-${c.id}`}
              >
                <div
                  className={cn(
                    "w-5 h-5 rounded border flex items-center justify-center shrink-0 transition-colors",
                    isSelected
                      ? "bg-primary border-primary"
                      : "border-border bg-card",
                  )}
                >
                  {isSelected && <Check className="w-3.5 h-3.5 text-white" />}
                </div>
                <div
                  className={cn(
                    "w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-xs shrink-0",
                    color,
                  )}
                >
                  {initials}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm text-foreground truncate">
                      {fullName || "—"}
                    </span>
                    {c.is_champion && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                        Champion
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap mt-0.5">
                    {c.competence_category && (
                      <span className="truncate max-w-[180px]">
                        {c.competence_category}
                      </span>
                    )}
                    {candidateLocation && (
                      <span className="truncate max-w-[140px]">
                        · {candidateLocation}
                      </span>
                    )}
                    {c.source && (
                      <span className="truncate max-w-[120px]">· {c.source}</span>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-border bg-muted/30 rounded-b-2xl">
          <span className="text-sm text-muted-foreground">
            {selectedCount > 0
              ? `Zaznaczono ${selectedCount} ${selectedCount === 1 ? "kandydata" : "kandydatów"}`
              : "Wybierz kandydatów do dodania"}
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
            >
              Anuluj
            </button>
            <button
              onClick={() => addMutation.mutate()}
              disabled={selectedCount === 0 || addMutation.isPending}
              className="flex items-center gap-1.5 px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid="add-candidates-confirm"
            >
              {addMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Dodaję...
                </>
              ) : (
                <>
                  <UserPlus className="w-4 h-4" />
                  Dodaj do pipeline
                  {selectedCount > 0 && ` (${selectedCount})`}
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
