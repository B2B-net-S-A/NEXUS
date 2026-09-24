"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeftRight,
  CalendarDays,
  CalendarPlus,
  ChevronDown,
  Clock3,
  FilePlus2,
  FileUp,
  History,
  Pencil,
  Plus,
  ReceiptText,
  Repeat,
  RotateCcw,
  Ban,
  SquareCheckBig,
  Trash2,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { ContractPersonLink } from "@/components/contracts/ContractPersonLink";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import {
  orderGroupsApi,
  type OrderGroupEvent,
  type OrderGroupRead,
  type OrderLineRead,
} from "@/lib/api/orderGroups";
import {
  consultantMatchesQuery,
  effectiveGroupOrderType,
  flattenOrderGroupIds,
  sortOrderLinesByConsultant,
  sortOrderLinesByEnd,
  usesSharedMdPool,
} from "@/lib/client-order-list";
import { countPl } from "@/lib/plural-pl";
import { formatDateTimePl } from "@/lib/date-pl";
import { formatDate, formatPLN } from "@/types/client-profile";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import { MD_TRANSFER_METHOD_LABELS } from "@/lib/order-takeover";

import {
  consultantUsageSentence,
  hasScopedMd,
  lineHasSettlements,
} from "@/lib/order-line-usage";
import { LineMonthlyHistoryDialog } from "./LineMonthlyHistoryDialog";
import { formatMd, MdBudgetBar } from "./MdBudgetBar";
import { MdScopeBars, MdScopePanels, MdScopeTotalBar } from "./MdScopeBars";
import { OrderTypeBadge } from "./OrderTypeBadge";

const SETTLED_LINE_DELETE_HINT =
  "Nie można usunąć — konsultant ma rozliczenia (MD lub faktury). " +
  "Użyj „Zostaw jako historię” albo „Zakończ”.";

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

function periodLabel(group: OrderGroupRead): string {
  const from = formatDate(group.start_date);
  const to = group.end_date ? formatDate(group.end_date) : "bezterminowo";
  return `${from} → ${to}`;
}

/** Część umowy ramowej CeZ w zapisie rzymskim — lokalna mapa, bo nagłówek
 *  karty pokazuje SAM numer umowy wykonawczej z częścią, nie etykietę
 *  „E-zdrowie cz.2" z pickerów. */
const PART_ROMAN: Record<string, string> = {
  cz1: "I",
  cz2: "II",
  cz4: "IV",
  cz5: "V",
  cz6: "VI",
};

function executiveContractLabel(
  contract: NonNullable<OrderGroupRead["executive_contract"]>,
): string {
  const roman = contract.project_part ? PART_ROMAN[contract.project_part] : undefined;
  return roman
    ? `Umowa wykonawcza ${contract.number} · Cz. ${roman}`
    : `Umowa wykonawcza ${contract.number}`;
}

/** Kotwica wiersza obsady — cel przejścia „→ następca" z wiersza osoby
 *  zastąpionej. Następca bywa w innej sekcji (aktywna obsada vs zakończone),
 *  więc przewijamy po id, nie po pozycji na liście. */
export function orderLineAnchorId(lineId: number): string {
  return `order-line-${lineId}`;
}

/** Przewinięcie do wiersza następcy z krótkim podświetleniem. Bez celu w DOM
 *  (następca na innej karcie) — nic; przycisk nie może udawać nawigacji. */
function focusOrderLine(lineId: number) {
  const el = document.getElementById(orderLineAnchorId(lineId));
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("ring-2", "ring-primary", "ring-inset");
  window.setTimeout(() => {
    el.classList.remove("ring-2", "ring-primary", "ring-inset");
  }, 1600);
}

