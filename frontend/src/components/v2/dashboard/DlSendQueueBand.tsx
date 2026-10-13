"use client";

/**
 * „Do wysłania do klienta” (13.10.2026) — pas Delivery Leada nad pulpitem.
 *
 * Do 13.10.2026 osoby po QC CV stały w panelu „Czeka na Ciebie” jako jedna
 * z kilku wąskich kolumn („Czeka na Twój przegląd (DL)”), razem z kartami,
 * których CV rekruter jeszcze poprawia. Delivery Lead nie widział, kto jest
 * gotowy do wysyłki ani od kiedy. Pas stoi nad panelem na całą szerokość:
 *  - gotowi — QC zdane albo przepuszczone, ruch ma Delivery Lead; tabela ze
 *    stawką kandydata wobec budżetu, stanem CV i screeningu oraz czasem
 *    czekania w kolorze pilności (dni robocze liczy serwer),
 *  - „Jeszcze u rekrutera” — CV do poprawy albo bez QC; jedna linia, wiersze
 *    po „Pokaż”,
 *  - „Z Traffita” — etap z importu, którego nikt nie ruszył w NEXUSIE.
 * Podział liczy `splitDlSendRows` (lustro reguły serwera), a dane to to samo
 * zapytanie co panel (`useBoardTasks`) — bez drugiego żądania.
 *
 * „Przejrzyj po kolei” prowadzi przez gotowe osoby jedna po drugiej
 * (`useReviewSequence`); link z górnego paska `?wysylka=po-kolei` robi to samo.
 * Awarię odczytu pokazuje panel pod spodem (to samo zapytanie) — pas wtedy
 * milczy, żeby komunikat nie stał dwa razy.
 */

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { ArrowRight } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DlReviewPanel } from "@/components/v2/recruitment/DlReviewPanel";
import type { CvPreviewLoaders } from "@/components/v2/recruitment/dl-review/CvColumn";
import { DlReviewQueueDialog } from "@/components/v2/recruitment/dl-review/DlReviewQueueDialog";
import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";
import { useReviewSequence } from "@/hooks/useReviewSequence";
import {
  splitDlSendRows,
  useBoardTasks,
  waitingFor,
  type BoardTaskRow,
  type DlSendUrgency,
} from "@/lib/api/boardTasks";
import { withoutHiddenPanels, type DashboardPanelKey } from "@/lib/dashboard-panels";
import { formatHourly } from "@/lib/dl-review-margin";
import { formatDeadlineShort } from "@/lib/job-header-subtitle";
import { rateText } from "@/lib/person-facts";
import { countPl } from "@/lib/plural-pl";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { boardCardBadge } from "@/lib/recommendation-card";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

/** Kotwica pasa — także pustej linii, żeby link `#do-wyslania` zawsze trafiał. */
export const DL_SEND_ANCHOR = "do-wyslania";
/** `/dashboard?wysylka=po-kolei` — link z okienka „Do wysłania” w górnym pasku. */
export const DL_SEND_SEQUENCE_PARAM = "wysylka";
export const DL_SEND_SEQUENCE_VALUE = "po-kolei";
/** Tyle gotowych osób przed „Pokaż wszystkie” — pas stoi NAD panelem i kafelkami. */
export const DL_SEND_ROWS = 8;

const NO_HIDDEN_PANELS: ReadonlySet<DashboardPanelKey> = new Set();

type RoleBearing = Parameters<typeof hasRole>[0];

/** Pas jest dla Delivery Leada, o ile nie usunął listy przeglądu z pulpitu.
 *  Pulpit pyta o to samo, żeby panel pod spodem nie mówił „nic nie czeka”. */
export function showsDlSendBand(
  user: RoleBearing,
  hiddenPanels: ReadonlySet<DashboardPanelKey>,
): boolean {
  return hasRole(user, "delivery_lead") && !hiddenPanels.has("dl_review");
}

const CARD_BADGE_VARIANT = { ok: "success", wait: "warning", neutral: "outline" } as const;

/** Stan pól screeningu w wierszu przeglądu DL. Pole nieobecne w odpowiedzi
 *  (starszy serwer) = bez plakietki; `null` = nikt nie wpisał żadnego pola. */
