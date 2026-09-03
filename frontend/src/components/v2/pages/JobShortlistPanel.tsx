"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronDown, ChevronUp, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  shortlistApi,
  type EvaluationStatus,
  type OutreachStatus,
  type ShortlistEntry,
  type ShortlistUpdate,
} from "@/lib/candidate-search-api";
import { priorityWorkErrorMessage } from "@/lib/priority-work-api";

const EVAL_LABELS: Record<EvaluationStatus, string> = {
  do_oceny: "Do oceny",
  potencjalny: "Potencjalny",
  zatwierdzony: "Zatwierdzony",
  odrzucony: "Odrzucony",
};

const OUTREACH_LABELS: Record<OutreachStatus, string> = {
  nie_kontaktowano: "Nie kontaktowano",
  do_kontaktu: "Do kontaktu",
  kontakt_w_toku: "Kontakt w toku",
  zainteresowany: "Zainteresowany",
  brak_zainteresowania: "Brak zainteresowania",
};

function apiErrorStatus(err: unknown): number | undefined {
  return (err as { response?: { status?: number } })?.response?.status;
}

function apiErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  return typeof detail === "string" && detail ? detail : fallback;
}

const SELECT_CLASS =
  "h-7 rounded-md border bg-background px-1.5 text-xs focus:outline-hidden focus:ring-1 focus:ring-ring disabled:opacity-50 dark:border-zinc-700";

interface JobShortlistPanelProps {
  jobId: number;
  /** Bump to force a reload (e.g. after adding candidates from search). */
  refreshSignal?: number;
  /** Called after a successful promote so the parent can refresh the pipeline. */
  onPromoted?: () => void;
  /** Keep shortlist data visible without exposing server mutations. */
  readOnly?: boolean;
}

/**
 * The job's shortlist inside the search workspace: evaluate + track outreach,
 * then promote approved candidates into the pipeline (SEARCH-P1-05). Status
 * edits are optimistic-locked — a stale row (409) triggers a reload.
 */
