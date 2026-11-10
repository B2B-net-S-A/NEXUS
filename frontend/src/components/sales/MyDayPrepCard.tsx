"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useCompanyPeople, type MyDayPrep, type MyDayPrepEntry } from "@/lib/api/sales";
import { formatDayMonthPl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { CreateOpportunityFromMeetingDialog } from "./CreateOpportunityFromMeetingDialog";
import { daysLabel } from "./format";
import { clock, historyHeadline, meetingSpan, telHref } from "./my-day";

const PEOPLE_PREVIEW = 3;

function HistoryFact({
  label,
  entry,
  companyName,
}: {
  label: string;
  entry: MyDayPrepEntry;
  companyName: string;
}) {
  const ago = entry.days === 0 ? "dziś" : `${daysLabel(entry.days)} temu`;
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium text-foreground">
        {historyHeadline(entry, companyName)}, {formatDayMonthPl(entry.at)} o {clock(entry.at)}
      </dd>
      <dd className="text-xs text-muted-foreground">
        <TruncatedText className="max-w-full">{entry.subject ? `${ago}, ${entry.subject}` : ago}</TruncatedText>
      </dd>
    </div>
  );
}

function CompanyContacts({ prep }: { prep: MyDayPrep }) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Kontakty w firmie</h3>
        <span className="text-xs text-muted-foreground">zaproszenie nie podaje, kto będzie</span>
      </div>
      {prep.contacts.length === 0 ? (
        <p className="text-xs text-muted-foreground">Firma nie ma kontaktów.</p>
      ) : (
        <ul className="space-y-0.5">
          {prep.contacts.map((contact) => (
            <li key={contact.id} className="flex min-w-0 items-baseline gap-2 text-xs">
              <span className="shrink-0 font-medium text-foreground">{contact.name}</span>
              <TruncatedText className="min-w-0 max-w-full flex-1 text-muted-foreground">
                {contact.title ?? ""}
              </TruncatedText>
              {contact.phone && (
                <a href={telHref(contact.phone)} className="shrink-0 tabular-nums text-primary hover:underline">
                  {contact.phone}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function WhoWeKnow({ companyId, companyName }: { companyId: number; companyName: string }) {
  const people = useCompanyPeople(companyId);
  const counts = people.data?.counts;
  const total = counts ? Object.values(counts).reduce((sum, n) => sum + n, 0) : 0;
  const state = resolveViewState({
    isLoading: people.isLoading,
    error: people.error,
    isSuccess: people.isSuccess,
    isEmpty: total === 0,
  });
  return (
    <div className="space-y-1.5 border-t border-border pt-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Kogo znamy</h3>
        <Link href={`/sales/companies/${companyId}`} className="text-xs text-primary hover:underline">
          Karta firmy
        </Link>
      </div>
      {state === "loading" ? (
        <p className="text-xs text-muted-foreground">Wczytywanie…</p>
      ) : state === "empty" ? (
        <p className="text-xs text-muted-foreground">W bazie nie ma nikogo z {companyName}.</p>
      ) : state !== "ready" ? (
        <QueryStateNotice state={state} onRetry={() => void people.refetch()} />
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            Teraz {counts?.current ?? 0} · przez nas {counts?.via_us ?? 0} · kiedyś {counts?.past ?? 0} · bez dat{" "}
            {counts?.unknown ?? 0}
          </p>
          <ul className="space-y-1">
            {(people.data?.people ?? []).slice(0, PEOPLE_PREVIEW).map((person) => (
              <li key={person.candidate_id} className="flex min-w-0 items-baseline justify-between gap-3 text-xs">
                <Link
                  href={`/candidates/${person.candidate_id}`}
                  className="shrink-0 font-medium text-foreground hover:underline"
                >
                  {person.name} {person.lastname}
                </Link>
                <TruncatedText className="min-w-0 max-w-full text-muted-foreground">{person.title ?? ""}</TruncatedText>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** Przygotowanie do najbliższego spotkania: kto, ostatni kontakt, czy jest szansa. */
export function MyDayPrepCard({ prep, canEdit }: { prep: MyDayPrep; canEdit: boolean }) {
  const [creating, setCreating] = useState(false);
  const [last, previous] = prep.history;
  return (
    <Card className="space-y-3 p-4">
      <div>
        <p className="text-xs text-muted-foreground">Przygotowanie do spotkania</p>
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="truncate text-base font-semibold text-foreground">{prep.company.name}</h2>
          <span className="shrink-0 text-sm font-semibold tabular-nums text-primary">
            {meetingSpan(prep.at, prep.duration_minutes)}
          </span>
        </div>
        <TruncatedText className="max-w-full text-xs text-muted-foreground">{prep.subject ?? ""}</TruncatedText>
      </div>
      <CompanyContacts prep={prep} />
      {last && (
        <dl className="space-y-2 border-t border-border pt-3">
          <HistoryFact label="Ostatni kontakt" entry={last} companyName={prep.company.name} />
          {previous && <HistoryFact label="Wcześniej" entry={previous} companyName={prep.company.name} />}
        </dl>
      )}
      {prep.can_create_opportunity && canEdit && (
        <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
          <div className="min-w-0 leading-tight">
            <p className="text-sm font-medium text-foreground">Brak otwartej szansy</p>
            <p className="text-xs text-muted-foreground">Załóż szansę po spotkaniu.</p>
          </div>
          <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
            Załóż
          </Button>
        </div>
      )}
      <WhoWeKnow companyId={prep.company.id} companyName={prep.company.name} />
      {creating && (
        <CreateOpportunityFromMeetingDialog meeting={{ id: prep.activity_id }} onClose={() => setCreating(false)} />
      )}
    </Card>
  );
}
