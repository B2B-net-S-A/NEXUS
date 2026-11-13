"use client";

import { Linkedin, Mail, Pencil, Plus } from "lucide-react";
import { useState } from "react";

import { TruncatedText } from "@/components/ds/TruncatedText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";

import type { AtlasMotion, DecisionMapEntry } from "@/lib/api/sales";

import { BotPeopleAction } from "./bot-people/BotPeopleAction";
import { CONTACT_STATUS, DECISION_LEVELS, OUR_ROLE_LABELS, sourceLine } from "./decision-map-labels";
import { DecisionPersonDialog } from "./DecisionPersonDialog";
import { safeHref } from "./format";

const CONTACT_LINK = "inline-flex min-w-0 items-center gap-1 text-primary hover:underline";
const LINK = "text-primary hover:underline";

interface PersonProps {
  entry: DecisionMapEntry;
  order: string | null;
  onEdit?: () => void;
  onCall?: (entry: DecisionMapEntry) => void;
}

function Person({ entry, order, onEdit, onCall }: PersonProps) {
  const [open, setOpen] = useState(false);
  const status = entry.contact_status ? CONTACT_STATUS[entry.contact_status] : undefined;
  // Adres z Atlasa to wolny tekst, więc link tylko dla http(s).
  const linkedin = safeHref(entry.linkedin_url);
  const blocked = Boolean(entry.do_not_contact);
  const gone = entry.active === false;
  const role = entry.role_in_company ?? undefined;
  const level = entry.decision_level ? DECISION_LEVELS[entry.decision_level - 1] : undefined;
  const origin = sourceLine(entry);
  return (
    <li className="text-sm">
      <div className="flex items-center gap-3 py-0.5">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="min-w-0 flex-1 text-left hover:text-primary"
        >
          <span className="flex min-w-0 items-baseline gap-2">
            <TruncatedText className={`max-w-[9.5rem] shrink-0 font-medium ${blocked || gone ? "text-muted-foreground" : "text-foreground"}`}>
              {entry.name}
            </TruncatedText>
            {gone && (
              <Badge variant="neutral" size="sm">
                nie pracuje
              </Badge>
            )}
            {order && (
              <Badge variant="soft" size="sm">
                {order}
              </Badge>
            )}
            {blocked && (
              <Badge variant="danger" size="sm">
                Nie kontaktować
              </Badge>
            )}
            {!order && !blocked && !gone && role && (
              <TruncatedText className="min-w-0 max-w-none text-xs text-muted-foreground">{role}</TruncatedText>
            )}
          </span>
          {order && role && <span className="block truncate text-xs text-muted-foreground">{role}</span>}
        </button>
        {blocked ? (
          <span className="shrink-0 text-xs text-muted-foreground">nie dzwonić</span>
        ) : entry.phone ? (
          <a
            href={`tel:${entry.phone.replace(/\s+/g, "")}`}
            onClick={() => onCall?.(entry)}
            className={`shrink-0 text-xs tabular-nums ${LINK}`}
          >
            {entry.phone}
          </a>
        ) : entry.email ? (
          <a href={`mailto:${entry.email}`} className={`shrink-0 text-xs ${LINK}`}>
            napisz mail
          </a>
        ) : onEdit ? (
          <button type="button" onClick={onEdit} className={`shrink-0 text-xs ${LINK}`}>
            uzupełnij
          </button>
        ) : (
          <span className="shrink-0 text-xs text-muted-foreground">brak numeru</span>
        )}
      </div>
      {open && (
        <div className="space-y-1 pb-2 text-xs text-muted-foreground">
          <p>
            {[
              level,
              role,
              entry.nexus_contact_id ? null : "spoza kontaktów",
              entry.last_contact_at ? `ostatni kontakt ${formatIsoDatePl(entry.last_contact_at)}` : null,
            ]
              .filter(Boolean)
              .join(" · ") || "—"}
          </p>
          {(entry.our_role || status) && (
            <div className="flex flex-wrap gap-1">
              {entry.our_role && (
                <Badge variant="soft" size="sm">
                  {OUR_ROLE_LABELS[entry.our_role] ?? entry.our_role}
                </Badge>
              )}
              {status && (
                <Badge variant={status.variant} size="sm">
                  {status.label}
                </Badge>
              )}
            </div>
          )}
          {entry.notes && <p className="whitespace-pre-line">{entry.notes}</p>}
          {origin && <p>{origin}</p>}
          {!blocked && (entry.email || linkedin) && (
            <p className="flex flex-wrap gap-x-3">
              {entry.email && (
                <a href={`mailto:${entry.email}`} className={CONTACT_LINK}>
                  <Mail className="h-3 w-3 shrink-0" aria-hidden /> <span className="truncate">{entry.email}</span>
                </a>
              )}
              {linkedin && (
                <a href={linkedin} target="_blank" rel="noreferrer" className={CONTACT_LINK}>
                  <Linkedin className="h-3 w-3 shrink-0" aria-hidden /> LinkedIn
                </a>
              )}
            </p>
          )}
          {onEdit && (
            <Button size="sm" variant="quiet" className="h-6 px-0" aria-label={`Popraw: ${entry.name}`} onClick={onEdit}>
              <Pencil className="mr-1 h-3 w-3" aria-hidden /> Popraw
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

function orderLabel(index: number, total: number): string | null {
  if (index < 0) return null;
  if (total === 1) return "Zadzwoń";
  return index === 0 ? "Najpierw" : "Potem";
}

function peopleCount(count: number): string {
  return `${count} ${count === 1 ? "osoba" : count > 1 && count < 5 ? "osoby" : "osób"}`;
}

interface SalesMotionPanelProps {
  opportunityId: number;
  motion: AtlasMotion | null;
  /** Lejek Fabryki IT: panel pokazuje się też bez danych z Atlasa i pozwala dodać osobę. */
  mapEnabled?: boolean;
  canEdit?: boolean;
  /** Firma konta: „Znajdź decydentów (bot)” w lejku Fabryki IT. */
  companyId?: number;
  /** Kolejka z paska kroku: osoby wskazane idą na górę. */
  queue?: readonly DecisionMapEntry[];
  onCall?: (entry: DecisionMapEntry) => void;
}

/**
 * Mapa decyzyjna na karcie szansy: zwarta lista, numer klikalny, szczegóły po rozwinięciu.
 * Proces zakupowy i produkty są niżej (`PurchasingProcessPanel`).
 */
export function SalesMotionPanel({
  opportunityId,
  motion,
  mapEnabled = false,
  canEdit = false,
  companyId,
  queue = [],
  onCall,
}: SalesMotionPanelProps) {
  const [editing, setEditing] = useState<DecisionMapEntry | "new" | null>(null);
  const factory = motion?.it_factory;
  const map = factory?.decision_map ?? [];
  if (!mapEnabled && map.length === 0) return null;
  const position = (entry: DecisionMapEntry) => queue.findIndex((item) => item.key === entry.key);
  const level = (entry: DecisionMapEntry) => entry.decision_level ?? DECISION_LEVELS.length;
  const people = [...map].sort((a, b) => {
    const left = position(a);
    const right = position(b);
    if (left >= 0 || right >= 0) {
      if (left < 0) return 1;
      if (right < 0) return -1;
      return left - right;
    }
    return level(a) - level(b);
  });
  const none = map.filter((entry) => entry.contact_status === "not_contacted").length;
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">Mapa decyzyjna</h2>
          <p
            className="text-xs text-muted-foreground"
            title={
              factory?.nexus_updated_at
                ? `Poprawiona ${formatDateTimePl(factory.nexus_updated_at)}`
                : factory?.updated_at
                  ? `Z Atlasa, ${formatIsoDatePl(factory.updated_at.slice(0, 10))}`
                  : undefined
            }
          >
            {peopleCount(map.length)}
            {none > 0 ? `, ${none === map.length ? "wszystkie" : none} bez kontaktu` : ""}
            {map.length > 0 && map.length < 3 ? " · za mało osób (min. 3)" : ""}
          </p>
        </div>
        {canEdit && mapEnabled && (
          <Button size="sm" variant="outline" className="shrink-0" data-tour="sales.decision-map.add" onClick={() => setEditing("new")}>
            <Plus className="h-3.5 w-3.5" aria-hidden /> Dodaj osobę
          </Button>
        )}
      </div>
      {mapEnabled && companyId !== undefined && (
        <BotPeopleAction companyId={companyId} canEdit={canEdit} className="mt-2" />
      )}
      {mapEnabled && map.length === 0 && <p className="mt-1 text-sm text-muted-foreground">Na mapie nie ma jeszcze nikogo.</p>}
      {people.length > 0 && (
        <ul className="mt-1 divide-y divide-border">
          {people.map((entry) => (
            <Person
              key={entry.key}
              entry={entry}
              order={orderLabel(position(entry), queue.length)}
              onEdit={canEdit ? () => setEditing(entry) : undefined}
              onCall={onCall}
            />
          ))}
        </ul>
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
