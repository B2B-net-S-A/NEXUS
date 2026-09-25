"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { laterDateError, nextBusinessDay } from "@/lib/trainee-call";

interface LaterDateDialogProps {
  open: boolean;
  personName: string;
  /** Dzień listy (RRRR-MM-DD) — od niego liczymy „po dziś”. */
  listDate: string;
  /** Ostatni dzień programu (RRRR-MM-DD) — później lista już nie powstanie. */
  programEnd?: string | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (date: string) => void;
}

/** „Prosi o telefon innego dnia” — wybór dnia roboczego po dziś. */
export function LaterDateDialog({
  open,
  personName,
  listDate,
  programEnd = null,
  busy,
  onCancel,
  onConfirm,
}: LaterDateDialogProps) {
  const [date, setDate] = useState(() => nextBusinessDay(listDate));
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (open) {
      setDate(nextBusinessDay(listDate));
      setTouched(false);
    }
  }, [open, listDate]);
  const error = laterDateError(date, listDate, programEnd);

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
      title="Telefon innego dnia"
      description={`${personName} prosi o telefon później. Pozycja zamknie się na dziś i wróci na listę wybranego dnia.`}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Anuluj
          </Button>
          <Button
            onClick={() => {
              setTouched(true);
              if (!error) onConfirm(date);
            }}
            loading={busy}
            disabled={busy}
          >
            Przenieś telefon
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-2">
        <label htmlFor="trainee-later-date" className="text-sm font-medium text-foreground">
          Dzień telefonu
        </label>
        <input
          id="trainee-later-date"
          type="date"
          min={nextBusinessDay(listDate)}
          max={programEnd ?? undefined}
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
            setTouched(true);
          }}
          aria-invalid={touched && error ? true : undefined}
          aria-describedby="trainee-later-hint"
          className="h-11 rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:border-primary focus:outline-hidden"
        />
        <p
          id="trainee-later-hint"
          role={touched && error ? "alert" : undefined}
          className={touched && error ? "text-xs font-medium text-destructive" : "text-xs text-muted-foreground"}
        >
          {touched && error ? error : "Tylko dni robocze — soboty, niedziele i święta odpadają."}
        </p>
      </div>
    </AppModal>
  );
}
