"use client";

import { useState } from "react";
import { CalendarDays, ChevronDown, Pencil, Repeat, Trash2 } from "lucide-react";

import { ContractPersonLink } from "@/components/contracts/ContractPersonLink";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import { usesSharedMdPool } from "@/lib/client-order-list";
import {
  agreementSentence,
  decisionLabel,
  ENDED_STATUS_LABEL,
  endedPeriod,
  endedStatus,
  endedUsage,
  hasPendingPoolDecision,
  requiresDecision,
} from "@/lib/order-ended-line";
import { hasScopedMd, lineHasSettlements } from "@/lib/order-line-usage";
import { MD_TRANSFER_METHOD_LABELS } from "@/lib/order-takeover";
import { cn } from "@/lib/utils";
import { formatDate, formatPLN } from "@/types/client-profile";

import { formatMd, MdBudgetBar } from "./MdBudgetBar";
import { MdScopeBars, MdScopePanels, MdScopeTotalBar } from "./MdScopeBars";
import {
  displayLineRate,
  focusOrderLine,
  initials,
  orderLineAnchorId,
} from "./order-line-display";

const SETTLED_LINE_DELETE_HINT =
  "Nie można usunąć — konsultant ma rozliczenia (MD lub faktury).";

interface Props {
  group: OrderGroupRead;
  line: OrderLineRead;
  highlighted: boolean;
  canManage: boolean;
  canEditAmounts: boolean;
  canManageLifecycle: boolean;
  onEditLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onSwapLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  /** Otwiera okno decyzji (także „Zmień decyzję"). */
  onDecide: (line: OrderLineRead) => void;
  onShowConsumptions?: (line: OrderLineRead) => void;
  /** Centrum e-Zdrowia: podstawa | opcja | łącznie jak na karcie konsultanta. */
  scopedPanels?: boolean;
}

/** Karta osoby z sekcji „Zakończone" (ticket 6, 09.2026).
 *
 *  Zwinięta odpowiada na cztery pytania: kto, że zakończył i kiedy, ile
 *  wykorzystał, czy trzeba podjąć decyzję. Stawki, pula, pochodzenie, umowa
 *  i akcje są w rozwinięciu — wcześniej wszystko stało naraz i nie było
 *  wiadomo, na co patrzeć. */
