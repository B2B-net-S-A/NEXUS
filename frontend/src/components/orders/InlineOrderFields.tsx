"use client";

// Prymitywy edycji inline zamówień — wyniesione z `OrdersAndContractsTab`,
// żeby zakładka „Draft (do uzupełnienia)" klientów wielo-konsultantowych
// (BIK/BNP) edytowała te same 4 pola DOKŁADNIE tym samym widgetem, którym
// robi to widok jednoosobowy. Dwie kopie click-to-edit rozjechałyby się przy
// pierwszej zmianie (skróty klawiszowe, save-on-blur, sanitizacja).

import { useState } from "react";
import { Calendar, Check, Pencil, X } from "lucide-react";

import {
  DATE_PATTERN,
  DATE_PLACEHOLDER,
  normalizeDateInput,
} from "@/lib/dateInput";

/** Data kalendarzowa (YYYY-MM-DD) z wartości ISO — bez strefy czasowej. */
export function dateOnly(value: string | null): string | null {
  return value ? value.slice(0, 10) : null;
}

export function fmtDate(d: string | null): string | null {
  if (!d) return null;
  return d.slice(0, 10);
}

interface InlineTextProps {
  /** Raw current value used to prefill the editor. */
  value: string;
  /** Rendered value while not editing. */
  display: React.ReactNode;
  ariaLabel: string;
  onSave: (raw: string) => Promise<void>;
  onError: (msg: string) => void;
  placeholder?: string;
  inputMode?: "text" | "decimal";
  sanitize?: (raw: string) => string;
  /** Czy pole może wejść w tryb edycji. Widok wartości pozostaje bez zmian. */
  editable?: boolean;
}

/** Click-to-edit text/number field. Enter/blur saves, Esc cancels. */
export function InlineText({
  value,
  display,
  ariaLabel,
  onSave,
  onError,
  placeholder,
  inputMode = "text",
  sanitize,
  editable = true,
}: InlineTextProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);

  function begin() {
    setDraft(value);
    setEditing(true);
  }

  async function commit() {
    if (saving) return;
    if (draft.trim() === value.trim()) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(draft.trim());
      setEditing(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Nie udało się zapisać");
    } finally {
      setSaving(false);
    }
  }

  if (!editable || !editing) {
    return (
      <span className="inline-flex items-center gap-1">
        {display}
        {editable ? (
          <button
            type="button"
            onClick={begin}
            aria-label={`Edytuj: ${ariaLabel}`}
            className="text-muted-foreground/50 hover:text-violet-600 transition-colors"
          >
            <Pencil className="w-3 h-3" />
          </button>
        ) : null}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1">
      <input
        autoFocus
        value={draft}
        inputMode={inputMode}
        placeholder={placeholder}
        disabled={saving}
        aria-label={ariaLabel}
        onChange={(e) =>
          setDraft(sanitize ? sanitize(e.target.value) : e.target.value)
        }
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        onBlur={commit}
        className="px-1.5 py-0.5 border border-violet-300 rounded bg-background text-sm w-full max-w-[11rem]"
      />
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={commit}
        disabled={saving}
        aria-label="Zapisz"
        className="text-green-600 hover:text-green-700 disabled:opacity-50"
      >
        <Check className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setEditing(false)}
        disabled={saving}
        aria-label="Anuluj"
        className="text-muted-foreground hover:text-destructive disabled:opacity-50"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </span>
  );
}

interface InlinePeriodProps {
  startDate: string | null;
  endDate: string | null;
  onSave: (start: string | null, end: string | null) => Promise<void>;
  onError: (msg: string) => void;
  /** Czy okres może wejść w tryb edycji. */
  editable?: boolean;
}

/** Click-to-edit order period (start → end / bezterminowo). */
export function InlinePeriod({
  startDate,
  endDate,
  onSave,
  onError,
  editable = true,
}: InlinePeriodProps) {
  const [editing, setEditing] = useState(false);
  const [start, setStart] = useState(dateOnly(startDate) ?? "");
  const [end, setEnd] = useState(dateOnly(endDate) ?? "");
  const [saving, setSaving] = useState(false);

  function begin() {
    setStart(dateOnly(startDate) ?? "");
    setEnd(dateOnly(endDate) ?? "");
    setEditing(true);
  }

  async function commit() {
    if (saving) return;
    const nextStart = start.trim() ? normalizeDateInput(start) : null;
    const nextEnd = end.trim() ? normalizeDateInput(end) : null;
    if (nextStart === dateOnly(startDate) && nextEnd === dateOnly(endDate)) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(nextStart, nextEnd);
      setEditing(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Nie udało się zapisać");
    } finally {
      setSaving(false);
    }
  }

  if (!editable || !editing) {
    return (
      <span className="inline-flex items-center gap-1">
        <Calendar className="w-3 h-3" />
        {/* „okres:", nie „okres zamówienia:" — ta etykieta stoi w jednej
            zawijającej się linii obok numeru zamówienia i obu stawek, a
            poprzedza ją ikona kalendarza, więc słowo „zamówienia" niczego tu
            nie doprecyzowuje, a wypychało stawki do kolejnego wiersza. Pełne
            brzmienie niesie `title`. */}
        <span title="Okres zamówienia">
          okres: {fmtDate(startDate) ?? "—"} →{" "}
          {fmtDate(endDate) ?? "bezterminowo"}
        </span>
        {editable ? (
          <button
            type="button"
            onClick={begin}
            aria-label="Edytuj: okres zamówienia"
            className="text-muted-foreground/50 hover:text-violet-600 transition-colors"
          >
            <Pencil className="w-3 h-3" />
          </button>
        ) : null}
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1 flex-wrap"
      onBlur={(e) => {
        // Match InlineText's save-on-blur: commit when focus leaves the whole
        // widget (outside click / tab-away), but stay put when moving between
        // the two date inputs or to the save/cancel buttons (they keep focus
        // via onMouseDown preventDefault, so they don't count as "leaving").
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) commit();
      }}
    >
      <span className="text-muted-foreground" title="Okres zamówienia">
        okres:
      </span>
      <input
        autoFocus
        type="text"
        inputMode="numeric"
        pattern={DATE_PATTERN}
        placeholder={DATE_PLACEHOLDER}
        value={start}
        disabled={saving}
        aria-label="Data od"
        onChange={(e) => setStart(e.target.value)}
        onBlur={(e) => setStart(normalizeDateInput(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        className="px-1.5 py-0.5 border border-violet-300 rounded bg-background text-sm w-28"
      />
      <span>→</span>
      <input
        type="text"
        inputMode="numeric"
        pattern={DATE_PATTERN}
        placeholder="bezterminowo"
        value={end}
        disabled={saving}
        aria-label="Data do (puste = bezterminowo)"
        onChange={(e) => setEnd(e.target.value)}
        onBlur={(e) => setEnd(normalizeDateInput(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        className="px-1.5 py-0.5 border border-violet-300 rounded bg-background text-sm w-28"
      />
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={commit}
        disabled={saving}
        aria-label="Zapisz"
        className="text-green-600 hover:text-green-700 disabled:opacity-50"
      >
        <Check className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setEditing(false)}
        disabled={saving}
        aria-label="Anuluj"
        className="text-muted-foreground hover:text-destructive disabled:opacity-50"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </span>
  );
}
