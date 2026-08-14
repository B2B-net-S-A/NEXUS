"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, History, Pencil, Plus, Repeat } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { orderGroupsApi, type OrderGroupRead, type OrderLineRead } from "@/lib/api/orderGroups";
import { formatDate, formatPLN } from "@/types/client-profile";

import { MdBudgetBar } from "./MdBudgetBar";

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

function periodLabel(group: OrderGroupRead): string {
  const from = formatDate(group.start_date);
  const to = group.end_date ? formatDate(group.end_date) : "bezterminowo";
  return `${from} → ${to}`;
}

interface Props {
  clientId: number;
  group: OrderGroupRead;
  canManage: boolean;
  onAddConsultant: (group: OrderGroupRead) => void;
  onEditGroup: (group: OrderGroupRead) => void;
  onEditLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onSwapLine: (group: OrderGroupRead, line: OrderLineRead) => void;
}

export function OrderGroupCard({
  clientId,
  group,
  canManage,
  onAddConsultant,
  onEditGroup,
  onEditLine,
  onSwapLine,
}: Props) {
  const [expanded, setExpanded] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);

  const history = useQuery({
    queryKey: ["order-group-events", clientId, group.id],
    queryFn: async () => (await orderGroupsApi.events(clientId, group.id)).data,
    enabled: historyOpen,
  });

  const activeLines = group.lines.filter((l) => l.is_active);

  return (
    <section className="rounded-xl border border-border bg-card">
      {/* Nagłówek karty — numer, okres, awatary konsultantów */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-4 px-5 py-4 text-left"
      >
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">
            Zamówienie nr {group.order_number}
          </p>
          <p className="text-xs text-muted-foreground">{periodLabel(group)}</p>
        </div>

        <div className="flex -space-x-2">
          {activeLines.slice(0, 5).map((line) => (
            <Avatar
              key={line.id}
              className="h-7 w-7 border-2 border-card"
              title={line.consultant_name}
            >
              <AvatarFallback className="bg-primary/10 text-[10px] font-semibold text-primary">
                {initials(line.consultant_name)}
              </AvatarFallback>
            </Avatar>
          ))}
          {activeLines.length > 5 ? (
            <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-card bg-muted text-[10px] font-semibold text-muted-foreground">
              +{activeLines.length - 5}
            </span>
          ) : null}
        </div>

        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>

      {expanded ? (
        <div className="border-t border-border px-5 py-4">
          {group.lines.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              To zamówienie nie ma jeszcze konsultantów.
            </p>
          ) : (
            <ul className="flex flex-col divide-y divide-border">
              {group.lines.map((line) => (
                <li
                  key={line.id}
                  className={cn(
                    "flex flex-wrap items-center gap-x-6 gap-y-3 py-3",
                    !line.is_active && "opacity-60",
                  )}
                >
                  <div className="flex min-w-[13rem] flex-1 items-center gap-3">
                    <Avatar className="h-8 w-8">
                      <AvatarFallback className="bg-primary/10 text-[11px] font-semibold text-primary">
                        {initials(line.consultant_name)}
                      </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {line.consultant_name}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {line.is_active ? "Konsultant" : "Zakończony"}
                        {line.start_date ? ` · od ${formatDate(line.start_date)}` : ""}
                        {!line.is_active && line.end_date
                          ? ` do ${formatDate(line.end_date)}`
                          : ""}
                      </p>
                      {line.predecessor_consultant_name ? (
                        <p className="truncate text-xs text-muted-foreground">
                          zastąpił: {line.predecessor_consultant_name}
                        </p>
                      ) : null}
                    </div>
                  </div>

                  {/* Stawki — „—" gdy rola nie ma uprawnień finansowych.
                      Zniknięcie kolumny zostawiłoby pustkę bez wyjaśnienia. */}
                  <div className="min-w-[8rem]">
                    <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      Stawka kosztowa
                    </p>
                    <p className="text-sm font-medium text-foreground">
                      {line.rate_cost === null ? "—" : `${formatPLN(line.rate_cost)}/MD`}
                    </p>
                  </div>
                  <div className="min-w-[8rem]">
                    <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      Stawka przychodowa
                    </p>
                    <p className="text-sm font-medium text-foreground">
                      {line.rate_revenue === null
                        ? "—"
                        : `${formatPLN(line.rate_revenue)}/MD`}
                    </p>
                  </div>

                  <MdBudgetBar
                    remaining={line.md_remaining}
                    total={line.md_total}
                    className="ml-auto"
                  />

                  {canManage ? (
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => onEditLine(group, line)}
                        aria-label={`Edytuj linię — ${line.consultant_name}`}
                        title="Edytuj linię"
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        <Pencil className="h-4 w-4" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => onSwapLine(group, line)}
                        disabled={!line.is_active}
                        aria-label={`Zamień kontraktora — ${line.consultant_name}`}
                        title={
                          line.is_active
                            ? "Zamień kontraktora"
                            : "Zamienić można tylko aktywną linię"
                        }
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Repeat className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}

          {canManage ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onAddConsultant(group)}
                className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/5"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj konsultanta do
                zamówienia
              </button>
              <button
                type="button"
                onClick={() => onEditGroup(group)}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Edytuj zamówienie
              </button>
            </div>
          ) : null}

          <div className="mt-4 border-t border-border pt-3">
            <button
              type="button"
              onClick={() => setHistoryOpen((v) => !v)}
              aria-expanded={historyOpen}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
            >
              <History className="h-3.5 w-3.5" aria-hidden="true" />
              Historia zamówienia ({group.event_count}{" "}
              {group.event_count === 1 ? "wpis" : "wpisy"})
              <ChevronDown
                className={cn("h-3 w-3 transition-transform", historyOpen && "rotate-180")}
                aria-hidden="true"
              />
            </button>

            {historyOpen ? (
              <div className="mt-3">
                {history.isError ? (
                  // Awaria pobrania NIE może wyglądać jak „brak historii" —
                  // pusta lista czytałaby się jak utrata zapisów.
                  <QueryStateNotice
                    state="error"
                    description="Nie udało się wczytać historii tego zamówienia."
                    onRetry={() => history.refetch()}
                  />
                ) : !history.isSuccess ? (
                  // Warunek na `isSuccess`, a NIE `isLoading`: między ponowieniami
                  // react-query ma `isLoading === false`, `isError === false`
                  // i puste `data`, więc gałąź „brak wpisów" wygrywała i ekran
                  // twierdził, że historia jest pusta, zanim cokolwiek wiadomo.
                  <p className="text-xs text-muted-foreground">Wczytywanie historii…</p>
                ) : history.data.events.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Brak wpisów w historii.</p>
                ) : (
                  <ol className="flex flex-col gap-2">
                    {history.data.events.map((ev) => (
                      <li key={ev.id} className="flex gap-3 text-xs">
                        <span className="w-28 shrink-0 tabular-nums text-muted-foreground">
                          {formatDate(ev.created_at)}
                        </span>
                        <span className="w-36 shrink-0 font-medium text-foreground">
                          {ev.event_label}
                        </span>
                        <span className="text-muted-foreground">{ev.description}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
