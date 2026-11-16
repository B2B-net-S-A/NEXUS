"use client";

import { CalendarCheck, Check, Users, Video } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { LiveTraining } from "@/lib/api/trainings";
import { safeExternalHref } from "@/lib/safe-href";
import { cn } from "@/lib/utils";

import { rehearsalLabel } from "./training-model";

const WEEKDAYS = ["nd", "pn", "wt", "śr", "czw", "pt", "sob"];
const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

interface TrainingCalendarProps {
  live: LiveTraining[];
  onRegister: (id: number, join: boolean) => Promise<boolean>;
  busy?: boolean;
  /** Dzień firmy `RRRR-MM-DD` (liczenie „za N dni”). */
  today: string;
}

function parts(iso: string | null): { weekday: string; day: string; month: string } | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return { weekday: WEEKDAYS[date.getUTCDay()], day: String(d), month: MONTHS[m - 1] };
}

function daysUntil(iso: string | null, today: string): number | null {
  if (!iso) return null;
  const a = Date.parse(`${iso}T00:00:00Z`);
  const b = Date.parse(`${today}T00:00:00Z`);
  return Math.round((a - b) / 86_400_000);
}

function DateBlock({ iso, big }: { iso: string | null; big?: boolean }) {
  const p = parts(iso);
  return (
    <div
      className={cn(
        "flex shrink-0 flex-col items-center justify-center rounded-lg border border-border bg-muted/40 leading-none",
        big ? "h-16 w-16" : "h-12 w-12",
      )}
      aria-hidden
    >
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{p?.weekday ?? "—"}</span>
      <span className={cn("font-semibold tabular-nums", big ? "text-2xl" : "text-lg")}>{p?.day ?? "?"}</span>
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{p?.month ?? ""}</span>
    </div>
  );
}

function seatsLabel(item: LiveTraining): string | null {
  if (item.seat_limit) {
    const free = Math.max(0, item.seat_limit - (item.taken ?? 0));
    return free === 0 ? "brak wolnych miejsc" : `${free} wolnych z ${item.seat_limit}`;
  }
  return item.taken ? `zapisani: ${item.taken}` : null;
}

function when(item: LiveTraining): string {
  const p = parts(item.session_date);
  const day = p ? `${p.weekday} ${p.day} ${p.month}` : "termin do ustalenia";
  const hours = item.time_from ? `, ${item.time_from}${item.time_to ? `–${item.time_to}` : ""}` : "";
  return `${day}${hours}`;
}

function Meta({ item }: { item: LiveTraining }) {
  const seats = seatsLabel(item);
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
      <span>{when(item)}</span>
      {item.trainer_kind ? (
        <span>{item.trainer_kind === "consultant" ? "trener z Talent Community" : "prowadzi osoba z zespołu"}</span>
      ) : null}
      {item.topic ? <span>{item.topic}</span> : null}
      <span className="inline-flex items-center gap-1">
        <Video className="h-3.5 w-3.5" aria-hidden /> {item.platform || "Microsoft Teams"}, nagrywane
      </span>
      {seats ? (
        <span className="inline-flex items-center gap-1 tabular-nums">
          <Users className="h-3.5 w-3.5" aria-hidden /> {seats}
        </span>
      ) : null}
    </span>
  );
}

function full(item: LiveTraining): boolean {
  return Boolean(item.seat_limit && (item.taken ?? 0) >= item.seat_limit);
}

/** Kalendarz szkoleń: najbliższe, na które jestem zapisany, na górze, reszta pod spodem. */
export function TrainingCalendar({ live, onRegister, busy, today }: TrainingCalendarProps) {
  if (live.length === 0) {
    return (
      <p data-tour="trainings.calendar" className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
        Nie ma zaplanowanych szkoleń. Nowe pojawią się tutaj razem z zapisem.
      </p>
    );
  }
  const next = live.find((item) => item.registered) ?? null;
  const rest = live.filter((item) => item !== next);
  const join = next?.join_url ? safeExternalHref(next.join_url) : null;
  const inDays = next ? daysUntil(next.session_date, today) : null;

  return (
    <div className="space-y-4" data-tour="trainings.calendar">
      {next ? (
        <section aria-label="Najbliższe Twoje szkolenie" className="flex gap-4 rounded-xl border border-border bg-card p-4">
          <DateBlock iso={next.session_date} big />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="success" size="md">
                <Check className="mr-1 h-3 w-3" aria-hidden /> Jesteś zapisany
              </Badge>
              {next.mandatory ? (
                <Badge variant="warning" size="md">
                  Obowiązkowe dla Twojej roli
                </Badge>
              ) : null}
              {inDays !== null ? (
                <span className="text-xs text-muted-foreground">
                  {inDays === 0 ? "dziś" : inDays === 1 ? "jutro" : `za ${inDays} dni`}
                </span>
              ) : null}
            </div>
            <h2 className="text-lg font-semibold leading-snug text-foreground">{next.title}</h2>
            <Meta item={next} />
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {join ? (
                <Button asChild size="sm">
                  <a href={join} target="_blank" rel="noopener noreferrer">
                    <Video className="h-3.5 w-3.5" aria-hidden /> Dołącz w Teams
                  </a>
                </Button>
              ) : null}
              {next.invited ? (
                <span className="inline-flex items-center gap-1 text-xs text-success-muted-foreground">
                  <CalendarCheck className="h-3.5 w-3.5" aria-hidden /> Zaproszenie jest w Twoim kalendarzu
                </span>
              ) : null}
              {next.mandatory ? null : (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void onRegister(next.id, false)}>
                  Wypisz się
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Przypomnimy dzień wcześniej i 15 minut przed. Nie dasz rady? Nagranie zobaczysz w „Nagraniach”.
            </p>
          </div>
        </section>
      ) : null}

      {rest.length > 0 ? (
        <section aria-label="Następne szkolenia" className="space-y-2">
          <h2 className="text-sm font-semibold text-foreground">{next ? "Następne" : "Najbliższe szkolenia"}</h2>
          <ul className="space-y-2">
            {rest.map((item) => {
              const link =
                (item.registered || item.leading) && item.join_url ? safeExternalHref(item.join_url) : null;
              return (
                <li
                  key={item.id}
                  className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5 sm:flex-nowrap"
                >
                  <DateBlock iso={item.session_date} />
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <p className="text-sm font-medium text-foreground">{item.title}</p>
                    <Meta item={item} />
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {link ? (
                      <a
                        href={link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm font-medium text-primary hover:underline"
                      >
                        Dołącz
                      </a>
                    ) : null}
                    {item.leading && item.rehearsal?.join_url ? (
                      <a
                        href={safeExternalHref(item.rehearsal.join_url) ?? undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-primary hover:underline"
                      >
                        Próba: {rehearsalLabel(item.rehearsal.start)}
                      </a>
                    ) : null}
                    {item.leading ? (
                      <Badge variant="soft" size="md">
                        Prowadzisz
                      </Badge>
                    ) : item.mandatory ? (
                      <Badge variant="warning" size="md">
                        Obowiązkowe
                      </Badge>
                    ) : (
                      <Button
                        size="sm"
                        variant={item.registered ? "outline" : "primary"}
                        disabled={busy || (!item.registered && full(item))}
                        onClick={() => void onRegister(item.id, !item.registered)}
                      >
                        {item.registered ? "Wypisz się" : full(item) ? "Brak miejsc" : "Zapisz się"}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
