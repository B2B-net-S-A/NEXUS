"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CONTRACT_OPTIONS,
  MODE_OPTIONS,
  START_OPTIONS,
  conditionsFromDraft,
  draftFromConditions,
  type ConditionsDraft,
  type ReportConditions,
  type StartWhen,
} from "@/lib/competence-reports/logic";

const NO_START = "brak";

/**
 * „Popraw warunki” — te same pola co formularz na stronie. Po zapisie backend
 * przelicza raport (`rebuild_snapshot`), więc podgląd maila pokazuje nowe liczby.
 */
export function ConditionsForm({
  initial,
  saving,
  onSave,
  onCancel,
}: {
  initial: ReportConditions;
  saving: boolean;
  onSave: (body: ReportConditions) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ConditionsDraft>(() => draftFromConditions(initial));
  const [errors, setErrors] = useState<Partial<Record<keyof ConditionsDraft, string>>>({});
  const set = <K extends keyof ConditionsDraft>(key: K, value: ConditionsDraft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const result = conditionsFromDraft(draft);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors({});
    void onSave(result.body);
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-4 rounded-lg border border-border bg-muted/40 p-4"
      aria-labelledby="conditions-form-title"
    >
      <h3 id="conditions-form-title" className="text-sm font-semibold text-foreground">
        Popraw warunki
      </h3>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="cr-rate" label="Stawka (zł/h netto)" error={errors.rate}>
          <Input
            id="cr-rate"
            inputMode="numeric"
            value={draft.rate}
            onChange={(e) => set("rate", e.target.value)}
          />
        </Field>
        <Field id="cr-current" label="Obecna stawka (zł/h)" error={errors.current_rate}>
          <Input
            id="cr-current"
            inputMode="numeric"
            value={draft.current_rate}
            onChange={(e) => set("current_rate", e.target.value)}
          />
        </Field>
        <Field id="cr-days" label="Najwięcej dni w biurze" error={errors.office_days_max}>
          <Input
            id="cr-days"
            inputMode="numeric"
            placeholder="0–5"
            value={draft.office_days_max}
            onChange={(e) => set("office_days_max", e.target.value)}
          />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <span id="cr-contract" className="block text-xs font-medium text-muted-foreground">
            Forma współpracy
          </span>
          <SegmentedRadio
            labelledBy="cr-contract"
            value={draft.contract}
            onChange={(value) => set("contract", value)}
            options={CONTRACT_OPTIONS}
            size="sm"
          />
        </div>
        <fieldset className="space-y-1.5">
          <legend className="text-xs font-medium text-muted-foreground">Tryb pracy</legend>
          <div className="flex flex-wrap gap-3 pt-1">
            {MODE_OPTIONS.map((option) => (
              <label key={option.value} className="flex items-center gap-1.5 text-sm text-foreground">
                <Checkbox
                  checked={draft.modes.includes(option.value)}
                  onCheckedChange={(checked) =>
                    set(
                      "modes",
                      checked
                        ? [...draft.modes, option.value]
                        : draft.modes.filter((m) => m !== option.value),
                    )
                  }
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="space-y-1.5">
          <Label htmlFor="cr-start" className="text-xs font-medium text-muted-foreground">
            Start
          </Label>
          <Select
            value={draft.start === "" ? NO_START : draft.start}
            onValueChange={(value) => set("start", value === NO_START ? "" : (value as StartWhen))}
          >
            <SelectTrigger id="cr-start" className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_START}>Nie podał</SelectItem>
              {START_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <Field id="cr-cities" label="Miasta (po przecinku)">
        <Input
          id="cr-cities"
          value={draft.office_cities}
          onChange={(e) => set("office_cities", e.target.value)}
          placeholder="np. Kraków, Warszawa"
        />
      </Field>
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" loading={saving}>
          Zapisz i przelicz
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
          Anuluj
        </Button>
      </div>
    </form>
  );
}

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
