"use client";

import Link from "next/link";
import {
  ArrowLeftRight,
  ClipboardList,
  MessageSquareQuote,
  PhoneCall,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { personInitials } from "@/components/hr/people/hr-format";
import { shortNames } from "@/components/care/week/week-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CareBoardCard, CareBoardKind } from "@/lib/api/care-board";
import { formatDayMonthPl } from "@/lib/date-pl";

import { DUE_VARIANT, TileShell, type TileDrag } from "./CaseTile";
import { HealthDot, HealthWord } from "./HealthMark";
import { MoveMenu } from "./MoveMenu";
import {
  careActionHref,
  careActionLabel,
  careBadge,
  careHeaderText,
  careStateText,
  careTileTitle,
  dataSummaryText,
  type WorkColumn,
} from "./work-board-model";

export const CARE_KIND_ICONS: Record<CareBoardKind, LucideIcon> = {
  contact: PhoneCall,
  feedback: MessageSquareQuote,
  decision: ArrowLeftRight,
  demand: TrendingUp,
  data: ClipboardList,
};

/** Akcja karty: okno z /care (F2/F3) albo — w Sprawach bez okien, przy danych i popycie bez menedżera — link. */
export function CareActionButton({
  card,
  onAction,
  className,
}: {
  card: CareBoardCard;
  onAction: (() => void) | null;
  className?: string;
}) {
  const label = careActionLabel(card);
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
      <Link href={careActionHref(card)} aria-label={`${label}: ${card.title}`}>
        {label}
      </Link>
    </Button>
  );
}

/** Linia stanu karty — reguła w `careStateText` (model, z testami). */
export const careStateNote = careStateText;

/** „„Dobrze, chce więcej pracy…” · 26.09” — cytat z ostatniej rozmowy z datą. */
export function CareQuote({ card, className }: { card: CareBoardCard; className?: string }) {
  if (!card.note_excerpt) return null;
  return (
    <p className={className ?? "line-clamp-2 text-xs text-muted-foreground"}>
      „{card.note_excerpt}”{card.note_on ? ` · ${formatDayMonthPl(card.note_on)}` : ""}
    </p>
  );
}

/** Popyt (R4): menedżer działu i otwarta rekrutacja klienta. */
export function demandFacts(card: CareBoardCard): string | null {
  if (card.kind !== "demand" || !card.demand) return null;
  const manager = card.demand.manager?.name
    ? `Menedżer: ${card.demand.manager.name}`
    : "Menedżer nieznany — najpierw „Kto komu podlega”";
  const job = card.demand.open_job
    ? `Otwarta rekrutacja: ${card.demand.open_job.title}`
    : "Brak otwartej rekrutacji";
  return `${manager} · ${job}`;
}

function Avatar({ name, kind }: { name: string | null; kind: CareBoardKind }) {
  if (!name) {
    return kind === "data" || kind === "demand" ? null : (
      <span className="shrink-0 text-xs text-muted-foreground">bez opiekuna</span>
    );
  }
  return (
    <span
      title={`opiekun: ${name}`}
      className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
    >
      <span aria-hidden>{personInitials(name)}</span>
      <span className="sr-only">opiekun: {name}</span>
    </span>
  );
}

/**
 * Karta opieki — ten sam układ co karta sprawy (makieta K1): plakietka
 * „Opieka” z powodem („rozmowa · dzień 30”), termin („3 dni po”, umówiona —
 * „24.10 · 14:00”, opinia — „czeka od 19.10”), tytuł „Rozmowa: osoba” z kropką
 * zdrowia, cytat z ostatniej rozmowy, ramka „nie odbiera — spróbować 25.10”,
 * zdrowie słowem · klient, jedna akcja i awatar opiekuna.
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
  const badge = careBadge(card, today, weekEnd);
  const badgeVariant = badge ? DUE_VARIANT[badge.tone] : null;
  const state = careStateText(card);
  const title = careTileTitle(card);
  const subtitle =
    card.kind === "feedback" && card.consultants?.length
      ? [card.client_name, `o: ${shortNames(card.consultants.map((person) => person.name))}`]
          .filter(Boolean)
          .join(" · ")
      : card.kind === "contact" || card.kind === "decision"
        ? null
        : card.subtitle;
  const facts = card.kind === "data" && card.data ? dataSummaryText(card.data) : demandFacts(card);
  return (
    <TileShell
      label={title}
      drag={drag}
      selected={selected}
      className={card.overdue_days > 0 ? "border-destructive/30" : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex min-w-0 items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <Badge size="sm" variant="soft" className="shrink-0">
            Opieka
          </Badge>
          <span className="truncate">{careHeaderText(card)}</span>
        </span>
        <span className="inline-flex shrink-0 items-center gap-1">
          {badge && badgeVariant ? (
            <Badge size="sm" variant={badgeVariant} className="h-auto py-0.5">
              {badge.text}
            </Badge>
          ) : badge ? (
            <span className="text-[11.5px] text-muted-foreground">{badge.text}</span>
          ) : null}
          {card.kind !== "data" ? <MoveMenu title={title} current={card.column} onMove={onMove} /> : null}
        </span>
      </div>
      <div className="flex items-start gap-1.5">
        {card.health ? <HealthDot health={card.health} className="mt-1.5" /> : null}
        <div className="min-w-0">
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Opieka: ${title}`}
            className="line-clamp-2 text-left font-semibold text-foreground hover:underline"
          >
            {title}
          </button>
          {subtitle ? <p className="truncate text-xs text-muted-foreground">{subtitle}</p> : null}
        </div>
      </div>
      <CareQuote card={card} />
      {facts ? <p className="text-xs text-muted-foreground">{facts}</p> : null}
      {state ? <p className="rounded-md bg-muted/60 px-2 py-1 text-xs">{state}</p> : null}
      {card.kind === "contact" || card.kind === "decision" ? (
        <p className="flex min-w-0 items-center gap-1 text-[11.5px] text-muted-foreground">
          {card.health ? <HealthWord health={card.health} /> : null}
          <span className="truncate">
            {card.health && card.client_name ? "· " : ""}
            {card.client_name}
          </span>
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        {card.column === "waiting" && card.kind === "contact" ? (
          <span className="flex-1" />
        ) : (
          <CareActionButton card={card} onAction={onAction} className="flex-1" />
        )}
        <Avatar name={card.owner_name} kind={card.kind} />
      </div>
    </TileShell>
  );
}
