"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { Hand, Plus, RefreshCw, Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBoBoard,
  useBoSync,
  useTakeNext,
  type BoBoard,
  type BoCard,
} from "@/lib/api/back-office";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";

import {
  COLUMN_LABELS,
  COLUMNS,
  FILTER_LABELS,
  columnOf,
  isOverdue,
  labelCounts,
  matchesFilter,
  matchesLabels,
  matchesSearch,
  waitLabel,
  type BoColumn,
  type BoFilter,
} from "./board-model";
import { CardPanel } from "./CardPanel";
import { Avatar, CardTile, DueChip, FamilyDot, LabelChip } from "./CardTile";
import { NewCaseDialog } from "./NewCaseDialog";
import { TriageStrip } from "./TriageStrip";
import { useCardCommands, type CardCommands } from "./use-card-commands";

const FILTERS: BoFilter[] = ["all", "free", "mine", "overdue", "week"];

function conflictCode(error: unknown): string | null {
  const detail = (
    error as { response?: { data?: { detail?: { code?: string } } } }
  )?.response?.data?.detail;
  return typeof detail === "object" && detail ? (detail.code ?? null) : null;
}

function statusOf(error: unknown): number | null {
  return (
    (error as { response?: { status?: number } })?.response?.status ?? null
  );
}

function Column({
  column,
  cards,
  board,
  commands,
  onOpen,
}: {
  column: BoColumn;
  cards: BoCard[];
  board: BoBoard;
  commands: CardCommands;
  onOpen: (card: BoCard) => void;
}) {
  return (
    <section
      className="flex min-w-0 flex-col rounded-xl bg-muted/60 p-2"
      aria-label={COLUMN_LABELS[column]}
    >
      <header className="flex items-center justify-between gap-2 px-1.5 pb-2 pt-1">
        <h3 className="truncate text-[13px] font-semibold">
          {COLUMN_LABELS[column]}
        </h3>
        <span className="rounded-full bg-card px-1.5 text-[11px] tabular-nums text-muted-foreground">
          {cards.length}
        </span>
      </header>
      {cards.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-card p-2.5 text-[11.5px] text-muted-foreground">
          {column === "outside"
            ? "Nic nie czeka na inny dział. Sprawę przekazujesz przyciskiem „Na zewnątrz” w karcie."
            : "Nic tu teraz nie czeka."}
        </p>
      ) : null}
      <ul className="max-h-[calc(100dvh-340px)] min-h-24 space-y-2 overflow-y-auto pr-0.5">
        {cards.map((card) => (
          <CardTile
            key={card.id}
            card={card}
            board={board}
            commands={commands}
            onOpen={onOpen}
          />
        ))}
      </ul>
    </section>
  );
}