/** Pasek wykorzystania pozycji MD zamówienia (podstawa + opcja) — CeZ. */
function PositionsMdBar({ group }: { group: OrderGroupRead }) {
  const total = group.md_positions_total ?? 0;
  const used = Math.max(0, group.md_used_total ?? 0);
  const pct = total > 0 ? (used / total) * 100 : null;
  const exceeded = total > 0 && used > total;
  const valuePct =
    group.contract_value_pln != null && group.contract_value_pln > 0
      ? ((group.used_value_pln ?? 0) / group.contract_value_pln) * 100
      : null;
  return (
    <div className="min-w-[14rem]">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(100, pct ?? 0))}
        aria-label="Wykorzystane MD zamówienia"
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            exceeded ? "bg-destructive" : "bg-primary",
          )}
          style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%` }}
        />
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Wykorzystano{" "}
        <span className={cn("font-semibold", exceeded ? "text-destructive" : "text-foreground")}>
          {formatMd(used)}
        </span>{" "}
        / {formatMd(total)} MD{pct !== null ? ` (${Math.round(pct)}%)` : ""}
      </p>
      {/* Kwoty tylko przy `contract_value_pln` z odpowiedzi — rola bez
          finansów dostaje `null` i widzi same MD, nie „0 zł z 0 zł". */}
      {group.contract_value_pln != null ? (
        <p className="mt-0.5 text-xs text-muted-foreground">
          Wykorzystano wartości umowy{" "}
          <span className="font-semibold text-foreground">
            {valuePct !== null ? `${Math.round(valuePct)}%` : "—"}
          </span>{" "}
          · {formatPLN(group.used_value_pln ?? 0)} / {formatPLN(group.contract_value_pln)}
        </p>
      ) : null}
    </div>
  );
}

const STATUS_BADGE: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  scheduled: "bg-sky-100 text-sky-800",
  completed: "bg-zinc-200 text-zinc-700",
  exhausted: "bg-destructive/15 text-destructive",
  cancelled: "bg-muted text-muted-foreground line-through",
};

/** Kotwica do przewijania. Osobna od `order-group-{id}-content`, bo dostają ją
 *  także zagnieżdżone przyszłe zamówienia — cel przejścia z historii bywa
 *  wierszem pod inną kartą, nie kartą najwyższego poziomu. */
export function orderGroupAnchorId(groupId: number): string {
  return `order-group-anchor-${groupId}`;
}

/** Żądanie „pokaż zamówienie X" płynące z wpisu `transfer_md`.
 *  `nonce` jest nośnikiem POWTÓRZENIA: samo id nie zmienia stanu, więc drugie
 *  kliknięcie tego samego numeru (po odjechaniu wzrokiem) przepadałoby po cichu. */
function displayLineRate(line: OrderLineRead, side: "cost" | "revenue") {
  const currency = (side === "cost" ? line.rate_candidate_currency : line.rate_client_currency) ?? "PLN";
  const amount = side === "cost" ? (line.source_rate_cost ?? line.rate_cost) : (line.source_rate_revenue ?? line.rate_revenue);
  if (amount == null) return "—";
  if (currency === "PLN") return `${formatPLN(amount)}/MD`;
  return `${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 3 }).format(amount)} ${currency}/MD`;
}

export interface OrderGroupFocusRequest {
  groupId: number;
  nonce: number;
}

/** Ikona wpisu historii lustrzy przycisk, który ten wpis produkuje — kolumna
 *  ikon czyta się wtedy tak samo jak pasek akcji nad nią. `transfer_md` celowo
 *  dostaje ikonę spoza tamtego zestawu: przeniesienie MD nie jest edycją
 *  zamówienia, tylko ruchem MIĘDZY dwoma zamówieniami. */
const EVENT_ICON: Record<string, LucideIcon> = {
  utworzenie: FilePlus2,
  dodanie_konsultanta: UserPlus,
  zamiana_kontraktora: Repeat,
  edycja_reczna: Pencil,
  zakonczenie: SquareCheckBig,
  przywrocenie: RotateCcw,
  wyczerpanie: AlertTriangle,
  przedluzenie: CalendarPlus,
  import_md: FileUp,
  import_faktur: ReceiptText,
  transfer_md: ArrowLeftRight,
};

/** Treść wpisu historii z klikalnym numerem zamówienia powiązanego.
 *
 *  Bez tego przejścia czytelnik musiałby szukać drugiego zamówienia wzrokiem,
 *  a przy przeniesieniu MD bywa ono zagnieżdżone pod zupełnie inną kartą.
 *  Gdy `related_group_id` jest `null`, renderujemy SAM TEKST — przycisk bez
 *  celu obiecuje nawigację, której nie wykona. */
function EventDescription({
  event,
  onFocusGroup,
}: {
  event: OrderGroupEvent;
  onFocusGroup: (groupId: number) => void;
}) {
  const groupId = event.related_group_id;
  const number = event.related_order_number;
  if (groupId == null || !number) return <>{event.description}</>;

  const link = (
    <button
      type="button"
      onClick={() => onFocusGroup(groupId)}
      aria-label={`Pokaż zamówienie nr ${number}`}
      className="font-semibold text-primary underline underline-offset-2 hover:no-underline"
    >
      {number}
    </button>
  );

  const at = event.description.indexOf(number);
  if (at < 0) {
    // Numeru nie ma w treści (inny szablon opisu po stronie backendu) —
    // doklejamy go obok, zamiast gubić przejście do powiązanego zamówienia.
    return (
      <>
        {event.description} {link}
      </>
    );
  }
  return (
    <>
      {event.description.slice(0, at)}
      {link}
      {event.description.slice(at + number.length)}
    </>
  );
}

/** Pasek wykorzystania budżetu kwotowego. Wypełnienie pokazuje POZOSTAŁOŚĆ —
 *  ta sama konwencja co przy MD, żeby dwa paski obok siebie nie znaczyły
 *  czegoś przeciwnego. */
function BudgetBar({ group }: { group: OrderGroupRead }) {
  // Rola bez VIEW_FINANCE (m.in. TAC, który tę zakładkę WIDZI) dostaje kwoty
  // grupy jako `null` — redakcja w `client_order_groups.py`. Domykanie tego
  // przez `?? 0` zamieniało BRAK UPRAWNIEŃ w „pozostało 0", czyli `depleted`,
  // czyli czerwony pasek `bg-destructive` pod podpisem „Kwota — · pozostało —".
  // Brak uprawnień nie może czytać się jak alarm o wyczerpanym budżecie —
  // nieuprawniony widziałby wtedy nie MNIEJ niż uprawniony, tylko COŚ INNEGO.
  // Warunek patrzy na `null`, NIE na `0`: zamówienie z realnym budżetem 0 to
  // inny stan świata (pieniądze się skończyły) niż brak dostępu do kwoty.
  if (group.budget_amount == null) {
    return (
      <p className="min-w-[14rem] text-xs text-muted-foreground">
        Kwota {formatPLN(null)} · wykorzystano {formatPLN(null)} · pozostało{" "}
        {formatPLN(null)}
      </p>
    );
  }

  const total = group.budget_amount;
  const remaining = group.budget_remaining ?? 0;
  const pct = total > 0 ? Math.max(0, Math.min(100, (remaining / total) * 100)) : 0;
  const depleted = remaining <= 0;
  const low = !depleted && pct <= 15;
  return (
    <div className="min-w-[14rem]">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-label="Pozostała kwota zamówienia"
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            depleted ? "bg-destructive" : low ? "bg-amber-500" : "bg-primary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {/* TRZY liczby, nie jedna. Ticket nazywa „zużyciem" wartość, która
          maleje — czyli resztę; jedno pole podpisane „zużycie", a pokazujące
          resztę, myli dokładnie w rozmowie o pieniądzach. */}
      <p className="mt-1 text-xs text-muted-foreground">
        Kwota {formatPLN(group.budget_amount)} · wykorzystano{" "}
        {formatPLN(group.budget_used)} · pozostało{" "}
        <span className={cn("font-semibold", depleted ? "text-destructive" : "text-foreground")}>
          {formatPLN(group.budget_remaining)}
        </span>
      </p>
    </div>
  );
}

/** Klientowo ograniczona wspólna pula MD Cyfrowego Polsatu i Lotte Wedel. */
function SharedMdBudgetBar({ group }: { group: OrderGroupRead }) {
  const total = group.md_budget_total ?? 0;
  const used = Math.max(0, group.md_budget_used ?? 0);
  const remaining = Math.max(0, group.md_budget_remaining ?? 0);
  const pct = total > 0 ? Math.max(0, Math.min(100, (remaining / total) * 100)) : 0;
  const depleted = total > 0 && remaining <= 0;
  const low = !depleted && pct <= 15;

  return (
    <div className="min-w-[14rem]">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-label="Pozostałe MD zamówienia"
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            depleted ? "bg-destructive" : low ? "bg-amber-500" : "bg-primary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Budżet {formatMd(total)} MD · wykorzystano {formatMd(used)} MD ·
        pozostało{" "}
        <span
          className={cn(
            "font-semibold",
            depleted ? "text-destructive" : "text-foreground",
          )}
        >
          {formatMd(remaining)} MD
        </span>
      </p>
    </div>
  );
}

interface OrderLineRowProps {
  group: OrderGroupRead;
  line: OrderLineRead;
  searchQuery: string;
  canManage: boolean;
  canManageLifecycle: boolean;
  onEditLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onSwapLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onResolveOffboarding: (group: OrderGroupRead, line: OrderLineRead) => void;
  onKeepHistory?: (group: OrderGroupRead, line: OrderLineRead) => void;
  onReplaceLine?: (group: OrderGroupRead, line: OrderLineRead) => void;
  /** „Rozliczenia miesięczne" — wpisy MD per miesiąc tej osoby. */
  onShowConsumptions?: (group: OrderGroupRead, line: OrderLineRead) => void;
  /** Karta konsultanta CeZ (pilotaż) zamiast jednego rzędu. */
  scopedCardLayout?: boolean;
  /** Wiersz stoi na liście kart (szare tło) — dostaje białą powierzchnię. */
  cardSurface?: boolean;
}

/** Jeden wiersz obsady. Stan `pending` jest częścią domeny, nie dekoracją:
 *  zwykłe akcje są wtedy ukryte, żeby nie dało się usunąć linii bokiem i
 *  pozostawić alertu Delivery Leada bez rozstrzygnięcia. */
function OrderLineRow({
  group,
  line,
  searchQuery,
  canManage,
  canManageLifecycle,
  onEditLine,
  onSwapLine,
  onDeleteLine,
  onResolveOffboarding,
  onKeepHistory,
  onReplaceLine,
  onShowConsumptions,
  scopedCardLayout = false,
  cardSurface = false,
}: OrderLineRowProps) {
  const pendingOffboarding = line.offboarding_case?.status === "pending";
  const completedCostLine = group.is_cost_based && !line.is_active;
  const sharedMd = usesSharedMdPool(group);
  const removed = Boolean(line.removed_from_order);
  // Rozliczenia miesięczne mają sens tylko przy własnym budżecie MD osoby —
  // zamówienie kosztowe rozlicza faktury, wspólna pula nie ma wpisów per osoba.
  const perPersonMd = !group.is_cost_based && !sharedMd;
  const replacedBy =
    line.replaced_by_order_id != null ? line.replaced_by_consultant_name : null;
  // B2 (ticket 09.2026): MD przeniesione na następcę nie są już „pozostało"
  // u osoby odchodzącej — pasek pokazuje zero, a zdanie mówi, kto je przejął.
  const transferredOut =
    line.replaced_by_md != null &&
    (line.replaced_by_kind === "swap" || line.replaced_by_kind === "takeover") &&
    !line.replaced_by_scheduled &&
    !line.is_active;
  const barLine: OrderLineRead = transferredOut ? { ...line, md_remaining: 0 } : line;
  const scheduledTakeover = line.takeover_scheduled === true;
  const pendingButScheduled = pendingOffboarding && line.replaced_by_scheduled === true;
  const endedCooperation = Boolean(line.cooperation_ended_on) && !line.is_active;
  // „[Osoba] wykorzystał(a) X zł / Y MD na tym zamówieniu przed zakończeniem
  // współpracy" — jedno zdanie dla zamówień MD i kosztowych.
  const usageSentence = consultantUsageSentence(group, line);
  // Usunięcie kasuje linię trwale — z rozliczeniami serwer odmawia (409).
  const hasSettlements = lineHasSettlements(line);
  // Osoba z zakończoną współpracą, która została na zamówieniu, a nikt jeszcze
  // o niej nie zdecydował (zamówienie MD z czekającą sprawą ma swój formularz).
  // Zastąpiona osoba MA już decyzję — następcę; pytanie „Zastąp kimś innym"
  // przy niej byłoby prośbą o drugie zastępstwo tej samej pozycji.
  const needsDecision =
    endedCooperation &&
    !removed &&
    line.replaced_by_order_id == null &&
    !line.history_kept_at &&
    !line.offboarding_case &&
    (canManage || canManageLifecycle);
  const hasHistoryNotes =
    (line.origin === "manual" && Boolean(line.added_at)) ||
    Boolean(usageSentence) ||
    Boolean(line.history_kept_at) ||
    needsDecision;

  // Kawałki wiersza składane w dwa układy: domyślny (jeden rząd — BIK,
  // Polkomtel, BNP; DOM identyczny jak przed kartą CeZ) i karta konsultanta
  // Centrum e-Zdrowia (nagłówek z akcjami → stawka | podstawa | opcja → łącznie).
  const nameBlock = (
    <>
      <div className="flex min-w-[13rem] flex-1 items-center gap-3">
        <Avatar className="h-8 w-8">
          <AvatarFallback
            className={cn(
              "bg-primary/10 text-[11px] font-semibold text-primary",
              pendingOffboarding && "bg-destructive/15 text-destructive",
            )}
          >
            {initials(line.consultant_name)}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-foreground">
            {/* Link prowadzi do kontraktu TEJ linii (`line.contract_id`),
                nie „do kontraktów tej osoby". Nazwiska poprzednika i następcy
                niżej celowo linkami NIE są — mają wyłącznie `*_order_id`, więc
                kontrakt trzeba by zgadywać. */}
            <ContractPersonLink
              contractId={line.contract_id}
              name={line.consultant_name}
              className="truncate"
            />
            {pendingOffboarding ? (
              <span className="rounded bg-destructive px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-destructive-foreground">
                Zakończenie współpracy
              </span>
            ) : null}
            {removed ? (
              <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Usunięty z zamówienia
              </span>
            ) : endedCooperation && !pendingOffboarding ? (
              <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Zakończył współpracę
              </span>
            ) : null}
            {scheduledTakeover ? (
              <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                Zaplanowane zastępstwo od {formatDate(line.start_date)}
              </span>
            ) : line.assignment_kind === "takeover" ? (
              <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                Zastępstwo
              </span>
            ) : line.assignment_kind === "join" ? (
              <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                Dołączona
              </span>
            ) : line.origin === "manual" ? (
              <span className="rounded bg-warning-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-muted-foreground">
                Dodany ręcznie
              </span>
            ) : null}
            {line.replaced_by_order_id != null ? (
              <span className="rounded-full bg-warning-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-muted-foreground">
                {line.replaced_by_scheduled
                  ? `Zastępstwo od ${formatDate(line.replaced_by_start_date ?? null)}`
                  : "Zastąpiony"}
              </span>
            ) : null}
          </p>
          <p
            className={cn(
              "text-xs text-muted-foreground",
              line.is_active && "truncate",
            )}
          >
            {scheduledTakeover
              ? "Zaplanowane zastępstwo"
              : pendingOffboarding
              ? "Współpraca zakończona"
              : removed
                ? "Usunięty z zamówienia"
                : endedCooperation
                  ? `Zakończył współpracę ${formatDate(line.cooperation_ended_on)}`
                  : line.is_active
                    ? "Konsultant"
                    : "Zakończony"}
            {line.start_date
              ? line.is_active || scheduledTakeover
                ? ` · od ${formatDate(line.start_date)}`
                : ` · był na zamówieniu od ${formatDate(line.start_date)}`
              : ""}
            {!line.is_active && line.end_date
              ? ` do ${formatDate(line.end_date)}`
              : ""}
          </p>
          {pendingButScheduled ? (
            <p role="status" className="mt-1 text-xs font-medium text-foreground">
              Zastępstwo zaplanowane: {line.replaced_by_consultant_name} od{" "}
              {formatDate(line.replaced_by_start_date ?? null)} — pozostałe MD
              przejdą automatycznie w dniu wejścia.
            </p>
          ) : pendingOffboarding && line.offboarding_case ? (
            <p role="status" className="mt-1 text-xs font-medium text-destructive">
              Kontrakt zakończył się {formatDate(line.offboarding_case.effective_date)}.
              Wymagana decyzja o pozostałej puli MD
              {line.offboarding_case.uses_shared_md_pool
                ? " (wspólna pula pozostaje bez zmian)."
                : // Migawka sprawy idzie za rozliczeniami (import po zejściu
                  // zmniejsza pulę), więc liczba jest stanem na dziś.
                  line.offboarding_case.remaining_md_snapshot > 0
                  ? `: pozostało ${formatMd(line.offboarding_case.remaining_md_snapshot)} MD.`
                  : ": pula wykorzystana w całości (0 MD do przeniesienia)."}
            </p>
          ) : null}
          {completedCostLine ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Zamówienie nr {group.order_number} · zafakturowano {" "}
              {line.invoiced_total == null
                ? "—"
                : line.invoiced_total === 0
                  ? "brak faktur"
                  : formatPLN(line.invoiced_total)}
            </p>
          ) : null}
          {line.assignment_kind === "takeover" && line.takeover_from_name ? (
            <p className="truncate text-xs text-muted-foreground">
              {scheduledTakeover ? "Przejmie po" : "Przejęła po"}:{" "}
              {line.takeover_from_name}
              {line.takeover_md != null ? ` · ${formatMd(line.takeover_md)} MD` : ""}
              {line.takeover_method
                ? ` (${MD_TRANSFER_METHOD_LABELS[line.takeover_method]})`
                : ""}
            </p>
          ) : line.predecessor_consultant_name ? (
            <p className="truncate text-xs text-muted-foreground">
              zastąpił: {line.predecessor_consultant_name}
            </p>
          ) : null}
          {line.replaced_by_order_id != null &&
          (line.replaced_by_kind === "takeover" || line.replaced_by_kind === "swap") ? (
            <p className="truncate text-xs text-muted-foreground">
              {line.replaced_by_scheduled ? "Zastąpi go" : "Zastąpiony przez"}:{" "}
              <button
                type="button"
                onClick={() => focusOrderLine(line.replaced_by_order_id as number)}
                aria-label={`Pokaż następcę${replacedBy ? `: ${replacedBy}` : ""}`}
                className="font-medium text-primary underline-offset-2 hover:underline"
              >
                {replacedBy ?? "następca"}
              </button>
              {line.replaced_by_start_date
                ? ` od ${formatDate(line.replaced_by_start_date)}`
                : ""}
              {transferredOut && line.replaced_by_md != null
                ? ` · przejęła ${formatMd(line.replaced_by_md)} MD`
                : ""}
            </p>
          ) : line.replaced_by_order_id != null ? (
            <p className="truncate text-xs text-muted-foreground">
              <button
                type="button"
                onClick={() => focusOrderLine(line.replaced_by_order_id as number)}
                aria-label={`Pokaż następcę${replacedBy ? `: ${replacedBy}` : ""}`}
                className="font-medium text-primary underline-offset-2 hover:underline"
              >
                → {replacedBy ?? "następca"}
              </button>
            </p>
          ) : null}
          {line.missing_consumption_month ? (
            <p className="truncate text-xs text-amber-700">
              Brak zejścia za {line.missing_consumption_month}
            </p>
          ) : null}
          {line.unsettled_total != null && line.unsettled_total > 0 ? (
            <p className="text-xs text-destructive">
              Nie udało się rozliczyć pełnej kwoty faktury — brakuje {" "}
              {formatPLN(line.unsettled_total)} na zamówieniu.
            </p>
          ) : null}
        </div>
      </div>
    </>
  );

  const ratesBlock = (
    <>
      {/* Stawki — „—" gdy rola nie ma uprawnień finansowych. Zniknięcie
          kolumny zostawiłoby pustkę bez wyjaśnienia.

          Etykieta stoi OBOK wartości, nie nad nią: układ dwuwierszowy robił
          z każdej stawki dwie linijki i podwajał wysokość wiersza obsady.
          Skróty są lustrem kafelka jednoosobowego (`koszt.`/`przych.`) —
          pełne brzmienie niesie `title`. */}
      <div className="flex min-w-[15rem] flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {/* `min-w-[15rem]` zastępuje dwa dawne `min-w-[8rem]` na kolumnach
            etykieta-nad-wartością. Bez podłogi blok stawek ma szerokość swojej
            treści, więc w liście kilkunastu konsultantów kolejna kolumna
            (pasek MD / „zafakturowano") zaczynałaby się w innym miejscu
            w każdym wierszu. Kompaktowość dotyczy WYSOKOŚCI — wyrównanie
            kolumn zostaje. */}
        <span className="text-muted-foreground" title="Stawka kosztowa">
          koszt.{" "}
          <span className="font-medium text-foreground">
            {displayLineRate(line, "cost")}
          </span>
        </span>
        <span className="text-muted-foreground" title="Stawka przychodowa">
          przych.{" "}
          <span className="font-medium text-foreground">
            {displayLineRate(line, "revenue")}
          </span>
        </span>
      </div>
    </>
  );

  const budgetBlock = (
    <>
      {group.is_cost_based ? (
        <span className="ml-auto text-xs text-muted-foreground">
          zafakturowano{" "}
          <span className="font-medium text-foreground">
            {/* „—" dla braku faktur, nie „0 zł": zero znaczyłoby
                „wystawiono zero", a tu nic jeszcze nie przyszło. */}
            {line.invoiced_total == null || line.invoiced_total === 0
              ? "—"
              : formatPLN(line.invoiced_total)}
          </span>
        </span>
      ) : sharedMd ? (
        <span className="ml-auto text-xs text-muted-foreground">
          budżet MD{" "}
          <span className="font-medium text-foreground">Wspólna pula</span>
        </span>
      ) : hasScopedMd(line, group) ? (
        // Podstawa + opcja — dwa paski ZUŻYCIA WYŁĄCZNIE na karcie przypiętej
        // do umowy wykonawczej (CeZ); BIK/Polkomtel dostają dotychczasowy
        // pasek „pozostało / całość" — backend zwraca `md_base_used` także im.
        <MdScopeBars line={barLine} className="ml-auto" />
      ) : (
        <MdBudgetBar
          remaining={barLine.md_remaining}
          total={line.md_total}
          className="ml-auto"
        />
      )}
    </>
  );

  const consumptionsButton = (
    <>
      {perPersonMd && onShowConsumptions ? (
        <button
          type="button"
          onClick={() => onShowConsumptions(group, line)}
          aria-label={`Rozliczenia miesięczne — ${line.consultant_name}`}
          title="Rozliczenia miesięczne"
          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <CalendarDays className="h-4 w-4" aria-hidden="true" />
        </button>
      ) : null}
    </>
  );

  const actionsBlock = (
    <>
      {pendingOffboarding && !pendingButScheduled ? (
        <div className="ml-auto flex flex-col items-end gap-1">
          {canManage ? (
            <button
              type="button"
              onClick={() => onResolveOffboarding(group, line)}
              aria-label={`Podejmij decyzję o MD — ${line.consultant_name}`}
              className="rounded-md bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground transition-colors hover:bg-destructive/90"
            >
              Podejmij decyzję
            </button>
          ) : (
            <span className="text-xs font-medium text-destructive">
              Oczekuje na decyzję Delivery Leada
            </span>
          )}
        </div>
      ) : (canManage || canManageLifecycle) && !removed ? (
        <div className="flex items-center gap-1">
          {canManage ? (
            <>
              <button
                type="button"
                onClick={() => onEditLine(group, line)}
                aria-label={`Edytuj linię — ${line.consultant_name}`}
                title="Edytuj linię"
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Pencil className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => onSwapLine(group, line)}
                // Bramka idzie po STATUSIE linii, bo to lustro serwera
                // (`swap_consultant` wymaga `status == active`). `is_active`
                // opisuje obsadę, a osoba z zapisaną datą zejścia ma dalej
                // aktywną linię — zamianę wolno jej zrobić.
                disabled={line.status !== "active"}
                aria-label={`Zamień kontraktora — ${line.consultant_name}`}
                title={
                  line.status === "active"
                    ? "Zamień kontraktora"
                    : "Zamienić można tylko aktywną linię"
                }
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Repeat className="h-4 w-4" aria-hidden="true" />
              </button>
            </>
          ) : null}
          {canManageLifecycle ? (
            <button
              type="button"
              onClick={() => onDeleteLine(group, line)}
              disabled={hasSettlements}
              aria-label={`Usuń konsultanta z zamówienia — ${line.consultant_name}`}
              title={
                hasSettlements
                  ? SETTLED_LINE_DELETE_HINT
                  : "Usuń konsultanta z zamówienia"
              }
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  );

  const notesBlock = (
    <>
      {hasHistoryNotes ? (
        <div className="basis-full space-y-1 pl-11">
          {line.origin === "manual" && line.added_at ? (
            <p className="text-xs text-muted-foreground">
              Dodany ręcznie {formatDate(line.added_at)}
              {line.added_by_name ? ` przez ${line.added_by_name}` : ""}
              {line.replaces_name ? ` jako zastępstwo za ${line.replaces_name}` : ""}.
              {group.has_file
                ? " Dokument zamówienia (PDF) podpięto także do profilu tej osoby."
                : ""}
            </p>
          ) : null}
          {usageSentence ? (
            <p className="text-xs font-medium text-foreground">{usageSentence}</p>
          ) : null}
          {line.history_kept_at ? (
            <p className="text-xs text-muted-foreground">
              Zostawiono jako historię {formatDate(line.history_kept_at)}
              {line.history_kept_by_name ? ` — ${line.history_kept_by_name}` : ""}.
            </p>
          ) : null}
          {needsDecision ? (
            <div
              role="status"
              className="mt-2 rounded-md border border-border bg-muted/40 p-2 text-xs text-muted-foreground"
            >
              <p>
                Ta osoba nie ma już aktywnej współpracy. Pozostaje widoczna na
                zamówieniu wraz z historią wykorzystania — jej kwota nie wraca do
                puli dostępnego budżetu.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {onKeepHistory ? (
                  <button
                    type="button"
                    onClick={() => onKeepHistory(group, line)}
                    className="rounded-md border border-border bg-background px-2.5 py-1 font-medium text-foreground hover:bg-muted"
                  >
                    Zostaw jako historię
                  </button>
                ) : null}
                {canManage && onReplaceLine && group.can_add_consultant ? (
                  <button
                    type="button"
                    onClick={() => onReplaceLine(group, line)}
                    className="rounded-md border border-border bg-background px-2.5 py-1 font-medium text-foreground hover:bg-muted"
                  >
                    Zastąp kimś innym
                  </button>
                ) : null}
                {canManageLifecycle ? (
                  <button
                    type="button"
                    onClick={() => onDeleteLine(group, line)}
                    disabled={hasSettlements}
                    title={hasSettlements ? SETTLED_LINE_DELETE_HINT : undefined}
                    className="rounded-md border border-destructive/40 bg-background px-2.5 py-1 font-medium text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Usuń z zamówienia
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
  if (scopedCardLayout) {
    return (
      <li
        id={orderLineAnchorId(line.id)}
        className={cn(
          "rounded-xl border border-border bg-card px-4 py-3",
          !line.is_active &&
            !pendingOffboarding &&
            !needsDecision &&
            !scheduledTakeover &&
            "opacity-60",
          searchQuery.trim() &&
            consultantMatchesQuery(line.consultant_name, searchQuery) &&
            "bg-primary/10 ring-1 ring-inset ring-primary/20",
          pendingOffboarding &&
            "border-destructive/50 bg-destructive/10 opacity-100 ring-1 ring-inset ring-destructive/20",
        )}
      >
        <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
          {nameBlock}
          <div className="ml-auto flex items-center gap-1">
            {consumptionsButton}
            {actionsBlock}
          </div>
        </div>
        <div className="mt-2 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[9rem_minmax(0,1fr)_minmax(0,1fr)] sm:items-start">
          {/* Stawki — „—" bez uprawnień finansowych, jak w układzie domyślnym. */}
          <div className="text-xs">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Stawka
            </p>
            <p className="mt-0.5 text-muted-foreground" title="Stawka kosztowa">
              koszt{" "}
              <span className="font-semibold text-foreground">
                {displayLineRate(line, "cost")}
              </span>
            </p>
            <p className="text-muted-foreground" title="Stawka przychodowa">
              przych.{" "}
              <span className="font-semibold text-foreground">
                {displayLineRate(line, "revenue")}
              </span>
            </p>
          </div>
          <MdScopePanels line={barLine} />
        </div>
        <MdScopeTotalBar line={barLine} className="mt-2" />
        {hasHistoryNotes ? <div className="mt-2">{notesBlock}</div> : null}
      </li>
    );
  }

  return (
    <li
      id={orderLineAnchorId(line.id)}
      className={cn(
        "flex flex-wrap items-center gap-x-5 gap-y-2 py-2",
        cardSurface && "rounded-xl border border-border bg-card px-4",
        !line.is_active &&
            !pendingOffboarding &&
            !needsDecision &&
            !scheduledTakeover &&
            "opacity-60",
        searchQuery.trim() &&
          consultantMatchesQuery(line.consultant_name, searchQuery) &&
          "rounded-md bg-primary/10 px-2 ring-1 ring-inset ring-primary/20",
        pendingOffboarding &&
          "my-1 rounded-lg border border-destructive/50 bg-destructive/10 px-3 opacity-100 ring-1 ring-inset ring-destructive/20",
      )}
    >
      {nameBlock}
      {ratesBlock}
      {budgetBlock}
      {consumptionsButton}
      {actionsBlock}
      {notesBlock}
    </li>
  );
}

interface FutureOrdersProps {
  orders: OrderGroupRead[];
  searchQuery: string;
  canManage: boolean;
  canManageLifecycle: boolean;
  onEditGroup: (group: OrderGroupRead) => void;
  onAddConsultant: (group: OrderGroupRead) => void;
  onEditLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteGroup: (group: OrderGroupRead) => void;
  /** Ciaśniejsze odstępy pod kartą konsultanta CeZ — wyłącznie klasy. */
  compact?: boolean;
}

/** Zwarta lista według wzorca Tailwind Plus „stacked list with actions".
 *  To celowo NIE są osobne karty: wszystkie kontynuacje pozostają pod
 *  bieżącym zamówieniem i przed jego historią. */
function FutureOrders({
  orders,
  searchQuery,
  canManage,
  canManageLifecycle,
  onEditGroup,
  onAddConsultant,
  onEditLine,
  onDeleteGroup,
  compact = false,
}: FutureOrdersProps) {
  if (orders.length === 0) return null;

  return (
    <div className={cn("border-t border-border", compact ? "mt-3 pt-2" : "mt-4 pt-3")}>
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Clock3 className="h-3.5 w-3.5" aria-hidden />
        Przyszłe zamówienia ({orders.length})
      </p>
      <ul
        className={cn(
          "divide-y divide-border border border-border",
          compact ? "mt-1.5 rounded-xl bg-card" : "mt-2 rounded-lg bg-background",
        )}
      >
        {orders.map((future) => (
          <li
            key={future.id}
            id={orderGroupAnchorId(future.id)}
            className={compact ? "px-3 py-2" : "p-3"}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p
                  className={cn(
                    "flex flex-wrap items-center gap-2 font-semibold text-foreground",
                    compact ? "text-xs" : "text-sm",
                  )}
                >
                  <span className="truncate">
                    nr {future.order_number} · od {formatDate(future.start_date)}
                  </span>
                  <OrderTypeBadge type={effectiveGroupOrderType(future)} />
                </p>
                {future.end_date ? (
                  <p className="text-xs text-muted-foreground">
                    obowiązuje do {formatDate(future.end_date)}
                  </p>
                ) : null}
              </div>
              {canManage || canManageLifecycle ? (
                <div className="flex shrink-0 items-center gap-1">
                  {canManage ? (
                    <button
                      type="button"
                      onClick={() => onAddConsultant(future)}
                      aria-label={`Dodaj konsultanta do przyszłego zamówienia nr ${future.order_number}`}
                      title="Dodaj konsultanta"
                      className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <Plus className="h-4 w-4" aria-hidden />
                    </button>
                  ) : null}
                  {canManage ? (
                    <button
                      type="button"
                      onClick={() => onEditGroup(future)}
                      aria-label={`Uzupełnij przyszłe zamówienie nr ${future.order_number}`}
                      title="Uzupełnij zamówienie"
                      className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <Pencil className="h-4 w-4" aria-hidden />
                    </button>
                  ) : null}
                  {canManageLifecycle ? (
                    <button
                      type="button"
                      onClick={() => onDeleteGroup(future)}
                      aria-label={`Usuń przyszłe zamówienie nr ${future.order_number}`}
                      title="Usuń przyszłe zamówienie"
                      className="rounded p-1.5 text-destructive hover:bg-destructive/10"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>

            {usesSharedMdPool(future) ? (
              <div className={compact ? "mt-1.5" : "mt-2"}>
                <SharedMdBudgetBar group={future} />
              </div>
            ) : null}

            {future.lines.length === 0 ? (
              <p className={cn("text-xs text-muted-foreground", compact ? "mt-1.5" : "mt-2")}>
                To zamówienie nie ma jeszcze konsultantów.
              </p>
            ) : (
              <ul className={cn("divide-y divide-border/70", compact ? "mt-1" : "mt-2")}>
                {sortOrderLinesByConsultant(future.lines).map((line) => (
                  <li
                    key={line.id}
                    className={cn(
                      "grid grid-cols-1 text-xs sm:grid-cols-[minmax(9rem,1fr)_repeat(3,minmax(6.5rem,auto))_auto] sm:items-center",
                      compact ? "gap-1.5 py-1.5" : "gap-2 py-2",
                      searchQuery.trim() &&
                        consultantMatchesQuery(line.consultant_name, searchQuery) &&
                        "rounded-md bg-primary/10 px-2 ring-1 ring-inset ring-primary/20",
                    )}
                  >
                    <ContractPersonLink
                      contractId={line.contract_id}
                      name={line.consultant_name}
                      className="truncate font-medium text-foreground"
                    />
                    <span className="text-muted-foreground">
                      <span className="block text-[10px] uppercase tracking-wide">kosztowa</span>
                      {line.rate_cost == null ? "—" : `${formatPLN(line.rate_cost)}/MD`}
                    </span>
                    <span className="text-muted-foreground">
                      <span className="block text-[10px] uppercase tracking-wide">przychodowa</span>
                      {line.rate_revenue == null
                        ? "—"
                        : `${formatPLN(line.rate_revenue)}/MD`}
                    </span>
                    <div className="text-muted-foreground">
                      <span className="block text-[10px] uppercase tracking-wide">
                        Budżet MD
                      </span>
                      {usesSharedMdPool(future) ? (
                        "wspólna pula"
                      ) : hasScopedMd(line, future) ? (
                        <MdScopeBars line={line} className="mt-1" />
                      ) : (
                        <MdBudgetBar
                          remaining={line.md_remaining}
                          total={line.md_total}
                          className="mt-1 gap-2"
                        />
                      )}
                    </div>
                    {canManage ? (
                      <button
                        type="button"
                        onClick={() => onEditLine(future, line)}
                        aria-label={`Edytuj dane konsultanta ${line.consultant_name} w przyszłym zamówieniu`}
                        title="Edytuj stawki i MD"
                        className="justify-self-start rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground sm:justify-self-end"
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface Props {
  clientId: number;
  group: OrderGroupRead;
  searchQuery?: string;
  canManage: boolean;
  /** Usuwanie / kończenie / przywracanie / przedłużanie — szersza rola niż
   *  `canManage` (stawki). Lustro backendowego `_ORDER_LIFECYCLE_ROLES`. */
  canManageLifecycle: boolean;
  onAddConsultant: (group: OrderGroupRead) => void;
  onEditGroup: (group: OrderGroupRead) => void;
  onEditLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onSwapLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onResolveOffboarding: (group: OrderGroupRead, line: OrderLineRead) => void;
  /** „Zostaw jako historię" — osoba z zakończoną współpracą zostaje. */
  onKeepHistory?: (group: OrderGroupRead, line: OrderLineRead) => void;
  /** „Zastąp kimś innym" — nowa osoba dołącza obok tej linii. */
  onReplaceLine?: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteGroup: (group: OrderGroupRead) => void;
  onCloseGroup: (group: OrderGroupRead) => void;
  onReopenGroup: (group: OrderGroupRead) => void;
  /** Anulowanie (tylko bez rozliczeń) i jego cofnięcie. */
  onCancelGroup?: (group: OrderGroupRead) => void;
  onRestoreGroup?: (group: OrderGroupRead) => void;
  onExtendGroup: (group: OrderGroupRead) => void;
  /** Klik w numer zamówienia powiązanego wpisem `transfer_md`. Rozstrzygnięcie,
   *  KTÓRA karta pokaże cel, należy do rodzica — tylko on widzi całą listę. */
  onFocusGroup: (groupId: number) => void;
  /** Ostatnie żądanie pokazania zamówienia — kierowane do wszystkich kart. */
  focusRequest?: OrderGroupFocusRequest | null;
}

export function OrderGroupCard({
  clientId,
  group,
  searchQuery = "",
  canManage,
  canManageLifecycle,
  onAddConsultant,
  onEditGroup,
  onEditLine,
  onSwapLine,
  onDeleteLine,
  onResolveOffboarding,
  onKeepHistory,
  onReplaceLine,
  onDeleteGroup,
  onCloseGroup,
  onReopenGroup,
  onCancelGroup,
  onRestoreGroup,
  onExtendGroup,
  onFocusGroup,
  focusRequest = null,
}: Props) {
  const [expanded, setExpanded] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pendingFocusId, setPendingFocusId] = useState<number | null>(null);
  // Linia, której rozliczenia miesięczne są otwarte. Trzymamy CAŁĄ linię, nie
  // id: po zapisie lista grup się odświeża, a dialog ma zostać przy tej samej
  // osobie także wtedy, gdy nowa odpowiedź jeszcze nie dotarła.
  const [consumptionLine, setConsumptionLine] = useState<OrderLineRead | null>(null);
  const servedFocusRef = useRef<number | null>(null);

  // Żądanie adresuje tę kartę, gdy celem jest ona sama albo któreś z jej
  // zagnieżdżonych przyszłych zamówień. Zagnieżdżone istnieją w DOM dopiero po
  // rozwinięciu karty, więc samo `scrollIntoView` na zwiniętej nie miałoby do
  // czego trafić — najpierw rozwijamy, przewijamy w efekcie obok.
  useEffect(() => {
    if (!focusRequest || servedFocusRef.current === focusRequest.nonce) return;
    if (!flattenOrderGroupIds([group]).includes(focusRequest.groupId)) return;
    // Zapamiętanie obsłużonego żądania — bez tego odświeżenie listy (nowa
    // identyczność `group`) przewijałoby ekran drugi raz, długo po kliknięciu.
    servedFocusRef.current = focusRequest.nonce;
    setExpanded(true);
    setPendingFocusId(focusRequest.groupId);
  }, [focusRequest, group]);

  useEffect(() => {
    if (pendingFocusId == null || !expanded) return;
    document
      .getElementById(orderGroupAnchorId(pendingFocusId))
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
    setPendingFocusId(null);
  }, [pendingFocusId, expanded]);

  const history = useQuery({
    queryKey: ["order-group-events", clientId, group.id],
    queryFn: async () => (await orderGroupsApi.events(clientId, group.id)).data,
    enabled: historyOpen,
  });

  const sortedLines = sortOrderLinesByConsultant(group.lines);
  // „Aktywna obsada" znaczy dokładnie tyle, ile mówi: osoby, które DZIŚ pracują
  // na tym zamówieniu. Do 09.2026 wisiała tu także osoba z nierozstrzygniętą
  // sprawą offboardingu — żeby decyzja DL nie zginęła — przez co sekcja
  // odpowiadała na dwa różne pytania naraz i zespół czytał ją jako listę
  // pracujących. Sprawa wędruje teraz razem z wierszem do „Zakończone", a żeby
  // nie zniknęła z oczu, nagłówek tej sekcji niesie licznik decyzji.
  // Zaplanowane zastępstwo (ticket 09.2026) czeka jako szkic w aktywnym
  // zamówieniu — należy do bieżącej obsady, nie do „Zakończonych".
  const isDraftLine = (line: OrderLineRead) =>
    (group.status === "draft" && line.status === "draft") ||
    line.takeover_scheduled === true;
  const currentLines = sortedLines.filter(
    (line) => line.is_active || isDraftLine(line),
  );
  const activeLines = currentLines.filter((line) => line.is_active);
  // „Zakończone" sortują się datą zejścia malejąco, nie alfabetem: sekcja mówi,
  // kto ostatnio zszedł z zamówienia.
  const completedLines = sortOrderLinesByEnd(
    sortedLines.filter((line) => !line.is_active && !isDraftLine(line)),
  );
  const pendingDecisions = completedLines.filter(
    (line) => line.offboarding_case?.status === "pending",
  ).length;
  const isActive = group.status === "active";
  const isCancelled = group.status === "cancelled";
  // Pilotaż karty konsultanta: WYŁĄCZNIE Centrum e-Zdrowia (po `clientId`, nie
  // po samym `md_optional_total` — zakres opcjonalny bywa też u innych klientów,
  // a ci mają zachować dotychczasowy wiersz). Kosztowe i wspólna pula nie mają
  // podstawy/opcji per osoba, więc zostają przy starym układzie.
  const compactCez = isEzdrowieClient(clientId);
  const usesScopedCard = (line: OrderLineRead) =>
    compactCez &&
    hasScopedMd(line, group) &&
    !group.is_cost_based &&
    !usesSharedMdPool(group);
  const lineListClass = (lines: OrderLineRead[]) =>
    lines.some(usesScopedCard)
      ? "flex flex-col gap-2 rounded-xl bg-muted/40 p-2"
      : "flex flex-col divide-y divide-border";

  return (
    <section
      id={orderGroupAnchorId(group.id)}
      className="rounded-xl border border-border bg-card"
    >
      {/* Nagłówek karty — numer, okres, awatary konsultantów */}
      <div className="flex w-full items-center gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-foreground">
            {/* Numer jest poza przyciskiem rozwijającym i jawnie zezwala na
                zaznaczanie tekstu. Natywny button przejmował gest myszy,
                przez co kopiowanie numeru nie działało standardowo. */}
            <span className="cursor-text select-text">
              Zamówienie nr {group.order_number}
            </span>
            {group.status !== "active" ? (
              <span
                className={cn(
                  "rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                  STATUS_BADGE[group.status] ?? "bg-muted text-muted-foreground",
                )}
              >
                {group.status_label}
              </span>
            ) : null}
            <OrderTypeBadge type={effectiveGroupOrderType(group)} />
          </p>
          <p className="text-xs text-muted-foreground">
            {periodLabel(group)}
            {group.closure_date
              ? ` · zakończone ${formatDate(group.closure_date)}`
              : ""}
            {group.status === "cancelled" && group.cancelled_at
              ? ` · anulowane ${formatDate(group.cancelled_at.slice(0, 10))}`
              : ""}
            {group.status === "cancelled" && group.cancellation_reason
              ? ` — ${group.cancellation_reason}`
              : ""}
          </p>
          {group.executive_contract ? (
            <p className="text-xs text-muted-foreground">
              {executiveContractLabel(group.executive_contract)}
            </p>
          ) : null}
        </div>

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={`order-group-${group.id}-content`}
          aria-label={`${expanded ? "Zwiń" : "Rozwiń"} zamówienie nr ${group.order_number}`}
          className="-my-2 flex shrink-0 items-center gap-4 rounded-md p-2 text-left transition-colors hover:bg-muted"
        >
          <span className="flex -space-x-2" aria-hidden="true">
            {activeLines.slice(0, 5).map((line) => (
              <Avatar
                key={line.id}
                className="h-7 w-7 border-2 border-card"
                title={line.consultant_name}
              >
                <AvatarFallback className="bg-primary/10 text-[10px] font-semibold text-primary">
                  {initials(line.consultant_name)}
                </AvatarFallback>
              </Avatar>
            ))}
            {activeLines.length > 5 ? (
              <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-card bg-muted text-[10px] font-semibold text-muted-foreground">
                +{activeLines.length - 5}
              </span>
            ) : null}
          </span>

          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
              expanded && "rotate-180",
            )}
            aria-hidden="true"
          />
        </button>
      </div>

      {expanded ? (
        <div
          id={`order-group-${group.id}-content`}
          className="border-t border-border px-5 py-4"
        >
          {group.is_cost_based ? (
            <div className="mb-4">
              <BudgetBar group={group} />
              {group.status === "exhausted" ? (
                <p
                  role="status"
                  className="mt-2 flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  Budżet wyczerpany — zamówienie nie przyjmuje nowych
                  konsultantów. Zorganizuj nowe zamówienie albo skoryguj kwotę.
                </p>
              ) : null}
            </div>
          ) : null}

          {/* Pasek pozycji i „Wykorzystano wartości umowy" WYŁĄCZNIE przy
              umowie wykonawczej — backend liczy `md_positions_total` dla
              każdego zamówienia MD per osoba, a BIK/Polkomtel mają wyglądać
              dokładnie jak przed strukturą umów CeZ. */}
          {group.executive_contract &&
          group.md_positions_total != null &&
          !group.is_cost_based ? (
            <div className="mb-4">
              <PositionsMdBar group={group} />
            </div>
          ) : null}

          {usesSharedMdPool(group) ? (
            <div className="mb-4">
              <SharedMdBudgetBar group={group} />
              {group.status === "exhausted" ||
              (group.md_budget_total != null &&
                (group.md_budget_remaining ?? 0) <= 0) ? (
                <p
                  role="status"
                  className="mt-2 flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive"
                >
                  <AlertTriangle
                    className="mt-0.5 h-3.5 w-3.5 shrink-0"
                    aria-hidden
                  />
                  Budżet MD wyczerpany — pozostało 0 MD i zamówienie nie
                  przyjmuje nowych konsultantów. Zorganizuj nowe zamówienie
                  albo skoryguj pulę.
                </p>
              ) : null}
            </div>
          ) : null}

          {group.lines.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              To zamówienie nie ma jeszcze konsultantów.
            </p>
          ) : (
            <div className="flex flex-col gap-5">
              <section aria-labelledby={`order-group-${group.id}-active-heading`}>
                <h4
                  id={`order-group-${group.id}-active-heading`}
                  className={cn(
                    "mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                    completedLines.length === 0 && "sr-only",
                  )}
                >
                  {group.status === "draft" ? "Konsultanci w szkicu" : "Aktywna obsada"}
                </h4>
                {currentLines.length === 0 ? (
                  <p className="py-3 text-sm text-muted-foreground">
                    Brak aktywnych konsultantów.
                  </p>
                ) : (
                  <ul className={lineListClass(currentLines)}>
                    {currentLines.map((line) => (
                      <OrderLineRow
                        key={line.id}
                        group={group}
                        line={line}
                        searchQuery={searchQuery}
                        canManage={canManage}
                        canManageLifecycle={canManageLifecycle}
                        onEditLine={onEditLine}
                        onSwapLine={onSwapLine}
                        onDeleteLine={onDeleteLine}
                        onResolveOffboarding={onResolveOffboarding}
                        onKeepHistory={onKeepHistory}
                        onReplaceLine={onReplaceLine}
                        onShowConsumptions={(_group, selected) => setConsumptionLine(selected)}
                        scopedCardLayout={usesScopedCard(line)}
                        cardSurface={currentLines.some(usesScopedCard)}
                      />
                    ))}
                  </ul>
                )}
              </section>

              {completedLines.length > 0 ? (
                <section
                  aria-labelledby={`order-group-${group.id}-completed-heading`}
                  className="border-t border-border pt-4"
                >
                  <h4
                    id={`order-group-${group.id}-completed-heading`}
                    className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    Zakończone
                    {pendingDecisions > 0 ? (
                      <span className="ml-2 font-semibold normal-case tracking-normal text-amber-600 dark:text-amber-500">
                        {`· ${pendingDecisions} ${
                          pendingDecisions === 1
                            ? "wymaga decyzji"
                            : "wymagają decyzji"
                        }`}
                      </span>
                    ) : null}
                  </h4>
                  <ul className={lineListClass(completedLines)}>
                    {completedLines.map((line) => (
                      <OrderLineRow
                        key={line.id}
                        group={group}
                        line={line}
                        searchQuery={searchQuery}
                        canManage={canManage}
                        canManageLifecycle={canManageLifecycle}
                        onEditLine={onEditLine}
                        onSwapLine={onSwapLine}
                        onDeleteLine={onDeleteLine}
                        onResolveOffboarding={onResolveOffboarding}
                        onKeepHistory={onKeepHistory}
                        onReplaceLine={onReplaceLine}
                        onShowConsumptions={(_group, selected) => setConsumptionLine(selected)}
                        scopedCardLayout={usesScopedCard(line)}
                        cardSurface={completedLines.some(usesScopedCard)}
                      />
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
          )}

          {canManage || canManageLifecycle ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {canManage ? (
                <button
                  type="button"
                  onClick={() => onAddConsultant(group)}
                  disabled={!group.can_add_consultant}
                  title={
                    group.can_add_consultant
                      ? undefined
                      : `Zamówienie jest ${group.status_label.toLowerCase()} — nie można dodać konsultanta`
                  }
                  className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj konsultanta do
                  zamówienia
                </button>
              ) : null}
              {canManage && !isCancelled ? (
                <button
                  type="button"
                  onClick={() => onEditGroup(group)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Uzupełnij zamówienie
                </button>
              ) : null}

              {canManageLifecycle && isCancelled ? (
                onRestoreGroup ? (
                  <button
                    type="button"
                    onClick={() => onRestoreGroup(group)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Przywróć anulowane
                  </button>
                ) : null
              ) : null}
              {canManageLifecycle && !isCancelled ? (
                <>
                  <button
                    type="button"
                    onClick={() => onExtendGroup(group)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                  >
                    <CalendarPlus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj
                    przedłużenie
                  </button>
                  {isActive ? (
                    <button
                      type="button"
                      onClick={() => onCloseGroup(group)}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                    >
                      <SquareCheckBig className="h-3.5 w-3.5" aria-hidden="true" /> Zakończ
                    </button>
                  ) : null}
                  {group.status === "completed" ? (
                    <button
                      type="button"
                      onClick={() => onReopenGroup(group)}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Przywróć
                    </button>
                  ) : null}
                  {onCancelGroup ? (
                    <button
                      type="button"
                      onClick={() => onCancelGroup(group)}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                    >
                      <Ban className="h-3.5 w-3.5" aria-hidden="true" /> Anuluj zamówienie
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => onDeleteGroup(group)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-destructive/40 px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Usuń całe
                    zamówienie
                  </button>
                </>
              ) : null}
              {canManageLifecycle && isCancelled ? (
                <button
                  type="button"
                  onClick={() => onDeleteGroup(group)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-destructive/40 px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Usuń całe
                  zamówienie
                </button>
              ) : null}
            </div>
          ) : null}

          <FutureOrders
            orders={group.future_orders}
            searchQuery={searchQuery}
            canManage={canManage}
            canManageLifecycle={canManageLifecycle}
            onEditGroup={onEditGroup}
            onAddConsultant={onAddConsultant}
            onEditLine={onEditLine}
            onDeleteGroup={onDeleteGroup}
            compact={compactCez}
          />

          <div className={cn("border-t border-border", compactCez ? "mt-3 pt-2" : "mt-4 pt-3")}>
            <button
              type="button"
              onClick={() => setHistoryOpen((v) => !v)}
              aria-expanded={historyOpen}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
            >
              <History className="h-3.5 w-3.5" aria-hidden="true" />
              Historia zamówienia (
              {countPl(group.event_count, "wpis", "wpisy", "wpisów")})
              <ChevronDown
                className={cn("h-3 w-3 transition-transform", historyOpen && "rotate-180")}
                aria-hidden="true"
              />
            </button>

            {historyOpen ? (
              <div className={compactCez ? "mt-2" : "mt-3"}>
                {history.isError ? (
                  // Awaria pobrania NIE może wyglądać jak „brak historii" —
                  // pusta lista czytałaby się jak utrata zapisów.
                  <QueryStateNotice
                    state="error"
                    description="Nie udało się wczytać historii tego zamówienia."
                    onRetry={() => history.refetch()}
                  />
                ) : !history.isSuccess ? (
                  // Warunek na `isSuccess`, a NIE `isLoading`: między ponowieniami
                  // react-query ma `isLoading === false`, `isError === false`
                  // i puste `data`, więc gałąź „brak wpisów" wygrywała i ekran
                  // twierdził, że historia jest pusta, zanim cokolwiek wiadomo.
                  <p className="text-xs text-muted-foreground">Wczytywanie historii…</p>
                ) : history.data.events.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Brak wpisów w historii.</p>
                ) : (
                  <ol className={cn("flex flex-col", compactCez ? "gap-1" : "gap-2")}>
                    {history.data.events.map((ev) => {
                      // Nieznany typ zdarzenia dostaje ikonę domyślną — nowy
                      // slug z backendu ma wyrenderować wiersz, a nie pustkę.
                      const EventIcon = EVENT_ICON[ev.event_type] ?? History;
                      return (
                        <li key={ev.id} className={cn("flex text-xs", compactCez ? "gap-2" : "gap-3")}>
                          <span
                            className={cn(
                              "shrink-0 tabular-nums text-muted-foreground",
                              compactCez ? "w-28" : "w-32",
                            )}
                          >
                            {formatDateTimePl(ev.created_at)}
                          </span>
                          {/* KTO — bez tego nie dało się ustalić, kto zmienił
                              budżet (UAT B50). Pusty autor to zdarzenie
                              automatyczne, nie brak danych: każdy handler
                              z użytkownikiem stempluje `created_by_user_id`. */}
                          <span
                            className={cn(
                              "shrink-0 break-words text-muted-foreground",
                              compactCez ? "w-28" : "w-32",
                            )}
                            title={eventAuthor(ev)}
                          >
                            {eventAuthor(ev)}
                          </span>
                          <span
                            className={cn(
                              "flex shrink-0 items-center gap-1.5 font-medium text-foreground",
                              compactCez ? "w-32" : "w-36",
                            )}
                          >
                            <EventIcon
                              className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                              aria-hidden="true"
                            />
                            {ev.event_label}
                          </span>
                          <span className="text-muted-foreground">
                            <EventDescription event={ev} onFocusGroup={onFocusGroup} />
                          </span>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {consumptionLine ? (
        <LineMonthlyHistoryDialog
          clientId={clientId}
          group={group}
          line={consumptionLine}
          canEdit={canManage}
          open
          onClose={() => setConsumptionLine(null)}
        />
      ) : null}
    </section>
  );
}

/** Wykonawca wpisu historii: nazwa, sam identyfikator (konto usunięte) albo system. */
function eventAuthor(ev: OrderGroupEvent): string {
  if (ev.created_by_name) return ev.created_by_name;
  if (ev.created_by_user_id != null) return `Użytkownik #${ev.created_by_user_id}`;
  return "Automatycznie (system)";
}
