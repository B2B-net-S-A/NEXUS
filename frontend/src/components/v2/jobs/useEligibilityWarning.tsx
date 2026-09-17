"use client";

/**
 * Okno „Przenieś mimo to" dla warsztatów kroków 06–07 (17.09.2026).
 *
 * Czarna lista, NDA, konkurent i weto hiring managera nie blokują ruchu:
 * `POST /api/pipeline/move` odpowiada raz 409 `ELIGIBILITY_WARNING`, a ekran
 * pyta użytkownika i powtarza TEN SAM ruch z `acknowledge_eligibility: true`.
 * Tablica i warsztat screeningu mają to okno wbudowane; ten hook daje ten sam
 * dialog (te same teksty) ekranom, które wysyłają ruch z własnej mutacji —
 * bez niego ostrzeżenie kończyłoby się tam toastem błędu, czyli znów bramką.
 */

import { useCallback, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  eligibilityWarningReason,
  isEligibilityWarning,
} from "@/lib/pipeline-eligibility-warning";

interface WarningState {
  reason: string;
  retry: () => void;
  onCancel?: () => void;
}

export interface EligibilityWarningControls {
  /**
   * `true` = błąd był ostrzeżeniem i okno zostało otwarte (wołający kończy
   * obsługę błędu); `false` = to inny błąd, obsłuż go jak dotąd.
   */
  intercept: (error: unknown, retry: () => void, onCancel?: () => void) => boolean;
  dialog: ReactNode;
}

export function useEligibilityWarning(): EligibilityWarningControls {
  const [warning, setWarning] = useState<WarningState | null>(null);

  const intercept = useCallback(
    (error: unknown, retry: () => void, onCancel?: () => void) => {
      if (!isEligibilityWarning(error)) return false;
      setWarning({
        reason: eligibilityWarningReason(error) ?? "Serwer ostrzega przed tym ruchem.",
        retry,
        onCancel,
      });
      return true;
    },
    [],
  );

  const cancel = () => {
    const onCancel = warning?.onCancel;
    setWarning(null);
    onCancel?.();
  };

  const dialog = warning ? (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) cancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ostrzeżenie przed przeniesieniem</DialogTitle>
          <DialogDescription>{warning.reason}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={cancel}>
            Anuluj
          </Button>
          <Button
            onClick={() => {
              const retry = warning.retry;
              setWarning(null);
              retry();
            }}
          >
            Przenieś mimo to
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ) : null;

  return { intercept, dialog };
}