export function ReviewCardBadge({ row }: { row: BoardTaskRow }) {
  if (row.card_status === undefined) return null;
  const badge = boardCardBadge(
    row.card_status ? { status: row.card_status, missing: row.card_missing ?? 0, answers: 0 } : null,
    0,
    "cv_qc",
  );
  if (!badge) return null;
  return (
    <Badge size="sm" variant={CARD_BADGE_VARIANT[badge.tone]} title={badge.title}>
      {badge.label}
    </Badge>
  );
}

const stageIdOf = (row: BoardTaskRow): number => row.stage_id;
/** Od kiedy osoba czeka na Delivery Leada; starszy serwer nie zna `ready_since`. */
const sinceOf = (row: BoardTaskRow): string => row.ready_since ?? row.since;

function jobLine(row: BoardTaskRow): string {
  const title = row.job_working_title?.trim() || row.job_title;
  return row.client_name ? `${title} · ${row.client_name}` : title;
}

/**
 * „budżet do 170 zł/h” / „budżet 110–130 zł/h”. Ocenę „ponad budżet” dostaje
 * wyłącznie stawka godzinowa w PLN — inna jednostka albo waluta to „nie do
 * porównania”, nigdy zgadywane przeliczenie w wierszu listy.
 */
function budgetLine(row: BoardTaskRow): { text: string; over: boolean } | null {
  const max = row.budget_max_hourly;
  if (max == null) return null;
  const min = row.budget_min_hourly;
  const range =
    min != null && min < max ? `${formatHourly(min).replace(" zł/h", "")}–${formatHourly(max)}` : null;
  const over = row.expected_rate_unit === "hourly" && isOverHourlyBudget(row, max);
  if (over) return { text: `ponad budżet ${range ?? formatHourly(max)}`, over };
  return { text: range ? `budżet ${range}` : `budżet do ${formatHourly(max)}`, over };
}

// Tekst na tle karty: `warning-muted-foreground` (ciemny bursztyn), nie
// `warning` — jasny bursztyn na białym jest nieczytelny.
const URGENCY_CLASS: Record<DlSendUrgency, string> = {
  late: "font-semibold text-destructive",
  due: "font-semibold text-warning-muted-foreground",
  fresh: "text-muted-foreground",
};

const TEXT_BUTTON =
  "font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

type RowTone = "ready" | "muted";

interface SendRowsTableProps {
  label: string;
  rows: BoardTaskRow[];
  /** `muted` — karta nie jest jeszcze ruchem Delivery Leada: bez koloru pilności. */
  tone: RowTone;
  actionLabel: string;
  /** Początek nazwy przycisku wiersza („Przejrzyj: Anna Nowak”). */
  actionName: string;
  onReview: (row: BoardTaskRow) => void;
  /** Liczba gotowych osób per rekrutacja — przy 2+ wiersz dostaje „porównaj”. */
  readyByJob?: ReadonlyMap<number, number>;
  onCompare?: (row: BoardTaskRow) => void;
}

/**
 * Tabela wierszy pasa. Kolumny mają stałe udziały (`table-fixed`), więc trzy
 * tabele pasa (gotowi i dwie rozwijane grupy) trzymają te same pionowe linie,
 * a nazwisko i rekrutacja skracają się wielokropkiem zamiast rozpychać układ.
 * Układ liczy się od szerokości pasa (udziały kolumn), nie okna. Poniżej
 * 58 rem tabela przewija się w swoim opakowaniu z przyklejoną osobą; próg
 * jest dobrany pod ok. 970 px treści pulpitu przy oknie 1280 px z przypiętym
 * menu — tam ma się mieścić bez przewijania.
 */
