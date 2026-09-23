"use client";

/**
 * „Czeka na Ciebie" — praca na Tablicach, której nikt nie widzi (0348).
 *
 * Trzy listy z `GET /api/board-tasks`:
 *  - „Czeka na DZ" — osoby w „Zweryfikowany" bez odznaki DZ; „✓ DZ" to ten
 *    sam ruch co przełącznik w doku (`POST /api/pipeline/move` z wersją
 *    procesu), więc ostrzeżenia i konflikty działają jak na Tablicy,
 *  - „Do wysłania do Cpro" (Nordea) — z wytypowaną osobą; zmiana osoby jednym
 *    wyborem, a „Oznacz wysłanie" otwiera dok na Tablicy (stawka do klienta),
 *  - „Wysłane do Cpro" — od ilu dni czekamy na Nordeę.
 *
 * Panel nie renderuje się, gdy nic nie czeka — pusta ramka uczyłaby go
 * ignorować. Kotwica `#czeka-na-ciebie` = link z porannego dzwonka.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  BOARD_TASKS_QUERY_KEY,
  assigneeLabel,
  setCproAssignee,
  useBoardTasks,
  useCproAssigneeOptions,
  waitingFor,
  type BoardTaskRow,
} from "@/lib/api/boardTasks";
import { isEligibilityWarning, eligibilityWarningReason } from "@/lib/pipeline-eligibility-warning";
import {
  PIPELINE_VERSION_CONFLICT_MESSAGE,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";
import { useAuthStore } from "@/store/auth";

export const BOARD_TASKS_ANCHOR = "czeka-na-ciebie";

function boardLink(row: BoardTaskRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function RowMeta({ row }: { row: BoardTaskRow }) {
  return (
    <p className="truncate text-xs text-muted-foreground">
      {row.job_title}
      {row.client_name ? ` · ${row.client_name}` : ""}
    </p>
  );
}

/** Tyle wierszy na listę, zanim trzeba kliknąć „Pokaż wszystkie" — na produkcji
 *  „Wysłane do Cpro" liczyło 98 osób, a panel stoi NAD pulpitem. */
export const BOARD_TASKS_ROWS = 6;

