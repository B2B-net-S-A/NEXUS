"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, MoreHorizontal, Plus } from "lucide-react";

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
  openCases,
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
 * sprawy w „Ludziach”, gdy czytający może ją otworzyć.
 */
function CaseRow({ item }: { item: CardCase }) {
  const pill = caseStatusPill(item);
  const when = caseWhen(item);
  const body = (
    <>
      <span className="min-w-0">
        <span className="block font-medium text-foreground">{item.title}</span>
        <span className={CALM_SUBLINE}>{caseMeta(item)}</span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-0.5">
        <Badge variant={CASE_PILL[pill.tone]} size="sm">
          {pill.label}
        </Badge>
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
}: {
  item: CardPlanItem;
  today: string;
  canEdit: boolean;
  onRecord: () => void;
  onSkip: () => void;
  onRestore: () => void;
  restoring: boolean;
}) {
  const overdue = item.status === "open" && item.due_on < today;
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
        note={
          item.status === "done"
            ? "zrobiony"
            : item.status === "skipped"
              ? item.skip_reason
                ? `pominięty · ${SKIP_REASON_LABELS[item.skip_reason].toLowerCase()}`
                : "pominięty"
              : overdue
                ? "po terminie"
                : undefined
        }
      >
        {item.label} · {formatIsoDatePl(item.due_on)}
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

type TalkTarget = { planItem: { id: number; label: string } | null };

interface ConsultantCardProps {
  contractId: number;
  /** `panel` — panel boczny `/care`; `page` — zakładka „Opieka” kontraktu na pełną szerokość. */
  layout: "panel" | "page";
  /** Akcja przy zdarzeniu „Historii” (zakładka kontraktu: „Edytuj” starej karty technologicznej). */
  historyAction?: (event: TimelineEvent) => ReactNode;
}

/**
 * Jedna karta konsultanta (decyzja 3 z 22.10.2026): nagłówek ze zdrowiem
 * relacji i „dlaczego”, cztery liczby, „Następny krok” z akcją, „Co wiemy
 * o projekcie”, sprawy, jedna „Historia” z filtrami, plan kontaktów zwinięty
 * i menu „Więcej” (opiekun, rytm, pominięcie punktu planu, kontrakt). Ten sam
 * komponent w panelu `/care?contract=<id>` i w zakładce „Opieka” kontraktu.
 * Bez stawek i danych o zdrowiu — serwer ich nie wysyła.
 */
export function ConsultantCard({ contractId, layout, historyAction }: ConsultantCardProps) {
  const query = useConsultantCard(contractId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <p className="p-4 text-sm text-muted-foreground">Wczytywanie karty konsultanta…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !query.data) {
    return (
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
  }
  return <CardBody card={query.data} layout={layout} historyAction={historyAction} />;
}

function CardBody({
  card,
  layout,
  historyAction,
}: {
  card: ConsultantCardData;
  layout: "panel" | "page";
  historyAction?: (event: TimelineEvent) => ReactNode;
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
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [frontOffice, setFrontOffice] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const today = warsawToday();

  const openPlan = card.plan
    .filter((item) => item.status === "open")
    .sort((a, b) => (a.due_on < b.due_on ? -1 : a.due_on > b.due_on ? 1 : 0));
  const nextPlan = openPlan[0] ?? null;
  const casesOpen = Boolean(hr.data?.open_modules.cases);
  const canOpenCase = casesOpen && Boolean(hr.data?.me.cases || hr.data?.me.is_admin);
  const name = card.candidate_name ?? "Konsultant";
  const subtitle = cardSubtitle(card);
  const why = healthWhy(card.health);
  const manager = card.known_project?.manager ?? null;
  const step = card.next_step;
  const open = openCases(card.cases);
  const closedLine = closedCasesLine(card.cases);

  const startTalk = (item: CardPlanItem | null) =>
    setTalk({ planItem: item ? { id: item.id, label: item.label } : null });

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

  const stepAction = (() => {
    if (!step?.kind) return null;
    if (step.kind === "conversation" && card.can_edit) {
      return (
        <Button size="sm" onClick={() => startTalk(nextPlan)}>
          Zapisz rozmowę
        </Button>
      );
    }
    if (step.kind === "feedback" && card.can_see_feedback) {
      return manager ? (
        <Button size="sm" onClick={() => setFeedbackOpen(true)}>
          Rozmowa z menedżerem
        </Button>
      ) : null;
    }
    if (step.kind === "front_office" && card.can_edit) {
      return (
        <Button size="sm" onClick={() => void handOffNow()} loading={handOff.isPending}>
          Przekaż
        </Button>
      );
    }
    if (step.kind === "raise_cadence") {
      return (
        <Button size="sm" onClick={() => setCadenceOpen(true)}>
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
          {openPlan.some((item) => item.due_on < today) ? " · po terminie" : ""}
          {nextPlan ? ` · najbliższy ${formatDayMonthPl(nextPlan.due_on)}` : ""}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t border-border/60 px-3 py-1">
        {card.plan.length ? (
          <ul className="divide-y divide-border/60" aria-label="Plan kontaktów">
            {card.plan.map((item) => (
              <PlanRow
                key={item.id}
                item={item}
                today={today}
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
        )}
      </CollapsibleContent>
    </Collapsible>
  );
  const history = <CardHistory contractId={card.contract_id} eventAction={historyAction} />;

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
          <div className={cn("flex shrink-0 items-center gap-1.5", layout === "panel" && "pr-10")}>
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
              <DropdownMenuContent align="end">
                {card.can_change_owner ? (
                  <DropdownMenuItem onSelect={() => setOwnerOpen(true)}>Zmień opiekuna</DropdownMenuItem>
                ) : null}
                <DropdownMenuItem onSelect={() => setCadenceOpen(true)}>Rytm kontaktu</DropdownMenuItem>
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
              </DropdownMenuContent>
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
                {step.matches?.length ? (
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
                ) : null}
              </p>
              {step.detail ? <p className="text-xs text-muted-foreground">{step.detail}</p> : null}
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {step.kind === "front_office" ? (
                <Button size="sm" variant="ghost" onClick={() => setFrontOffice((v) => !v)}>
                  {frontOffice ? "Zwiń szczegóły" : "Więcej szczegółów"}
                </Button>
              ) : null}
              {stepAction}
            </div>
          </div>
          {step.kind === "feedback" && card.can_see_feedback && !manager ? (
            <p className="text-xs text-muted-foreground">
              Najpierw wskaż menedżera w „Co wiemy o projekcie” — opinię zbiera się od niego.
            </p>
          ) : null}
          {frontOffice ? <FrontOfficeSection contractId={card.contract_id} /> : null}
        </section>
      ) : null}

      {layout === "page" ? (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="space-y-5">
            {knowledge}
            {cases}
            {plan}
          </div>
          <div className="rounded-lg border border-border bg-card p-3">{history}</div>
        </div>
      ) : (
        <div className="space-y-5">
          {knowledge}
          {cases}
          {plan}
          {history}
        </div>
      )}

      {talk ? (
        <ConversationDialog
          contractId={card.contract_id}
          clientId={card.client_id}
          planItem={talk.planItem}
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
      {cadenceOpen ? (
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
      {feedbackOpen && manager ? (
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
          open
          onOpenChange={(next) => {
            setFeedbackOpen(next);
            // Opinia zmienia liczbę „Opinia menedżera” i „Następny krok”.
            if (!next) void queryClient.invalidateQueries({ queryKey: careKeys.card(card.contract_id) });
          }}
        />
      ) : null}
    </div>
  );
}
