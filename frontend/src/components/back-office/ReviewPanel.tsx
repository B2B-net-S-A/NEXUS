"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBoBoard,
  useFinishReview,
  useReviewCard,
  type BoBoard,
  type BoCard,
  type BoTeamId,
} from "@/lib/api/back-office";

import { dueTone, formatDay } from "./board-model";
import { MoveDialog } from "./MoveDialog";

/**
 * Przegląd przed startem: każda stara sprawa dostaje jedną decyzję kierownika,
 * a nic nie znika bez niej. Po „Zakończ przegląd” nowe sprawy tu nie trafiają.
 */
export function ReviewPanel() {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useBoBoard();
  const review = useReviewCard();
  const finish = useFinishReview();
  const [moving, setMoving] = useState<BoCard | null>(null);
  const board: BoBoard | undefined = query.data;

  if (query.isError) {
    return <p className="text-sm text-destructive">{apiErrorMessage(query.error, "Nie udało się wczytać przeglądu.")}</p>;
  }
  if (!board) return <p className="text-sm text-muted-foreground">Ładowanie…</p>;

  const rows = board.cards.filter((card) => card.needs_review);
  const decide = async (card: BoCard, decision: "current" | "close", note?: string) => {
    try {
      await review.mutateAsync({ id: card.id, decision, note });
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zapisać decyzji."), "error");
    }
  };
  const laneLabel = (card: BoCard) =>
    board.teams.flatMap((team) => team.lanes).find((lane) => lane.id === card.lane)?.label ?? card.lane;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {rows.length} otwartych spraw do przejrzenia. Dla każdej jedna decyzja, a nic nie znika bez niej.
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
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed bg-card p-3 text-sm text-muted-foreground">
          Wszystkie sprawy mają decyzję.
        </p>
      ) : (
        <div className="max-h-[calc(100dvh-280px)] overflow-y-auto rounded-xl border bg-card">
          <table className="w-full text-sm">
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
