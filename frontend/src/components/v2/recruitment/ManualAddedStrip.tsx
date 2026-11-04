"use client";

/**
 * „Dodani teraz” nad listą „Szukaj ręcznie” (15.10.2026). Dodana osoba znika
 * z wyników (lista ukrywa osoby już w rekrutacji), więc „Cofnij” i „Pasuje też
 * do” stoją tu — jak przy wierszu w pozostałych zakładkach okna „Kandydaci do
 * dodania” (`AddCandidatesPanel`, `useSearchBaseTab`).
 *
 * „Cofnij” = usunięcie z rekrutacji z `quick_undo` (15 min, `useUndoWindow`
 * u właściciela listy osób); po cofnięciu osoba wraca do wyników.
 */

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";

import type { CandidatesListAddedPerson } from "@/components/v2/pages/CandidatesListV2";
import { candidatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { jobProposalsKeys } from "@/lib/job-proposals-api";

import { alsoFitsSlot } from "./also-fits-block";
import { useAlsoFitsJobs } from "./useAlsoFitsJobs";

/**
 * Ile najnowszych osób widać od razu — pasek stoi nad listą wyników, a ekran
 * docelowy to laptop 1280 × 720; „Pasuje też do” hak sprawdza sam też 3 ostatnie.
 */
export const MANUAL_ADDED_VISIBLE = 3;

export interface ManualAddedStripProps {
  jobId: number;
  /** Dodani w tym oknie, w kolejności dodania. */
  people: readonly CandidatesListAddedPerson[];
  /** Osoby, którym minęło okno „Cofnij”. */
  undoExpired: ReadonlySet<number>;
  readOnly: boolean;
  /** „Cofnij” się udało — wiersz ma zniknąć. */
  onUndone: (candidateId: number) => void;
}

export function ManualAddedStrip({ jobId, people, undoExpired, readOnly, onUndone }: ManualAddedStripProps) {
  const queryClient = useQueryClient();
  const [undoing, setUndoing] = useState<ReadonlySet<number>>(() => new Set());
  const [errors, setErrors] = useState<ReadonlyMap<number, string>>(() => new Map());
  const [expanded, setExpanded] = useState(false);
  // Kolejność dodania — hak sam sprawdza tylko ostatnie osoby.
  const addedIds = useMemo(() => new Set(people.map((p) => p.candidateId)), [people]);
  const alsoFits = useAlsoFitsJobs({ fromJobId: jobId, addedIds, enabled: !readOnly });

  if (people.length === 0) return null;

  const setError = (candidateId: number, message: string | null) =>
    setErrors((prev) => {
      if (!message && !prev.has(candidateId)) return prev;
      const next = new Map(prev);
      if (message) next.set(candidateId, message);
      else next.delete(candidateId);
      return next;
    });

  const undo = async (candidateId: number) => {
    if (readOnly) return;
    setUndoing((prev) => new Set([...prev, candidateId]));
    setError(candidateId, null);
    try {
      await candidatesApi.removeFromRecruitment(candidateId, jobId, { quickUndo: true });
    } catch (error) {
      setError(candidateId, apiErrorMessage(error, "Nie udało się cofnąć dodania."));
      setUndoing((prev) => new Set([...prev].filter((id) => id !== candidateId)));
      return;
    }
    await Promise.allSettled([
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] }),
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] }),
      queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] }),
      queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) }),
    ]);
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
    // Lista „Szukaj ręcznie” — osoba spoza rekrutacji wraca do wyników.
    void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
    setUndoing((prev) => new Set([...prev].filter((id) => id !== candidateId)));
    onUndone(candidateId);
  };

  return (
    <section aria-label="Dodani teraz" className="space-y-1.5" data-testid="manual-added-strip">
      <h3 className="text-xs font-semibold text-foreground">Dodani teraz ({people.length})</h3>
      <ul className="divide-y divide-border rounded-md border border-border">
        {/* Najnowsi u góry — tam, gdzie patrzy osoba, która właśnie dodała. */}
        {[...people].reverse().slice(0, expanded ? undefined : MANUAL_ADDED_VISIBLE).map(({ candidateId, fullName }) => {
          const busy = undoing.has(candidateId);
          const error = errors.get(candidateId);
          return (
            <li key={candidateId} data-candidate-id={candidateId} className="min-w-0 bg-success-muted/40 px-3 py-2">
              <p className="truncate text-sm font-medium text-foreground" title={fullName}>
                {fullName}
              </p>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-1 text-xs font-medium text-success-muted-foreground">
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                Dodano do „Nowych” · rezerwacja 12 h
                {!readOnly && !undoExpired.has(candidateId) ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <button
                      type="button"
                      onClick={() => void undo(candidateId)}
                      disabled={busy}
                      aria-label={`Cofnij dodanie: ${fullName}`}
                      className="font-semibold text-primary hover:underline disabled:opacity-60"
                    >
                      {busy ? "Cofam…" : "Cofnij"}
                    </button>
                  </>
                ) : null}
              </p>
              {error ? (
                <p role="alert" className="mt-1 text-xs text-destructive-muted-foreground">
                  {error}
                </p>
              ) : null}
              {alsoFitsSlot(alsoFits, candidateId, fullName, readOnly)}
            </li>
          );
        })}
      </ul>
      {people.length > MANUAL_ADDED_VISIBLE ? (
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          className="text-xs font-semibold text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkich (${people.length})`}
        </button>
      ) : null}
    </section>
  );
}
