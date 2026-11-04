"use client";

/**
 * „Osoby od systemu czekają na decyzję” w „Czeka na Ciebie” (makieta B1,
 * 23.10.2026). Silnik „Nowi na 20” dodaje osoby bez blokady; po 2 dniach
 * roboczych bez „Dzwonię” ani odrzucenia osoba trafia tutaj (serwer:
 * `board_flow._autofill_decisions`, reguła terminu wspólna z Tablicą).
 * Akcje:
 *  - „Dzwonię” — `POST /api/pipeline/claim` (blokada 12 h i decyzja na stałe),
 *  - „Otwórz” — panel osoby na Tablicy, gdzie jest „Odrzuć z powodem”.
 * Obsłużona osoba znika od razu; odświeżenie kolejki dogania w tle.
 */

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_TASKS_QUERY_KEY, type FlowAutofillDecision } from "@/lib/api/boardTasks";
import { workdaysText } from "@/lib/board-card-badges";

import { Section } from "./BoardTasksSection";

function key(row: Pick<FlowAutofillDecision, "job_id" | "candidate_id">): string {
  return `${row.job_id}-${row.candidate_id}`;
}

/** Panel osoby na Tablicy rekrutacji. */
export function autofillPersonHref(row: Pick<FlowAutofillDecision, "job_id" | "candidate_id">): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function jobLabel(row: FlowAutofillDecision): string {
  return row.job_working_title?.trim() || row.job_title;
}

/** Wiersze bez osób obsłużonych w tej sesji. */
export function withoutDecided(
  rows: readonly FlowAutofillDecision[],
  handled: ReadonlySet<string>,
): FlowAutofillDecision[] {
  return rows.filter((row) => !handled.has(key(row)));
}

export function BoardAutofillDecisions({
  rows,
  total,
  expanded,
  onToggle,
  shown,
}: {
  rows: FlowAutofillDecision[] | null | undefined;
  total: number;
  expanded: boolean;
  onToggle: () => void;
  shown: <T>(kind: string, rows: T[]) => T[];
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [handled, setHandled] = useState<ReadonlySet<string>>(new Set());

  const call = useMutation({
    mutationFn: (row: FlowAutofillDecision) =>
      api.post("/api/pipeline/claim", { candidate_id: row.candidate_id, job_id: row.job_id }),
    onSuccess: (_data, row) => {
      setHandled((prev) => new Set([...prev, key(row)]));
      showSuccess(`Dzwonisz do: ${row.candidate_name} — masz 12 h.`);
      void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(row.job_id)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", row.job_id] });
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się wziąć tej osoby.")),
  });

  const visible = withoutDecided(rows ?? [], handled);
  if (visible.length === 0) return null;
  const left = Math.max(total - handled.size, visible.length);

  return (
    <Section
      title="Osoby od systemu czekają na decyzję"
      hint="System dodał je do „Nowych” ponad 2 dni robocze temu. Zadzwoń albo otwórz i odrzuć z powodem — powody uczą system."
      count={left}
      rows={visible.length}
      expanded={expanded}
      onToggle={onToggle}
    >
      {shown("flow_autofill_decisions", visible).map((row) => (
        <li
          key={key(row)}
          className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2"
          data-testid="autofill-decision-row"
        >
          <div className="min-w-[10rem] flex-1">
            <Link href={autofillPersonHref(row)} className="block truncate text-sm font-medium hover:underline">
              {row.candidate_name}
            </Link>
            <p className="truncate text-xs text-muted-foreground">
              {jobLabel(row)}
              {row.client_name ? ` · ${row.client_name}` : ""}
            </p>
          </div>
          {typeof row.score === "number" ? (
            <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
              {row.score}%
            </span>
          ) : null}
          <span className="shrink-0 rounded-full bg-warning-muted px-2 py-0.5 text-xs font-semibold text-warning-muted-foreground">
            {workdaysText(row.waiting_days)}
          </span>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              size="sm"
              disabled={call.isPending}
              aria-label={`Dzwonię do ${row.candidate_name} — biorę na 12 h`}
              onClick={() => call.mutate(row)}
            >
              Dzwonię
            </Button>
            <Button size="sm" variant="quiet" asChild>
              <Link href={autofillPersonHref(row)} aria-label={`Otwórz ${row.candidate_name} na Tablicy`}>
                Otwórz
              </Link>
            </Button>
          </div>
        </li>
      ))}
    </Section>
  );
}
