"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  CalendarX,
  Download,
  ExternalLink,
  FilePlus2,
  History,
  MoreHorizontal,
  Plus,
  Trash2,
  TrendingUp,
  UserPlus,
  UserX,
} from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DetailFacts, DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { AppModal } from "@/components/ds/AppModal";
import { ContractPersonLink } from "@/components/contracts/ContractPersonLink";
import { ContractTerminationDialog } from "@/components/contracts/ContractTerminationDialog";
import { EditOrderDialog } from "@/components/EditOrderDialog";
import { ExtendOrderDialog } from "@/components/ExtendOrderDialog";
import { DeleteOrderDialog } from "@/components/orders/DeleteOrderDialog";
import { InlinePeriod, InlineText, fmtDate } from "@/components/orders/InlineOrderFields";
import { CloseClientOrderModal } from "@/components/client-profile/orders/CloseClientOrderModal";
import { OrderTypeBadge } from "@/components/client-profile/orders/OrderTypeBadge";
import { apiErrorMessage } from "@/lib/api-error";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  ClientOrderRead,
  ClientOrderStatus,
  ClientOrderUpdate,
  ContractWithOrdersRead,
  CreateDraftOrder,
  OrderType,
} from "@/lib/api/dlPortal";
import { useExecutiveContractOptions } from "@/lib/api/executiveContracts";
import { downloadAuthenticatedFile, openAuthenticatedFile } from "@/lib/authenticated-files";
import { invalidateClientOrderQueries } from "@/lib/client-order-cache";
import {
  contractorOrderType,
  effectiveClientOrderType,
  isCurrentOrder,
  orderNotStarted,
  type LegacyClientOrderType,
} from "@/lib/client-order-list";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { HOURS_PER_MONTH } from "@/lib/work-time";
import { normalizeOrderCurrency } from "@/components/orders/OrderRateUnitToggle";
import { canManageContractStatus, useAuthStore } from "@/store/auth";

import {
  canTerminateContractor,
  contractorEnding,
  contractorMissingOrder,
  contractorRates,
  contractorRowSummary,
  fmtMoney,
  rateUnitSuffix,
  splitOrders,
  type ContractorRowTone,
} from "./contractor-order-row";

/** Deep link z panelu „Moi klienci" (`?order=`). `nonce` rozróżnia kolejne
 *  kliknięcia w ten sam link. */
export interface ContractorOrderFocus {
  contractId: number;
  orderId: number;
  openEditor: boolean;
  nonce: number;
}

export interface ContractorOrderPanelProps {
  contractor: ContractWithOrdersRead;
  clientId: number;
  /** Serwerowa bramka zapisu zamówień okresowych (admin albo DL klienta). */
  canManageOrders: boolean;
  /** Zapis kwot w oknach zamówień (ta sama flaga serwera co dotąd). */
  canManageFinance: boolean;
  /** Widoczność kwot; bez niej pola stawek się nie renderują. */
  canViewFinance: boolean;
  suggestedOrderType: OrderType;
  legacyNullOrderType: LegacyClientOrderType;
  allowedOrderTypes?: readonly OrderType[];
  /** Aktywne wyszukiwanie — wymusza rozwinięcie historii. */
  searching?: boolean;
  /** Cel z `?order=` dla TEGO kontraktora: rozwija historię, a przy
   *  `openEditor` otwiera „Uzupełnij zamówienie". */
  focusOrder?: ContractorOrderFocus | null;
  /** Panel obsłużył cel — rodzic czyści żądanie. */
  onFocusOrderServed?: () => void;
  /** „Przypisz do zamówienia" na karcie szkicu (Centrum e-Zdrowia).
   *  `openCompleteOrder` otwiera „Uzupełnij zamówienie" tego panelu. */
  onAssignToOrder?: (
    contractor: ContractWithOrdersRead,
    openCompleteOrder: () => void,
  ) => void;
  onClose: () => void;
}

const STATUS_LABELS: Record<ClientOrderStatus, string> = {
  draft: "Draft",
  active: "Aktywne",
  paused: "Wstrzymane",
  completed: "Zakończone",
  cancelled: "Anulowane",
};

const STATUS_BADGE: Record<
  ClientOrderStatus,
  "warning" | "success" | "neutral" | "danger"
> = {
  draft: "warning",
  active: "success",
  paused: "warning",
  completed: "neutral",
  cancelled: "danger",
};

const TONE_BADGE: Record<ContractorRowTone, "success" | "warning" | "danger" | "neutral"> = {
  ok: "success",
  warn: "warning",
  bad: "danger",
  mut: "neutral",
};

/** Menu akcji otwiera okno na następnym tiku, gdy Radix skończy zamykać menu
 *  (issue 533 — dialog otwarty z menu potrafił się zamknąć). */
function MenuAction({
  icon,
  children,
  onSelect,
  destructive,
}: {
  icon: ReactNode;
  children: ReactNode;
  onSelect: () => void;
  destructive?: boolean;
}) {
  return (
    <DropdownMenuItem
      className={cn("min-h-9", destructive && "text-destructive focus:text-destructive")}
      onSelect={() => setTimeout(onSelect, 0)}
    >
      {icon}
      {children}
    </DropdownMenuItem>
  );
}

/**
 * Panel szczegółów kontraktora z zamówieniami okresowymi. Cała logika dawnego
 * kafelka (`ContractorCard`) — edycja w miejscu, zakładanie szkicu przy
 * pierwszym zapisie, przyszłe i historyczne zamówienia, wszystkie okna — tylko
 * w bocznym panelu listy.
 */
