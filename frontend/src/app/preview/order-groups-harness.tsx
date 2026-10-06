"use client";

/**
 * Wspólna rama harnessów zamówień MD/kosztowych (wersja B, 29.09.2026):
 * PRODUKCYJNA tabela `OrdersTable` z panelami `OrderGroupPanel` /
 * `OrderLinePanel` w `ListDetailLayout` — ta sama plątanina zaznaczenia co
 * w `MultiConsultantOrdersTab`, ale bez zapytań o listę i bez okien zapisu.
 * Akcje z paneli nie mają serwera, więc harness tylko mówi, co by się
 * otworzyło (`onAction`).
 *
 * `seedOrderGroupPanels` zasiewa historię i zużycie MD każdego zamówienia
 * i każdej osoby — panel otwiera je od razu, a publiczny harness nie może
 * polecieć po nie do API.
 */

import { createContext, useContext, useId, useState, type ReactNode } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { EndedLineDecisionDialog } from "@/components/client-profile/orders/EndedLineDecisionDialog";
import { lineConsumptionsQueryKey } from "@/components/client-profile/orders/LineConsumptionTable";
import { OrderGroupPanel } from "@/components/client-profile/orders/OrderGroupPanel";
import { orderHistoryQueryKey } from "@/components/client-profile/orders/OrderHistoryPanel";
import { OrderLinePanel } from "@/components/client-profile/orders/OrderLinePanel";
import { OrdersTable, type LinePanelTab } from "@/components/client-profile/orders/OrdersTable";
import { sharedMdConsumptionsQueryKey } from "@/components/client-profile/orders/SharedMdConsumptionsSection";
import {
  buildSectionRows,
  findGroup,
  findLine,
  selectionFromKey,
  selectionKey,
  type OrderSelection,
  type OrdersTableSection,
} from "@/components/client-profile/orders/orders-table-model";
import { ContractorOrderPanel } from "@/components/client-profile/orders/ContractorOrderPanel";
import type { ContractWithOrdersRead, OrderType } from "@/lib/api/dlPortal";
import type {
  LineConsumptionsResponse,
  OrderGroupRead,
  SharedMdConsumptionsResponse,
  OrderHistoryEntry,
  OrderLineRead,
} from "@/lib/api/orderGroups";
import {
  ORDER_TYPE_ORDER,
  contractorOrderType,
  effectiveGroupOrderType,
  usesSharedMdPool,
} from "@/lib/client-order-list";

function allGroups(groups: readonly OrderGroupRead[]): OrderGroupRead[] {
  return groups.flatMap((group) => [group, ...allGroups(group.future_orders)]);
}

/** Historia i zużycie MD dla każdego zamówienia i każdej osoby (także
 *  w przyszłych zamówieniach). Klucz zasiany wcześniej przez stronę wygrywa. */
export function seedOrderGroupPanels(
  qc: QueryClient,
  clientId: number,
  groups: readonly OrderGroupRead[],
  data: {
    history?: Record<number, OrderHistoryEntry[]>;
    consumptions?: Record<number, LineConsumptionsResponse>;
    /** Zejścia wspólnej puli MD per zamówienie (sekcja „Zejścia MD”). */
    sharedConsumptions?: Record<number, SharedMdConsumptionsResponse>;
  } = {},
): void {
  for (const group of allGroups(groups)) {
    if (usesSharedMdPool(group)) {
      const sharedKey = sharedMdConsumptionsQueryKey(clientId, group.id);
      if (qc.getQueryData(sharedKey) === undefined) {
        qc.setQueryData<SharedMdConsumptionsResponse>(
          sharedKey,
          data.sharedConsumptions?.[group.id] ?? {
            months: [],
            consultants: group.lines.map((line) => ({
              order_id: line.id,
              consultant_name: line.consultant_name,
              status: line.status,
            })),
            md_budget_total: group.md_budget_total ?? null,
            md_used: group.md_budget_used ?? null,
            md_remaining: group.md_budget_remaining ?? null,
          },
        );
      }
    }
    const historyKey = orderHistoryQueryKey(clientId, group.id);
    if (qc.getQueryData(historyKey) === undefined) {
      const entries = data.history?.[group.id] ?? [];
      qc.setQueryData(historyKey, {
        entries,
        people: [...new Set(entries.flatMap((entry) => entry.person_names))].sort(),
      });
    }
    for (const line of group.lines) {
      const key = lineConsumptionsQueryKey(clientId, group.id, line.id);
      if (qc.getQueryData(key) === undefined) {
        qc.setQueryData(key, data.consumptions?.[line.id] ?? { rows: [] });
      }
    }
  }
}

function parentOf(groups: readonly OrderGroupRead[], groupId: number): OrderGroupRead | null {
  for (const group of groups) {
    if (group.future_orders.some((future) => future.id === groupId)) return group;
    const nested = parentOf(group.future_orders, groupId);
    if (nested) return nested;
  }
  return null;
}

/** Kilka tabel na jednej stronie (przypadki obok siebie) — panel naraz jeden,
 *  inaczej poniżej 1600 px nakładki paneli leżałyby na sobie. */
