"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";

import { CaseFormDialog } from "@/components/admin-cases/CaseFormDialog";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useBoBoard, useBoSync, type BoBoard, type BoCard, type BoTeam } from "@/lib/api/back-office";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";

import {
  FILTER_LABELS,
  dueTone,
  defaultTeam,
  formatDay,
  matchesFilter,
  matchesSearch,
  teamCount,
  waitLabel,
  type BoFilter,
} from "./board-model";
import { CardPanel } from "./CardPanel";
import { CardTile } from "./CardTile";
import { TriageStrip } from "./TriageStrip";
import { useCardCommands, type CardCommands } from "./use-card-commands";

const VISIBLE_IN_LANE = 5;
const STATUS_COLUMNS = [
  { id: "new", label: "Nowa" },
  { id: "in_progress", label: "W toku" },
  { id: "waiting", label: "Czeka na kogoś" },
] as const;

function Lane({
  lane,
  cards,
  board,
  commands,
  onOpen,
}: {
  lane: BoTeam["lanes"][number];
  cards: BoCard[];
  board: BoBoard;
  commands: CardCommands;
  onOpen: (card: BoCard) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? cards : cards.slice(0, VISIBLE_IN_LANE);
  const hidden = cards.length - visible.length;
  return (
    <section className="min-w-0 rounded-xl bg-muted/60 p-2" aria-label={lane.label}>
      <header className="px-1.5 pb-2 pt-1">
        <div className="flex items-center justify-between gap-2">
          <h3 className="truncate text-sm font-semibold">{lane.label}</h3>
          <Badge variant={cards.length > 0 ? "soft" : "neutral"} size="sm">
            {cards.length}
          </Badge>
        </div>
        <p className="mt-0.5 truncate text-[11px] leading-tight text-muted-foreground">{lane.description}</p>
      </header>
      {cards.length === 0 ? (
        <p className="rounded-lg border border-dashed bg-card p-3 text-xs text-muted-foreground">
          Nic tu teraz nie czeka.
        </p>
      ) : null}
      <ul className="space-y-2">
        {visible.map((card) => (
          <CardTile key={card.id} card={card} board={board} commands={commands} onOpen={onOpen} />
        ))}
      </ul>
      {hidden > 0 || expanded ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="px-1.5 pt-2 text-[11px] text-muted-foreground hover:text-foreground"
        >
          {expanded ? "Zwiń" : `+ ${hidden} kolejnych`}
        </button>
      ) : null}
    </section>
  );
}

function StatusColumns({
  cards,
  board,
  commands,
  onOpen,
}: {
  cards: BoCard[];
  board: BoBoard;
  commands: CardCommands;
  onOpen: (card: BoCard) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {STATUS_COLUMNS.map((column) => {
        const inColumn = cards.filter((card) => card.state === column.id);
        return (
          <Lane
            key={column.id}
            lane={{ id: column.id, label: column.label, description: "" }}
            cards={inColumn}
            board={board}
            commands={commands}
            onOpen={onOpen}
          />
        );
      })}
    </div>
  );
}

