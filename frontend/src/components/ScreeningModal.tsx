"use client";

/**
 * ScreeningModal (Phase 10).
 *
 * Blocks the recruiter from pushing a candidate to an external-facing stage
 * (cv_sent and later) until they have answered the Champion Profile questions.
 * Reads the job's Champion Profile + any existing answers and persists via
 * `POST /api/pipeline/stages/{id}/screening`.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X, Loader2, CheckCircle2, AlertTriangle, Save } from "lucide-react";
import {
  screeningApi,
  type ScreeningAnswerItem,
  type ScreeningAnswers,
  type ScreeningQuestion,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface ScreeningModalProps {
  stageId: number;
  candidateName?: string;
  onClose: () => void;
  /** Called after a successful submit — parent can now advance the stage. */
  onSubmitted?: (matchPercent: number) => void;
}

const FIT_OPTIONS: Array<{
  value: ScreeningAnswers["overall_fit"];
  label: string;
  color: string;
}> = [
  { value: "fit", label: "Pasuje", color: "bg-emerald-600 text-white" },
  { value: "uncertain", label: "Niepewnie", color: "bg-amber-500 text-white" },
  { value: "miss", label: "Nie pasuje", color: "bg-red-600 text-white" },
];

export function ScreeningModal({
  stageId,
  candidateName,
  onClose,
  onSubmitted,
}: ScreeningModalProps) {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["stage-screening", stageId],
    queryFn: () => screeningApi.getForStage(stageId).then((r) => r.data),
  });

  const [answers, setAnswers] = useState<Map<string, ScreeningAnswerItem>>(new Map());
  const [overallFit, setOverallFit] = useState<ScreeningAnswers["overall_fit"]>(
    "uncertain"
  );
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Hydrate from existing answers / champion questions on load.
  useEffect(() => {
    if (!data) return;
    const questions: ScreeningQuestion[] =
      (data.champion_profile as { screening_questions?: ScreeningQuestion[] })
        ?.screening_questions ?? [];
    const existing = data.screening_answers;
    const map = new Map<string, ScreeningAnswerItem>();
    for (const q of questions) {
      const prev = existing?.answers?.find((a) => a.question_id === q.id);
      map.set(q.id, {
        question_id: q.id,
        response: prev?.response ?? "",
        deal_breaker_hit: prev?.deal_breaker_hit ?? false,
      });
    }
    setAnswers(map);
    if (existing?.overall_fit) setOverallFit(existing.overall_fit);
    if (existing?.notes) setNotes(existing.notes);
  }, [data]);

  const submitMut = useMutation({
    mutationFn: (payload: ScreeningAnswers) => screeningApi.submit(stageId, payload),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["stage-screening", stageId] });
      qc.invalidateQueries({ queryKey: ["kanban"] });
      onSubmitted?.(r.data.match_percent);
    },
    onError: (e: unknown) => {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail ?? "Błąd zapisu")
          : "Błąd zapisu";
      setError(String(msg));
    },
  });

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const questions: ScreeningQuestion[] =
    (data?.champion_profile as { screening_questions?: ScreeningQuestion[] })
      ?.screening_questions ?? [];

  const hasDealBreaker = Array.from(answers.values()).some((a) => a.deal_breaker_hit);
  const allAnswered =
    questions.length > 0 &&
    questions.every((q) => (answers.get(q.id)?.response ?? "").trim().length > 0);

  const submit = () => {
    setError(null);
    const payload: ScreeningAnswers = {
      answers: Array.from(answers.values()),
      overall_fit: overallFit,
      notes,
    };
    submitMut.mutate(payload);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="screening-modal-title"
    >
      <div
        className="w-full max-w-3xl bg-white dark:bg-gray-800 rounded-xl shadow-xl mt-10 mb-10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between px-5 py-3.5 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-t-xl z-10">
          <div>
            <h2
              id="screening-modal-title"
              className="font-semibold text-gray-900 dark:text-gray-100"
            >
              Screening Championa
            </h2>
            <p className="text-xs text-gray-500">
              {candidateName ? `${candidateName} · ` : ""}wymagane przed rekomendacją do klienta
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {isLoading && (
            <div className="flex justify-center py-10 text-gray-400">
              <Loader2 className="w-6 h-6 animate-spin" />
            </div>
          )}

          {!isLoading && questions.length === 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              Delivery Lead nie skonfigurował jeszcze Profilu Championa dla tej
              rekrutacji. Poproś go o wypełnienie — screening powinien zostać
              wykonany przed rekomendacją kandydata do klienta.
            </div>
          )}

          {questions.map((q, i) => {
            const a = answers.get(q.id);
            return (
              <div
                key={q.id}
                className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2"
                data-testid={`screening-answer-${q.id}`}
              >
                <div className="flex items-start gap-2">
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-mono">
                    Q{i + 1}
                  </span>
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {q.question}
                  </p>
                </div>
                {q.ideal_answer && (
                  <details className="text-[11px] text-gray-500">
                    <summary className="cursor-pointer select-none hover:text-gray-700">
                      Idealna odpowiedź (hint)
                    </summary>
                    <p className="mt-1 italic">{q.ideal_answer}</p>
                  </details>
                )}
                {q.deal_breaker && (
                  <details className="text-[11px] text-red-500">
                    <summary className="cursor-pointer select-none hover:text-red-700">
                      Deal-breaker
                    </summary>
                    <p className="mt-1 italic">{q.deal_breaker}</p>
                  </details>
                )}
                <textarea
                  value={a?.response ?? ""}
                  onChange={(e) =>
                    setAnswers((prev) => {
                      const next = new Map(prev);
                      const cur = next.get(q.id) ?? {
                        question_id: q.id,
                        response: "",
                        deal_breaker_hit: false,
                      };
                      next.set(q.id, { ...cur, response: e.target.value });
                      return next;
                    })
                  }
                  rows={2}
                  placeholder="Odpowiedź kandydata…"
                  className="w-full px-2 py-1.5 text-xs border border-gray-200 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                />
                <label className="inline-flex items-center gap-1.5 text-[11px] text-red-600">
                  <input
                    type="checkbox"
                    checked={a?.deal_breaker_hit ?? false}
                    onChange={(e) =>
                      setAnswers((prev) => {
                        const next = new Map(prev);
                        const cur = next.get(q.id) ?? {
                          question_id: q.id,
                          response: "",
                          deal_breaker_hit: false,
                        };
                        next.set(q.id, { ...cur, deal_breaker_hit: e.target.checked });
                        return next;
                      })
                    }
                    className="accent-red-600"
                  />
                  Deal-breaker trafiony
                </label>
              </div>
            );
          })}

          {questions.length > 0 && (
            <>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-gray-500">Ogólna ocena:</span>
                {FIT_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => setOverallFit(o.value)}
                    className={cn(
                      "text-[11px] px-2 py-1 rounded-md border",
                      overallFit === o.value
                        ? o.color + " border-transparent"
                        : "bg-white dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300"
                    )}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                placeholder="Dodatkowe uwagi rekrutera…"
                className="w-full px-2 py-1.5 text-xs border border-gray-200 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
              />

              {hasDealBreaker && (
                <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 inline-flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  Jeden z deal-breakerów został oznaczony — klient prawdopodobnie
                  odrzuci. Upewnij się zanim wyślesz CV.
                </div>
              )}
              {!allAnswered && (
                <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  Nie wszystkie pytania mają odpowiedź — możesz zapisać draft, ale
                  klient oczekuje kompletnego screeningu.
                </div>
              )}
              {error && (
                <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        <div className="sticky bottom-0 flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-b-xl">
          <button
            onClick={onClose}
            className="text-xs px-3 py-1.5 text-gray-600 hover:text-gray-800 dark:text-gray-300"
          >
            Anuluj
          </button>
          <button
            onClick={submit}
            disabled={submitMut.isPending || questions.length === 0}
            className="inline-flex items-center gap-1.5 text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-md font-medium disabled:opacity-60"
            data-testid="screening-submit"
          >
            {submitMut.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Save className="w-3.5 h-3.5" />
            )}
            {submitMut.isSuccess ? (
              <>
                <CheckCircle2 className="w-3.5 h-3.5" /> Zapisano
              </>
            ) : (
              "Zapisz screening"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