export function JobShortlistPanel({
  jobId,
  refreshSignal,
  onPromoted,
  readOnly = false,
}: JobShortlistPanelProps) {
  const [entries, setEntries] = useState<ShortlistEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // M4 PR-03 (audyt P2.8): błąd pobrania NIE udaje pustej listy — panel
  // pokazuje stan błędu z możliwością ponowienia zamiast znikać.
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    shortlistApi
      .list(jobId)
      .then(setEntries)
      .catch((err) => {
        console.error("Shortlist load failed", err);
        setLoadError(apiErrorMessage(err, "Nie udało się pobrać shortlisty."));
      })
      .finally(() => setLoading(false));
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load, refreshSignal]);

  const patch = async (entry: ShortlistEntry, body: Partial<ShortlistUpdate>) => {
    if (readOnly) return;
    setBusyId(entry.id);
    setError(null);
    try {
      const updated = await shortlistApi.update(entry.id, {
        version: entry.version,
        ...body,
      });
      setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    } catch (err) {
      // M4 PR-03 (audyt P2.8): 409 = realny konflikt wersji; pozostałe
      // statusy przestają udawać konflikt równoległej edycji.
      const status = apiErrorStatus(err);
      if (status === 409) {
        setError("Wpis zmieniony w innym miejscu — lista odświeżona.");
        load();
      } else if (status === 403) {
        setError("Brak uprawnień do zmiany tego wpisu.");
      } else {
        setError(apiErrorMessage(err, "Nie udało się zapisać zmiany."));
      }
    } finally {
      setBusyId(null);
    }
  };

  const promote = async (entry: ShortlistEntry) => {
    if (readOnly) return;
    setBusyId(entry.id);
    setError(null);
    try {
      await shortlistApi.promote(entry.id);
      onPromoted?.();
      load();
    } catch (err) {
      setError(
        priorityWorkErrorMessage(err) ??
          apiErrorMessage(err, "Nie udało się przenieść do rekrutacji."),
      );
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (entry: ShortlistEntry) => {
    if (readOnly) return;
    setBusyId(entry.id);
    setError(null);
    try {
      await shortlistApi.remove(entry.id);
      setEntries((prev) => prev.filter((e) => e.id !== entry.id));
    } catch (err) {
      // M4 PR-03 (audyt P2.8): błąd usunięcia był cicho maskowany reloadem.
      setError(apiErrorMessage(err, "Nie udało się usunąć wpisu."));
      load();
    } finally {
      setBusyId(null);
    }
  };

  if (loadError) {
    return (
      <div className="rounded-lg border bg-card p-3 text-sm dark:border-zinc-800">
        <span className="text-rose-600 dark:text-rose-400">{loadError}</span>{" "}
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={load}
          className="ml-2 h-7 text-xs"
        >
          Spróbuj ponownie
        </Button>
      </div>
    );
  }

  if (entries.length === 0 && !loading) return null;

  return (
    <div className="rounded-lg border bg-card dark:border-zinc-800">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between p-3 text-sm"
      >
        <span className="font-medium">
          Shortlista{" "}
          <span className="text-zinc-500 dark:text-zinc-400">
            ({entries.length})
          </span>
        </span>
        {open ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>
      {open && (
        <div className="divide-y border-t dark:divide-zinc-800 dark:border-zinc-800">
          {error && (
            <div className="p-2 text-xs text-rose-600 dark:text-rose-400">
              {error}
            </div>
          )}
          {entries.map((e) => (
            <div
              key={e.id}
              className="flex flex-wrap items-center gap-2 p-2 text-sm"
            >
              <Link
                href={`/candidates/${e.candidate_id}`}
                className="min-w-0 flex-1 truncate font-medium hover:underline"
              >
                {e.candidate_name} {e.candidate_lastname}
              </Link>
              {typeof e.score_snapshot === "number" && (
                <span className="tabular-nums text-xs text-zinc-500 dark:text-zinc-400">
                  {e.score_snapshot}
                </span>
              )}
              {readOnly ? (
                <>
                  <span
                    aria-label={`Ocena: ${EVAL_LABELS[e.evaluation_status]}`}
                    className="rounded-md border bg-muted px-2 py-1 text-xs"
                  >
                    {EVAL_LABELS[e.evaluation_status]}
                  </span>
                  <span
                    aria-label={`Kontakt: ${OUTREACH_LABELS[e.outreach_status]}`}
                    className="rounded-md border bg-muted px-2 py-1 text-xs"
                  >
                    {OUTREACH_LABELS[e.outreach_status]}
                  </span>
                </>
              ) : (
                <>
                  <select
                    aria-label="Ocena"
                    value={e.evaluation_status}
                    disabled={busyId === e.id}
                    onChange={(ev) =>
                      patch(e, {
                        evaluation_status: ev.target.value as EvaluationStatus,
                      })
                    }
                    className={SELECT_CLASS}
                  >
                    {Object.entries(EVAL_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Kontakt"
                    value={e.outreach_status}
                    disabled={busyId === e.id}
                    onChange={(ev) =>
                      patch(e, {
                        outreach_status: ev.target.value as OutreachStatus,
                      })
                    }
                    className={SELECT_CLASS}
                  >
                    {Object.entries(OUTREACH_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </>
              )}
              {e.promoted_to_pipeline_at ? (
                <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  w rekrutacji
                </span>
              ) : !readOnly ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busyId === e.id}
                  onClick={() => promote(e)}
                  className="h-7 gap-1 text-xs"
                >
                  {busyId === e.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <ArrowRight className="h-3 w-3" />
                  )}
                  Do rekrutacji
                </Button>
              ) : null}
              {!readOnly ? (
                <button
                  type="button"
                  onClick={() => remove(e)}
                  disabled={busyId === e.id}
                  aria-label={`Usuń ${e.candidate_name} z shortlisty`}
                  className="text-zinc-400 hover:text-rose-600 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
