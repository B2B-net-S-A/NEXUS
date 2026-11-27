"use client";

/**
 * 0762 (decyzje Artura 23.11.2026) — ustawienie rekrutacji „Każda osoba podpisuje umowę
 * przedwstępną przed <etap>” z przełącznikiem „Zatrzymaj kartę do podpisu”.
 * Ten sam edytor na `/jobs/new` (sekcja „Warunki”) i w nagłówku rekrutacji.
 */

import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { PreContractRuleStage } from "@/lib/api/preContracts";
import { RULE_STAGE_OPTIONS } from "@/lib/pre-contract-stop";

export interface PreContractRuleDraft {
  needed_before: PreContractRuleStage;
  stop: boolean;
}

interface PreContractRuleEditorProps {
  value: PreContractRuleDraft | null;
  onChange: (next: PreContractRuleDraft | null) => void;
  idPrefix: string;
  disabled?: boolean;
}

export function PreContractRuleEditor({ value, onChange, idPrefix, disabled = false }: PreContractRuleEditorProps) {
  return (
    <div className="flex flex-col gap-3">
      <label htmlFor={`${idPrefix}-on`} className="flex items-start gap-2 text-sm">
        <Checkbox
          id={`${idPrefix}-on`}
          checked={value != null}
          disabled={disabled}
          onCheckedChange={(v) => onChange(v === true ? { needed_before: "cv_sent", stop: true } : null)}
          className="mt-0.5"
        />
        <span>
          <span className="font-medium">Każda osoba podpisuje umowę przedwstępną</span>
          <span className="block text-xs text-muted-foreground">
            Prośba zakłada się sama, gdy osoba wejdzie na „Przygotowanie CV”; wystawia rekruter prowadzący.
          </span>
        </span>
      </label>

      {value ? (
        <div className="flex flex-col gap-3 border-l-2 border-border pl-4">
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">Na jakim etapie musi być podpisana</p>
            <RadioGroup
              value={value.needed_before}
              onValueChange={(v) => onChange({ ...value, needed_before: v as PreContractRuleStage })}
              aria-label="Na jakim etapie musi być podpisana"
              className="flex flex-wrap gap-2"
            >
              {RULE_STAGE_OPTIONS.map((o) => (
                <label
                  key={o.value}
                  htmlFor={`${idPrefix}-${o.value}`}
                  className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
                >
                  <RadioGroupItem id={`${idPrefix}-${o.value}`} value={o.value} disabled={disabled} />
                  {o.label}
                </label>
              ))}
            </RadioGroup>
          </div>
          <label htmlFor={`${idPrefix}-stop`} className="flex items-start gap-2 text-sm" data-tour="pre-contract.rule.stop">
            <Checkbox
              id={`${idPrefix}-stop`}
              checked={value.stop}
              disabled={disabled}
              onCheckedChange={(v) => onChange({ ...value, stop: v === true })}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">Zatrzymaj kartę do podpisu</span>
              <span className="block text-xs text-muted-foreground">
                {value.stop
                  ? "Bez podpisu obu stron osoba nie przejdzie na ten etap ani dalej — także u Delivery Leada. Wyjątek dla jednej osoby: panel osoby › Umowa."
                  : "Brak umowy tylko ostrzega (plakietka i dzwonek), ruch przechodzi."}
              </span>
            </span>
          </label>
        </div>
      ) : null}
    </div>
  );
}
