"use client";

/**
 * „Kto wyśle do Cpro?" — okno przy oznaczeniu „Gotowy do Cpro" (Nordea).
 *
 * Za każdym razem wysyła ktoś inny (decyzja Artura 22.09.2026), więc osobę
 * typuje ten, kto oznacza gotowość. Wytypowana osoba dostaje dzwonek i ma
 * zadanie w panelu „Czeka na Ciebie" na pulpicie. Domyślnie: ja.
 */

import { useEffect, useState } from "react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { assigneeLabel, useCproAssigneeOptions } from "@/lib/api/boardTasks";

interface CproAssigneeDialogProps {
  open: boolean;
  candidateName: string;
  /** Kogo zaznaczyć na starcie — zwykle zalogowana osoba. */
  defaultAssigneeId: number | null;
  onConfirm: (assigneeId: number) => void;
  onCancel: () => void;
}

export function CproAssigneeDialog({
  open,
  candidateName,
  defaultAssigneeId,
  onConfirm,
  onCancel,
}: CproAssigneeDialogProps) {
  const options = useCproAssigneeOptions(open);
  const [assigneeId, setAssigneeId] = useState<number | null>(defaultAssigneeId);

  useEffect(() => {
    if (open) setAssigneeId(defaultAssigneeId);
  }, [open, defaultAssigneeId]);

  const list = options.data ?? [];
  const known = assigneeId != null && list.some((o) => o.id === assigneeId);

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onCancel())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Gotowy do Cpro</DialogTitle>
          <DialogDescription>
            Kto wyśle <span className="font-semibold">{candidateName}</span> do Cpro? Ta
            osoba dostanie powiadomienie i zadanie na swoim pulpicie.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <label htmlFor="cpro-assignee" className="mb-1.5 block text-sm font-medium">
            Wysyła
          </label>
          <select
            id="cpro-assignee"
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={assigneeId ?? ""}
            disabled={options.isLoading}
            onChange={(e) => setAssigneeId(e.target.value ? Number(e.target.value) : null)}
          >
            {!known && <option value="">{options.isLoading ? "Wczytuję zespół…" : "Wybierz osobę"}</option>}
            {list.map((o) => (
              <option key={o.id} value={o.id}>
                {assigneeLabel(o)}
                {o.id === defaultAssigneeId ? " (ja)" : ""}
              </option>
            ))}
          </select>
          {options.isError && (
            <p className="mt-2 text-xs text-destructive">
              Nie udało się wczytać zespołu. Zamknij okno i spróbuj ponownie.
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onCancel}>
            Anuluj
          </Button>
          <Button onClick={() => assigneeId != null && onConfirm(assigneeId)} disabled={!known}>
            Oznacz „Gotowy do Cpro”
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
