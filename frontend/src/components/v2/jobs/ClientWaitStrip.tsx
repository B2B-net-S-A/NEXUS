"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  clientWaitKey,
  fetchClientWait,
  peopleLabel,
  workdaysLabel,
  type ClientWaitPerson,
} from "@/lib/api/clientWait";
import { BOARD_COLUMN_LABEL } from "@/lib/board-stages";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { ClientReminderDialog } from "./ClientReminderDialog";

const PANEL_TONE: Record<ClientWaitPerson["panel_state"], string> = {
  off: "border-border text-muted-foreground",
  unseen: "border-border text-muted-foreground",
  viewed: "border-info/40 bg-info-muted text-info-muted-foreground",
  interview: "border-success/40 bg-success-muted text-success-muted-foreground",
  not_fit: "border-border bg-muted text-muted-foreground",
};

function PersonRow({ jobId, person }: { jobId: number; person: ClientWaitPerson }) {
  return (
    <li className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1.4fr)] items-center gap-3 px-3 py-1.5 text-sm">
      <div className="min-w-0">
        <Link href={`/jobs/${jobId}?candidate=${person.candidate_id}`} className="truncate font-medium hover:underline">
          {person.name}
        </Link>
        {person.added_by ? (
          <p className="truncate text-xs text-muted-foreground">Dodał(a): {person.added_by}</p>
        ) : null}
      </div>
      <p className="min-w-0 text-xs text-muted-foreground">
        {BOARD_COLUMN_LABEL[person.column]} od {formatDayMonthPl(person.entered_at)}
        <br />
        <span className="font-medium text-foreground">{workdaysLabel(person.workdays)}</span>
        {person.reminded_at ? ` · przygotowano przypomnienie ${formatDayMonthPl(person.reminded_at)}` : ""}
      </p>
      <span
        className={cn(
          "w-fit max-w-full truncate rounded-full border px-2 py-0.5 text-xs",
          PANEL_TONE[person.panel_state],
        )}
        title={person.panel_label}
      >
        {person.panel_label}
      </span>
    </li>
  );
}

/**
 * Pas nad Tablicą (S-C2, 08.11.2026): ile osób czeka na klienta ponad 5 dni
 * roboczych, kto najdłużej, lista i gotowa wiadomość. Awaria to komunikat,
 * nie brak pasa: pustka czytałaby się jak „nikt nie czeka”.
 */
export function ClientWaitStrip({ jobId }: { jobId: number }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [reminderOpen, setReminderOpen] = useState(false);
  const query = useQuery({
    queryKey: clientWaitKey(jobId),
    queryFn: () => fetchClientWait(jobId),
    staleTime: 60_000,
    retry: 1,
  });

  if (query.isError) {
    return (
      <div
        role="alert"
        data-testid="client-wait-error"
        className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-2 text-sm text-destructive"
      >
        <p className="min-w-0 flex-1">
          {apiErrorMessage(query.error, "Nie udało się sprawdzić, kto czeka na odpowiedź klienta.")}
        </p>
        <Button type="button" size="sm" variant="outline" onClick={() => void query.refetch()}>
          Spróbuj ponownie
        </Button>
      </div>
    );
  }
  const wait = query.data;
  if (!query.isSuccess || !wait || wait.count === 0) return null;

  const needing = wait.people.filter((person) => person.needs_action);
  return (
    <section
      data-testid="client-wait-strip"
      data-tour="job.client-wait"
      className="mb-3 rounded-lg border border-warning/40 bg-warning-muted text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2">
        <p className="min-w-0 flex-1 text-warning-muted-foreground">
          <strong>Czeka na odpowiedź klienta: {peopleLabel(wait.count)}</strong> · najdłużej{" "}
          {workdaysLabel(wait.longest_workdays)}
          {wait.auto_close && wait.nearest_close_in != null ? (
            <span className="block text-xs">
              NEXUS sam zamknie po {wait.auto_close_days} dniach: najbliższe za{" "}
              {Math.max(0, wait.nearest_close_in)} dni
            </span>
          ) : null}
        </p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Ukryj osoby" : "Pokaż osoby"}
        </Button>
        <Button type="button" size="sm" onClick={() => setReminderOpen(true)}>
          Przypomnij klientowi
        </Button>
      </div>
      {expanded ? (
        <ul className="max-h-[40dvh] divide-y divide-border overflow-y-auto border-t border-warning/40 bg-card">
          {needing.map((person) => (
            <PersonRow key={person.candidate_id} jobId={jobId} person={person} />
          ))}
        </ul>
      ) : null}
      <ClientReminderDialog
        open={reminderOpen}
        onOpenChange={setReminderOpen}
        jobId={jobId}
        onPrepared={() => void queryClient.invalidateQueries({ queryKey: clientWaitKey(jobId) })}
      />
    </section>
  );
}
