"use client";

/**
 * Historia zmian formularza screeningu (0424, 07.10.2026).
 *
 * Każdy zapis, przywrócenie i cofnięcie to wersja pary (`GET
 * /api/screening-form/versions`). „Przywróć” zakłada NOWĄ wersję z treścią
 * wybranej — nic nie znika z historii. Stawka wraca tylko przed
 * „Zweryfikowany” (później zmianą stawki zarządza Delivery Lead), a odpowiedź
 * na pytanie, którego treść w Profilu Championa się zmieniła, jest pomijana —
 * oba fakty mówi odpowiedź serwera. Wersja bez stawki nie zdejmuje stawki,
 * która jest (`rate_not_restored_reason: "not_in_version"`).
 *
 * Potwierdzenie przywrócenia stoi w wierszu — bez natywnego `confirm()`.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { History, Loader2, RotateCcw } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  screeningFormConflictOf,
  screeningFormQueryKey,
  useRestoreScreeningForm,
  useScreeningFormVersions,
  type ScreeningFormRestoreResult,
  type ScreeningFormVersion,
  type VersionChange,
} from "@/lib/api/screeningForm";
import { rateNotRestoredMessage, versionActionLabel } from "@/lib/screening-form";
import { countPl } from "@/lib/plural-pl";

const SECTION_LABEL: Record<VersionChange["section"], string> = {
  answers: "Pytania",
  terms: "Warunki",
  assessment: "Ocena",
  rate: "Stawka",
};

const DATE_TIME = new Intl.DateTimeFormat("pl-PL", { dateStyle: "short", timeStyle: "short" });

function when(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : DATE_TIME.format(date);
}

function ChangeLine({ change }: { change: VersionChange }) {
  return (
    <li className="text-xs [overflow-wrap:anywhere]">
      <span className="text-muted-foreground">{SECTION_LABEL[change.section] ?? change.section} · </span>
      <span className="font-medium text-foreground">{change.label}</span>
      {": "}
      <span className="text-muted-foreground line-through decoration-muted-foreground/60">
        {change.before?.trim() || "—"}
      </span>
      <span aria-hidden> → </span>
      <span className="sr-only"> zmienione na </span>
      <span className="text-foreground">{change.after?.trim() || "—"}</span>
    </li>
  );
}

export interface ScreeningFormHistoryViewProps {
  versions: readonly ScreeningFormVersion[];
  total: number;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  /** Bieżąca wersja formularza — przy niej nie ma „Przywróć”. */
  currentVersion: number;
  canRestore: boolean;
  onRestore?: (versionNo: number) => void;
  restoringVersion?: number | null;
  /** Formularz ma niezapisane zmiany — przywrócenie je zastąpi. */
  dirty?: boolean;
}