function SendRowsTable({
  label,
  rows,
  tone,
  actionLabel,
  actionName,
  onReview,
  readyByJob,
  onCompare,
}: SendRowsTableProps) {
  const muted = tone === "muted";
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[58rem] table-fixed text-left text-xs" aria-label={label}>
        <colgroup>
          <col className="w-[16%]" />
          <col className="w-[21%]" />
          <col className="w-[11%]" />
          <col className="w-[13%]" />
          <col className="w-[15%]" />
          <col className="w-[8%]" />
          <col className="w-[16%]" />
        </colgroup>
        <thead className="bg-muted text-[11px] text-muted-foreground">
          <tr>
            <th scope="col" className="sticky left-0 bg-muted py-1.5 pl-4 pr-2 font-medium">Osoba</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Rekrutacja</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Przekazał(a)</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Stawka kandydata</th>
            <th scope="col" className="px-2 py-1.5 font-medium">CV i screening</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Czeka</th>
            <th scope="col" className="py-1.5 pl-2 pr-4 font-medium">
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => {
            const rate = rateText(row.expected_rate_value, row.expected_rate_unit, row.expected_rate_currency);
            const budget = budgetLine(row);
            const due = formatDeadlineShort(row.deadline);
            const sameJob = readyByJob?.get(row.job_id) ?? 0;
            const job = jobLine(row);
            return (
              <tr key={row.stage_id} data-testid="dl-send-row" className={muted ? "text-muted-foreground" : undefined}>
                <td className="sticky left-0 bg-card py-2 pl-4 pr-2 align-top">
                  <button
                    type="button"
                    onClick={() => onReview(row)}
                    title={row.candidate_name}
                    className={cn(
                      "block max-w-full truncate text-left text-sm hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      muted ? "font-normal" : "font-semibold",
                    )}
                  >
                    {row.candidate_name}
                  </button>
                </td>
                <td className="px-2 py-2 align-top">
                  <p className="truncate" title={job}>
                    {job}
                  </p>
                  {due || (sameJob > 1 && onCompare) ? (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {due ? `termin ${due}` : null}
                      {sameJob > 1 && onCompare ? (
                        <>
                          {due ? " · " : null}
                          {countPl(sameJob, "osoba", "osoby", "osób")} ·{" "}
                          <button
                            type="button"
                            onClick={() => onCompare(row)}
                            aria-label={`porównaj osoby w rekrutacji: ${row.job_working_title?.trim() || row.job_title}`}
                            className={TEXT_BUTTON}
                          >
                            porównaj
                          </button>
                        </>
                      ) : null}
                    </p>
                  ) : null}
                </td>
                <td className="px-2 py-2 align-top">
                  <span className="block truncate" title={row.handed_over_by_name ?? undefined}>
                    {row.handed_over_by_name ?? "—"}
                  </span>
                </td>
                <td className="px-2 py-2 align-top tabular-nums">
                  <span className="block">{rate ?? "—"}</span>
                  {budget ? (
                    <span
                      className={cn(
                        "mt-0.5 block text-[11px]",
                        budget.over ? "font-medium text-warning-muted-foreground" : "text-muted-foreground",
                      )}
                    >
                      {budget.text}
                    </span>
                  ) : null}
                </td>
                <td className="px-2 py-2 align-top">
                  <span className="flex flex-wrap gap-1">
                    <QcStatusBadge row={row} />
                    <ReviewCardBadge row={row} />
                  </span>
                </td>
                <td
                  className={cn(
                    "whitespace-nowrap px-2 py-2 align-top tabular-nums",
                    muted ? undefined : URGENCY_CLASS[row.urgency ?? "fresh"],
                  )}
                >
                  {waitingFor(sinceOf(row))}
                </td>
                <td className="py-2 pl-2 pr-4 text-right align-top">
                  <Button
                    size="sm"
                    variant="outline"
                    className={muted ? undefined : "border-primary/45 font-semibold text-primary"}
                    onClick={() => onReview(row)}
                    aria-label={`${actionName}: ${row.candidate_name}`}
                  >
                    {actionLabel}
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface CollapsedGroupProps {
  /** Krótka nazwa grupy — nazwa dostępna linii i tabeli. */
  label: string;
  /** Zdanie linii, bez liczby. */
  summary: string;
  rows: BoardTaskRow[];
  onReview: (row: BoardTaskRow) => void;
}

/** Grupa, która nie jest dziś ruchem Delivery Leada: jedna linia z liczbą,
 *  wiersze dopiero po „Pokaż” — żeby nie rozmywały listy gotowych. */
function CollapsedGroup({ label, summary, rows, onReview }: CollapsedGroupProps) {
  const [open, setOpen] = useState(false);
  return (
    <div role="group" aria-label={label} className="border-t border-border">
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2 text-xs text-muted-foreground">
        <span>
          {summary}: {rows.length}
        </span>
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className={TEXT_BUTTON}>
          {open ? "Zwiń" : "Pokaż"}
        </button>
      </p>
      {open ? (
        <SendRowsTable
          label={label}
          rows={rows}
          tone="muted"
          actionLabel="Podgląd"
          actionName="Podgląd"
          onReview={onReview}
        />
      ) : null}
    </div>
  );
}

/**
 * `?wysylka=po-kolei` — link z górnego paska uruchamia przegląd po kolei, gdy
 * kolejka jest już wczytana, i znika z adresu (odświeżenie strony nie zaczyna
 * przeglądu od nowa). Osobny komponent w `Suspense`, bo `useSearchParams`
 * wymusza granicę Suspense w Next 15 — jak `OversightLinkSync` na pulpicie.
 */
function SequenceLinkSync({ loaded, onStart }: { loaded: boolean; onStart: () => void }) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const { replaceUrl } = useUrlWriter();
  const requested = searchParams?.get(DL_SEND_SEQUENCE_PARAM) === DL_SEND_SEQUENCE_VALUE;
  // Adres zmienia się klatkę po zapisie, a lista odświeża się po każdej
  // decyzji — bez znacznika kolejka startowałaby drugi raz od początku.
  const handled = useRef(false);
  useEffect(() => {
    if (!requested) {
      handled.current = false;
      return;
    }
    if (!loaded || handled.current || !pathname) return;
    handled.current = true;
    onStart();
    const next = new URLSearchParams(searchParams?.toString() ?? "");
    next.delete(DL_SEND_SEQUENCE_PARAM);
    const qs = next.toString();
    replaceUrl(`${pathname}${qs ? `?${qs}` : ""}${window.location.hash}`);
  }, [requested, loaded, pathname, searchParams, onStart, replaceUrl]);
  return null;
}

export interface DlSendQueueBandProps {
  /** Listy usunięte z pulpitu (`lib/dashboard-panels.ts`) — bez `dl_review` pasa nie ma. */
  hiddenPanels?: ReadonlySet<DashboardPanelKey>;
  /** Harness: bajty plików CV w przeglądzie bez sieci. */
  previewLoaders?: CvPreviewLoaders;
}

export function DlSendQueueBand({ hiddenPanels = NO_HIDDEN_PANELS, previewLoaders }: DlSendQueueBandProps = {}) {
  const user = useAuthStore((s) => s.user);
  if (!showsDlSendBand(user, hiddenPanels)) return null;
  return <DlSendQueue hiddenPanels={hiddenPanels} previewLoaders={previewLoaders} />;
}

function DlSendQueue({
  hiddenPanels,
  previewLoaders,
}: {
  hiddenPanels: ReadonlySet<DashboardPanelKey>;
  previewLoaders?: CvPreviewLoaders;
}) {
  const query = useBoardTasks();
  const { showInfo } = useToast();
  const data = useMemo(
    () => (query.data ? withoutHiddenPanels(query.data, hiddenPanels) : undefined),
    [query.data, hiddenPanels],
  );
  const groups = useMemo(() => splitDlSendRows(data?.dl_review ?? []), [data]);
  const { ready, notReady, imported } = groups;
  const sequence = useReviewSequence(ready, stageIdOf);
  const [reviewing, setReviewing] = useState<BoardTaskRow | null>(null);
  const [compareJob, setCompareJob] = useState<{ id: number; title: string } | null>(null);
  const [showAll, setShowAll] = useState(false);

  const { active, current, start, finish, skipped } = sequence;
  // Ostatnia osoba załatwiona (albo zniknęła z listy): kolejka się zamyka sama.
  // Pominięte osoby dalej czekają — komunikat nie może mówić, że nikogo nie ma.
  useEffect(() => {
    if (!active || current !== null) return;
    finish();
    showInfo(
      skipped > 0
        ? `Koniec kolejki — pominięte osoby dalej czekają: ${skipped}.`
        : "Kolejka przejrzana — nikt więcej nie czeka na wysyłkę.",
    );
  }, [active, current, finish, showInfo, skipped]);

  const startSequence = useCallback(() => {
    // Pusta kolejka nie ma kogo pokazać — start od razu ogłosiłby jej koniec.
    if (ready.length === 0) return;
    setReviewing(null);
    start(ready);
  }, [ready, start]);

  const readyByJob = useMemo(() => {
    const counts = new Map<number, number>();
    for (const row of ready) counts.set(row.job_id, (counts.get(row.job_id) ?? 0) + 1);
    return counts;
  }, [ready]);

  const sync = (
    <Suspense fallback={null}>
      <SequenceLinkSync loaded={data !== undefined} onStart={startSequence} />
    </Suspense>
  );
  // Brak danych: wczytywanie albo awaria — tę drugą pokazuje panel pod spodem.
  // Ten sam kształt drzewa co niżej, żeby `SequenceLinkSync` nie montował się
  // od nowa, gdy kolejka się wczyta.
  if (!data) return <>{sync}</>;

  const total = ready.length + notReady.length + imported.length;
  const oldest = ready[0];
  const late = ready.filter((row) => row.urgency === "late").length;
  const canSend = data.can_send_to_client === true;
  const task = active ? current : reviewing;

  return (
    <>
      {sync}
      {total === 0 ? (
        // Pusty stan tylko po udanym odczycie — awaria nie może wyglądać jak „nikt nie czeka”.
        query.isSuccess ? (
          <p
            id={DL_SEND_ANCHOR}
            role="status"
            className="scroll-mt-20 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
          >
            Nikt nie czeka teraz na wysyłkę do klienta.
          </p>
        ) : null
      ) : (
        // Bez `overflow-hidden` (ucinałby tabelę zamiast ją przewijać): dolny
        // odstęp trzyma tła wierszy z dala od zaokrąglonych rogów ramki.
        <section
          id={DL_SEND_ANCHOR}
          aria-label="Do wysłania do klienta"
          className="scroll-mt-20 rounded-xl border border-primary/40 bg-card pb-2"
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3">
            <h2 className="text-base font-semibold">Do wysłania do klienta</h2>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
                ready.length > 0 ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
              )}
            >
              {countPl(ready.length, "gotowa", "gotowe", "gotowych")}
            </span>
            {oldest ? (
              <p className="min-w-0 text-xs text-muted-foreground">
                najdłużej czeka {waitingFor(sinceOf(oldest))}
                {late > 0 ? (
                  <span className="font-medium text-destructive">
                    {" "}
                    · {countPl(late, "osoba", "osoby", "osób")} 2+ dni robocze
                  </span>
                ) : null}
              </p>
            ) : null}
            {ready.length >= 2 ? (
              <Button size="sm" className="ml-auto shrink-0" onClick={startSequence}>
                <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                Przejrzyj po kolei ({ready.length})
              </Button>
            ) : null}
          </div>
          {ready.length > 0 ? (
            <>
              <SendRowsTable
                label="Gotowi do wysłania do klienta"
                rows={showAll ? ready : ready.slice(0, DL_SEND_ROWS)}
                tone="ready"
                actionLabel={canSend ? "Przejrzyj i wyślij" : "Przejrzyj"}
                actionName="Przejrzyj"
                onReview={setReviewing}
                readyByJob={readyByJob}
                onCompare={(row) =>
                  setCompareJob({ id: row.job_id, title: row.job_working_title?.trim() || row.job_title })
                }
              />
              {ready.length > DL_SEND_ROWS ? (
                <p className="border-t border-border px-4 py-2 text-xs">
                  <button
                    type="button"
                    onClick={() => setShowAll((v) => !v)}
                    aria-expanded={showAll}
                    className={TEXT_BUTTON}
                  >
                    {showAll ? "Zwiń" : `Pokaż wszystkie (${ready.length})`}
                  </button>
                </p>
              ) : null}
            </>
          ) : null}
          {notReady.length > 0 ? (
            <CollapsedGroup
              label="Jeszcze u rekrutera"
              summary="Jeszcze u rekrutera — CV do poprawy albo bez sprawdzenia QC"
              rows={notReady}
              onReview={setReviewing}
            />
          ) : null}
          {imported.length > 0 ? (
            <CollapsedGroup
              label="Z Traffita"
              summary="Z Traffita — nikt nie ruszył karty w NEXUSIE"
              rows={imported}
              onReview={setReviewing}
            />
          ) : null}
        </section>
      )}
      <DlReviewPanel
        task={task}
        open={task !== null}
        onOpenChange={(open) => {
          if (open) return;
          // Zamknięcie okna w trakcie przeglądu po kolei kończy kolejkę.
          if (active) finish();
          else setReviewing(null);
        }}
        canSendToClient={data.can_send_to_client}
        previewLoaders={previewLoaders}
        onDecided={active ? () => sequence.advance() : undefined}
        sequence={
          active
            ? {
                position: sequence.position,
                total: sequence.total,
                onSkip: sequence.skip,
                onFinish: finish,
              }
            : undefined
        }
      />
      <DlReviewQueueDialog
        jobId={compareJob?.id ?? null}
        jobTitle={compareJob?.title ?? null}
        open={compareJob !== null}
        onOpenChange={(open) => {
          if (!open) setCompareJob(null);
        }}
        onReview={setReviewing}
      />
    </>
  );
}
