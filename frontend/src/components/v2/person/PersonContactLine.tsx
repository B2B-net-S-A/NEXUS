"use client";

/**
 * Telefon i e-mail osoby pod jej nazwiskiem w panelu na Tablicy (09.10.2026).
 * Do tej daty po kontakt trzeba było wejść w profil. Numer jest linkiem
 * `tel:`, ikona obok kopiuje; adres jest tekstem z ikoną kopiowania.
 * Czego profil nie ma, tego nie pokazujemy — puste miejsce czytałoby się jak
 * wartość.
 */

import { Copy, Mail, Phone } from "lucide-react";

import { useToast } from "@/components/Toast";
import { telHref } from "@/components/v2/candidates/CandidatePhoneCell";
import { copyTextToClipboard } from "@/lib/clipboard";

const COPY_BUTTON =
  "hit-area shrink-0 rounded p-0.5 text-muted-foreground hover:bg-primary/10 hover:text-primary focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

export interface PersonContactLineProps {
  phone: string | null | undefined;
  email: string | null | undefined;
  personName: string;
}

export function PersonContactLine({ phone, email, personName }: PersonContactLineProps) {
  const { showSuccess, showError } = useToast();
  const phoneValue = phone?.trim() || null;
  const emailValue = email?.trim() || null;
  if (!phoneValue && !emailValue) return null;

  const copy = async (value: string, done: string, failed: string) => {
    const ok = await copyTextToClipboard(value);
    if (ok) showSuccess(done);
    else showError(failed);
  };

  return (
    <div
      className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px]"
      data-testid="person-contact-line"
    >
      {phoneValue ? (
        <span className="inline-flex min-w-0 items-center gap-1">
          <Phone className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
          <a
            href={telHref(phoneValue)}
            title={`Zadzwoń: ${phoneValue}`}
            className="truncate tabular-nums text-foreground hover:text-primary hover:underline"
          >
            {phoneValue}
          </a>
          <button
            type="button"
            onClick={() =>
              void copy(
                phoneValue,
                "Skopiowano numer telefonu",
                "Nie udało się skopiować numeru — zaznacz go ręcznie.",
              )
            }
            aria-label={`Kopiuj numer: ${personName}`}
            title="Kopiuj numer"
            className={COPY_BUTTON}
          >
            <Copy className="h-3 w-3" aria-hidden="true" />
          </button>
        </span>
      ) : null}
      {emailValue ? (
        <span className="inline-flex min-w-0 items-center gap-1">
          <Mail className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="truncate text-foreground" title={emailValue}>
            {emailValue}
          </span>
          <button
            type="button"
            onClick={() =>
              void copy(
                emailValue,
                "Skopiowano adres e-mail",
                "Nie udało się skopiować adresu — zaznacz go ręcznie.",
              )
            }
            aria-label={`Kopiuj adres e-mail: ${personName}`}
            title="Kopiuj adres e-mail"
            className={COPY_BUTTON}
          >
            <Copy className="h-3 w-3" aria-hidden="true" />
          </button>
        </span>
      ) : null}
    </div>
  );
}