interface SectionProps {
  title: string;
  hint: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function Section({ title, hint, count, expanded, onToggle, children }: SectionProps) {
  return (
    <section aria-label={title} className="min-w-0">
      <header className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {count}
        </span>
      </header>
      <p className="mb-2 text-xs text-muted-foreground">{hint}</p>
      <ul className="divide-y divide-border rounded-lg border border-border">{children}</ul>
      {count > BOARD_TASKS_ROWS && (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${count})`}
        </button>
      )}
    </section>
  );
}

export function BoardTasksPanel() {
  const query = useBoardTasks();
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const me = useAuthStore((s) => s.user);
  const [busy, setBusy] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const toggle = (kind: string) => setExpanded((prev) => ({ ...prev, [kind]: !prev[kind] }));
  const shown = <T,>(kind: string, rows: T[]): T[] =>
    expanded[kind] ? rows : rows.slice(0, BOARD_TASKS_ROWS);
  const data = query.data;
  const hasCpro = (data?.cpro_to_send.length ?? 0) > 0;
  const options = useCproAssigneeOptions(hasCpro);
  // Link z porannego dzwonka (`/dashboard#czeka-na-ciebie`): panel pojawia się
  // dopiero po odczycie kolejki, więc przeglądarka sama do niego nie przewinie.
  const scrolled = useRef(false);
  useEffect(() => {
    if (scrolled.current || !data || typeof window === "undefined") return;
    if (window.location.hash !== `#${BOARD_TASKS_ANCHOR}`) return;
    scrolled.current = true;
    document.getElementById(BOARD_TASKS_ANCHOR)?.scrollIntoView({ block: "start" });
  }, [data]);

  if (!data) return null;
  const total = data.dz.length + data.cpro_to_send.length + data.cpro_sent.length;
  if (total === 0) return null;

  const refresh = (jobId: number) => {
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  };

  const approveDz = async (row: BoardTaskRow) => {
    if (row.target_stage_def_id == null) return;
    setBusy(row.stage_id);
    try {
      await api.post("/api/pipeline/move", {
        candidate_id: row.candidate_id,
        job_id: row.job_id,
        stage_def_id: row.target_stage_def_id,
        expected_state_version: row.process_state_version,
      });
      showSuccess(`${row.candidate_name} — zatwierdzony przez DZ.`);
    } catch (error) {
      if (isEligibilityWarning(error)) {
        // Ostrzeżenie dopuszczalności ma swoje okno na Tablicy — tam decyzja.
        showError(
          `${eligibilityWarningReason(error) ?? "Serwer ostrzega przed tym ruchem."} Otwórz osobę na Tablicy, żeby zdecydować.`
        );
      } else if (isPipelineVersionConflict(error)) {
        showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
      } else {
        showError(apiErrorMessage(error, "Nie udało się zatwierdzić. Spróbuj ponownie."));
      }
    } finally {
      setBusy(null);
      refresh(row.job_id);
    }
  };

  const reassign = async (row: BoardTaskRow, assigneeId: number) => {
    setBusy(row.stage_id);
    try {
      const res = await setCproAssignee(row.stage_id, assigneeId);
      showSuccess(
        `Wysyła: ${res.assignee_name ?? "wybrana osoba"}${res.added_to_team ? " (dodana do zespołu rekrutacji)" : ""}.`
      );
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić osoby. Spróbuj ponownie."));
    } finally {
      setBusy(null);
      refresh(row.job_id);
    }
  };

  return (
    <div
      id={BOARD_TASKS_ANCHOR}
      role="region"
      aria-label="Czeka na Ciebie"
      className="scroll-mt-20 rounded-xl border border-primary/30 bg-card p-4"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">Czeka na Ciebie</h2>
        <p className="text-xs text-muted-foreground">
          Ruchy na Tablicach z ostatnich {data.window_days} dni · najdłużej czekający na górze
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {data.dz.length > 0 && (
          <Section
            title="Czeka na DZ"
            hint="Zweryfikowani bez zatwierdzenia DZ."
            count={data.dz.length}
            expanded={expanded["dz"] === true}
            onToggle={() => toggle("dz")}
          >
            {shown("dz", data.dz).map((row) => (
              <li key={row.stage_id} className="flex items-center gap-2 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <Link href={boardLink(row)} className="block truncate text-sm font-medium hover:underline">
                    {row.candidate_name}
                  </Link>
                  <RowMeta row={row} />
                </div>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {waitingFor(row.since)}
                </span>
                {data.can_approve_dz && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    disabled={busy === row.stage_id || row.target_stage_def_id == null}
                    onClick={() => void approveDz(row)}
                    aria-label={`Zatwierdź przez DZ: ${row.candidate_name}`}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    DZ
                  </Button>
                )}
              </li>
            ))}
          </Section>
        )}

        {data.cpro_to_send.length > 0 && (
          <Section
            title="Do wysłania do Cpro"
            hint="Gotowi do Cpro — wysyła wytypowana osoba."
            count={data.cpro_to_send.length}
            expanded={expanded["cpro_to_send"] === true}
            onToggle={() => toggle("cpro_to_send")}
          >
            {shown("cpro_to_send", data.cpro_to_send).map((row) => (
              <li key={row.stage_id} className="flex flex-col gap-1.5 px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <Link href={boardLink(row)} className="block truncate text-sm font-medium hover:underline">
                      {row.candidate_name}
                    </Link>
                    <RowMeta row={row} />
                  </div>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {waitingFor(row.since)}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <label className="sr-only" htmlFor={`cpro-assignee-${row.stage_id}`}>
                    Kto wysyła do Cpro: {row.candidate_name}
                  </label>
                  <select
                    id={`cpro-assignee-${row.stage_id}`}
                    className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs"
                    value={row.assignee_id ?? ""}
                    disabled={busy === row.stage_id || options.isLoading}
                    onChange={(e) => {
                      if (e.target.value) void reassign(row, Number(e.target.value));
                    }}
                  >
                    {row.assignee_id == null && <option value="">Nikt nie wytypowany — wybierz</option>}
                    {row.assignee_id != null &&
                      !(options.data ?? []).some((o) => o.id === row.assignee_id) && (
                        <option value={row.assignee_id}>{row.assignee_name ?? "Wytypowana osoba"}</option>
                      )}
                    {(options.data ?? []).map((o) => (
                      <option key={o.id} value={o.id}>
                        Wysyła: {assigneeLabel(o)}
                        {o.id === me?.id ? " (ja)" : ""}
                      </option>
                    ))}
                  </select>
                  {row.assignee_id === me?.id && (
                    <Button asChild size="sm" className="shrink-0">
                      <Link href={boardLink(row)}>
                        <Send className="h-3.5 w-3.5" />
                        Oznacz wysłanie
                      </Link>
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </Section>
        )}

        {data.cpro_sent.length > 0 && (
          <Section
            title="Wysłane do Cpro"
            hint="Czekamy na odpowiedź Nordei."
            count={data.cpro_sent.length}
            expanded={expanded["cpro_sent"] === true}
            onToggle={() => toggle("cpro_sent")}
          >
            {shown("cpro_sent", data.cpro_sent).map((row) => (
              <li key={row.stage_id} className="flex items-center gap-2 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <Link href={boardLink(row)} className="block truncate text-sm font-medium hover:underline">
                    {row.candidate_name}
                  </Link>
                  <RowMeta row={row} />
                </div>
                <span className="inline-flex shrink-0 items-center gap-1 text-xs tabular-nums text-muted-foreground">
                  <Clock className="h-3 w-3" aria-hidden />
                  {waitingFor(row.since)}
                </span>
              </li>
            ))}
          </Section>
        )}
      </div>
    </div>
  );
}