export function ContractorOrderPanel({
  contractor,
  clientId,
  canManageOrders,
  canManageFinance,
  canViewFinance,
  suggestedOrderType,
  legacyNullOrderType,
  allowedOrderTypes,
  searching = false,
  focusOrder = null,
  onFocusOrderServed,
  onAssignToOrder,
  onClose,
}: ContractorOrderPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((state) => state.user);
  // Ta sama bramka co na stronie kontraktu: w trybie „podgląd jako" i bez
  // roli zarządzającej statusem kontraktu nie kończymy współpracy.
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const canTerminateByRole = !impersonating && canManageContractStatus(user);

  const onChange = useCallback(
    () => invalidateClientOrderQueries(queryClient, clientId),
    [queryClient, clientId],
  );
  const onError = useCallback((msg: string) => showToast(msg, "error"), [showToast]);
  const onSuccess = useCallback((msg: string) => showToast(msg, "success"), [showToast]);

  const [showHistory, setShowHistory] = useState(false);
  const historyOpen = searching ? true : showHistory;
  const servedFocusRef = useRef<number | null>(null);

  // ── Okna ──────────────────────────────────────────────────────────────────
  const [extendingContract, setExtendingContract] =
    useState<ContractWithOrdersRead | null>(null);
  const [terminating, setTerminating] = useState(false);
  const [closingOrder, setClosingOrder] = useState<ClientOrderRead | null>(null);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [deletingActiveOrder, setDeletingActiveOrder] =
    useState<ClientOrderRead | null>(null);
  const [confirmingDismiss, setConfirmingDismiss] = useState(false);
  // Migawka z chwili otwarcia — dialog trzyma JEDNĄ instancję `onCreate`
  // przez całe życie, a guard szkicu i tak czyta ref (`knownOrderIdRef`).
  const [editingOrder, setEditingOrder] = useState<{
    order: ClientOrderRead | null;
    contractor: ContractWithOrdersRead;
    createOrder: CreateDraftOrder;
  } | null>(null);

  const closeOrder = useMutation({
    mutationFn: async (values: {
      orderId: number;
      closure_date: string;
      closure_reason: string | null;
    }) =>
      (
        await dlPortalApi.closeOrder(clientId, values.orderId, {
          closure_date: values.closure_date,
          closure_reason: values.closure_reason,
        })
      ).data,
    onSuccess: () => {
      setClosingOrder(null);
      setCloseError(null);
      showToast("Zamówienie zakończone", "success");
      onChange();
    },
    onError: (err: unknown) => {
      setCloseError(apiErrorMessage(err, "Nie udało się zakończyć zamówienia."));
    },
  });

  // „Usuń szkic" (ticket 09.2026, C1): pusta karta znika, kontrakt i dane
  // rekrutacji zostają. Serwer usuwa wyłącznie szkice zamówień tej osoby.
  const dismissDraft = useMutation({
    mutationFn: () => dlPortalApi.dismissDraftCard(clientId, contractor.contract_id),
    onSuccess: () => {
      setConfirmingDismiss(false);
      onSuccess("Usunięto szkic — kontrakt i rekrutacja zostały zachowane");
      onChange();
    },
    onError: (err: unknown) => {
      setConfirmingDismiss(false);
      onError(apiErrorMessage(err, "Nie udało się usunąć szkicu."));
    },
  });
  const deleteActiveOrder = useMutation({
    mutationFn: (orderId: number) => dlPortalApi.deleteOrder(clientId, orderId),
    onSuccess: () => {
      onSuccess("Zamówienie usunięte");
      onChange();
    },
    onError: (err: unknown) => {
      onError(apiErrorMessage(err, "Nie udało się usunąć zamówienia."));
    },
  });

  // „Umowa wykonawcza" — tylko Centrum e-Zdrowia. Część umowy jest od
  // struktury umów wartością POCHODNĄ z umowy ramowej.
  const ezdrowie = isEzdrowieClient(clientId);
  const executiveContracts = useExecutiveContractOptions(clientId);
  const [partSaving, setPartSaving] = useState(false);
  // Umowa wybrana ZANIM powstało zamówienie — `POST /orders` wymaga jej dla
  // e-Zdrowia, więc kontraktor bez zamówienia musi mieć jak ją podać.
  const [pendingExecutiveContractId, setPendingExecutiveContractId] = useState<
    number | null
  >(null);
  // Id szkicu założonego w TEJ sesji panelu. Odświeżenie listy jest
  // asynchroniczne, więc bez tej pamięci kolejny zapis w tym okienku zakładałby
  // DRUGI szkic tego samego zamówienia.
  const [draftOrderId, setDraftOrderId] = useState<number | null>(null);
  // Ten sam fakt czytany REFEM: dialog trzyma zamrożone `onCreate` z chwili
  // otwarcia, a domknięcie widziałoby stare `draftOrderId === null`.
  const knownOrderIdRef = useRef<number | null>(null);

  const split = useMemo(() => splitOrders(contractor.orders), [contractor.orders]);
  const { activeOrder, futureOrders, historyOrders } = split;
  knownOrderIdRef.current = activeOrder?.id ?? draftOrderId;
  const rates = contractorRates(contractor, activeOrder);
  const {
    contractRateClientCurrency,
    contractRateCandidateCurrency,
    costFromContract,
  } = rates;

  /**
   * Zapis pola, gdy kontraktor NIE MA jeszcze żadnego zamówienia: pierwszy
   * zapis zakłada szkic zamówienia i od razu stosuje wpisaną wartość (zgłoszenie
   * „u Banku Pocztowego nie da się nic wpisać" — różnica DANYCH, nie
   * konfiguracji klienta). Klient z zamówieniami nie wchodzi w tę ścieżkę.
   */
  const createDraftOrder = useCallback<CreateDraftOrder>(
    async (patch, opts) => {
      // Szkic mógł już powstać: z edycji w miejscu albo z POPRZEDNIEGO,
      // nieudanego zapisu tego samego dialogu. Bez tego sprawdzenia drugie
      // „Zapisz" zakładało DRUGIE zamówienie na tym samym kontrakcie.
      const existingId = knownOrderIdRef.current;
      if (existingId !== null && existingId !== undefined) {
        const merged: Partial<ClientOrderUpdate> = { ...patch };
        if (opts?.title?.trim()) merged.title = opts.title.trim();
        if (
          ezdrowie &&
          merged.executive_contract_id == null &&
          opts?.executiveContractId
        ) {
          merged.executive_contract_id = opts.executiveContractId;
        }
        await dlPortalApi.updateOrder(clientId, existingId, merged);
        if (opts?.file) {
          await dlPortalApi.replaceOrderPo(clientId, existingId, opts.file);
        }
        return existingId;
      }
      // Centrum e-Zdrowia: bez umowy wykonawczej `POST /orders` zwraca 422 —
      // odmawiamy tutaj, po polsku, wskazując pole do uzupełnienia.
      const executiveContractId =
        opts?.executiveContractId ?? pendingExecutiveContractId;
      if (ezdrowie && !executiveContractId) {
        throw new Error(
          "Najpierw wybierz umowę wykonawczą — bez niej nie da się założyć zamówienia u Centrum e-Zdrowia.",
        );
      }
      const form = new FormData();
      form.append("contract_id", String(contractor.contract_id));
      if (ezdrowie && executiveContractId) {
        form.append("executive_contract_id", String(executiveContractId));
      }
      // „(bez numeru)" jest uczciwe i widoczne — pusty tytuł odrzuca walidacja,
      // a zmyślony numer wyglądałby jak dane z dokumentu klienta.
      form.append("title", opts?.title?.trim() || "(bez numeru)");
      // `draft`: zamówienie z jednego pola nie jest kompletne. Komplet pól
      // promuje je po stronie serwera (`_activate_complete_draft`).
      form.append("order_status", "draft");
      form.append("order_type", patch.order_type ?? suggestedOrderType);
      if (contractor.initial_job_id != null) {
        form.append("job_id", String(contractor.initial_job_id));
      }
      if (patch.start_date) form.append("start_date", patch.start_date);
      if (patch.end_date) form.append("end_date", patch.end_date);
      if (patch.rate_client != null) {
        form.append("rate_client", String(patch.rate_client));
      }
      if (patch.rate_candidate != null) {
        form.append("rate_candidate", String(patch.rate_candidate));
      }
      form.append("rate_unit", patch.rate_unit ?? contractor.rate_unit);
      form.append(
        "billing_hours_per_month",
        String(
          patch.billing_hours_per_month ??
            contractor.billing_hours_per_month ??
            HOURS_PER_MONTH,
        ),
      );
      form.append(
        "rate_client_currency",
        normalizeOrderCurrency(
          patch.rate_client_currency,
          patch.currency,
          contractRateClientCurrency,
        ),
      );
      form.append(
        "rate_candidate_currency",
        normalizeOrderCurrency(
          patch.rate_candidate_currency,
          contractRateCandidateCurrency,
        ),
      );
      if (patch.total_value != null) {
        form.append("total_value", String(patch.total_value));
      }
      if (patch.md_quantity != null) {
        form.append("md_quantity", String(patch.md_quantity));
      }
      if (patch.description) form.append("description", patch.description);
      // Plik w tym samym żądaniu — JEDEN request, nie create + upload.
      if (opts?.file) form.append("file", opts.file);
      const created = await dlPortalApi.createOrderExtension(clientId, form);
      // Ref PRZED stanem: ponowny „Zapisz" leci, zanim React przerenderuje.
      knownOrderIdRef.current = created.data.id;
      setDraftOrderId(created.data.id);
      return created.data.id;
    },
    [
      clientId,
      contractor.contract_id,
      contractor.billing_hours_per_month,
      contractor.initial_job_id,
      contractor.rate_unit,
      contractRateClientCurrency,
      contractRateCandidateCurrency,
      ezdrowie,
      pendingExecutiveContractId,
      suggestedOrderType,
    ],
  );

  /** Otwiera „Uzupełnij zamówienie"; `null` = kontraktor bez zamówienia. */
  const openOrderDialog = useCallback(
    (order: ClientOrderRead | null) =>
      setEditingOrder({ order, contractor, createOrder: createDraftOrder }),
    [contractor, createDraftOrder],
  );

  // Jedno wejście dla obu ścieżek zapisu — guard szkicu siedzi w
  // `createDraftOrder`, więc nie da się go ominąć.
  async function saveOntoOrder(
    patch: Partial<ClientOrderUpdate>,
    opts?: { title?: string; executiveContractId?: number },
  ) {
    await createDraftOrder(patch, opts);
  }

  // Deep link `?order=`: historia rozwinięta, a szkic — od razu w oknie
  // uzupełniania. Obsłużone żądanie jest zapamiętane.
  useEffect(() => {
    if (!focusOrder || servedFocusRef.current === focusOrder.nonce) return;
    if (focusOrder.contractId !== contractor.contract_id) return;
    const order = contractor.orders.find((item) => item.id === focusOrder.orderId);
    if (!order) return;
    servedFocusRef.current = focusOrder.nonce;
    if (historyOrders.some((item) => item.id === order.id)) setShowHistory(true);
    if (focusOrder.openEditor && canManageOrders) openOrderDialog(order);
    onFocusOrderServed?.();
  }, [
    focusOrder,
    contractor.contract_id,
    contractor.orders,
    historyOrders,
    canManageOrders,
    openOrderDialog,
    onFocusOrderServed,
  ]);

  const ending = contractorEnding(contractor, split);
  const missing = contractorMissingOrder(contractor);
  const summary = contractorRowSummary(contractor, undefined, { canViewFinance });

  // Zamknięte i anulowane nie mają czego kończyć.
  const canCloseActiveOrder =
    activeOrder !== null &&
    activeOrder.status !== "completed" &&
    activeOrder.status !== "cancelled";
  const cardOrderType = activeOrder
    ? effectiveClientOrderType(activeOrder, legacyNullOrderType)
    : contractor.orders.length > 0
      ? contractorOrderType(contractor, legacyNullOrderType)
      : suggestedOrderType;
  const hasSection = futureOrders.length > 0 || historyOrders.length > 0;
  const isDraftCard = contractor.draft_card === true;
  const extendIsPrimary = ending !== null || (missing !== null && !isDraftCard);
  const canDeleteActiveOrder = canManageOrders && activeOrder !== null && !isDraftCard;
  const showTerminate =
    canTerminateByRole && canTerminateContractor(contractor.contract_status);

  const currentSectionTitle = !activeOrder
    ? "Nowe zamówienie"
    : isCurrentOrder(activeOrder) || orderNotStarted(activeOrder)
      ? "Bieżące zamówienie"
      : "Ostatnie zamówienie";

  // ── Nagłówek ──────────────────────────────────────────────────────────────
  const title = (
    <ContractPersonLink contractId={contractor.contract_id} name={contractor.candidate_name} />
  );
  const badges = (
    <>
      <OrderTypeBadge type={cardOrderType} />
      {ending && (
        <Badge variant="warning" size="sm" data-testid="order-ending-badge">
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          {ending.label}
        </Badge>
      )}
      {missing && (
        <Badge
          variant={isDraftCard ? "warning" : "danger"}
          size="sm"
          title={missing.hint}
          data-testid="no-active-order-note"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          {missing.label}
        </Badge>
      )}
      {!ending && !missing && summary.state.kind !== "active" && (
        <Badge variant={TONE_BADGE[summary.state.tone]} size="sm">
          {summary.state.label}
        </Badge>
      )}
    </>
  );
  const subtitle = <span>Kontrakt #{contractor.contract_id}</span>;

  // ── Bieżące zamówienie ────────────────────────────────────────────────────
  const numberField = (
    <span data-order-detail-line="number" title="Numer zamówienia">
      <InlineText
        value={activeOrder?.title ?? ""}
        display={
          activeOrder ? (
            <span className="font-medium text-foreground">{activeOrder.title}</span>
          ) : (
            <em className="text-muted-foreground">wpisz numer</em>
          )
        }
        ariaLabel="Numer zamówienia"
        editable={canManageOrders}
        placeholder="np. 45767"
        onError={onError}
        onSave={async (raw) => {
          if (!raw) throw new Error("Numer zamówienia nie może być pusty");
          await saveOntoOrder({ title: raw }, { title: raw });
          onSuccess("Numer zamówienia zaktualizowany");
          onChange();
        }}
      />
    </span>
  );

  const executiveValue = activeOrder
    ? activeOrder.executive_contract_id
    : pendingExecutiveContractId;
  const executiveField = ezdrowie ? (
    <span className="flex flex-wrap items-center gap-1" data-order-detail-line="executive">
      <select
        value={String(executiveValue ?? "")}
        aria-label="Umowa wykonawcza"
        disabled={!canManageOrders || partSaving}
        onChange={async (e) => {
          const value = e.target.value ? Number(e.target.value) : null;
          // disabled na czas zapisu (bez wyścigu dwóch PATCH-y); po błędzie
          // onChange() synchronizuje select z serwerem.
          setPartSaving(true);
          try {
            if (activeOrder) {
              await dlPortalApi.updateOrder(clientId, activeOrder.id, {
                executive_contract_id: value,
              });
              onSuccess("Umowa wykonawcza zaktualizowana");
            } else if (value) {
              // Bez zamówienia umowa wykonawcza jest POLEM, które je zakłada.
              await saveOntoOrder({}, { executiveContractId: value });
              setPendingExecutiveContractId(value);
              onSuccess("Umowa wykonawcza zapisana");
            } else {
              setPendingExecutiveContractId(null);
            }
          } catch {
            onError("Nie udało się zapisać umowy wykonawczej");
          } finally {
            setPartSaving(false);
            onChange();
          }
        }}
        className={cn(
          "min-w-0 max-w-full rounded border bg-background px-1.5 py-0.5 text-xs disabled:opacity-60 pointer-coarse:py-1.5",
          executiveValue ? "border-border" : "border-warning text-warning-muted-foreground",
        )}
      >
        <option value="">— uzupełnij —</option>
        {executiveContracts.groups.map((group) => (
          <optgroup key={group.framework_contract_id} label={group.label}>
            {group.options.map((ec) => (
              <option key={ec.id} value={String(ec.id)}>
                {ec.number}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {executiveContracts.isSuccess && executiveContracts.groups.length === 0 ? (
        <span className="text-xs text-muted-foreground">
          Dodaj umowę wykonawczą w sekcji Struktura umów na profilu klienta.
        </span>
      ) : null}
    </span>
  ) : null;

  const periodField = (
    <span data-order-detail-line="period">
      <InlinePeriod
        startDate={activeOrder?.start_date ?? null}
        endDate={activeOrder?.end_date ?? null}
        editable={canManageOrders}
        showLabel={false}
        onError={onError}
        onSave={async (start, end) => {
          await saveOntoOrder({ start_date: start, end_date: end });
          onSuccess("Okres zamówienia zaktualizowany");
          onChange();
        }}
      />
    </span>
  );

  const costField = (
    <span data-order-detail-line="cost" title="Stawka kosztowa">
      <InlineText
        value={rates.costAmount != null ? String(rates.costAmount) : ""}
        display={
          rates.costAmount != null ? (
            <strong className="text-foreground">
              {fmtMoney(rates.costAmount)}
              {` ${rates.costCurrency}`}
              {rateUnitSuffix(rates.unit)}
            </strong>
          ) : (
            <em className="text-muted-foreground">ustaw stawkę</em>
          )
        }
        ariaLabel="Stawka kosztowa"
        // Kontrakt jest źródłem prawdy dla stawki kosztowej (09.2026) —
        // edycja zostaje tylko dla kontraktu bez stawki.
        editable={canManageOrders && !costFromContract}
        inputMode="decimal"
        sanitize={sanitizeDecimalInput}
        placeholder="np. 12000"
        onError={onError}
        onSave={async (raw) => {
          // Przez zamówienie, nie PATCH /api/contracts/{id} (tam admin-only
          // bramka pól finansowych dawała DL-owi 403).
          await saveOntoOrder({ rate_candidate: parseDecimalInput(raw) });
          onSuccess("Stawka kosztowa zaktualizowana");
          onChange();
        }}
      />
      {costFromContract && (
        <span
          className="ml-1 text-[10px] text-muted-foreground"
          title="Stawka kosztowa pochodzi z kontraktu tej osoby — zmień ją w kontrakcie. Zaplanowane podwyżki wchodzą do zamówienia w swoim dniu."
        >
          (z kontraktu)
        </span>
      )}
    </span>
  );

  const revenueField = (
    <span data-order-detail-line="revenue" title="Stawka przychodowa">
      <InlineText
        value={rates.revenueAmount != null ? String(rates.revenueAmount) : ""}
        display={
          rates.revenueAmount != null ? (
            <strong className="text-foreground">
              {fmtMoney(rates.revenueAmount)}
              {` ${rates.revenueCurrency}`}
              {rateUnitSuffix(rates.unit)}
            </strong>
          ) : (
            <em className="text-muted-foreground">ustaw stawkę</em>
          )
        }
        ariaLabel="Stawka przychodowa"
        editable={canManageOrders}
        inputMode="decimal"
        sanitize={sanitizeDecimalInput}
        placeholder="np. 18000"
        onError={onError}
        onSave={async (raw) => {
          await saveOntoOrder({ rate_client: parseDecimalInput(raw) });
          onSuccess("Stawka przychodowa zaktualizowana");
          onChange();
        }}
      />
    </span>
  );

  const redactedAmount = (
    <span className="text-muted-foreground" title="Kwoty widzi administrator, Finanse i Delivery Lead tego klienta">
      —
    </span>
  );

  const currentSection = (
    <DetailSection title={currentSectionTitle}>
      <DetailFacts
        items={[
          ["Numer", numberField],
          ezdrowie && ["Umowa wykonawcza", executiveField],
          ["Okres", periodField],
          // Bez dostępu do kwot wiersze zostają z „—" — znikające pola czytały
          // się jak brak danych, a nie jak brak uprawnień (lustro tabeli).
          ["Koszt", canViewFinance ? costField : redactedAmount],
          ["Przychód", canViewFinance ? revenueField : redactedAmount],
          canViewFinance &&
            activeOrder?.monthly_margin != null && [
              "Marża",
              <span key="margin" className="text-success">
                {fmtMoney(activeOrder.monthly_margin)}{" "}
                {currencyLabel(activeOrder.rate_client_currency ?? activeOrder.currency)} / mc
              </span>,
            ],
          contractor.initial_job_title
            ? ["Z rekrutacji", <span key="job">{contractor.initial_job_title}</span>]
            : null,
          activeOrder?.has_file
            ? [
                "PDF",
                <OrderPdfActions
                  key="pdf"
                  clientId={clientId}
                  order={activeOrder}
                  onError={onError}
                />,
              ]
            : null,
        ]}
      />
      {!activeOrder && !hasSection ? (
        <p className="text-xs italic text-muted-foreground">
          Brak zamówień — uzupełnij numer, okres i stawki powyżej, a zamówienie
          powstanie automatycznie jako szkic.
        </p>
      ) : null}
    </DetailSection>
  );

  // ── Przyszłe i historia ───────────────────────────────────────────────────
  const futureSection = hasSection ? (
    <DetailSection
      title={`Przyszłe zamówienie${futureOrders.length > 0 ? ` (${futureOrders.length})` : ""}`}
    >
      {futureOrders.length > 0 ? (
        <div className="grid gap-2">
          {futureOrders.map((order) => (
            <FutureOrderRow
              key={order.id}
              order={order}
              clientId={clientId}
              canManageOrders={canManageOrders}
              legacyNullOrderType={legacyNullOrderType}
              onEditOrder={openOrderDialog}
              onError={onError}
              onSuccess={onSuccess}
              onChange={onChange}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs italic text-muted-foreground">Brak przyszłych zamówień.</p>
      )}
    </DetailSection>
  ) : null;

  const historySection =
    historyOrders.length > 0 ? (
      <section className="grid gap-1.5">
        <button
          type="button"
          onClick={() => {
            // Przy aktywnym wyszukiwaniu historia jest wymuszona.
            if (!searching) setShowHistory((v) => !v);
          }}
          aria-expanded={historyOpen}
          className="flex w-fit items-center gap-1 rounded text-[11px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-primary focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          <History className="h-3 w-3" aria-hidden="true" />
          Historia zamówień ({historyOrders.length})
        </button>
        {historyOpen && (
          <div className="grid gap-2">
            {historyOrders.map((order) => (
              <HistoryOrderRow
                key={order.id}
                order={order}
                clientId={clientId}
                canViewFinance={canViewFinance}
                canManageOrders={canManageOrders}
                legacyNullOrderType={legacyNullOrderType}
                fallbackRateUnit={contractor.rate_unit}
                fallbackRateClientCurrency={contractRateClientCurrency}
                onEditOrder={openOrderDialog}
                onError={onError}
                onSuccess={onSuccess}
                onDeleted={onChange}
              />
            ))}
          </div>
        )}
      </section>
    ) : null;

  // ── Stopka ────────────────────────────────────────────────────────────────
  const completeButton = (primary: boolean) => (
    <Button
      key="complete"
      type="button"
      size="sm"
      variant={primary ? "primary" : "outline"}
      onClick={() => openOrderDialog(activeOrder)}
    >
      <FilePlus2 className="h-3.5 w-3.5" aria-hidden="true" />
      Uzupełnij zamówienie
    </Button>
  );
  const extendButton = (primary: boolean) => (
    <Button
      key="extend"
      type="button"
      size="sm"
      variant={primary ? "primary" : "outline"}
      onClick={() => setExtendingContract(contractor)}
    >
      <Plus className="h-3.5 w-3.5" aria-hidden="true" />
      Dodaj przedłużenie
    </Button>
  );
  const assignButton =
    canManageOrders && isDraftCard && onAssignToOrder ? (
      <Button
        key="assign"
        type="button"
        size="sm"
        variant="primary"
        onClick={() => onAssignToOrder(contractor, () => openOrderDialog(activeOrder))}
      >
        <UserPlus className="h-3.5 w-3.5" aria-hidden="true" />
        Przypisz do zamówienia
      </Button>
    ) : null;

  const footerActions: ReactNode[] = [];
  if (assignButton) footerActions.push(assignButton);
  if (canManageOrders) {
    if (extendIsPrimary) {
      footerActions.push(extendButton(true), completeButton(false));
    } else {
      footerActions.push(completeButton(!assignButton), extendButton(false));
    }
    // DWIE różne akcje: „Zakończ zamówienie" domyka JEDEN wiersz, „Zakończ
    // współpracę" wypowiada UMOWĘ (razem z liniami MD tej osoby).
    if (activeOrder && canCloseActiveOrder) {
      footerActions.push(
        <Button
          key="close"
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            setCloseError(null);
            setClosingOrder(activeOrder);
          }}
        >
          <CalendarX className="h-3.5 w-3.5" aria-hidden="true" />
          Zakończ zamówienie
        </Button>,
      );
    }
    if (isDraftCard) {
      footerActions.push(
        <Button
          key="dismiss"
          type="button"
          size="sm"
          variant="outline"
          disabled={dismissDraft.isPending}
          onClick={() => setConfirmingDismiss(true)}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          Usuń szkic
        </Button>,
      );
    }
    if (canDeleteActiveOrder) {
      footerActions.push(
        // modal={false}: modalne menu zostawia zablokowane pointer-events na
        // body podczas zamykania, a z menu otwieramy okno (issue 533).
        <DropdownMenu key="more" modal={false}>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              aria-label="Więcej akcji zamówienia"
              disabled={deleteActiveOrder.isPending}
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <MenuAction
              icon={<Trash2 className="h-4 w-4" aria-hidden="true" />}
              destructive
              onSelect={() => activeOrder && setDeletingActiveOrder(activeOrder)}
            >
              Usuń zamówienie
            </MenuAction>
          </DropdownMenuContent>
        </DropdownMenu>,
      );
    }
  }
  if (showTerminate) {
    footerActions.push(
      <span key="spacer" className="flex-1" aria-hidden="true" />,
      <Button
        key="terminate"
        type="button"
        size="sm"
        variant="outline"
        className="border-destructive/40 text-destructive hover:bg-destructive/10"
        onClick={() => setTerminating(true)}
      >
        <UserX className="h-3.5 w-3.5" aria-hidden="true" />
        Zakończ współpracę…
      </Button>,
    );
  }
  const footer = footerActions.length > 0 ? <>{footerActions}</> : undefined;

  const body = (
    <>
      {currentSection}
      {futureSection}
      {historySection}
    </>
  );

  const dialogs = (
    <>
      {extendingContract ? (
        <ExtendOrderDialog
          clientId={clientId}
          contract={extendingContract}
          canManageFinance={canManageFinance}
          onClose={() => setExtendingContract(null)}
          onCreated={async () => {
            await onChange();
            setExtendingContract(null);
          }}
        />
      ) : null}

      <CloseClientOrderModal
        open={closingOrder !== null}
        onOpenChange={(open) => {
          if (!open) {
            setClosingOrder(null);
            setCloseError(null);
          }
        }}
        order={closingOrder}
        consultantName={contractor.candidate_name}
        submitting={closeOrder.isPending}
        error={closeError}
        onSubmit={(values) => {
          if (!closingOrder) return;
          closeOrder.mutate({ orderId: closingOrder.id, ...values });
        }}
      />

      {terminating ? (
        <ContractTerminationDialog
          contractIds={[contractor.contract_id]}
          candidateName={contractor.candidate_name}
          onClose={() => setTerminating(false)}
          onSuccess={() => {
            setTerminating(false);
            onChange();
            showToast("Zakończenie współpracy zapisane", "success");
          }}
        />
      ) : null}

      {editingOrder ? (
        <EditOrderDialog
          clientId={clientId}
          candidateId={editingOrder.contractor.candidate_id}
          order={editingOrder.order}
          rateCandidate={editingOrder.contractor.rate_candidate}
          contractRateUnit={editingOrder.contractor.rate_unit}
          contractBillingHoursPerMonth={
            editingOrder.contractor.billing_hours_per_month ?? HOURS_PER_MONTH
          }
          contractRateClientCurrency={normalizeOrderCurrency(
            editingOrder.contractor.rate_client_currency,
            editingOrder.contractor.currency,
          )}
          contractRateCandidateCurrency={normalizeOrderCurrency(
            editingOrder.contractor.rate_candidate_currency,
            editingOrder.contractor.currency,
            editingOrder.contractor.rate_client_currency,
          )}
          onCreate={editingOrder.createOrder}
          siblingOrders={editingOrder.contractor.orders}
          canManageFinance={canManageFinance}
          suggestedOrderType={suggestedOrderType}
          allowedOrderTypes={allowedOrderTypes}
          legacyNullOrderType={legacyNullOrderType}
          onClose={() => setEditingOrder(null)}
          onSaved={async () => {
            await onChange();
            setEditingOrder(null);
          }}
          onChanged={onChange}
        />
      ) : null}

      <AppModal
        open={confirmingDismiss}
        onOpenChange={(open) => {
          if (!dismissDraft.isPending) setConfirmingDismiss(open);
        }}
        title="Usunąć szkic?"
        description={contractor.candidate_name}
        footer={
          <>
            <button
              type="button"
              onClick={() => setConfirmingDismiss(false)}
              disabled={dismissDraft.isPending}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
            >
              Anuluj
            </button>
            <button
              type="button"
              onClick={() => dismissDraft.mutate()}
              disabled={dismissDraft.isPending}
              className="rounded-md bg-destructive px-3 py-2 text-sm font-medium text-destructive-foreground disabled:opacity-50"
            >
              {dismissDraft.isPending ? "Usuwanie…" : "Usuń szkic"}
            </button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">
          Karta zniknie z zakładki Zamówienia razem ze szkicem zamówienia.
          Kontrakt i dane rekrutacji zostają bez zmian — karta wróci, gdy dla tej
          osoby powstanie nowe zamówienie.
        </p>
      </AppModal>
      {deletingActiveOrder ? (
        <DeleteOrderDialog
          clientId={clientId}
          orderId={deletingActiveOrder.id}
          title={deletingActiveOrder.title}
          pending={deleteActiveOrder.isPending}
          onConfirm={() => {
            const target = deletingActiveOrder.id;
            setDeletingActiveOrder(null);
            deleteActiveOrder.mutate(target);
          }}
          onClose={() => setDeletingActiveOrder(null)}
        />
      ) : null}
    </>
  );

  return (
    <>
      <DetailPanel
        title={title}
        badges={badges}
        subtitle={subtitle}
        onClose={onClose}
        footer={footer}
        data-testid="contractor-order-panel"
      >
        {body}
      </DetailPanel>
      {dialogs}
    </>
  );
}

// ── PDF bieżącego zamówienia ─────────────────────────────────────────────────

function OrderPdfActions({
  clientId,
  order,
  onError,
}: {
  clientId: number;
  order: ClientOrderRead;
  onError: (msg: string) => void;
}) {
  // Endpoint pliku wymaga nagłówka Bearer — surowy <a href> go nie wysyła.
  const path = `/api/clients/${clientId}/orders/${order.id}/file`;
  const filename = order.filename ?? `zamowienie-${order.id}.pdf`;
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="min-w-0 truncate text-muted-foreground" title={filename}>
        {filename}
      </span>
      <button
        type="button"
        className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        onClick={async () => {
          try {
            await openAuthenticatedFile(path, order.content_type ?? "application/pdf", filename);
          } catch {
            onError("Nie udało się otworzyć pliku zamówienia.");
          }
        }}
      >
        <ExternalLink className="h-3 w-3" aria-hidden="true" />
        Otwórz
      </button>
      <button
        type="button"
        className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        onClick={async () => {
          try {
            await downloadAuthenticatedFile(path, filename);
          } catch {
            onError("Nie udało się pobrać pliku zamówienia.");
          }
        }}
      >
        <Download className="h-3 w-3" aria-hidden="true" />
        Pobierz
      </button>
    </span>
  );
}

/** Marża jest w walucie stawki przychodowej zamówienia. */
function currencyLabel(currency: string | null | undefined): string {
  return !currency || currency === "PLN" ? "zł" : currency;
}

/** „Uzupełnij zamówienie" przy wierszu przyszłym i historycznym. */
function CompleteOrderLink({ onClick, orderNumber }: { onClick: () => void; orderNumber: string | null }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={orderNumber ? `Uzupełnij zamówienie ${orderNumber}` : undefined}
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
    >
      <FilePlus2 className="h-3.5 w-3.5" aria-hidden="true" />
      Uzupełnij zamówienie
    </button>
  );
}

// ── Przyszłe zamówienie (przedłużenie w kolejce) ─────────────────────────────

interface FutureOrderRowProps {
  order: ClientOrderRead;
  clientId: number;
  canManageOrders: boolean;
  legacyNullOrderType: LegacyClientOrderType;
  onEditOrder: (order: ClientOrderRead) => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
  onChange: () => void;
}

function FutureOrderRow({
  order,
  clientId,
  canManageOrders,
  legacyNullOrderType,
  onEditOrder,
  onError,
  onSuccess,
  onChange,
}: FutureOrderRowProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteMutation = useMutation({
    mutationFn: () => dlPortalApi.deleteOrder(clientId, order.id),
    onSuccess: () => {
      onSuccess("Zamówienie usunięte");
      onChange();
    },
    onError: (err: unknown) => {
      onError(apiErrorMessage(err, "Nie udało się usunąć zamówienia."));
    },
  });

  return (
    <div className="flex items-start justify-between gap-3 rounded border border-border bg-background p-2 text-sm">
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Numer zamówienia:</span>
          <InlineText
            value={order.title}
            display={<span className="font-medium">{order.title}</span>}
            ariaLabel="Numer zamówienia (przyszłe)"
            editable={canManageOrders}
            onError={onError}
            onSave={async (raw) => {
              if (!raw) throw new Error("Numer zamówienia nie może być pusty");
              await dlPortalApi.updateOrder(clientId, order.id, { title: raw });
              onSuccess("Numer zamówienia zaktualizowany");
              onChange();
            }}
          />
          <OrderTypeBadge type={effectiveClientOrderType(order, legacyNullOrderType)} />
        </div>
        {(order.start_date || order.end_date) && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Calendar className="h-3 w-3" aria-hidden="true" />
            {fmtDate(order.start_date)} → {fmtDate(order.end_date) || "bezterminowo"}
          </div>
        )}
        {canManageOrders ? <CompleteOrderLink onClick={() => onEditOrder(order)} orderNumber={order.title || null} /> : null}
      </div>
      {canManageOrders ? (
        <button
          type="button"
          onClick={() => setConfirmingDelete(true)}
          className="hit-area p-1 text-muted-foreground hover:text-destructive"
          title="Usuń zamówienie"
          aria-label="Usuń zamówienie"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      ) : null}
      {confirmingDelete ? (
        <DeleteOrderDialog
          clientId={clientId}
          orderId={order.id}
          title={order.title}
          pending={deleteMutation.isPending}
          onConfirm={() => {
            setConfirmingDelete(false);
            deleteMutation.mutate();
          }}
          onClose={() => setConfirmingDelete(false)}
        />
      ) : null}
    </div>
  );
}

// ── Historia (przeszłe / zastąpione / anulowane) ─────────────────────────────

interface HistoryOrderRowProps {
  order: ClientOrderRead;
  clientId: number;
  canViewFinance: boolean;
  canManageOrders: boolean;
  legacyNullOrderType: LegacyClientOrderType;
  /** Fallback dla zamówień utworzonych przed snapshotem stawek. */
  fallbackRateUnit: string;
  fallbackRateClientCurrency: string;
  onEditOrder: (order: ClientOrderRead) => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
  onDeleted: () => void;
}

function HistoryOrderRow({
  order,
  clientId,
  canViewFinance,
  canManageOrders,
  legacyNullOrderType,
  fallbackRateUnit,
  fallbackRateClientCurrency,
  onEditOrder,
  onError,
  onSuccess,
  onDeleted,
}: HistoryOrderRowProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteMutation = useMutation({
    mutationFn: () => dlPortalApi.deleteOrder(clientId, order.id),
    onSuccess: () => {
      onSuccess("Zamówienie usunięte");
      onDeleted();
    },
    onError: (err: unknown) => {
      onError(apiErrorMessage(err, "Nie udało się usunąć zamówienia."));
    },
  });

  // Endpoint pliku wymaga nagłówka Bearer — pobieramy blob z tokenem.
  const handleDownloadPo = async () => {
    try {
      await downloadAuthenticatedFile(
        `/api/clients/${clientId}/orders/${order.id}/file`,
        order.filename ?? `zamowienie-${order.id}.pdf`,
      );
    } catch {
      onError("Nie udało się pobrać pliku zamówienia.");
    }
  };

  return (
    <div className="flex items-start justify-between gap-3 rounded border border-border bg-background p-2 text-sm">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={STATUS_BADGE[order.status]} size="sm">
            {STATUS_LABELS[order.status]}
          </Badge>
          <span className="font-medium">{order.title}</span>
          <OrderTypeBadge type={effectiveClientOrderType(order, legacyNullOrderType)} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          {(order.start_date || order.end_date) && (
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" aria-hidden="true" />
              {fmtDate(order.start_date)} → {fmtDate(order.end_date) || "bezterminowo"}
            </span>
          )}
          {canViewFinance && order.rate_client !== null && (
            <span>
              przychód {fmtMoney(order.rate_client)}{" "}
              {normalizeOrderCurrency(
                order.rate_client_currency,
                order.currency,
                fallbackRateClientCurrency,
              )}
              {rateUnitSuffix(order.rate_unit ?? fallbackRateUnit)}
            </span>
          )}
          {/* Marża zostaje /mc — jest znormalizowana miesięcznie po stronie BE. */}
          {canViewFinance && order.monthly_margin !== null && (
            <span className="flex items-center gap-1 text-success">
              <TrendingUp className="h-3 w-3" aria-hidden="true" />
              marża {fmtMoney(order.monthly_margin)}/mc
            </span>
          )}
          {order.has_file && (
            <button
              type="button"
              onClick={handleDownloadPo}
              className="flex items-center gap-1 hover:text-primary"
            >
              <Download className="h-3 w-3" aria-hidden="true" />
              PDF
            </button>
          )}
          {canManageOrders ? <CompleteOrderLink onClick={() => onEditOrder(order)} orderNumber={order.title || null} /> : null}
        </div>
      </div>
      {canManageOrders ? (
        <button
          type="button"
          onClick={() => setConfirmingDelete(true)}
          className="hit-area p-1 text-muted-foreground hover:text-destructive"
          title="Usuń zamówienie"
          aria-label="Usuń zamówienie"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      ) : null}
      {confirmingDelete ? (
        <DeleteOrderDialog
          clientId={clientId}
          orderId={order.id}
          title={order.title}
          pending={deleteMutation.isPending}
          onConfirm={() => {
            setConfirmingDelete(false);
            deleteMutation.mutate();
          }}
          onClose={() => setConfirmingDelete(false)}
        />
      ) : null}
    </div>
  );
}
