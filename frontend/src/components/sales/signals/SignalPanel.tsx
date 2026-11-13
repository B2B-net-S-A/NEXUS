"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { TruncatedText } from "@/components/ds/TruncatedText";
import { safeHref } from "@/components/sales/format";
import { Card } from "@/components/ui/card";
import {
  SIGNAL_STRENGTH_LABELS,
  SIGNAL_TYPE_LABELS,
  signalPayload,
  useCompanyPeople,
  type Lead,
} from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";

import { SignalActions } from "./SignalActions";
import { TalkingPoints } from "./TalkingPoints";

const FIRST_PEOPLE = 3;

function Block({ label, aside, children }: { label: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-0.5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-xs font-medium text-foreground">{label}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Line({ children }: { children: string }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}

/** Kogo znamy w firmie teraz; awaria nie udaje, że nikogo nie znamy. */
function KnownPeople({ companyId }: { companyId: number }) {
  const people = useCompanyPeople(companyId);
  const current = (people.data?.people ?? []).filter((person) => person.relationship === "current");
  return (
    <section className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-medium text-foreground">
          Kogo znamy
          {people.isSuccess && (
            <span className="font-normal text-muted-foreground"> · {people.data.counts.current ?? 0} obecnie</span>
          )}
        </h3>
        <Link href={`/sales/companies/${companyId}?tab=people`} className="shrink-0 text-xs text-primary hover:underline">
          Karta firmy
        </Link>
      </div>
      {people.isLoading ? (
        <Line>Szukamy osób z bazy…</Line>
      ) : people.isError ? (
        <Line>Nie udało się pobrać listy osób. Spróbuj na karcie firmy.</Line>
      ) : current.length === 0 ? (
        <Line>Nikt z bazy NEXUSA nie pracuje tam teraz.</Line>
      ) : (
        <ul className="space-y-0.5">
          {current.slice(0, FIRST_PEOPLE).map((person) => (
            <li key={person.candidate_id} className="flex min-w-0 items-baseline gap-2 text-xs">
              <Link
                href={`/candidates/${person.candidate_id}`}
                className="shrink-0 font-medium text-foreground hover:underline"
              >
                {person.name} {person.lastname}
              </Link>
              {person.title && (
                <TruncatedText className="min-w-0 max-w-none text-muted-foreground">{person.title}</TruncatedText>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface SignalPanelProps {
  lead: Lead;
  reasons?: readonly string[];
}

/** Panel sygnału: co się stało, dlaczego teraz, źródło, przez kogo wejść, decyzja. */
export function SignalPanel({ lead, reasons }: SignalPanelProps) {
  const signal = signalPayload(lead);
  const href = safeHref(lead.url);
  const meta = [
    signal.strength ? SIGNAL_STRENGTH_LABELS[signal.strength] : null,
    signal.type ? SIGNAL_TYPE_LABELS[signal.type] : null,
    signal.published ? formatIsoDatePl(signal.published) : null,
  ].filter(Boolean);
  return (
    <Card className="flex flex-col overflow-hidden p-0 lg:sticky lg:top-3 lg:max-h-[calc(100dvh-15.25rem)]">
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2.5">
        <header className="space-y-0.5">
          <div className="flex items-baseline justify-between gap-2">
            {lead.company_id ? (
              <Link
                href={`/sales/companies/${lead.company_id}`}
                className="truncate text-sm font-semibold text-foreground hover:underline"
              >
                {lead.company_name}
              </Link>
            ) : (
              <span className="truncate text-sm font-semibold text-foreground">{lead.company_name}</span>
            )}
            <span className="shrink-0 text-xs text-muted-foreground">{meta.join(" · ")}</span>
          </div>
          <h2 className="text-sm font-medium leading-snug text-foreground">{lead.title}</h2>
        </header>
        {lead.summary && (
          <Block label="Co się stało">
            <p className="text-xs leading-snug text-muted-foreground">{lead.summary}</p>
          </Block>
        )}
        {signal.why_now && (
          <Block label="Dlaczego teraz">
            <p className="text-xs leading-snug text-muted-foreground">{signal.why_now}</p>
          </Block>
        )}
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            Źródło: {signal.domain || href} <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        )}
        {lead.company_id && <KnownPeople companyId={lead.company_id} />}
        {lead.company_id && <TalkingPoints companyId={lead.company_id} showEmpty />}
      </div>
      <div className="shrink-0 border-t border-border px-3 py-2">
        <SignalActions key={lead.id} lead={lead} reasons={reasons} />
      </div>
    </Card>
  );
}