const ActivePanelContext = createContext<{
  activeId: string | null;
  setActiveId: (id: string | null) => void;
} | null>(null);

export function OrderGroupsHarnessGroup({ children }: { children: ReactNode }) {
  const [activeId, setActiveId] = useState<string | null>(null);
  return (
    <ActivePanelContext.Provider value={{ activeId, setActiveId }}>
      {children}
    </ActivePanelContext.Provider>
  );
}

export interface OrderGroupsHarnessProps {
  clientId: number;
  groups: OrderGroupRead[];
  canManage?: boolean;
  canManageLifecycle?: boolean;
  canEditAmounts?: boolean;
  /** Panel otwarty od wejścia (zrzuty ekranu jednego stanu). */
  initialSelection?: OrderSelection | null;
  initialLineTab?: LinePanelTab | null;
  /** Akcja bez serwera — „co by się otworzyło". */
  onAction?: (label: string) => void;
  /** „Zostaw jako historię" na stanie lokalnym strony. */
  onKeepHistory?: (group: OrderGroupRead, line: OrderLineRead) => void;
  panelLabel?: string;
}

export function OrderGroupsHarness({
  clientId,
  groups,
  canManage = true,
  canManageLifecycle = true,
  canEditAmounts = true,
  initialSelection = null,
  initialLineTab = null,
  onAction,
  onKeepHistory,
  panelLabel = "Szczegóły zamówienia",
}: OrderGroupsHarnessProps) {
  const harnessId = useId();
  const shared = useContext(ActivePanelContext);
  const [ownSelection, setSelection] = useState<OrderSelection | null>(initialSelection);
  // W grupie harnessów panel pokazuje tylko ostatnio kliknięta tabela.
  const selection =
    shared && shared.activeId !== null && shared.activeId !== harnessId ? null : ownSelection;
  const [lineTab, setLineTab] = useState<LinePanelTab | null>(initialLineTab);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() =>
    initialSelection?.kind === "line" ? new Set([initialSelection.groupId]) : new Set(),
  );
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
  const [decision, setDecision] = useState<{ group: OrderGroupRead; line: OrderLineRead } | null>(
    null,
  );

  const sections: OrdersTableSection[] = ORDER_TYPE_ORDER.map((type) => {
    const items = groups
      .filter((group) => effectiveGroupOrderType(group) === type)
      .map((group) => ({ kind: "group" as const, group }));
    return {
      type,
      itemCount: items.length,
      rows: buildSectionRows(items, { expandedEnded: expanded, collapsedEnded: collapsed }),
    };
  }).filter((section) => section.itemCount > 0);

  const note =
    (label: string) =>
    (group: OrderGroupRead, line?: OrderLineRead) =>
      onAction?.(`${label}: ${line ? line.consultant_name : `zamówienie nr ${group.order_number}`}`);

  const select = (next: OrderSelection | null, tab: LinePanelTab | null = null) => {
    setSelection(next);
    setLineTab(tab);
    if (next) shared?.setActiveId(harnessId);
  };
  const selectLine = (groupId: number, lineId: number) => {
    const found = findLine(groups, lineId);
    if (!found) return;
    setExpanded((prev) => new Set(prev).add(found.group.id));
    select({ kind: "line", groupId: found.group.id ?? groupId, lineId });
  };
  const selectGroup = (groupId: number) => select({ kind: "group", groupId });
  const close = () => select(null);

  const selectedGroup = selection?.kind === "group" ? findGroup(groups, selection.groupId) : null;
  const selectedLine = selection?.kind === "line" ? findLine(groups, selection.lineId) : null;

  let panel: React.ReactNode = null;
  if (selectedGroup) {
    panel = (
      <OrderGroupPanel
        key={`g-${selectedGroup.id}`}
        clientId={clientId}
        group={selectedGroup}
        parent={parentOf(groups, selectedGroup.id)}
        canManage={canManage}
        canManageLifecycle={canManageLifecycle}
        searchQuery=""
        onClose={close}
        onSelectLine={selectLine}
        onSelectGroup={selectGroup}
        onAddConsultant={note("Dodaj konsultanta")}
        onEditGroup={note("Uzupełnij zamówienie")}
        onEditLine={note("Edycja linii")}
        onExtendGroup={note("Dodaj przedłużenie")}
        onCloseGroup={note("Zakończ")}
        onReopenGroup={note("Przywróć")}
        onCancelGroup={note("Anuluj zamówienie")}
        onRestoreGroup={note("Przywróć anulowane")}
        onDeleteGroup={note("Usuń zamówienie")}
      />
    );
  } else if (selectedLine) {
    panel = (
      <OrderLinePanel
        key={`l-${selectedLine.line.id}`}
        clientId={clientId}
        group={selectedLine.group}
        line={selectedLine.line}
        canManage={canManage}
        canEditAmounts={canEditAmounts}
        canManageLifecycle={canManageLifecycle}
        initialTab={lineTab}
        onClose={close}
        onEditLine={note("Edycja linii")}
        onSwapLine={note("Zamiana kontraktora")}
        onDeleteLine={note("Usunięcie z zamówienia")}
        onDecide={(group, line) => setDecision({ group, line })}
        onSelectLine={selectLine}
        onSelectGroup={selectGroup}
      />
    );
  }

  // Panele pokazują komunikaty (np. błąd otwarcia PDF-a) — harness ma własny
  // dostawca, bo strony `/preview/*` renderują się bez powłoki aplikacji.
  return (
    <ToastProvider>
      <ListDetailLayout
        panelLabel={panelLabel}
        onClose={close}
        panel={panel}
        list={
          <OrdersTable
            sections={sections}
            selectedKey={selection ? selectionKey(selection) : null}
            onSelect={(key, tab) => {
              const next = selectionFromKey(key, sections);
              if (next) select(next, tab ?? null);
            }}
            onToggleEnded={(groupId, open) => {
              setExpanded((prev) => {
                const next = new Set(prev);
                if (open) next.add(groupId);
                else next.delete(groupId);
                return next;
              });
              setCollapsed((prev) => {
                const next = new Set(prev);
                if (open) next.delete(groupId);
                else next.add(groupId);
                return next;
              });
            }}
            searchQuery=""
            canDecide={canManage || canManageLifecycle}
            canManage={canManage}
            canViewFinance={canEditAmounts}
          />
        }
      />
      <EndedLineDecisionDialog
        group={decision?.group ?? null}
        line={decision?.line ?? null}
        onClose={() => setDecision(null)}
        canManage={canManage}
        canManageLifecycle={canManageLifecycle}
        onKeepHistory={onKeepHistory ?? note("Zostaw jako historię")}
        onReplaceLine={note("Zastąp kimś innym")}
        onDeleteLine={note("Usunięcie z zamówienia")}
        onResolveOffboarding={note("Decyzja o puli MD")}
      />
    </ToastProvider>
  );
}

