"use client";

/**
 * Stopka edytora CV z przekazaniem Delivery Leadowi (D6, 14.10.2026).
 *
 * Pokazuje się tylko, gdy wołający podał `handoff` (karta na „Zweryfikowany”,
 * nie tylko do odczytu). Pole uwagi trzyma okno — wpis żyje, dopóki edytor
 * jest otwarty. Reguła przycisków i linii stanu: `lib/cv-editor-handoff.ts`.
 *
 * Edytor CV 3 (PR 3): „Zapisz” → „Gotowe”, „Zapisz i przekaż do DL” →
 * „Gotowe, przekaż do DL” — treść zapisuje się sama, przycisk kończy pracę
 * (ta sama ścieżka: szkic, pola w nawiasach, zatwierdzenie w tle).
 */

import { ArrowRight, Check, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { HANDOFF_REMARK_MAX, type HandoffGate } from "@/lib/cv-editor-handoff";
import { cn } from "@/lib/utils";

export interface CvEditorHandoffBarProps {
  gate: HandoffGate;
  status: string;
  remark: string;
  onRemarkChange: (value: string) => void;
  /** Zapis albo przekazanie w toku. */
  busy: boolean;
  /** Edytor nie jest gotowy (wczytywanie, nowy szkic). */
  disabled: boolean;
  error: string | null;
  onSave: () => void;
  onHandOff: () => void;
  onOverride: () => void;
}

const BLOCKED_HINT =
  "Najpierw popraw rzeczy, które blokują wysyłkę — przepuścić mimo QC może osoba z uprawnieniem wysyłki CV.";

export function CvEditorHandoffBar({
  gate,
  status,
  remark,
  onRemarkChange,
  busy,
  disabled,
  error,
  onSave,
  onHandOff,
  onOverride,
}: CvEditorHandoffBarProps) {
  const blocking = gate.kind === "override" || gate.kind === "blocked";
  const primaryDisabled = disabled || busy || gate.kind === "waiting" || gate.kind === "blocked";
  return (
    <div
      role="group"
      aria-label="Przekazanie Delivery Leadowi"
      data-testid="cv-editor-handoff"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border bg-card px-4 py-2"
    >
      <input
        type="text"
        aria-label="Uwaga dla Delivery Leada (opcjonalnie)"
        placeholder="Uwaga dla Delivery Leada (opcjonalnie)"
        maxLength={HANDOFF_REMARK_MAX}
        value={remark}
        disabled={busy}
        onChange={(event) => onRemarkChange(event.target.value)}
        className="h-8 w-0 min-w-[220px] flex-1 rounded-md border border-input bg-background px-2.5 text-sm placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60"
      />
      <p
        role="status"
        className={cn("text-xs", blocking ? "font-medium text-destructive" : "text-muted-foreground")}
      >
        {status}
      </p>
      {error ? (
        <p role="alert" className="basis-full text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <div className="ml-auto flex flex-none items-center gap-2">
        <Button size="sm" variant="outline" onClick={onSave} disabled={disabled || busy}>
          <Check className="h-3.5 w-3.5 mr-1.5" aria-hidden />
          Gotowe
        </Button>
        {gate.kind === "override" ? (
          <Button size="sm" onClick={onOverride} disabled={primaryDisabled}>
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" aria-hidden /> : null}
            Przekaż mimo uwag…
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={onHandOff}
            disabled={primaryDisabled}
            title={gate.kind === "blocked" ? BLOCKED_HINT : gate.kind === "waiting" ? "Czekam na wynik QC…" : undefined}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" aria-hidden /> : null}
            Gotowe, przekaż do DL
            <ArrowRight className="h-3.5 w-3.5 ml-1.5" aria-hidden />
          </Button>
        )}
      </div>
      {gate.kind === "blocked" ? (
        <p className="basis-full text-[11px] text-muted-foreground">{BLOCKED_HINT}</p>
      ) : null}
    </div>
  );
}
