"use client";

/**
 * „Wyślij też do…” (Match, 22.10.2026) — z panelu osoby, gdy osoba jest już
 * wysłana w tej rekrutacji. Ta sama lista i ta sama wysyłka co sekcja
 * przeglądu DL-a; stawka podpowiada się z tej rekrutacji.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Send } from "lucide-react";

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
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { dlMatchApi } from "@/lib/dl-match-api";
import { RATE_UNIT_LABEL, type ClientRateUnit } from "@/lib/person-facts";

import { DlMatchSection, matchTargets, summarizeResults, useDlMatch } from "./DlMatchSection";

export interface DlMatchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string;
  jobId: number;
  jobLabel: string;
  /** Stawka do klienta w tej rekrutacji — podpowiedź w każdym wierszu. */
  defaultRate: string;
  /** Jednostka i waluta tej stawki — idą z każdą wysyłką (stawka dzienna
   * w A nie może trafić do B jako godzinowa). */
  rateUnit: ClientRateUnit;
  currency: string;
}

export function DlMatchDialog({
  open,
  onOpenChange,
  candidateId,
  candidateName,
  jobId,
  jobLabel,
  defaultRate,
  rateUnit,
  currency,
}: DlMatchDialogProps) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const match = useDlMatch(candidateId, jobId, open);
  const [busy, setBusy] = useState(false);
  const { targets, missingRate } = matchTargets(match.jobs, match.selection, {
    rate: defaultRate,
    unit: rateUnit,
    currency,
  });
  const unitText = RATE_UNIT_LABEL[rateUnit].replace("zł", currency === "PLN" ? "zł" : currency);

  const send = async () => {
    setBusy(true);
    try {
      const response = await dlMatchApi.send({ candidate_id: candidateId, from_job_id: jobId, targets });
      const summary = summarizeResults(response.results);
      if (summary.sent) showSuccess(`${candidateName} — ${summary.sent}`);
      if (summary.problems.length > 0) showError(summary.problems.join(" · "));
      void queryClient.invalidateQueries({ queryKey: ["dl-match", jobId, candidateId] });
      for (const r of response.results) {
        void queryClient.invalidateQueries({ queryKey: ["kanban", String(r.job_id)] });
        void queryClient.invalidateQueries({ queryKey: ["kanban", r.job_id] });
      }
      match.reset();
      onOpenChange(false);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać do pozostałych rekrutacji."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (!busy ? onOpenChange(next) : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Wyślij {candidateName} też do…</DialogTitle>
          <DialogDescription>
            Ta sama osoba i to samo CV co w „{jobLabel}”. Bez arkusza i pytań. Stawki w {unitText}, jak w tej rekrutacji.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <DlMatchSection model={match} fallbackRate={defaultRate} disabled={busy} />
        </DialogBody>
        <DialogFooter>
          {missingRate > 0 ? (
            <p className="mr-auto text-xs text-muted-foreground">Wpisz stawkę przy zaznaczonych rekrutacjach.</p>
          ) : null}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Anuluj
          </Button>
          <Button onClick={() => void send()} disabled={busy || targets.length === 0 || missingRate > 0}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" />}
            {targets.length > 0 ? `Wyślij do ${targets.length} rekrutacji` : "Zaznacz rekrutacje"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
