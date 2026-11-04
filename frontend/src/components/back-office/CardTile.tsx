"use client";

import Link from "next/link";
import { ArrowUpRight, Clock, Hand, Lock, UserRoundCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { BoBoard, BoCard } from "@/lib/api/back-office";
import { cn } from "@/lib/utils";

import { amountLabel, dueTone, formatDay, stepSummary, waitLabel } from "./board-model";
import type { CardCommands } from "./use-card-commands";

export const ACTION_LABELS: Record<string, string> = {
  approve: "Akceptuj",
  return: "Zwróć",
  approve_all: "Zatwierdź wszystkie",
  cancel_all: "Anuluj",
  mark_done: "Zrobione",
};

function initials(name: string | null): string {
  return (name ?? "?")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2);
}

interface CardTileProps {
  card: BoCard;
  board: BoBoard;
  commands: CardCommands;
  onOpen: (card: BoCard) => void;
}

export function CardTile({ card, board, commands, onOpen }: CardTileProps) {
  const own = board.me.is_lead || board.me.teams.includes(card.team);
  const tone = dueTone(card.due_on, board.today);
  const wait = waitLabel(card, board.today);
  const steps = stepSummary(card);
  const amount = amountLabel(card);
  const heading = card.person || card.title;
  const second = [card.person ? card.title : null, card.client].filter(Boolean).join(" · ");
  return (
    <li className={cn("rounded-lg border bg-card p-2.5 shadow-xs", card.assignee && "opacity-70")}>
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => onOpen(card)}
          className="min-w-0 truncate text-left text-sm font-medium hover:underline"
        >
          {heading}
        </button>
        <Badge variant={tone} size="sm">
          {formatDay(card.due_on)}
        </Badge>
      </div>
      {second ? <p className="truncate text-xs text-muted-foreground">{second}</p> : null}
      {steps ? <p className="truncate text-xs font-medium text-primary">{steps}</p> : null}
      {amount ? <p className="text-xs tabular-nums text-muted-foreground">razem {amount}</p> : null}
      {card.source_kind === "bonus" && !amount ? (
        <p className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <Lock aria-hidden className="size-3" /> kwota dla Płac
        </p>
      ) : null}
      {wait ? (
        <p
          className={cn(
            "mt-0.5 flex items-center gap-1 truncate text-xs",
            card.escalated && !card.assignee ? "font-medium text-destructive" : "text-muted-foreground",
          )}
        >
          <Clock aria-hidden className="size-3 shrink-0" /> {wait}
        </p>
      ) : null}
      {card.priority && !card.assignee ? (
        <p className="truncate text-xs text-muted-foreground">
          Ostatnio rozmawiał(a): {card.priority.name ?? "inna osoba"}
        </p>
      ) : null}
      <div className="mt-1.5 flex items-center justify-between gap-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {card.actions.length > 0 ? (
            card.actions.map((action, index) => (
              <Button
                key={action}
                size="sm"
                variant={index === 0 ? "primary" : "outline"}
                className="h-7 px-2.5 text-xs"
                disabled={commands.busy}
                onClick={() => commands.runAction(card, action)}
              >
                {ACTION_LABELS[action]}
              </Button>
            ))
          ) : card.assignee ? (
            <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
              <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[9px] font-semibold text-primary">
                {initials(card.assignee.name)}
              </span>
              <span className="truncate">
                {card.assignee.name}
                {card.substituting ? " (zastępuje)" : ""}
              </span>
            </span>
          ) : own ? (
            <Button
              size="sm"
              className="h-7 gap-1 px-2.5 text-xs"
              disabled={commands.busy}
              onClick={() => commands.take(card, { substitute: false })}
            >
              <Hand aria-hidden className="size-3.5" /> Biorę
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              className="h-7 gap-1 px-2.5 text-xs"
              disabled={commands.busy}
              onClick={() => commands.take(card, { substitute: true })}
            >
              <UserRoundCheck aria-hidden className="size-3.5" /> Zastępuję
            </Button>
          )}
        </div>
        {card.href ? (
          <Link
            href={card.href}
            className="inline-flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground"
            aria-label={`Otwórz ekran pracy: ${heading}`}
          >
            {card.actions.length > 0 ? null : "Otwórz"} <ArrowUpRight aria-hidden className="size-3" />
          </Link>
        ) : null}
      </div>
    </li>
  );
}
