"use client";

/**
 * „Czeka na Ciebie" — praca na Tablicach, której nikt nie widzi (0348, v5).
 *
 * Listy z `GET /api/board-tasks`:
 *  - „Propozycje automatu do akceptacji" (02.10.2026) — automat przydziału
 *    proponuje osobę do requestu bez rekrutera, a Head of Recruitment albo
 *    admin ją akceptuje, zmienia albo odrzuca (`AllocationProposalsSection`).
 *    Pierwsza sekcja panelu; widzi ją wyłącznie osoba, która o propozycjach
 *    decyduje (`can_decide_proposals`),
 *  - „Nowe osoby do ustawienia” (0612, 28.10.2026) — konto po pierwszym
 *    logowaniu przez Microsoft czeka na decyzję, kim jest, a rekruterowi
 *    brakuje kategorii albo przełożonego; okno „Ustaw” (`NewPeopleSection`).
 *    Admin i Head of Recruitment; liczy się do tego, czy coś „czeka”.
 *  - „Nowe rekrutacje — kto prowadzi" — dla admina i Head of Recruitment:
 *    kto jest rekruterem prowadzącym świeżo przekazanych rekrutacji (automat
 *    albo osoba wskazana przez Delivery Leada) i „Zmień" tam, gdzie się nie
 *    zgadzają (`NewJobLeadsSection`). To informacja, nie zadanie: nie liczy
 *    się do tego, czy coś „czeka", a bez innych list stoi sama nad pulpitem,
 *  - „Obłożenie" (09.10.2026) — ile requestów ma każda osoba; stoi pod dwiema
 *    listami wyżej, gdy któraś ma wiersze, bo to przy nich przydziela się
 *    ludzi (`TeamLoadSection`). Informacja jak lista prowadzących,
 *  - „Do wrzucenia do Cpro" (Nordea) — jedna linia na rekrutację; „Wrzucaj po
 *    kolei" otwiera `CproQueueDialog`. Do Cpro wrzuca JEDNA osoba na całą
 *    firmę (decyzja Artura 23.09.2026) i tylko ona widzi obie listy Cpro
 *    (24.09.2026); gdy nikt nie jest ustawiony — admin i HoR, żeby ktoś ją
 *    ustawił,
 *  - „Wysłane do Cpro" — od ilu dni czekamy na Nordeę (tylko osoba od Cpro),
 *  - „Prepy przed rozmową u klienta" (0370) — brak prepu, prep słaby albo bez
 *    nagrania; wiersz prowadzi do karty kandydata w kalendarzu. Nic nie
 *    blokuje — to przypomnienie, nie bramka (`PrepAttentionSection`),
 *  - „Follow-up z kandydatami" (0372) — klient milczy 14 dni, telefon do
 *    kandydata; jeden na OSOBĘ, także gdy jest w kilku procesach
 *    (`FollowupSection`).
 *  - „Rekrutacje do dokończenia albo zamknięcia" — stare szkice (zamykają się
 *    same po terminie) i rekrutacje opublikowane bez przekazania do searchu,
 *    z „Dokończ / Uzupełnij / Zamknij" i Twoimi niedokończonymi formularzami
 *    nowej rekrutacji (`PendingJobsSection`). Jak lista prowadzących — nie
 *    liczy się do tego, czy coś „czeka".
 *  - „Wymagania do poprawy” (13.10.2026, D4) — propozycje uporządkowania
 *    wymagań otwartych rekrutacji do zatwierdzenia albo odrzucenia
 *    (`RequirementFixesSection`). Jak lista do dokończenia — nie liczy się
 *    do tego, czy coś „czeka”.
 *  - „Umowy do potwierdzenia / do zamknięcia” (04.10.2026) — podpis umowy
 *    z Generatora potwierdza osoba z „Podpis B2B”; rekruter widzi swoje
 *    prośby w „U innych” (`AgreementTasksSection`).
 *  - „Twoje CV w drodze" (02.10.2026) — dla rekrutera kandydata: co wróciło
 *    (odrzucenie przez DL, cofnięcie z QC, zwrot z kolejki Cpro), co czeka
 *    w przeglądzie i co poszło do klienta (`CvInTransitSection`). Każdy ma ją
 *    domyślnie i może usunąć z pulpitu; bez innych list jest wąskim paskiem.
 *
 * Przegląd Delivery Leada („Czeka na Twój przegląd (DL)") wyszedł stąd
 * 13.10.2026 do pasa „Do wysłania do klienta" nad panelem (`DlSendQueueBand`):
 * w wąskiej kolumnie gotowi do wysyłki ginęli między innymi listami. Wiersze
 * `dl_review` nie liczą się tu do tego, czy coś „czeka", a przy pasie
 * (`dlSendBand`) panel nie mówi „Nic na Ciebie teraz nie czeka." — pustą
 * kolejkę wysyłki ogłasza pas.
 *
 * „Do uzupełnienia” (21.10.2026, prośba Olafa): umowy do zamknięcia,
 * rekrutacje do dokończenia, wymagania do poprawy i (od 23.10.2026) prepy
 * przed rozmową u klienta można przenieść do kafelka
 * na siatce (`custom/ToCompleteTile`). Gdy kafelek stoi na pulpicie
 * (`toCompleteOnGrid`), panel tych list nie pokazuje; gdy go nie ma — stoją
 * tu jak dotąd, z linią „Przenieś na pulpit” (`onMoveToComplete`).
 *
 * Cały panel jako kafelek (23.10.2026, Head of Recruitment i admin): menu „⋯”
 * w nagłówku (`onMoveToGrid`, `onRemovePanel`) stawia go na siatce albo usuwa
 * z pulpitu; w kafelku (`custom/BoardTasksTile`, `inTile`) nie stoi nad siatką.
 *
 * Kolejka „Czeka na DZ" i przegląd DZ (0353) zniknęły — zastąpiło je QC CV.
 * Panel „Czeka na Ciebie" nie renderuje się, gdy nic nie czeka — pusta ramka
 * uczyłaby go ignorować (zostają wtedy najwyżej listy informacyjne: „Nowe
 * rekrutacje — kto prowadzi", „Rekrutacje do dokończenia albo zamknięcia",
 * „Wymagania do poprawy” i pasek „Twoje CV w drodze"). Kotwica `#czeka-na-ciebie` = link z porannego dzwonka.
 */

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Clock, LayoutGrid, ListOrdered, MoreHorizontal, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AllocationProposalsSection } from "@/components/v2/dashboard/AllocationProposalsSection";
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState";
import { FollowupSection } from "@/components/v2/followups/FollowupSection";
import {
  groupCproByJob,
  useBoardTasks,
  useCproSender,
  waitingFor,
  type BoardTaskRow,
} from "@/lib/api/boardTasks";
import { countPl } from "@/lib/plural-pl";
import { withoutHiddenPanels, type DashboardPanelKey } from "@/lib/dashboard-panels";
import { toCompleteCounts, withoutToCompleteLists } from "@/lib/dashboard-to-complete";
import { transitToFixTotal } from "@/lib/cv-in-transit";
import { useDepartedCare } from "@/lib/departed-care";
import { hasRole, useAuthStore } from "@/store/auth";

