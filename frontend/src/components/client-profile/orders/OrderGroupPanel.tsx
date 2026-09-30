"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Ban,
  CalendarPlus,
  Download,
  Ellipsis,
  ExternalLink,
  Pencil,
  Plus,
  RotateCcw,
  SquareCheckBig,
  Trash2,
} from "lucide-react";

import { DetailFacts, DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/Toast";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import { downloadAuthenticatedFile, openAuthenticatedFile } from "@/lib/authenticated-files";
import { effectiveGroupOrderType, usesSharedMdPool } from "@/lib/client-order-list";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { formatDate } from "@/types/client-profile";

import { OrderHistoryPanel } from "./OrderHistoryPanel";
import { OrderTypeBadge } from "./OrderTypeBadge";
import {
  BudgetBar,
  FutureOrders,
  PositionsMdBar,
  SharedMdBudgetBar,
  STATUS_BADGE,
  executiveContractLabel,
  periodLabel,
} from "./order-group-parts";
import { displayLineRate } from "./order-line-display";
import { groupRoster } from "./orders-table-model";

/** Callbacki zamówienia — te same, które wołała dawna karta zamówienia.
 *  Każdy otwiera okno hostowane przez `MultiConsultantOrdersTab`. */
export interface OrderGroupActions {
  onAddConsultant: (group: OrderGroupRead) => void;
  onEditGroup: (group: OrderGroupRead) => void;
  onEditLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onExtendGroup: (group: OrderGroupRead) => void;
  onCloseGroup: (group: OrderGroupRead) => void;
  onReopenGroup: (group: OrderGroupRead) => void;
  onCancelGroup: (group: OrderGroupRead) => void;
  onRestoreGroup: (group: OrderGroupRead) => void;
  onDeleteGroup: (group: OrderGroupRead) => void;
}

interface Props extends OrderGroupActions {
  clientId: number;
  group: OrderGroupRead;
  /** Zamówienie, którego `group` jest przedłużeniem (wiersz „Przyszłe zamówienie"). */
  parent: OrderGroupRead | null;
  canManage: boolean;
  canManageLifecycle: boolean;
  searchQuery: string;
  onClose: () => void;
  onSelectLine: (groupId: number, lineId: number) => void;
  onSelectGroup: (groupId: number) => void;
}

type Tab = "szczegoly" | "historia";

/** Panel zamówienia MD/kosztowego (wersja B, 29.09.2026). */
export function OrderGroupPanel({
  clientId,
  group,
  parent,
  canManage,
  canManageLifecycle,
  searchQuery,
  onClose,
  onSelectLine,
  onSelectGroup,
  ...actions
}: Props) {
  const [tab, setTab] = useState<Tab>("szczegoly");
  const { showToast } = useToast();
  const [fileBusy, setFileBusy] = useState(false);
  const isCancelled = group.status === "cancelled";
  const isActive = group.status === "active";
  const roster = groupRoster(group);
  const fileEndpoint = `/api/clients/${clientId}/order-groups/${group.id}/file`;
  const sharedMd = usesSharedMdPool(group);

  async function withFile(action: () => Promise<void>, message: string) {
    setFileBusy(true);
    try {
      await action();
    } catch {
      showToast(message, "error");
    } finally {
      setFileBusy(false);
    }
  }

  // Zakończ / Przywróć / Anuluj / Usuń — rola cyklu życia (lustro backendowego
  // `_ORDER_LIFECYCLE_ROLES`), szersza niż `canManage`.
  const hasMenu = canManageLifecycle;

  const footer =
    canManage || canManageLifecycle ? (
      <>
        {canManage ? (
          <Button
            type="button"
            size="sm"
            onClick={() => actions.onAddConsultant(group)}
            disabled={!group.can_add_consultant}
            title={
              group.can_add_consultant
                ? undefined
                : `Zamówienie jest ${group.status_label.toLowerCase()} — nie można dodać konsultanta`
            }
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj konsultanta
          </Button>
        ) : null}
        {canManage && !isCancelled ? (
          <Button type="button" size="sm" variant="outline" onClick={() => actions.onEditGroup(group)}>
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Uzupełnij zamówienie
          </Button>
        ) : null}
        {canManageLifecycle && !isCancelled ? (
          <Button type="button" size="sm" variant="outline" onClick={() => actions.onExtendGroup(group)}>
            <CalendarPlus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj przedłużenie
          </Button>
        ) : null}
        {hasMenu ? (
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button type="button" size="icon-sm" variant="outline" aria-label="Więcej akcji zamówienia" title="Więcej akcji">
                <Ellipsis className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              {isActive ? (
                <DropdownMenuItem onSelect={() => defer(() => actions.onCloseGroup(group))}>
                  <SquareCheckBig className="h-4 w-4" /> Zakończ
                </DropdownMenuItem>
              ) : null}
              {group.status === "completed" ? (
                <DropdownMenuItem onSelect={() => defer(() => actions.onReopenGroup(group))}>
                  <RotateCcw className="h-4 w-4" /> Przywróć
                </DropdownMenuItem>
              ) : null}
              {!isCancelled ? (
                <DropdownMenuItem onSelect={() => defer(() => actions.onCancelGroup(group))}>
                  <Ban className="h-4 w-4" /> Anuluj zamówienie
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onSelect={() => defer(() => actions.onRestoreGroup(group))}>
                  <RotateCcw className="h-4 w-4" /> Przywróć anulowane
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => defer(() => actions.onDeleteGroup(group))}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="h-4 w-4" /> Usuń całe zamówienie
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </>
    ) : null;

  return (
    <DetailPanel
      compact
      data-testid="order-group-panel"
      title={<span className="select-text">Zamówienie nr {group.order_number}</span>}
      badges={
        <>
          <OrderTypeBadge type={effectiveGroupOrderType(group)} />
          {group.status !== "active" ? (
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                STATUS_BADGE[group.status] ?? "bg-muted text-muted-foreground",
              )}
            >
              {group.status_label}
            </span>
          ) : null}
        </>
      }
      subtitle={
        parent ? (
          <>
            Przedłużenie zamówienia{" "}
            <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={() => onSelectGroup(parent.id)}>
              {parent.order_number}
            </button>
          </>
        ) : (
          periodLabel(group)
        )
      }
      onClose={onClose}
      closeLabel="Zamknij panel zamówienia"
      tabs={[
        { value: "szczegoly", label: "Szczegóły" },
        { value: "historia", label: `Historia (${group.event_count})` },
      ]}
      tab={tab}
      onTabChange={(value) => setTab(value as Tab)}
      footer={footer}
    >
      {tab === "historia" ? (
        <OrderHistoryPanel clientId={clientId} groupId={group.id} compact onFocusGroup={onSelectGroup} />
      ) : (
        <>
          {group.status === "exhausted" && group.is_cost_based ? (
            <p role="status" className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              Budżet wyczerpany — zamówienie nie przyjmuje nowych konsultantów. Zorganizuj nowe zamówienie albo skoryguj kwotę.
            </p>
          ) : null}
          {sharedMd &&
          (group.status === "exhausted" || (group.md_budget_total != null && (group.md_budget_remaining ?? 0) <= 0)) ? (
            <p role="status" className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              Budżet MD wyczerpany — pozostało 0 MD i zamówienie nie przyjmuje nowych konsultantów. Zorganizuj nowe zamówienie albo skoryguj pulę.
            </p>
          ) : null}

          <DetailSection title="Zamówienie">
            <DetailFacts
              compact
              items={[
                ["Okres", periodLabel(group)],
                group.closure_date ? ["Zakończone", formatDate(group.closure_date)] : null,
                group.status === "cancelled" && group.cancelled_at
                  ? [
                      "Anulowane",
                      `${formatDate(warsawDateOf(group.cancelled_at) ?? group.cancelled_at)}${group.cancellation_reason ? ` — ${group.cancellation_reason}` : ""}`,
                    ]
                  : null,
                group.executive_contract ? ["Umowa", executiveContractLabel(group.executive_contract)] : null,
                ["Obsada", `${countPl(roster.current.length, "osoba", "osoby", "osób")}${roster.ended.length ? ` · ${roster.ended.length} zakończone` : ""}`],
                group.notes ? ["Notatki", <span key="notes" className="whitespace-pre-line">{group.notes}</span>] : null,
                group.has_file
                  ? [
                      "PDF",
                      <span key="pdf" className="flex flex-wrap items-center gap-x-2">
                        <span className="min-w-0 truncate">{group.filename ?? `${group.order_number}.pdf`}</span>
                        <button
                          type="button"
                          disabled={fileBusy}
                          onClick={() =>
                            withFile(
                              () => openAuthenticatedFile(fileEndpoint, "application/pdf", `${group.order_number}.pdf`),
                              "Nie udało się otworzyć pliku PDF.",
                            )
                          }
                          className="inline-flex items-center gap-1 text-primary hover:underline disabled:opacity-50"
                        >
                          <ExternalLink className="h-3.5 w-3.5" aria-hidden /> Otwórz
                        </button>
                        <button
                          type="button"
                          disabled={fileBusy}
                          onClick={() =>
                            withFile(
                              () => downloadAuthenticatedFile(fileEndpoint, `${group.order_number}.pdf`),
                              "Nie udało się pobrać pliku PDF.",
                            )
                          }
                          className="inline-flex items-center gap-1 text-primary hover:underline disabled:opacity-50"
                        >
                          <Download className="h-3.5 w-3.5" aria-hidden /> Pobierz
                        </button>
                      </span>,
                    ]
                  : null,
              ]}
            />
          </DetailSection>

          {group.is_cost_based ? (
            <DetailSection title="Budżet">
              <BudgetBar group={group} />
            </DetailSection>
          ) : null}
          {group.executive_contract && group.md_positions_total != null && !group.is_cost_based ? (
            <DetailSection title="Pozycje MD">
              <PositionsMdBar group={group} />
            </DetailSection>
          ) : null}
          {sharedMd ? (
            <DetailSection title="Wspólna pula MD">
              <SharedMdBudgetBar group={group} />
            </DetailSection>
          ) : null}

          {/* Zawsze — puste zamówienie mówi to wprost, jak dawna karta. */}
          <DetailSection title={`Konsultanci (${group.lines.length})`}>
            {group.lines.length === 0 ? (
              <p className="text-xs text-muted-foreground">To zamówienie nie ma jeszcze konsultantów.</p>
            ) : (
              <ul className="divide-y divide-border rounded-md border border-border text-xs">
                {[...roster.current, ...roster.ended].map((line) => (
                  <li key={line.id}>
                    <button
                      type="button"
                      onClick={() => onSelectLine(group.id, line.id)}
                      className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-accent"
                    >
                      <span className={cn("min-w-0 flex-1 truncate font-medium", !line.is_active && "text-muted-foreground")}>
                        {line.consultant_name}
                      </span>
                      <span className="whitespace-nowrap tabular-nums text-muted-foreground">{displayLineRate(line, "revenue")}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </DetailSection>

          <FutureOrders
            orders={group.future_orders}
            searchQuery={searchQuery}
            canManage={canManage}
            canManageLifecycle={canManageLifecycle}
            onEditGroup={actions.onEditGroup}
            onAddConsultant={actions.onAddConsultant}
            onEditLine={actions.onEditLine}
            onDeleteGroup={actions.onDeleteGroup}
            compact
          />
        </>
      )}
    </DetailPanel>
  );
}

/** Akcja z menu po jego zamknięciu — inaczej okno i menu walczą o fokus. */
function defer(action: () => void) {
  window.setTimeout(action, 0);
}
