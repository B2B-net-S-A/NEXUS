"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { CareBoardCard } from "@/lib/api/care-board";

import { careTileTitle, scheduledIso, validateBoardState } from "./work-board-model";

export interface BoardStateValue {
  scheduled_at?: string;
  retry_on?: string;
  note?: string | null;
}

/**
 * Małe okienko przy ruchu karty opieki: „W toku” rozmowy albo opinii pyta
 * o umówiony dzień i godzinę, „Czeka na kogoś” — o dzień ponownej próby
 * (po nim karta sama wraca do „Nowa”). Notatka ≤ 500 znaków, bez danych
 * o zdrowiu i bez stawek.
 */
export function BoardStateDialog({
  card,
  ask,
  today,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  card: CareBoardCard;
  ask: "schedule" | "retry";
  today: string;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (value: BoardStateValue) => void;
}) {
  const [day, setDay] = useState(ask === "schedule" ? today : "");
  const [time, setTime] = useState("10:00");
  const [note, setNote] = useState("");
  const [invalid, setInvalid] = useState<string | null>(null);

  const submit = () => {
    const problem = validateBoardState(ask, { day, time }, today);
    setInvalid(problem);
    if (problem) return;
    const trimmed = note.trim() || null;
    if (ask === "schedule") onSubmit({ scheduled_at: scheduledIso(day, time) ?? undefined, note: trimmed });
    else onSubmit({ retry_on: day, note: trimmed });
  };

  const message = invalid ?? error;
  const name = careTileTitle(card);
  const withManager = card.kind === "feedback" || card.kind === "demand";
  const title =
    ask === "schedule"
      ? withManager
        ? "Kiedy rozmowa z menedżerem?"
        : "Kiedy rozmowa?"
      : card.kind === "feedback"
        ? "Do kiedy czekać na menedżera?"
        : "Kiedy spróbować ponownie?";
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onCancel())}
      title={title}
      description={
        ask === "schedule"
          ? `${name} — karta przejdzie do „W toku” z umówionym terminem.`
          : `${name} — karta czeka i wróci do „Nowa” w wybranym dniu.`
      }
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={pending}>
            {pending ? "Zapisywanie…" : ask === "schedule" ? "Umów" : "Odłóż"}
          </Button>
        </>
      }
    >
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="grid grid-cols-2 gap-3">
          <FormField
            label={ask === "schedule" ? "Dzień" : card.kind === "feedback" ? "Czekamy do" : "Dzień ponownej próby"}
            htmlFor="board-state-day"
            required
            className={ask === "retry" ? "col-span-2" : undefined}
          >
            <Input
              id="board-state-day"
              type="date"
              value={day}
              onChange={(event) => setDay(event.target.value)}
            />
          </FormField>
          {ask === "schedule" ? (
            <FormField label="Godzina" htmlFor="board-state-time" required>
              <Input
                id="board-state-time"
                type="time"
                step={300}
                value={time}
                onChange={(event) => setTime(event.target.value)}
              />
            </FormField>
          ) : null}
        </div>
        <FormField
          label="Notatka (opcjonalnie)"
          htmlFor="board-state-note"
          description="Bez danych o zdrowiu i bez stawek."
        >
          <Textarea
            id="board-state-note"
            rows={2}
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </FormField>
        {message ? (
          <p role="alert" className="text-sm text-destructive">
            {message}
          </p>
        ) : null}
      </form>
    </AppModal>
  );
}
