"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { personInitials } from "@/components/hr/people/hr-format";
import { PRIORITY_DOT, caseSubline, dueBadge } from "@/components/admin-cases/case-format";
import { shortNames } from "@/components/care/week/week-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CASE_AREA_LABELS, CASE_STATUS_LABELS } from "@/lib/api/admin-cases";
import type { CareBoardCard } from "@/lib/api/care-board";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { Chip } from "./Chip";
import { DUE_VARIANT } from "./CaseTile";
import { CARE_KIND_ICONS, CareActionButton, CareQuote, demandFacts } from "./CareTile";
import { HealthDot, HealthWord } from "./HealthMark";
import {
  LIST_FILTER_LABELS,
  LIST_PAGE,
  WORK_COLUMN_LABELS,
  careBadge,
  careReasonShort,
  careStateText,
  clientPeopleHref,
  dataSummaryText,
  initialSurname,
  listFilterCounts,
  listGroups,
  matchesListFilter,
  overdueText,
  paginateGroups,
  type ListFilter,
  type WorkItem,
} from "./work-board-model";

function Avatar({ name }: { name: string | null | undefined }) {
  if (!name) return <span className="w-6 shrink-0" />;
  return (
    <span
      title={name}
      className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
    >
      <span aria-hidden>{personInitials(name)}</span>
      <span className="sr-only">{name}</span>
    </span>
  );
}

/** Klient jako link do „Ludzie i technologie” (P1: klik w klienta). */
function ClientLink({ card }: { card: CareBoardCard }) {
  if (!card.client_name) return null;
  if (!card.client_id) return <span>{card.client_name}</span>;
  return (
    <Link href={clientPeopleHref(card.client_id)} className="hover:text-foreground hover:underline">
      {card.client_name}
    </Link>
  );
}

/** Druga linia wiersza: „Telekom Wzorcowy · QA · menedżer K. Kierownicza”. */
function CareSubline({ card }: { card: CareBoardCard }) {
  const rest: string[] = [];
  if (card.kind === "contact") {
    if (card.role_label) rest.push(card.role_label);
    rest.push(card.manager?.name ? `menedżer ${initialSurname(card.manager.name)}` : "menedżer: nie wskazano");
  } else if (card.kind === "feedback") {
    const count = card.consultants?.length ?? 0;
    rest.push(`menedżer ${count} ${count === 1 ? "naszego" : "naszych"}`);
  } else if (card.kind === "decision") {
    if (card.role_label) rest.push(card.role_label);
    if (card.end_on) rest.push(`koniec ${formatDayMonthPl(card.end_on)}`);
  } else if (card.kind === "demand") {
    if (card.demand?.area?.name) rest.push(card.demand.area.name);
  } else if (card.kind === "data" && card.data) {
    rest.push(`klient · ${card.data.consultants} ${card.data.consultants === 1 ? "konsultant" : "konsultantów"}`);
  }
  return (
    <p className="truncate text-xs text-muted-foreground">
      {card.kind === "data" ? null : <ClientLink card={card} />}
      {rest.length ? `${card.kind === "data" || !card.client_name ? "" : " · "}${rest.join(" · ")}` : null}
    </p>
  );
}

/** Powód wiersza: „Dzień 30 · 3 dni po terminie”, „Opinia · kwartał bez opinii”, „Chce zmiany”. */
function careReasonLine(card: CareBoardCard, today: string | undefined): string | null {
  if (card.kind === "data" && card.data) return dataSummaryText(card.data);
  if (card.kind === "demand") return demandFacts(card);
  const reason = careReasonShort(card);
  const head =
    card.kind === "feedback"
      ? `Opinia · ${(card.reason_label ?? "").toLocaleLowerCase("pl-PL") || "prośba"}`
      : reason
        ? reason[0].toLocaleUpperCase("pl-PL") + reason.slice(1)
        : null;
  let when: string | null = null;
  if (card.column === "in_progress" && card.scheduled_at) when = null;
  else if (card.overdue_days > 0) when = overdueText(card.overdue_days, card.kind === "contact");
  else if (card.due_on && today && card.due_on === today) when = "dziś";
  return [head, when].filter(Boolean).join(" · ") || null;
}

