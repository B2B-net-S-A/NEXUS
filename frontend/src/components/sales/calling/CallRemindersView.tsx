"use client";

import { BellRing } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  useCallReminders,
  type CallRecordScope,
  type QueueItem,
} from "@/lib/api/sales-calling";
import { formatWeekdayDayPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { CallCard, type MeetingStage } from "./CallCard";
import {
  nextKey,
  plusDaysIso,
  reminderGroups,
  STATE_TONES,
  stateLabel,
} from "./calling";

interface CallRemindersViewProps {
  today: string;
  canEdit: boolean;
  meetingStage: MeetingStage | null;
}

/**
 * Dzwonienie → „Przypomnienia” (decyzja Artura 13.11.2026): terminy powrotów
 * („Oddzwonić”, oferta z ponownym kontaktem) po dniach, bez nowej tabeli w bazie.
 * Klik otwiera tę samą kartę rozmowy co kolejka.
 */
export function CallRemindersView({
  today,
  canEdit,
  meetingStage,
}: CallRemindersViewProps) {
  const [scope, setScope] = useState<CallRecordScope>("mine");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const query = useCallReminders(scope);
  const items = query.data ?? [];
  const selected = items.find((item) => item.key === selectedKey) ?? null;
  const upcomingKey = selected ? nextKey(items, selected.key) : null;
  const upcoming = items.find((item) => item.key === upcomingKey) ?? null;
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: items.length === 0,
  });
  const groups = reminderGroups(items, today, plusDaysIso(today, 1));

  return (
    <div className="space-y-2">
      <SegmentedRadio
        size="sm"
        label="Czyje przypomnienia"
        options={[
          { value: "mine", label: "Moje" },
          { value: "all", label: "Wszyscy" },
        ]}
        value={scope}
        onChange={(value) => {
          setScope(value as CallRecordScope);
          setSelectedKey(null);
        }}
      />
      {viewState === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">
          Wczytywanie przypomnień…
        </p>
      ) : viewState === "empty" ? (
        <div className="rounded-lg border border-border bg-card">
          <EmptyState
            icon={BellRing}
            title="Brak przypomnień."
            description="Pojawią się tu rekordy z terminem: „Oddzwonić” i oferta z ponownym kontaktem."
          />
        </div>
      ) : viewState !== "ready" ? (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_364px]">
          <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
            {groups.map((group) => (
              <section key={group.title} aria-label={group.title}>
                <header className="flex items-baseline justify-between gap-3 border-b border-border bg-muted/40 px-3 py-1">
                  <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {group.title}
                  </h2>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {group.items.length}
                  </span>
                </header>
                <ul className="divide-y divide-border border-b border-border">
                  {group.items.map((item) => (
                    <ReminderRow
                      key={item.key}
                      item={item}
                      showCaller={scope === "all"}
                      active={selected?.key === item.key}
                      onSelect={() => setSelectedKey(item.key)}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </div>
          {selected && (
            <div className="lg:sticky lg:top-2 lg:max-h-[calc(100dvh-1rem)] lg:overflow-y-auto">
              <CallCard
                key={selected.key}
                item={selected}
                position={`${items.indexOf(selected) + 1} z ${items.length}`}
                today={today}
                nextCompany={upcoming?.company.name ?? null}
                canEdit={canEdit}
                meetingStage={meetingStage}
                onSaved={() => setSelectedKey(upcomingKey)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ReminderRowProps {
  item: QueueItem;
  showCaller: boolean;
  active: boolean;
  onSelect: () => void;
}

function ReminderRow({ item, showCaller, active, onSelect }: ReminderRowProps) {
  return (
    <li>
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex min-h-11 w-full items-center gap-2 px-3 py-1 text-left hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          active && "bg-primary/10 shadow-[inset_3px_0_0_hsl(var(--primary))]",
        )}
        onClick={onSelect}
      >
        <span className="w-16 shrink-0 text-xs tabular-nums text-muted-foreground">
          {item.due_on ? formatWeekdayDayPl(item.due_on) : "—"}
        </span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-sm font-medium text-foreground">
            {item.company.name}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {[item.person_name, showCaller ? item.assignee?.name : null]
              .filter(Boolean)
              .join(" · ") || "Bez wskazanej osoby"}
          </span>
        </span>
        <Badge
          variant={STATE_TONES[item.state]}
          size="sm"
          className="shrink-0 whitespace-nowrap"
        >
          {stateLabel(item.state)}
        </Badge>
      </button>
    </li>
  );
}
