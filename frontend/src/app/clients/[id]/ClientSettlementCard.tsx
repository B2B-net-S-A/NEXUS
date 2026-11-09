"use client";

// Sposób rozliczenia konsultantów u tego klienta. Ustawiają Finanse, a panel konsultanta
// układa z tego kroki miesiąca. Bez uprawnień do odczytu karty nie ma.

import { useEffect, useState } from "react";

import { SETTLEMENT_MODES } from "@/components/consultant-portal/portal-model";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useSaveSettlementRule, useSettlementRule } from "@/lib/api/consultant-panel";
import type { SettlementMode } from "@/lib/api/consultant-portal";
import { resolveViewState } from "@/lib/view-state";

const MODES = Object.keys(SETTLEMENT_MODES) as SettlementMode[];

export function ClientSettlementCard({ clientId, canEdit }: { clientId: number; canEdit: boolean }) {
  const { showToast } = useToast();
  const rule = useSettlementRule(clientId);
  const save = useSaveSettlementRule(clientId);
  const [mode, setMode] = useState<SettlementMode | "">("");
  const [instructions, setInstructions] = useState("");
  const state = resolveViewState({
    isLoading: rule.isLoading,
    error: rule.error,
    isSuccess: rule.isSuccess,
  });

  useEffect(() => {
    if (!rule.data) return;
    setMode(rule.data.mode ?? "");
    setInstructions(rule.data.instructions);
  }, [rule.data]);

  if (state === "forbidden" || state === "loading") return null;
  if (state !== "ready") {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(rule.error, "Nie udało się wczytać sposobu rozliczenia.")}
      </p>
    );
  }
  const submit = async () => {
    if (!mode) return;
    try {
      await save.mutateAsync({ mode, instructions });
      showToast("Sposób rozliczenia zapisany.", "success");
    } catch (failure) {
      showToast(apiErrorMessage(failure, "Nie udało się zapisać sposobu rozliczenia."), "error");
    }
  };
  return (
    <section className="space-y-3 rounded-xl border bg-card p-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Jak rozliczają się konsultanci</h3>
        <p className="text-xs text-muted-foreground">Konsultant widzi to w swoim panelu.</p>
      </div>
      <fieldset className="space-y-1.5 text-sm" disabled={!canEdit}>
        {MODES.map((key) => (
          <label key={key} className="flex items-start gap-2">
            <input
              type="radio"
              name="settlement-mode"
              className="mt-1"
              checked={mode === key}
              onChange={() => setMode(key)}
            />
            <span className="min-w-0">
              <span className="block font-medium">{SETTLEMENT_MODES[key].label}</span>
              <span className="block text-xs text-muted-foreground">{SETTLEMENT_MODES[key].intro}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <FormField label="Dodatkowy opis dla konsultanta" htmlFor="settlement-instructions">
        <Textarea
          id="settlement-instructions"
          rows={3}
          disabled={!canEdit}
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
        />
      </FormField>
      {canEdit ? (
        <Button size="sm" disabled={!mode || save.isPending} onClick={submit}>
          Zapisz sposób rozliczenia
        </Button>
      ) : (
        <p className="text-xs text-muted-foreground">Zmieniają Finanse.</p>
      )}
    </section>
  );
}
