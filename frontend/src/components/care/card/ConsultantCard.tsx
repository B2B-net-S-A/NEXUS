"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, MoreHorizontal, Plus } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiErrorMessage } from "@/lib/api-error";
import {
  HIRING_SOURCE_LABELS,
  OWNER_SOURCE_LABELS,
  SKIP_REASON_LABELS,
  careKeys,
  useConsultantCard,
  useHandOffToFrontOffice,
  useUpdatePlanItem,
  type CardCase,
  type CardPlanItem,
  type ConsultantCardData,
  type HiringSource,
  type TimelineEvent,
} from "@/lib/api/care";
import { useHrConfig } from "@/lib/api/hr";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, formatIsoDatePl, monthYearPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useContractFeedback } from "@/lib/api/client-people";
import { countPl } from "@/lib/plural-pl";

import { careWithoutRhythm, nearestPlanItem, planItemOverdue } from "../back-office-care";
import { CadenceDialog } from "../CadenceDialog";
import { ClientFeedbackDialog } from "../ClientFeedbackDialog";
import { ConversationDialog } from "../ConversationDialog";
import { HEALTH_BADGE, healthLabel, healthWhy } from "../health-format";
import { SkipPlanItemDialog } from "../SkipPlanItemDialog";
import { FrontOfficeSection, handoffToast } from "../week/FrontOfficeSection";
import { CardHistory } from "./CardHistory";
import {
  cardKpis,
  cardSubtitle,
  caseMeta,
  caseStatusPill,
  caseWhen,
  casesHeading,
  closedCasesLine,
  daysAgoText,
  managerFeedbackKpi,
  openCases,
  satisfactionKpi,
  teamText,
  type CaseStatusTone,
  type KpiTone,
} from "./card-format";
import { ManagerPicker } from "./ManagerPicker";
import { NewCaseDialog } from "./NewCaseDialog";
import { OwnerDialog } from "./OwnerDialog";

const KPI_TONE: Record<KpiTone, string> = {
  neutral: "text-foreground",
  good: "text-success-muted-foreground",
  warning: "text-warning-muted-foreground",
  danger: "text-destructive",
};

