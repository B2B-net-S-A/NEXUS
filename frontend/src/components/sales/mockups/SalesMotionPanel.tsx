"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatIsoDatePl } from "@/lib/date-pl";

import { useOppMotionMock, type DecisionMapEntry } from "./useAtlasMock";

const OUR_ROLE: Record<string, string> = {
  decision_maker: "Decydent",
  economic_buyer: "Budżet",
  champion: "Champion",
  influencer: "Wpływa",
  blocker: "Hamuje",
  end_user: "Użytkownik",
};
const CONTACT_STATUS: Record<string, { label: string; variant: "neutral" | "info" | "success" | "warning" }> = {
  not_contacted: { label: "bez kontaktu", variant: "warning" },
  in_progress: { label: "w toku", variant: "info" },
  first_contact: { label: "pierwszy kontakt", variant: "info" },
  regular_dialog: { label: "stały dialog", variant: "success" },
};
const RFP: Record<string, string> = { yearly: "co rok", biennial: "co 2 lata", ad_hoc: "doraźnie" };
const MILESTONES: [string, string][] = [
  ["vendor_questionnaire_submitted_at", "Ankieta dostawcy"],
  ["nda_signed_at", "NDA"],
  ["added_to_vendor_list_at", "Lista dostawców"],
  ["next_evaluation_at", "Następna ocena"],
  ["next_rfp_expected_at", "Następne RFP"],
];
const LEVELS = ["Zarząd / C-level", "Dyrektorzy", "Kierownicy", "Zespół"];

function Person({ entry, contactId }: { entry: DecisionMapEntry; contactId?: number }) {
  const status = entry.contact_status ? CONTACT_STATUS[entry.contact_status] : undefined;
  return (
    <li className="flex items-start justify-between gap-3 py-1.5 text-sm">
      <div className="min-w-0">
        <p className="font-medium text-foreground">
          {entry.name}
          {contactId ? null : (
            <span className="ml-1 text-xs font-normal text-muted-foreground">(spoza kontaktów)</span>
          )}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {[entry.role_in_company, entry.last_contact_at ? `ostatni kontakt ${formatIsoDatePl(entry.last_contact_at)}` : null]
            .filter(Boolean)
            .join(" · ") || "—"}
        </p>
      </div>
      <div className="flex shrink-0 gap-1">
        {entry.our_role && <Badge variant="soft" size="sm">{OUR_ROLE[entry.our_role] ?? entry.our_role}</Badge>}
        {status && <Badge variant={status.variant} size="sm">{status.label}</Badge>}
      </div>
    </li>
  );
}

/** MAKIETA: Sales Motion (Fabryki IT) i produkty z Atlasa na karcie szansy — tylko odczyt. */
export function SalesMotionPanel({ opportunityId }: { opportunityId: number }) {
  const mock = useOppMotionMock();
  const [expanded, setExpanded] = useState(false);
  const motion = mock.data?.opportunities[String(opportunityId)];
  const factory = motion?.it_factory;
  if (!motion || (!factory && !motion.products?.length)) return null;
  const map = factory?.decision_map ?? [];
  const process = factory?.purchasing_process;
  const contacts = mock.data?.contacts ?? {};
  const byLevel = LEVELS.map((label, index) => ({
    label,
    people: map.filter((entry) => (entry.decision_level ?? 4) === index + 1),
  })).filter((group) => group.people.length > 0);
  const milestonesDone = MILESTONES.filter(([key]) => process?.milestones?.[key]).length;

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Mapa decyzyjna i proces zakupowy</h2>
        <p className="text-xs text-muted-foreground">
          {map.length} os. na mapie · kamienie milowe {milestonesDone}/5
          {factory?.updated_at ? ` · z Atlasa, ${formatIsoDatePl(factory.updated_at.slice(0, 10))}` : ""}
        </p>
      </div>
      {motion.products?.length ? (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Produkty:</span>
          {motion.products.map((product) => (
            <Badge key={product} variant="outline" size="sm">{product}</Badge>
          ))}
        </div>
      ) : null}
      {factory?.next_step && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          <span className="font-medium">Następny krok:</span> {factory.next_step}
          {factory.next_step_due ? ` · do ${formatIsoDatePl(factory.next_step_due)}` : ""}
        </p>
      )}
      {byLevel.length > 0 && (
        <div className="grid gap-x-6 md:grid-cols-2">
          {byLevel.map((group) => (
            <div key={group.label}>
              <h3 className="mt-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{group.label}</h3>
              <ul className="divide-y divide-border">
                {group.people.map((entry) => (
                  <Person
                    key={`${entry.name}-${entry.contact_id}`}
                    entry={entry}
                    contactId={entry.contact_id ? contacts[entry.contact_id] : undefined}
                  />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {process && (
        <div className="space-y-2 border-t border-border pt-3 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground">
            <span>Cykl decyzji: <b className="text-foreground">{process.decision_cycle_months ? `${process.decision_cycle_months} mies.` : "—"}</b></span>
            <span>RFP: <b className="text-foreground">{process.rfp_frequency ? RFP[process.rfp_frequency] ?? process.rfp_frequency : "—"}</b></span>
            {MILESTONES.map(([key, label]) => (
              <span key={key}>
                {label}: <b className="text-foreground">{formatIsoDatePl(process.milestones?.[key] ?? null) || "—"}</b>
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
