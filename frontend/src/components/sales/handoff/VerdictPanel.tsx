"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import { useGiveVerdict, type Handoff, type HandoffVerdict } from "@/lib/api/sales-handoffs";
import { cn } from "@/lib/utils";

import { dayPlus, VERDICT_HINTS, VERDICT_LABELS, VERDICT_ORDER } from "./helpers";

const RETURN_IN = [
  { value: "30", label: "Za miesiąc" },
  { value: "90", label: "Za kwartał" },
  { value: "180", label: "Za pół roku" },
] as const;
type ReturnIn = (typeof RETURN_IN)[number]["value"];

const NOT_A_FIT_REASONS = ["Za mała firma", "Brak budżetu", "Brak potrzeby", "Mają dostawcę"];

const SAVED: Record<HandoffVerdict, string> = {
  qualified: "Zapisano: kwalifikuje się. Szansa jest na etapie „Lead kwalifikowany”.",
  not_now: "Zapisano: nie teraz. Krok wróci do Ciebie w wybranym dniu.",
  not_a_fit: "Zapisano: nie nasz klient. Szansa jest zamknięta.",
  no_show: "Zapisano: nie odbyło się. Osoba, która umówiła spotkanie, dostała zadanie.",
};

interface VerdictPanelProps {
  handoff: Handoff;
  onSaved: (kind: HandoffVerdict) => void;
}

/**
 * Werdykt po spotkaniu. „Kwalifikuje się” i „Nie odbyło się” zapisują się jednym
 * kliknięciem; „Nie teraz” pyta o datę powrotu, „Nie nasz klient” o powód. Każdy werdykt
 * widzi potem osoba, która umówiła spotkanie.
 */
export function VerdictPanel({ handoff, onSaved }: VerdictPanelProps) {
  const give = useGiveVerdict();
  const { showError, showSuccess } = useToast();
  const [asking, setAsking] = useState<"not_now" | "not_a_fit" | null>(null);
  const [returnIn, setReturnIn] = useState<ReturnIn | null>("30");
  const [returnOn, setReturnOn] = useState("");
  const [reason, setReason] = useState("");

  const save = (kind: HandoffVerdict, extra: { reason?: string | null; return_on?: string | null } = {}) => {
    give.mutate(
      { opportunity_id: handoff.opportunity.id, kind, ...extra },
      {
        onSuccess: () => {
          showSuccess(SAVED[kind]);
          onSaved(kind);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać werdyktu.")),
      },
    );
  };

  const choose = (kind: HandoffVerdict) => {
    if (kind === "not_now" || kind === "not_a_fit") {
      setAsking((current) => (current === kind ? null : kind));
      setReason("");
      return;
    }
    save(kind);
  };

  return (
    <div className="space-y-2" data-testid="verdict-panel">
      <h3 className="text-sm font-semibold text-foreground">Jak poszło?</h3>
      <div className="grid grid-cols-2 gap-1.5" role="group" aria-label="Werdykt po spotkaniu">
        {VERDICT_ORDER.map((kind) => (
          <button
            key={kind}
            type="button"
            disabled={give.isPending}
            aria-pressed={asking === kind}
            onClick={() => choose(kind)}
            className={cn(
              "rounded-md border px-2.5 py-1.5 text-left transition-colors disabled:opacity-60",
              asking === kind ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted",
            )}
          >
            <span className="block text-sm font-medium text-foreground">{VERDICT_LABELS[kind]}</span>
            <span className="block text-xs text-muted-foreground">{VERDICT_HINTS[kind]}</span>
          </button>
        ))}
      </div>
      {asking === "not_now" && (
        <div className="space-y-2 rounded-md border border-border bg-muted/30 p-2">
          <p className="text-xs font-medium text-foreground">Kiedy wrócić?</p>
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedRadio
              size="sm"
              label="Kiedy wrócić"
              options={RETURN_IN}
              value={returnOn ? null : returnIn}
              onChange={(value) => {
                setReturnIn(value);
                setReturnOn("");
              }}
            />
            <Input
              aria-label="Data powrotu"
              type="date"
              className="h-8 w-40 text-xs"
              value={returnOn}
              onChange={(event) => setReturnOn(event.target.value)}
            />
          </div>
          <Input
            aria-label="Dopisek"
            placeholder="Dopisek, np. budżet od stycznia"
            className="h-8 text-xs"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              loading={give.isPending}
              onClick={() =>
                save("not_now", {
                  return_on: returnOn || dayPlus(Number(returnIn ?? "30")),
                  reason: reason.trim() || null,
                })
              }
            >
              Zapisz „Nie teraz”
            </Button>
          </div>
        </div>
      )}
      {asking === "not_a_fit" && (
        <div className="space-y-2 rounded-md border border-border bg-muted/30 p-2">
          <p className="text-xs font-medium text-foreground">Dlaczego nie nasz klient?</p>
          <div className="flex flex-wrap gap-1">
            {NOT_A_FIT_REASONS.map((preset) => (
              <Button
                key={preset}
                size="sm"
                className="h-7 px-2"
                variant={reason === preset ? "primary" : "outline"}
                aria-pressed={reason === preset}
                onClick={() => setReason(preset)}
              >
                {preset}
              </Button>
            ))}
          </div>
          <Input
            aria-label="Powód"
            placeholder="Powód (opcjonalnie)"
            className="h-8 text-xs"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              loading={give.isPending}
              onClick={() => save("not_a_fit", { reason: reason.trim() || null })}
            >
              Zamknij szansę
            </Button>
          </div>
        </div>
      )}
      {handoff.booked_by && (
        <p className="text-xs leading-snug text-muted-foreground">
          Werdykt zobaczy {handoff.booked_by.name} przy swoich spotkaniach: umówione → odbyte → zakwalifikowane.
        </p>
      )}
    </div>
  );
}
