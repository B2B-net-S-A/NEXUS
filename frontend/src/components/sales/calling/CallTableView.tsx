"use client";

import { PhoneCall, Search } from "lucide-react";
import { useDeferredValue, useEffect, useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCallRecords, type QueueItem, type RecordState } from "@/lib/api/sales-calling";
import { formatWeekdayDayPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { CallCard, type MeetingStage } from "./CallCard";
import { nextKey, STATE_TONES, stateLabel, TABLE_STATES, weekdayOf } from "./calling";

interface CallTableViewProps {
  today: string;
  campaignId: number | null;
  canEdit: boolean;
  meetingStage: MeetingStage | null;
}

/**
 * Dzwonienie → „Tabela” (decyzja Artura 11.11.2026): ta sama lista co kolejka, ale cała,
 * z filtrem po wyniku i kolorami jak w legendzie Excela. Klik w wiersz otwiera tę samą
 * kartę rozmowy z tymi samymi wynikami i klawiszami.
 */
export function CallTableView({ today, campaignId, canEdit, meetingStage }: CallTableViewProps) {
  const [state, setState] = useState<RecordState | null>(null);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const query = useCallRecords({ state, campaignId, search: deferredSearch });
  const items = query.data?.items ?? [];
  const selected = items.find((item) => item.key === selectedKey) ?? null;
  const upcomingKey = selected ? nextKey(items, selected.key) : null;
  const upcoming = items.find((item) => item.key === upcomingKey) ?? null;

  // Zmiana filtra czyści wybór, gdy wybranego wiersza nie ma już na liście.
  useEffect(() => {
    if (selectedKey !== null && query.isSuccess && !selected) setSelectedKey(null);
  }, [query.isSuccess, selected, selectedKey]);

  const counts = query.data?.counts ?? {};
  const all = TABLE_STATES.reduce((sum, key) => sum + (counts[key] ?? 0), 0);
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: items.length === 0,
  });

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <div role="group" aria-label="Wynik" className="flex flex-wrap items-center gap-1.5">
          <FilterChip active={state === null} label="Wszyscy" count={all} onClick={() => setState(null)} />
          {TABLE_STATES.filter((key) => (counts[key] ?? 0) > 0 || state === key).map((key) => (
            <FilterChip
              key={key}
              active={state === key}
              label={stateLabel(key)}
              count={counts[key] ?? 0}
              onClick={() => setState(state === key ? null : key)}
            />
          ))}
        </div>
        <label className="relative ml-auto w-full sm:w-56">
          <span className="sr-only">Szukaj firmy, osoby albo numeru</span>
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            className="h-7 pl-7 text-xs"
            placeholder="Firma, osoba, numer"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>
      {viewState === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie listy…</p>
      ) : viewState === "empty" ? (
        <div className="rounded-lg border border-border bg-card">
          <EmptyState
            icon={PhoneCall}
            title={state || search ? "Nikt nie pasuje do filtra." : "Nie masz jeszcze nikogo na liście."}
            description={
              state || search
                ? "Zmień wynik albo wyczyść wyszukiwanie."
                : "Osoby trafiają tu z importu listy do kampanii i z wyników kolejki."
            }
          />
        </div>
      ) : viewState !== "ready" ? (
        <QueryStateNotice state={viewState} onRetry={() => void query.refetch()} />
      ) : (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_364px]">
          <div className="min-w-0 overflow-x-auto rounded-lg border border-border bg-card">
            <RecordTable items={items} today={today} selectedKey={selected?.key ?? null} onSelect={setSelectedKey} />
            {query.data && query.data.total > items.length && (
              <p className="border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
                Pokazano {items.length} z {query.data.total}. Zawęź filtr albo wyszukiwanie.
              </p>
            )}
          </div>
          {selected ? (
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
          ) : (
            <p className="hidden rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground lg:block">
              Kliknij osobę w tabeli: obok otworzy się karta rozmowy z wynikami (klawisze 1–7).
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return (
    <Button size="sm" variant={active ? "primary" : "outline"} className="h-7 px-2" aria-pressed={active} onClick={onClick}>
      {label}
      <span className="ml-1 tabular-nums opacity-70">{count}</span>
    </Button>
  );
}

function returnLabel(item: QueueItem, today: string): string {
  if (!item.due_on) return item.state === "not_interested" ? "nigdy" : "—";
  if (item.due_on <= today) return "dziś";
  return formatWeekdayDayPl(item.due_on);
}

function RecordTable({
  items,
  today,
  selectedKey,
  onSelect,
}: {
  items: QueueItem[];
  today: string;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  return (
    <table className="w-full text-xs">
      <thead className="border-b border-border bg-muted/40 text-muted-foreground">
        <tr>
          {["Firma", "Osoba", "Telefon", "Wynik", "Powrót"].map((header) => (
            <th key={header} scope="col" className="whitespace-nowrap px-2 py-1.5 text-left font-medium">
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {items.map((item) => (
          <tr
            key={item.key}
            aria-selected={selectedKey === item.key}
            className={cn("cursor-pointer hover:bg-muted/50", selectedKey === item.key && "bg-primary/5")}
            onClick={() => onSelect(item.key)}
          >
            <td className="max-w-36 px-2 py-1.5">
              <button
                type="button"
                className="block max-w-full truncate text-left font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(item.key);
                }}
              >
                {item.company.name}
              </button>
            </td>
            <td className="max-w-36 px-2 py-1.5">
              <span className="block truncate text-foreground">{item.person_name ?? "—"}</span>
              {item.person_title && <span className="block truncate text-muted-foreground">{item.person_title}</span>}
            </td>
            <td className="whitespace-nowrap px-2 py-1.5 tabular-nums text-muted-foreground">{item.phone ?? "brak"}</td>
            <td className="px-2 py-1.5">
              <Badge variant={STATE_TONES[item.state]} size="sm" className="whitespace-nowrap">
                {stateLabel(item.state)}
              </Badge>
            </td>
            <td
              className="whitespace-nowrap px-2 py-1.5 text-muted-foreground"
              title={item.last_outcome_at ? `Ostatnio ${weekdayOf(item.last_outcome_at)}, prób: ${item.attempts}` : undefined}
            >
              {returnLabel(item, today)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
