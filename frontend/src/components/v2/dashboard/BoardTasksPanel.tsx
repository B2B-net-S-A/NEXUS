"use client";

/**
 * „Czeka na Ciebie" — praca na Tablicach, której nikt nie widzi (0348, v5).
 *
 * Listy z `GET /api/board-tasks`:
 *  - „Czeka na Twój przegląd (DL)" (klienci spoza Nordei) — osoby w kolumnie
 *    „QC CV", które Delivery Lead wysyła do klienta ze stawką albo odrzuca;
 *    wiersz otwiera `DlReviewPanel` (CV, QC, screening, stawka),
 *    Widzi go wyłącznie Delivery Lead rekrutacji (admin i HoR nie),
 *  - „Do wrzucenia do Cpro" (Nordea) — jedna linia na rekrutację; „Wrzucaj po
 *    kolei" otwiera `CproQueueDialog`. Do Cpro wrzuca JEDNA osoba na całą
 *    firmę (decyzja Artura 23.09.2026) i tylko ona widzi obie listy Cpro
 *    (24.09.2026); gdy nikt nie jest ustawiony — admin i HoR, żeby ktoś ją
 *    ustawił,
 *  - „Wysłane do Cpro" — od ilu dni czekamy na Nordeę (tylko osoba od Cpro),
 *  - „Prepy przed rozmową u klienta" (0370) — brak prepu, prep słaby albo bez
 *    nagrania; wiersz prowadzi do karty kandydata w kalendarzu. Nic nie
 *    blokuje — to przypomnienie, nie bramka,
 *  - „Follow-up z kandydatami" (0372) — klient milczy 14 dni, telefon do
 *    kandydata; jeden na OSOBĘ, także gdy jest w kilku procesach
 *    (`FollowupSection`).
 *
 * Kolejka „Czeka na DZ" i przegląd DZ (0353) zniknęły — zastąpiło je QC CV.
 * Panel nie renderuje się, gdy nic nie czeka — pusta ramka uczyłaby go
 * ignorować. Kotwica `#czeka-na-ciebie` = link z porannego dzwonka.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Clock, Eye, ListOrdered } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FollowupSection } from "@/components/v2/followups/FollowupSection";
import { DlReviewPanel } from "@/components/v2/recruitment/DlReviewPanel";
import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";
import {
  PREP_ATTENTION_REASON_LABEL,
  groupCproByJob,
  prepAttentionLink,
  useBoardTasks,
  useCproSender,
  waitingFor,
  type BoardTaskRow,
  type PrepAttentionRow,
} from "@/lib/api/boardTasks";
import { formatDayLabel, formatTime } from "@/lib/interview-cycle";
import { countPl } from "@/lib/plural-pl";

import { CproQueueDialog, CproSenderControl } from "./CproQueueDialog";

export const BOARD_TASKS_ANCHOR = "czeka-na-ciebie";

function boardLink(row: BoardTaskRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function prepRowKey(row: PrepAttentionRow): string {
  return `${row.interview_event_id}-${row.prep_no}-${row.reason}`;
}

/** Pilny wiersz (rozmowa tuż-tuż) na czerwono, reszta na bursztynowo. */
function prepReasonClass(row: PrepAttentionRow): string {
  return row.urgent
    ? "bg-destructive/10 text-destructive"
    : "bg-warning-muted text-warning-muted-foreground";
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
  /** Liczba wierszy listy, gdy inna niż `count` (Cpro: wiersz = rekrutacja). */
  rows?: number;
  expanded: boolean;
  onToggle: () => void;
  /** Dodatek pod nagłówkiem (Cpro: kto wrzuca · Zmień). */
  aside?: React.ReactNode;
  children: React.ReactNode;
}

