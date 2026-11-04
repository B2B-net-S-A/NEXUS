"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useMoveCard, type BoBoard, type BoCard, type BoTeamId } from "@/lib/api/back-office";

import { MoveDialog } from "./MoveDialog";

/** „Do rozdzielenia”: reguły i AI nie były pewne, więc decyduje kierownik. */
export function TriageStrip({ board }: { board: BoBoard }) {
  const { showToast } = useToast();
  const move = useMoveCard();
  const [moving, setMoving] = useState<BoCard | null>(null);
  if (board.triage.length === 0) return null;

  const accept = async (card: BoCard) => {
    if (!card.triage_guess) return;
    await run(card, card.triage_guess.team, card.triage_guess.lane);
  };
  const run = async (card: BoCard, team: BoTeamId, lane: string) => {
    try {
      await move.mutateAsync({ id: card.id, team, lane });
      setMoving(null);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się rozdzielić sprawy."), "error");
    }
  };
  const label = (card: BoCard) => {
    const guess = card.triage_guess;
    if (!guess) return "bez propozycji";
    const team = board.teams.find((row) => row.id === guess.team);
    const lane = team?.lanes.find((row) => row.id === guess.lane);
    return `propozycja: ${team?.label ?? guess.team} · ${lane?.label ?? guess.lane}`;
  };

  return (
    <section className="rounded-xl border bg-card p-3" aria-label="Do rozdzielenia">
      <h3 className="pb-1.5 text-sm font-semibold">
        Do rozdzielenia <span className="font-normal text-muted-foreground">· {board.triage.length}</span>
      </h3>
      <ul className="divide-y text-sm">
        {board.triage.map((card) => (
          <li key={card.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
            <span className="min-w-0">
              <span className="block truncate font-medium">{card.title}</span>
              <span className="block truncate text-xs text-muted-foreground">{label(card)}</span>
            </span>
            <span className="inline-flex gap-1">
              {card.triage_guess ? (
                <Button size="sm" className="h-7 px-2.5 text-xs" disabled={move.isPending} onClick={() => accept(card)}>
                  Przyjmij
                </Button>
              ) : null}
              <Button size="sm" variant="outline" className="h-7 px-2.5 text-xs" onClick={() => setMoving(card)}>
                Przenieś…
              </Button>
            </span>
          </li>
        ))}
      </ul>
      {moving ? (
        <MoveDialog teams={board.teams} current={moving} onCancel={() => setMoving(null)} onMove={(team, lane) => run(moving, team, lane)} />
      ) : null}
    </section>
  );
}
