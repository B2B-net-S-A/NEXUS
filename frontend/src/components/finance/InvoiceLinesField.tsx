"use client";

import { useEffect, useId, useState } from "react";
import { AlertTriangle, Check, Copy, Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { InvoiceLine } from "@/lib/api/finance";
import { copyTextToClipboard } from "@/lib/clipboard";
import { formatMoment } from "@/lib/finance-order-changes";
import {
  INVOICE_LINE_MISSING,
  hasMissingInvoiceData,
  invoiceLineSegments,
} from "@/lib/invoice-lines";

const COPIED_MS = 2000;

/**
 * Nordea, Wejścia: gotowa pozycja faktury cyklicznej do skopiowania
 * (ticket 8). Jedna formuła na osobę z tabeli „Consultant(s)”.
 *
 * `[brak]` = pole nieodczytane z PDF-a — ostrzeżenie i ręczna poprawka przed
 * skopiowaniem. Poprawkę zapisuje `onSave` (Admin/Finanse); bez uprawnień
 * da się ją tylko skopiować.
 */
export function InvoiceLinesField({
  lines,
  canSave,
  onSave,
}: {
  lines: InvoiceLine[];
  canSave: boolean;
  onSave?: (line: InvoiceLine, text: string) => Promise<boolean>;
}) {
  if (lines.length === 0) return null;
  return (
    <div className="mt-2 space-y-2">
      {lines.map((line) => (
        <InvoiceLineRow
          key={line.index}
          line={line}
          label={
            lines.length > 1 && line.consultant
              ? `Pozycja faktury — ${line.consultant}`
              : "Pozycja faktury"
          }
          canSave={canSave && Boolean(onSave)}
          onSave={onSave}
        />
      ))}
    </div>
  );
}

function InvoiceLineRow({
  line,
  label,
  canSave,
  onSave,
}: {
  line: InvoiceLine;
  label: string;
  canSave: boolean;
  onSave?: (line: InvoiceLine, text: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(line.text);
  const [saving, setSaving] = useState(false);
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");

  // Po zapisie (albo odświeżeniu danych) szkic idzie za serwerem.
  useEffect(() => {
    if (!editing) setDraft(line.text);
  }, [editing, line.text]);

  useEffect(() => {
    if (copy !== "copied") return;
    const timer = window.setTimeout(() => setCopy("idle"), COPIED_MS);
    return () => window.clearTimeout(timer);
  }, [copy]);

  const shown = editing ? draft : line.text;
  const missing = hasMissingInvoiceData(shown);
  const fieldId = useId();

  async function copyText() {
    setCopy((await copyTextToClipboard(shown)) ? "copied" : "failed");
  }

  async function save() {
    const text = draft.trim();
    if (!onSave || !text || text === line.text || saving) return;
    setSaving(true);
    try {
      if (await onSave(line, text)) setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-md border border-border bg-background px-3 py-2">
      <p
        id={`${fieldId}-label`}
        className="text-xs font-semibold text-muted-foreground"
      >
        {label}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {editing ? (
          <Textarea
            aria-labelledby={`${fieldId}-label`}
            value={draft}
            maxLength={500}
            rows={3}
            autoFocus
            onChange={(event) =>
              // Pozycja faktury to jedna linia — nowe linie z wklejenia znikają.
              setDraft(event.target.value.replace(/[\r\n]+/g, " "))
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (canSave) void save();
              } else if (event.key === "Escape") {
                event.preventDefault();
                setEditing(false);
              }
            }}
            className="min-h-0 basis-full font-mono text-xs"
          />
        ) : (
          <code
            aria-labelledby={`${fieldId}-label`}
            className="min-w-0 flex-1 break-words font-mono text-xs text-foreground"
          >
            {invoiceLineSegments(line.text).map((segment, index) =>
              segment === INVOICE_LINE_MISSING ? (
                <mark
                  key={index}
                  className="rounded-sm bg-warning-muted px-0.5 font-semibold text-warning-muted-foreground"
                >
                  {segment}
                </mark>
              ) : (
                <span key={index}>{segment}</span>
              ),
            )}
          </code>
        )}
        <div
          className={
            editing
              ? "flex items-center gap-1.5"
              : "flex shrink-0 items-center gap-1.5"
          }
        >
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void copyText()}
            aria-label={
              copy === "copied" ? "Skopiowano" : `Kopiuj: ${label.toLowerCase()}`
            }
          >
            {copy === "copied" ? (
              <Check className="h-3.5 w-3.5 text-success" aria-hidden />
            ) : (
              <Copy className="h-3.5 w-3.5" aria-hidden />
            )}
            {copy === "copied" ? "Skopiowano" : "Kopiuj"}
          </Button>
          {editing ? (
            <>
              {canSave ? (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void save()}
                  loading={saving}
                  disabled={!draft.trim() || draft.trim() === line.text}
                >
                  Zapisz
                </Button>
              ) : null}
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setEditing(false)}
                disabled={saving}
              >
                Anuluj
              </Button>
            </>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`Edytuj: ${label.toLowerCase()}`}
              onClick={() => {
                setDraft(line.text);
                setEditing(true);
              }}
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden />
              Edytuj
            </Button>
          )}
        </div>
      </div>
      {missing ? (
        <p
          role="note"
          className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-medium text-warning-muted-foreground"
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          Uzupełnij brakujące dane w formule
        </p>
      ) : null}
      {copy === "failed" ? (
        <p role="alert" className="mt-1.5 text-xs text-destructive">
          Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie.
        </p>
      ) : null}
      {editing && !canSave ? (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Poprawki nie zapiszesz — możesz ją skopiować.
        </p>
      ) : null}
      {!editing && line.edited_at ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Poprawione ręcznie
          {line.edited_by_name ? ` przez ${line.edited_by_name}` : ""},{" "}
          {formatMoment(line.edited_at)}
        </p>
      ) : null}
    </div>
  );
}