export function ScreeningFormHistoryView({
  versions,
  total,
  loading = false,
  error = false,
  onRetry,
  currentVersion,
  canRestore,
  onRestore,
  restoringVersion = null,
  dirty = false,
}: ScreeningFormHistoryViewProps) {
  const [confirming, setConfirming] = useState<number | null>(null);

  return (
    <section aria-label="Historia zmian formularza" className="space-y-2" data-testid="screening-form-history">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        <History className="h-3.5 w-3.5" aria-hidden /> Historia zmian
        {total > 0 ? <span className="font-normal normal-case tracking-normal">({total})</span> : null}
      </h3>
      {loading ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> Wczytywanie historii…
        </p>
      ) : error ? (
        <p role="alert" className="text-xs text-destructive">
          Nie udało się wczytać historii zmian.{" "}
          {onRetry ? (
            <button type="button" className="font-medium underline underline-offset-2" onClick={onRetry}>
              Ponów
            </button>
          ) : null}
        </p>
      ) : versions.length === 0 ? (
        <p className="text-xs text-muted-foreground">Formularz nie ma jeszcze zapisanych wersji.</p>
      ) : (
        <ol className="space-y-2">
          {versions.map((version) => {
            const current = version.version_no === currentVersion;
            return (
              <li
                key={version.version_no}
                data-version={version.version_no}
                className="space-y-1.5 rounded-lg border border-border bg-card px-3 py-2"
              >
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
                  <span className="font-semibold text-foreground">Wersja {version.version_no}</span>
                  <span className="text-foreground">
                    {versionActionLabel(version.action, version.restored_from_version)}
                    {version.source === "note_import" ? " · z notatki" : ""}
                  </span>
                  <span className="text-muted-foreground">
                    {version.created_by_name?.trim() || "system"} · {when(version.created_at)}
                  </span>
                  {current ? (
                    <span className="rounded-full bg-primary/10 px-1.5 py-px text-[10.5px] font-medium text-primary">
                      bieżąca
                    </span>
                  ) : null}
                </div>
                {version.changes.length > 0 ? (
                  <ul className="space-y-0.5">
                    {version.changes.map((change) => (
                      <ChangeLine key={`${change.section}:${change.key}`} change={change} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground">Bez zmian treści.</p>
                )}
                {!current && canRestore && onRestore ? (
                  confirming === version.version_no ? (
                    <div
                      role="group"
                      aria-label={`Przywrócić wersję ${version.version_no}?`}
                      className="flex flex-wrap items-center gap-2 rounded-md bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground"
                    >
                      <span className="mr-auto">
                        Przywrócić wersję {version.version_no}?
                        {dirty ? " Niezapisane zmiany w formularzu przepadną." : ""} Powstanie nowa wersja — nic nie
                        znika z historii.
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        loading={restoringVersion === version.version_no}
                        onClick={() => {
                          onRestore(version.version_no);
                          setConfirming(null);
                        }}
                      >
                        Przywróć
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                        Anuluj
                      </Button>
                    </div>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={restoringVersion != null}
                      aria-label={`Przywróć wersję ${version.version_no}`}
                      onClick={() => setConfirming(version.version_no)}
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Przywróć
                    </Button>
                  )
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export interface ScreeningFormHistoryProps {
  candidateId: number;
  jobId: number;
  currentVersion: number;
  /** Odcisk stanu formularza (`ScreeningFormState.state_token`) — przywrócenie go odsyła. */
  stateToken: string;
  canRestore: boolean;
  dirty?: boolean;
  /** Przed odświeżeniem zapytań — formularz przyjmuje stan po przywróceniu. */
  onRestored?: (result: ScreeningFormRestoreResult) => void;
}

export function ScreeningFormHistory({
  candidateId,
  jobId,
  currentVersion,
  stateToken,
  canRestore,
  dirty = false,
  onRestored,
}: ScreeningFormHistoryProps) {
  const { showSuccess, showError, showInfo } = useToast();
  const queryClient = useQueryClient();
  const query = useScreeningFormVersions(candidateId, jobId);
  const restore = useRestoreScreeningForm({
    onSaved: (result) => onRestored?.(result),
  });
  const [restoring, setRestoring] = useState<number | null>(null);

  const runRestore = (versionNo: number) => {
    setRestoring(versionNo);
    restore.mutate(
      {
        candidate_id: candidateId,
        job_id: jobId,
        version_no: versionNo,
        expected_version: currentVersion,
        state_token: stateToken,
        mode: "restore",
      },
      {
        onSuccess: (result) => {
          showSuccess(`Przywrócono wersję ${versionNo}.`);
          const rateMessage = rateNotRestoredMessage(result, "restore");
          if (rateMessage) showInfo(rateMessage);
          if (result.skipped_answers.length > 0) {
            showInfo(
              `Pominięto ${countPl(result.skipped_answers.length, "odpowiedź", "odpowiedzi", "odpowiedzi")} — treść pytania w Profilu Championa się zmieniła.`,
            );
          }
        },
        onError: (err) => {
          showError(apiErrorMessage(err, "Nie udało się przywrócić wersji. Spróbuj ponownie."));
          // Ktoś zmienił formularz w międzyczasie — wczytaj nowy stan i historię.
          if (screeningFormConflictOf(err)) {
            void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
          }
        },
        onSettled: () => setRestoring(null),
      },
    );
  };

  return (
    <ScreeningFormHistoryView
      versions={query.data?.items ?? []}
      total={query.data?.total ?? 0}
      loading={query.isLoading}
      error={query.isError}
      onRetry={() => void query.refetch()}
      currentVersion={currentVersion}
      canRestore={canRestore}
      onRestore={runRestore}
      restoringVersion={restoring}
      dirty={dirty}
    />
  );
}
