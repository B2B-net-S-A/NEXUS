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

import { CadenceDialog } from "../CadenceDialog";
import { contractForm } from "../cadence-format";
import { ClientFeedbackDialog } from "../ClientFeedbackDialog";
import { ConversationDialog } from "../ConversationDialog";
import { HEALTH_BADGE, healthLabel, healthWhy } from "../health-format";
import { SkipPlanItemDialog } from "../SkipPlanItemDialog";
import { FrontOfficeSection } from "../week/FrontOfficeSection";
import { CardHistory } from "./CardHistory";
import { cardKpis, casesHeading, openCases, type KpiTone } from "./card-format";
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

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

function sourceText(card: ConsultantCardData): string | null {
  const source = card.known_project?.source;
  if (!source) return null;
  return [
    source.kind === "tech_card" ? "z karty technologicznej" : "z rozmowy",
    formatIsoDatePl(source.on),
    source.author_name,
  ]
    .filter(Boolean)
    .join(" · ");
}

function KnownProject({ card }: { card: ConsultantCardData }) {
  const known = card.known_project;
  if (!known) {
    return (
      <p className="text-sm text-muted-foreground">
        Nic jeszcze nie wiemy o projekcie. Zapytaj przy rozmowie — prawa kolumna okna „Rozmowa”.
      </p>
    );
  }
  const team = [
    known.team_size ? `${known.team_size} osób` : null,
    known.team_externals != null ? `z zewnątrz ${known.team_externals}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {sourceText(card) ?? "Bez rozmowy o projekcie — to, co wiemy z kontraktu."}
      </p>
      <dl className="grid gap-1">
        <Fact label="Dział">{known.area?.name ?? "—"}</Fact>
        <Fact label="Menedżer">
          {known.manager
            ? `${known.manager.name}${known.manager.position ? ` · ${known.manager.position}` : ""}`
            : "nie wskazano"}
        </Fact>
        {team ? <Fact label="Zespół">{team}</Fact> : null}
        <Fact label="Technologie">
          {known.technologies.length ? (
            <ul className="flex flex-wrap gap-1" aria-label="Technologie w projekcie">
              {known.technologies.map((tech) => (
                <li
                  key={tech.skill_id}
                  className="rounded-md border border-border bg-muted/40 px-1.5 py-0.5 text-xs"
                >
                  {tech.name}
                </li>
              ))}
            </ul>
          ) : (
            "—"
          )}
        </Fact>
        {known.vendors.length ? <Fact label="Inni dostawcy">{known.vendors.join(", ")}</Fact> : null}
        {known.project_end_month ? (
          <Fact label="Koniec projektu">{monthYearPl(known.project_end_month)}</Fact>
        ) : null}
        {known.hiring ? (
          <Fact label="Klient zatrudnia">
            {known.hiring.roles.join(", ") || "tak"}
            {known.hiring.source && known.hiring.source in HIRING_SOURCE_LABELS
              ? ` · ${HIRING_SOURCE_LABELS[known.hiring.source as HiringSource]}`
              : ""}
          </Fact>
        ) : null}
      </dl>
      {known.quote ? <q className="block text-sm text-muted-foreground">{known.quote}</q> : null}
    </div>
  );
}

function CaseRow({ item }: { item: CardCase }) {
  const meta = [
    item.area_label,
    item.status_label,
    item.due_on ? `termin ${formatDayMonthPl(item.due_on)}` : null,
    item.assignee_name ?? "bez osoby",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="py-1.5 text-sm">
      {item.content_hidden ? (
        <span className="font-medium">{item.title}</span>
      ) : (
        <Link href={`/people/cases/${item.id}`} className="font-medium hover:underline">
          {item.title}
        </Link>
      )}
      <span className={CALM_SUBLINE}>{meta}</span>
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

const KNOWN_FORMS = ["b2b", "uop", "uzlecenie"] as const;

/** „B2B”, „Zlecenie” — forma ze słownika; nieznana zostaje tekstem z serwera. */
function formText(form: string | null): string | null {
  if (!form) return null;
  const known = KNOWN_FORMS.find((value) => value === form);
  return known ? contractForm(known) : form;
}

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
  const subtitle = [
    card.role,
    formText(card.form),
    card.client_name,
    card.start_on ? `od ${formatIsoDatePl(card.start_on)}` : null,
    card.end_on ? `umowa do ${formatIsoDatePl(card.end_on)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const why = healthWhy(card.health);
  const ownerLine = [
    card.owner.name ? `Opiekun: ${card.owner.name}` : "Bez opiekuna",
    card.owner.source ? OWNER_SOURCE_LABELS[card.owner.source] : null,
    card.cadence
      ? `rytm ${card.cadence.label}${card.cadence.until_on ? ` do ${formatDayMonthPl(card.cadence.until_on)}` : ""}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const manager = card.known_project?.manager ?? null;
  const step = card.next_step;
  const open = openCases(card.cases);

  const startTalk = (item: CardPlanItem | null) =>
    setTalk({ planItem: item ? { id: item.id, label: item.label } : null });

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
      ) : (
        <Button size="sm" variant="outline" asChild>
          <Link href={`/clients/${card.client_id}?tab=ludzie`}>Wskaż menedżera</Link>
        </Button>
      );
    }
    if (step.kind === "front_office") {
      return (
        <Button size="sm" variant={frontOffice ? "ghost" : "primary"} onClick={() => setFrontOffice((v) => !v)}>
          {frontOffice ? "Zwiń" : "Przekaż do front office"}
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
      {card.cases.length ? (
        <ul className="divide-y divide-border/60" aria-label="Sprawy konsultanta">
          {[...open, ...card.cases.filter((item) => !open.includes(item))].map((item) => (
            <CaseRow key={item.id} item={item} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Brak spraw z tym kontraktem.</p>
      )}
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
            {subtitle ? <p className="text-sm text-muted-foreground">{subtitle}</p> : null}
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
        {why ? (
          <p className="text-sm text-foreground">
            <span className="text-muted-foreground">Dlaczego: </span>
            {why}
          </p>
        ) : null}
        <p className="text-xs text-muted-foreground">{ownerLine}</p>
      </header>

      <section aria-label="Najważniejsze liczby">
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {cardKpis(card).map((kpi) => (
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
              <p className="text-sm font-medium text-foreground">{step.label}</p>
              {step.detail ? <p className="text-xs text-muted-foreground">{step.detail}</p> : null}
            </div>
            {stepAction}
          </div>
          {step.matches?.length && !frontOffice ? (
            <ul className="space-y-0.5 text-sm" aria-label="Pasujące rekrutacje">
              {step.matches.map((job) => (
                <li key={job.job_id}>
                  <Link href={`/jobs/${job.job_id}`} className="hover:underline">
                    {job.title}
                  </Link>
                  <span className="text-xs text-muted-foreground">
                    {" "}
                    · {[job.client_name, `dopasowanie ${job.score}`].filter(Boolean).join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
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
