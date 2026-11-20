"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { DocIcon } from "./DocIcon";

/** Pozycja menu wykonana po zamknięciu menu — okno otwarte w trakcie zamykania menu gubiło fokus. */
function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

interface Props {
  label: string;
  /** Folder założony przez ludzi (ikona folderu, „Rozwiń folder …”) albo grupa po rodzaju. */
  isFolder: boolean;
  colSpan: number;
  open: boolean;
  /** Pliki w grupie i — przy wyszukiwaniu — ile z nich pasuje. */
  total: number;
  matching: number | null;
  /** Podpowiedź po najechaniu na nazwę grupy. */
  hint?: string;
  /** Dopisek po prawej: archiwum, rozmiar i data założenia folderu, folder automatyczny. */
  note?: string;
  canRename: boolean;
  canDelete: boolean;
  onToggle: () => void;
  onRename: (name: string) => Promise<boolean>;
  onDelete: () => void;
}

/**
 * Nagłówek grupy w tabeli dokumentów: zwijanie, nazwa, liczba plików
 * i dopisek. Folder ma w „⋯” „Zmień nazwę” (w wierszu: Enter zapisuje,
 * Esc anuluje) i „Usuń folder…”; grupa zamówień (dawny automatyczny folder
 * „Zamówienia”) tylko „Zmień nazwę”. Menu widać po najechaniu albo z klawiatury.
 */
export function DocumentGroupHeader({
  label,
  isFolder,
  colSpan,
  open,
  total,
  matching,
  hint,
  note,
  canRename,
  canDelete,
  onToggle,
  onRename,
  onDelete,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(label);
  const [saving, setSaving] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const startEdit = () => {
    setDraft(label);
    setEditing(true);
  };

  const save = async () => {
    const name = draft.trim();
    if (!name || name === label) {
      setEditing(false);
      return;
    }
    setSaving(true);
    const ok = await onRename(name);
    setSaving(false);
    if (ok) setEditing(false);
  };

  const what = isFolder ? "folder" : "grupę";

  return (
    <tr className="group/header h-10 border-b border-border/60 bg-muted/30">
      <th scope="colgroup" colSpan={colSpan} className="px-4 py-1.5 text-left font-normal">
        <div className="flex min-w-0 items-center justify-between gap-3">
          {editing ? (
            <form
              className="flex min-w-0 flex-1 items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              <label className="sr-only" htmlFor={inputId}>
                Nowa nazwa folderu
              </label>
              <input
                id={inputId}
                ref={inputRef}
                value={draft}
                maxLength={120}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setEditing(false);
                }}
                className="h-8 w-0 min-w-0 max-w-sm flex-1 rounded-md border border-primary bg-card px-2 text-[13px] font-semibold text-foreground focus:outline-hidden"
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
              aria-expanded={open}
              aria-label={`${open ? "Zwiń" : "Rozwiń"} ${what} ${label}`}
              title={hint}
              className="-ml-1 inline-flex min-w-0 items-center gap-1.5 rounded-md px-1 py-0.5 text-[13px] font-semibold text-foreground hover:bg-muted"
            >
              {open ? (
                <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              ) : (
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              )}
              {isFolder && <DocIcon group="folder" />}
              <span className="truncate">{label}</span>
              <span className="rounded-full bg-muted px-1.5 text-[11px] font-medium tabular-nums text-muted-foreground">
                {matching != null ? `${matching} z ${total}` : total}
              </span>
            </button>
          )}
          {!editing && (note || canRename || canDelete) && (
            <div className="flex min-w-0 items-center gap-1.5">
              {note && <span className="truncate text-[12px] text-muted-foreground">{note}</span>}
              {(canRename || canDelete) && (
                <div
                  className={cn(
                    "transition-opacity",
                    !menuOpen &&
                      "pointer-fine:opacity-0 pointer-fine:group-hover/header:opacity-100 focus-within:opacity-100",
                  )}
                >
                  <DropdownMenu modal={false} onOpenChange={setMenuOpen}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        className="-my-1"
                        title={isFolder ? "Akcje folderu" : "Akcje grupy"}
                        aria-label={`${isFolder ? "Akcje folderu" : "Akcje grupy"} ${label}`}
                      >
                        <MoreHorizontal className="size-4" aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="min-w-44">
                      {canRename && (
                        <DropdownMenuItem onSelect={() => deferMenuAction(startEdit)}>Zmień nazwę</DropdownMenuItem>
                      )}
                      {canDelete && (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() => deferMenuAction(onDelete)}
                            className="text-muted-foreground focus:bg-destructive/10 focus:text-destructive"
                          >
                            Usuń folder…
                          </DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              )}
            </div>
          )}
        </div>
      </th>
    </tr>
  );
}
