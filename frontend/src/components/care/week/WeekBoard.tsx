"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CareWeek, WeekContact } from "@/lib/api/care";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import {
  reasonPill,
  signalPills,
  visibleCards,
  weekColumns,
  type WeekColumn,
} from "./week-format";

/** Ostatnia ocena zadowolenia (1–5) kropkami — kolor wzmacnia liczbę w etykiecie. */
export function SatisfactionDots({ value }: { value: number }) {
  return (
    <span className="inline-flex gap-0.5" role="img" aria-label={`ocena ${value} z 5`}>
      {[1, 2, 3, 4, 5].map((step) => (
        <span
          key={step}
          aria-hidden
          className={cn("size-1.5 rounded-full", step <= value ? "bg-success" : "bg-border")}
        />
      ))}
    </span>
  );
}

interface CardProps {
  row: WeekContact;
  /** Karta w kolumnie „Zaległe/Wcześniej” — termin nie wynika z nagłówka. */
  inBefore: boolean;
  today: string;
  canEdit: boolean;
  showOwner: boolean;
  selected: boolean;
  onOpen: (row: WeekContact) => void;
  onTalk: (row: WeekContact) => void;
}

/* Karta ma 150 px kolumny: plakietka powodu („30 dni przed końcem zamówienia”)
   i sygnały zawijają się zamiast wystawać poza kartę i stronę przy 360 px. */
const WRAP_PILL = "h-auto max-w-full whitespace-normal py-0.5";

function ContactCard({ row, inBefore, today, canEdit, showOwner, selected, onOpen, onTalk }: CardProps) {
  const [primary, ...rest] = row.reasons;
  const pill = reasonPill(primary, today, inBefore);
  const signals = signalPills(row);
  const place = [row.client_name, row.manager?.area?.name ?? row.job_title]
    .filter(Boolean)
    .join(" · ");
  const last = row.last_conversation;
  return (
    <li
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border bg-card p-2.5 text-sm shadow-xs",
        row.overdue ? "border-destructive/30" : "border-border",
        selected && "ring-2 ring-primary/40",
      )}
    >
      <button
        type="button"
        className="text-left text-[13px] font-semibold leading-tight hover:underline"
        aria-label={`Oś konsultanta: ${row.candidate_name ?? "konsultant"}`}
        onClick={() => onOpen(row)}
      >
        {row.candidate_name ?? "Konsultant"}
      </button>
      <span className="text-xs text-muted-foreground">{place}</span>
      {row.manager ? (
        <span className="text-xs text-muted-foreground">menedżer: {row.manager.name}</span>
      ) : null}
      <div className="flex flex-wrap gap-1">
        <Badge size="sm" variant={pill.tone} className={WRAP_PILL}>
          {pill.text}
        </Badge>
        {rest.length ? (
          <Badge size="sm" variant="neutral" className={WRAP_PILL} title={rest.map((r) => r.label).join(", ")}>
            +{rest.length}
          </Badge>
        ) : null}
      </div>
      {signals.length || row.front_office.handed_off_on ? (
        <div className="flex flex-wrap gap-1">
          {signals.map((text) => (
            <Badge key={text} size="sm" variant="warning" className={WRAP_PILL}>
              {text}
            </Badge>
          ))}
          {row.front_office.handed_off_on ? (
            <Badge size="sm" variant="neutral" className={WRAP_PILL}>
              front office od {formatDayMonthPl(row.front_office.handed_off_on)}
            </Badge>
          ) : null}
        </div>
      ) : null}
      {last?.note_excerpt ? (
        <p className="line-clamp-3 rounded-md bg-muted/60 px-2 py-1 text-xs">„{last.note_excerpt}”</p>
      ) : null}
      <div className="flex items-center justify-between gap-2 text-[11.5px] text-muted-foreground">
        <span className="tabular-nums">
          {last ? `ostatnio ${formatDayMonthPl(last.occurred_on)}` : "bez rozmów"}
        </span>
        {last?.satisfaction ? <SatisfactionDots value={last.satisfaction} /> : null}
      </div>
      {showOwner ? (
        <span className="text-[11.5px] text-muted-foreground">
          opiekun: {row.owner?.name ?? "—"}
        </span>
      ) : null}
      {canEdit ? (
        <Button
          size="sm"
          variant={row.overdue ? "primary" : "outline"}
          className="w-full"
          onClick={() => onTalk(row)}
        >
          Zapisz rozmowę
        </Button>
      ) : null}
    </li>
  );
}