export function EndedLineCard({
  group,
  line,
  highlighted,
  canManage,
  canEditAmounts,
  canManageLifecycle,
  onEditLine,
  onSwapLine,
  onDeleteLine,
  onDecide,
  onShowConsumptions,
  scopedPanels = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const detailsId = `${orderLineAnchorId(line.id)}-details`;
  const needsDecision = requiresDecision(line);
  const pendingPool = hasPendingPoolDecision(line);
  const canDecide = canManage || canManageLifecycle;
  const status = endedStatus(line);
  const usage = endedUsage(group, line);
  const decided = decisionLabel(line);
  const agreement = agreementSentence(line);
  const sharedMd = usesSharedMdPool(group);
  const perPersonMd = !group.is_cost_based && !sharedMd;
  const hasSettlements = lineHasSettlements(line);
  const showRates = line.rate_cost != null || line.rate_revenue != null;
  // MD przeniesione na następcę nie są już „pozostało" u osoby odchodzącej.
  const transferredOut =
    line.replaced_by_md != null &&
    (line.replaced_by_kind === "swap" || line.replaced_by_kind === "takeover") &&
    !line.replaced_by_scheduled;
  const barLine: OrderLineRead = transferredOut ? { ...line, md_remaining: 0 } : line;
  // Po decyzji wolno ją zmienić tylko wtedy, gdy nic nieodwracalnego się nie
  // stało: zostawienie jako historii da się zamienić na zastępstwo albo
  // usunięcie. Rozstrzygniętej sprawy puli ani zamiany serwer nie cofa.
  const canChangeDecision =
    canDecide &&
    Boolean(line.history_kept_at) &&
    !line.removed_from_order &&
    line.replaced_by_order_id == null;

  const toggle = () => setOpen((value) => !value);

  return (
    <li
      id={orderLineAnchorId(line.id)}
      className={cn(
        "rounded-lg border px-3 py-2",
        needsDecision
          ? "border-destructive/50 bg-destructive/5"
          : "border-border bg-muted/30",
        highlighted && "ring-1 ring-inset ring-primary/30",
      )}
    >
      {/* Klik w dowolne miejsce karty rozwija szczegóły — poza linkami
          i przyciskami, które robią swoje. Klawiatura idzie przez strzałkę. */}
      <div
        className="flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-1.5 lg:grid lg:grid-cols-[minmax(0,1fr)_10rem_10rem_14rem]"
        onClick={(event) => {
          if ((event.target as HTMLElement).closest("a, button")) return;
          toggle();
        }}
      >
        <div className="flex min-w-[12rem] flex-1 items-center gap-3 lg:min-w-0">
          <Avatar className="h-7 w-7">
            <AvatarFallback
              className={cn(
                "text-[10px] font-semibold",
                needsDecision
                  ? "bg-destructive/15 text-destructive"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {initials(line.consultant_name)}
            </AvatarFallback>
          </Avatar>
          {/* Gdy brakuje miejsca, plakietka schodzi pod nazwisko — nazwisko
              („kto") nie może się ucinać ani łamać w środku słowa. */}
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <ContractPersonLink
              contractId={line.contract_id}
              name={line.consultant_name}
              className="text-sm font-medium leading-tight text-foreground"
            />
            <span
              className={cn(
                "shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                status === "cooperation"
                  ? "bg-foreground/10 text-foreground"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {ENDED_STATUS_LABEL[status]}
            </span>
          </div>
        </div>
        {/* Od `lg` siatka ze stałymi kolumnami: okres, wykorzystanie i akcja
            stoją w jednej linii na wszystkich kartach sekcji, niezależnie od
            długości nazwiska i opisu decyzji. Węziej — zawijanie. */}
        <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
          {endedPeriod(line)}
        </span>
        <span className="whitespace-nowrap text-xs font-medium tabular-nums text-foreground lg:text-right">
          {usage ?? ""}
        </span>
        <div className="ml-auto flex items-center justify-end gap-2">
          {needsDecision ? (
            canDecide && (canManage || !pendingPool) ? (
              <button
                type="button"
                onClick={() => onDecide(line)}
                aria-label={`Podejmij decyzję — ${line.consultant_name}`}
                className="rounded-md bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground transition-colors hover:bg-destructive/90"
              >
                Podejmij decyzję
              </button>
            ) : (
              <span className="text-xs font-medium text-destructive">
                Oczekuje na decyzję Delivery Leada
              </span>
            )
          ) : decided ? (
            line.replaced_by_order_id != null ? (
              <button
                type="button"
                onClick={() => focusOrderLine(line.replaced_by_order_id as number)}
                aria-label={`Pokaż następcę${
                  line.replaced_by_consultant_name
                    ? `: ${line.replaced_by_consultant_name}`
                    : ""
                }`}
                className="max-w-[10rem] text-right text-xs leading-tight text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                {decided}
              </button>
            ) : (
              <span className="max-w-[10rem] text-right text-xs leading-tight text-muted-foreground">
                {decided}
              </span>
            )
          ) : null}
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            aria-controls={detailsId}
            aria-label={`${open ? "Zwiń" : "Pokaż"} szczegóły — ${line.consultant_name}`}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            Szczegóły
            <ChevronDown
              className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
              aria-hidden="true"
            />
          </button>
        </div>
      </div>

      {open ? (
        <div
          id={detailsId}
          className="mt-2 flex flex-col gap-2 border-t border-border pt-2 pl-10 text-xs text-muted-foreground"
        >
          {showRates ? (
            <p className="flex flex-wrap gap-x-4 gap-y-1">
              <span title="Stawka kosztowa">
                koszt.{" "}
                <span className="font-medium text-foreground">
                  {displayLineRate(line, "cost")}
                </span>
              </span>
              <span title="Stawka przychodowa">
                przych.{" "}
                <span className="font-medium text-foreground">
                  {displayLineRate(line, "revenue")}
                </span>
              </span>
            </p>
          ) : null}

          {group.is_cost_based ? (
            <p>
              Zamówienie nr {group.order_number} · zafakturowano{" "}
              <span className="font-medium text-foreground">
                {line.invoiced_total == null || line.invoiced_total === 0
                  ? "brak faktur"
                  : formatPLN(line.invoiced_total)}
              </span>
            </p>
          ) : sharedMd ? (
            <p>
              Budżet MD: <span className="font-medium text-foreground">wspólna pula</span>
            </p>
          ) : scopedPanels ? (
            <div className="flex flex-col gap-2">
              <div className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
                <MdScopePanels line={barLine} />
              </div>
              <MdScopeTotalBar line={barLine} />
            </div>
          ) : hasScopedMd(line, group) ? (
            <MdScopeBars line={barLine} />
          ) : (
            <MdBudgetBar remaining={barLine.md_remaining} total={line.md_total} />
          )}

          {pendingPool && line.offboarding_case ? (
            <p className="font-medium text-destructive">
              Wymagana decyzja o pozostałej puli MD
              {line.offboarding_case.uses_shared_md_pool
                ? " (wspólna pula pozostaje bez zmian)."
                : line.offboarding_case.remaining_md_snapshot > 0
                  ? `: pozostało ${formatMd(line.offboarding_case.remaining_md_snapshot)} MD.`
                  : ": pula wykorzystana w całości (0 MD do przeniesienia)."}
            </p>
          ) : null}
          {line.replaced_by_scheduled ? (
            <p>
              Zastępstwo zaplanowane: {line.replaced_by_consultant_name} od{" "}
              {formatDate(line.replaced_by_start_date ?? null)} — pozostałe MD przejdą
              automatycznie w dniu wejścia.
            </p>
          ) : transferredOut && line.replaced_by_md != null ? (
            <p>
              {line.replaced_by_consultant_name ?? "Następca"} przejął(a){" "}
              {formatMd(line.replaced_by_md)} MD.
            </p>
          ) : null}

          {line.origin === "manual" && line.added_at ? (
            <p>
              Dodany ręcznie {formatDate(line.added_at)}
              {line.added_by_name ? ` przez ${line.added_by_name}` : ""}
              {line.replaces_name ? ` jako zastępstwo za ${line.replaces_name}` : ""}.
            </p>
          ) : null}
          {line.assignment_kind === "takeover" && line.takeover_from_name ? (
            <p>
              Przejęła po: {line.takeover_from_name}
              {line.takeover_md != null ? ` · ${formatMd(line.takeover_md)} MD` : ""}
              {line.takeover_method
                ? ` (${MD_TRANSFER_METHOD_LABELS[line.takeover_method]})`
                : ""}
            </p>
          ) : line.predecessor_consultant_name ? (
            <p>zastąpił: {line.predecessor_consultant_name}</p>
          ) : null}
          {line.history_kept_at ? (
            <p>
              Zostawiony jako historia {formatDate(line.history_kept_at)}
              {line.history_kept_by_name ? ` — ${line.history_kept_by_name}` : ""}.
            </p>
          ) : null}
          {agreement ? <p>{agreement}</p> : null}
          {line.missing_consumption_month ? (
            <p className="text-amber-700">
              Brak zejścia za {line.missing_consumption_month}
            </p>
          ) : null}
          {line.unsettled_total != null && line.unsettled_total > 0 ? (
            <p className="text-destructive">
              Nie udało się rozliczyć pełnej kwoty faktury — brakuje{" "}
              {formatPLN(line.unsettled_total)} na zamówieniu.
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            {perPersonMd && onShowConsumptions ? (
              <button
                type="button"
                onClick={() => onShowConsumptions(line)}
                aria-label={`Zużycie MD — ${line.consultant_name}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 font-medium text-foreground hover:bg-muted"
              >
                <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
                Zużycie MD
              </button>
            ) : null}
            {canManage || canEditAmounts ? (
              <button
                type="button"
                onClick={() => onEditLine(group, line)}
                aria-label={
                  canManage
                    ? `Edytuj linię — ${line.consultant_name}`
                    : `Edytuj stawki — ${line.consultant_name}`
                }
                title={canManage ? "Edytuj linię" : "Edytuj stawki"}
                className="rounded-md p-1.5 pointer-coarse:p-2.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Pencil className="h-4 w-4" aria-hidden="true" />
              </button>
            ) : null}
            {/* Linia MD kończy się budżetem, nie datą — osoba po zejściu bywa
                dalej `status: active` i serwer pozwala ją zamienić. */}
            {canManage && line.status === "active" ? (
              <button
                type="button"
                onClick={() => onSwapLine(group, line)}
                aria-label={`Zamień kontraktora — ${line.consultant_name}`}
                title="Zamień kontraktora"
                className="rounded-md p-1.5 pointer-coarse:p-2.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Repeat className="h-4 w-4" aria-hidden="true" />
              </button>
            ) : null}
            {/* Linia bez decyzji do podjęcia (np. zakończone zamówienie) nie ma
                okna decyzji — usunięcie zostaje tutaj, żeby nie zniknęło. */}
            {canManageLifecycle &&
            !needsDecision &&
            !pendingPool &&
            !canChangeDecision &&
            !line.removed_from_order ? (
              <button
                type="button"
                onClick={() => onDeleteLine(group, line)}
                disabled={hasSettlements}
                aria-label={`Usuń konsultanta z zamówienia — ${line.consultant_name}`}
                title={
                  hasSettlements ? SETTLED_LINE_DELETE_HINT : "Usuń konsultanta z zamówienia"
                }
                className="rounded-md p-1.5 pointer-coarse:p-2.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </button>
            ) : null}
            {canChangeDecision ? (
              <button
                type="button"
                onClick={() => onDecide(line)}
                className="rounded-md border border-border bg-background px-2.5 py-1 font-medium text-foreground hover:bg-muted"
              >
                Zmień decyzję
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  );
}
