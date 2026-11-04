"use client";

import { Linkedin, Mail, Pencil, Phone, Plus } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";

import type { AtlasMotion, DecisionMapEntry } from "@/lib/api/sales";

import { CONTACT_STATUS, DECISION_LEVELS, OUR_ROLE_LABELS } from "./decision-map-labels";
import { DecisionPersonDialog } from "./DecisionPersonDialog";

const RFP: Record<string, string> = { yearly: "co rok", biennial: "co 2 lata", ad_hoc: "doraźnie" };
const MILESTONES: [string, string][] = [
  ["vendor_questionnaire_submitted_at", "Ankieta dostawcy"],
  ["nda_signed_at", "NDA"],
  ["added_to_vendor_list_at", "Lista dostawców"],
  ["next_evaluation_at", "Następna ocena"],
  ["next_rfp_expected_at", "Następne RFP"],
];

const CONTACT_LINK = "inline-flex min-w-0 items-center gap-1 text-primary hover:underline";

function Person({ entry, onEdit }: { entry: DecisionMapEntry; onEdit?: () => void }) {
  const status = entry.contact_status ? CONTACT_STATUS[entry.contact_status] : undefined;
  // Adres z Atlasa to wolny tekst, więc link tylko dla http(s).
  const linkedin = /^https?:\/\//i.test(entry.linkedin_url ?? "") ? entry.linkedin_url : null;
  return (
    <li className="space-y-1 py-2 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium text-foreground">
            {entry.name}
            {entry.nexus_contact_id ? null : (
              <span className="ml-1 text-xs font-normal text-muted-foreground">(spoza kontaktów)</span>
            )}
          </p>
          <p className="text-xs text-muted-foreground">
            {[entry.role_in_company, entry.last_contact_at ? `ostatni kontakt ${formatIsoDatePl(entry.last_contact_at)}` : null]
              .filter(Boolean)
              .join(" · ") || "—"}
          </p>
        </div>
        {onEdit && (
          <Button size="icon-sm" variant="quiet" className="shrink-0" aria-label={`Popraw: ${entry.name}`} onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" aria-hidden />
          </Button>
        )}
      </div>
      {(entry.our_role || status) && (
        <div className="flex flex-wrap gap-1">
          {entry.our_role && <Badge variant="soft" size="sm">{OUR_ROLE_LABELS[entry.our_role] ?? entry.our_role}</Badge>}
          {status && <Badge variant={status.variant} size="sm">{status.label}</Badge>}
        </div>
      )}
      {(linkedin || entry.phone || entry.email) && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
          {linkedin && (
            <a href={linkedin} target="_blank" rel="noreferrer" className={CONTACT_LINK}>
              <Linkedin className="h-3 w-3 shrink-0" aria-hidden /> LinkedIn
            </a>
          )}
          {entry.phone && (
            <a href={`tel:${entry.phone.replace(/\s+/g, "")}`} className={CONTACT_LINK}>
              <Phone className="h-3 w-3 shrink-0" aria-hidden /> {entry.phone}
            </a>
          )}
          {entry.email && (
            <a href={`mailto:${entry.email}`} className={CONTACT_LINK}>
              <Mail className="h-3 w-3 shrink-0" aria-hidden /> <span className="truncate">{entry.email}</span>
            </a>
          )}
        </p>
      )}
      {!(linkedin || entry.phone || entry.email) && onEdit && (
        <button type="button" onClick={onEdit} className="block text-left text-xs text-primary hover:underline">
          Brak telefonu, maila i LinkedIna — uzupełnij
        </button>
      )}
      {entry.notes && <p className="line-clamp-3 whitespace-pre-line text-xs text-muted-foreground">{entry.notes}</p>}
    </li>
  );
}

interface SalesMotionPanelProps {
  opportunityId: number;
  motion: AtlasMotion | null;
  /** Lejek Fabryki IT: panel pokazuje się też bez danych z Atlasa i pozwala dodać osobę. */
  mapEnabled?: boolean;
  canEdit?: boolean;
}

/**
 * Sales Motion (Fabryki IT) i produkty z Atlasa na karcie szansy (audyt importu
 * 28.10.2026: dane leżały w `custom_fields.atlas`, ekran ich nie pokazywał).
 * Osoby na mapie poprawia „Sprzedaż: edycja”, proces zakupowy jest tylko do odczytu.
 */
export function SalesMotionPanel({ opportunityId, motion, mapEnabled = false, canEdit = false }: SalesMotionPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState<DecisionMapEntry | "new" | null>(null);
  const factory = motion?.it_factory;
  if (!mapEnabled && (!motion || (!factory && !motion.products?.length))) return null;
  const map = factory?.decision_map ?? [];
  const process = factory?.purchasing_process;
  const byLevel = DECISION_LEVELS.map((label, index) => ({
    label,
    people: map.filter((entry) => (entry.decision_level ?? 4) === index + 1),
  })).filter((group) => group.people.length > 0);
  const milestonesDone = MILESTONES.filter(([key]) => process?.milestones?.[key]).length;

  return (
    <Card className="space-y-3 p-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-foreground">Mapa decyzyjna i proces zakupowy</h2>
          {canEdit && mapEnabled && (
            <Button size="sm" variant="outline" className="shrink-0" data-tour="sales.decision-map.add" onClick={() => setEditing("new")}>
              <Plus className="h-3.5 w-3.5" aria-hidden /> Dodaj osobę
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {map.length} os. na mapie · kamienie milowe {milestonesDone}/5
          {map.length > 0 && map.length < 3 ? " · za mało osób (min. 3)" : ""}
          {factory?.nexus_updated_at
            ? ` · poprawiona ${formatDateTimePl(factory.nexus_updated_at)}`
            : factory?.updated_at
              ? ` · z Atlasa, ${formatIsoDatePl(factory.updated_at.slice(0, 10))}`
              : ""}
        </p>
      </div>
      {motion?.products?.length ? (
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
      {mapEnabled && map.length === 0 && (
        <p className="text-sm text-muted-foreground">Na mapie nie ma jeszcze nikogo.</p>
      )}
      {byLevel.length > 0 && (
        <div className="grid gap-x-6 md:grid-cols-2">
          {byLevel.map((group) => (
            <div key={group.label}>
              <h3 className="mt-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{group.label}</h3>
              <ul className="divide-y divide-border">
                {group.people.map((entry) => (
                  <Person key={entry.key} entry={entry} onEdit={canEdit ? () => setEditing(entry) : undefined} />
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
      {editing !== null && (
        <DecisionPersonDialog
          opportunityId={opportunityId}
          entry={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Card>
  );
}
