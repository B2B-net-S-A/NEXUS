"use client";

/**
 * Edytor „Procesu u klienta” (18.11.2026) — ten sam w okienku nagłówka
 * rekrutacji i w `/jobs/new`. Kontrolowany: wartość i zmiany trzyma rodzic.
 */

import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  FORMAT_LABEL,
  MAX_STEPS,
  DURATION_MAX_CHARS,
  PROCESS_PRESETS,
  STEP_LABEL,
  matchingPreset,
  parseWorkdays,
  type ClientProcessInput,
  type ProcessStep,
  type ProcessStepFormat,
  type ProcessStepKind,
} from "@/lib/job-client-process";
import { cn } from "@/lib/utils";

const FIELD_CLASS =
  "h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground focus:border-primary focus:outline-hidden";

interface ClientProcessEditorProps {
  value: ClientProcessInput;
  onChange: (next: ClientProcessInput) => void;
  /** Prefiks identyfikatorów pól (dwa edytory na jednej stronie). */
  idPrefix: string;
}

export function ClientProcessEditor({ value, onChange, idPrefix }: ClientProcessEditorProps) {
  const active = matchingPreset(value.steps);
  const [daysText, setDaysText] = useState(
    value.decision_workdays != null ? String(value.decision_workdays) : "",
  );
  // Wartość z zewnątrz (gotowy układ, „Użyj” podpowiedzi) nadpisuje pole.
  useEffect(() => {
    const parsed = parseWorkdays(daysText);
    if (parsed !== "invalid" && parsed !== value.decision_workdays) {
      setDaysText(value.decision_workdays != null ? String(value.decision_workdays) : "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tylko zmiana z zewnątrz
  }, [value.decision_workdays]);
  const daysInvalid = parseWorkdays(daysText) === "invalid";

  const setSteps = (steps: ProcessStep[]) => onChange({ ...value, steps });
  const update = (index: number, patch: Partial<ProcessStep>) =>
    setSteps(value.steps.map((step, i) => (i === index ? { ...step, ...patch } : step)));

  return (
    <div className="flex flex-col gap-3" data-testid="client-process-editor">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Gotowe układy etapów">
        {PROCESS_PRESETS.map((preset) => (
          <button
            key={preset.key}
            type="button"
            aria-pressed={active === preset.key}
            onClick={() => setSteps(preset.steps.map((s) => ({ ...s })))}
            className={cn(
              "h-7 rounded-full border px-3 text-xs focus-visible:outline-2 focus-visible:outline-primary",
              active === preset.key
                ? "border-primary bg-primary/10 font-medium text-primary"
                : "border-border hover:bg-muted",
            )}
          >
            {preset.label}
          </button>
        ))}
      </div>

      {value.steps.length > 0 ? (
        <ol className="flex flex-col gap-2">
          {value.steps.map((step, index) => (
            <li key={index} className="flex items-center gap-1.5">
              <span className="w-4 shrink-0 text-xs text-muted-foreground">{index + 1}.</span>
              <select
                aria-label={`Etap ${index + 1}: rodzaj`}
                className={cn(FIELD_CLASS, "w-[178px] shrink-0")}
                value={step.kind}
                onChange={(e) => update(index, { kind: e.target.value as ProcessStepKind })}
              >
                {Object.entries(STEP_LABEL).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <select
                aria-label={`Etap ${index + 1}: forma`}
                className={cn(FIELD_CLASS, "w-[92px] shrink-0")}
                value={step.format}
                onChange={(e) => update(index, { format: e.target.value as ProcessStepFormat })}
              >
                {Object.entries(FORMAT_LABEL).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <input
                aria-label={`Etap ${index + 1}: czas`}
                className={cn(FIELD_CLASS, "w-0 min-w-0 flex-1")}
                value={step.duration}
                maxLength={DURATION_MAX_CHARS}
                onChange={(e) => update(index, { duration: e.target.value })}
                placeholder="czas, np. 60 min"
              />
              <Button
                type="button"
                size="icon-sm"
                variant="quiet"
                aria-label={`Usuń etap ${index + 1}`}
                onClick={() => setSteps(value.steps.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-xs text-muted-foreground">
          Wybierz układ powyżej albo dodaj etapy po kolei.
        </p>
      )}

      {value.steps.length < MAX_STEPS ? (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="self-start gap-1"
          onClick={() =>
            setSteps([...value.steps, { kind: "tech_interview", format: "remote", duration: "" }])
          }
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          Dodaj etap
        </Button>
      ) : null}

      <div className="flex flex-col gap-1">
        <label htmlFor={`${idPrefix}-decision`} className="flex items-center gap-2 text-sm">
          Decyzja klienta w ciągu
          <input
            id={`${idPrefix}-decision`}
            className={cn(FIELD_CLASS, "w-14 text-center", daysInvalid && "border-destructive")}
            value={daysText}
            inputMode="numeric"
            aria-invalid={daysInvalid || undefined}
            onChange={(e) => {
              setDaysText(e.target.value);
              const parsed = parseWorkdays(e.target.value);
              if (parsed !== "invalid") onChange({ ...value, decision_workdays: parsed });
            }}
          />
          dni roboczych
        </label>
        {daysInvalid ? (
          <p className="text-xs text-destructive">Wpisz liczbę od 1 do 60 albo zostaw puste.</p>
        ) : null}
      </div>
    </div>
  );
}