function Section({
  title,
  action,
  children,
  className,
}: {
  title: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function sourceText(card: ConsultantCardData): string | null {
  const source = card.known_project?.source;
  if (!source) return null;
  return [
    source.kind === "tech_card" ? "z karty technologicznej" : "z rozmowy",
    formatDayMonthPl(source.on),
    source.author_name,
  ]
    .filter(Boolean)
    .join(" · ");
}

function Strong({ children }: { children: ReactNode }) {
  return <span className="font-medium text-foreground">{children}</span>;
}

/**
 * „Co wiemy o projekcie” (makieta P2): skąd wiemy, potem jedna linia
 * „Dział X · menedżer Y · zespół 9 osób (4 z zewnątrz: A, B)”, technologie
 * jako chipy i „Klient zatrudnia: …” z cytatem w jednej linii. Brak
 * menedżera = „Wskaż menedżera” prosto w karcie.
 */
function KnownProject({ card }: { card: ConsultantCardData }) {
  const known = card.known_project;
  const manager = known?.manager ?? null;
  const managerPart = manager ? (
    <Strong>{manager.name}</Strong>
  ) : card.can_edit ? (
    <ManagerPicker contractId={card.contract_id} clientId={card.client_id} />
  ) : (
    <span className="text-muted-foreground">nie wskazano</span>
  );
  if (!known) {
    return (
      <div className="space-y-1 text-sm">
        <p className="text-muted-foreground">
          Nic jeszcze nie wiemy o projekcie. Zapytaj przy rozmowie — prawa kolumna okna „Rozmowa”.
        </p>
        {/* div, nie p — „Wskaż menedżera” rozwija formularz (div w p psuje hydratację). */}
        <div className="text-muted-foreground">menedżer {managerPart}</div>
      </div>
    );
  }
  const team = teamText(known.team_size, known.team_externals, known.vendors);
  const hiringSource =
    known.hiring?.source && known.hiring.source in HIRING_SOURCE_LABELS
      ? HIRING_SOURCE_LABELS[known.hiring.source as HiringSource]
      : null;
  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-muted-foreground">
        {sourceText(card) ?? "Bez rozmowy o projekcie — to, co wiemy z kontraktu."}
      </p>
      <div className="text-muted-foreground">
        Dział {known.area ? <Strong>{known.area.name}</Strong> : "—"} · menedżer {managerPart}
        {team ? ` · ${team}` : ""}
        {known.project_end_month ? ` · projekt do ${monthYearPl(known.project_end_month)}` : ""}
      </div>
      {known.technologies.length ? (
        <ul className="flex flex-wrap gap-1" aria-label="Technologie w projekcie">
          {known.technologies.map((tech) => (
            <li key={tech.skill_id} className="rounded-md border border-border bg-muted/40 px-1.5 py-0.5 text-xs">
              {tech.name}
            </li>
          ))}
        </ul>
      ) : null}
      {known.hiring || known.quote ? (
        <p className="text-muted-foreground">
          {known.hiring ? (
            <>
              Klient zatrudnia: <Strong>{known.hiring.roles.join(", ") || "tak"}</Strong>
              {hiringSource ? ` (${hiringSource})` : ""}
            </>
          ) : null}
          {known.hiring && known.quote ? " · " : null}
          {known.quote ? <q>{known.quote}</q> : null}
        </p>
      ) : null}
    </div>
  );
}

const CASE_PILL: Record<CaseStatusTone, "info" | "warning" | "neutral"> = {
  info: "info",
  warning: "warning",
  neutral: "neutral",
};

/**
 * Wiersz sprawy (makieta S3): tytuł, „Negocjacje · ręcznie · prowadzi X ·
 * treść tylko w Sprawach”, po prawej status i termin. Cały wiersz prowadzi do
 * sprawy w „Ludziach”, gdy czytający może ją otworzyć. Na kontrakcie status
 * stoi kropką (spokojny wiersz), w panelu `/care` — plakietką jak dotąd.
 */
function CaseRow({ item, dot = false }: { item: CardCase; dot?: boolean }) {
  const pill = caseStatusPill(item);
  const when = caseWhen(item);
  const body = (
    <>
      <span className="min-w-0">
        <span className="block font-medium text-foreground">{item.title}</span>
        <span className={CALM_SUBLINE}>{caseMeta(item)}</span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-0.5">
        {dot ? (
          <StatusDot tone={CASE_PILL[pill.tone]}>{pill.label}</StatusDot>
        ) : (
          <Badge variant={CASE_PILL[pill.tone]} size="sm">
            {pill.label}
          </Badge>
        )}
        {when ? <span className="text-xs tabular-nums text-muted-foreground">{when}</span> : null}
      </span>
    </>
  );
  const rowClass = "flex items-start justify-between gap-3 py-1.5 text-sm";
  return (
    <li>
      {item.content_hidden ? (
        <div className={rowClass}>{body}</div>
      ) : (
        <Link
          href={`/people/cases/${item.id}`}
          className={cn(rowClass, "-mx-1.5 rounded-md px-1.5 hover:bg-muted/50")}
        >
          {body}
        </Link>
      )}
    </li>
  );
}

function PlanRow({
  item,
  today,
  canEdit,
  onRecord,
  onSkip,
  onRestore,
  restoring,
  withoutRhythm,
  compact = false,
}: {
  item: CardPlanItem;
  today: string;
  /** Moduł back office: rozmowa z rytmu sprzed modułu nie jest „po terminie”. */
  withoutRhythm: boolean;
  canEdit: boolean;
  onRecord: () => void;
  onSkip: () => void;
  onRestore: () => void;
  restoring: boolean;
  /** Wąska prawa kolumna kontraktu: data w drugiej linii, przyciski obok etykiety. */
  compact?: boolean;
}) {
  const overdue = planItemOverdue(item, today, withoutRhythm);
  const status =
    item.status === "done"
      ? "zrobiony"
      : item.status === "skipped"
        ? item.skip_reason
          ? `pominięty · ${SKIP_REASON_LABELS[item.skip_reason].toLowerCase()}`
          : "pominięty"
        : overdue
          ? "po terminie"
          : undefined;
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 py-1.5 text-sm">
      <StatusDot
        tone={
          item.status === "done"
            ? "success"
            : item.status === "skipped"
              ? "neutral"
              : overdue
                ? "danger"
                : "info"
        }
        note={compact ? [formatIsoDatePl(item.due_on), status].filter(Boolean).join(" · ") : status}
      >
        {compact ? item.label : `${item.label} · ${formatIsoDatePl(item.due_on)}`}
      </StatusDot>
      {canEdit && item.status === "open" ? (
        <span className="flex shrink-0 gap-1">
          <Button variant="ghost" size="sm" onClick={onRecord}>
            Zapisz
          </Button>
          <Button variant="quiet" size="sm" onClick={onSkip}>
            Pomiń
          </Button>
        </span>
      ) : null}
      {canEdit && item.status === "skipped" ? (
        <Button variant="ghost" size="sm" disabled={restoring} onClick={onRestore}>
          Przywróć
        </Button>
      ) : null}
    </li>
  );
}

type TalkTarget = {
  planItem: { id: number; label: string } | null;
  /** Tekst wpisany w strumieniu kontraktu — trafia do pola „Notatka” okna rozmowy. */
  note?: string;
  onSaved?: () => void;
};

type FeedbackTarget = { note: string; onSaved?: () => void };

/**
 * Co strumień rozmów na kontrakcie (`layout="page"`) może zrobić przez kartę:
 * otworzyć okno rozmowy z konsultantem (z najbliższym punktem planu) albo
 * okno opinii menedżera — z tekstem wpisanym w polu strumienia. `null` =
 * karta jeszcze się wczytuje albo nie ma do niej dostępu (zostają notatki).
 */
