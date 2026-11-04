"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
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
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateP0, requestJobP0, setJobP0 } from "@/lib/api/jobP0";
import {
  P0_DURATION_OPTIONS,
  P0_HINT,
  P0_REQUEST_HINT,
  P0_REASON_MAX,
  validateP0Reason,
  type P0Duration,
} from "@/lib/job-p0";

export interface SetP0DialogProps {
  jobId: number;
  jobTitle?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Obecny powód, gdy P0 już trwa — ponowne ustawienie go nadpisuje. */
  initialReason?: string | null;
  /**
   * `request` — Delivery Lead rekrutacji prosi o P0 (28.10.2026), Head of
   * Recruitment zatwierdza. `set` — HoR i administrator ustawiają od razu.
   */
  mode?: "set" | "request";
}

/**
 * Okno „Ustaw P0” (27.10.2026) — z menu priorytetu w nagłówku i z przycisku
 * „P0 na 24 h” w Daily. Powód obowiązkowy, bo widzą go wszyscy. W trybie
 * `request` to samo okno wysyła prośbę Delivery Leada (28.10.2026).
 */
export function SetP0Dialog({
  jobId,
  jobTitle,
  open,
  onOpenChange,
  initialReason,
  mode = "set",
}: SetP0DialogProps) {
  const asking = mode === "request";
  const queryClient = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState(initialReason ?? "");
  const [duration, setDuration] = useState<P0Duration>("24h");
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const { reason: clean, error } = validateP0Reason(reason);

  const submit = async () => {
    setTouched(true);
    if (error) return;
    setSaving(true);
    try {
      if (asking) {
        await requestJobP0(jobId, { reason: clean, duration });
        invalidateP0(queryClient, jobId);
        toast.showSuccess("Prośba o P0 wysłana do Head of Recruitment.");
      } else {
        const state = await setJobP0(jobId, { reason: clean, duration });
        invalidateP0(queryClient, jobId);
        toast.showSuccess(
          state.notified > 0
            ? `P0 ustawione. Zespół rekrutacji dostał powiadomienie i mail (${state.notified}).`
            : "P0 ustawione.",
        );
      }
      onOpenChange(false);
    } catch (err) {
      toast.showError(
        apiErrorMessage(err, asking ? "Nie udało się wysłać prośby o P0." : "Nie udało się ustawić P0."),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setReason(initialReason ?? "");
          setDuration("24h");
          setTouched(false);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent size="sm" aria-describedby="set-p0-desc" data-testid="set-p0-dialog">
        <DialogHeader>
          <DialogTitle>{asking ? "Poproś o P0 — ultrapilne" : "Ustaw P0 — ultrapilne"}</DialogTitle>
          <DialogDescription id="set-p0-desc">
            {jobTitle ? `${jobTitle}. ` : ""}
            {asking ? P0_REQUEST_HINT : P0_HINT}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="p0-reason" className="text-sm font-medium">
              Po co P0 (widzą wszyscy)
            </label>
            <Textarea
              id="p0-reason"
              value={reason}
              maxLength={P0_REASON_MAX + 50}
              rows={3}
              placeholder="np. Klient chce 2 CV do jutra 12:00 — wszyscy na tę rekrutację"
              onChange={(event) => setReason(event.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={touched && error ? true : undefined}
              aria-describedby={touched && error ? "p0-reason-error" : undefined}
            />
            {touched && error ? (
              <p id="p0-reason-error" className="text-xs text-destructive">
                {error}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <span id="p0-duration-label" className="text-sm font-medium">
              Na jak długo
            </span>
            <SegmentedRadio<P0Duration>
              labelledBy="p0-duration-label"
              value={duration}
              onChange={setDuration}
              options={P0_DURATION_OPTIONS}
              size="sm"
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            Anuluj
          </Button>
          <Button variant="destructive" onClick={() => void submit()} loading={saving}>
            {asking ? "Wyślij prośbę" : "Ustaw P0"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
