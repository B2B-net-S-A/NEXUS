"use client";

import { useEffect, useState } from "react";
import { Ellipsis, Pencil, Repeat, Trash2 } from "lucide-react";

import { ContractPersonLink } from "@/components/contracts/ContractPersonLink";
import { DetailFacts, DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { MD_TRANSFER_METHOD_LABELS, swapBlockedReason } from "@/lib/order-takeover";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import { formatDate, formatPLN } from "@/types/client-profile";

import { formatPeriodMonthPl, LineConsumptionTable } from "./LineConsumptionTable";
import { formatMd, MdBudgetBar } from "./MdBudgetBar";
import { MdScopeBars, MdScopePanels, MdScopeTotalBar } from "./MdScopeBars";
import { OrderHistoryPanel } from "./OrderHistoryPanel";
import type { LinePanelTab } from "./OrdersTable";
import { displayLineRate } from "./order-line-display";
import { isCurrentLine } from "./orders-table-model";

const SETTLED_LINE_DELETE_HINT =
  "Nie można usunąć — konsultant ma rozliczenia (MD lub faktury). " +
  "Użyj „Zostaw jako historię” albo „Zakończ”.";

interface Props {
  clientId: number;
  group: OrderGroupRead;
  line: OrderLineRead;
  canManage: boolean;
  canEditAmounts: boolean;
  canManageLifecycle: boolean;
  initialTab?: LinePanelTab | null;
  onClose: () => void;
  onEditLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onSwapLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  /** Okno decyzji po zakończeniu współpracy (także „Zmień decyzję"). */
  onDecide: (group: OrderGroupRead, line: OrderLineRead) => void;
  onSelectLine: (groupId: number, lineId: number) => void;
  onSelectGroup: (groupId: number) => void;
}

/**
 * Panel osoby na zamówieniu MD/kosztowym (wersja B, 29.09.2026). Łączy
 * dawny wiersz obsady (`OrderLineRow`), kartę osoby zakończonej
 * z sekcji „Zakończone" i okno „Zużycie MD". Przyciski otwierają TE SAME okna.
 */
export function OrderLinePanel({
  clientId,
  group,
  line,
  canManage,
  canEditAmounts,
  canManageLifecycle,
  initialTab = null,
  onClose,
  onEditLine,
  onSwapLine,
  onDeleteLine,
  onDecide,
  onSelectLine,
  onSelectGroup,
}: Props) {
  const sharedMd = usesSharedMdPool(group);
  // Rozliczenia miesięczne mają sens tylko przy własnym budżecie MD osoby.
  const perPersonMd = !group.is_cost_based && !sharedMd;
  const ended = !isCurrentLine(line);
  const needsDecision = ended && requiresDecision(line);
  const pendingPool = hasPendingPoolDecision(line);
  const canDecide = canManage || canManageLifecycle;
  const hasSettlements = lineHasSettlements(line);
  const scheduledTakeover = line.takeover_scheduled === true;
  const canChangeDecision =
    canDecide && Boolean(line.history_kept_at) && !line.removed_from_order && line.replaced_by_order_id == null;
  // MD przeniesione na następcę nie są już „pozostało" u osoby odchodzącej.
  const transferredOut =
    ended &&
    line.replaced_by_md != null &&
    (line.replaced_by_kind === "swap" || line.replaced_by_kind === "takeover") &&
    !line.replaced_by_scheduled;
  const barLine: OrderLineRead = transferredOut ? { ...line, md_remaining: 0 } : line;
  const scopedCard = isEzdrowieClient(clientId) && hasScopedMd(line, group) && !group.is_cost_based && !sharedMd;

  const defaultTab: LinePanelTab = initialTab ?? (perPersonMd && !needsDecision ? "zuzycie" : "szczegoly");
  const [tab, setTab] = useState<LinePanelTab>(defaultTab);
  // Inna osoba w tym samym panelu — wróć do zakładki domyślnej dla niej.
  useEffect(() => {
    setTab(defaultTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [line.id, initialTab]);
  const effectiveTab: LinePanelTab = !perPersonMd && tab === "zuzycie" ? "szczegoly" : tab;

  const tabs = [
    ...(perPersonMd ? [{ value: "zuzycie", label: "Zużycie MD" }] : []),
    { value: "szczegoly", label: "Szczegóły" },
    { value: "historia", label: "Historia" },
  ];

  const statusChip = ended ? (
    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
      {ENDED_STATUS_LABEL[endedStatus(line)]}
    </span>
  ) : scheduledTakeover ? (
    <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
      Zaplanowane zastępstwo od {formatDate(line.start_date)}
    </span>
  ) : null;

  const budget = group.is_cost_based ? (
    <p className="text-sm">
      zafakturowano{" "}
      <span className="font-medium">
        {line.invoiced_total == null || line.invoiced_total === 0 ? "—" : formatPLN(line.invoiced_total)}
      </span>
    </p>
  ) : sharedMd ? (
    <p className="text-sm">wspólna pula MD zamówienia</p>
  ) : scopedCard ? (
    <div className="grid gap-2">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <MdScopePanels line={barLine} />
      </div>
      <MdScopeTotalBar line={barLine} />
    </div>
  ) : hasScopedMd(line, group) ? (
    <MdScopeBars line={barLine} />
  ) : (
    <MdBudgetBar remaining={barLine.md_remaining} total={line.md_total} />
  );

  const decisionButton = needsDecision ? (
    canDecide && (canManage || !pendingPool) ? (
      <Button type="button" size="sm" variant="destructive" onClick={() => onDecide(group, line)}>
        Podejmij decyzję
      </Button>
    ) : (
      <span className="text-xs font-medium text-destructive">Oczekuje na decyzję Delivery Leada</span>
    )
  ) : canChangeDecision ? (
    <Button type="button" size="sm" variant="outline" onClick={() => onDecide(group, line)}>
      Zmień decyzję
    </Button>
  ) : null;

  const canDelete =
    canManageLifecycle &&
    (!ended || (!needsDecision && !pendingPool && !canChangeDecision && !line.removed_from_order));
  const swapReason = swapBlockedReason(line);
  const showSwap = canManage && (!ended || swapReason === null);

  const footer =
    decisionButton || canManage || canEditAmounts || canManageLifecycle ? (
      <>
        {decisionButton}
        {canManage || canEditAmounts ? (
          <Button type="button" size="sm" variant={decisionButton ? "outline" : "primary"} onClick={() => onEditLine(group, line)}>
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            {canManage ? "Edytuj linię" : "Edytuj stawki"}
          </Button>
        ) : null}
        {showSwap ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onSwapLine(group, line)}
            disabled={swapReason !== null}
            title={swapReason ?? "Zamień kontraktora"}
          >
            <Repeat className="h-3.5 w-3.5" aria-hidden="true" /> Zamień kontraktora
          </Button>
        ) : null}
        {canDelete ? (
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button type="button" size="icon-sm" variant="outline" aria-label="Więcej akcji konsultanta" title="Więcej akcji">
                <Ellipsis className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              <DropdownMenuItem
                disabled={hasSettlements}
                title={hasSettlements ? SETTLED_LINE_DELETE_HINT : undefined}
                onSelect={() => window.setTimeout(() => onDeleteLine(group, line), 0)}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="h-4 w-4" /> Usuń konsultanta z zamówienia
              </DropdownMenuItem>
              {hasSettlements ? (
                <p className="px-2 pb-1.5 text-xs text-muted-foreground">{SETTLED_LINE_DELETE_HINT}</p>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </>
    ) : null;

  return (
    <DetailPanel
      compact
      data-testid="order-line-panel"
      title={line.consultant_name}
      badges={statusChip}
      subtitle={
        <>
          Zamówienie{" "}
          <button type="button" className="font-mono text-primary underline-offset-2 hover:underline" onClick={() => onSelectGroup(group.id)}>
            {group.order_number}
          </button>
          {line.start_date ? ` · od ${formatDate(line.start_date)}` : ""}
          {" · "}
          <ContractPersonLink contractId={line.contract_id} name="Otwórz kontrakt →" className="text-primary" />
        </>
      }
      onClose={onClose}
      closeLabel="Zamknij panel konsultanta"
      tabs={tabs}
      tab={effectiveTab}
      onTabChange={(value) => setTab(value as LinePanelTab)}
      footer={footer}
    >
      {effectiveTab === "zuzycie" ? (
        <>
          <DetailSection title="Budżet">{budget}</DetailSection>
          <LineConsumptionTable clientId={clientId} group={group} line={line} canEdit={canManage} compact />
        </>
      ) : effectiveTab === "historia" ? (
        <OrderHistoryPanel clientId={clientId} groupId={group.id} compact onFocusGroup={onSelectGroup} />
      ) : (
        <>
          {needsDecision && pendingPool && line.offboarding_case ? (
            <p role="status" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs font-medium text-destructive">
              Wymagana decyzja o pozostałej puli MD
              {line.offboarding_case.uses_shared_md_pool
                ? " (wspólna pula pozostaje bez zmian)."
                : line.offboarding_case.remaining_md_snapshot > 0
                  ? `: pozostało ${formatMd(line.offboarding_case.remaining_md_snapshot)} MD.`
                  : ": pula wykorzystana w całości (0 MD do przeniesienia)."}
            </p>
          ) : needsDecision ? (
            <p role="status" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs font-medium text-destructive">
              Osoba zakończyła współpracę — zdecyduj, co z nią na tym zamówieniu.
            </p>
          ) : null}
          {line.missing_consumption_month ? (
            <p className="rounded-md bg-warning-muted p-2 text-xs text-warning-muted-foreground">
              Brak zejścia za {formatPeriodMonthPl(line.missing_consumption_month)}
            </p>
          ) : null}
          {line.unsettled_total != null && line.unsettled_total > 0 ? (
            <p className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">
              Nie udało się rozliczyć pełnej kwoty faktury — brakuje {formatPLN(line.unsettled_total)} na zamówieniu.
            </p>
          ) : null}

          <DetailSection title="Na zamówieniu">
            <DetailFacts
              compact
              items={[
                ["Stawka kosztowa", displayLineRate(line, "cost")],
                ["Stawka przychodowa", displayLineRate(line, "revenue")],
                ended ? ["Okres", endedPeriod(line)] : null,
                ended && endedUsage(group, line) ? ["Wykorzystanie", endedUsage(group, line)] : null,
                ended && decisionLabel(line) ? ["Decyzja", decisionLabel(line)] : null,
              ]}
            />
          </DetailSection>

          <DetailSection title="Budżet">
            {group.is_cost_based ? (
              <p className="text-xs text-muted-foreground">Zamówienie nr {group.order_number}</p>
            ) : null}
            {budget}
            {ended ? (
              <p className="text-xs text-muted-foreground">
                Kwota i MD wykorzystane przez tę osobę nie wracają do puli dostępnej dla innych.
              </p>
            ) : null}
          </DetailSection>

          <DetailSection title="Relacje i historia osoby">
            <div className="grid gap-1 text-xs text-muted-foreground">
              {line.assignment_kind === "takeover" && line.takeover_from_name ? (
                <p>
                  {scheduledTakeover ? "Przejmie po" : "Przejęła po"}: {line.takeover_from_name}
                  {line.takeover_md != null ? ` · ${formatMd(line.takeover_md)} MD` : ""}
                  {line.takeover_method ? ` (${MD_TRANSFER_METHOD_LABELS[line.takeover_method]})` : ""}
                </p>
              ) : line.predecessor_consultant_name ? (
                <p>zastąpił: {line.predecessor_consultant_name}</p>
              ) : null}
              {line.replaced_by_order_id != null ? (
                <p>
                  {line.replaced_by_scheduled ? "Zastąpi go" : "Zastąpiony przez"}:{" "}
                  <button
                    type="button"
                    onClick={() => onSelectLine(group.id, line.replaced_by_order_id as number)}
                    className="font-medium text-primary underline-offset-2 hover:underline"
                  >
                    {line.replaced_by_consultant_name ?? "następca"}
                  </button>
                  {line.replaced_by_start_date ? ` od ${formatDate(line.replaced_by_start_date)}` : ""}
                </p>
              ) : null}
              {line.replaced_by_scheduled ? (
                <p>
                  Zastępstwo zaplanowane: {line.replaced_by_consultant_name} od {formatDate(line.replaced_by_start_date ?? null)} — pozostałe MD
                  przejdą automatycznie w dniu wejścia.
                </p>
              ) : transferredOut && line.replaced_by_md != null ? (
                <p>
                  {line.replaced_by_consultant_name ?? "Następca"} przejął(a) {formatMd(line.replaced_by_md)} MD.
                </p>
              ) : null}
              {line.origin === "manual" && line.added_at ? (
                <p>
                  Dodano do zamówienia {formatDate(line.added_at)}
                  {line.added_by_name ? ` (${line.added_by_name})` : ""}
                  {line.replaces_name ? ` jako zastępstwo za ${line.replaces_name}` : ""}.
                  {group.has_file ? " Dokument zamówienia (PDF) podpięto także do profilu tej osoby." : ""}
                </p>
              ) : null}
              {line.history_kept_at ? (
                <p>
                  Zostawiony jako historia {formatDate(line.history_kept_at)}
                  {line.history_kept_by_name ? ` — ${line.history_kept_by_name}` : ""}.
                </p>
              ) : null}
              {ended && agreementSentence(line) ? <p>{agreementSentence(line)}</p> : null}
              {!ended && !line.is_active && !scheduledTakeover ? <p>Szkic przypisania — uzupełnij budżet i stawki.</p> : null}
            </div>
          </DetailSection>
        </>
      )}
    </DetailPanel>
  );
}
