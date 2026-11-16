"use client";

// Pole „Zmiany w umowie” aneksu z własną nazwą (16.11.2026). Każdy wiersz to
// jedna zmiana: §, ustęp i co się dzieje — formułkę („§ 10 ust. 1 Umowy
// otrzymuje brzmienie”) dopisuje dokument, a pod wierszem widać, jak
// zabrzmi. Gotowe klauzule z rejestru typów dopisują wiersze z treścią
// i nazwę aneksu (gdy pusta); człowiek może je potem zmienić.

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { AnnexChangeRow, AnnexClauseDef, DocumentValue } from "@/lib/api/b2bDocuments";
import {
  ANNEX_CHANGE_OPS,
  EMPTY_ANNEX_CHANGE,
  MAX_ANNEX_CHANGES,
  annexChangeLead,
  annexChangeRows,
  clauseRows,
} from "@/lib/annex-changes";
import { cn } from "@/lib/utils";

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-border bg-card px-2 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring disabled:opacity-50";

export interface AnnexChangesFieldProps {
  id: string;
  value: DocumentValue | undefined;
  onChange: (value: AnnexChangeRow[]) => void;
  clauses?: readonly AnnexClauseDef[];
  /** Wartości do `{klucz}` w klauzulach (paragraf zakazu, klient umowy). */
  clauseVars?: Record<string, string | null | undefined>;
  /** Klauzula ma nazwę aneksu — formularz wpisze ją, gdy pole jest puste. */
  onClauseTitle?: (title: string) => void;
  disabled?: boolean;
  invalid?: boolean;
}

function isBlank(row: AnnexChangeRow): boolean {
  return !row.paragraph.trim() && !row.section.trim() && !row.text.trim();
}

export function AnnexChangesField({
  id,
  value,
  onChange,
  clauses = [],
  clauseVars = {},
  onClauseTitle,
  disabled,
  invalid,
}: AnnexChangesFieldProps) {
  const stored = annexChangeRows(value);
  const rows = stored.length ? stored : [EMPTY_ANNEX_CHANGE];
  const patch = (index: number, next: Partial<AnnexChangeRow>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...next } : row)));

  const applyClause = (clause: AnnexClauseDef) => {
    // Puste wiersze ustępują klauzuli; wpisane zostają.
    const kept = rows.filter((row) => !isBlank(row));
    onChange([...kept, ...clauseRows(clause, clauseVars)].slice(0, MAX_ANNEX_CHANGES));
    onClauseTitle?.(clause.title);
  };

  return (
    <div id={id} className="space-y-3">
      {clauses.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Gotowe klauzule:</span>
          {clauses.map((clause) => (
            <Button
              key={clause.key}
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={() => applyClause(clause)}
            >
              {clause.label}
            </Button>
          ))}
        </div>
      ) : null}

      {rows.map((row, index) => {
        const rowId = `${id}-${index}`;
        const usesParagraph = row.op !== "free";
        return (
          <div
            key={index}
            className={cn(
              "space-y-2 rounded-lg border p-3",
              invalid ? "border-destructive" : "border-border",
            )}
          >
            <div className="grid grid-cols-[4.5rem_4.5rem_minmax(0,1fr)_auto] items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor={`${rowId}-paragraph`} className="text-xs text-muted-foreground">
                  §
                </Label>
                <Input
                  id={`${rowId}-paragraph`}
                  value={row.paragraph}
                  disabled={disabled || !usesParagraph}
                  onChange={(e) => patch(index, { paragraph: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`${rowId}-section`} className="text-xs text-muted-foreground">
                  ust.
                </Label>
                <Input
                  id={`${rowId}-section`}
                  value={row.section}
                  disabled={disabled || !usesParagraph}
                  onChange={(e) => patch(index, { section: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`${rowId}-op`} className="text-xs text-muted-foreground">
                  Co się dzieje
                </Label>
                <select
                  id={`${rowId}-op`}
                  className={SELECT_CLASS}
                  value={row.op}
                  disabled={disabled}
                  onChange={(e) =>
                    patch(index, { op: e.target.value as AnnexChangeRow["op"] })
                  }
                >
                  {ANNEX_CHANGE_OPS.map((op) => (
                    <option key={op.value} value={op.value}>
                      {op.label}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Usuń zmianę ${index + 1}`}
                disabled={disabled || rows.length === 1}
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
            {row.op !== "delete" ? (
              <Textarea
                aria-label={`Treść zmiany ${index + 1}`}
                rows={3}
                placeholder={row.op === "free" ? "Treść punktu aneksu" : "Nowa treść ustępu"}
                value={row.text}
                disabled={disabled}
                onChange={(e) => patch(index, { text: e.target.value })}
              />
            ) : null}
            <p className="text-xs text-muted-foreground">
              W aneksie: <span className="text-foreground">{annexChangeLead(row)}</span>
            </p>
          </div>
        );
      })}

      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || rows.length >= MAX_ANNEX_CHANGES}
        onClick={() => onChange([...rows, EMPTY_ANNEX_CHANGE])}
      >
        <Plus className="mr-1 h-4 w-4" aria-hidden="true" />
        Dodaj zmianę
      </Button>
    </div>
  );
}
