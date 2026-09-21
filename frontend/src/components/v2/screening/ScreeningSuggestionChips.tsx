"use client";

/**
 * Podpowiedzi „Z notatek: … — Użyj" pod polami stawki na stanowisku screeningu.
 *
 * Stawka: kliknięcie wyłącznie WYPEŁNIA pole (jak wpisanie z klawiatury) —
 * do serwera idzie dopiero przy ruchu na „Zweryfikowany". Bez `rate` (w tym
 * przy `rate_redacted`) chip stawki nie istnieje: rola bez wglądu w stawki nie
 * widzi nawet śladu kwoty.
 *
 * Dostępność: „Użyj" to JAWNY zapis w profilu kandydata (robi go rodzic).
 * NIGDY nie dopisujemy jej do „Notatek rekrutera" — to pole widzi KLIENT
 * w share portalu, a podpowiedź pochodzi z wewnętrznych notatek. Wartość,
 * której nie da się pewnie przełożyć na pola profilu, dostaje link
 * „uzupełnij w profilu" zamiast „Użyj".
 */

import Link from "next/link";
import { StickyNote } from "lucide-react";

import {
  availabilityProfilePatch,
  availabilitySuggestionText,
  notedAtLabel,
  rateSuggestionFill,
  rateSuggestionLabel,
  type ScreeningSuggestions,
} from "@/lib/screening-suggestions";
import type { RateUnit } from "@/lib/api";

export interface ScreeningSuggestionChipsProps {
  suggestions: ScreeningSuggestions | null | undefined;
  disabled?: boolean;
  onUseRate: (fill: { rate: string; unit: RateUnit }) => void;
  /** Zapis dostępności w PROFILU. Brak = użytkownik nie może edytować kandydata. */
  onSaveAvailability?: (patch: { availability_date: string }) => void;
  savingAvailability?: boolean;
  /** Dokąd prowadzi „uzupełnij w profilu", gdy wartości nie da się zmapować. */
  profileHref?: string;
}

function Chip({
  text,
  actionLabel,
  onUse,
  hint,
  link,
  busy = false,
}: {
  text: string;
  actionLabel: string;
  onUse?: () => void;
  hint?: string;
  link?: { href: string; label: string };
  busy?: boolean;
}) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
      <StickyNote className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span className="min-w-0 truncate" title={text}>
        Z notatek: <span className="font-medium text-foreground">{text}</span>
      </span>
      {onUse ? (
        <button
          type="button"
          onClick={onUse}
          disabled={busy}
          aria-label={actionLabel}
          className="shrink-0 font-semibold text-primary hover:underline disabled:opacity-60"
        >
          {busy ? "Zapisuję…" : "Użyj"}
        </button>
      ) : link ? (
        <Link href={link.href} className="shrink-0 font-semibold text-primary hover:underline">
          {link.label}
        </Link>
      ) : hint ? (
        <span className="shrink-0 italic">{hint}</span>
      ) : null}
    </span>
  );
}

export function ScreeningSuggestionChips({
  suggestions,
  disabled = false,
  onUseRate,
  onSaveAvailability,
  savingAvailability = false,
  profileHref,
}: ScreeningSuggestionChipsProps) {
  const rate = suggestions?.rate_redacted ? undefined : suggestions?.rate;
  const availabilityText = suggestions?.availability
    ? availabilitySuggestionText(suggestions.availability)
    : null;
  if (!rate && !availabilityText) return null;

  const fill = rate ? rateSuggestionFill(rate) : null;
  const availabilityNoted = notedAtLabel(suggestions?.availability?.noted_at);
  const availabilityPatch = suggestions?.availability
    ? availabilityProfilePatch(suggestions.availability)
    : null;
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="screening-suggestions">
      {rate ? (
        <Chip
          text={rateSuggestionLabel(rate)}
          actionLabel="Użyj stawki z notatek"
          onUse={!disabled && fill ? () => onUseRate(fill) : undefined}
          hint={!fill ? "inna waluta lub jednostka — wpisz ręcznie" : undefined}
        />
      ) : null}
      {availabilityText ? (
        <Chip
          text={availabilityNoted ? `${availabilityText} · ${availabilityNoted}` : availabilityText}
          actionLabel="Zapisz dostępność z notatek w profilu kandydata"
          busy={savingAvailability}
          onUse={
            !disabled && onSaveAvailability && availabilityPatch
              ? () => onSaveAvailability(availabilityPatch)
              : undefined
          }
          link={
            !availabilityPatch && profileHref
              ? { href: profileHref, label: "uzupełnij w profilu" }
              : undefined
          }
        />
      ) : null}
    </div>
  );
}
