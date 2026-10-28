"use client";

/**
 * Panel „Ocena AI · N zaznaczonych osób” (28.10.2026, makieta C:
 * https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS) w oknie „Kandydaci do
 * dodania”. Rekruter zaznacza osoby i klika „✦ Oceń z AI” zamiast pobierać
 * CV do prywatnego czatu: panel układa je w kolejności dzwonienia
 * (Dzwoń / Może / Nie pasuje), każdy powód z cytatem z CV albo notatki.
 *
 * AI niczego nie odrzuca: osoba bez werdyktu („AI nie oceniło”) zostaje na
 * liście, a „Dodaj K „Dzwoń” do Nowych” idzie tą samą drogą co „Dodaj do
 * Nowych” zakładki (`onAdd` — `proposals/bulk`). Ocena jest zapisana przy
 * rekrutacji: `people == null` otwiera ostatnią ocenę bez wołania modelu.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles, UserPlus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  AI_ASSESSMENT_CHUNK,
  AI_ASSESSMENT_MAX,
  AI_ASSESSMENT_PARALLEL,
  SOURCE_LABEL,
  VERDICT_LABEL,
  aiAssessmentApi,
  callOrder,
  mergeRows,
  newBatchId,
  notAssessedLabel,
  verdictCounts,
  type AiAssessmentRow,
  type AiVerdict,
} from "@/lib/ai-assessment";
import { cn } from "@/lib/utils";

export interface AiAssessmentPerson {
  candidateId: number;
  fullName: string;
}

export interface AiAssessmentPanelProps {
  jobId: number;
  /** Zaznaczone osoby; `null` = pokaż ostatnią zapisaną ocenę. */
  people: readonly AiAssessmentPerson[] | null;
  /** Dodanie do „Nowych” w podanej kolejności; zwraca, kogo dodano. */
  onAdd: (candidateIds: number[]) => Promise<readonly number[]>;
  onClose: () => void;
  readOnly?: boolean;
}

const VERDICT_CLASS: Record<AiVerdict, string> = {
  call: "bg-success-muted text-success-muted-foreground",
  maybe: "bg-warning-muted text-warning-muted-foreground",
  no_fit: "bg-muted text-muted-foreground",
};

/** Osoby z paczki, która nie wróciła — bez werdyktu, ale dalej na liście. */
function failedRows(
  people: readonly AiAssessmentPerson[],
  firstIndex: number,
): AiAssessmentRow[] {
  return people.map((p, i) => ({
    candidate_id: p.candidateId,
    full_name: p.fullName,
    selection_index: firstIndex + i,
    verdict: null,
    strength: null,
    must_found: 0,
    must_total: 0,
    reasons: [],
    error_kind: "model",
    reused: false,
  }));
}

