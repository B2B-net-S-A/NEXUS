"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { BoOutsideTeam } from "@/lib/api/back-office";
import { cn } from "@/lib/utils";

interface OutsideDialogProps {
  teams: { id: BoOutsideTeam; label: string }[];
  busy?: boolean;
  onCancel: () => void;
  onConfirm: (team: BoOutsideTeam, note: string) => void | Promise<void>;
}

/**
 * „Na zewnątrz” (decyzja Artura z 10.11.2026): gdy back office nie da rady,
 * sprawa czeka na inny dział. Osoba prowadząca zostaje przy sprawie.
 */
export function OutsideDialog({ teams, busy = false, onCancel, onConfirm }: OutsideDialogProps) {
  const [team, setTeam] = useState<BoOutsideTeam | null>(null);
  const [note, setNote] = useState("");
  const ready = team != null && note.trim().length > 0;
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      title="Przekaż na zewnątrz"
      description="Sprawa zostaje u Ciebie i stoi w kolumnie „Na zewnątrz”, dopóki dział nie odpowie."
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Anuluj
          </Button>
          <Button disabled={!ready || busy} onClick={() => team && onConfirm(team, note.trim())}>
            Przekaż
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="space-y-1">
          <span className="text-sm font-medium">Do kogo *</span>
          <div className="grid grid-cols-2 gap-1.5" role="radiogroup" aria-label="Dział">
            {teams.map((row) => (
              <button
                key={row.id}
                type="button"
                role="radio"
                aria-checked={team === row.id}
                onClick={() => setTeam(row.id)}
                className={cn(
                  "rounded-md border px-3 py-2 text-left text-sm",
                  team === row.id ? "border-primary bg-primary/10 font-medium text-primary" : "border-border hover:border-primary/40",
                )}
              >
                {row.label}
              </button>
            ))}
          </div>
        </div>
        <label className="block space-y-1" htmlFor="bo-outside-note">
          <span className="text-sm font-medium">O co prosisz *</span>
          <Textarea
            id="bo-outside-note"
            rows={2}
            maxLength={200}
            placeholder="np. Konto w systemie klienta dla nowej osoby"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
      </div>
    </AppModal>
  );
}
