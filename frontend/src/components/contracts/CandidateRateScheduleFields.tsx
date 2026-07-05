"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { sanitizeDecimalInput } from "@/lib/utils";
import {
  formatEffectiveTo,
  type RateScheduleRow,
} from "@/lib/contract-rate-schedule";

interface Props {
  rows: RateScheduleRow[];
  onChange: (rows: RateScheduleRow[]) => void;
  /** Data rozpoczęcia kontraktu — domyślne „Obowiązuje od" pierwszego etapu. */
  startDate: string;
}

/**
 * Progresywna stawka kandydata — lista etapów `{ Stawka, Obowiązuje od,
 * Obowiązuje do }` wprowadzana przy tworzeniu kontraktu. „Obowiązuje do" jest
 * read-only i wyliczane z daty startu kolejnego etapu (patrz
 * `formatEffectiveTo`). Współdzielone przez `/contracts/new` i rejestr per-klient.
 */
export function CandidateRateScheduleFields({ rows, onChange, startDate }: Props) {
  const patchRow = (idx: number, patch: Partial<RateScheduleRow>) =>
    onChange(rows.map((row, i) => (i === idx ? { ...row, ...patch } : row)));

  const addRow = () => onChange([...rows, { rate: "", effectiveFrom: "" }]);

  const removeRow = (idx: number) =>
    onChange(rows.filter((_, i) => i !== idx));

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Label className="block">Stawka kandydata</Label>
        <span className="text-xs text-muted-foreground">
          Możesz zaplanować progresję stawki — system zastosuje aktualną od
          wskazanej daty.
        </span>
      </div>

      <div className="space-y-2">
        {rows.map((row, idx) => (
          <div key={idx} className="flex items-end gap-2">
            <div className="flex-1">
              {idx === 0 && (
                <span className="mb-1 block text-xs text-muted-foreground">
                  Stawka
                </span>
              )}
              <Input
                type="text"
                inputMode="decimal"
                value={row.rate}
                onChange={(e) =>
                  patchRow(idx, { rate: sanitizeDecimalInput(e.target.value) })
                }
                placeholder="np. 215,60"
              />
            </div>
            <div className="flex-1">
              {idx === 0 && (
                <span className="mb-1 block text-xs text-muted-foreground">
                  Obowiązuje od
                </span>
              )}
              <Input
                type="date"
                value={row.effectiveFrom}
                onChange={(e) => patchRow(idx, { effectiveFrom: e.target.value })}
                placeholder={idx === 0 ? "= data rozpoczęcia" : ""}
              />
            </div>
            <div className="flex-1">
              {idx === 0 && (
                <span className="mb-1 block text-xs text-muted-foreground">
                  Obowiązuje do
                </span>
              )}
              <Input
                type="text"
                readOnly
                tabIndex={-1}
                value={formatEffectiveTo(rows, startDate, idx)}
                className="bg-muted/40 text-muted-foreground"
                aria-label="Obowiązuje do (wyliczane automatycznie)"
              />
            </div>
            {idx > 0 ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                title="Usuń etap stawki"
                onClick={() => removeRow(idx)}
              >
                <X className="h-4 w-4" />
              </Button>
            ) : (
              <span className="w-9 shrink-0" aria-hidden />
            )}
          </div>
        ))}
      </div>

      <Button type="button" variant="outline" size="sm" onClick={addRow}>
        + Dodaj stawkę progresywną
      </Button>

      {rows[0]?.effectiveFrom === "" && (
        <p className="text-xs text-muted-foreground">
          Pierwszy etap bez daty obowiązuje od daty rozpoczęcia kontraktu.
        </p>
      )}
    </div>
  );
}
