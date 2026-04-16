"use client";

import { useEffect, useState } from "react";
import { Loader2, X, ClipboardList, Star } from "lucide-react";
import { phase3Api, type ScorecardQuestion, type ScorecardSchema } from "@/lib/api";

interface Props {
  candidateStageId: number;
  stageId: number;
  stageDefId: number;
  stageName?: string;
  onClose: () => void;
  onSaved: () => void;
}

type AnswerValue = string | number | boolean;

export function ScorecardModal({
  candidateStageId,
  stageId,
  stageDefId,
  stageName,
  onClose,
  onSaved,
}: Props) {
  const [loading, setLoading] = useState(true);
  const [schema, setSchema] = useState<ScorecardSchema | null>(null);
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const [overall, setOverall] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await phase3Api.getScorecardSchema(stageDefId);
        if (!cancel) setSchema(r.data.schema);
      } catch (e: unknown) {
        const msg =
          e && typeof e === "object" && "response" in e
            ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
            : "Błąd";
        if (!cancel) setError(msg);
      } finally {
        if (!cancel) setLoading(false);
      }
    };
    load();
    return () => {
      cancel = true;
    };
  }, [stageDefId]);

  const set = (qid: string, v: AnswerValue) =>
    setAnswers(prev => ({ ...prev, [qid]: v }));

  const validate = (): string | null => {
    if (!schema) return null;
    for (const q of schema.questions) {
      if (!q.required) continue;
      const v = answers[q.id];
      if (v == null || v === "" || v === false) {
        return `Pole "${q.label}" jest wymagane`;
      }
    }
    return null;
  };

  const handleSubmit = async () => {
    const vErr = validate();
    if (vErr) {
      setError(vErr);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const answersArray = schema
        ? schema.questions
            .filter(q => answers[q.id] != null)
            .map(q => ({ question_id: q.id, value: answers[q.id] }))
        : [];
      await phase3Api.submitAnswers(candidateStageId, {
        stage_id: stageId,
        stage_def_id: stageDefId,
        answers: answersArray,
        overall_rating: overall ?? undefined,
        notes: notes || undefined,
      });
      onSaved();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd zapisu")
          : "Błąd zapisu";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const renderField = (q: ScorecardQuestion) => {
    const val = answers[q.id];
    switch (q.type) {
      case "rating": {
        const num = typeof val === "number" ? val : 0;
        return (
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map(n => (
              <button
                key={n}
                type="button"
                onClick={() => set(q.id, n)}
                className="p-1"
                aria-label={`${n} gwiazdek`}
              >
                <Star
                  className={`w-5 h-5 ${
                    n <= num ? "fill-yellow-400 text-yellow-400" : "text-gray-300"
                  }`}
                />
              </button>
            ))}
          </div>
        );
      }
      case "checkbox":
        return (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={!!val}
              onChange={e => set(q.id, e.target.checked)}
              className="w-4 h-4 accent-blue-600"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">
              {q.description ?? "Tak"}
            </span>
          </label>
        );
      case "select":
        return (
          <select
            value={typeof val === "string" ? val : ""}
            onChange={e => set(q.id, e.target.value)}
            className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1.5 text-sm bg-white dark:bg-gray-800"
          >
            <option value="">— wybierz —</option>
            {(q.options ?? []).map(opt => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        );
      case "text":
      default:
        return (
          <textarea
            value={typeof val === "string" ? val : ""}
            onChange={e => set(q.id, e.target.value)}
            rows={2}
            className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1.5 text-sm bg-white dark:bg-gray-800"
            placeholder={q.description ?? ""}
          />
        );
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="font-semibold flex items-center gap-2 text-gray-900 dark:text-gray-100">
            <ClipboardList className="w-5 h-5 text-blue-500" />
            Scorecard: {schema?.title ?? stageName ?? "ocena etapu"}
          </h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
            aria-label="Zamknij"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {loading && (
            <div className="flex justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
            </div>
          )}

          {!loading && !schema && !error && (
            <p className="text-sm text-gray-500 py-6">
              Dla tego etapu nie zdefiniowano scorecardu. Możesz zapisać ogólną ocenę i notatki.
            </p>
          )}

          {error && (
            <div className="text-sm text-red-700 bg-red-50 dark:bg-red-900/20 rounded p-3">
              {error}
            </div>
          )}

          {!loading && schema && schema.questions.length > 0 && (
            <div className="space-y-4">
              {schema.questions.map(q => (
                <div key={q.id}>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">
                    {q.label}
                    {q.required && <span className="text-red-500 ml-0.5">*</span>}
                  </label>
                  {q.description && q.type !== "checkbox" && (
                    <p className="text-xs text-gray-400 mb-1">{q.description}</p>
                  )}
                  {renderField(q)}
                </div>
              ))}
            </div>
          )}

          <div className="pt-3 border-t border-gray-200 dark:border-gray-700">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">
              Ogólna ocena (1-5)
            </label>
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map(n => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setOverall(n === overall ? null : n)}
                  className="p-1"
                  aria-label={`Ogólnie ${n} gwiazdek`}
                >
                  <Star
                    className={`w-6 h-6 ${
                      overall != null && n <= overall
                        ? "fill-yellow-400 text-yellow-400"
                        : "text-gray-300"
                    }`}
                  />
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">
              Notatki
            </label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={3}
              className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1.5 text-sm bg-white dark:bg-gray-800"
              placeholder="Uwagi z etapu…"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
          >
            Anuluj
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-60"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            Zapisz scorecard
          </button>
        </div>
      </div>
    </div>
  );
}
