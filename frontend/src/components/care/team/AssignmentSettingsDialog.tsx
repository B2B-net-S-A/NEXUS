"use client";

import { useState, type ReactNode } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useSetLoadThreshold, type CareAssignment } from "@/lib/api/care";

import { ClientDefaultOwnersTable } from "../ClientDefaultOwnersDialog";
import { OwnerPoolPanel } from "../OwnerPoolPanel";

function ThresholdEditor({ data }: { data: CareAssignment }) {
  const { showToast } = useToast();
  const save = useSetLoadThreshold();
  const [value, setValue] = useState(
    data.threshold.monthly_conversations ? String(data.threshold.monthly_conversations) : "",
  );
  const submit = () => {
    const parsed = value.trim() ? Number(value) : null;
    if (parsed != null && (!Number.isInteger(parsed) || parsed < 1 || parsed > 1000)) {
      showToast("Próg to liczba rozmów w miesiącu od 1 do 1000.", "error");
      return;
    }
    save.mutate(parsed, {
      onSuccess: () => showToast(parsed ? "Próg zapisany" : "Próg wyłączony", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać progu."), "error"),
    });
  };
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="care-load-threshold" className="text-muted-foreground">
          Rozmów w miesiącu na opiekuna
        </label>
        <Input
          id="care-load-threshold"
          type="number"
          min={1}
          max={1000}
          inputMode="numeric"
          className="h-8 w-20"
          value={value}
          placeholder="brak"
          onChange={(event) => setValue(event.target.value)}
        />
        <Button size="sm" variant="outline" className="h-8" disabled={save.isPending} onClick={submit}>
          Zapisz próg
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Obciążenie liczone z rytmów, nie samą liczbą osób. Próg to ostrzeżenie, nie blokada.
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 border-t border-border pt-3" aria-label={title}>
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </section>
  );
}

/**
 * „Ustawienia przydziału” (makieta P6, 22.10.2026) — jedno okno na rzeczy
 * ustawiane raz na jakiś czas: pula opiekunów z „Nie przypisuj” i automatem
 * dla nowych kontraktów, próg obciążenia i domyślni opiekunowie klientów
 * (jedyne miejsce ich zapisu). Sam przydział „wg obłożenia” jest na pasku
 * ekranu, nie w oknie.
 */
export function AssignmentSettingsDialog({
  data,
  open,
  onOpenChange,
}: {
  data: CareAssignment;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Ustawienia przydziału"
      description="Pula opiekunów, „Nie przypisuj”, próg obciążenia, automat dla nowych kontraktów i domyślni opiekunowie klientów."
      size="xl"
      footer={
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Zamknij
        </Button>
      }
    >
      <div className="space-y-4">
        {/* Pula ma własny nagłówek i ramkę (`OwnerPoolPanel`). */}
        {data.can_assign ? <OwnerPoolPanel withAutoPreview={false} /> : null}
        {data.can_edit_threshold ? (
          <Section title="Próg obciążenia">
            <ThresholdEditor data={data} />
          </Section>
        ) : null}
        <Section title="Domyślni opiekunowie klientów">
          <ClientDefaultOwnersTable data={data} />
        </Section>
      </div>
    </AppModal>
  );
}