function AllList({
  cards,
  board,
  onOpen,
  commands,
}: {
  cards: BoCard[];
  board: BoBoard;
  onOpen: (card: BoCard) => void;
  commands: CardCommands;
}) {
  const laneLabel = useMemo(() => {
    const labels = new Map<string, string>();
    board.teams.forEach((team) => team.lanes.forEach((lane) => labels.set(lane.id, lane.label)));
    return labels;
  }, [board.teams]);
  const teamLabel = (id: string) => board.teams.find((team) => team.id === id)?.label ?? id;
  if (cards.length === 0) {
    return (
      <p className="rounded-lg border border-dashed bg-card p-3 text-sm text-muted-foreground">
        Nic tu teraz nie czeka.
      </p>
    );
  }
  return (
    <div className="max-h-[calc(100dvh-300px)] min-h-48 overflow-y-auto rounded-xl border bg-card">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card text-left text-[11px] uppercase tracking-wide text-muted-foreground">
          <tr className="border-b">
            <th className="px-4 py-2 font-medium">Termin</th>
            <th className="py-2 font-medium">Typ</th>
            <th className="py-2 font-medium">Sprawa</th>
            <th className="py-2 font-medium">Zespół</th>
            <th className="py-2 font-medium">Czeka</th>
            <th className="px-4 py-2 font-medium">Kto</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => (
            <tr key={card.id} className="border-b last:border-0">
              <td className="px-4 py-2">
                <Badge variant={dueTone(card.due_on, board.today)} size="sm">
                  {formatDay(card.due_on)}
                </Badge>
              </td>
              <td className="py-2 text-xs">{laneLabel.get(card.lane) ?? card.lane}</td>
              <td className="max-w-[320px] py-2">
                <button
                  type="button"
                  onClick={() => onOpen(card)}
                  className="block max-w-full truncate text-left font-medium hover:underline"
                >
                  {card.person || card.title}
                </button>
                <span className="block truncate text-xs text-muted-foreground">
                  {[card.person ? card.title : null, card.client].filter(Boolean).join(" · ")}
                </span>
              </td>
              <td className="py-2 text-xs text-muted-foreground">{teamLabel(card.team)}</td>
              <td className="py-2 text-xs text-muted-foreground">{waitLabel(card, board.today)}</td>
              <td className="px-4 py-2 text-xs">
                {card.assignee ? (
                  card.assignee.name
                ) : card.actions.length > 0 ? (
                  <span className="text-muted-foreground">akcept na karcie</span>
                ) : board.me.is_lead ? (
                  <Button size="sm" className="h-7 px-2.5 text-xs" onClick={() => onOpen(card)}>
                    Przydziel
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2.5 text-xs"
                    onClick={() =>
                      commands.take(card, { substitute: !board.me.teams.includes(card.team) })
                    }
                  >
                    Biorę
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface QueueBoardProps {
  /** „Po statusie” zespołu Opieka: dotychczasowy kanban spraw 1:1 (warunek z 22.10). */
  careStatusBoard: ReactNode | null;
}

/**
 * Kolejka całego back office'u. `?zespol=care|finance|contracts|orders|all`,
 * `?uklad=status`, `?filtr=`, `?karta=<id>` (dzwonki, linki).
 */
export function QueueBoard({ careStatusBoard }: QueueBoardProps) {
  const params = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const { showToast } = useToast();
  const query = useBoBoard();
  const sync = useBoSync();
  const commands = useCardCommands();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const board = query.data;

  const write = (change: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(window.location.search);
    change(next);
    const qs = next.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (!board) {
    if (state === "forbidden" || state === "not_found" || state === "error") {
      return <QueryStateNotice state={state} onRetry={() => query.refetch()} />;
    }
    return <p className="p-4 text-sm text-muted-foreground">Ładowanie kolejki…</p>;
  }

  const teamId = params?.get("zespol") || defaultTeam(board);
  const layout = params?.get("uklad") === "status" ? "status" : "type";
  const filter = (params?.get("filtr") as BoFilter) || "all";
  const cardParam = Number(params?.get("karta"));
  const openId = Number.isInteger(cardParam) && cardParam > 0 ? cardParam : null;
  const activeTeam = board.teams.find((team) => team.id === teamId);
  const shown = board.cards.filter(
    (card) =>
      matchesFilter(card, filter, board.me.user_id, board.today) && matchesSearch(card, search),
  );
  const filters: BoFilter[] = [
    "all",
    "free",
    "mine",
    "week",
    "nobody",
    ...(board.me.is_lead ? (["escalated"] as const) : []),
  ];
  const onOpen = (card: BoCard) => write((next) => next.set("karta", String(card.id)));
  // Kanban Opieki ma własne filtry i szukanie; dwa paski obok siebie mylą.
  const kanban = activeTeam?.id === "care" && layout === "status" && Boolean(careStatusBoard);

  return (
    <div className="space-y-2" data-help="hr.care.queue">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Zespoły">
          {board.teams.map((team) => (
            <button
              key={team.id}
              type="button"
              role="tab"
              aria-selected={teamId === team.id}
              onClick={() => write((next) => next.set("zespol", team.id))}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm",
                teamId === team.id ? "border-primary bg-primary/10 font-medium text-primary" : "bg-card text-muted-foreground",
              )}
            >
              {team.label} <span className="text-xs tabular-nums">{teamCount(team, board.cards)}</span>
            </button>
          ))}
          <button
            type="button"
            role="tab"
            aria-selected={teamId === "all"}
            onClick={() => write((next) => next.set("zespol", "all"))}
            className={cn(
              "rounded-full border px-3 py-1 text-sm",
              teamId === "all" ? "border-primary bg-primary/10 font-medium text-primary" : "bg-card text-muted-foreground",
            )}
          >
            Wszystko
          </button>
        </div>
        <span className="inline-flex overflow-hidden rounded-md border text-xs" role="group" aria-label="Układ tablicy">
          {(
            [
              ["type", "Po typie"],
              ["status", "Po statusie"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={layout === id}
              onClick={() =>
                write((next) => {
                  if (id === "status") next.set("uklad", "status");
                  else next.delete("uklad");
                })
              }
              className={cn(
                "px-2.5 py-1",
                layout === id ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </span>
      </div>

      {kanban ? null : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="inline-flex overflow-hidden rounded-md border">
              {filters.map((id) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={filter === id}
                  onClick={() =>
                    write((next) => {
                      if (id === "all") next.delete("filtr");
                      else next.set("filtr", id);
                    })
                  }
                  className={cn(
                    "px-2.5 py-1",
                    filter === id ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground",
                  )}
                >
                  {FILTER_LABELS[id]}
                </button>
              ))}
            </span>
            <span className="flex items-center gap-2">
              <Input
                aria-label="Szukaj spraw"
                placeholder="Szukaj spraw…"
                className="h-7 w-40 text-xs"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <Button size="sm" variant="outline" className="h-7 px-2.5 text-xs" onClick={() => setCreating(true)}>
                Nowa sprawa
              </Button>
              {board.me.is_lead ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 gap-1 px-2 text-xs"
                  disabled={sync.isPending}
                  onClick={() =>
                    sync.mutate(undefined, {
                      onError: (error) =>
                        showToast(apiErrorMessage(error, "Nie udało się odświeżyć kolejki."), "error"),
                    })
                  }
                >
                  <RefreshCw aria-hidden className="size-3" /> Odśwież
                </Button>
              ) : null}
            </span>
          </div>

          <p className="text-xs text-muted-foreground">
            Bez osoby: <span className="font-medium text-foreground">{board.counts.unassigned}</span> · po terminie i bez
            osoby: <span className="font-medium text-destructive">{board.counts.overdue_unassigned}</span> · u kierownika po
            dniu roboczym: <span className="font-medium text-foreground">{board.counts.escalated}</span> · moje w toku:{" "}
            <span
              className={cn(
                "font-medium",
                board.me.in_progress > board.me.limit ? "text-destructive" : "text-foreground",
              )}
            >
              {board.me.in_progress} z {board.me.limit}
            </span>
          </p>

        </>
      )}

      {board.me.is_lead && !activeTeam ? <TriageStrip board={board} /> : null}
      {activeTeam && layout === "status" ? (
        activeTeam.id === "care" && careStatusBoard ? (
          careStatusBoard
        ) : (
          <StatusColumns
            cards={shown.filter((card) => card.team === activeTeam.id)}
            board={board}
            commands={commands}
            onOpen={onOpen}
          />
        )
      ) : activeTeam ? (
        <div className="grid grid-cols-4 gap-3">
          {activeTeam.lanes.map((lane) => (
            <Lane
              key={lane.id}
              lane={lane}
              cards={shown.filter((card) => card.team === activeTeam.id && card.lane === lane.id)}
              board={board}
              commands={commands}
              onOpen={onOpen}
            />
          ))}
        </div>
      ) : (
        <AllList cards={shown} board={board} onOpen={onOpen} commands={commands} />
      )}

      {!openId ? commands.dialogs : null}
      {openId ? (
        <CardPanel
          cardId={openId}
          board={board}
          commands={commands}
          onClose={() => write((next) => next.delete("karta"))}
        />
      ) : null}
      {creating ? <CaseFormDialog open onOpenChange={setCreating} onCreated={() => sync.mutate()} /> : null}
    </div>
  );
}
