"use client";

/**
 * Rutyny (makieta 3 raportu „Tarcza NEXUSA”, 27.11.2026): kalendarz testów
 * i przeglądów oraz tabela rytmu, żeby nic nie zależało od pamięci. Termin
 * następnego przebiegu = wykonanie + rytm; po terminie admini dostają dzwonek
 * i mail. Tygodniowy skan CI odhacza się sam z biegu w GitHub Actions.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl, monthTitlePl, shiftMonth, WEEKDAYS_PL } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import {
  CADENCE_LABEL,
  calendarDays,
  CHIP_TONE,
  SECURITY_OVERVIEW_KEY,
  SECURITY_ROUTINES_KEY,
  type SecurityRoutine,
} from "./security-model";
import { TONE_CHIP } from "./tone";

const STATE_LABEL: Record<SecurityRoutine["state"], { text: string; variant: "success" | "warning" | "danger" }> = {
  ok: { text: "w terminie", variant: "success" },
  soon: { text: "wkrótce", variant: "warning" },
  overdue: { text: "po terminie", variant: "danger" },
};

export interface SecurityRoutinesPanelProps {
  today: string;
}

export function SecurityRoutinesPanel({ today }: SecurityRoutinesPanelProps) {
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const { askReason, confirmDialog } = useConfirmV2();
  const [view, setView] = useState<"week" | "month">("month");
  const [anchor, setAnchor] = useState(today);
  const [doneError, setDoneError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: SECURITY_ROUTINES_KEY,
    queryFn: async () => (await api.get<SecurityRoutine[]>("/api/security/routines")).data,
  });

  const done = useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) =>
      (await api.post<SecurityRoutine>(`/api/security/routines/${id}/done`, { note: note || null })).data,
    onSuccess: (routine) => {
      setDoneError(null);
      showSuccess(`Odhaczone. Następnie: ${formatIsoDatePl(routine.next_due_on)}.`);
      void queryClient.invalidateQueries({ queryKey: SECURITY_ROUTINES_KEY });
      void queryClient.invalidateQueries({ queryKey: SECURITY_OVERVIEW_KEY });
    },
    onError: (error: unknown) => setDoneError(apiErrorMessage(error, "Nie udało się odhaczyć rutyny.")),
  });

  const markDone = async (routine: SecurityRoutine) => {
    const note = await askReason({
      title: `Wykonane dziś: ${routine.title}`,
      description: "Następny termin policzy się od dzisiaj. Notatka jest opcjonalna (np. gdzie jest raport).",
      confirmLabel: "Odhacz",
      field: { label: "Notatka", placeholder: "np. raport w prywatnym artefakcie", minLength: 0, maxLength: 1000 },
    });
    if (note !== null) done.mutate({ id: routine.id, note });
  };

  const shift = (delta: number) => {
    if (view === "month") {
      setAnchor(`${shiftMonth(anchor.slice(0, 7), delta)}-01`);
    } else {
      const [y, m, d] = anchor.split("-").map(Number);
      setAnchor(new Date(Date.UTC(y, m - 1, d + 7 * delta)).toISOString().slice(0, 10));
    }
  };

  if (query.isError) {
    return <QueryStateNotice state="error" onRetry={() => void query.refetch()} />;
  }
  const routines = query.data ?? [];
  const days = calendarDays(routines, anchor, today, view);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button size="icon-sm" variant="ghost" aria-label="Wcześniej" onClick={() => shift(-1)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-36 text-center text-sm font-semibold text-foreground">
            {view === "month" ? monthTitlePl(anchor.slice(0, 7)) : `Tydzień od ${formatIsoDatePl(days[0]?.iso)}`}
          </span>
          <Button size="icon-sm" variant="ghost" aria-label="Później" onClick={() => shift(1)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAnchor(today)}>
            Dziś
          </Button>
        </div>
        <div className="flex gap-1" role="group" aria-label="Widok kalendarza">
          <Button size="sm" variant={view === "week" ? "primary" : "outline"} aria-pressed={view === "week"} onClick={() => setView("week")}>
            Tydzień
          </Button>
          <Button size="sm" variant={view === "month" ? "primary" : "outline"} aria-pressed={view === "month"} onClick={() => setView("month")}>
            Miesiąc
          </Button>
        </div>
      </div>

      <div className="relative overflow-x-auto">
        <div className="grid min-w-[640px] grid-cols-7 gap-1.5" data-testid="security-calendar">
          {WEEKDAYS_PL.map((d) => (
            <span key={d} className="px-2 text-[11px] uppercase tracking-wide text-muted-foreground">
              {d}
            </span>
          ))}
          {days.map((day) => (
            <div
              key={day.iso}
              className={cn(
                "grid min-h-12 content-start gap-0.5 rounded-md border border-border p-1.5 text-[11.5px]",
                !day.inMonth && "opacity-50",
                day.isToday && "border-primary",
              )}
            >
              <span className={cn("tabular-nums text-muted-foreground", day.isToday && "font-semibold text-primary")}>{day.day}</span>
              {day.chips.map((chip) => (
                <span
                  key={`${chip.routineId}-${chip.kind}`}
                  className={cn("truncate rounded px-1.5 py-0.5 font-semibold", TONE_CHIP[CHIP_TONE[chip.kind]])}
                  title={chip.title}
                >
                  {chip.kind === "done" ? "✓ " : ""}
                  {chip.short}
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>

      <section className="rounded-lg border border-border bg-card" aria-labelledby="security-rhythm">
        <h2 id="security-rhythm" className="border-b border-border px-4 py-2 text-sm font-semibold">
          Rytm
        </h2>
        {doneError ? (
          <p role="alert" className="px-4 pt-2 text-xs text-destructive">
            {doneError}
          </p>
        ) : null}
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="sticky left-0 bg-card px-4 py-1.5 font-medium">Rutyna</th>
                <th className="px-4 py-1.5 font-medium">Co ile</th>
                <th className="px-4 py-1.5 font-medium">Kto</th>
                <th className="px-4 py-1.5 font-medium">Ostatnio</th>
                <th className="px-4 py-1.5 font-medium">Następnie</th>
                <th className="px-4 py-1.5 font-medium">
                  <span className="sr-only">Akcja</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {query.isSuccess && routines.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-3 text-muted-foreground">
                    Brak rutyn.
                  </td>
                </tr>
              ) : null}
              {routines.map((r) => (
                <tr key={r.id}>
                  <td className="sticky left-0 bg-card px-4 py-1.5 text-foreground">{r.title}</td>
                  <td className="px-4 py-1.5 text-muted-foreground">{CADENCE_LABEL[r.cadence]}</td>
                  <td className="px-4 py-1.5 text-muted-foreground">{r.owner_label}</td>
                  <td className="px-4 py-1.5 text-muted-foreground" title={r.last_note ?? undefined}>
                    {formatIsoDatePl(r.last_done_on)}
                  </td>
                  <td className="px-4 py-1.5">
                    <span className="mr-2 tabular-nums text-foreground">{formatIsoDatePl(r.next_due_on)}</span>
                    <Badge variant={STATE_LABEL[r.state].variant}>{STATE_LABEL[r.state].text}</Badge>
                  </td>
                  <td className="px-4 py-1.5 text-right">
                    {r.automatic ? (
                      <span className="text-xs text-muted-foreground">sam z CI</span>
                    ) : (
                      <Button size="sm" variant="outline" disabled={done.isPending} onClick={() => void markDone(r)}>
                        Zrobione
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {confirmDialog}
    </div>
  );
}
