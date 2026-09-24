"use client";

import { useEffect, useMemo, useState } from "react";
import { CompetenceCategoryName } from "@/components/v2/CompetenceCategoryBadge";
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
import { eligibilityBadgeClass } from "@/lib/conflicts";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

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

  const { data, isFetching, isError, isSuccess } = useQuery({
    queryKey: ["add-candidates-quick", jobId, debouncedQuery],
    queryFn: () =>
      candidateSearchApi.search({
        q: debouncedQuery || undefined,
        exclude_in_job_id: jobId,
        sort: debouncedQuery ? "relevance" : "recent",
        page: 1,
        page_size: 25,
        // Runda 2: bez tego pola szybkie dodawanie NIGDY nie dotykało wektorów
        // (backendowy default to "boolean"). Bramka i tak wymaga q, więc
        // przegląd bez frazy zostaje po staremu.
        search_mode: "hybrid",
        // Nazwisko, e-mail albo telefon szukamy DOSŁOWNIE (reguła `text_mode=auto`
        // wspólnej semantyki v2, `candidate_search_predicates.interpret_text`).
        // Bez tego wpisane nazwisko szło po wektorach i obok właściwej osoby
        // wracało ~200 niezwiązanych (test na produkcji 23.09.2026).
        semantics_version: 2,
        text_mode: "auto",
      }),
    enabled: open,
    staleTime: 30_000,
  });

  const items: CandidateSearchItem[] = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;

  const selectedCount = selected.size;
  // Weto hiring managera (`assignment_allowed: false`) blokuje dodanie — taki
  // wiersz jest widoczny z powodem, ale nie da się go zaznaczyć. Konflikt
  // z klientem (czarna lista klienta / NDA / konkurent) od 17.09.2026 jest
  // tylko ostrzeżeniem i zaznaczyć go można.
  const selectableItems = useMemo(
    () => items.filter((c) => c.eligibility?.assignment_allowed !== false),
    [items],
  );
  const allOnPageSelected = useMemo(
    () =>
      selectableItems.length > 0 &&
      selectableItems.every((c) => selected.has(c.id)),
    [selectableItems, selected],
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
        for (const c of selectableItems) next.delete(c.id);
      } else {
        for (const c of selectableItems) next.add(c.id);
      }
      return next;
    });
  };

  const addMutation = useMutation({
    mutationFn: () => {
      setAddError(null);
      return proposalsBulkApi.add(jobId, {
        candidate_ids: Array.from(selected),
        source: "quick_add",
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

  // Rama na `Dialog` (Radix): Escape i klik w tło zamykają, fokus zostaje
  // w oknie, a czytnik ekranu dostaje `role="dialog"` z tytułem. Logika
  // wyszukiwania i dodawania bez zmian.
  return (
    <Dialog open onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent
        size="lg"
        hideClose
        className="rounded-2xl shadow-xl max-h-[88dvh]"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2 min-w-0">
            <UserPlus className="w-5 h-5 text-primary shrink-0" />
            <div className="min-w-0">
              <DialogTitle className="text-lg font-bold text-foreground truncate">
                Dodaj kandydatów do pipeline
              </DialogTitle>
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
            {selectableItems.length > 0 && (
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

          {isSuccess && items.length === 0 && !isFetching && (
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
            const elig = c.eligibility;
            const assignBlocked = elig?.assignment_allowed === false;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => toggle(c.id)}
                disabled={assignBlocked}
                title={assignBlocked ? elig?.reason : undefined}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors mb-1 disabled:cursor-not-allowed disabled:opacity-60",
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
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-warning-muted text-warning-muted-foreground font-medium">
                        Champion
                      </span>
                    )}
                    {elig && (
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                          eligibilityBadgeClass(elig),
                        )}
                        data-testid={`add-candidate-eligibility-${c.id}`}
                      >
                        <AlertCircle className="h-3 w-3 shrink-0" />
                        {elig.reason}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap mt-0.5">
                    {c.competence_category && (
                      <span className="truncate max-w-[180px]">
                        <CompetenceCategoryName slug={c.competence_category} />
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
      </DialogContent>
    </Dialog>
  );
}
