"use client";

// Części wspólne tabeli zamówień i paneli szczegółów (wersja B, 29.09.2026):
// paski budżetu, etykiety okresu i umowy wykonawczej, lista przyszłych
// zamówień. Wydzielone z dawnej karty zamówienia bez zmian zachowania.

import { Clock3, Pencil, Plus, Trash2 } from "lucide-react";

import { ContractPersonLink } from "@/components/contracts/ContractPersonLink";
import { cn } from "@/lib/utils";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  consultantMatchesQuery,
  effectiveGroupOrderType,
  sortOrderLinesByConsultant,
  usesSharedMdPool,
} from "@/lib/client-order-list";
import { formatDate, formatPLN } from "@/types/client-profile";
import { hasScopedMd } from "@/lib/order-line-usage";

import { formatMd, MdBudgetBar } from "./MdBudgetBar";
import { MdScopeBars } from "./MdScopeBars";
import { OrderTypeBadge } from "./OrderTypeBadge";
import { displayLineRate } from "./order-line-display";

export function periodLabel(group: OrderGroupRead): string {
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

export function executiveContractLabel(
  contract: NonNullable<OrderGroupRead["executive_contract"]>,
): string {
  const roman = contract.project_part ? PART_ROMAN[contract.project_part] : undefined;
  return roman
    ? `Umowa wykonawcza ${contract.number} · Cz. ${roman}`
    : `Umowa wykonawcza ${contract.number}`;
}

/** Pasek wykorzystania pozycji MD zamówienia (podstawa + opcja) — CeZ. */
export function PositionsMdBar({ group }: { group: OrderGroupRead }) {
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

export const STATUS_BADGE: Record<string, string> = {
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

/** Pasek wykorzystania budżetu kwotowego. Wypełnienie pokazuje POZOSTAŁOŚĆ —
 *  ta sama konwencja co przy MD, żeby dwa paski obok siebie nie znaczyły
 *  czegoś przeciwnego. */
export function BudgetBar({ group }: { group: OrderGroupRead }) {
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
export function SharedMdBudgetBar({ group }: { group: OrderGroupRead }) {
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

export interface FutureOrdersProps {
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
export function FutureOrders({
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
                      className="rounded p-1.5 pointer-coarse:p-2.5 text-muted-foreground hover:bg-muted hover:text-foreground"
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
                      className="rounded p-1.5 pointer-coarse:p-2.5 text-muted-foreground hover:bg-muted hover:text-foreground"
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
                      className="rounded p-1.5 pointer-coarse:p-2.5 text-destructive hover:bg-destructive/10"
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
                      // Panel ma ~350 px niezależnie od okna — kolumny liczone
                      // od szerokości panelu, nie od `sm:` okna (29.09.2026).
                      "grid grid-cols-[repeat(3,minmax(0,1fr))_auto] items-start text-xs",
                      compact ? "gap-1.5 py-1.5" : "gap-2 py-2",
                      searchQuery.trim() &&
                        consultantMatchesQuery(line.consultant_name, searchQuery) &&
                        "rounded-md bg-primary/10 px-2 ring-1 ring-inset ring-primary/20",
                    )}
                  >
                    <ContractPersonLink
                      contractId={line.contract_id}
                      name={line.consultant_name}
                      className="col-span-full truncate font-medium text-foreground"
                    />
                    <span className="min-w-0 text-muted-foreground">
                      <span className="block text-[10px] uppercase tracking-wide">kosztowa</span>
                      {/* Waluta linii jak w aktywnej obsadzie (N9, 24.09.2026) —
                          „/MD" w PLN przy stawce w EUR mylił o kurs. */}
                      {displayLineRate(line, "cost")}
                    </span>
                    <span className="min-w-0 text-muted-foreground">
                      <span className="block text-[10px] uppercase tracking-wide">przychodowa</span>
                      {displayLineRate(line, "revenue")}
                    </span>
                    <div className="min-w-0 text-muted-foreground">
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
                          className="mt-1 flex-wrap gap-x-2 gap-y-0.5"
                        />
                      )}
                    </div>
                    {canManage ? (
                      <button
                        type="button"
                        onClick={() => onEditLine(future, line)}
                        aria-label={`Edytuj dane konsultanta ${line.consultant_name} w przyszłym zamówieniu`}
                        title="Edytuj stawki i MD"
                        className="justify-self-end rounded p-1.5 pointer-coarse:p-2.5 text-muted-foreground hover:bg-muted hover:text-foreground"
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