export interface CareStreamActions {
  canTalk: boolean;
  startTalk: (note: string, onSaved?: () => void) => void;
  /** Najbliższy otwarty punkt planu, który zamknie zapis rozmowy. */
  nextPlan: { label: string; due_on: string; overdue: boolean } | null;
  canFeedback: boolean;
  /** Menedżer u klienta, od którego zbiera się opinię; bez niego okna nie ma. */
  managerName: string | null;
  openFeedback: (note: string, onSaved?: () => void) => void;
}

interface ConsultantCardProps {
  contractId: number;
  /**
   * `panel` — panel boczny `/care` (bez zmian od 22.10.2026); `page` — zakładka
   * „Opieka i rozmowy” kontraktu w wariancie A (20.11.2026): wiersz z opiekunem
   * i rytmem, po lewej strumień (`stream`), po prawej następny krok, plan,
   * zadowolenie i opinie, sprawy i projekt.
   */
  layout: "panel" | "page";
  /** Akcja przy zdarzeniu „Historii” w panelu (dawniej „Edytuj” starej karty technologicznej). */
  historyAction?: (event: TimelineEvent) => ReactNode;
  /** Lewa kolumna układu `page` — strumień rozmów i notatek kontraktu. */
  stream?: (actions: CareStreamActions | null) => ReactNode;
  /**
   * Otwórz od razu okno zapisu rozmowy (przycisk „Zapisz rozmowę” w pasie
   * „Co się dzieje” na stronie kontraktu); po otwarciu karta woła `onAutoStartTalkDone`.
   */
  autoStartTalk?: boolean;
  onAutoStartTalkDone?: () => void;
}

/**
 * Jedna karta konsultanta (decyzja 3 z 22.10.2026): nagłówek ze zdrowiem
 * relacji i „dlaczego”, cztery liczby, „Następny krok” z akcją, „Co wiemy
 * o projekcie”, sprawy, jedna „Historia” z filtrami, plan kontaktów zwinięty
 * i menu „Więcej” (opiekun, rytm, pominięcie punktu planu, kontrakt) — tak
 * w panelu `/care?contract=<id>`. Na kontrakcie (`layout="page"`) te same dane
 * i akcje w układzie wariantu A; zdrowie i „dlaczego” pokazuje tam pas
 * „Co się dzieje” nad zakładkami. Z modułem back office (20.11.2026) w obu
 * układach bez rytmu: bez „Rytm kontaktu” i „Zmień rytm”, a rozmowa z rytmu
 * sprzed modułu nie jest „po terminie”. Bez stawek i danych o zdrowiu — serwer
 * ich nie wysyła.
 */
export function ConsultantCard({
  contractId,
  layout,
  historyAction,
  stream,
  autoStartTalk = false,
  onAutoStartTalkDone,
}: ConsultantCardProps) {
  const query = useConsultantCard(contractId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading" || state === "forbidden" || state === "not_found" || state === "error" || !query.data) {
    const notice =
      state === "loading" ? (
        <p className="p-4 text-sm text-muted-foreground">Wczytywanie karty konsultanta…</p>
      ) : (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={
            state === "forbidden" || state === "not_found"
              ? apiErrorMessage(query.error, "Nie możesz zobaczyć opieki tego kontraktu.")
              : "Nie udało się wczytać karty konsultanta."
          }
          onRetry={() => query.refetch()}
        />
      );
    // Na kontrakcie notatki nie czekają na kartę opieki: awaria karty to
    // komunikat w prawej kolumnie, strumień zostaje.
    if (layout === "page" && stream) {
      return (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
          <div className="min-w-0">{stream(null)}</div>
          <aside aria-label="Opieka" className="rounded-xl border border-border bg-card shadow-xs">
            {notice}
          </aside>
        </div>
      );
    }
    return notice;
  }
  return (
    <CardBody
      card={query.data}
      layout={layout}
      historyAction={historyAction}
      stream={stream}
      autoStartTalk={autoStartTalk}
      onAutoStartTalkDone={onAutoStartTalkDone}
    />
  );
}

