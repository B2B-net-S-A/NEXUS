"use client";

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

import type { FileProblem } from "./payroll-model";

/**
 * Odmowa pliku z listą osób (deklaracja ZUS bez danych, nikogo do zgłoszenia,
 * PIT-11 bez gotowych osób) — w oknie, bo dymek gubi listę.
 */
export function FileProblemDialog({ problem, onClose }: { problem: FileProblem | null; onClose: () => void }) {
  return (
    <Dialog
      open={problem != null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="md">
        {problem ? (
          <>
            <DialogHeader>
              <DialogTitle className="text-lg">{problem.title}</DialogTitle>
              {problem.message ? <DialogDescription>{problem.message}</DialogDescription> : null}
            </DialogHeader>
            <DialogBody>
              {problem.items.length ? (
                <ul className="space-y-1.5 text-[13px]">
                  {problem.items.map((item) => (
                    <li key={item} className="flex items-start gap-2">
                      <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-warning" />
                      <span className="min-w-0 break-words">{item}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">Serwer nie podał listy osób.</p>
              )}
            </DialogBody>
            <DialogFooter>
              <Button size="sm" onClick={onClose}>
                Zamknij
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
