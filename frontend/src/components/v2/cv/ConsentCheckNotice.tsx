"use client";

/**
 * Zrzut zgody nie pasuje do kandydata albo rekrutacji (F37, 27.10.2026).
 *
 * Wariant A (decyzja Artura): zrzut nie trafia sam pod CV. Rekruter wgrywa
 * inny albo zapisuje ten z powodem — powód widzi Delivery Lead w QC CV.
 * Wspólne dla pola zgody w generatorze i przycisku na karcie CV.
 */

import { useId, useState } from "react";
import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CONSENT_OVERRIDE_REASON_MIN, overrideReasonValid, type ConsentCheck } from "@/lib/consent-check";

interface Props {
  check: ConsentCheck;
  busy: boolean;
  onPickAnother: () => void;
  onOverride: (reason: string) => void;
}

export function ConsentCheckNotice({ check, busy, onPickAnother, onOverride }: Props) {
  const reasonId = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const recruiterRequest = check.problems.some((line) => line.code === "recruiter_request");

  return (
    <div
      role="alert"
      data-testid="consent-check-mismatch"
      className="flex flex-col gap-2 rounded-md border border-destructive/25 bg-destructive-muted px-2.5 py-2 text-xs text-destructive-muted-foreground"
    >
      <p className="font-semibold">
        {recruiterRequest ? "To prośba o zgodę, a nie odpowiedź kandydata" : "Zrzut nie pasuje do tej rekrutacji"}
      </p>
      <ul className="flex flex-col gap-0.5">
        {check.problems.map((line) => (
          <li key={`p-${line.code}`} className="flex items-start gap-1.5">
            <X aria-hidden className="mt-0.5 size-3.5 shrink-0 text-destructive" />
            <span>{line.detail}</span>
          </li>
        ))}
        {check.passed.map((line) => (
          <li key={`ok-${line.code}`} className="flex items-start gap-1.5 text-foreground/80">
            <Check aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success" />
            <span>{line.detail}</span>
          </li>
        ))}
      </ul>
      <p>Zrzut nie trafił pod CV. PKO BP przyjmuje tylko mail od kandydata ze zgodą na numer ZOB tej rekrutacji.</p>
      {open ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={reasonId} className="font-medium text-foreground">
            Dlaczego to dobry zrzut? Delivery Lead zobaczy powód w QC CV.
          </label>
          <Textarea
            id={reasonId}
            rows={2}
            className="min-h-0 text-xs"
            value={reason}
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
            placeholder="np. kandydat odpisał z innej skrzynki"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              disabled={busy || !overrideReasonValid(reason)}
              loading={busy}
              onClick={() => onOverride(reason.trim())}
            >
              Zapisz z powodem
            </Button>
            <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
              Anuluj
            </Button>
            {!overrideReasonValid(reason) ? (
              <span className="text-muted-foreground">Co najmniej {CONSENT_OVERRIDE_REASON_MIN} znaków.</span>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <Button type="button" size="sm" disabled={busy} onClick={onPickAnother}>
            Wgraj inny zrzut
          </Button>
          <button
            type="button"
            className="text-xs underline underline-offset-2 hover:text-destructive disabled:opacity-60"
            disabled={busy}
            onClick={() => setOpen(true)}
          >
            To dobry zrzut — zapisz mimo to…
          </button>
        </div>
      )}
    </div>
  );
}
