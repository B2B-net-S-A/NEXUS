"use client";

import Link from "next/link";
import { ArrowUpRight, CalendarClock, Clock, Hand, Lock, Send, UserRoundCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { BoBoard, BoCard, BoTeamId } from "@/lib/api/back-office";
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

/** Kropka rodziny etykiet — jeden spokojny akcent zamiast koloru zespołu. */
const FAMILY_DOT: Record<BoTeamId, string> = {
  care: "bg-primary",
  finance: "bg-success",
  contracts: "bg-warning",
  orders: "bg-info",
};

export function initials(name: string | null | undefined): string {
  return (name ?? "?")
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function labelText(board: Pick<BoBoard, "labels">, lane: string): string {
  return board.labels.find((label) => label.id === lane)?.label ?? lane;
}

export function LabelChip({
  board,
  card,
  className,
}: {
  board: Pick<BoBoard, "labels">;
  card: Pick<BoCard, "lane" | "team"> & { notice?: BoCard["notice"] };
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-card px-2 text-[11px] font-medium text-foreground",
        className,
      )}
    >
      <span aria-hidden className={cn("size-1.5 rounded-full", FAMILY_DOT[card.team])} />
      {/* Sprawa z maila z propozycją: rodzaj zamiast „Zakończenie” (0759). */}
      {card.notice?.label ?? labelText(board, card.lane)}
    </span>
  );
}

export function FamilyDot({ family }: { family: BoTeamId }) {
  return <span aria-hidden className={cn("inline-block size-1.5 rounded-full", FAMILY_DOT[family])} />;
}

export function DueChip({ due, today }: { due: string | null; today: string }) {
  const tone = dueTone(due, today);
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded-md px-1.5 text-[11px] tabular-nums",
        tone === "danger" && "bg-destructive-muted text-destructive-muted-foreground",
        tone === "warning" && "bg-warning-muted text-warning-muted-foreground",
        tone === "neutral" && "bg-muted text-muted-foreground",
      )}
    >
      {formatDay(due)}
    </span>
  );
}

export function Avatar({ name }: { name: string | null | undefined }) {
  return (
    <span
      aria-hidden
      className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[9px] font-semibold text-primary"
    >
      {initials(name)}
    </span>
  );
}

function meetingLabel(startAt: string): string {
  const start = new Date(startAt);
  const day = `${String(start.getDate()).padStart(2, "0")}.${String(start.getMonth() + 1).padStart(2, "0")}`;
  const time = start.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Warsaw" });
  return `${day} ${time}`;
}

interface CardTileProps {
  card: BoCard;
  board: BoBoard;
  commands: CardCommands;
  onOpen: (card: BoCard) => void;
}

/** Kafelek sprawy: etykieta, termin, osoba, klient, kto ma albo „Biorę”. */
export function CardTile({ card, board, commands, onOpen }: CardTileProps) {
  const own = board.me.is_lead || board.me.teams.includes(card.team);
  const wait = waitLabel(card, board.today);
  const steps = stepSummary(card);
  const amount = amountLabel(card);
  const heading = card.person || card.title;
  const second = card.client ?? (card.person ? card.title : null);
  const outside = card.state === "waiting" && card.outside_team
    ? board.outside_teams.find((team) => team.id === card.outside_team)?.label
    : null;
  return (
    <li className="rounded-lg border border-border bg-card p-2.5 shadow-xs hover:border-primary/40">
      <div className="flex items-start justify-between gap-2">
        <LabelChip board={board} card={card} />
        <DueChip due={card.due_on} today={board.today} />
      </div>
      <button
        type="button"
        onClick={() => onOpen(card)}
        className="mt-1.5 block w-full min-w-0 truncate text-left text-[13px] font-medium leading-5 hover:underline"
      >
        {heading}
      </button>
      {second ? <p className="truncate text-[11.5px] text-muted-foreground">{second}</p> : null}
      {card.notice ? (
        <p className="mt-1 truncate rounded-md bg-muted px-1.5 text-[11px] text-foreground">
          Z maila · do potwierdzenia
          {card.notice.last_day ? ` · koniec ${formatDay(card.notice.last_day)}` : ""}
        </p>
      ) : null}
      {card.meeting ? (
        <p className="mt-1 inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 text-[11px] text-primary">
          <CalendarClock aria-hidden className="size-3" /> Rozmowa {meetingLabel(card.meeting.start_at)} ·{" "}
          {card.meeting.topic}
        </p>
      ) : null}
      {steps ? <p className="truncate text-[11.5px] font-medium text-primary">{steps}</p> : null}
      {amount ? <p className="text-[11.5px] tabular-nums text-muted-foreground">razem {amount}</p> : null}
      {card.source_kind === "bonus" && !amount ? (
        <p className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
          <Lock aria-hidden className="size-3" /> kwota dla Płac
        </p>
      ) : null}
      {outside ? (
        <p className="mt-0.5 flex items-center gap-1 truncate text-[11.5px] text-muted-foreground">
          <Send aria-hidden className="size-3 shrink-0" /> {outside}
          {card.waiting_on ? `: ${card.waiting_on}` : ""}
        </p>
      ) : wait && card.assignee == null ? (
        <p
          className={cn(
            "mt-0.5 flex items-center gap-1 truncate text-[11.5px]",
            card.escalated || wait.includes("dni") ? "text-destructive" : "text-muted-foreground",
          )}
        >
          <Clock aria-hidden className="size-3 shrink-0" /> {wait}
        </p>
      ) : card.state === "waiting" && card.waiting_on ? (
        <p className="mt-0.5 truncate text-[11.5px] text-muted-foreground">czeka na: {card.waiting_on}</p>
      ) : null}
      {card.priority && !card.assignee ? (
        <p className="truncate text-[11.5px] text-muted-foreground">
          Ostatnio rozmawiał(a): {card.priority.name ?? "inna osoba"}
        </p>
      ) : null}
      <div className="mt-2 flex items-center justify-between gap-1.5">
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
            <span className="inline-flex min-w-0 items-center gap-1.5 text-[11.5px] text-muted-foreground">
              <Avatar name={card.assignee.name} />
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
