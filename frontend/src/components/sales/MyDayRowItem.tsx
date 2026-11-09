"use client";

import Link from "next/link";
import { useState } from "react";

import { TruncatedText } from "@/components/ds/TruncatedText";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useCompleteActivity, type MyDayRow } from "@/lib/api/sales";

import { formatDealAmount, safeHref } from "./format";
import { clock, replyHref, rowReason, telHref } from "./my-day";
import { CallPanel, PhonePanel, PlanPanel } from "./MyDayRowPanels";

type PanelMode = "call" | "plan" | "phone";

const companyHref = (row: MyDayRow) =>
  row.opportunity ? `/sales/opportunities/${row.opportunity.id}` : `/sales/companies/${row.company.id}`;

function Reason({ row }: { row: MyDayRow }) {
  if (row.section !== "overdue") {
    return <TruncatedText className="max-w-full">{rowReason(row)}</TruncatedText>;
  }
  return (
    <span className="flex min-w-0 gap-1">
      <span className="shrink-0 text-destructive">Po terminie {row.days} dni</span>
      <TruncatedText className="max-w-full">{`· ${rowReason(row)}`}</TruncatedText>
    </span>
  );
}

function ContactInline({ row }: { row: MyDayRow }) {
  if (row.do_not_contact) return <Badge variant="neutral">Nie kontaktować</Badge>;
  const person = row.person;
  return (
    <span className="ml-auto flex shrink-0 items-baseline gap-1.5 text-xs">
      {person && <TruncatedText className="max-w-[112px] text-muted-foreground">{person.name}</TruncatedText>}
      {person?.phone ? (
        <a
          href={telHref(person.phone)}
          className="max-w-[124px] truncate tabular-nums text-primary hover:underline"
        >
          {person.phone}
        </a>
      ) : (
        <span className="text-muted-foreground">brak numeru</span>
      )}
    </span>
  );
}

function ReplyButton({ row }: { row: MyDayRow }) {
  const href = replyHref(row, safeHref(row.web_link));
  if (!href) {
    return (
      <Button size="sm" className="h-7 w-[72px] px-0" disabled title="Ten mail nie ma linku. Odpisz ze skrzynki.">
        Odpisz
      </Button>
    );
  }
  return (
    <Button size="sm" className="h-7 w-[72px] px-0" asChild>
      <a href={href} target="_blank" rel="noreferrer">
        Odpisz
      </a>
    </Button>
  );
}

/** Jeden wiersz kolejki: firma, osoba, numer, powód, kwota i przyciski, które to załatwiają. */
export function MyDayRowItem({ row, canEdit }: { row: MyDayRow; canEdit: boolean }) {
  const [mode, setMode] = useState<PanelMode | null>(null);
  const complete = useCompleteActivity();
  const { showError } = useToast();
  const toggle = (next: PanelMode) => setMode((current) => (current === next ? null : next));
  const close = () => setMode(null);
  const isMeeting = row.section === "meetings";
  const hasPhone = Boolean(row.person?.phone);

  const markDone = () => {
    if (row.activity_id === null) return;
    complete.mutate(
      { id: row.activity_id },
      { onError: (error) => showError(apiErrorMessage(error, "Nie udało się zamknąć zadania.")) },
    );
  };

  return (
    <li>
      <div className="flex min-h-11 items-center gap-2 px-3 py-1 max-lg:flex-wrap">
        {isMeeting && <span className="shrink-0 text-sm font-semibold tabular-nums text-primary">{clock(row.at)}</span>}
        <div className="min-w-0 flex-1 leading-tight max-lg:basis-full">
          <div className="flex min-w-0 items-baseline gap-2 max-lg:flex-wrap">
            <Link
              href={companyHref(row)}
              className="min-w-0 truncate text-sm font-medium text-foreground hover:underline"
              title={row.company.name}
            >
              {row.company.name}
            </Link>
            {!isMeeting && <ContactInline row={row} />}
          </div>
          <div className="flex min-w-0 items-baseline gap-2 text-xs text-muted-foreground">
            <div className="min-w-0 flex-1">
              <Reason row={row} />
            </div>
            {row.amount !== null && (
              <span className="shrink-0 font-medium tabular-nums text-foreground">
                {formatDealAmount(row.amount, row.currency)}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {row.section === "reply" && <ReplyButton row={row} />}
          {canEdit && row.section === "overdue" && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-[72px] px-0"
              disabled={complete.isPending}
              onClick={markDone}
            >
              Zrobione
            </Button>
          )}
          {canEdit && isMeeting && (
            <Button size="sm" variant="outline" className="h-7 px-2.5" onClick={() => toggle("plan")}>
              Po spotkaniu
            </Button>
          )}
          {canEdit && !isMeeting && (
            <>
              <Button size="sm" variant="ghost" className="h-7 px-2.5" onClick={() => toggle("plan")}>
                Zaplanuj
              </Button>
              {!row.do_not_contact && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 w-[104px] px-0"
                  onClick={() => toggle(hasPhone ? "call" : "phone")}
                >
                  {hasPhone ? "Zadzwoniłem" : "Uzupełnij numer"}
                </Button>
              )}
            </>
          )}
        </div>
      </div>
      {mode === "plan" && <PlanPanel row={row} onDone={close} />}
      {mode === "call" && <CallPanel row={row} onDone={close} />}
      {mode === "phone" && <PhonePanel row={row} onDone={close} />}
    </li>
  );
}
