"use client";

import { personInitials } from "@/components/hr/people/hr-format";
import { PRIORITY_DOT, caseSubline, dueBadge } from "@/components/admin-cases/case-format";
import { Badge } from "@/components/ui/badge";
import { CASE_AREA_LABELS, CASE_STATUS_LABELS } from "@/lib/api/admin-cases";
import type { CareBoardCard } from "@/lib/api/care-board";
import { cn } from "@/lib/utils";

import { DUE_VARIANT } from "./CaseTile";
import { CARE_KIND_ICONS, CareActionButton } from "./CareTile";
import { HealthDot } from "./HealthMark";
import { WORK_COLUMN_LABELS, careDueBadge, listGroups, type WorkItem } from "./work-board-model";

function Avatar({ name }: { name: string | null | undefined }) {
  if (!name) return <span className="w-6 shrink-0" />;
  return (
    <span
      title={name}
      className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
    >
      <span aria-hidden>{personInitials(name)}</span>
      <span className="sr-only">{name}</span>
    </span>
  );
}

function Row({
  item,
  today,
  weekEnd,
  selected,
  onOpen,
  careAction,
}: {
  item: WorkItem;
  today?: string;
  weekEnd?: string;
  selected: boolean;
  onOpen: () => void;
  careAction: (card: CareBoardCard) => (() => void) | null;
}) {
  if (item.type === "case") {
    const card = item.card;
    const due = dueBadge(card, today, weekEnd);
    const variant = due ? DUE_VARIANT[due.tone] : null;
    return (
      <li
        aria-label={card.title}
        className={cn(
          "flex items-center gap-3 border-b border-border/60 px-3 py-2 last:border-b-0",
          selected && "bg-primary/5",
        )}
      >
        <span className={cn("size-2 shrink-0 rounded-full", PRIORITY_DOT[card.priority])} title={card.priority} />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Sprawa: ${card.title}`}
            className="block max-w-full truncate text-left text-sm font-semibold text-foreground hover:underline"
          >
            {card.title}
          </button>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            {card.contract?.health ? <HealthDot health={card.contract.health} /> : null}
            <span className="truncate">
              {[caseSubline(card), CASE_AREA_LABELS[card.area].toLowerCase(), CASE_STATUS_LABELS[card.status].toLowerCase()]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </p>
        </div>
        {due && variant ? (
          <Badge size="sm" variant={variant} className="h-auto shrink-0 py-0.5">
            {due.text}
          </Badge>
        ) : null}
        <Avatar name={card.assignee?.name} />
      </li>
    );
  }
  const card = item.card;
  const Icon = CARE_KIND_ICONS[card.kind];
  const due = careDueBadge(card, today, weekEnd);
  const variant = due ? DUE_VARIANT[due.tone] : null;
  return (
    <li
      aria-label={card.title}
      className={cn(
        "flex items-center gap-3 border-b border-border/60 px-3 py-2 last:border-b-0",
        selected && "bg-primary/5",
      )}
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          {card.health ? <HealthDot health={card.health} /> : null}
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Opieka: ${card.title}`}
            className="truncate text-left text-sm font-semibold text-foreground hover:underline"
          >
            {card.title}
          </button>
          <Badge size="sm" variant="soft" className="shrink-0">
            Opieka
          </Badge>
        </span>
        <p className="truncate text-xs text-muted-foreground">
          {[card.subtitle, card.reason_label, card.column !== "new" ? WORK_COLUMN_LABELS[card.column].toLowerCase() : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      {due && variant ? (
        <Badge size="sm" variant={variant} className="h-auto shrink-0 py-0.5">
          {due.text}
        </Badge>
      ) : null}
      <Avatar name={card.owner_name} />
      <CareActionButton card={card} onAction={careAction(card)} className="hidden shrink-0 sm:inline-flex" />
    </li>
  );
}

/**
 * Widok „Lista” — te same karty co tablica, jako kolejka wierszy w grupach
 * Po terminie · Do piątku · Decyzje · Popyt (i reszta bez terminu w tygodniu).
 */
export function WorkList({
  items,
  today,
  weekEnd,
  selectedKey,
  onOpen,
  careAction,
}: {
  items: readonly WorkItem[];
  today?: string;
  weekEnd?: string;
  selectedKey: string | null;
  onOpen: (item: WorkItem) => void;
  careAction: (card: CareBoardCard) => (() => void) | null;
}) {
  const groups = listGroups(items, weekEnd);
  if (!groups.length) {
    return <p className="text-sm text-muted-foreground">Nic nie czeka na zrobienie.</p>;
  }
  return (
    <div className="space-y-3" aria-label="Kolejka do zrobienia">
      {groups.map((group) => (
        <section key={group.key} aria-labelledby={`work-list-${group.key}`} className="rounded-xl border border-border bg-card">
          <h3
            id={`work-list-${group.key}`}
            className={cn(
              "flex items-center gap-2 border-b border-border px-3 py-2 text-[13.5px] font-semibold",
              group.key === "overdue" && "text-destructive",
            )}
          >
            {group.label}
            <Badge size="sm" variant={group.key === "overdue" ? "danger" : "neutral"} className="tabular-nums">
              {group.items.length}
            </Badge>
          </h3>
          <ul>
            {group.items.map((item) => (
              <Row
                key={item.key}
                item={item}
                today={today}
                weekEnd={weekEnd}
                selected={selectedKey === item.key}
                onOpen={() => onOpen(item)}
                careAction={careAction}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
