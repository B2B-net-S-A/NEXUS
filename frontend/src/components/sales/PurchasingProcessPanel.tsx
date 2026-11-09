"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { AtlasMotion } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";

const RFP: Record<string, string> = { yearly: "co rok", biennial: "co 2 lata", ad_hoc: "doraźnie" };
export const MILESTONES: [string, string][] = [
  ["vendor_questionnaire_submitted_at", "Ankieta dostawcy"],
  ["nda_signed_at", "NDA"],
  ["added_to_vendor_list_at", "Lista dostawców"],
  ["next_evaluation_at", "Następna ocena"],
  ["next_rfp_expected_at", "Następne RFP"],
];

/** Produkty i proces zakupowy z Atlasa, pod mapą decyzyjną; tylko do odczytu. */
export function PurchasingProcessPanel({ motion }: { motion: AtlasMotion | null }) {
  const [expanded, setExpanded] = useState(false);
  const factory = motion?.it_factory;
  const process = factory?.purchasing_process;
  const products = motion?.products ?? [];
  if (!process && !products.length && !factory?.next_step) return null;
  const done = MILESTONES.filter(([key]) => process?.milestones?.[key]).length;
  return (
    <Card className="space-y-2 p-4">
      <h2 className="text-base font-semibold text-foreground">Proces zakupowy i produkty</h2>
      {products.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Produkty:</span>
          {products.map((product) => (
            <Badge key={product} variant="outline" size="sm">
              {product}
            </Badge>
          ))}
        </div>
      )}
      {factory?.next_step && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          <span className="font-medium">Następny krok z Atlasa:</span> {factory.next_step}
          {factory.next_step_due ? ` · do ${formatIsoDatePl(factory.next_step_due)}` : ""}
        </p>
      )}
      {process && (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
            <span>
              Kamienie milowe: <b className="text-foreground">{done}/5</b>
            </span>
            <span>
              Cykl decyzji:{" "}
              <b className="text-foreground">
                {process.decision_cycle_months ? `${process.decision_cycle_months} mies.` : "—"}
              </b>
            </span>
            <span>
              RFP:{" "}
              <b className="text-foreground">
                {process.rfp_frequency ? (RFP[process.rfp_frequency] ?? process.rfp_frequency) : "—"}
              </b>
            </span>
            {MILESTONES.map(([key, label]) => (
              <span key={key}>
                {label}:{" "}
                <b className="text-foreground">{formatIsoDatePl(process.milestones?.[key] ?? null) || "—"}</b>
              </span>
            ))}
          </div>
          {process.description && (
            <div>
              <p className={`whitespace-pre-line text-muted-foreground ${expanded ? "" : "line-clamp-3"}`}>
                {process.description}
              </p>
              <Button size="sm" variant="quiet" className="px-0" onClick={() => setExpanded((value) => !value)}>
                {expanded ? "Zwiń opis procesu" : "Pokaż cały opis procesu"}
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