function useAssessment(jobId: number, people: readonly AiAssessmentPerson[] | null) {
  const [rows, setRows] = useState<AiAssessmentRow[]>([]);
  const [done, setDone] = useState(0);
  const [total, setTotal] = useState(people?.length ?? 0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [createdAt, setCreatedAt] = useState<string | null>(null);
  const runId = useRef(0);

  const run = useCallback(
    async (refresh: boolean) => {
      if (!people || people.length === 0) return;
      const id = ++runId.current;
      const batchId = newBatchId();
      const chunks: { people: readonly AiAssessmentPerson[]; first: number }[] = [];
      for (let start = 0; start < people.length; start += AI_ASSESSMENT_CHUNK) {
        chunks.push({ people: people.slice(start, start + AI_ASSESSMENT_CHUNK), first: start });
      }
      setRows([]);
      setDone(0);
      setTotal(people.length);
      setError(null);
      setRunning(true);
      let next = 0;
      let stopped = false;
      const worker = async () => {
        while (!stopped && next < chunks.length) {
          const chunk = chunks[next++];
          try {
            const batch = await aiAssessmentApi.assess(jobId, {
              batch_id: batchId,
              candidate_ids: chunk.people.map((p) => p.candidateId),
              first_index: chunk.first,
              refresh,
            });
            if (runId.current !== id) return;
            const mine = new Set(chunk.people.map((p) => p.candidateId));
            setRows((prev) => mergeRows(prev, batch.rows.filter((r) => mine.has(r.candidate_id))));
            setRemaining(batch.remaining_today);
            setCreatedAt(batch.created_at);
          } catch (err) {
            if (runId.current !== id) return;
            // Limit dzienny zatrzymuje resztę paczek; inna awaria = osoby bez werdyktu.
            const status = (err as { response?: { status?: number } })?.response?.status;
            if (status === 429) stopped = true;
            setError(apiErrorMessage(err, "Nie udało się ocenić części osób."));
            setRows((prev) => mergeRows(prev, failedRows(chunk.people, chunk.first)));
          } finally {
            if (runId.current === id) setDone((d) => d + chunk.people.length);
          }
        }
      };
      await Promise.all(Array.from({ length: AI_ASSESSMENT_PARALLEL }, worker));
      if (runId.current === id) setRunning(false);
    },
    [jobId, people],
  );

  useEffect(() => {
    if (people) {
      void run(false);
      return () => {
        runId.current += 1;
      };
    }
    const id = ++runId.current;
    setRunning(true);
    aiAssessmentApi
      .latest(jobId)
      .then((batch) => {
        if (runId.current !== id) return;
        setRows(callOrder(batch.rows));
        setTotal(batch.rows.length);
        setDone(batch.rows.length);
        setRemaining(batch.remaining_today);
        setCreatedAt(batch.created_at);
      })
      .catch((err) => {
        if (runId.current === id) setError(apiErrorMessage(err, "Nie wczytano ostatniej oceny."));
      })
      .finally(() => {
        if (runId.current === id) setRunning(false);
      });
    return () => {
      runId.current += 1;
    };
  }, [jobId, people, run]);

  return { rows, done, total, running, error, remaining, createdAt, rerun: () => run(true) };
}

function formatTime(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AiAssessmentPanel({
  jobId,
  people,
  onAdd,
  onClose,
  readOnly = false,
}: AiAssessmentPanelProps) {
  const { rows, done, total, running, error, remaining, createdAt, rerun } = useAssessment(
    jobId,
    people,
  );
  const [adding, setAdding] = useState(false);
  const [addedIds, setAddedIds] = useState<ReadonlySet<number>>(() => new Set());
  const counts = verdictCounts(rows);
  const callIds = rows
    .filter((r) => r.verdict === "call" && !addedIds.has(r.candidate_id))
    .map((r) => r.candidate_id);
  const count = people?.length ?? rows.length;
  const when = formatTime(createdAt);

  const addCalls = async () => {
    if (callIds.length === 0 || adding) return;
    setAdding(true);
    try {
      const added = await onAdd(callIds);
      setAddedIds((prev) => new Set([...prev, ...added]));
    } finally {
      setAdding(false);
    }
  };

  return (
    <section
      aria-label="Ocena AI"
      className="flex h-full flex-col"
      data-testid="ai-assessment-panel"
    >
      <header className="space-y-2 border-b border-border px-5 pb-3 pt-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-base font-semibold">
            Ocena AI · {count} {count === 1 ? "zaznaczona osoba" : "zaznaczonych osób"}
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Zamknij ocenę AI"
            data-testid="ai-assessment-close"
          >
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          Czytam całe CV i notatki każdej osoby i porównuję je z rekrutacją, Profilem Championa
          i umiejętnościami krytycznymi. Każdy powód ma cytat — bez cytatu powód znika. AI
          niczego nie odrzuca i nie zmienia procentu dopasowania.
        </p>
        <div className="flex flex-wrap items-center gap-2 text-xs font-medium" aria-live="polite">
          <span className={cn("rounded-full px-2 py-0.5", VERDICT_CLASS.call)}>
            Dzwoń · {counts.call}
          </span>
          <span className={cn("rounded-full px-2 py-0.5", VERDICT_CLASS.maybe)}>
            Może · {counts.maybe}
          </span>
          <span className={cn("rounded-full px-2 py-0.5", VERDICT_CLASS.no_fit)}>
            Nie pasuje · {counts.no_fit}
          </span>
          {counts.none > 0 ? (
            <span className="rounded-full border border-border px-2 py-0.5 text-muted-foreground">
              AI nie oceniło · {counts.none}
            </span>
          ) : null}
          {running ? (
            <span className="text-muted-foreground" data-testid="ai-assessment-progress">
              Oceniam… {Math.min(done, total)} z {total}
            </span>
          ) : null}
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </header>

      <ol className="flex-1 divide-y divide-border overflow-y-auto" data-testid="ai-assessment-rows">
        {rows.map((row, index) => (
          <li
            key={row.candidate_id}
            className="flex gap-3 px-5 py-3"
            data-testid="ai-assessment-row"
            data-verdict={row.verdict ?? "none"}
          >
            <span className="w-5 shrink-0 pt-0.5 text-right text-sm font-semibold tabular-nums text-muted-foreground">
              {index + 1}.
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-start justify-between gap-2">
                <span className="font-medium">{row.full_name}</span>
                {addedIds.has(row.candidate_id) ? (
                  <span className="shrink-0 rounded-full bg-success-muted px-2 py-0.5 text-xs font-medium text-success-muted-foreground">
                    Dodano do Nowych
                  </span>
                ) : row.verdict ? (
                  <span
                    className={cn(
                      "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                      VERDICT_CLASS[row.verdict],
                    )}
                  >
                    {VERDICT_LABEL[row.verdict]}
                  </span>
                ) : (
                  <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                    AI nie oceniło
                  </span>
                )}
              </div>
              {row.verdict ? (
                row.reasons.map((reason, i) => (
                  <div key={i} className="text-sm">
                    <p>{reason.text}</p>
                    <p className="text-xs italic text-muted-foreground">
                      {SOURCE_LABEL[reason.source]}: „{reason.quote}”
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">{notAssessedLabel(row)}</p>
              )}
            </div>
          </li>
        ))}
        {!running && rows.length === 0 && !error ? (
          <li className="px-5 py-6 text-sm text-muted-foreground">
            Nie ma zapisanej oceny z ostatnich 7 dni. Zaznacz osoby i kliknij „Oceń z AI”.
          </li>
        ) : null}
      </ol>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
        <p className="text-xs text-muted-foreground">
          CV nie wychodzą z NEXUSA · ocena zapisana przy rekrutacji
          {when ? ` (${when})` : ""}
          {remaining != null ? ` · dziś zostało ${remaining} ocen` : ""}
          {people && !running ? (
            <>
              {" · "}
              <button
                type="button"
                className="underline"
                onClick={() => void rerun()}
                data-testid="ai-assessment-rerun"
              >
                Oceń jeszcze raz
              </button>
            </>
          ) : null}
        </p>
        {readOnly ? null : (
          <Button
            onClick={() => void addCalls()}
            disabled={callIds.length === 0 || adding || running}
            loading={adding}
            data-testid="ai-assessment-add-calls"
          >
            <UserPlus className="h-4 w-4" aria-hidden />
            Dodaj {callIds.length} „Dzwoń” do Nowych w tej kolejności
          </Button>
        )}
      </footer>
    </section>
  );
}

/** Przycisk „✦ Oceń z AI” — ten sam w „Szukaj ręcznie” i w propozycjach. */
export function AssessWithAiButton({
  count,
  onClick,
  disabled,
  size = "sm",
  primary = false,
}: {
  count: number;
  onClick: () => void;
  disabled?: boolean;
  size?: "sm" | "md";
  /** Makieta C: w pasku „Szukaj ręcznie” to główna akcja. */
  primary?: boolean;
}) {
  const tooMany = count > AI_ASSESSMENT_MAX;
  return (
    <Button
      size={size}
      variant={primary ? "primary" : "outline"}
      onClick={onClick}
      disabled={disabled || count === 0 || tooMany}
      title={tooMany ? `Oceniamy najwyżej ${AI_ASSESSMENT_MAX} osób naraz — odznacz część.` : undefined}
      data-testid="assess-with-ai"
    >
      <Sparkles className="h-3.5 w-3.5" aria-hidden /> Oceń z AI
    </Button>
  );
}
