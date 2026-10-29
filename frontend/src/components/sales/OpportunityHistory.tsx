"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useOpportunityHistory, type OpportunityEvent } from "@/lib/api/sales";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { formatDealAmount } from "./format";

const FIELD_LABELS: Record<string, string> = {
  title: "Nazwa",
  stage_id: "Etap",
  status: "Status",
  lost_reason: "Powód przegranej",
  value: "Wartość",
  mrr_value: "Miesięcznie",
  margin_pct: "Marża",
  owner_user_id: "Opiekun",
  expected_close_date: "Planowane zamknięcie",
  company_id: "Firma",
};
const STATUS_WORDS: Record<string, string> = {
  open: "otwarta",
  won: "wygrana",
  lost: "przegrana",
};

function shown(
  field: string | null,
  value: string | null,
  label: string | null,
  currency: string,
): string {
  if (value === null || value === "") return "—";
  switch (field) {
    case "stage_id":
    case "owner_user_id":
    case "company_id":
      // Etap albo konto usunięte po zmianie — zostaje sam identyfikator.
      return label ?? `#${value}`;
    case "status":
      return STATUS_WORDS[value] ?? value;
    case "value":
    case "mrr_value":
      return formatDealAmount(value, currency);
    case "margin_pct":
      return `${Number(value)}%`;
    case "expected_close_date":
      return formatIsoDatePl(value);
    case "title":
    case "lost_reason":
      return `„${value}”`;
    default:
      return value;
  }
}

/** Jedno zdanie o zmianie: „Etap: Lead → Oferta wysłana”. */
export function describeEvent(event: OpportunityEvent, currency = "PLN"): string {
  switch (event.kind) {
    case "created":
      return `Założenie szansy na etapie „${shown("stage_id", event.new_value, event.new_label, currency)}”`;
    case "archived":
      return "Przeniesienie do archiwum";
    case "restored":
      return "Przywrócenie z archiwum";
    case "company_merged":
      return `Scalenie firm: ${shown("company_id", event.old_value, event.old_label, currency)} → ${shown("company_id", event.new_value, event.new_label, currency)}`;
    default: {
      const label = FIELD_LABELS[event.field ?? ""] ?? event.field ?? "Zmiana";
      const before = shown(event.field, event.old_value, event.old_label, currency);
      const after = shown(event.field, event.new_value, event.new_label, currency);
      return `${label}: ${before} → ${after}`;
    }
  }
}

interface OpportunityHistoryProps {
  opportunityId: number;
  currency: string;
}

/**
 * „Historia zmian” szansy (jak w Atlasie): kto i kiedy zmienił etap, status,
 * wartość, opiekuna, datę zamknięcia albo nazwę. Zwinięta — wpisy dociągamy
 * dopiero po rozwinięciu. Historia zaczyna się od pracy w NEXUSIE (import
 * z Atlasa jej nie przenosi).
 */
export function OpportunityHistory({ opportunityId, currency }: OpportunityHistoryProps) {
  const [open, setOpen] = useState(false);
  const history = useOpportunityHistory(opportunityId, open);
  const state = resolveViewState({
    isLoading: history.isLoading,
    error: history.error,
    isSuccess: history.isSuccess,
  });
  const events = history.data ?? [];

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Historia zmian</h2>
        <Button
          size="sm"
          variant="quiet"
          aria-expanded={open}
          aria-controls="sales-opp-history"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Zwiń" : "Pokaż"}
        </Button>
      </div>
      {open && (
        <div id="sales-opp-history" className="mt-2">
          {state === "loading" ? (
            <p className="text-sm text-muted-foreground">Wczytywanie historii…</p>
          ) : state === "forbidden" || state === "not_found" || state === "error" ? (
            <QueryStateNotice state={state} onRetry={() => void history.refetch()} />
          ) : history.isSuccess && events.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Bez zmian od przeniesienia z Atlasa.
            </p>
          ) : (
            <ol className="divide-y divide-border">
              {events.map((event) => (
                <li key={event.id} className="py-2 text-sm">
                  <p className="text-foreground">{describeEvent(event, currency)}</p>
                  <p className="text-xs text-muted-foreground">
                    {[event.user?.name || "System", formatDateTimePl(event.created_at)].join(" · ")}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Card>
  );
}
