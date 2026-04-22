"use client";

import { useEffect, useState } from "react";
import { ClipboardList, Loader2, Plus, Trash2, X, GripVertical, Save } from "lucide-react";
import { phase3Api, type ScorecardQuestion, type ScorecardSchema } from "@/lib/api";
import { ScorecardV2 } from "./v2/modals/ScorecardV2";

interface Props {
  stageDefId: number;
  stageName: string;
  onClose: () => void;
  onSaved: () => void;
}

type QType = ScorecardQuestion["type"];

const TYPE_LABELS: Record<QType, string> = {
  rating: "Ocena (1-5 gwiazdek)",
  text: "Tekst (wielolinijkowy)",
  checkbox: "Checkbox (tak/nie)",
  select: "Wybór z listy",
};

function slugify(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_]/g, "")
    .slice(0, 40);
}

export function ScorecardSchemaBuilder({
  stageDefId,
  stageName,
  onClose,
  onSaved,
}: Props) {
  const [title, setTitle] = useState<string>(stageName);
  const [questions, setQuestions] = useState<ScorecardQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    let cancel = false;
    (async () => {
      setLoading(true);
      try {
        const r = await phase3Api.getScorecardSchema(stageDefId);
        if (cancel) return;
        const sch = r.data.schema;
        setTitle(sch?.title ?? stageName);
        setQuestions(Array.isArray(sch?.questions) ? sch.questions : []);
      } catch (e: unknown) {
        if (!cancel) {
          const msg =
            e && typeof e === "object" && "response" in e
              ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
                "")
              : "";
          // 404 or empty is fine — start blank
          if (!msg.toLowerCase().includes("not found")) {
            setError(msg || "Błąd pobierania scorecard");
          }
        }
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [stageDefId, stageName]);

  const add = () => {
    const base = `question_${questions.length + 1}`;
    setQuestions(prev => [
      ...prev,
      {
        id: base,
        label: "",
        type: "rating",
        required: false,
      },
    ]);
  };

  const remove = (idx: number) =>
    setQuestions(prev => prev.filter((_, i) => i !== idx));

  const move = (idx: number, dir: -1 | 1) => {
    setQuestions(prev => {
      const next = [...prev];
      const j = idx + dir;
      if (j < 0 || j >= next.length) return prev;
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  };

  const patch = (idx: number, p: Partial<ScorecardQuestion>) =>
    setQuestions(prev => prev.map((q, i) => (i === idx ? { ...q, ...p } : q)));

  const validate = (): string | null => {
    if (questions.length === 0)
      return "Dodaj co najmniej jedno pytanie (albo usuń cały scorecard klikając Zapisz pusty).";
    const ids = new Set<string>();
    for (const q of questions) {
      if (!q.id.trim()) return "Każde pytanie musi mieć ID (slug).";
      if (ids.has(q.id)) return `Duplikat ID: "${q.id}"`;
      ids.add(q.id);
      if (!q.label.trim()) return "Każde pytanie musi mieć label.";
      if (q.type === "select" && (!q.options || q.options.length === 0))
        return `Pytanie "${q.label}" typu "Wybór z listy" wymaga co najmniej jednej opcji.`;
    }
    return null;
  };

  const handleSave = async () => {
    if (questions.length > 0) {
      const v = validate();
      if (v) {
        setError(v);
        return;
      }
    }
    setSaving(true);
    setError(null);
    try {
      const schema: ScorecardSchema = {
        title: title.trim() || null,
        questions,
      };
      await phase3Api.setScorecardSchema(stageDefId, schema);
      onSaved();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 sticky top-0 bg-white dark:bg-gray-800 z-10">
          <h3 className="font-semibold flex items-center gap-2 text-gray-900 dark:text-gray-100">
            <ClipboardList className="w-5 h-5 text-blue-500" />
            Scorecard dla: {stageName}
          </h3>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPreview(v => !v)}
              disabled={questions.length === 0}
              className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-100 disabled:opacity-40"
            >
              {preview ? "Schowaj podgląd" : "Podgląd wypełnienia"}
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="p-4 space-y-4">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
            </div>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">
                  Tytuł scorecardu (opcjonalnie)
                </label>
                <input
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder={stageName}
                  className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1.5 text-sm bg-white dark:bg-gray-900"
                />
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-gray-200 dark:border-gray-700">
                <h4 className="font-medium text-gray-700 dark:text-gray-200">
                  Pytania ({questions.length})
                </h4>
                <button
                  onClick={add}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm"
                >
                  <Plus className="w-4 h-4" />
                  Dodaj pytanie
                </button>
              </div>

              {questions.length === 0 && (
                <p className="text-sm text-gray-500 py-6 text-center">
                  Brak pytań. Dodaj pierwsze.
                </p>
              )}

              <ul className="space-y-2">
                {questions.map((q, idx) => (
                  <li
                    key={idx}
                    className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 p-3 space-y-2"
                  >
                    <div className="flex items-center gap-2">
                      <div className="flex flex-col">
                        <button
                          onClick={() => move(idx, -1)}
                          disabled={idx === 0}
                          className="text-gray-400 hover:text-gray-600 disabled:opacity-20"
                          title="W górę"
                        >
                          ▲
                        </button>
                        <button
                          onClick={() => move(idx, 1)}
                          disabled={idx === questions.length - 1}
                          className="text-gray-400 hover:text-gray-600 disabled:opacity-20"
                          title="W dół"
                        >
                          ▼
                        </button>
                      </div>
                      <GripVertical className="w-4 h-4 text-gray-400" />
                      <span className="text-xs text-gray-400 font-mono">
                        #{idx + 1}
                      </span>
                      <input
                        value={q.label}
                        onChange={e => {
                          const newLabel = e.target.value;
                          // Auto-generate ID from label if still matches pattern
                          const wasAutoId = q.id.startsWith("question_") || q.id === slugify(q.label);
                          patch(idx, {
                            label: newLabel,
                            id: wasAutoId ? slugify(newLabel) || q.id : q.id,
                          });
                        }}
                        placeholder="Pytanie (np. Komunikacja)"
                        className="flex-1 rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-sm bg-white dark:bg-gray-900"
                      />
                      <button
                        onClick={() => remove(idx)}
                        className="text-red-400 hover:text-red-600"
                        aria-label="Usuń"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-[11px] text-gray-500 mb-0.5">
                          ID (slug)
                        </label>
                        <input
                          value={q.id}
                          onChange={e => patch(idx, { id: e.target.value })}
                          placeholder="communication"
                          className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-xs bg-white dark:bg-gray-900 font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-gray-500 mb-0.5">
                          Typ
                        </label>
                        <select
                          value={q.type}
                          onChange={e => patch(idx, { type: e.target.value as QType })}
                          className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-xs bg-white dark:bg-gray-900"
                        >
                          {(Object.keys(TYPE_LABELS) as QType[]).map(t => (
                            <option key={t} value={t}>
                              {TYPE_LABELS[t]}
                            </option>
                          ))}
                        </select>
                      </div>
                      <label className="flex items-center gap-1.5 text-xs mt-5">
                        <input
                          type="checkbox"
                          checked={!!q.required}
                          onChange={e => patch(idx, { required: e.target.checked })}
                          className="w-3.5 h-3.5 accent-blue-600"
                        />
                        <span className="text-gray-700 dark:text-gray-300">Wymagane</span>
                      </label>
                    </div>

                    <div>
                      <label className="block text-[11px] text-gray-500 mb-0.5">
                        Opis (podpowiedź dla oceniającego)
                      </label>
                      <input
                        value={q.description ?? ""}
                        onChange={e => patch(idx, { description: e.target.value })}
                        placeholder="np. Oceń jasność i tempo"
                        className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-xs bg-white dark:bg-gray-900"
                      />
                    </div>

                    {q.type === "select" && (
                      <div>
                        <label className="block text-[11px] text-gray-500 mb-0.5">
                          Opcje (po przecinku)
                        </label>
                        <input
                          value={(q.options ?? []).join(", ")}
                          onChange={e =>
                            patch(idx, {
                              options: e.target.value
                                .split(",")
                                .map(s => s.trim())
                                .filter(Boolean),
                            })
                          }
                          placeholder="Junior, Mid, Senior, Lead"
                          className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-xs bg-white dark:bg-gray-900"
                        />
                      </div>
                    )}
                  </li>
                ))}
              </ul>

              {error && (
                <div className="text-sm text-red-700 bg-red-50 dark:bg-red-900/20 rounded p-3">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-gray-200 dark:border-gray-700 sticky bottom-0 bg-white dark:bg-gray-800">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
          >
            Anuluj
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {questions.length === 0 ? "Zapisz pusty" : `Zapisz (${questions.length})`}
          </button>
        </div>
      </div>

      <ScorecardV2
        open={preview}
        onOpenChange={setPreview}
        candidateStageId={0}
        stageId={0}
        stageDefId={stageDefId}
        stageName={title || stageName}
        onSaved={() => setPreview(false)}
      />
    </div>
  );
}
