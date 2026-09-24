"use client";

/**
 * Akademia — okno „Dokumenty uczestnika”: umowa uczestnictwa, harmonogram
 * (załącznik nr 1), oświadczenie, regulamin i protokół przekazania Manuala
 * w jednym ZIP-ie. PESEL i adres trafiają WYŁĄCZNIE do pliku — NEXUS ich nie
 * zapisuje; puste pole = linia kropek do uzupełnienia ręcznie.
 */

import * as React from "react";

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
import { toIsoDate } from "@/lib/academy-flow";
import type { AcademyApplication, CohortDates, DocumentsBody } from "@/lib/api/academy";

export function AcademyDocumentsDialog({
  app,
  open,
  onOpenChange,
  cohort,
  defaultHandoverName,
  onDownload,
  onMarkSent,
}: {
  app: AcademyApplication;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  cohort: CohortDates | null | undefined;
  defaultHandoverName: string;
  onDownload: (app: AcademyApplication, body: DocumentsBody) => Promise<boolean>;
  onMarkSent?: () => void;
}) {
  const today = toIsoDate(new Date());
  const [signingDate, setSigningDate] = React.useState(today);
  const [start, setStart] = React.useState(cohort?.start ?? "");
  const [end, setEnd] = React.useState(cohort?.end ?? "");
  const [address, setAddress] = React.useState("");
  const [pesel, setPesel] = React.useState("");
  const [handover, setHandover] = React.useState(defaultHandoverName);
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const ids = {
    signing: React.useId(),
    start: React.useId(),
    end: React.useId(),
    address: React.useId(),
    pesel: React.useId(),
    handover: React.useId(),
  };
  const peselInvalid = pesel.trim() !== "" && !/^\d{11}$/.test(pesel.trim());
  const datesInvalid = start !== "" && end !== "" && end < start;
  const field = "rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground";
  const label = "flex flex-col gap-1 text-xs font-medium text-muted-foreground";

  const download = async () => {
    setBusy(true);
    try {
      const ok = await onDownload(app, {
        signing_date: signingDate || null,
        program_start: start || null,
        program_end: end || null,
        address: address.trim() || null,
        pesel: pesel.trim() || null,
        handover_name: handover.trim() || null,
        protocol_date: start || null,
      });
      if (ok) {
        setDone(true);
        // PESEL nie zostaje w pamięci formularza dłużej, niż to konieczne.
        setPesel("");
        setAddress("");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Dokumenty uczestnika — {app.full_name}</DialogTitle>
          <DialogDescription>
            Umowa uczestnictwa, harmonogram (zał. nr 1), oświadczenie, regulamin i protokół
            przekazania Manuala — jeden plik ZIP.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label htmlFor={ids.signing} className={label}>
              Data zawarcia umowy
              <input id={ids.signing} type="date" className={field} value={signingDate} onChange={(e) => setSigningDate(e.target.value)} />
            </label>
            <label htmlFor={ids.start} className={label}>
              Program od
              <input id={ids.start} type="date" className={field} value={start} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label htmlFor={ids.end} className={label}>
              Program do
              <input id={ids.end} type="date" className={field} value={end} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            Domyślnie 10 dni roboczych od pierwszego dnia roboczego miesiąca edycji (z polskimi
            świętami). Program trwa do 10 dni roboczych — tak mówi umowa.
          </p>
          {datesInvalid ? (
            <p role="alert" className="text-sm text-destructive">
              Koniec programu nie może być przed początkiem.
            </p>
          ) : null}
          <label htmlFor={ids.address} className={label}>
            Adres zamieszkania (opcjonalnie)
            <input id={ids.address} className={field} value={address} maxLength={300} onChange={(e) => setAddress(e.target.value)} autoComplete="off" />
          </label>
          <label htmlFor={ids.pesel} className={label}>
            PESEL (opcjonalnie)
            <input
              id={ids.pesel}
              className={field}
              value={pesel}
              inputMode="numeric"
              maxLength={11}
              autoComplete="off"
              aria-invalid={peselInvalid}
              onChange={(e) => setPesel(e.target.value.replace(/\D/g, ""))}
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Adresu i PESEL-u NEXUS nie zapisuje — trafiają tylko do pobranego pliku. Puste pole
            zostaje w umowie linią do wypełnienia ręcznie.
          </p>
          <label htmlFor={ids.handover} className={label}>
            Kto przekazuje Manual (protokół)
            <input id={ids.handover} className={field} value={handover} maxLength={200} onChange={(e) => setHandover(e.target.value)} />
          </label>
          {done ? (
            <p className="rounded-md bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
              Pobrano komplet. Gdy wyślesz go uczestnikowi, oznacz umowę jako wysłaną.
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          {done && onMarkSent && app.status === "task_passed" ? (
            <Button
              variant="outline"
              onClick={() => {
                onMarkSent();
                onOpenChange(false);
              }}
            >
              Oznacz: umowa wysłana
            </Button>
          ) : null}
          <Button disabled={busy || peselInvalid || datesInvalid} onClick={() => void download()}>
            {busy ? "Przygotowuję…" : "Pobierz komplet (ZIP)"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
