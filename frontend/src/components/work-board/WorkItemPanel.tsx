"use client";

import { useState } from "react";
import Link from "next/link";
import { ExternalLink, Plus } from "lucide-react";

import { CadenceDialog } from "@/components/care/CadenceDialog";
import { NewCaseDialog } from "@/components/care/card/NewCaseDialog";
import { SkipPlanItemDialog } from "@/components/care/SkipPlanItemDialog";
import { CaseConsultantSection, CaseWhoBar } from "@/components/admin-cases/CaseConsultant";
import { PRIORITY_BADGE, STATUS_TONE, dueLabel } from "@/components/admin-cases/case-format";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  CASE_AREA_LABELS,
  CASE_SOURCE_LABELS,
  CASE_STATUS_LABELS,
  useCase,
  type CaseCard,
} from "@/lib/api/admin-cases";
import { useCareContractCardSummary, type CardCase } from "@/lib/api/care";
import type { CareBoardCard } from "@/lib/api/care-board";
import { formatDayMonthPl, formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { CareActionButton, CareQuote, demandFacts } from "./CareTile";
import { HealthWord } from "./HealthMark";
import {
  WORK_COLUMNS,
  WORK_COLUMN_LABELS,
  carePanelKicker,
  carePanelSubtitle,
  careMoveOptions,
  careStateText,
  careTileTitle,
  clientPeopleHref,
  consultantBriefRows,
  dataSummaryText,
  itemColumn,
  openPersonCases,
  planItemIdOf,
  shortPersonName,
  type WorkColumn,
  type WorkItem,
} from "./work-board-model";

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
      {children}
    </h3>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

/** Przyciski przesunięcia — ta sama ścieżka co przeciągnięcie i „Przenieś do…”. */
function MoveButtons({
  current,
  onMove,
}: {
  current: WorkColumn | "closed";
  onMove: (target: WorkColumn) => void;
}) {
  return (
    <div role="group" aria-label="Przenieś do" className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">Przenieś do:</span>
      {WORK_COLUMNS.filter((column) => column !== current).map((column) => (
        <Button key={column} size="sm" variant="outline" className="h-7 px-2.5" onClick={() => onMove(column)}>
          {WORK_COLUMN_LABELS[column]}
        </Button>
      ))}
    </div>
  );
}

function CasePanelBody({
  card,
  careAccess,
  canMove,
  onMove,
}: {
  card: CaseCard;
  careAccess: boolean;
  canMove: boolean;
  /** `fresh` = szczegół sprawy; atrapa z karty konsultanta nie ma wersji (`updated_at`). */
  onMove: (target: WorkColumn, fresh: CaseCard) => void;
}) {
  const query = useCase(card.id);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  const detail = query.data;
  // Sprawa otwarta z karty konsultanta ma tylko skrót — resztę dociąga `useCase`.
  const view: CaseCard = detail ?? card;
  const due = dueLabel(view);
  const lastComment = detail?.comments.at(-1) ?? null;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="pr-8">{view.title}</SheetTitle>
        <SheetDescription asChild>
          <div className="flex flex-wrap items-center gap-2">
            <StatusDot tone={STATUS_TONE[view.status]}>{CASE_STATUS_LABELS[view.status]}</StatusDot>
            <Badge variant={PRIORITY_BADGE[view.priority]} size="sm">
              {view.priority}
            </Badge>
            {due ? (
              <Badge variant={due.overdue ? "danger" : "outline"} size="sm">
                {due.text}
              </Badge>
            ) : null}
            <span>
              {[CASE_AREA_LABELS[view.area], CASE_SOURCE_LABELS[view.source]].filter(Boolean).join(" · ")}
            </span>
          </div>
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="space-y-4">
        {canMove && detail ? (
          <MoveButtons
            current={itemColumn({ type: "case", key: "", card: view })}
            onMove={(target) => onMove(target, detail)}
          />
        ) : null}
        {state === "loading" ? (
          <p className="text-sm text-muted-foreground">Wczytywanie sprawy…</p>
        ) : state !== "ready" || !detail ? (
          <QueryStateNotice
            state={state === "forbidden" || state === "not_found" ? state : "error"}
            onRetry={() => query.refetch()}
          />
        ) : (
          <>
            <CaseWhoBar detail={detail} />
            {detail.description ? (
              <section>
                <SectionTitle>Opis</SectionTitle>
                <p className="line-clamp-5 whitespace-pre-line break-words text-sm text-foreground">
                  {detail.description}
                </p>
              </section>
            ) : null}
            <section>
              <SectionTitle>Szczegóły</SectionTitle>
              <Row label="Osoba odpowiedzialna">{detail.assignee?.name ?? "nikt"}</Row>
              <Row label="Termin">{formatIsoDatePl(detail.due_on)}</Row>
              {detail.follow_up_on ? <Row label="Kontakt">{formatIsoDatePl(detail.follow_up_on)}</Row> : null}
            </section>
            {detail.checklist.length ? (
              <section>
                <SectionTitle>
                  Checklista · {detail.checklist.filter((item) => item.done).length}/
                  {detail.checklist.length}
                </SectionTitle>
                <ul className="space-y-1 text-sm">
                  {detail.checklist.map((item, index) => (
                    <li key={`${index}-${item.text}`} className="flex items-start gap-2">
                      <span
                        aria-hidden
                        className={
                          item.done
                            ? "mt-1 size-3 shrink-0 rounded-sm bg-primary"
                            : "mt-1 size-3 shrink-0 rounded-sm border border-border"
                        }
                      />
                      <span className={item.done ? "text-muted-foreground line-through" : "text-foreground"}>
                        <span className="sr-only">{item.done ? "zrobione: " : "do zrobienia: "}</span>
                        {item.text}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            <section>
              <SectionTitle>Ostatni komentarz</SectionTitle>
              {lastComment ? (
                <div className="text-sm">
                  <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {lastComment.author?.name ?? "Konto usunięte"}
                    </span>
                    <span>{formatMomentPl(lastComment.created_at)}</span>
                  </div>
                  <p className="mt-0.5 line-clamp-4 whitespace-pre-line break-words">{lastComment.body}</p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Nikt jeszcze nie skomentował.</p>
              )}
            </section>
            {detail.contract && detail.can_manage ? (
              <section className="rounded-lg border border-border p-3">
                <SectionTitle>Konsultant</SectionTitle>
                <CaseConsultantSection detail={detail} careAccess={careAccess} />
              </section>
            ) : null}
          </>
        )}
        <Button variant="tertiary" className="px-0" asChild>
          <Link href={`/people/cases/${card.id}`}>
            <ExternalLink className="h-4 w-4" aria-hidden />
            Pełny widok sprawy
          </Link>
        </Button>
      </SheetBody>
    </>
  );
}

function BriefSection({
  card,
  onOpenCase,
  canCreateCase,
}: {
  card: CareBoardCard;
  onOpenCase: (item: CardCase) => void;
  canCreateCase: boolean;
}) {
  const query = useCareContractCardSummary(card.contract_id ?? null);
  const [creating, setCreating] = useState(false);
  if (!card.contract_id) return null;
  if (query.isLoading) {
    return <p className="text-sm text-muted-foreground">Wczytywanie karty konsultanta…</p>;
  }
  if (query.isError || !query.data) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać karty konsultanta."
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  const cases = openPersonCases(data.cases);
  const name = data.candidate_name ?? card.title;
  return (
    <>
      <section>
        <SectionTitle>Konsultant w skrócie</SectionTitle>
        {consultantBriefRows(card, data).map((row) => (
          <Row key={row.label} label={row.label}>
            {row.value}
          </Row>
        ))}
      </section>
      <section>
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <SectionTitle>Sprawy tej osoby · {cases.length}</SectionTitle>
          {canCreateCase ? (
            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setCreating(true)}>
              <Plus className="h-3.5 w-3.5" aria-hidden />
              Nowa sprawa
            </Button>
          ) : null}
        </div>
        {cases.length ? (
          <ul className="space-y-1">
            {cases.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onOpenCase(item)}
                  aria-label={`Sprawa: ${item.title}`}
                  className="flex w-full items-baseline justify-between gap-2 rounded-md px-1.5 py-1 text-left text-sm hover:bg-muted"
                >
                  <span className="min-w-0 truncate">
                    <span className="font-medium text-foreground">{item.title}</span>
                    {item.assignee_name ? (
                      <span className="text-muted-foreground"> · prowadzi {shortPersonName(item.assignee_name)}</span>
                    ) : null}
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                    <Badge size="sm" variant={item.status === "waiting" ? "warning" : "neutral"}>
                      {item.status_label}
                    </Badge>
                    {item.status === "waiting" && item.follow_up_on
                      ? formatDayMonthPl(item.follow_up_on)
                      : item.due_on
                        ? `do ${formatDayMonthPl(item.due_on)}`
                        : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Brak otwartych spraw.</p>
        )}
      </section>
      {creating ? (
        <NewCaseDialog
          contractId={card.contract_id}
          subject={[name, data.client_name].filter(Boolean).join(" · ")}
          open
          onOpenChange={setCreating}
        />
      ) : null}
    </>
  );
}

/** „Przenieś na tablicy” (K2): trzy pola z podpowiedzią; „Zrobione” daje tylko zapis. */
function CareMoveChoices({
  card,
  onMove,
}: {
  card: CareBoardCard;
  onMove: (target: WorkColumn) => void;
}) {
  const options = careMoveOptions(card.kind);
  if (!options.length) return null;
  return (
    <section>
      <SectionTitle>Przenieś na tablicy</SectionTitle>
      <div role="group" aria-label="Przenieś na tablicy" className="grid gap-1.5 sm:grid-cols-3">
        {options.map((option) => {
          const current = option.column === card.column;
          return (
            <button
              key={option.column}
              type="button"
              aria-pressed={current}
              onClick={() => onMove(option.column)}
              className={cn(
                "rounded-lg border px-2.5 py-2 text-left text-sm transition-colors",
                current
                  ? "border-primary/40 bg-primary/10 text-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}
            >
              <span className="block font-medium">{option.label}</span>
              <span className="block text-xs text-muted-foreground">{option.hint}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function CarePanelBody({
  card,
  onMove,
  onAction,
  onOpenCase,
  onOpenContract,
  canCreateCase,
}: {
  card: CareBoardCard;
  onMove: (target: WorkColumn) => void;
  onAction: (() => void) | null;
  onOpenCase: (item: CardCase) => void;
  onOpenContract?: (contractId: number) => void;
  canCreateCase: boolean;
}) {
  const state = careStateText(card);
  const subtitle = carePanelSubtitle(card);
  const facts = card.kind === "data" && card.data ? dataSummaryText(card.data) : demandFacts(card);
  const planItemId = planItemIdOf(card.key);
  const [cadenceOpen, setCadenceOpen] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const contractId = card.contract_id ?? null;
  return (
    <>
      <SheetHeader>
        <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          {carePanelKicker(card)}
        </p>
        <SheetTitle className="pr-8">{careTileTitle(card)}</SheetTitle>
        <SheetDescription asChild>
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            {subtitle ? <span>{subtitle}</span> : null}
            {card.health ? (
              <>
                {subtitle ? <span aria-hidden>·</span> : null}
                <HealthWord health={card.health} />
              </>
            ) : null}
          </div>
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="space-y-4">
        <CareActionButton card={card} onAction={onAction} />
        <CareMoveChoices card={card} onMove={onMove} />
        {state ? <p className="rounded-md bg-muted/60 px-2 py-1 text-sm">{state}</p> : null}
        {card.health?.reasons.length ? (
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Dlaczego „{card.health.label}”: </span>
            {card.health.reasons.join("; ")}.
          </p>
        ) : null}
        {facts ? <p className="text-sm text-foreground">{facts}</p> : null}
        {card.kind === "decision" || (card.kind !== "contact" && card.note_excerpt) ? (
          <CareQuote card={card} className="rounded-md bg-muted/60 px-2 py-1 text-sm" />
        ) : null}
        {card.demand ? (
          <section>
            <SectionTitle>Popyt</SectionTitle>
            <Row label="Role">{card.demand.roles.join(", ") || "—"}</Row>
            <Row label="Dział">{card.demand.area?.name ?? "nie wskazano"}</Row>
            {card.demand.source ? <Row label="Źródło">{card.demand.source}</Row> : null}
          </section>
        ) : null}
        {card.kind === "feedback" ? (
          <section>
            <SectionTitle>U klienta</SectionTitle>
            <Row label="Klient">{card.client_name ?? "—"}</Row>
            {card.last_feedback ? (
              <Row label="Ostatnia opinia">
                {formatDayMonthPl(card.last_feedback.held_on)}
                {card.last_feedback.average != null ? ` · ${card.last_feedback.average.toFixed(1)} / 5` : ""}
              </Row>
            ) : null}
            {card.consultants?.length ? (
              <ul className="mt-1 space-y-0.5 text-sm">
                {card.consultants.map((person) => (
                  <li key={person.contract_id}>
                    <Link href={`/care?contract=${person.contract_id}`} className="text-primary hover:underline">
                      {person.name}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
        {card.kind === "contact" || card.kind === "decision" ? (
          <BriefSection card={card} onOpenCase={onOpenCase} canCreateCase={canCreateCase} />
        ) : null}
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {contractId ? (
            onOpenContract ? (
              <Button size="sm" variant="outline" onClick={() => onOpenContract(contractId)}>
                <ExternalLink className="h-4 w-4" aria-hidden />
                Otwórz pełną kartę konsultanta
              </Button>
            ) : (
              <Button size="sm" variant="outline" asChild>
                <Link href={`/care?contract=${contractId}`}>
                  <ExternalLink className="h-4 w-4" aria-hidden />
                  Otwórz pełną kartę konsultanta
                </Link>
              </Button>
            )
          ) : card.client_id ? (
            <Button size="sm" variant="outline" asChild>
              <Link href={clientPeopleHref(card.client_id)}>
                <ExternalLink className="h-4 w-4" aria-hidden />
                Ludzie i technologie klienta
              </Link>
            </Button>
          ) : null}
          {contractId && card.kind === "contact" ? (
            <Button size="sm" variant="ghost" onClick={() => setCadenceOpen(true)}>
              Zmień rytm
            </Button>
          ) : null}
          {contractId && planItemId != null ? (
            <Button size="sm" variant="ghost" onClick={() => setSkipping(true)}>
              Pomiń z powodem
            </Button>
          ) : null}
        </div>
      </SheetBody>
      {cadenceOpen && contractId ? (
        <CadenceDialog contractId={contractId} open onOpenChange={setCadenceOpen} />
      ) : null}
      {skipping && contractId && planItemId != null ? (
        <SkipPlanItemDialog
          contractId={contractId}
          item={{ id: planItemId, label: card.reason_label ?? "Rozmowa", due_on: card.due_on ?? "" }}
          onOpenChange={(open) => {
            if (!open) setSkipping(false);
          }}
        />
      ) : null}
    </>
  );
}

/**
 * Panel boczny karty tablicy (klik w kartę — nie nowa strona). Sprawa: skrót
 * z checklistą, ostatnim komentarzem, sekcją „Konsultant” albo „Kogo
 * dotyczy?” i linkiem do pełnego widoku. Karta opieki (makieta K2): nagłówek
 * „OPIEKA · ROZMOWA · DZIEŃ 30 · 3 DNI PO TERMINIE”, akcja, „Przenieś na
 * tablicy” (trzy pola z podpowiedzią), „Konsultant w skrócie”, „Sprawy tej
 * osoby” z „+ Nowa sprawa” (klik w sprawę otwiera ten sam panel), stopka
 * „Otwórz pełną kartę konsultanta” · „Zmień rytm” · „Pomiń z powodem”.
 */
export function WorkItemPanel({
  item,
  onClose,
  careAccess,
  canManageCases,
  onMove,
  careAction,
  onOpenCase,
  onOpenContract,
  canCreateCase = false,
}: {
  item: WorkItem | null;
  onClose: () => void;
  /** Zostają w kształcie propsów (ten sam panel co tablica); termin liczy karta. */
  today?: string;
  weekEnd?: string;
  careAccess: boolean;
  canManageCases: boolean;
  onMove: (item: WorkItem, target: WorkColumn) => void;
  careAction: (card: CareBoardCard) => (() => void) | null;
  /** Klik w sprawę z „Sprawy tej osoby” — ten sam panel ze sprawą. */
  onOpenCase: (item: CardCase) => void;
  /** Karta konsultanta w panelu ekranu (/care); bez niej — link `/care?contract=`. */
  onOpenContract?: (contractId: number) => void;
  /** „+ Nowa sprawa” — obsługa skrzynki (uprawnienie „Sprawy”) i admin. */
  canCreateCase?: boolean;
}) {
  return (
    <Sheet open={item !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <SheetContent
        side="right"
        size="md"
        // Fokus na panelu, nie na pierwszym przycisku „Przenieś do” (klik w kartę to podgląd, nie ruch).
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          (event.currentTarget as HTMLElement | null)?.focus();
        }}
      >
        {item?.type === "case" ? (
          <CasePanelBody
            key={item.key}
            card={item.card}
            careAccess={careAccess}
            canMove={canManageCases}
            onMove={(target, fresh) => onMove({ ...item, card: fresh }, target)}
          />
        ) : item?.type === "care" ? (
          <CarePanelBody
            key={item.key}
            card={item.card}
            onMove={(target) => onMove(item, target)}
            onAction={careAction(item.card)}
            onOpenCase={onOpenCase}
            onOpenContract={
              onOpenContract
                ? (id) => {
                    onClose();
                    onOpenContract(id);
                  }
                : undefined
            }
            canCreateCase={canCreateCase}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
