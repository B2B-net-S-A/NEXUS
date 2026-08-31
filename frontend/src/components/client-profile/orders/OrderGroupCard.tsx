"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeftRight,
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
  SquareCheckBig,
  Trash2,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
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
  usesSharedMdPool,
} from "@/lib/client-order-list";
import { countPl } from "@/lib/plural-pl";
import { formatDate, formatPLN } from "@/types/client-profile";

import { formatMd, MdBudgetBar } from "./MdBudgetBar";
import { OrderTypeBadge } from "./OrderTypeBadge";

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

const STATUS_BADGE: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  scheduled: "bg-sky-100 text-sky-800",
  completed: "bg-zinc-200 text-zinc-700",
  exhausted: "bg-destructive/15 text-destructive",
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
}: OrderLineRowProps) {
  const pendingOffboarding = line.offboarding_case?.status === "pending";
  const completedCostLine = group.is_cost_based && !line.is_active;
  const sharedMd = usesSharedMdPool(group);

  return (
    <li
      className={cn(
        "flex flex-wrap items-center gap-x-6 gap-y-3 py-3",
        !line.is_active && !pendingOffboarding && "opacity-60",
        searchQuery.trim() &&
          consultantMatchesQuery(line.consultant_name, searchQuery) &&
          "rounded-md bg-primary/10 px-2 ring-1 ring-inset ring-primary/20",
        pendingOffboarding &&
          "my-1 rounded-lg border border-destructive/50 bg-destructive/10 px-3 opacity-100 ring-1 ring-inset ring-destructive/20",
      )}
    >
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
            <span className="truncate">{line.consultant_name}</span>
            {pendingOffboarding ? (
              <span className="rounded bg-destructive px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-destructive-foreground">
                Zakończenie współpracy
              </span>
            ) : null}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {pendingOffboarding
              ? "Współpraca zakończona"
              : line.is_active
                ? "Konsultant"
                : "Zakończony"}
            {line.start_date ? ` · od ${formatDate(line.start_date)}` : ""}
            {!line.is_active && line.end_date
              ? ` do ${formatDate(line.end_date)}`
              : ""}
          </p>
          {pendingOffboarding && line.offboarding_case ? (
            <p role="status" className="mt-1 text-xs font-medium text-destructive">
              Kontrakt zakończył się {formatDate(line.offboarding_case.effective_date)}.
              Wymagana decyzja o pozostałej puli MD
              {line.offboarding_case.uses_shared_md_pool
                ? " (wspólna pula pozostaje bez zmian)."
                : "."}
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
          {line.predecessor_consultant_name ? (
            <p className="truncate text-xs text-muted-foreground">
              zastąpił: {line.predecessor_consultant_name}
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

      {/* Stawki — „—" gdy rola nie ma uprawnień finansowych. Zniknięcie
          kolumny zostawiłoby pustkę bez wyjaśnienia. */}
      <div className="min-w-[8rem]">
        <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Stawka kosztowa
        </p>
        <p className="text-sm font-medium text-foreground">
          {line.rate_cost === null ? "—" : `${formatPLN(line.rate_cost)}/MD`}
        </p>
      </div>
      <div className="min-w-[8rem]">
        <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Stawka przychodowa
        </p>
        <p className="text-sm font-medium text-foreground">
          {line.rate_revenue === null
            ? "—"
            : `${formatPLN(line.rate_revenue)}/MD`}
        </p>
      </div>

      {group.is_cost_based ? (
        <div className="ml-auto min-w-[8rem]">
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Zafakturowano
          </p>
          <p className="text-sm font-medium text-foreground">
            {/* „—" dla braku faktur, nie „0 zł": zero znaczyłoby
                „wystawiono zero", a tu nic jeszcze nie przyszło. */}
            {line.invoiced_total == null || line.invoiced_total === 0
              ? "—"
              : formatPLN(line.invoiced_total)}
          </p>
        </div>
      ) : sharedMd ? (
        <div className="ml-auto min-w-[8rem] text-right">
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Budżet MD
          </p>
          <p className="text-sm font-medium text-foreground">Wspólna pula</p>
        </div>
      ) : (
        <MdBudgetBar
          remaining={line.md_remaining}
          total={line.md_total}
          className="ml-auto"
        />
      )}

      {pendingOffboarding ? (
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
      ) : canManage || canManageLifecycle ? (
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
                disabled={!line.is_active}
                aria-label={`Zamień kontraktora — ${line.consultant_name}`}
                title={
                  line.is_active
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
              aria-label={`Usuń konsultanta z zamówienia — ${line.consultant_name}`}
              title="Usuń konsultanta z zamówienia"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      ) : null}
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
}: FutureOrdersProps) {
  if (orders.length === 0) return null;

  return (
    <div className="mt-4 border-t border-border pt-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Clock3 className="h-3.5 w-3.5" aria-hidden />
        Przyszłe zamówienia ({orders.length})
      </p>
      <ul className="mt-2 divide-y divide-border rounded-lg border border-border bg-background">
        {orders.map((future) => (
          <li key={future.id} id={orderGroupAnchorId(future.id)} className="p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-foreground">
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
              <div className="mt-2">
                <SharedMdBudgetBar group={future} />
              </div>
            ) : null}

            {future.lines.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">
                To zamówienie nie ma jeszcze konsultantów.
              </p>
            ) : (
              <ul className="mt-2 divide-y divide-border/70">
                {sortOrderLinesByConsultant(future.lines).map((line) => (
                  <li
                    key={line.id}
                    className={cn(
                      "grid grid-cols-1 gap-2 py-2 text-xs sm:grid-cols-[minmax(9rem,1fr)_repeat(3,minmax(6.5rem,auto))_auto] sm:items-center",
                      searchQuery.trim() &&
                        consultantMatchesQuery(line.consultant_name, searchQuery) &&
                        "rounded-md bg-primary/10 px-2 ring-1 ring-inset ring-primary/20",
                    )}
                  >
                    <span className="truncate font-medium text-foreground">
                      {line.consultant_name}
                    </span>
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
  onDeleteGroup: (group: OrderGroupRead) => void;
  onCloseGroup: (group: OrderGroupRead) => void;
  onReopenGroup: (group: OrderGroupRead) => void;
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
  onDeleteGroup,
  onCloseGroup,
  onReopenGroup,
  onExtendGroup,
  onFocusGroup,
  focusRequest = null,
}: Props) {
  const [expanded, setExpanded] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pendingFocusId, setPendingFocusId] = useState<number | null>(null);
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
  const activeLines = sortedLines.filter(
    (line) => line.is_active && line.offboarding_case?.status !== "pending",
  );
  // Sprawa pending pozostaje na widoku głównym do czasu decyzji, ale nie jest
  // już liczona jako aktywna obsada w awatarach nagłówka.
  const currentLines = sortedLines.filter(
    (line) => line.is_active || line.offboarding_case?.status === "pending",
  );
  const completedLines = sortedLines.filter(
    (line) => !line.is_active && line.offboarding_case?.status !== "pending",
  );
  const isActive = group.status === "active";

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
          </p>
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
                  Aktywna obsada
                </h4>
                {currentLines.length === 0 ? (
                  <p className="py-3 text-sm text-muted-foreground">
                    Brak aktywnych konsultantów.
                  </p>
                ) : (
                  <ul className="flex flex-col divide-y divide-border">
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
                  </h4>
                  <ul className="flex flex-col divide-y divide-border">
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
              {canManage ? (
                <button
                  type="button"
                  onClick={() => onEditGroup(group)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Uzupełnij zamówienie
                </button>
              ) : null}

              {canManageLifecycle ? (
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
          />

          <div className="mt-4 border-t border-border pt-3">
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
              <div className="mt-3">
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
                  <ol className="flex flex-col gap-2">
                    {history.data.events.map((ev) => {
                      // Nieznany typ zdarzenia dostaje ikonę domyślną — nowy
                      // slug z backendu ma wyrenderować wiersz, a nie pustkę.
                      const EventIcon = EVENT_ICON[ev.event_type] ?? History;
                      return (
                        <li key={ev.id} className="flex gap-3 text-xs">
                          <span className="w-28 shrink-0 tabular-nums text-muted-foreground">
                            {formatDate(ev.created_at)}
                          </span>
                          <span className="flex w-36 shrink-0 items-center gap-1.5 font-medium text-foreground">
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
    </section>
  );
}
