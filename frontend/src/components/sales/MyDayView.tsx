"use client";

import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useMyDay, type MyDay, type MyDayRow, type MyDaySectionKey } from "@/lib/api/sales";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { dayHeading, dayLine, isDayEmpty, OFFERS_PREVIEW, plural } from "./my-day";
import { MyDayPrepCard } from "./MyDayPrepCard";
import { MyDayRowItem } from "./MyDayRowItem";

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
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
      {SECTIONS.filter((section) => day[section.key].length > 0).map((section) => (
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
      ))}
    </div>
  );
}

function DayContent({ day, canEdit }: { day: MyDay; canEdit: boolean }) {
  const older = day.counts.older_tasks;
  return (
    <div className="space-y-2">
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-4 text-sm">
        <p className="min-w-0 text-muted-foreground">
          <span className="font-medium text-foreground">{dayHeading(day.today)}:</span> {dayLine(day)}
        </p>
        {older > 0 && (
          <Link href="/sales/tasks" className="shrink-0 text-xs text-primary hover:underline">
            {plural(older, "starsze zadanie", "starsze zadania", "starszych zadań")}
          </Link>
        )}
      </div>
      {isDayEmpty(day) ? (
        <div className="rounded-lg border border-border bg-card">
          <EmptyState
            icon={CheckCircle2}
            title="Czysto. Nic pilnego."
            description="Nowe maile, zaległe kroki i spotkania pojawią się tu same."
          />
        </div>
      ) : (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_364px]">
          <DayQueue day={day} canEdit={canEdit} />
          {day.prep && <MyDayPrepCard prep={day.prep} canEdit={canEdit} />}
        </div>
      )}
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
