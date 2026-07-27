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
      console.error("saved-searches load failed: ", e);
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
      console.error("saved-search save failed: ", e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Usunąć filtr ? ")) return;
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
          className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg border border-border dark:border-border bg-card dark:bg-muted hover:bg-muted dark:hover:bg-muted"
          data-testid="saved-searches-toggle"
        >
          <Bookmark className="w-3.5 h-3.5 text-primary" />
          Filtry
          {items.length > 0 && (
            <span className="ml-1 text-[10px] bg-primary/15 text-primary px-1.5 py-0.5 rounded-full">
              {items.length}
            </span>
          )}
          <ChevronDown className="w-3 h-3" />
        </button>
        <button
          onClick={() => setShowSave(v => !v)}
          title="Zapisz aktualne filtry"
          aria-label="Zapisz aktualne filtry"
          className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg border border-border dark:border-border bg-card dark:bg-muted hover:bg-muted dark:hover:bg-muted"
        >
          <BookmarkPlus className="w-3.5 h-3.5 text-emerald-500" />
        </button>
      </div>

      {open && (
        <div className="absolute z-30 mt-1 left-0 w-72 rounded-lg bg-card dark:bg-muted shadow-xl border border-border dark:border-border py-1 max-h-80 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center py-4">
              <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
            </div>
          ) : items.length === 0 ? (
            <p className="px-3 py-3 text-xs text-muted-foreground">
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
                    className="w-full px-3 py-2 text-left text-sm hover:bg-muted dark:hover:bg-muted flex items-start gap-2 group"
                  >
                    <Bookmark className="w-3.5 h-3.5 text-primary mt-0.5 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-foreground dark:text-foreground">
                          {ss.name}
                        </span>
                        {ss.shared && (
                          <span className="text-[10px] text-emerald-600 font-semibold">
                            ∗współdzielony
                          </span>
                        )}
                      </div>
                      {ss.description && (
                        <p className="text-[11px] text-muted-foreground truncate">
                          {ss.description}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={e => handleDelete(ss.id, e)}
                      className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
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
        <div className="absolute z-30 mt-1 left-0 w-72 rounded-lg bg-card dark:bg-muted shadow-xl border border-border dark:border-border p-3 space-y-2">
          <p className="text-xs font-medium text-foreground dark:text-muted-foreground">
            Zapisz aktualne filtry
          </p>
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="Nazwa filtru (np. Senior PL)"
            className="w-full rounded border border-border dark:border-border px-2 py-1.5 text-sm bg-card dark:bg-card"
            autoFocus
          />
          <label className="flex items-center gap-2 text-xs text-muted-foreground dark:text-muted-foreground">
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
              className="text-xs px-2 py-1 text-muted-foreground hover:text-foreground"
            >
              Anuluj
            </button>
            <button
              onClick={handleSave}
              disabled={!newName.trim() || saving}
              className="flex items-center gap-1 text-xs px-2.5 py-1 bg-primary text-white rounded hover:bg-primary/90 disabled:opacity-50"
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