function ColumnHead({ column }: { column: WeekColumn }) {
  const late = column.key === "before" && column.items.some((row) => row.overdue);
  return (
    <div
      className={cn(
        "flex items-baseline justify-between rounded-md border px-2.5 py-1.5 text-[13px]",
        late
          ? "border-destructive/30 bg-destructive-muted text-destructive-muted-foreground"
          : column.isToday
            ? "border-primary/30 bg-primary/10 text-primary"
            : "border-border bg-card",
      )}
    >
      <span className="font-semibold">{column.label}</span>
      <span className={cn("tabular-nums", !late && !column.isToday && "text-muted-foreground")}>
        {column.isToday ? `dziś${column.items.length ? ` · ${column.items.length}` : ""}` : column.items.length || "—"}
      </span>
    </div>
  );
}

interface BoardProps {
  data: CareWeek;
  showOwner: boolean;
  selectedId: number | null;
  onOpen: (row: WeekContact) => void;
  onTalk: (row: WeekContact) => void;
}

/**
 * Plan tygodnia opiekuna: „Zaległe · pn … pt”, dziś wyróżnione. Siatka
 * zawija kolumny, gdy obok otwarty jest panel osi konsultanta.
 */
export function WeekBoard({ data, showOwner, selectedId, onOpen, onTalk }: BoardProps) {
  const columns = weekColumns(data.contacts, data.week);
  return (
    <div
      className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] items-start gap-2.5"
      role="group"
      aria-label="Rozmowy z konsultantami w tym tygodniu"
    >
      {columns.map((column) => (
        <DayColumn
          key={column.key}
          column={column}
          data={data}
          showOwner={showOwner}
          selectedId={selectedId}
          onOpen={onOpen}
          onTalk={onTalk}
        />
      ))}
    </div>
  );
}

function DayColumn({
  column,
  data,
  showOwner,
  selectedId,
  onOpen,
  onTalk,
}: { column: WeekColumn } & BoardProps) {
  const [expanded, setExpanded] = useState(false);
  const { shown, hidden } = visibleCards(column.items, expanded, selectedId);
  return (
    <section
      className="flex min-w-0 flex-col gap-2"
      aria-label={column.isToday ? `${column.label} (dziś)` : column.label}
    >
      <ColumnHead column={column} />
      {column.items.length ? (
        <ul className="flex flex-col gap-2">
          {shown.map((row) => (
            <ContactCard
              key={row.contract_id}
              row={row}
              inBefore={column.key === "before"}
              today={data.week.today}
              canEdit={data.can_edit}
              showOwner={showOwner}
              selected={selectedId === row.contract_id}
              onOpen={onOpen}
              onTalk={onTalk}
            />
          ))}
        </ul>
      ) : (
        <p className="rounded-lg border border-dashed border-border px-2 py-3 text-center text-xs text-muted-foreground">
          {column.key === "before" ? "nic zaległego" : column.isPast ? "—" : "wolne"}
        </p>
      )}
      {hidden > 0 || expanded ? (
        <Button size="sm" variant="ghost" className="w-full" onClick={() => setExpanded((v) => !v)}>
          {hidden > 0 ? `Pokaż wszystkie (${column.items.length})` : "Pokaż mniej"}
        </Button>
      ) : null}
    </section>
  );
}
