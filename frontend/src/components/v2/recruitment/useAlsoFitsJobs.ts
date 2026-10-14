"use client";

/**
 * „Pasuje też do” (14.10.2026, decyzje Artura D1–D2): po „+ Dodaj” w oknie
 * „Kandydaci do dodania” pytamy, do jakich jeszcze rekrutacji w pracy pasuje ta
 * osoba, i dajemy „+ Dodaj” do każdej z nich. Dodanie to zwykłe dodanie do
 * tamtej rekrutacji (`proposals/bulk`, źródło `also_fits`): „Nowi”, rezerwacja
 * 12 h dla dodającego, „Cofnij” przez 15 min, dzwonek do rekrutera tamtej
 * rekrutacji (serwer).
 *
 * Hak żyje w zakładkach okna (`AddCandidatesPanel`, `useSearchBaseTab`), nie
 * w `PickList` — lista jest prezentacyjna i renderuje się bez QueryClient.
 */

import { useCallback, useMemo, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { alsoFitsApi, alsoFitsKeys, type AlsoFitsJob } from "@/lib/also-fits-api";
import { candidatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { proposalsBulkApi, type BulkSkippedRow } from "@/lib/candidate-search-api";
import { jobProposalsKeys } from "@/lib/job-proposals-api";

import { useUndoWindow } from "./useUndoWindow";

/** Stan dodania osoby do jednej z podpowiedzianych rekrutacji. */
export type ElsewhereState = "adding" | "added" | "undoing";

export interface AlsoFitsRowModel {
  /** `unavailable` = serwer nie mógł sprawdzić (awaria wyszukiwania). */
  status: "loading" | "error" | "unavailable" | "ok";
  jobs: AlsoFitsJob[];
  stateOf: (jobId: number) => ElsewhereState | undefined;
  /** Odmowa serwera przy dodaniu do tej rekrutacji (zamknięta karta, weto…). */
  errorOf: (jobId: number) => string | undefined;
  undoable: (jobId: number) => boolean;
}

export interface AlsoFits {
  /** Model bloku pod wierszem osoby dodanej w tym oknie; `null` = nie dotyczy. */
  forCandidate: (candidateId: number) => AlsoFitsRowModel | null;
  add: (candidateId: number, jobIds: readonly number[]) => void;
  undo: (candidateId: number, jobId: number) => void;
  retry: (candidateId: number) => void;
}

const STALE_MS = 5 * 60 * 1000;

const pairKey = (candidateId: number, jobId: number) => `${candidateId}:${jobId}`;

/** Komunikat odmowy z odpowiedzi `proposals/bulk` — etykieta serwera, gdy jest. */
export function elsewhereRefusal(row: BulkSkippedRow | undefined): string {
  if (row?.reason_label) return row.reason_label;
  switch (row?.reason) {
    case "already_in_job":
      return "Ta osoba jest już w tej rekrutacji.";
    case "closed_in_job":
      return "Ta osoba ma zamkniętą kartę w tej rekrutacji — przywróć ją na jej Tablicy.";
    case "rejected_by_hiring_manager":
      return "Hiring manager tej rekrutacji odrzucił już tę osobę.";
    case "blacklisted":
      return "Osoba jest na czarnej liście.";
    default:
      return "Nie dodano do tej rekrutacji.";
  }
}

export function useAlsoFitsJobs({
  fromJobId,
  addedIds,
  enabled,
}: {
  fromJobId: number;
  /** Osoby dodane w tym oknie (kolejność bez znaczenia). */
  addedIds: ReadonlySet<number>;
  enabled: boolean;
}): AlsoFits {
  const queryClient = useQueryClient();
  const ids = useMemo(() => [...addedIds].sort((a, b) => a - b), [addedIds]);
  const results = useQueries({
    queries: ids.map((candidateId) => ({
      queryKey: alsoFitsKeys.one(fromJobId, candidateId),
      queryFn: () => alsoFitsApi.get(candidateId, fromJobId),
      enabled,
      staleTime: STALE_MS,
      // Błąd pokazujemy z „Ponów” — bez cichych powtórek przy każdym dodaniu.
      retry: false,
    })),
  });
  const [states, setStates] = useState<ReadonlyMap<string, ElsewhereState>>(() => new Map());
  const [errors, setErrors] = useState<ReadonlyMap<string, string>>(() => new Map());
  const undoWindow = useUndoWindow<string>();

  const setPair = useCallback((key: string, value: ElsewhereState | undefined) => {
    setStates((prev) => {
      const next = new Map(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    });
  }, []);
  const setError = useCallback((key: string, message: string | undefined) => {
    setErrors((prev) => {
      if (!message && !prev.has(key)) return prev;
      const next = new Map(prev);
      if (message) next.set(key, message);
      else next.delete(key);
      return next;
    });
  }, []);

  const refreshAfter = useCallback(
    (candidateId: number, jobId: number) => {
      for (const id of [jobId, fromJobId]) {
        void queryClient.invalidateQueries({ queryKey: ["kanban", String(id)] });
        void queryClient.invalidateQueries({ queryKey: ["kanban", id] });
      }
      void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
      void queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
      void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.quickView(candidateId) });
    },
    [queryClient, fromJobId],
  );

  const add = useCallback(
    (candidateId: number, jobIds: readonly number[]) => {
      for (const jobId of jobIds) {
        const key = pairKey(candidateId, jobId);
        setPair(key, "adding");
        setError(key, undefined);
        proposalsBulkApi
          .add(jobId, {
            candidate_ids: [candidateId],
            initial_stage_legacy: "new",
            source: "also_fits",
            origin_job_id: fromJobId,
          })
          .then((result) => {
            if (result.added.includes(candidateId)) {
              setPair(key, "added");
              undoWindow.start([key]);
              refreshAfter(candidateId, jobId);
            } else {
              setPair(key, undefined);
              setError(
                key,
                elsewhereRefusal(result.skipped.find((s) => s.candidate_id === candidateId)),
              );
            }
          })
          .catch((err: unknown) => {
            setPair(key, undefined);
            setError(key, apiErrorMessage(err, "Nie udało się dodać do tej rekrutacji."));
          });
      }
    },
    [fromJobId, refreshAfter, setError, setPair, undoWindow],
  );

  const undo = useCallback(
    (candidateId: number, jobId: number) => {
      const key = pairKey(candidateId, jobId);
      setPair(key, "undoing");
      candidatesApi
        .removeFromRecruitment(candidateId, jobId, { quickUndo: true })
        .then(() => {
          setPair(key, undefined);
          refreshAfter(candidateId, jobId);
        })
        .catch((err: unknown) => {
          setPair(key, "added");
          setError(key, apiErrorMessage(err, "Nie udało się cofnąć dodania."));
        });
    },
    [refreshAfter, setError, setPair],
  );

  const retry = useCallback(
    (candidateId: number) => {
      void queryClient.refetchQueries({ queryKey: alsoFitsKeys.one(fromJobId, candidateId) });
    },
    [queryClient, fromJobId],
  );

  const forCandidate = useCallback(
    (candidateId: number): AlsoFitsRowModel | null => {
      const index = ids.indexOf(candidateId);
      if (index < 0 || !enabled) return null;
      const query = results[index];
      const status: AlsoFitsRowModel["status"] = query.isError
        ? "error"
        : !query.data
          ? "loading"
          : query.data.status === "unavailable"
            ? "unavailable"
            : "ok";
      return {
        status,
        jobs: query.data?.jobs ?? [],
        stateOf: (jobId) => states.get(pairKey(candidateId, jobId)),
        errorOf: (jobId) => errors.get(pairKey(candidateId, jobId)),
        undoable: (jobId) => !undoWindow.expired.has(pairKey(candidateId, jobId)),
      };
    },
    [ids, enabled, results, states, errors, undoWindow.expired],
  );

  return { forCandidate, add, undo, retry };
}
