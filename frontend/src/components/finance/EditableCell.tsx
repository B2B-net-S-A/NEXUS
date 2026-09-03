"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

interface EditableCellProps {
  value: number | null;
  /** Sformatowana treść pokazywana poza trybem edycji. */
  display: React.ReactNode;
  ariaLabel: string;
  /** True gdy pole jest puste PO IMPORCIE (a nie po ręcznym wyczyszczeniu) —
   *  tylko wtedy komórka woła o uzupełnienie. */
  needsCompletion: boolean;
  onSave: (next: number | null) => Promise<void>;
  onError: (msg: string) => void;
  className?: string;
  readOnly?: boolean;
}

/**
 * Komórka edytowana DWUKLIKIEM (pkt 4.4 ticketu).
 *
 * W repo nie ma żadnej edycji dwuklikiem — najbliższy wzorzec to `InlineText`
 * z `OrdersAndContractsTab`, który wchodzi w edycję po kliknięciu ołówka.
 * Semantyka zapisu jest stamtąd przejęta 1:1 (Enter/blur zapisuje, Esc
 * anuluje, brak zmiany nie wysyła żądania); różni się wyłącznie wyzwalacz,
 * bo tabela z dziewięcioma kolumnami nie udźwignęłaby ikony w każdej komórce.
 */
export function EditableCell({
  value,
  display,
  ariaLabel,
  needsCompletion,
  onSave,
  onError,
  className,
  readOnly = false,
}: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  function begin() {
    setDraft(value != null ? String(value) : "");
    setEditing(true);
  }

  async function commit() {
    if (saving) return;
    const next = parseDecimalInput(draft);
    if (next === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(next);
      setEditing(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Nie udało się zapisać");
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <td className={cn("px-3 py-1.5 text-right tabular-nums", className)}>
        <input
          autoFocus
          value={draft}
          inputMode="decimal"
          aria-label={ariaLabel}
          disabled={saving}
          onChange={(e) => setDraft(sanitizeDecimalInput(e.target.value))}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") setEditing(false);
          }}
          className="w-24 rounded border border-primary bg-background px-1.5 py-0.5 text-right text-sm tabular-nums focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
        />
        {saving && (
          <Loader2 className="ml-1 inline h-3 w-3 animate-spin text-muted-foreground" />
        )}
      </td>
    );
  }

  if (readOnly) {
    return (
      <td className={cn("px-3 py-1.5 text-right tabular-nums", className)}>
        {display}
      </td>
    );
  }

  return (
    <td
      onDoubleClick={begin}
      title="Kliknij dwukrotnie, aby edytować"
      className={cn(
        "cursor-cell px-3 py-1.5 text-right tabular-nums",
        needsCompletion && "text-muted-foreground",
        className,
      )}
    >
      {needsCompletion ? (
        <span className="inline-flex items-center gap-1.5 rounded border border-dashed border-destructive/50 px-1.5 py-0.5 text-xs italic">
          Uzupełnij
          <span className="rounded bg-destructive/10 px-1 not-italic text-destructive">
            brak danych
          </span>
        </span>
      ) : (
        display
      )}
    </td>
  );
}
