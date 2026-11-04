"use client";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { localTodayIso } from "@/lib/client-order-list";
import {
  defaultPlacementsRange,
  placementsRangeError,
  type PlacementsRange,
} from "@/lib/placements-export";

interface PlacementsExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  /** Pobiera plik; `true` = udało się i okno można zamknąć. */
  onExport: (range: PlacementsRange) => Promise<boolean>;
}

export function PlacementsExportDialog({
  open,
  onOpenChange,
  busy,
  onExport,
}: PlacementsExportDialogProps) {
  const [range, setRange] = useState<PlacementsRange>(() =>
    defaultPlacementsRange(localTodayIso()),
  );
  // Każde otwarcie zaczyna od bieżącego miesiąca — okno nie pamięta
  // okresu sprzed tygodnia.
  useEffect(() => {
    if (open) setRange(defaultPlacementsRange(localTodayIso()));
  }, [open]);

  const error = placementsRangeError(range);

  const submit = async () => {
    if (error || busy) return;
    if (await onExport(range)) onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>Placementy (.xlsx)</DialogTitle>
          <DialogDescription>
            Kontrakty ze startem w okresie, także zakończone. Kolumny w kolejności
            arkusza „Placementy”: stawki i marża z dnia startu, DL, rekruter,
            akceptacja, podpis i premia.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="placements-from">Start od</Label>
              <Input
                id="placements-from"
                type="date"
                value={range.from}
                onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="placements-to">Start do</Label>
              <Input
                id="placements-to"
                type="date"
                value={range.to}
                onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
              />
            </div>
          </div>
          {error && (
            <p role="alert" className="mt-2 text-sm text-destructive">
              {error}
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button
            variant="primary"
            disabled={Boolean(error) || busy}
            onClick={() => void submit()}
          >
            {busy ? "Pobieram…" : "Pobierz"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
