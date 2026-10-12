"use client";

import * as React from "react";
import Link from "next/link";

import { EMPLOYMENT_DOT_TONE, EmploymentPill } from "@/components/ds/EmploymentMarker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  employedCountLabel,
  markerDetails,
  markerLabel,
  markerTone,
  type EmploymentMarker,
  type EmploymentMarkerTone,
} from "@/lib/employment-marker";
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

export const ASK_DELIVERY_HINT = "Przed wysłaniem profilu zapytaj Delivery.";
/** Okna dodawania: znacznik informuje, nie blokuje (decyzja D2, 12.10.2026). */
export const ADD_ANYWAY_HINT =
  "Dodanie jest możliwe. Przed wysłaniem CV do klienta uzgodnij to z Delivery Leadem.";

type FrameTone = EmploymentMarkerTone | "neutral";

const FRAME_TONE: Record<FrameTone, string> = {
  success: "border-success/20 bg-success-muted/40",
  warning: "border-warning/25 bg-warning-muted/50",
  info: "border-info/20 bg-info-muted/40",
  neutral: "border-border bg-muted/40",
};

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

export interface EmploymentNoticeProps {
  marker: EmploymentMarker;
  /** Gdy ramka stoi z dala od nazwiska: „Anna Przykładowa pracuje u nas · …”. */
  personName?: string;
  /** Ostatnia linia; `null` = bez niej. */
  hint?: string | null;
  tone?: FrameTone;
  role?: "note" | "alert";
  testId?: string;
  className?: string;
}

/**
 * Ramka z tym, co rekruter musi wiedzieć o osobie, która u nas pracuje:
 * klient, koniec zamówienia, Delivery Lead. Informuje, niczego nie blokuje.
 * „Kontrakt ›” widzi tylko osoba z dostępem do sekcji Delivery — bez niego
 * link prowadził na 403.
 */
export function EmploymentNotice({
  marker,
  personName,
  hint = ASK_DELIVERY_HINT,
  tone,
  role = "note",
  testId = "employment-notice",
  className,
}: EmploymentNoticeProps) {
  const canOpenContract = useAuthStore((state) => hasSectionAccess(state.user, "delivery"));
  const markerToneValue = markerTone(marker);
  return (
    <div
      role={role}
      data-testid={testId}
      className={cn("rounded-lg border px-3 py-2 text-xs", FRAME_TONE[tone ?? markerToneValue], className)}
    >
      <ul className="flex flex-col gap-1.5">
        {markerDetails(marker).map((line) => (
          <li key={line.key} className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="flex min-w-0 items-start gap-1.5 font-semibold text-foreground">
                <span
                  aria-hidden
                  className={cn(
                    "mt-1 inline-block size-2 shrink-0 rounded-full",
                    EMPLOYMENT_DOT_TONE[markerToneValue],
                  )}
                />
                <span className="min-w-0 break-words">
                  {personName ? `${personName} ${lowerFirst(line.title)}` : line.title}
                </span>
              </p>
              {line.detail ? <p className="mt-0.5 text-muted-foreground">{line.detail}</p> : null}
            </div>
            {line.contractId !== null && canOpenContract ? (
              <Link
                href={`/contracts/${line.contractId}?from=candidate`}
                className="inline-flex min-h-6 shrink-0 items-center font-medium text-primary hover:underline"
              >
                Kontrakt ›
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
      {hint ? <p className="mt-1 font-medium text-warning-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export interface EmployedPerson {
  id: number;
  name: string;
  marker: EmploymentMarker;
}

export interface EmployedPeopleNoticeProps {
  /** Osoby z wyboru, które u nas pracują (albo zaczynają). */
  people: EmployedPerson[];
  /** Ile osób jest w całym wyborze — do nagłówka „2 z 4 osób pracują u nas”. */
  total: number;
  hint?: string | null;
  /** Np. przycisk „Dodaj bez tych 2 osób”. */
  action?: React.ReactNode;
  className?: string;
}

const LISTED_PEOPLE = 3;

/** Ramka w oknach dodawania: jedna osoba — pełne szczegóły, kilka — lista. */
export function EmployedPeopleNotice({
  people,
  total,
  hint = ASK_DELIVERY_HINT,
  action,
  className,
}: EmployedPeopleNoticeProps) {
  if (people.length === 0) return null;
  if (people.length === 1 && !action) {
    return (
      <EmploymentNotice
        marker={people[0].marker}
        personName={people[0].name}
        hint={hint}
        className={className}
      />
    );
  }
  const rest = people.length - LISTED_PEOPLE;
  return (
    <div
      role="note"
      data-testid="employment-notice"
      className={cn("rounded-lg border px-3 py-2 text-xs", FRAME_TONE.success, className)}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 font-semibold text-foreground">
          <span aria-hidden className="inline-block size-2 shrink-0 rounded-full bg-success" />
          {employedCountLabel(people.length, total)}
        </p>
        {action}
      </div>
      <ul className="mt-1 flex flex-col gap-0.5 text-muted-foreground">
        {people.slice(0, LISTED_PEOPLE).map((person) => (
          <li key={person.id} className="min-w-0 break-words">
            <span className="font-medium text-foreground">{person.name}</span>
            {" — "}
            {lowerFirst(markerLabel(person.marker))}
          </li>
        ))}
        {rest > 0 ? <li>i jeszcze {rest}</li> : null}
      </ul>
      {hint ? <p className="mt-1 font-medium text-warning-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/**
 * Krótka pigułka, która po kliknięciu pokazuje ramkę — dla miejsc, gdzie
 * stała ramka zabrałaby treści wysokość (nagłówek panelu osoby).
 */
export function EmploymentPopoverPill({
  marker,
  className,
}: {
  marker: EmploymentMarker;
  className?: string;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex max-w-full rounded-full focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <EmploymentPill
            marker={marker}
            label={{ clients: "none", date: "short" }}
            className="whitespace-nowrap"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 max-w-[calc(100vw-1rem)] p-2">
        <EmploymentNotice marker={marker} tone="neutral" className="border-0 bg-transparent px-1 py-1" />
      </PopoverContent>
    </Popover>
  );
}