function CareRow({
  card,
  today,
  weekEnd,
  selected,
  onOpen,
  onOpenContract,
  careAction,
}: {
  card: CareBoardCard;
  today?: string;
  weekEnd?: string;
  selected: boolean;
  onOpen: () => void;
  onOpenContract?: (contractId: number) => void;
  careAction: (card: CareBoardCard) => (() => void) | null;
}) {
  const Icon = CARE_KIND_ICONS[card.kind];
  const badge = careBadge(card, today, weekEnd);
  const variant = badge ? DUE_VARIANT[badge.tone] : null;
  const state = careStateText(card);
  const reason = careReasonLine(card, today);
  const contractId = card.contract_id ?? null;
  // P1: klik w osobę otwiera Kartę konsultanta; bez kontraktu (opinia, popyt, dane) — panel karty.
  const openName = contractId && onOpenContract ? () => onOpenContract(contractId) : onOpen;
  return (
    <li
      aria-label={card.title}
      className={cn(
        "flex items-start gap-3 border-b border-border/60 px-3 py-2.5 last:border-b-0",
        selected && "bg-primary/5",
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1 space-y-0.5">
        <span className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={openName}
            aria-label={contractId && onOpenContract ? `Karta konsultanta: ${card.title}` : `Opieka: ${card.title}`}
            className="truncate text-left text-sm font-semibold text-foreground hover:underline"
          >
            {card.title}
          </button>
          {card.kind === "feedback" ? (
            <Badge size="sm" variant="outline" className="shrink-0">
              menedżer
            </Badge>
          ) : null}
          {contractId && onOpenContract ? (
            <button
              type="button"
              onClick={onOpen}
              className="text-xs text-muted-foreground hover:text-foreground hover:underline"
            >
              szczegóły
            </button>
          ) : null}
        </span>
        <CareSubline card={card} />
        {reason ? <p className="text-xs font-medium text-foreground">{reason}</p> : null}
        {card.kind === "feedback" && card.consultants?.length ? (
          <p className="truncate text-xs text-muted-foreground">
            o: {shortNames(card.consultants.map((person) => person.name))}
            {card.last_feedback ? ` · ostatnia ${formatDayMonthPl(card.last_feedback.held_on)}` : ""}
            {card.last_feedback?.average != null ? ` · ${Math.round(card.last_feedback.average)} / 5` : ""}
          </p>
        ) : null}
        <CareQuote card={card} className="truncate text-xs text-muted-foreground" />
        {state ? <p className="text-xs text-muted-foreground">{state}</p> : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {badge && variant && card.column === "in_progress" ? (
          <Badge size="sm" variant={variant} className="h-auto py-0.5">
            {badge.text}
          </Badge>
        ) : null}
        {card.health ? (
          <span className="rounded-full border border-border px-2 py-0.5">
            <HealthWord health={card.health} />
          </span>
        ) : null}
        {card.column !== "new" ? (
          <span className="hidden text-xs text-muted-foreground md:inline">
            {WORK_COLUMN_LABELS[card.column].toLowerCase()}
          </span>
        ) : null}
        <CareActionButton card={card} onAction={careAction(card)} className="hidden sm:inline-flex" />
      </div>
    </li>
  );
}

function Row({
  item,
  today,
  weekEnd,
  selected,
  onOpen,
  onOpenContract,
  careAction,
}: {
  item: WorkItem;
  today?: string;
  weekEnd?: string;
  selected: boolean;
  onOpen: () => void;
  onOpenContract?: (contractId: number) => void;
  careAction: (card: CareBoardCard) => (() => void) | null;
}) {
  if (item.type === "care") {
    return (
      <CareRow
        card={item.card}
        today={today}
        weekEnd={weekEnd}
        selected={selected}
        onOpen={onOpen}
        onOpenContract={onOpenContract}
        careAction={careAction}
      />
    );
  }
  const card = item.card;
  const due = dueBadge(card, today, weekEnd);
  const variant = due ? DUE_VARIANT[due.tone] : null;
  return (
    <li
      aria-label={card.title}
      className={cn(
        "flex items-center gap-3 border-b border-border/60 px-3 py-2 last:border-b-0",
        selected && "bg-primary/5",
      )}
    >
      <span className={cn("size-2 shrink-0 rounded-full", PRIORITY_DOT[card.priority])} title={card.priority} />
      <div className="min-w-0 flex-1">
        {card.content_hidden ? (
          // Czytający nie otworzy sprawy (brak dostępu) — wiersz bez linku.
          <span className="block max-w-full truncate text-sm font-semibold text-foreground">{card.title}</span>
        ) : (
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Sprawa: ${card.title}`}
            className="block max-w-full truncate text-left text-sm font-semibold text-foreground hover:underline"
          >
            {card.title}
          </button>
        )}
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          {card.contract?.health ? <HealthDot health={card.contract.health} /> : null}
          <span className="truncate">
            {[
              "Sprawa",
              caseSubline(card),
              CASE_AREA_LABELS[card.area].toLowerCase(),
              CASE_STATUS_LABELS[card.status].toLowerCase(),
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </p>
      </div>
      {due && variant ? (
        <Badge size="sm" variant={variant} className="h-auto shrink-0 py-0.5">
          {due.text}
        </Badge>
      ) : null}
      <Avatar name={card.assignee?.name} />
    </li>
  );
}

const CHIPS: readonly ListFilter[] = ["all", "overdue", "week", "contact", "feedback", "decision", "data", "demand"];

/**
 * Widok „Lista” (makieta P1) — te same karty co tablica, jako kolejka
 * „kto teraz i dlaczego”: chipy-filtry z licznikami (Wszystko · Po terminie ·
 * Rozmowy · Opinie menedżerów · Decyzje · Dane · Popyt — popyt tylko, gdy
 * jest), postęp „Ten tydzień: 2 z 6 zapisane”, grupy Po terminie · Do piątku
 * · Decyzje · Popyt · Dane do uzupełnienia, wiersz = jeden powód i jedna akcja,
 * po 50 wierszy („Pokaż więcej”) — prod miał 482 zaległe.
 */
export function WorkList({
  items,
  today,
  weekEnd,
  selectedKey,
  onOpen,
  careAction,
  filter,
  onFilterChange,
  progress,
  onOpenContract,
}: {
  items: readonly WorkItem[];
  today?: string;
  weekEnd?: string;
  selectedKey: string | null;
  onOpen: (item: WorkItem) => void;
  careAction: (card: CareBoardCard) => (() => void) | null;
  filter: ListFilter;
  onFilterChange: (filter: ListFilter) => void;
  /** `null` — tablica bez opieki (Sprawy) albo starsza odpowiedź. */
  progress?: { done: number; total: number } | null;
  onOpenContract?: (contractId: number) => void;
}) {
  const [limit, setLimit] = useState(LIST_PAGE);
  const counts = useMemo(() => listFilterCounts(items, weekEnd), [items, weekEnd]);
  const filtered = useMemo(
    () => items.filter((item) => matchesListFilter(item, filter, weekEnd)),
    [items, filter, weekEnd],
  );
  const groups = listGroups(filtered, weekEnd);
  const page = paginateGroups(groups, limit);
  // „Do piątku” stoi tylko, gdy przyszedł z linku (`?filter=do-piatku`); popyt i dane — gdy są.
  const chips = CHIPS.filter(
    (key) =>
      key === filter ||
      (key === "week" ? false : key === "demand" || key === "data" ? counts[key] > 0 : true),
  );
  return (
    <div className="space-y-3" aria-label="Kolejka do zrobienia">
      <div className="flex flex-wrap items-center gap-1.5">
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filtr kolejki">
          {chips.map((key) => (
            <Chip
              key={key}
              active={filter === key}
              tone={key === "overdue" ? "danger" : undefined}
              onClick={() => {
                setLimit(LIST_PAGE);
                onFilterChange(filter === key && key !== "all" ? "all" : key);
              }}
            >
              {LIST_FILTER_LABELS[key]} <span className="tabular-nums opacity-70">{counts[key]}</span>
            </Chip>
          ))}
        </div>
        {progress && progress.total > 0 ? (
          <p className="ml-auto text-xs text-muted-foreground">
            Ten tydzień:{" "}
            <span className="font-semibold tabular-nums text-foreground">
              {progress.done} z {progress.total}
            </span>{" "}
            zapisane
          </p>
        ) : null}
      </div>
      {!groups.length ? (
        <p className="text-sm text-muted-foreground">
          {filter === "all" ? "Nic nie czeka na zrobienie." : "Nic w tym filtrze."}
        </p>
      ) : (
        <>
          {page.groups.map((group) => (
            <section
              key={group.key}
              aria-labelledby={`work-list-${group.key}`}
              className="rounded-xl border border-border bg-card"
            >
              <h3
                id={`work-list-${group.key}`}
                className={cn(
                  "flex items-center gap-2 border-b border-border px-3 py-2 text-[13.5px] font-semibold",
                  group.key === "overdue" && "text-destructive",
                )}
              >
                {group.label}
                <Badge size="sm" variant={group.key === "overdue" ? "danger" : "neutral"} className="tabular-nums">
                  {groups.find((full) => full.key === group.key)?.items.length ?? group.items.length}
                </Badge>
                {group.key === "overdue" ? (
                  <span className="text-xs font-normal text-muted-foreground">najstarszy termin u góry</span>
                ) : null}
              </h3>
              <ul>
                {group.items.map((item) => (
                  <Row
                    key={item.key}
                    item={item}
                    today={today}
                    weekEnd={weekEnd}
                    selected={selectedKey === item.key}
                    onOpen={() => onOpen(item)}
                    onOpenContract={onOpenContract}
                    careAction={careAction}
                  />
                ))}
              </ul>
            </section>
          ))}
          {page.hidden > 0 ? (
            <Button variant="outline" className="w-full" onClick={() => setLimit((value) => value + LIST_PAGE)}>
              Pokaż więcej ({page.hidden})
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
