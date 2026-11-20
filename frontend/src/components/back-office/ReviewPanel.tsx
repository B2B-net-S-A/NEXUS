"use client";

import { useMemo, useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBoBoard,
  useBulkReview,
  useFinishReview,
  useReviewCard,
  type BoBoard,
  type BoCard,
  type BoTeamId,
} from "@/lib/api/back-office";

import { dueTone, formatDay } from "./board-model";
import { LabelChip, labelText } from "./CardTile";
import { MoveDialog } from "./MoveDialog";

/** Sprawa starsza niż tyle dni może zostać zamknięta hurtem (wariant A, 19.11.2026). */
const OLD_DAYS = 60;
const BULK_NOTE = `Przegląd przed startem: starsza niż ${OLD_DAYS} dni`;

function ageDays(card: BoCard, today: string): number {
  return Math.floor(
    (new Date(`${today}T00:00:00`).getTime() - new Date(card.created_at).getTime()) / 86_400_000,
  );
}

/**
 * Przegląd przed startem: każda stara sprawa dostaje jedną decyzję kierownika,
 * a nic nie znika bez niej. Grupy po etykiecie; sprawy starsze niż 60 dni da się
 * zamknąć hurtem, każda z powodem w historii. Po „Zakończ przegląd” nowe sprawy
 * tu nie trafiają.
 */
