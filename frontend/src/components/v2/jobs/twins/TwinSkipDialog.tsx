"use client";

/**
 * Odmowa 409 `TWIN_SCREENING_REQUIRED` (0614, 28.10.2026): osoba idzie też do
 * bliźniaka, a screeningu pod niego nie ma. Właściwa droga to screening razem
 * („Screening dla” w panelu osoby); wyjątek — pominięcie bliźniaka z powodem,
 * który zostaje w Historii zdarzeń.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { TwinScreeningRequired } from "@/lib/pipeline-move-core";

export interface TwinSkipDialogProps {
  refusal: TwinScreeningRequired;
  onSkip: (skips: Record<string, string>) => void;
  onClose: () => void;
  /** Panel osoby otwarty na screeningu — „Zrób screening razem”. */
  onOpenScreening?: () => void;
}

export function TwinSkipDialog({ refusal, onSkip, onClose, onOpenScreening }: TwinSkipDialogProps) {
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const ready = refusal.twins.every((t) => reasons[String(t.job_id)]);
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent size="md" aria-describedby="twin-skip-desc" data-testid="twin-skip-dialog">
        <DialogHeader>
          <DialogTitle>Ta osoba idzie też do bliźniaka</DialogTitle>
          <DialogDescription id="twin-skip-desc">
            Zweryfikuj ją w jednej rozmowie pod obie rekrutacje: w panelu osoby, „Screening dla”. Pomiń bliźniaka
            tylko z powodem — zostanie w Historii zdarzeń.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {refusal.twins.map((twin) => (
            <label key={twin.job_id} className="block space-y-1 text-sm">
              <span className="font-medium">
                {twin.reference_number ? <span className="mr-1.5 font-mono text-xs">{twin.reference_number}</span> : null}
                {twin.title}
              </span>
              <select
                aria-label={`Powód pominięcia — ${twin.title}`}
                className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
                value={reasons[String(twin.job_id)] ?? ""}
                onChange={(e) => setReasons((prev) => ({ ...prev, [String(twin.job_id)]: e.target.value }))}
              >
                <option value="">Wybierz powód pominięcia…</option>
                {Object.entries(refusal.skipReasons).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </DialogBody>
        <DialogFooter className="items-center">
          <Button variant="ghost" onClick={onClose} className="mr-auto">
            Zamknij
          </Button>
          {onOpenScreening ? (
            <Button variant="outline" onClick={onOpenScreening}>
              Zrób screening razem
            </Button>
          ) : null}
          <Button onClick={() => onSkip(reasons)} disabled={!ready} data-testid="twin-skip-submit">
            Pomiń bliźniaka i przekaż
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
