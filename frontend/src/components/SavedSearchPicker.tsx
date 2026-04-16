"use client";

import { useEffect, useState } from "react";
import { BookmarkPlus, Bookmark, Loader2, Save, Trash2, ChevronDown } from "lucide-react";
import { savedSearchesApi, type SavedSearchRow } from "@/lib/api";

interface Props {
  entity: string;
  currentFilters: Record<string, unknown>;
  onApply: (filters: Record<string, unknown>) => void;
}

export function SavedSearchPicker({ entity, currentFilters, onApply }: Props) {
  const [items, setItems] = useState<SavedSearchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [showSave, setShowSave] = useState(false);
  const [newName, setNewName] = useState("");
  const [shared, setShared] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await savedSearchesApi.list(entity);
      setItems(r.data);
    } catch (e) {
      console.error("saved-searches load failed:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity]);

  const handleSave = async () => {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      await savedSearchesApi.create({
        name: newName.trim(),
        entity,
        filters: currentFilters,
        shared,
      });
      setNewName("");
      setShared(false);
      setShowSave(false);
      await load();
    } catch (e) {
      console.error("saved-search save failed:", e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Usunąć filtr?")) return;
    try {
      await savedSearchesApi.delete(id);
      await load();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="relative">
      <div className="flex gap-1.5 items-center">
        <button
          onClick={() => setOpen(v => !v)}
          className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700"
          data-testid="saved-searches-toggle"
        >
          <Bookmark className="w-3.5 h-3.5 text-blue-500" />
          Filtry
          {items.length > 0 && (
            <span className="ml-1 text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">
              {items.length}
            </span>
          )}
          <ChevronDown className="w-3 h-3" />
        </button>
        <button
          onClick={() => setShowSave(v => !v)}
          title="Zapisz aktualne filtry"
          aria-label="Zapisz aktualne filtry"
          className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700"
        >
          <BookmarkPlus className="w-3.5 h-3.5 text-emerald-500" />
        </button>
      </div>

      {open && (
        <div className="absolute z-30 mt-1 left-0 w-72 rounded-lg bg-white dark:bg-gray-800 shadow-xl border border-gray-200 dark:border-gray-700 py-1 max-h-80 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center py-4">
              <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
            </div>
          ) : items.length === 0 ? (
            <p className="px-3 py-3 text-xs text-gray-500">
              Brak zapisanych filtrów. Kliknij <BookmarkPlus className="inline w-3 h-3" /> aby zapisać aktualne.
            </p>
          ) : (
            <ul>
              {items.map(ss => (
                <li key={ss.id}>
                  <button
                    onClick={() => {
                      onApply(ss.filters ?? {});
                      setOpen(false);
                    }}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700 flex items-start gap-2 group"
                  >
                    <Bookmark className="w-3.5 h-3.5 text-blue-400 mt-0.5 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-gray-900 dark:text-gray-100">
                          {ss.name}
                        </span>
                        {ss.shared && (
                          <span className="text-[10px] text-emerald-600 font-semibold">
                            ∗współdzielony
                          </span>
                        )}
                      </div>
                      {ss.description && (
                        <p className="text-[11px] text-gray-400 truncate">
                          {ss.description}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={e => handleDelete(ss.id, e)}
                      className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 transition-opacity"
                      aria-label="Usuń filtr"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {showSave && (
        <div className="absolute z-30 mt-1 left-0 w-72 rounded-lg bg-white dark:bg-gray-800 shadow-xl border border-gray-200 dark:border-gray-700 p-3 space-y-2">
          <p className="text-xs font-medium text-gray-700 dark:text-gray-200">
            Zapisz aktualne filtry
          </p>
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="Nazwa filtru (np. Senior PL)"
            className="w-full rounded border border-gray-300 dark:border-gray-600 px-2 py-1.5 text-sm bg-white dark:bg-gray-900"
            autoFocus
          />
          <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
            <input
              type="checkbox"
              checked={shared}
              onChange={e => setShared(e.target.checked)}
              className="w-3.5 h-3.5 accent-blue-600"
            />
            Udostępnij zespołowi
          </label>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowSave(false)}
              className="text-xs px-2 py-1 text-gray-500 hover:text-gray-700"
            >
              Anuluj
            </button>
            <button
              onClick={handleSave}
              disabled={!newName.trim() || saving}
              className="flex items-center gap-1 text-xs px-2.5 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
              Zapisz
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
