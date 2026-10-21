"use client";

import Link from "next/link";
import {
  ArrowLeftRight,
  MessageSquareQuote,
  PhoneCall,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { personInitials } from "@/components/hr/people/hr-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CARE_KIND_LABELS, type CareBoardCard, type CareBoardKind } from "@/lib/api/care-board";
import { formatDateTimePl, formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { DUE_VARIANT, TileShell, type TileDrag } from "./CaseTile";
import { HealthDot, HealthWord } from "./HealthMark";
import { MoveMenu } from "./MoveMenu";
import {
  CARE_ACTION_LABELS,
  careCardHref,
  careDueBadge,
  type WorkColumn,
} from "./work-board-model";

export const CARE_KIND_ICONS: Record<CareBoardKind, LucideIcon> = {
  contact: PhoneCall,
  feedback: MessageSquareQuote,
  decision: ArrowLeftRight,
  demand: TrendingUp,
};

/** Akcja karty: okno z /care (F2/F3) albo — w Sprawach bez okien — link do opieki. */
export function CareActionButton({
  card,
  onAction,
  className,
}: {
  card: CareBoardCard;
  onAction: (() => void) | null;
  className?: string;
}) {
  const label = CARE_ACTION_LABELS[card.kind];
  const variant = card.overdue_days > 0 ? "primary" : "outline";
  if (onAction) {
    return (
      <Button
        size="sm"
        variant={variant}
        className={className}
        onClick={onAction}
        aria-label={`${label}: ${card.title}`}
      >
        {label}
      </Button>
    );
  }
  return (
    <Button size="sm" variant={variant} className={className} asChild>
      <Link href={careCardHref(card)} aria-label={`${label}: ${card.title}`}>
        {label}
      </Link>
    </Button>
  );
}

/** Umówiona rozmowa albo ponowna próba — ramka jak „odezwać się” na karcie sprawy. */
export function careStateNote(card: CareBoardCard): string | null {
  if (card.column === "in_progress" && card.scheduled_at) {
    return `umówione ${formatDateTimePl(card.scheduled_at)}`;
  }
  if (card.column === "waiting" && card.retry_on) {
    return `ponowna próba ${formatDayMonthPl(card.retry_on)}`;
  }
  return null;
}

/**
 * Karta opieki — ten sam układ co karta sprawy: ikona źródła, plakietka
 * „Opieka”, termin (czerwony po terminie), tytuł z kropką zdrowia, podtytuł
 * i cytat z ostatniej rozmowy, zdrowie słowem i kolorem, awatar opiekuna,
 * jedna akcja.
 */
export function CareTile({
  card,
  today,
  weekEnd,
  onOpen,
  onAction,
  onMove,
  drag,
  selected,
}: {
  card: CareBoardCard;
  today?: string;
  weekEnd?: string;
  onOpen: () => void;
  onAction: (() => void) | null;
  onMove: (target: WorkColumn) => void;
  drag?: TileDrag;
  selected?: boolean;
}) {
  const Icon = CARE_KIND_ICONS[card.kind];
  const due = careDueBadge(card, today, weekEnd);
  const dueVariant = due ? DUE_VARIANT[due.tone] : null;
  const state = careStateNote(card);
  return (
    <TileShell
      label={card.title}
      drag={drag}
      selected={selected}
      className={card.overdue_days > 0 ? "border-destructive/30" : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex min-w-0 items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">{CARE_KIND_LABELS[card.kind]}</span>
          <Badge size="sm" variant="soft" className="shrink-0">
            Opieka
          </Badge>
        </span>
        <span className="inline-flex items-center gap-1">
          {due && dueVariant ? (
            <Badge size="sm" variant={dueVariant} className="h-auto py-0.5">
              {due.text}
            </Badge>
          ) : due ? (
            <span className="text-[11.5px] text-muted-foreground">{due.text}</span>
          ) : null}
          <MoveMenu title={card.title} current={card.column} onMove={onMove} />
        </span>
      </div>
      <div className="flex items-start gap-1.5">
        {card.health ? (
          <HealthDot health={card.health} className="mt-1.5" />
        ) : (
          <span aria-hidden className="mt-1.5 size-2 shrink-0 rounded-full bg-muted-foreground/40" />
        )}
        <div className="min-w-0">
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Opieka: ${card.title}`}
            className="line-clamp-2 text-left font-semibold text-foreground hover:underline"
          >
            {card.title}
          </button>
          {card.subtitle ? (
            <p className="truncate text-xs text-muted-foreground">{card.subtitle}</p>
          ) : null}
        </div>
      </div>
      {state ? <p className="rounded-md bg-muted/60 px-2 py-1 text-xs">{state}</p> : null}
      {card.note_excerpt ? (
        <p className="line-clamp-2 rounded-md bg-muted/60 px-2 py-1 text-xs">„{card.note_excerpt}”</p>
      ) : null}
      <div className="flex items-center gap-2">
        <span className="flex min-w-0 flex-1 items-center gap-1.5">
          {card.health ? <HealthWord health={card.health} /> : null}
          {card.reason_label ? (
            <span className={cn("truncate text-[11.5px] text-muted-foreground")}>
              {card.health ? "· " : ""}
              {card.reason_label}
            </span>
          ) : null}
        </span>
        {card.owner_name ? (
          <span
            title={`opiekun: ${card.owner_name}`}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
          >
            <span aria-hidden>{personInitials(card.owner_name)}</span>
            <span className="sr-only">opiekun: {card.owner_name}</span>
          </span>
        ) : (
          <span className="shrink-0 text-xs text-muted-foreground">bez opiekuna</span>
        )}
      </div>
      <CareActionButton card={card} onAction={onAction} className="w-full" />
    </TileShell>
  );
}
