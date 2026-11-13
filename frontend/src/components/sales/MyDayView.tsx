"use client";

import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { useMyDay, type MyDay, type MyDayRow, type MyDaySectionKey } from "@/lib/api/sales";
import { useHandoffs } from "@/lib/api/sales-handoffs";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { BookMeetingDialog } from "./handoff/BookMeetingForm";
import { useMyDayHandoffs } from "./handoff/MyDayHandoffs";
import { dayHeading, dayLine, isDayEmpty, OFFERS_PREVIEW, plural } from "./my-day";
import { MyDayPrepCard } from "./MyDayPrepCard";
import { MyDayReminders } from "./MyDayReminders";
import { MyDayRowItem } from "./MyDayRowItem";
import { MyDaySignals } from "./signals/MyDaySignals";

const SECTIONS: { key: MyDaySectionKey; title: string }[] = [
  { key: "meetings", title: "Spotkania dziś" },
  { key: "reply", title: "Odpowiedz" },
  { key: "overdue", title: "Zaległe kroki" },
  { key: "offers", title: "Oferty bez ruchu ponad 14 dni" },
];

function OffersHint({
  shown,
  total,
  onToggle,
}: {
  shown: boolean;
  total: number;
  onToggle: () => void;
}) {
  return (
    <span className="text-xs text-muted-foreground">
      {shown ? `Wszystkie ${total}` : `${OFFERS_PREVIEW} największych z ${total}`}
      {" · "}
      <button type="button" className="text-primary hover:underline" onClick={onToggle}>
        {shown ? "Zwiń" : `Pokaż pozostałe ${total - OFFERS_PREVIEW}`}
      </button>
    </span>
  );
}

function DayQueue({ day, canEdit }: { day: MyDay; canEdit: boolean }) {
  const [allOffers, setAllOffers] = useState(false);
  const rowsOf = (key: MyDaySectionKey): MyDayRow[] =>
    key === "offers" && !allOffers ? day[key].slice(0, OFFERS_PREVIEW) : day[key];
  const renderSection = (section: (typeof SECTIONS)[number]) => (
        <section key={section.key}>
          <header className="flex items-baseline justify-between gap-3 border-b border-border bg-muted/40 px-3 py-1">
            <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{section.title}</h2>
            {section.key === "offers" && day.offers.length > OFFERS_PREVIEW && (
              <OffersHint
                shown={allOffers}
                total={day.offers.length}
                onToggle={() => setAllOffers((value) => !value)}
              />
            )}
          </header>
          <ul className="divide-y divide-border border-b border-border">
            {rowsOf(section.key).map((row) => (
              <MyDayRowItem key={row.key} row={row} canEdit={canEdit} />
            ))}
          </ul>
        </section>
  );
  const visible = SECTIONS.filter((section) => day[section.key].length > 0);
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
      {visible.filter((section) => section.key !== "offers").map(renderSection)}
      {/* Nowe sygnały nad ofertami bez ruchu (G3). */}
      <MyDaySignals signals={day.signals ?? []} />
      {visible.filter((section) => section.key === "offers").map(renderSection)}
    </div>
  );
}

/** Spotkania dziś bez tych, które są już w „Przekazane do Ciebie”: jedno spotkanie, jeden wiersz. */
function withoutHandedMeetings(day: MyDay, handedIds: Set<number>): MyDay {
  const meetings = day.meetings.filter((row) => !row.opportunity || !handedIds.has(row.opportunity.id));
  return { ...day, meetings, counts: { ...day.counts, meetings: meetings.length } };
}

function DayContent({ day: fullDay, canEdit }: { day: MyDay; canEdit: boolean }) {
  const handoffs = useHandoffs();
  const [booking, setBooking] = useState(false);
  const handed = handoffs.data?.to_me ?? [];
  const day = withoutHandedMeetings(fullDay, new Set(handed.map((row) => row.opportunity.id)));
  const queue = useMyDayHandoffs(handoffs.data, canEdit, day.prep !== null);
  const older = day.counts.older_tasks;
  const line = [
    handed.length > 0 ? plural(handed.length, "przekazane spotkanie", "przekazane spotkania", "przekazanych spotkań") : null,
    dayLine(day),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="space-y-2">
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
        <p className="min-w-0 text-muted-foreground">
          <span className="font-medium text-foreground">{dayHeading(day.today)}:</span> {line}
        </p>
        <div className="flex shrink-0 items-center gap-3">
          {older > 0 && (
            <Link href="/sales/tasks" className="text-xs text-primary hover:underline">
              {plural(older, "starsze zadanie", "starsze zadania", "starszych zadań")}
            </Link>
          )}
          {canEdit && (
            <Button size="sm" className="h-7" data-tour="sales.book-meeting" onClick={() => setBooking(true)}>
              Umów spotkanie
            </Button>
          )}
        </div>
      </div>
      {/* Awaria listy przekazań nie może wyglądać jak brak przekazań. */}
      {handoffs.isError && (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać przekazanych spotkań."
          onRetry={() => void handoffs.refetch()}
        />
      )}
      <MyDayReminders today={day.today} />
      {isDayEmpty(day) && queue.count === 0 ? (
        <div className="rounded-lg border border-border bg-card">
          <EmptyState
            icon={CheckCircle2}
            title="Czysto. Nic pilnego."
            description="Nowe maile, zaległe kroki i spotkania pojawią się tu same."
          />
        </div>
      ) : (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_364px]">
          <div className="min-w-0 space-y-3">
            {queue.count > 0 && (
              <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">{queue.sections}</div>
            )}
            {!isDayEmpty(day) && <DayQueue day={day} canEdit={canEdit} />}
          </div>
          {queue.card ?? (day.prep && <MyDayPrepCard prep={day.prep} canEdit={canEdit} />)}
        </div>
      )}
      {booking && <BookMeetingDialog onClose={() => setBooking(false)} />}
      {queue.dialog}
    </div>
  );
}

/** Kolejka dnia: awaria i wczytywanie mają własny wygląd, pusta kolejka tylko po sukcesie. */
export function MyDayView() {
  const query = useMyDay();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: false,
  });
  if (state === "loading") return <p className="py-6 text-sm text-muted-foreground">Wczytywanie dnia…</p>;
  if (state !== "ready" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "ready" || state === "empty" ? "error" : state}
        onRetry={() => void query.refetch()}
      />
    );
  }
  return <DayContent day={query.data} canEdit={canEdit} />;
}
