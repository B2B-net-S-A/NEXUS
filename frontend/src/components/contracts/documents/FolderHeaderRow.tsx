"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Folder, Pencil, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { filesLabel, formatBytes, type FolderSection } from "@/lib/contract-document-folders";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";

interface Props {
  folder: FolderSection;
  expanded: boolean;
  readOnly: boolean;
  onToggle: () => void;
  onRename: (name: string) => Promise<boolean>;
  onDelete: () => void;
}

/**
 * Wiersz folderu: nazwa, liczba plików, łączny rozmiar, data założenia,
 * „Zmień nazwę” (w wierszu: Enter zapisuje, Esc anuluje) i „Usuń”.
 * Folder „Zamówienia” ma oznaczenie „automatyczny” i nie ma „Usuń”.
 */
export function FolderHeaderRow({
  folder,
  expanded,
  readOnly,
  onToggle,
  onRename,
  onDelete,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(folder.name);
  const [saving, setSaving] = useState(false);

  const startEdit = () => {
    setDraft(folder.name);
    setEditing(true);
  };
  const save = async () => {
    const name = draft.trim();
    if (!name || name === folder.name) {
      setEditing(false);
      return;
    }
    setSaving(true);
    const ok = await onRename(name);
    setSaving(false);
    if (ok) setEditing(false);
  };

  const Chevron = expanded ? ChevronDown : ChevronRight;
  const colSpanBefore = readOnly ? 0 : 1;

  return (
    <tr className="border-t border-border bg-muted/30">
      {colSpanBefore > 0 && <td className="w-10 pl-4 pr-0" />}
      <td className="sticky left-0 z-10 bg-muted/30 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={`${expanded ? "Zwiń" : "Rozwiń"} folder ${folder.name}`}
            className="grid h-6 w-6 shrink-0 place-items-center rounded hover:bg-muted"
          >
            <Chevron className="h-4 w-4" />
          </button>
          <Folder className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          {editing ? (
            <form
              className="flex min-w-0 flex-1 items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              <label className="sr-only" htmlFor={`folder-name-${folder.id}`}>
                Nowa nazwa folderu
              </label>
              <input
                id={`folder-name-${folder.id}`}
                value={draft}
                maxLength={120}
                autoFocus
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setEditing(false);
                }}
                className="h-8 w-0 min-w-0 max-w-sm flex-1 rounded-md border border-primary bg-card px-2 text-sm font-semibold"
              />
              <Button type="submit" size="sm" loading={saving}>
                Zapisz
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Anuluj
              </Button>
            </form>
          ) : (
            <button
              type="button"
              onClick={onToggle}
              className="min-w-0 truncate text-left font-semibold"
            >
              {folder.name}
              <span className="ml-1.5 font-normal text-muted-foreground">
                · {folder.rows.length === 0 ? "pusty" : filesLabel(folder.rows.length)}
              </span>
            </button>
          )}
          {folder.auto && !editing && (
            <Badge variant="info" size="sm" title="Nowe zamówienia trafiają tu same">
              automatyczny
            </Badge>
          )}
        </div>
      </td>
      <td className="px-4 py-2.5 text-muted-foreground">Folder</td>
      <td className="whitespace-nowrap px-4 py-2.5 text-muted-foreground tabular-nums">
        {formatBytes(folder.totalBytes) || "—"}
      </td>
      <td className="px-4 py-2.5 text-muted-foreground">—</td>
      <td className="px-4 py-2.5 text-xs text-muted-foreground">
        {folder.createdAt ? formatDate(folder.createdAt) : "—"}
      </td>
      <td className="px-4 py-2.5 text-right">
        {!readOnly && !editing && (
          <div className="inline-flex gap-1">
            <button
              type="button"
              onClick={startEdit}
              className="rounded p-1.5 text-muted-foreground hover:bg-muted pointer-coarse:p-2.5"
              title="Zmień nazwę"
              aria-label={`Zmień nazwę folderu ${folder.name}`}
            >
              <Pencil className="h-4 w-4" />
            </button>
            {!folder.auto && (
              <button
                type="button"
                onClick={onDelete}
                className="rounded p-1.5 text-destructive hover:bg-destructive/10 pointer-coarse:p-2.5"
                title="Usuń folder"
                aria-label={`Usuń folder ${folder.name}`}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}
