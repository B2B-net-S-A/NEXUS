"use client";

import { useEffect, useState } from "react";
import { Loader2, Sparkles, X, Save, Plus } from "lucide-react";
import api, { recommendationsApi } from "@/lib/api";

interface Props {
  jobId: number;
  onClose: () => void;
  onSaved: () => void;
}

type Skill = { name: string; level?: string | null };

export function CriteriaPreviewModal({ jobId, onClose, onSaved }: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<"ollama" | "heuristic" | null>(null);

  const [must, setMust] = useState<Skill[]>([]);
  const [nice, setNice] = useState<Skill[]>([]);
  const [newMust, setNewMust] = useState("");
  const [newNice, setNewNice] = useState("");

  useEffect(() => {
    let cancel = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await recommendationsApi.previewCriteria(jobId);
        if (cancel) return;
        setMust([...(r.data.must_skills ?? [])]);
        setNice([...(r.data.nice_skills ?? [])]);
        setSource(r.data.source);
      } catch (e: unknown) {
        if (!cancel) {
          const msg =
            e && typeof e === "object" && "response" in e
              ? ((e as { response?: { data?: { detail?: string } } }).response?.data
                  ?.detail ?? "Błąd generowania")
              : "Błąd generowania";
          setError(msg);
        }
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [jobId]);

  const addMust = () => {
    const n = newMust.trim();
    if (!n) return;
    if (must.some(s => s.name.toLowerCase() === n.toLowerCase())) return;
    setMust(prev => [...prev, { name: n }]);
    setNewMust("");
  };
  const addNice = () => {
    const n = newNice.trim();
    if (!n) return;
    if (nice.some(s => s.name.toLowerCase() === n.toLowerCase())) return;
    setNice(prev => [...prev, { name: n }]);
    setNewNice("");
  };

  const removeMust = (idx: number) =>
    setMust(prev => prev.filter((_, i) => i !== idx));
  const removeNice = (idx: number) =>
    setNice(prev => prev.filter((_, i) => i !== idx));

  const toMust = (idx: number) => {
    setNice(prev => {
      const s = prev[idx];
      if (!s) return prev;
      setMust(m => [...m, s]);
      return prev.filter((_, i) => i !== idx);
    });
  };
  const toNice = (idx: number) => {
    setMust(prev => {
      const s = prev[idx];
      if (!s) return prev;
      setNice(m => [...m, s]);
      return prev.filter((_, i) => i !== idx);
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/api/jobs/${jobId}`, {
        must_skills: must,
        nice_skills: nice,
      });
      onSaved();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
            "Błąd")
          : "Błąd";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="font-semibold flex items-center gap-2 text-gray-900 dark:text-gray-100">
            <Sparkles className="w-5 h-5 text-violet-500" />
            Podgląd kryteriów AI
            {source && (
              <span className="text-xs font-normal text-gray-400">
                ({source === "ollama" ? "Ollama" : "heurystyka"})
              </span>
            )}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-10 gap-3 text-gray-500">
              <Loader2 className="w-5 h-5 animate-spin" />
              Analizuję opis oferty...
            </div>
          ) : (
            <>
              <p className="text-xs text-gray-500">
                Zaproponowane kryteria. Możesz edytować przed zapisem — kliknij ikonkę chip&apos;a żeby
                przesunąć, wpisz własne skille, usuń niepotrzebne.
              </p>

              {/* Must-have */}
              <div className="bg-red-50 dark:bg-red-900/10 rounded-lg p-3 border border-red-200 dark:border-red-800/50">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-medium text-sm text-red-700 dark:text-red-300">
                    Must-have ({must.length})
                  </h4>
                </div>
                <div className="flex flex-wrap gap-2 mb-2">
                  {must.length === 0 && (
                    <span className="text-xs text-gray-400 italic">Brak</span>
                  )}
                  {must.map((s, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 bg-white dark:bg-gray-800 border border-red-300 text-sm px-2 py-0.5 rounded-full"
                    >
                      {s.name}
                      <button
                        onClick={() => toNice(i)}
                        title="Przenieś do nice-to-have"
                        className="text-gray-400 hover:text-blue-600 text-[10px]"
                      >
                        →nice
                      </button>
                      <button
                        onClick={() => removeMust(i)}
                        className="text-gray-400 hover:text-red-600"
                        aria-label="Usuń"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    value={newMust}
                    onChange={e => setNewMust(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addMust();
                      }
                    }}
                    placeholder="Dodaj must-have..."
                    className="flex-1 rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-sm bg-white dark:bg-gray-900"
                  />
                  <button
                    onClick={addMust}
                    className="flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-gray-300 hover:bg-gray-50"
                  >
                    <Plus className="w-3 h-3" />
                    Dodaj
                  </button>
                </div>
              </div>

              {/* Nice-to-have */}
              <div className="bg-blue-50 dark:bg-blue-900/10 rounded-lg p-3 border border-blue-200 dark:border-blue-800/50">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-medium text-sm text-blue-700 dark:text-blue-300">
                    Nice-to-have ({nice.length})
                  </h4>
                </div>
                <div className="flex flex-wrap gap-2 mb-2">
                  {nice.length === 0 && (
                    <span className="text-xs text-gray-400 italic">Brak</span>
                  )}
                  {nice.map((s, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 bg-white dark:bg-gray-800 border border-blue-300 text-sm px-2 py-0.5 rounded-full"
                    >
                      {s.name}
                      <button
                        onClick={() => toMust(i)}
                        title="Przenieś do must-have"
                        className="text-gray-400 hover:text-red-600 text-[10px]"
                      >
                        →must
                      </button>
                      <button
                        onClick={() => removeNice(i)}
                        className="text-gray-400 hover:text-red-600"
                        aria-label="Usuń"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    value={newNice}
                    onChange={e => setNewNice(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addNice();
                      }
                    }}
                    placeholder="Dodaj nice-to-have..."
                    className="flex-1 rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-sm bg-white dark:bg-gray-900"
                  />
                  <button
                    onClick={addNice}
                    className="flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-gray-300 hover:bg-gray-50"
                  >
                    <Plus className="w-3 h-3" />
                    Dodaj
                  </button>
                </div>
              </div>

              {error && (
                <div className="text-sm text-red-700 bg-red-50 dark:bg-red-900/20 rounded p-3">
                  {error}
                </div>
              )}
            </>
          )}
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
            onClick={handleSave}
            disabled={saving || loading}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Zastosuj
          </button>
        </div>
      </div>
    </div>
  );
}