import {
  AgreementTasksSection,
  AgreementWaitingSection,
  agreementTasksCount,
} from "./AgreementTasksSection";
import { BoardFlowOthers, BoardFlowSections, flowWorkCount, hasFlowOthers } from "./BoardFlowSections";
import { DepartedCareSection, departedCareCount } from "./DepartedCareSection";
import { BOARD_TASKS_ROWS, Section } from "./BoardTasksSection";
import { RateChangesSection, RateChangesWaitingSection } from "./RateChangesSection";
import { CproQueueDialog, CproSenderControl } from "./CproQueueDialog";
import { CvInTransitSection } from "./CvInTransitSection";
import { NewJobLeadsSection } from "./NewJobLeadsSection";
import { NewPeopleSection } from "./NewPeopleSection";
import { PendingJobsSection, hasPendingJobsContent } from "./PendingJobsSection";
import { PrepAttentionSection } from "./PrepAttentionSection";
import { RequirementFixesSection } from "./RequirementFixesSection";
import { TeamLoadSection } from "./TeamLoadSection";
import { ToCompleteMovePrompt } from "./ToCompleteMovePrompt";

export const BOARD_TASKS_ANCHOR = "czeka-na-ciebie";

function boardLink(row: BoardTaskRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function RowMeta({ row }: { row: BoardTaskRow }) {
  return (
    <p className="truncate text-xs text-muted-foreground">
      {row.job_working_title?.trim() || row.job_title}
      {row.client_name ? ` · ${row.client_name}` : ""}
    </p>
  );
}

export { BOARD_TASKS_ROWS } from "./BoardTasksSection";

export interface BoardTasksPanelProps {
  /** Listy usunięte z pulpitu (Head of Recruitment — `lib/dashboard-panels.ts`).
   *  Ukryta lista wygląda dla panelu jak pusta. */
  hiddenPanels?: ReadonlySet<DashboardPanelKey>;
  /** Nad panelem stoi pas „Do wysłania do klienta” (`DlSendQueueBand`) — pustą
   *  kolejkę ogłasza on, a „Nic na Ciebie teraz nie czeka.” tuż pod osobami
   *  gotowymi do wysyłki byłoby nieprawdą. */
  dlSendBand?: boolean;
  /** Kafelek „Do uzupełnienia” stoi na pulpicie — jego list tu nie ma. */
  toCompleteOnGrid?: boolean;
  /** Linia „Przenieś na pulpit” nad listami do uzupełnienia; bez funkcji jej nie ma. */
  onMoveToComplete?: () => void;
  onKeepToComplete?: () => void;
  moveBusy?: boolean;
  /** „Postaw jako kafelek” (23.10.2026, Head of Recruitment i admin) — panel
   *  przechodzi do kafelka `board_tasks` na siatce. Bez funkcji pozycji nie ma. */
  onMoveToGrid?: () => void;
  /** „Usuń z pulpitu” — cały panel znika; wraca z „Listy nad pulpitem”. */
  onRemovePanel?: () => void;
  /** Panel w kafelku „Czeka na Ciebie”: zdanie zamiast pustki, gdy nic nie
   *  czeka (kafelek nie może stać pusty), i miejsce na menu kafelka w rogu. */
  inTile?: boolean;
}

const NO_HIDDEN_PANELS: ReadonlySet<DashboardPanelKey> = new Set();

export function BoardTasksPanel({
  hiddenPanels = NO_HIDDEN_PANELS,
  dlSendBand = false,
  toCompleteOnGrid = false,
  onMoveToComplete,
  onKeepToComplete,
  moveBusy = false,
  onMoveToGrid,
  onRemovePanel,
  inTile = false,
}: BoardTasksPanelProps = {}) {
  const query = useBoardTasks();
  // „Po osobach, które odeszły” (28.10.2026): opiekunem jest DL, główny DL
  // klienta albo Head of Recruitment; admin i HoR widzą też licznik per DL.
  const me = useAuthStore((s) => s.user);
  const care = useDepartedCare(
    hasRole(me, "delivery_lead", "head_of_recruitment", "admin"),
  );
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [cproJob, setCproJob] = useState<number | null>(null);
  const [cproOpen, setCproOpen] = useState(false);
  const toggle = (kind: string) => setExpanded((prev) => ({ ...prev, [kind]: !prev[kind] }));
  const shown = <T,>(kind: string, rows: T[]): T[] =>
    expanded[kind] ? rows : rows.slice(0, BOARD_TASKS_ROWS);
  const data = useMemo(() => {
    if (!query.data) return undefined;
    const visible = withoutHiddenPanels(query.data, hiddenPanels);
    return toCompleteOnGrid ? withoutToCompleteLists(visible) : visible;
  }, [query.data, hiddenPanels, toCompleteOnGrid]);
  const hasCpro = (data?.cpro_to_send.length ?? 0) > 0;
  // Osobę od Cpro ustawia admin albo DL Nordei (25.09.2026) — przełącznik
  // stoi u nich także przy pustej kolejce, inaczej martwe konto albo brak
  // osoby nie dałby się naprawić z żadnego miejsca.
  const canSetSender = data?.can_set_cpro_sender === true;
  const sender = useCproSender(hasCpro || canSetSender);
  // Link z porannego dzwonka (`/dashboard#czeka-na-ciebie`): panel pojawia się
  // dopiero po odczycie kolejki, więc przeglądarka sama do niego nie przewinie.
  const scrolled = useRef(false);
  useEffect(() => {
    if (scrolled.current || !data || typeof window === "undefined") return;
    if (window.location.hash !== `#${BOARD_TASKS_ANCHOR}`) return;
    scrolled.current = true;
    document.getElementById(BOARD_TASKS_ANCHOR)?.scrollIntoView({ block: "start" });
  }, [data]);

  if (!data) {
    // Runda 8 (R8-N14-1): awaria odczytu nie może udawać „nic nie czeka” —
    // osoba z porannego dzwonka uznałaby, że kolejka jest pusta.
    if (!query.isError) return null;
    return (
      <div
        id={BOARD_TASKS_ANCHOR}
        role="region"
        aria-label="Czeka na Ciebie"
        className="scroll-mt-20 rounded-xl border border-border bg-card px-4"
      >
        <WidgetErrorBlock
          title="Nie udało się wczytać listy „Czeka na Ciebie”."
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }
  const preps = data.prep_attention ?? [];
  const followups = data.followups ?? [];
  // Serwer wysyła propozycje tylko osobie decydującej; flaga jest drugim
  // zamkiem — bez niej sekcji nie ma, nawet gdyby wiersze przyszły.
  const proposals =
    data.can_decide_proposals === true ? (data.allocation_proposals ?? []) : [];
  // „Nowe osoby do ustawienia” (0612) — zadanie admina i Head of Recruitment.
  const newPeople = data.can_decide_proposals === true ? (data.new_people ?? []) : [];
  const newPeopleFailed = data.can_decide_proposals === true && data.new_people === null;
  const total =
    newPeople.length +
    proposals.length +
    data.cpro_to_send.length +
    data.cpro_sent.length +
    preps.length +
    followups.length +
    agreementTasksCount(data.agreements) +
    flowWorkCount(data.flow, data.finance) +
    departedCareCount(care.data) +
    (data.rate_changes?.length ?? 0);
  // „Twoje CV w drodze”: gdy coś wróciło albo panel i tak stoi — kolumna
  // w panelu; gdy nie — sam wąski pasek nad pulpitem (także z pustym stanem,
  // bo każdy ma tę listę domyślnie i może ją usunąć z pulpitu).
  const transit = data.cv_in_transit ?? null;
  // „Nowe rekrutacje — kto prowadzi” to informacja dla Head of Recruitment
  // i admina (serwer nie wysyła jej nikomu innemu): do `total` się nie liczy,
  // a gdy nic nie czeka — stoi sama, we własnej ramce.
  const leads = data.new_job_leads ?? [];
  // „Obłożenie” towarzyszy listom, przy których przydziela się ludzi — bez
  // nich nie ma czego rozstrzygać, a pełna tablica jest w „Requesty i obłożenie”.
  const showLoad =
    data.can_decide_proposals === true &&
    proposals.length + leads.length > 0 &&
    !hiddenPanels.has("team_load");
  // „Rekrutacje do dokończenia albo zamknięcia” (Rekrutacja bez szkiców) —
  // zaległość, nie zadanie z Tablicy: do `total` się nie liczy, jak lista
  // prowadzących. Starszy serwer pól nie oddaje (`undefined`/`null`).
  const hasPendingJobs = hasPendingJobsContent(data.pending_jobs, data.unfinished_forms);
  // „Wymagania do poprawy” — tak samo: zaległość obok zadań, do `total` się nie liczy.
  const fixes = data.requirement_fixes ?? [];
  // `null` = serwer nie policzył listy — mówimy to, zamiast udawać, że nic nie ma.
  const fixesFailed = data.requirement_fixes === null;
  // Admin i Head of Recruitment widzą listę do dokończenia zwiniętą do jednej
  // linii, gdy obok są zadania — to zaległość, nie praca na dziś.
  const collapsePending = data.can_decide_proposals === true;
  const movePrompt =
    onMoveToComplete && toCompleteCounts(data).total > 0 ? (
      <ToCompleteMovePrompt
        onMove={onMoveToComplete}
        onKeep={() => onKeepToComplete?.()}
        busy={moveBusy}
      />
    ) : null;
  const flowOthers = hasFlowOthers(data.flow);
  const waitingAgreements = data.agreements?.waiting_on_others ?? [];
  if (
    total === 0 &&
    (transit?.returned_total ?? 0) === 0 &&
    !flowOthers &&
    waitingAgreements.length === 0 &&
    (data.rate_changes_by_others?.length ?? 0) === 0
  ) {
    // Rola z sekcjami przepływu (rekruter, TCM, DL) dostaje jedno zdanie
    // zamiast znikającego panelu — inaczej „nic” i „nie wczytało się” wyglądają
    // tak samo. Pozostałe role: bez pustej ramki, jak dotąd. Przy pasie „Do
    // wysłania do klienta” zdania nie ma — o pustej kolejce mówi pas.
    const quiet = data.flow?.applies === true && !dlSendBand;
    if (
      !quiet &&
      !canSetSender &&
      !transit &&
      leads.length === 0 &&
      !hasPendingJobs &&
      fixes.length === 0 &&
      !fixesFailed
    ) {
      return inTile ? (
        <p role="status" className="text-sm text-muted-foreground">
          Nic na Ciebie teraz nie czeka.
        </p>
      ) : null;
    }
    return (
      <div className="flex flex-col gap-3">
        {quiet ? (
          <p
            id={BOARD_TASKS_ANCHOR}
            role="status"
            className="scroll-mt-20 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
          >
            Nic na Ciebie teraz nie czeka.
          </p>
        ) : null}
        {canSetSender ? (
          <div role="region" aria-label="Osoba od Cpro" className="rounded-xl border border-border bg-card px-4 py-2">
            <CproSenderControl sender={sender.data} loading={sender.isLoading} compact />
          </div>
        ) : null}
        <NewJobLeadsSection rows={leads} standalone />
        {showLoad ? <TeamLoadSection standalone /> : null}
        {movePrompt}
        <PendingJobsSection pending={data.pending_jobs} forms={data.unfinished_forms} standalone />
        <RequirementFixesSection rows={fixes} standalone />
        {fixesFailed ? <RequirementFixesFailed /> : null}
        {transit ? <CvInTransitSection transit={transit} standalone /> : null}
      </div>
    );
  }

  const cproGroups = groupCproByJob(data.cpro_to_send);
  // „Twoje CV w drodze” z czymś, co wróciło do poprawy, to Twój ruch (popraw
  // i oddaj); czekanie na przegląd i klienta albo samo odrzucenie przez DL —
  // „U innych”.
  const transitIsMine = transit ? transitToFixTotal(transit) > 0 : false;
  const othersGroup =
    (Boolean(transit) && !transitIsMine) ||
    data.cpro_sent.length > 0 ||
    flowOthers ||
    waitingAgreements.length > 0 ||
    (data.rate_changes_by_others?.length ?? 0) > 0;
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
      <div className={`mb-3 flex flex-wrap items-baseline justify-between gap-2 ${inTile ? "pr-9" : ""}`}>
        <h2 className="text-base font-semibold">Czeka na Ciebie</h2>
        <div className="flex items-center gap-2">
          <p className="text-xs text-muted-foreground">
            Ruchy na Tablicach z ostatnich {Math.max(data.window_days, data.dl_review_window_days ?? 0)} dni · najdłużej czekający na górze
          </p>
          {onMoveToGrid || onRemovePanel ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Opcje panelu „Czeka na Ciebie”">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {onMoveToGrid ? (
                  <DropdownMenuItem onSelect={onMoveToGrid}>
                    <LayoutGrid className="h-4 w-4" />
                    Postaw jako kafelek na pulpicie
                  </DropdownMenuItem>
                ) : null}
                {onRemovePanel ? (
                  <DropdownMenuItem onSelect={onRemovePanel} className="text-destructive">
                    <Trash2 className="h-4 w-4" />
                    Usuń z pulpitu
                  </DropdownMenuItem>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>
      {!hasCpro && canSetSender ? (
        <div className="mb-3">
          <CproSenderControl sender={sender.data} loading={sender.isLoading} compact />
        </div>
      ) : null}
      {/* PR 6 (04.10.2026): „Twój ruch” i „U innych” — to, co zrobisz sam,
          oddzielone od tego, na co czekasz (przegląd, klient, Cpro). */}
      {othersGroup && (total > 0 || transitIsMine) ? (
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Twój ruch
        </h3>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Kolejka Cpro pierwsza (decyzja Artura 26.10.2026): to codzienna
            praca osoby od Cpro, a pod Finansami i follow-upami trzeba było
            do niej przewijać. Widzi ją tylko osoba od Cpro. */}
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
        <NewPeopleSection rows={newPeople} />
        {newPeopleFailed ? <NewPeopleFailed /> : null}
        <AllocationProposalsSection
          rows={proposals}
          leaveKnown={data.allocation_leave_known !== false}
        />
        <NewJobLeadsSection rows={leads} />
        {showLoad ? <TeamLoadSection /> : null}
        <DepartedCareSection
          data={care.data}
          failed={care.isError}
          expanded={expanded["departed_care"] === true}
          onToggle={() => toggle("departed_care")}
        />
        {movePrompt}
        <PendingJobsSection
          pending={data.pending_jobs}
          forms={data.unfinished_forms}
          collapsed={collapsePending}
        />
        <RequirementFixesSection rows={fixes} collapsed={collapsePending} />
        {fixesFailed ? <RequirementFixesFailed /> : null}
        <BoardFlowSections
          flow={data.flow}
          finance={data.finance}
          expanded={expanded}
          onToggle={toggle}
          shown={shown}
        />
        <FollowupSection rows={followups} others={data.followups_by_others ?? []} />
        <AgreementTasksSection tasks={data.agreements} />
        <RateChangesSection rows={data.rate_changes} />
        {transit && transitIsMine ? <CvInTransitSection transit={transit} /> : null}
        <PrepAttentionSection rows={preps} />

      </div>
      {othersGroup ? (
        <div className="mt-4 border-t border-border pt-3" role="group" aria-label="U innych">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            U innych — czekasz na nich
          </h3>
          <div className="grid gap-4 lg:grid-cols-3">
            {transit && !transitIsMine ? <CvInTransitSection transit={transit} /> : null}
            <AgreementWaitingSection rows={waitingAgreements} />
            <BoardFlowOthers flow={data.flow} expanded={expanded} onToggle={toggle} shown={shown} />
            <RateChangesWaitingSection rows={data.rate_changes_by_others} />
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
      ) : null}
      <CproQueueDialog open={cproOpen} onClose={() => setCproOpen(false)} initialJobId={cproJob} />
    </div>
  );
}

/** Awaria liczenia „Wymagań do poprawy” (`requirement_fixes: null`, audyt 13.10.2026). */
function RequirementFixesFailed() {
  return (
    <p
      role="status"
      data-testid="requirement-fixes-failed"
      className="rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground lg:col-span-3"
    >
      Nie udało się policzyć „Wymagań do poprawy” — odśwież pulpit.
    </p>
  );
}

/** Awaria liczenia „Nowych osób do ustawienia” (`new_people: null`). */
function NewPeopleFailed() {
  return (
    <p
      role="status"
      data-testid="new-people-failed"
      className="rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground lg:col-span-3"
    >
      Nie udało się policzyć „Nowych osób do ustawienia” — odśwież pulpit.
    </p>
  );
}
