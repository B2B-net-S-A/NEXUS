"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";

import { safeHref } from "@/components/sales/format";
import { Badge } from "@/components/ui/badge";
import type { Potential } from "@/lib/api/sales-potential";

import { VERDICT_VARIANT, eventDate } from "./potential-format";

const QUESTIONS_SHOWN = 3;
const EVENTS_SHOWN = 3;

/** Czy skrót coś pokaże: gotowa ocena albo przynajmniej zdarzenia z researchu. */
export function prepPotentialShows(data: Potential | undefined): boolean {
  if (!data?.enabled || !data.result) return false;
  return Boolean(data.result.assessment) || (data.result.research.events ?? []).length > 0;
}

/** Bez oceny modelu (awaria, brak klucza): same zdarzenia ze źródłami, jak punkty. */
function ResearchOnly({ companyId, data }: { companyId: number; data: Potential }) {
  const events = (data.result?.research.events ?? []).slice(0, EVENTS_SHOWN);
  return (
    <section className="space-y-1 border-t border-border pt-3" aria-label="Co się dzieje w firmie">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Co się dzieje w firmie</h3>
        <Link href={`/sales/companies/${companyId}?tab=potential`} className="text-xs text-primary hover:underline">
          Więcej
        </Link>
      </div>
      <ul className="list-disc space-y-0.5 pl-4">
        {events.map((event) => {
          const href = safeHref(event.url);
          return (
            <li key={`${event.date}-${event.text}`} className="text-xs leading-snug text-muted-foreground">
              <span className="tabular-nums">{eventDate(event.date)}</span> {event.text}
              {href && (
                <a href={href} target="_blank" rel="noreferrer" className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline">
                  źródło <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Pierwsze zdania streszczenia: skrót ma się zmieścić w karcie obok listy. */
function firstSentences(text: string, count: number): string {
  const parts = text.match(/[^.!?]+[.!?]+(\s|$)/g);
  return parts ? parts.slice(0, count).join("").trim() : text;
}

/**
 * „Mój dzień” → „Przygotowanie do spotkania”: skrót gotowej oceny potencjału
 * (decyzja Artura 23.11.2026). Bez oceny pokazuje zdarzenia z researchu, a bez
 * researchu nic nie rysuje i karta pokazuje punkty do rozmowy jak dotąd.
 */
export function PrepPotential({ companyId, data }: { companyId: number; data: Potential | undefined }) {
  if (!data || !prepPotentialShows(data)) return null;
  const assessment = data.result?.assessment;
  if (!assessment) return <ResearchOnly companyId={companyId} data={data} />;
  const reference = data.result?.references[0]?.reference;
  return (
    <section className="space-y-1.5 border-t border-border pt-3" aria-label="Potencjał współpracy">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">Potencjał</h3>
          <Badge variant={VERDICT_VARIANT[assessment.verdict]} size="sm">
            {assessment.verdict}
          </Badge>
        </div>
        <Link href={`/sales/companies/${companyId}?tab=potential`} className="text-xs text-primary hover:underline">
          Pełna ocena
        </Link>
      </div>
      <p className="text-xs leading-snug text-foreground">{firstSentences(assessment.summary, 2)}</p>
      <p className="text-xs leading-snug">
        <span className="text-muted-foreground">Wejście: </span>
        <span className="font-medium text-foreground">{assessment.land.title}</span>
      </p>
      {assessment.questions.length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground">Zapytaj</p>
          <ul className="list-disc space-y-0.5 pl-4 text-xs leading-snug text-foreground">
            {assessment.questions.slice(0, QUESTIONS_SHOWN).map((q) => (
              <li key={q.text}>{q.text}</li>
            ))}
          </ul>
        </div>
      )}
      {reference && (
        <p className="text-xs leading-snug text-muted-foreground">
          Pokaż: <span className="text-foreground">{reference.client}</span>
        </p>
      )}
    </section>
  );
}
