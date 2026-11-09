"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import type { BoCard, BoTeam, BoTeamId } from "@/lib/api/back-office";

interface MoveDialogProps {
  teams: BoTeam[];
  current: BoCard;
  onCancel: () => void;
  onMove: (team: BoTeamId, lane: string) => void;
}

const SELECT = "h-9 w-full rounded-md border bg-card px-2 text-sm";

/** „Przenieś…”: zespół i kolumna. Karta zostaje tam, gdzie ją postawił kierownik. */
export function MoveDialog({ teams, current, onCancel, onMove }: MoveDialogProps) {
  const [team, setTeam] = useState<BoTeamId>(current.team);
  const lanes = teams.find((row) => row.id === team)?.lanes ?? [];
  const [lane, setLane] = useState(current.lane);
  const laneValid = lanes.some((row) => row.id === lane);
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      title="Przenieś do kolumny"
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>
            Anuluj
          </Button>
          <Button disabled={!laneValid} onClick={() => onMove(team, lane)}>
            Przenieś
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Zespół">
          <select className={SELECT} value={team} onChange={(event) => setTeam(event.target.value as BoTeamId)}>
            {teams.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Kolumna">
          <select className={SELECT} value={laneValid ? lane : ""} onChange={(event) => setLane(event.target.value)}>
            {laneValid ? null : <option value="">wybierz…</option>}
            {lanes.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label}
              </option>
            ))}
          </select>
        </FormField>
      </div>
    </AppModal>
  );
}