export interface ContractorOrdersHarnessProps {
  clientId: number;
  contractors: ContractWithOrdersRead[];
  canViewFinance?: boolean;
  canManageFinance?: boolean;
  /** Typ sekcji dla kontraktora bez zamówień (jak w zakładce: podpowiedź serwera). */
  suggestedOrderType?: OrderType;
  initialContractId?: number | null;
}

/**
 * Kontraktorzy z zamówieniami okresowymi (i innymi pojedynczymi zamówieniami)
 * jako wiersze tabeli z `ContractorOrderPanel` — to samo, co zakładka pokazuje
 * obok zamówień MD/kosztowych. Panel nie ma zapytań przy wejściu (tylko
 * mutacje po kliknięciu), więc nie wymaga zasiewu.
 */
export function ContractorOrdersHarness({
  clientId,
  contractors,
  canViewFinance = true,
  canManageFinance = true,
  suggestedOrderType = "periodic",
  initialContractId = null,
}: ContractorOrdersHarnessProps) {
  const harnessId = useId();
  const shared = useContext(ActivePanelContext);
  const [ownContractId, setContractId] = useState<number | null>(initialContractId);
  const contractId =
    shared && shared.activeId !== null && shared.activeId !== harnessId ? null : ownContractId;
  const select = (next: number | null) => {
    setContractId(next);
    if (next !== null) shared?.setActiveId(harnessId);
  };

  const sections: OrdersTableSection[] = ORDER_TYPE_ORDER.map((type) => {
    const items = contractors
      .filter(
        (contractor) =>
          (contractor.orders.length > 0
            ? contractorOrderType(contractor, "periodic")
            : suggestedOrderType) === type,
      )
      .map((contractor) => ({ kind: "contractor" as const, contractor }));
    return {
      type,
      itemCount: items.length,
      rows: buildSectionRows(items, { expandedEnded: new Set(), collapsedEnded: new Set() }),
    };
  }).filter((section) => section.itemCount > 0);

  const selected = contractors.find((item) => item.contract_id === contractId) ?? null;

  return (
    <ToastProvider>
      <ListDetailLayout
        panelLabel="Szczegóły zamówienia"
        onClose={() => select(null)}
        panel={
          selected ? (
            <ContractorOrderPanel
              key={selected.contract_id}
              clientId={clientId}
              contractor={selected}
              canViewFinance={canViewFinance}
              canManageFinance={canManageFinance}
              canManageOrders={canManageFinance}
              suggestedOrderType={suggestedOrderType}
              legacyNullOrderType="periodic"
              onClose={() => select(null)}
            />
          ) : null
        }
        list={
          <OrdersTable
            sections={sections}
            selectedKey={contractId !== null ? `c:${contractId}` : null}
            onSelect={(key) => {
              const next = selectionFromKey(key, sections);
              if (next?.kind === "contractor") select(next.contractId);
            }}
            onToggleEnded={() => undefined}
            searchQuery=""
            canDecide={false}
            canManage={canManageFinance}
            canViewFinance={canViewFinance}
          />
        }
      />
    </ToastProvider>
  );
}
