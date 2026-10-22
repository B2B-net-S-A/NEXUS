"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

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
import { useCareContractCardSummary } from "@/lib/api/care";
import { CARE_KIND_LABELS, type CareBoardCard } from "@/lib/api/care-board";
import { formatDayMonthPl, formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";

import { CareActionButton, careStateNote } from "./CareTile";
import { HealthWord } from "./HealthMark";
import {
  WORK_COLUMNS,
  WORK_COLUMN_LABELS,
  careDueBadge,
  itemColumn,
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
  onMove: (target: WorkColumn) => void;
}) {
  const query = useCase(card.id);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  const detail = query.data;
  const due = dueLabel(detail ?? card);
  const lastComment = detail?.comments.at(-1) ?? null;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="pr-8">{card.title}</SheetTitle>
        <SheetDescription asChild>
          <div className="flex flex-wrap items-center gap-2">
            <StatusDot tone={STATUS_TONE[detail?.status ?? card.status]}>
              {CASE_STATUS_LABELS[detail?.status ?? card.status]}
            </StatusDot>
            <Badge variant={PRIORITY_BADGE[card.priority]} size="sm">
              {card.priority}
            </Badge>
            {due ? (
              <Badge variant={due.overdue ? "danger" : "outline"} size="sm">
                {due.text}
              </Badge>
            ) : null}
            <span>
              {CASE_AREA_LABELS[card.area]} · {CASE_SOURCE_LABELS[card.source]}
            </span>
          </div>
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="space-y-4">
        {canMove ? <MoveButtons current={itemColumn({ type: "case", key: "", card })} onMove={onMove} /> : null}
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
            {detail.contract ? (
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

function CareContractSummary({ card }: { card: CareBoardCard }) {
  const query = useCareContractCardSummary(card.contract_id ?? null);
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
  const manager = data.known_project?.manager ?? null;
  const openCases = data.cases.filter((item) => item.status !== "done" && item.status !== "closed");
  return (
    <section className="space-y-2">
      <SectionTitle>Konsultant</SectionTitle>
      <div>
        <Row label="Ostatnia rozmowa">
          {data.kpis.last_contact
            ? `${formatDayMonthPl(data.kpis.last_contact.on)} · ${countPl(data.kpis.last_contact.days_ago, "dzień", "dni", "dni")} temu`
            : "jeszcze nie było"}
        </Row>
        <Row label="Menedżer u klienta">
          {manager ? [manager.name, manager.position].filter(Boolean).join(" · ") : (card.manager?.name ?? "nie wskazano")}
        </Row>
        <Row label="Koniec zamówienia">
          {data.kpis.order_end
            ? `${formatIsoDatePl(data.kpis.order_end.on)} · za ${countPl(data.kpis.order_end.days, "dzień", "dni", "dni")}`
            : "bez końca"}
        </Row>
        <Row label="Rytm">{data.cadence?.label ?? "—"}</Row>
        <Row label="Opiekun">{data.owner?.name ?? "nikt"}</Row>
      </div>
      <div>
        <SectionTitle>Sprawy osoby</SectionTitle>
        {openCases.length ? (
          <ul className="space-y-1 text-sm">
            {openCases.map((item) => (
              <li key={item.id} className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate">
                  {item.title}
                  <span className="text-muted-foreground"> · {item.area_label}</span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {item.status_label}
                  {item.due_on ? ` · do ${formatDayMonthPl(item.due_on)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Brak otwartych spraw.</p>
        )}
      </div>
    </section>
  );
}

function CarePanelBody({
  card,
  today,
  weekEnd,
  onMove,
  onAction,
}: {
  card: CareBoardCard;
  today?: string;
  weekEnd?: string;
  onMove: (target: WorkColumn) => void;
  onAction: (() => void) | null;
}) {
  const due = careDueBadge(card, today, weekEnd);
  const state = careStateNote(card);
  return (
    <>
      <SheetHeader>
        <SheetTitle className="pr-8">{card.title}</SheetTitle>
        <SheetDescription asChild>
          <div className="flex flex-wrap items-center gap-2">
            <Badge size="sm" variant="soft">
              Opieka
            </Badge>
            <span>{CARE_KIND_LABELS[card.kind]}</span>
            <StatusDot tone={card.column === "new" ? "info" : card.column === "in_progress" ? "warning" : "neutral"}>
              {WORK_COLUMN_LABELS[card.column]}
            </StatusDot>
            {due ? (
              <Badge size="sm" variant={due.tone === "overdue" ? "danger" : due.tone === "week" ? "warning" : "outline"}>
                {due.text}
              </Badge>
            ) : null}
          </div>
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="space-y-4">
        <MoveButtons current={card.column} onMove={onMove} />
        <CareActionButton card={card} onAction={onAction} />
        {card.subtitle || card.reason_label ? (
          <p className="text-sm text-muted-foreground">
            {[card.subtitle, card.reason_label].filter(Boolean).join(" · ")}
          </p>
        ) : null}
        {state ? <p className="rounded-md bg-muted/60 px-2 py-1 text-sm">{state}</p> : null}
        {card.health ? (
          <section>
            <SectionTitle>Zdrowie relacji</SectionTitle>
            <HealthWord health={card.health} className="text-sm" />
            {card.health.reasons.length ? (
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                {card.health.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
        {card.note_excerpt ? (
          <section>
            <SectionTitle>Z ostatniej rozmowy</SectionTitle>
            <p className="rounded-md bg-muted/60 px-2 py-1 text-sm">„{card.note_excerpt}”</p>
          </section>
        ) : null}
        {card.demand ? (
          <section>
            <SectionTitle>Popyt</SectionTitle>
            <Row label="Role">{card.demand.roles.join(", ") || "—"}</Row>
            <Row label="Dział">{card.demand.area?.name ?? "nie wskazano"}</Row>
            {card.demand.source ? <Row label="Źródło">{card.demand.source}</Row> : null}
          </section>
        ) : null}
        {!card.contract_id ? (
          <section>
            <SectionTitle>U klienta</SectionTitle>
            <Row label="Klient">{card.client_name ?? "—"}</Row>
            {card.manager ? <Row label="Menedżer">{card.manager.name}</Row> : null}
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
        <CareContractSummary card={card} />
        {card.contract_id ? (
          <Button variant="tertiary" className="px-0" asChild>
            <Link href={`/care?contract=${card.contract_id}`}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              Otwórz pełną kartę konsultanta
            </Link>
          </Button>
        ) : card.client_id ? (
          <Button variant="tertiary" className="px-0" asChild>
            <Link href={`/clients/${card.client_id}?tab=ludzie`}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              Ludzie i technologie klienta
            </Link>
          </Button>
        ) : null}
      </SheetBody>
    </>
  );
}

/**
 * Panel boczny karty tablicy (klik w kartę — nie nowa strona). Sprawa: skrót
 * z checklistą, ostatnim komentarzem, sekcją „Konsultant” albo „Kogo
 * dotyczy?” i linkiem do pełnego widoku. Karta opieki: przesunięcia, akcja,
 * skrót Karty konsultanta i link do pełnej karty.
 */
export function WorkItemPanel({
  item,
  onClose,
  today,
  weekEnd,
  careAccess,
  canManageCases,
  onMove,
  careAction,
}: {
  item: WorkItem | null;
  onClose: () => void;
  today?: string;
  weekEnd?: string;
  careAccess: boolean;
  canManageCases: boolean;
  onMove: (item: WorkItem, target: WorkColumn) => void;
  careAction: (card: CareBoardCard) => (() => void) | null;
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
            onMove={(target) => onMove(item, target)}
          />
        ) : item?.type === "care" ? (
          <CarePanelBody
            key={item.key}
            card={item.card}
            today={today}
            weekEnd={weekEnd}
            onMove={(target) => onMove(item, target)}
            onAction={careAction(item.card)}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