/** Sekcja prawej kolumny kontraktu: nagłówek z liczbą i akcją, treść pod spodem. */
function SideSection({
  title,
  meta,
  action,
  children,
  label,
}: {
  title: string;
  meta?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  label?: string;
}) {
  return (
    <section aria-label={label ?? title} className="space-y-1.5 px-4 py-3">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h3 className="flex items-baseline gap-2 text-[13px] font-semibold text-foreground">
          {title}
          {meta ? <span className="text-[12px] font-normal text-muted-foreground">{meta}</span> : null}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function ValueRow({
  label,
  value,
  note,
  tone = "neutral",
}: {
  label: string;
  value: string;
  note?: string | null;
  tone?: KpiTone;
}) {
  // „—” z dopiskiem „bez oceny” czyta się jak dwa braki — zostaje sam dopisek.
  const empty = value === "—";
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-[13px]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">
        {empty ? (
          <span className="text-muted-foreground">{note ?? "—"}</span>
        ) : (
          <>
            <span className={cn("font-medium", KPI_TONE[tone])}>{value}</span>
            {note ? <span className="text-muted-foreground"> · {note}</span> : null}
          </>
        )}
      </dd>
    </div>
  );
}

function CardBody({
  card,
  layout,
  historyAction,
  stream,
  autoStartTalk = false,
  onAutoStartTalkDone,
}: {
  card: ConsultantCardData;
  layout: "panel" | "page";
  historyAction?: (event: TimelineEvent) => ReactNode;
  stream?: (actions: CareStreamActions | null) => ReactNode;
  autoStartTalk?: boolean;
  onAutoStartTalkDone?: () => void;
}) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const hr = useHrConfig();
  const restore = useUpdatePlanItem(card.contract_id);
  const handOff = useHandOffToFrontOffice(card.contract_id);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [talk, setTalk] = useState<TalkTarget | null>(null);
  const [skipping, setSkipping] = useState<CardPlanItem | null>(null);
  const [cadenceOpen, setCadenceOpen] = useState(false);
  const [ownerOpen, setOwnerOpen] = useState(false);
  const [caseOpen, setCaseOpen] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackTarget | null>(null);
  const [frontOffice, setFrontOffice] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const today = warsawToday();
  // Liczba opinii klienta w „Zadowoleniu i opiniach” (tylko kontrakt, krąg D11).
  const clientFeedback = useContractFeedback(card.contract_id, layout === "page" && card.can_see_feedback);

  const openPlan = card.plan
    .filter((item) => item.status === "open")
    .sort((a, b) => (a.due_on < b.due_on ? -1 : a.due_on > b.due_on ? 1 : 0));
  const nextPlan = openPlan[0] ?? null;
  // Do czasu wczytania konfiguracji karta jak bez modułu (menu jest zamknięte).
  const withoutRhythm = hr.data ? careWithoutRhythm(hr.data) : false;
  const nearestPlan = nearestPlanItem(openPlan, today, withoutRhythm);
  const casesOpen = Boolean(hr.data?.open_modules.cases);
  const canOpenCase = casesOpen && Boolean(hr.data?.me.cases || hr.data?.me.is_admin);
  const name = card.candidate_name ?? "Konsultant";
  const subtitle = cardSubtitle(card);
  const why = healthWhy(card.health);
  const manager = card.known_project?.manager ?? null;
  const step = card.next_step;
  const open = openCases(card.cases);
  const closedLine = closedCasesLine(card.cases);

  const startTalk = (item: CardPlanItem | null, note?: string, onSaved?: () => void) =>
    setTalk({ planItem: item ? { id: item.id, label: item.label } : null, note, onSaved });

  // „Zapisz rozmowę” z pasa „Co się dzieje”: okno zapisu otwiera się samo,
  // z najbliższym punktem planu — tak jak przycisk „Następnego kroku”.
  useEffect(() => {
    if (!autoStartTalk) return;
    if (card.can_edit) startTalk(nextPlan);
    onAutoStartTalkDone?.();
    // Jednorazowo na żądanie, nie przy każdej zmianie planu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStartTalk]);

  const handOffNow = async () => {
    const matches = step?.matches ?? [];
    const ok = await askConfirm({
      title: `Przekazać ${name} do front office?`,
      description: matches.length
        ? `Front office dostanie dzwonek z pasującymi rekrutacjami: ${matches.map((job) => job.title).join(", ")}.`
        : "Front office dostanie dzwonek bez pasujących rekrutacji — dobierze je sam.",
      confirmLabel: "Przekaż",
    });
    if (!ok) return;
    handOff.mutate(
      matches.map((job) => job.job_id),
      {
        onSuccess: (result) => {
          const message = handoffToast(result);
          showToast(message.text, message.tone);
          // „Następny krok” i historia liczą się od nowa po przekazaniu.
          void queryClient.invalidateQueries({ queryKey: careKeys.card(card.contract_id) });
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przekazać do front office."), "error"),
      },
    );
  };

  // Na kontrakcie główny przycisk to „Zapisz” w strumieniu — akcja kroku jest obok, spokojniej.
  const stepVariant = layout === "page" ? "outline" : "primary";
  const stepAction = (() => {
    if (!step?.kind) return null;
    if (step.kind === "conversation" && card.can_edit) {
      return (
        <Button size="sm" variant={stepVariant} onClick={() => startTalk(nextPlan)}>
          Zapisz rozmowę
        </Button>
      );
    }
    if (step.kind === "feedback" && card.can_see_feedback) {
      return manager ? (
        <Button size="sm" variant={stepVariant} onClick={() => setFeedback({ note: "" })}>
          Rozmowa z menedżerem
        </Button>
      ) : null;
    }
    if (step.kind === "front_office" && card.can_edit) {
      return (
        <Button size="sm" variant={stepVariant} onClick={() => void handOffNow()} loading={handOff.isPending}>
          Przekaż
        </Button>
      );
    }
    if (step.kind === "raise_cadence" && !withoutRhythm) {
      return (
        <Button size="sm" variant={stepVariant} onClick={() => setCadenceOpen(true)}>
          Zmień rytm
        </Button>
      );
    }
    return null;
  })();

  const knowledge = (
    <Section title="Co wiemy o projekcie">
      <KnownProject card={card} />
    </Section>
  );
  const cases = (
    <Section
      title={casesHeading(card.cases)}
      action={
        canOpenCase ? (
          <Button size="sm" variant="ghost" onClick={() => setCaseOpen(true)}>
            <Plus aria-hidden className="size-3.5" /> Nowa sprawa
          </Button>
        ) : null
      }
    >
      {open.length ? (
        <ul className="divide-y divide-border/60" aria-label="Sprawy konsultanta">
          {open.map((item) => (
            <CaseRow key={item.id} item={item} />
          ))}
        </ul>
      ) : card.cases.length ? null : (
        <p className="text-sm text-muted-foreground">Brak spraw z tym kontraktem.</p>
      )}
      {closedLine ? <p className="text-xs text-muted-foreground">{closedLine}</p> : null}
      {casesOpen && !canOpenCase && card.can_edit ? (
        <p className="text-xs text-muted-foreground">
          Sprawę z tym kontraktem założysz w oknie rozmowy („Coś do załatwienia?”).
        </p>
      ) : null}
    </Section>
  );
  const renderPlanRows = (compact: boolean) => card.plan.length ? (
    <ul className="divide-y divide-border/60" aria-label="Plan kontaktów">
      {card.plan.map((item) => (
        <PlanRow
          key={item.id}
          item={item}
          today={today}
          compact={compact}
          withoutRhythm={withoutRhythm}
          canEdit={card.can_edit}
          onRecord={() => startTalk(item)}
          onSkip={() => setSkipping(item)}
          restoring={restore.isPending}
          onRestore={() =>
            restore.mutate(
              { itemId: item.id, status: "open" },
              {
                onError: (err) =>
                  showToast(apiErrorMessage(err, "Nie udało się przywrócić kontaktu."), "error"),
              },
            )
          }
        />
      ))}
    </ul>
  ) : (
    <p className="py-1.5 text-sm text-muted-foreground">
      {card.start_on ? "Plan pojawi się, gdy kontrakt będzie aktywny." : "Kontrakt nie ma daty startu — plan liczy się od niej."}
    </p>
  );
  const plan = (
    <Collapsible open={planOpen} onOpenChange={setPlanOpen} className="rounded-md border border-border/60">
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted/50">
        <ChevronRight
          aria-hidden
          className={cn("size-4 text-muted-foreground transition-transform", planOpen && "rotate-90")}
        />
        Plan kontaktów
        <span className="text-xs font-normal text-muted-foreground">
          {openPlan.length ? `${openPlan.length} otwarte` : "bez otwartych"}
          {openPlan.some((item) => planItemOverdue(item, today, withoutRhythm)) ? " · po terminie" : ""}
          {nearestPlan ? ` · najbliższy ${formatDayMonthPl(nearestPlan.due_on)}` : ""}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t border-border/60 px-3 py-1">{renderPlanRows(false)}</CollapsibleContent>
    </Collapsible>
  );
  const history = <CardHistory contractId={card.contract_id} eventAction={historyAction} />;

  // Menu opiekuna, rytmu i planu — „Więcej” w panelu, „Zmień” przy opiekunie na kontrakcie.
  const menuItems = (
    <>
      {card.can_change_owner ? (
        <DropdownMenuItem onSelect={() => setOwnerOpen(true)}>Zmień opiekuna</DropdownMenuItem>
      ) : null}
      {withoutRhythm ? null : (
        <DropdownMenuItem onSelect={() => setCadenceOpen(true)}>Rytm kontaktu</DropdownMenuItem>
      )}
      {card.can_edit && nextPlan ? (
        <DropdownMenuItem onSelect={() => setSkipping(nextPlan)}>
          Pomiń punkt planu ({formatDayMonthPl(nextPlan.due_on)})
        </DropdownMenuItem>
      ) : null}
      <DropdownMenuSeparator />
      {layout === "panel" ? (
        <DropdownMenuItem asChild>
          <Link href={`/contracts/${card.contract_id}?tab=care`}>Otwórz kontrakt</Link>
        </DropdownMenuItem>
      ) : null}
      {card.candidate_id ? (
        <DropdownMenuItem asChild>
          <Link href={`/candidates/${card.candidate_id}`}>Profil kandydata</Link>
        </DropdownMenuItem>
      ) : null}
      <DropdownMenuItem asChild>
        <Link href={`/clients/${card.client_id}?tab=ludzie`}>Ludzie i technologie klienta</Link>
      </DropdownMenuItem>
    </>
  );

  const stepMatches = step?.matches?.length ? (
    <>
      <span className="font-normal text-muted-foreground"> — pasuje do </span>
      <span aria-label="Pasujące rekrutacje" role="list" className="inline">
        {step.matches.map((job, index) => (
          <span key={job.job_id} role="listitem">
            {index > 0 ? (
              <span className="font-normal text-muted-foreground">
                {index === step.matches!.length - 1 ? " i " : ", "}
              </span>
            ) : null}
            <Link
              href={`/jobs/${job.job_id}`}
              className="inline-flex items-baseline gap-1 rounded-md border border-border bg-card px-1.5 py-0.5 text-xs font-medium hover:bg-muted"
              title={job.client_name ?? undefined}
            >
              {job.title}
              <span className="tabular-nums text-muted-foreground">{job.score}</span>
            </Link>
          </span>
        ))}
      </span>
    </>
  ) : null;
  const frontOfficeToggle =
    step?.kind === "front_office" ? (
      <Button size="sm" variant="ghost" onClick={() => setFrontOffice((v) => !v)}>
        {frontOffice ? "Zwiń szczegóły" : "Więcej szczegółów"}
      </Button>
    ) : null;
  const feedbackWithoutManager =
    step?.kind === "feedback" && card.can_see_feedback && !manager ? (
      <p className="text-xs text-muted-foreground">
        Najpierw wskaż menedżera w „Co wiemy o projekcie” — opinię zbiera się od niego.
      </p>
    ) : null;

  const dialogs = (
    <>
      {talk ? (
        <ConversationDialog
          contractId={card.contract_id}
          clientId={card.client_id}
          planItem={talk.planItem}
          initialNote={talk.note}
          onSaved={talk.onSaved}
          open
          onOpenChange={(next) => {
            if (!next) setTalk(null);
          }}
        />
      ) : null}
      {skipping ? (
        <SkipPlanItemDialog
          contractId={card.contract_id}
          item={skipping}
          onOpenChange={(next) => {
            if (!next) setSkipping(null);
          }}
        />
      ) : null}
      {cadenceOpen && !withoutRhythm ? (
        <CadenceDialog contractId={card.contract_id} open onOpenChange={setCadenceOpen} />
      ) : null}
      {ownerOpen ? <OwnerDialog card={card} open onOpenChange={setOwnerOpen} /> : null}
      {caseOpen ? (
        <NewCaseDialog
          contractId={card.contract_id}
          subject={`${name} · ${card.client_name}`}
          open
          onOpenChange={setCaseOpen}
        />
      ) : null}
      {confirmDialog}
      {feedback && manager ? (
        <ClientFeedbackDialog
          clientId={card.client_id}
          clientName={card.client_name}
          manager={{ id: manager.contact_id, name: manager.name }}
          consultants={[
            {
              contract_id: card.contract_id,
              candidate_id: card.candidate_id,
              candidate_name: card.candidate_name,
              role: card.role,
              end_date: card.kpis.order_end?.on ?? card.end_on,
              end_source: card.kpis.order_end ? "order" : card.end_on ? "contract" : null,
              last_feedback: null,
            },
          ]}
          initialNote={feedback.note}
          onSaved={feedback.onSaved}
          open
          onOpenChange={(next) => {
            if (!next) setFeedback(null);
            // Opinia zmienia liczbę „Opinia menedżera” i „Następny krok”.
            if (!next) void queryClient.invalidateQueries({ queryKey: careKeys.card(card.contract_id) });
          }}
        />
      ) : null}
    </>
  );

  if (layout === "page") {
    return (
      <ContractCareLayout
        card={card}
        today={today}
        openPlan={openPlan}
        nextPlan={nextPlan}
        withoutRhythm={withoutRhythm}
        manager={manager}
        clientFeedback={clientFeedback}
        stream={stream}
        history={history}
        menuItems={menuItems}
        step={step}
        stepMatches={stepMatches}
        stepAction={stepAction}
        frontOfficeToggle={frontOfficeToggle}
        feedbackWithoutManager={feedbackWithoutManager}
        frontOffice={frontOffice}
        planRows={renderPlanRows(true)}
        openCasesList={open}
        closedLine={closedLine}
        canOpenCase={canOpenCase}
        casesHint={casesOpen && !canOpenCase && card.can_edit}
        onNewCase={() => setCaseOpen(true)}
        onStartTalk={(note, onSaved) => startTalk(nextPlan, note, onSaved)}
        onOpenFeedback={(note, onSaved) => setFeedback({ note, onSaved })}
        dialogs={dialogs}
      />
    );
  }

  return (
    <div className="space-y-4" data-testid="consultant-card" data-help="hr.care.card">
      <header className="space-y-1.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">{name}</h2>
              {card.health ? (
                <Badge variant={HEALTH_BADGE[card.health.level]} size="md">
                  {healthLabel(card.health)}
                </Badge>
              ) : null}
            </div>
            {subtitle ? (
              <p
                className="text-sm text-muted-foreground"
                title={card.owner.source ? `Opiekun: ${OWNER_SOURCE_LABELS[card.owner.source]}` : undefined}
              >
                {subtitle}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1.5 pr-10">
            {card.can_edit ? (
              <Button size="sm" onClick={() => startTalk(nextPlan)}>
                Zapisz rozmowę
              </Button>
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline" aria-label="Więcej akcji">
                  Więcej <MoreHorizontal aria-hidden className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">{menuItems}</DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {why && card.health ? (
          <p className="text-sm text-foreground">
            <span className="font-medium">Dlaczego „{healthLabel(card.health)}”:</span> {why}.
          </p>
        ) : null}
      </header>

      <section aria-label="Najważniejsze liczby">
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {cardKpis(card, today).map((kpi) => (
            <div key={kpi.label} className="rounded-lg border border-border bg-card px-3 py-2">
              <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {kpi.label}
              </dt>
              <dd className={cn("text-base font-semibold tabular-nums", KPI_TONE[kpi.tone])}>{kpi.value}</dd>
              {kpi.note ? <dd className="text-xs text-muted-foreground">{kpi.note}</dd> : null}
            </div>
          ))}
        </dl>
      </section>

      {step ? (
        <section
          aria-label="Następny krok"
          className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Następny krok
              </p>
              <p className="text-sm font-medium text-foreground">
                {step.label}
                {stepMatches}
              </p>
              {step.detail ? <p className="text-xs text-muted-foreground">{step.detail}</p> : null}
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {frontOfficeToggle}
              {stepAction}
            </div>
          </div>
          {feedbackWithoutManager}
          {frontOffice ? <FrontOfficeSection contractId={card.contract_id} /> : null}
        </section>
      ) : null}

      <div className="space-y-5">
        {knowledge}
        {cases}
        {plan}
        {history}
      </div>

      {dialogs}
    </div>
  );
}

/**
 * Układ zakładki „Opieka i rozmowy” kontraktu (wariant A, 20.11.2026): cienki
 * wiersz z opiekunem, rytmem i ostatnim kontaktem, po lewej strumień rozmów
 * i notatek, po prawej następny krok, plan kontaktów, zadowolenie i opinie,
 * sprawy i to, co wiemy o projekcie. Imię, klienta i powody „Uwaga” pokazują
 * nagłówek i pas „Co się dzieje”, więc tu ich nie ma.
 */
function ContractCareLayout({
  card,
  today,
  openPlan,
  nextPlan,
  withoutRhythm,
  manager,
  clientFeedback,
  stream,
  history,
  menuItems,
  step,
  stepMatches,
  stepAction,
  frontOfficeToggle,
  feedbackWithoutManager,
  frontOffice,
  planRows,
  openCasesList,
  closedLine,
  canOpenCase,
  casesHint,
  onNewCase,
  onStartTalk,
  onOpenFeedback,
  dialogs,
}: {
  card: ConsultantCardData;
  today: string;
  openPlan: CardPlanItem[];
  nextPlan: CardPlanItem | null;
  withoutRhythm: boolean;
  manager: { contact_id: number; name: string } | null;
  clientFeedback: ReturnType<typeof useContractFeedback>;
  stream?: (actions: CareStreamActions | null) => ReactNode;
  history: ReactNode;
  menuItems: ReactNode;
  step: ConsultantCardData["next_step"];
  stepMatches: ReactNode;
  stepAction: ReactNode;
  frontOfficeToggle: ReactNode;
  feedbackWithoutManager: ReactNode;
  frontOffice: boolean;
  planRows: ReactNode;
  openCasesList: CardCase[];
  closedLine: string | null;
  canOpenCase: boolean;
  casesHint: boolean;
  onNewCase: () => void;
  onStartTalk: (note: string, onSaved?: () => void) => void;
  onOpenFeedback: (note: string, onSaved?: () => void) => void;
  dialogs: ReactNode;
}) {
  const overduePlan = openPlan.filter((item) => planItemOverdue(item, today, withoutRhythm)).length;
  const sat = satisfactionKpi(card.kpis.satisfaction);
  const mgr = managerFeedbackKpi(card.kpis.manager_feedback, card.can_see_feedback);
  const feedbackItems = clientFeedback.data?.items ?? [];
  const latestFeedback = feedbackItems.reduce<string | null>(
    (latest, item) => (latest == null || item.held_on > latest ? item.held_on : latest),
    null,
  );
  const lastContact = card.kpis.last_contact;
  const actions: CareStreamActions = {
    canTalk: card.can_edit,
    startTalk: onStartTalk,
    nextPlan: nextPlan ? { label: nextPlan.label, due_on: nextPlan.due_on, overdue: planItemOverdue(nextPlan, today, withoutRhythm) } : null,
    canFeedback: card.can_see_feedback,
    managerName: manager?.name ?? null,
    openFeedback: onOpenFeedback,
  };
  return (
    <div className="space-y-3" data-testid="consultant-card" data-help="hr.care.card">
      <div
        role="group"
        aria-label="Opiekun i rytm"
        className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground"
      >
        <span>
          Opiekun: <span className="font-medium text-foreground">{card.owner.name ?? "bez opiekuna"}</span>
          {card.owner.source ? ` (${OWNER_SOURCE_LABELS[card.owner.source]})` : ""}
        </span>
        <span aria-hidden>·</span>
        {/* Z modułem back office rytmu rozmów nie ma (#3674) — bez „rytm: …”. */}
        {withoutRhythm ? null : (
          <>
            <span>
              rytm: <span className="font-medium text-foreground">{card.cadence?.label ?? "nie ustalono"}</span>
              {card.cadence?.until_on ? ` do ${formatIsoDatePl(card.cadence.until_on)}` : ""}
            </span>
            <span aria-hidden>·</span>
          </>
        )}
        <span>
          {lastContact ? (
            <>
              ostatni kontakt{" "}
              <span className="font-medium tabular-nums text-foreground">{formatIsoDatePl(lastContact.on)}</span>
              {` (${daysAgoText(lastContact.days_ago)})`}
            </>
          ) : (
            "jeszcze bez rozmowy"
          )}
        </span>
        <span aria-hidden>·</span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="hit-area inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
            >
              Zmień
              <ChevronDown aria-hidden className="size-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">{menuItems}</DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="min-w-0">{stream ? stream(actions) : history}</div>

        <aside aria-label="Opieka" className="divide-y divide-border/70 rounded-xl border border-border bg-card shadow-xs">
          {step ? (
            <SideSection title="Następny krok">
              <p className="text-[13px] font-medium leading-5 text-foreground">
                {step.label}
                {stepMatches}
              </p>
              {step.detail ? <p className="text-[12px] text-muted-foreground">{step.detail}</p> : null}
              {frontOfficeToggle || stepAction ? (
                <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  {stepAction}
                  {frontOfficeToggle}
                </div>
              ) : null}
              {feedbackWithoutManager}
              {frontOffice ? <FrontOfficeSection contractId={card.contract_id} /> : null}
            </SideSection>
          ) : null}

          <SideSection
            title="Plan kontaktów"
            meta={
              overduePlan
                ? countPl(overduePlan, "zaległy", "zaległe", "zaległych")
                : openPlan.length
                  ? countPl(openPlan.length, "otwarty", "otwarte", "otwartych")
                  : null
            }
          >
            {planRows}
          </SideSection>

          <SideSection
            title="Zadowolenie i opinie"
            action={
              card.can_see_feedback ? (
                <Link
                  href={`/clients/${card.client_id}?tab=struktura`}
                  className="text-[12px] font-medium text-primary hover:underline"
                >
                  Struktura u klienta
                </Link>
              ) : null
            }
          >
            <dl className="divide-y divide-border/60">
              <ValueRow label="Zadowolenie konsultanta" value={sat.value} note={sat.note} tone={sat.tone} />
              <ValueRow label="Opinia menedżera" value={mgr.value} note={mgr.note} tone={mgr.tone} />
              {card.can_see_feedback ? (
                <ValueRow
                  label="Opinie klienta"
                  value={
                    clientFeedback.isError
                      ? "niedostępne"
                      : clientFeedback.isSuccess
                        ? feedbackItems.length
                          ? countPl(feedbackItems.length, "opinia", "opinie", "opinii")
                          : "brak"
                        : "…"
                  }
                  note={latestFeedback ? `ostatnia ${formatIsoDatePl(latestFeedback)}` : null}
                />
              ) : null}
            </dl>
          </SideSection>

          <SideSection
            title="Sprawy"
            meta={openCasesList.length ? countPl(openCasesList.length, "otwarta", "otwarte", "otwartych") : null}
            action={
              canOpenCase ? (
                <Button size="sm" variant="ghost" className="-mr-2 h-7" onClick={onNewCase}>
                  <Plus aria-hidden className="size-3.5" /> Nowa sprawa
                </Button>
              ) : null
            }
          >
            {openCasesList.length ? (
              <ul className="divide-y divide-border/60" aria-label="Sprawy konsultanta">
                {openCasesList.map((item) => (
                  <CaseRow key={item.id} item={item} dot />
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-muted-foreground">Brak otwartych spraw przy tym kontrakcie.</p>
            )}
            {closedLine ? <p className="text-xs text-muted-foreground">{closedLine}</p> : null}
            {casesHint ? (
              <p className="text-xs text-muted-foreground">
                Sprawę z tym kontraktem założysz w oknie rozmowy („Coś do załatwienia?”).
              </p>
            ) : null}
          </SideSection>

          <SideSection title="Co wiemy o projekcie">
            <KnownProject card={card} />
          </SideSection>
        </aside>
      </div>
      {dialogs}
    </div>
  );
}
