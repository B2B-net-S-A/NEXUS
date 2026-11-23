"use client";

import { PhoneIncoming } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWhoCalls, type PhoneMatch } from "@/lib/api/sales-calling";
import { formatWeekdayDayPl } from "@/lib/date-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { resolveViewState } from "@/lib/view-state";

import { STATE_TONES, stateLabel } from "./calling";

const PHONE_DIGITS = 9;

/** Ostatnie 9 cyfr wpisanego numeru: +48, spacje i myślniki nie mają znaczenia. */
export function phoneTail(value: string): string {
  const digits = value.replace(/\D/g, "");
  return digits.length >= PHONE_DIGITS ? digits.slice(-PHONE_DIGITS) : "";
}

function matchLine(match: PhoneMatch): string {
  if (match.record_id === null) return "Kontakt firmy, bez listy dzwonienia";
  return [
    match.caller_name ? `Dzwoni ${match.caller_name}` : "Bez osoby",
    match.last_outcome_at ? `ostatnio ${formatWeekdayDayPl(match.last_outcome_at.slice(0, 10))}` : null,
    match.callback_on ? `powrót ${formatWeekdayDayPl(match.callback_on)}` : null,
    match.campaign_name,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * „Kto dzwoni?” (zgłoszenie dzwoniących 23.11.2026): klient oddzwania, telefon pokazuje
 * sam numer. Pole w nagłówku Dzwonienia szuka w listach wszystkich osób i w kontaktach firm.
 */
export function WhoIsCalling() {
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const tail = phoneTail(useDebouncedValue(value, 250));
  const query = useWhoCalls(tail);
  const typedDigits = value.replace(/\D/g, "").length;
  const matches = query.data ?? [];
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: matches.length === 0,
  });

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={box} className="relative" data-tour="sales.calling.who-calls">
      <PhoneIncoming
        className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <Input
        aria-label="Kto dzwoni? Numer telefonu"
        placeholder="Kto dzwoni? Wpisz numer"
        inputMode="tel"
        className="h-7 w-52 pl-7 text-xs"
        value={value}
        maxLength={40}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => event.key === "Escape" && setOpen(false)}
        onChange={(event) => {
          setValue(event.target.value);
          setOpen(true);
        }}
      />
      {open && typedDigits > 0 && (
        <div
          role="dialog"
          aria-label="Kto dzwoni"
          className="absolute right-0 top-8 z-30 w-[min(34rem,calc(100vw-2rem))] rounded-lg border border-border bg-popover p-2 shadow-lg"
        >
          {!tail ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">Wpisz cały numer: co najmniej 9 cyfr.</p>
          ) : viewState === "loading" ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">Szukam numeru…</p>
          ) : viewState === "empty" ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">
              Tego numeru nie ma w listach dzwonienia ani w kontaktach firm.
            </p>
          ) : viewState !== "ready" ? (
            <QueryStateNotice state={viewState} onRetry={() => void query.refetch()} />
          ) : (
            <ul className="divide-y divide-border">
              {matches.map((match) => (
                <li
                  key={match.record_id !== null ? `r:${match.record_id}` : `c:${match.contact_id}`}
                  className="flex items-start gap-3 px-1 py-2"
                >
                  <div className="min-w-0 flex-1 leading-tight">
                    <p className="truncate text-sm font-semibold text-foreground">{match.company.name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {[match.person_name, match.person_title].filter(Boolean).join(" · ") || "Bez wskazanej osoby"}
                    </p>
                    <p className="mt-1 truncate text-xs text-foreground">{matchLine(match)}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    {match.do_not_contact ? (
                      <Badge variant="danger" size="sm">
                        Nie kontaktować
                      </Badge>
                    ) : match.record_state ? (
                      <Badge variant={STATE_TONES[match.record_state]} size="sm" className="whitespace-nowrap">
                        {stateLabel(match.record_state)}
                      </Badge>
                    ) : null}
                    <Button size="sm" variant="outline" className="h-7 px-2 text-xs" asChild>
                      <Link href={`/sales/companies/${match.company.id}`}>Karta firmy</Link>
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