function Section({ title, hint, count, rows = count, expanded, onToggle, aside, children }: SectionProps) {
  return (
    <section aria-label={title} className="min-w-0">
      <header className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {count}
        </span>
      </header>
      {aside ? <div className="mb-1">{aside}</div> : null}
      <p className="mb-2 text-xs text-muted-foreground">{hint}</p>
      <ul className="divide-y divide-border rounded-lg border border-border">{children}</ul>
      {rows > BOARD_TASKS_ROWS && (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${rows})`}
        </button>
      )}
    </section>
  );
}

export function BoardTasksPanel() {
  const query = useBoardTasks();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [reviewing, setReviewing] = useState<BoardTaskRow | null>(null);
  const [cproJob, setCproJob] = useState<number | null>(null);
  const [cproOpen, setCproOpen] = useState(false);
  const toggle = (kind: string) => setExpanded((prev) => ({ ...prev, [kind]: !prev[kind] }));
  const shown = <T,>(kind: string, rows: T[]): T[] =>
    expanded[kind] ? rows : rows.slice(0, BOARD_TASKS_ROWS);
  const data = query.data;
  const hasCpro = (data?.cpro_to_send.length ?? 0) > 0;
  const sender = useCproSender(hasCpro);
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
  const dlReview = data.dl_review ?? [];
  const preps = data.prep_attention ?? [];
  const followups = data.followups ?? [];
  const total =
    dlReview.length +
    data.cpro_to_send.length +
    data.cpro_sent.length +
    preps.length +
    followups.length;
  if (total === 0) return null;

  const cproGroups = groupCproByJob(data.cpro_to_send);
  const openQueue = (jobId: number | null) => {
    setCproJob(jobId);
    setCproOpen(true);
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
          Ruchy na Tablicach z ostatnich {Math.max(data.window_days, data.dl_review_window_days ?? 0)} dni · najdłużej czekający na górze
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <FollowupSection rows={followups} others={data.followups_by_others ?? []} />
        {dlReview.length > 0 && (
          <Section
            title="Czeka na Twój przegląd (DL)"
            hint={`Po QC CV — wyślij do klienta ze stawką albo odrzuć (ostatnie ${data.dl_review_window_days ?? 30} dni).`}
            count={dlReview.length}
            expanded={expanded["dl_review"] === true}
            onToggle={() => toggle("dl_review")}
          >
            {shown("dl_review", dlReview).map((row) => (
              <li key={row.stage_id} className="flex items-center gap-2 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => setReviewing(row)}
                    className="block max-w-full truncate text-left text-sm font-medium hover:underline"
                  >
                    {row.candidate_name}
                  </button>
                  <RowMeta row={row} />
                </div>
                <QcStatusBadge row={row} />
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {waitingFor(row.since)}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  className="shrink-0"
                  onClick={() => setReviewing(row)}
                  aria-label={`Przejrzyj: ${row.candidate_name}`}
                >
                  <Eye className="h-3.5 w-3.5" />
                  Przejrzyj
                </Button>
              </li>
            ))}
          </Section>
        )}

        {data.cpro_to_send.length > 0 && (
          <Section
            title="Do wrzucenia do Cpro"
            hint="Jedna osoba wrzuca do Cpro kandydatów wszystkich rekrutacji."
            count={data.cpro_to_send.length}
            rows={cproGroups.length}
            expanded={expanded["cpro_to_send"] === true}
            onToggle={() => toggle("cpro_to_send")}
            aside={<CproSenderControl sender={sender.data} loading={sender.isLoading} compact />}
          >
            {shown("cpro_to_send", cproGroups).map((group) => (
              <li key={group.job_id} className="flex items-center gap-2 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => openQueue(group.job_id)}
                    className="block max-w-full truncate text-left text-sm font-medium hover:underline"
                  >
                    {group.job_title} · {countPl(group.rows.length, "osoba", "osoby", "osób")}
                  </button>
                  <p className="truncate text-xs text-muted-foreground">
                    {group.client_name ? `${group.client_name} · ` : ""}najstarsza czeka {waitingFor(group.rows[0].since)}
                  </p>
                </div>
              </li>
            ))}
            <li className="px-3 py-2">
              <Button size="sm" className="w-full" onClick={() => openQueue(null)}>
                <ListOrdered className="h-3.5 w-3.5" />
                Wrzucaj po kolei
              </Button>
            </li>
          </Section>
        )}

        {preps.length > 0 && (
          <Section
            title="Prepy przed rozmową u klienta"
            hint="Brak prepu, prep słaby albo bez nagrania — nic nie blokuje, ale warto to nadrobić przed rozmową."
            count={preps.length}
            expanded={expanded["prep_attention"] === true}
            onToggle={() => toggle("prep_attention")}
          >
            {shown("prep_attention", preps).map((row) => (
              <li
                key={prepRowKey(row)}
                className={`flex items-center gap-2 px-3 py-2 ${row.urgent ? "bg-destructive/5" : ""}`}
              >
                <div className="min-w-0 flex-1">
                  <Link
                    href={prepAttentionLink(row)}
                    className="block truncate text-sm font-medium hover:underline"
                  >
                    {row.candidate_name}
                  </Link>
                  <p className="truncate text-xs text-muted-foreground">
                    {row.job_title} · Prep {row.prep_no}
                  </p>
                  <p className="text-xs tabular-nums text-muted-foreground">
                    Rozmowa u klienta: {formatDayLabel(row.interview_start)}, {formatTime(row.interview_start)}
                  </p>
                </div>
                <span
                  className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${prepReasonClass(row)}`}
                >
                  {row.urgent && <AlertTriangle className="h-3 w-3" aria-hidden />}
                  {PREP_ATTENTION_REASON_LABEL[row.reason]}
                  {row.urgent && <span className="sr-only"> — pilne</span>}
                </span>
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
      <DlReviewPanel
        task={reviewing}
        open={reviewing !== null}
        onOpenChange={(open) => {
          if (!open) setReviewing(null);
        }}
        canSendToClient={data.can_send_to_client}
      />
      <CproQueueDialog open={cproOpen} onClose={() => setCproOpen(false)} initialJobId={cproJob} />
    </div>
  );
}
