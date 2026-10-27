"use client";

import { Copy, Mail, Phone } from "lucide-react";

import { useToast } from "@/components/Toast";
import { telHref } from "@/components/v2/candidates/CandidatePhoneCell";
import { copyTextToClipboard } from "@/lib/clipboard";
import { formatPhone } from "@/lib/phone-format";

/**
 * Telefon i e-mail kandydata pod nazwiskiem w nagłówku panelu rozmowy —
 * żeby umawiać termin bez wchodzenia w profil (wariant C, 20.10.2026).
 * Numer to link `tel:`, e-mail `mailto:`, „Kopiuj” bierze to, co jest.
 * Bez obu (brak danych albo rola bez odczytu kandydatów) linii nie ma.
 */
export function CandidateContactLine({
  phone,
  email,
}: {
  phone: string | null | undefined;
  email: string | null | undefined;
}) {
  const { showSuccess, showError } = useToast();
  const tel = phone?.trim() || null;
  const mail = email?.trim() || null;
  if (!tel && !mail) return null;

  const both = tel != null && mail != null;
  const copy = async () => {
    const ok = await copyTextToClipboard([tel, mail].filter(Boolean).join(" · "));
    if (ok) showSuccess(both ? "Skopiowano telefon i e-mail" : tel ? "Skopiowano numer telefonu" : "Skopiowano e-mail");
    else showError("Nie udało się skopiować — zaznacz tekst ręcznie.");
  };

  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm"
      data-testid="cycle-candidate-contact"
    >
      {tel ? (
        <a
          href={telHref(tel)}
          className="inline-flex items-center gap-1.5 font-semibold tabular-nums text-foreground hover:text-primary hover:underline"
        >
          <Phone className="h-3.5 w-3.5 text-primary" aria-hidden />
          {formatPhone(tel)}
        </a>
      ) : null}
      {mail ? (
        <a
          href={`mailto:${mail}`}
          className="inline-flex min-w-0 max-w-full items-center gap-1.5 text-foreground hover:text-primary hover:underline"
        >
          <Mail className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
          <span className="truncate">{mail}</span>
        </a>
      ) : null}
      <button
        type="button"
        onClick={copy}
        className="inline-flex h-7 items-center gap-1 rounded-full border border-border px-2.5 text-xs font-semibold text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Copy className="h-3 w-3" aria-hidden />
        {both ? "Kopiuj oba" : "Kopiuj"}
      </button>
    </div>
  );
}