export function ReviewPanel() {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useBoBoard();
  const review = useReviewCard();
  const finish = useFinishReview();
  const bulk = useBulkReview();
  const [moving, setMoving] = useState<BoCard | null>(null);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const board: BoBoard | undefined = query.data;
  const groups = useMemo(() => {
    const out = new Map<string, BoCard[]>();
    for (const card of board?.cards ?? []) {
      if (!card.needs_review) continue;
      out.set(card.lane, [...(out.get(card.lane) ?? []), card]);
    }
    return [...out.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [board]);

  if (query.isError) {
    return <p className="text-sm text-destructive">{apiErrorMessage(query.error, "Nie udało się wczytać przeglądu.")}</p>;
  }
  if (!board) return <p className="text-sm text-muted-foreground">Ładowanie…</p>;

  const rows = board.cards.filter((card) => card.needs_review && (openGroup == null || card.lane === openGroup));
  const total = groups.reduce((sum, [, cards]) => sum + cards.length, 0);
  const closeOld = async (cards: BoCard[]) => {
    const old = cards.filter((card) => ageDays(card, board.today) > OLD_DAYS);
    const ok = await askConfirm({
      title: `Zamknąć ${old.length} spraw starszych niż ${OLD_DAYS} dni?`,
      description: `Każda dostanie w historii powód „${BULK_NOTE}”.`,
      confirmLabel: "Zamknij",
      cancelLabel: "Anuluj",
    });
    if (!ok) return;
    try {
      const result = await bulk.mutateAsync({ card_ids: old.map((card) => card.id), decision: "close", note: BULK_NOTE });
      showToast(`Zamknięte: ${result.done}${result.skipped ? `, pominięte: ${result.skipped}` : ""}`, "success");
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zamknąć spraw."), "error");
    }
  };
  const decide = async (card: BoCard, decision: "current" | "close", note?: string) => {
    try {
      await review.mutateAsync({ id: card.id, decision, note });
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zapisać decyzji."), "error");
    }
  };
  const laneLabel = (card: BoCard) => labelText(board, card.lane);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {total} otwartych spraw do przejrzenia. Dla każdej jedna decyzja, a nic nie znika bez niej.
        </p>
        <Button
          size="sm"
          variant="outline"
          disabled={finish.isPending}
          onClick={async () => {
            const ok = await askConfirm({
              title: "Zakończyć przegląd?",
              description: "Nowe sprawy nie będą już trafiać na tę listę.",
              confirmLabel: "Zakończ przegląd",
              cancelLabel: "Anuluj",
            });
            if (ok) {
              finish.mutate(undefined, {
                onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zakończyć przeglądu."), "error"),
              });
            }
          }}
        >
          Zakończ przegląd
        </Button>
      </div>
      {groups.length > 0 ? (
        <div className="overflow-hidden rounded-xl border bg-card">
          <table className="w-full text-sm" aria-label="Przegląd po etykietach">
            <thead className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b">
                <th className="px-4 py-2 font-medium">Etykieta</th>
                <th className="py-2 font-medium">Spraw</th>
                <th className="py-2 font-medium">Starsze niż {OLD_DAYS} dni</th>
                <th className="py-2 font-medium">Najstarsza</th>
                <th className="px-4 py-2 font-medium">Decyzja dla grupy</th>
              </tr>
            </thead>
            <tbody>
              {groups.map(([lane, cards]) => {
                const old = cards.filter((card) => ageDays(card, board.today) > OLD_DAYS).length;
                const oldest = [...cards].sort((a, b) => a.created_at.localeCompare(b.created_at))[0];
                return (
                  <tr key={lane} className={openGroup === lane ? "border-b bg-primary/5" : "border-b last:border-0"}>
                    <td className="px-4 py-2">
                      <LabelChip board={board} card={cards[0]} />
                    </td>
                    <td className="py-2 tabular-nums">{cards.length}</td>
                    <td className="py-2 tabular-nums">{old}</td>
                    <td className="max-w-[300px] py-2">
                      <span className="block truncate">{oldest?.person || oldest?.title}</span>
                      <span className="block text-xs text-muted-foreground">od {formatDay(oldest?.created_at ?? null)}</span>
                    </td>
                    <td className="px-4 py-2">
                      <span className="inline-flex flex-wrap gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 px-2 text-xs"
                          aria-pressed={openGroup === lane}
                          onClick={() => setOpenGroup(openGroup === lane ? null : lane)}
                        >
                          {openGroup === lane ? "Pokaż wszystkie" : "Przejrzyj po kolei"}
                        </Button>
                        {old > 0 ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={bulk.isPending}
                            onClick={() => closeOld(cards)}
                          >
                            Zamknij starsze ({old})
                          </Button>
                        ) : null}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed bg-card p-3 text-sm text-muted-foreground">
          Wszystkie sprawy mają decyzję.
        </p>
      ) : (
        <div className="max-h-[calc(100dvh-380px)] overflow-y-auto rounded-xl border bg-card">
          <table className="w-full text-sm" aria-label="Sprawy do przejrzenia">
            <thead className="sticky top-0 bg-card text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b">
                <th className="px-4 py-2 font-medium">Termin</th>
                <th className="py-2 font-medium">Sprawa</th>
                <th className="py-2 font-medium">Trafi do</th>
                <th className="py-2 font-medium">Kto</th>
                <th className="px-4 py-2 font-medium">Decyzja</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((card) => (
                <tr key={card.id} className="border-b last:border-0">
                  <td className="px-4 py-1.5">
                    <Badge variant={dueTone(card.due_on, board.today)} size="sm">
                      {formatDay(card.due_on)}
                    </Badge>
                  </td>
                  <td className="max-w-[340px] py-1.5">
                    <span className="block truncate font-medium">{card.person || card.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {[card.person ? card.title : null, card.client].filter(Boolean).join(" · ")}
                    </span>
                  </td>
                  <td className="py-1.5 text-xs">{laneLabel(card)}</td>
                  <td className="py-1.5 text-xs text-muted-foreground">{card.assignee?.name ?? "bez osoby"}</td>
                  <td className="px-4 py-1.5">
                    <span className="inline-flex gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={review.isPending}
                        onClick={() => decide(card, "current")}
                      >
                        Aktualna
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={review.isPending}
                        onClick={async () => {
                          const ok = await askConfirm({
                            title: "Zamknąć tę sprawę?",
                            description: card.title,
                            confirmLabel: "Zamknij",
                            cancelLabel: "Anuluj",
                          });
                          if (ok) await decide(card, "close");
                        }}
                      >
                        Zamknij
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        onClick={() => setMoving(card)}
                      >
                        Przenieś…
                      </Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {confirmDialog}
      {moving ? (
        <MoveDialog
          teams={board.teams}
          current={moving}
          onCancel={() => setMoving(null)}
          onMove={async (team: BoTeamId, lane: string) => {
            try {
              await review.mutateAsync({ id: moving.id, decision: "move", team, lane });
              setMoving(null);
            } catch (error) {
              showToast(apiErrorMessage(error, "Nie udało się przenieść sprawy."), "error");
            }
          }}
        />
      ) : null}
    </div>
  );
}