function ListView({
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
  if (cards.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-card p-3 text-sm text-muted-foreground">
        Nic tu teraz nie czeka.
      </p>
    );
  }
  return (
    <div className="max-h-[calc(100dvh-300px)] min-h-48 overflow-y-auto rounded-xl border border-border bg-card">
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-[1] bg-card text-left text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          <tr className="border-b border-border/60">
            <th className="px-3 py-2">Termin</th>
            <th className="py-2">Etykieta</th>
            <th className="py-2">Sprawa</th>
            <th className="py-2">Stan</th>
            <th className="px-3 py-2">Kto</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => (
            <tr
              key={card.id}
              className="border-b border-border/60 last:border-0"
            >
              <td className="px-3 py-1.5">
                <DueChip due={card.due_on} today={board.today} />
              </td>
              <td className="py-1.5">
                <LabelChip board={board} card={card} />
              </td>
              <td className="max-w-[360px] py-1.5">
                <button
                  type="button"
                  onClick={() => onOpen(card)}
                  className="block max-w-full truncate text-left text-[13px] font-medium hover:underline"
                >
                  {card.person || card.title}
                </button>
                <span className="block truncate text-[11.5px] text-muted-foreground">
                  {[card.person ? card.title : null, card.client]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </td>
              <td className="py-1.5 text-[11.5px] text-muted-foreground">
                {COLUMN_LABELS[columnOf(card)]}
                {card.assignee == null && waitLabel(card, board.today)
                  ? ` · ${waitLabel(card, board.today)}`
                  : ""}
              </td>
              <td className="px-3 py-1.5 text-[11.5px]">
                {card.assignee ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Avatar name={card.assignee.name} />
                    {card.assignee.name}
                  </span>
                ) : card.actions.length > 0 ? (
                  <span className="text-muted-foreground">
                    akcept na karcie
                  </span>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2.5 text-xs"
                    onClick={() =>
                      commands.take(card, {
                        substitute:
                          !board.me.is_lead &&
                          !board.me.teams.includes(card.team),
                      })
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
  /**
   * Dotychczasowy kanban Opieki 1:1 (warunek Artura z 22.10.2026) jako trzeci
   * widok „Tablica Opieki”; `null`, gdy osoba nie ma do niego dostępu.
   */
  careStatusBoard?: ReactNode | null;
}

type View = "tablica" | "lista" | "opieka";

/**
 * Sprawy całego back office'u (jeden zespół, decyzje Artura z 19.11.2026):
 * tablica stanów Nowe · W toku · Czeka na kogoś · Na zewnątrz, etykiety zamiast
 * zespołów i „Weź następną”. `?filtr=`, `?etykiety=help,exit`,
 * `?widok=lista|opieka`, `?karta=<id>` (dzwonki, linki).
 */
export function QueueBoard({ careStatusBoard = null }: QueueBoardProps) {
  const params = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const { showToast } = useToast();
  const query = useBoBoard();
  const sync = useBoSync();
  const takeNext = useTakeNext();
  const commands = useCardCommands();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const board = query.data;

  const write = (change: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(window.location.search);
    change(next);
    const qs = next.toString();
    replaceUrl(
      qs ? `${window.location.pathname}?${qs}` : window.location.pathname,
    );
  };

  const picked = useMemo(
    () => new Set((params?.get("etykiety") ?? "").split(",").filter(Boolean)),
    [params],
  );

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
    return (
      <p className="p-4 text-sm text-muted-foreground">Ładowanie spraw…</p>
    );
  }

  const rawFilter = params?.get("filtr");
  const filter: BoFilter =
    rawFilter && rawFilter in FILTER_LABELS ? (rawFilter as BoFilter) : "all";
  const rawView = params?.get("widok");
  const view: View =
    rawView === "lista"
      ? "lista"
      : rawView === "opieka" && careStatusBoard
        ? "opieka"
        : "tablica";
  const list = view === "lista";
  const views: [View, string][] = [
    ["tablica", "Tablica"],
    ["lista", "Lista"],
    ...(careStatusBoard
      ? ([["opieka", "Tablica Opieki"]] as [View, string][])
      : []),
  ];
  const cardParam = Number(params?.get("karta"));
  const openId =
    Number.isInteger(cardParam) && cardParam > 0 ? cardParam : null;
  const filters: BoFilter[] = board.me.is_lead
    ? [...FILTERS, "escalated"]
    : FILTERS;
  const byFilter = board.cards.filter(
    (card) =>
      matchesFilter(card, filter, board.me.user_id, board.today) &&
      matchesSearch(card, search),
  );
  const shown = byFilter.filter((card) => matchesLabels(card, picked));
  const counts = labelCounts(byFilter);
  const filterCount = (id: BoFilter) =>
    board.cards.filter((card) =>
      matchesFilter(card, id, board.me.user_id, board.today),
    ).length;
  const onOpen = (card: BoCard) =>
    write((next) => next.set("karta", String(card.id)));
  const toggleLabel = (lane: string) =>
    write((next) => {
      const set = new Set(picked);
      if (set.has(lane)) set.delete(lane);
      else set.add(lane);
      if (set.size) next.set("etykiety", [...set].join(","));
      else next.delete("etykiety");
    });
  const overdueFree = board.cards.filter(
    (card) => card.assignee == null && isOverdue(card, board.today),
  ).length;

  const grabNext = async () => {
    try {
      const card = await takeNext.mutateAsync();
      showToast(`Twoja sprawa: ${card.person || card.title}`, "success");
      write((next) => next.set("karta", String(card.id)));
    } catch (error) {
      if (statusOf(error) === 404) {
        showToast("Nie ma teraz nic do wzięcia.", "info");
      } else {
        showToast(
          apiErrorMessage(
            error,
            conflictCode(error) === "limit"
              ? "Masz już 5 spraw w toku."
              : "Nie udało się wziąć sprawy.",
          ),
          "error",
        );
      }
    }
  };

  return (
    <div className="space-y-2.5" data-help="hr.care.queue">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="group"
          aria-label="Filtr spraw"
        >
          {/* Kanban Opieki ma własne filtry i szukanie; dwa paski obok siebie mylą. */}
          {view === "opieka"
            ? null
            : filters.map((id) => (
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
                    "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs",
                    filter === id
                      ? "border-primary bg-primary/10 font-medium text-primary"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {FILTER_LABELS[id]}
                  <span className="text-[11px] tabular-nums opacity-80">
                    {filterCount(id)}
                  </span>
                </button>
              ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className={cn("relative", view === "opieka" && "hidden")}>
            <Search
              aria-hidden
              className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              aria-label="Szukaj spraw"
              placeholder="Szukaj: osoba, klient…"
              className="h-8 w-48 pl-7 text-xs"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <span
            className="inline-flex overflow-hidden rounded-md border border-border text-xs"
            role="group"
            aria-label="Widok"
          >
            {views.map(([id, label]) => (
              <button
                key={id}
                type="button"
                aria-pressed={view === id}
                onClick={() =>
                  write((next) => {
                    if (id === "tablica") next.delete("widok");
                    else next.set("widok", id);
                  })
                }
                className={cn(
                  "px-2.5 py-1.5",
                  view === id
                    ? "bg-primary font-medium text-primary-foreground"
                    : "text-muted-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </span>
          {board.me.cases_handler ? (
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1 px-2.5 text-xs"
              onClick={() => setCreating(true)}
            >
              <Plus aria-hidden className="size-3.5" /> Nowa sprawa
            </Button>
          ) : null}
          <Button
            size="sm"
            className="h-8 gap-1 px-3 text-xs"
            disabled={takeNext.isPending}
            onClick={grabNext}
          >
            <Hand aria-hidden className="size-3.5" /> Weź następną
          </Button>
          {board.me.is_lead ? (
            <Button
              size="sm"
              variant="ghost"
              className="h-8 gap-1 px-2 text-xs"
              disabled={sync.isPending}
              onClick={() =>
                sync.mutate(undefined, {
                  onError: (error) =>
                    showToast(
                      apiErrorMessage(error, "Nie udało się odświeżyć spraw."),
                      "error",
                    ),
                })
              }
            >
              <RefreshCw aria-hidden className="size-3" /> Odśwież
            </Button>
          ) : null}
        </div>
      </div>

      {view === "opieka" ? null : (
        <>
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label="Etykiety"
          >
            <span className="text-[11px] text-muted-foreground">Etykiety:</span>
            {board.labels
              .filter(
                (label) =>
                  (counts.get(label.id) ?? 0) > 0 || picked.has(label.id),
              )
              .sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0))
              .map((label) => (
                <button
                  key={label.id}
                  type="button"
                  aria-pressed={picked.has(label.id)}
                  title={label.description}
                  onClick={() => toggleLabel(label.id)}
                  className={cn(
                    "inline-flex h-6 items-center gap-1 rounded-full border px-2 text-[11px]",
                    picked.has(label.id)
                      ? "border-primary bg-primary/10 font-medium text-primary"
                      : "border-border bg-card text-foreground hover:border-primary/40",
                  )}
                >
                  <FamilyDot family={label.family} />
                  {label.label}
                  <span className="tabular-nums text-muted-foreground">
                    {counts.get(label.id) ?? 0}
                  </span>
                </button>
              ))}
            {picked.size ? (
              <button
                type="button"
                className="text-[11px] text-primary hover:underline"
                onClick={() => write((next) => next.delete("etykiety"))}
              >
                Wszystkie etykiety
              </button>
            ) : null}
          </div>

          <p className="text-[11.5px] text-muted-foreground">
            Bez osoby:{" "}
            <span className="font-medium text-foreground">
              {board.counts.unassigned}
            </span>{" "}
            · po terminie i bez osoby:{" "}
            <span className="font-medium text-destructive">{overdueFree}</span>
            {board.me.is_lead ? (
              <>
                {" "}
                · u kierownika po dniu roboczym:{" "}
                <span className="font-medium text-foreground">
                  {board.counts.escalated}
                </span>
              </>
            ) : null}{" "}
            · moje w toku:{" "}
            <span
              className={cn(
                "font-medium",
                board.me.in_progress > board.me.limit
                  ? "text-destructive"
                  : "text-foreground",
              )}
            >
              {board.me.in_progress} z {board.me.limit}
            </span>
          </p>
        </>
      )}

      {board.me.is_lead && view !== "opieka" ? (
        <TriageStrip board={board} />
      ) : null}

      {view === "opieka" ? (
        careStatusBoard
      ) : list ? (
        <ListView
          cards={shown}
          board={board}
          onOpen={onOpen}
          commands={commands}
        />
      ) : (
        <div className="grid grid-cols-4 gap-2.5">
          {COLUMNS.map((column) => (
            <Column
              key={column}
              column={column}
              cards={shown.filter((card) => columnOf(card) === column)}
              board={board}
              commands={commands}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}

      {!openId ? commands.dialogs : null}
      {openId ? (
        <CardPanel
          cardId={openId}
          board={board}
          commands={commands}
          onClose={() => write((next) => next.delete("karta"))}
          onOpenCard={(id) => write((next) => next.set("karta", String(id)))}
        />
      ) : null}
      {creating ? (
        <NewCaseDialog board={board} onClose={() => setCreating(false)} />
      ) : null}
    </div>
  );
}
