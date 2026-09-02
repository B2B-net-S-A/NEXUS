"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";
import { ContractorOrderCards } from "@/components/OrdersAndContractsTab";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import {
  orderGroupsApi,
  type OrderGroupExtendInput,
  type OrderGroupInput,
  type OrderGroupRead,
  type OrderLineRead,
  type OrderOffboardingResolutionInput,
  type OrderType,
  type SwapConsultantInput,
} from "@/lib/api/orderGroups";
import { countPl } from "@/lib/plural-pl";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  ORDER_TYPE_ORDER,
  contractorMatchesPill,
  contractorOrderType,
  effectiveClientOrderType,
  effectiveGroupOrderType,
  filterMaterializedContractorShells,
  filterAndSortContractors,
  filterAndSortOrderGroups,
  flattenOrderGroupIds,
  orderGroupMatchesPill,
  sortUnifiedOrderItems,
  visibleLegacyOrderIds,
  type LegacyClientOrderType,
  type OrderListFilters,
  type UnifiedOrderPill,
} from "@/lib/client-order-list";
import {
  downloadBlob,
  postAuthenticatedDownload,
} from "@/lib/authenticated-files";
import {
  canViewCandidateFinance,
  canManageMultiConsultantOrders,
  canManageOrderLifecycle,
  hasRole,
  useAuthStore,
} from "@/store/auth";

import { ConsultantLineModal, type LineFormValues } from "./ConsultantLineModal";
import { EndOrderGroupModal } from "./EndOrderGroupModal";
import { ExtendOrderGroupModal } from "./ExtendOrderGroupModal";
import { NordeaOrderImportPanel } from "./NordeaOrderImportPanel";
import { OffboardingDecisionModal } from "./OffboardingDecisionModal";
import { OrderGroupCard, type OrderGroupFocusRequest } from "./OrderGroupCard";
import { OrderGroupFormModal } from "./OrderGroupFormModal";
import { OrderListControls } from "./OrderListControls";
import { OrderTypeBadge, orderTypeLabel } from "./OrderTypeBadge";
import { SwapConsultantModal } from "./SwapConsultantModal";

/** Wyciąga czytelny komunikat z odpowiedzi API (detail bywa stringiem lub obiektem). */
function apiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    const typedDetail = detail as { code?: string; message?: string };
    const code = typedDetail.code;
    if (code === "finance_fields_forbidden") {
      return (
        "Stawki linii może ustawiać administrator albo Delivery Lead " +
        "przypisany do tego klienta."
      );
    }
    if (typedDetail.message) return typedDetail.message;
  }
  return fallback;
}

/** Wynik zapisu zamówienia razem z osobnym, drugim wywołaniem — wgraniem PDF-a.
 *
 *  `fileError` niepuste znaczy: zamówienie JEST zapisane, plik nie wszedł.
 *  Rozdzielenie tych dwóch faktów jest tu istotne, bo mylenie ich prowadzi
 *  wprost do duplikatu zamówienia (patrz `attachFile`). */
type GroupSaveResult = { saved: OrderGroupRead; fileError: string | null };

const PILLS: Array<{ key: UnifiedOrderPill; label: string }> = [
  { key: "all", label: "Wszystkie" },
  { key: "active", label: "Aktywne" },
  { key: "ending_30d", label: "⚠️ Kończące się 30d" },
  { key: "completed", label: "Zakończeni" },
  { key: "exhausted", label: "Wyczerpane" },
  { key: "draft", label: "📝 Draft (do uzupełnienia)" },
];

interface Props {
  clientId: number;
  /** Zachowuje klientowe dodatki dotychczasowego rejestru okresowego (np. import Nordei). */
  clientName?: string;
  /** Czy u tego klienta wolno zakładać zamówienia KOSZTOWE.
   *
   *  Flagę liczy SERWER (konfiguracja lub jawny predykat klienta) i przekazuje
   *  ją profil klienta, który i tak ma już pobrany rekord. Front nie trzyma
   *  kopii listy klientów ani nie robi drugiego zapytania o ten sam obiekt. */
  costOrdersEnabled?: boolean;
  /** Trwała konfiguracja klienta; `false` usuwa typ okresowy z tworzenia. */
  periodicOrdersEnabled?: boolean;
}

/**
 * Jedna zakładka i jeden zestaw kontrolek dla wszystkich typów zamówień.
 * Renderowanie kart pozostaje domenowe: okresowe korzystają z kart kontraktora,
 * a kosztowe/MD z grup, ale użytkownik dostaje jedną posortowaną listę.
 */
export function MultiConsultantOrdersTab({
  clientId,
  clientName = "",
  costOrdersEnabled = false,
  periodicOrdersEnabled = true,
}: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((s) => s.user);
  const canViewFinance = canViewCandidateFinance(user);
  const canManage = canManageMultiConsultantOrders(user);
  const canLifecycle = canManageOrderLifecycle(user);
  const canExport =
    !hasRole(user, "talent_community_manager") ||
    hasRole(user, "admin", "delivery_lead", "finance");
  const legacyNullOrderType: LegacyClientOrderType = periodicOrdersEnabled
    ? "periodic"
    : "md";
  const allowedOrderTypes: readonly OrderType[] = periodicOrdersEnabled
    ? ["periodic", "cost", "md"]
    : costOrdersEnabled
      ? ["cost", "md"]
      : ["md"];

  const [pill, setPill] = useState<UnifiedOrderPill>("all");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<OrderListFilters>({
    ...DEFAULT_ORDER_LIST_FILTERS,
  });
  const [exporting, setExporting] = useState(false);
  const [newOrderType, setNewOrderType] = useState<OrderType>("periodic");
  const [standardOrderModalOpen, setStandardOrderModalOpen] = useState(false);
  const [groupModal, setGroupModal] = useState<{ open: boolean; group: OrderGroupRead | null }>(
    { open: false, group: null },
  );
  const [lineModal, setLineModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
    line: OrderLineRead | null;
  }>({ open: false, group: null, line: null });
  const [swapModal, setSwapModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
    line: OrderLineRead | null;
  }>({ open: false, group: null, line: null });
  const [offboardingModal, setOffboardingModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
    line: OrderLineRead | null;
  }>({ open: false, group: null, line: null });
  const [endModal, setEndModal] = useState<{ open: boolean; group: OrderGroupRead | null }>({
    open: false,
    group: null,
  });
  const [extendModal, setExtendModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
  }>({ open: false, group: null });
  const [formError, setFormError] = useState<string | null>(null);
  // Przejście z wpisu „transfer_md" do zamówienia powiązanego. Żądanie leci do
  // WSZYSTKICH kart, bo cel bywa zagnieżdżony w przyszłych zamówieniach innej
  // karty — tylko ona wie, że go zawiera, i tylko ona umie się rozwinąć.
  const [focusRequest, setFocusRequest] = useState<OrderGroupFocusRequest | null>(
    null,
  );

  const query = useQuery({
    queryKey: ["client-order-groups", clientId],
    queryFn: async () => (await orderGroupsApi.list(clientId)).data,
  });
  const contractorQuery = useQuery({
    queryKey: ["dl-orders-grouped", clientId],
    queryFn: async () => (await dlPortalApi.listContractorsWithOrders(clientId)).data,
  });
  const serverSuggestedOrderType = query.data?.suggested_order_type ?? "periodic";
  const suggestedOrderType = allowedOrderTypes.includes(serverSuggestedOrderType)
    ? serverSuggestedOrderType
    : allowedOrderTypes[0];

  function openNewOrderForm(orderType: OrderType) {
    const allowedType = allowedOrderTypes.includes(orderType)
      ? orderType
      : allowedOrderTypes[0];
    setFormError(null);
    setNewOrderType(allowedType);
    if (allowedType === "periodic") {
      setGroupModal({ open: false, group: null });
      setStandardOrderModalOpen(true);
      return;
    }
    setStandardOrderModalOpen(false);
    setGroupModal({ open: true, group: null });
  }

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] });
    queryClient.invalidateQueries({ queryKey: ["dl-orders-grouped", clientId] });
    queryClient.invalidateQueries({ queryKey: ["order-group-events", clientId] });
    queryClient.invalidateQueries({ queryKey: ["contract-documents"] });
    // Backend oznacza alert jako handled w tej samej transakcji co decyzję.
    // Dashboard ma od razu odczytać ten stan, bez czekania na staleTime.
    queryClient.invalidateQueries({ queryKey: ["dl-alerts"] });
  };

  /** Dogrywa PDF do zamówienia, które JUŻ jest w bazie.
   *
   *  Zapis zamówienia z plikiem to DWA wywołania API pod jedną mutacją.
   *  `replaceFile` ma własne ścieżki odmowy (415 nie-PDF, 415 zły magic
   *  `%PDF-`, 413 powyżej 25 MB, 410 brak pliku) plus 30-sekundowy timeout
   *  instancji axios — a `order_number` jest świadomie BEZ unikalności w bazie.
   *  Gdyby błąd uploadu leciał do `onError` mutacji, komunikat mówiłby „nie
   *  udało się zapisać zamówienia" przy otwartym modalu, mimo że grupa razem
   *  z liniami konsultantów już istnieje — a kliknięcie „Zapisz" jeszcze raz
   *  zakładałoby DRUGIE zamówienie o tym samym numerze. Niejednoznaczność
   *  wyszłaby dopiero przy imporcie zużycia MD, czyli daleko od przyczyny.
   *  Dlatego awarię uploadu zwracamy jako część UDANEGO wyniku: modal się
   *  zamyka, lista się odświeża, a komunikat mówi prawdę o tym, co nie weszło.
   */
  async function attachFile(
    group: OrderGroupRead,
    file: File | null,
  ): Promise<GroupSaveResult> {
    if (!file) return { saved: group, fileError: null };
    try {
      const withFile = (await orderGroupsApi.replaceFile(clientId, group.id, file))
        .data;
      return { saved: withFile, fileError: null };
    } catch (err) {
      return {
        saved: group,
        fileError: apiError(err, "Nie udało się wgrać pliku PDF."),
      };
    }
  }

  /** Jeden komunikat na dwa możliwe wyniki: pełny sukces albo zapis bez pliku. */
  function announceSaved(result: GroupSaveResult, savedMessage: string) {
    if (result.fileError) {
      showToast(
        `${savedMessage}, ale nie udało się wgrać PDF-a: ${result.fileError} ` +
          "Wgraj plik ponownie przez edycję zamówienia — NIE zakładaj go " +
          "drugi raz.",
        "error",
      );
      return;
    }
    showToast(savedMessage, "success");
  }

  const saveGroup = useMutation({
    mutationFn: async ({
      values,
      file,
    }: {
      values: OrderGroupInput;
      file: File | null;
    }): Promise<GroupSaveResult> => {
      let saved: OrderGroupRead;
      if (groupModal.group) {
        saved = (
          await orderGroupsApi.update(clientId, groupModal.group.id, {
            order_number: values.order_number,
            start_date: values.start_date,
            end_date: values.end_date,
            notes: values.notes,
            ...(values.budget_amount != null
              ? { budget_amount: values.budget_amount }
              : {}),
            ...(values.md_budget_total != null
              ? { md_budget_total: values.md_budget_total }
              : {}),
          })
        ).data;
      } else {
        saved = (await orderGroupsApi.create(clientId, values)).data;
      }
      return attachFile(saved, file);
    },
    onSuccess: (result) => {
      setGroupModal({ open: false, group: null });
      setFormError(null);
      invalidate();
      announceSaved(result, "Zapisano zamówienie");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zapisać zamówienia.")),
  });

  const saveLine = useMutation({
    mutationFn: async (values: LineFormValues) => {
      const group = lineModal.group;
      if (!group) throw new Error("Brak zamówienia");
      if (lineModal.line) {
        return (
          await orderGroupsApi.updateLine(clientId, group.id, lineModal.line.id, {
            rate_cost: values.rate_cost,
            rate_revenue: values.rate_revenue,
            ...(values.input_mode ? { input_mode: values.input_mode } : {}),
            ...(values.input_value != null
              ? { input_value: values.input_value }
              : {}),
            end_date: values.end_date,
          })
        ).data;
      }
      return (await orderGroupsApi.addLine(clientId, group.id, values)).data;
    },
    onSuccess: () => {
      setLineModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast("Zapisano linię konsultanta", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zapisać linii.")),
  });

  const adjustRemaining = useMutation({
    mutationFn: async (mdRemaining: number) => {
      const group = lineModal.group;
      const line = lineModal.line;
      if (!group || !line) throw new Error("Brak linii");
      return (
        await orderGroupsApi.updateLine(clientId, group.id, line.id, {
          md_remaining: mdRemaining,
        })
      ).data;
    },
    onSuccess: () => {
      setLineModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast("Skorygowano pozostałe MD", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się skorygować MD.")),
  });

  const swap = useMutation({
    mutationFn: async (values: SwapConsultantInput) => {
      const group = swapModal.group;
      const line = swapModal.line;
      if (!group || !line) throw new Error("Brak linii");
      return (await orderGroupsApi.swapLine(clientId, group.id, line.id, values)).data;
    },
    onSuccess: () => {
      setSwapModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast("Zamieniono kontraktora", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zamienić kontraktora.")),
  });

  const resolveOffboarding = useMutation({
    mutationFn: async (values: OrderOffboardingResolutionInput) => {
      const group = offboardingModal.group;
      const offboardingCase = offboardingModal.line?.offboarding_case;
      if (!group || !offboardingCase || offboardingCase.status !== "pending") {
        throw new Error("Brak aktywnej sprawy zakończenia współpracy");
      }
      return (
        await orderGroupsApi.resolveOffboardingCase(
          clientId,
          group.id,
          offboardingCase.id,
          values,
        )
      ).data;
    },
    onSuccess: () => {
      setOffboardingModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast("Zapisano decyzję i zaktualizowano obsadę zamówienia", "success");
    },
    onError: (err) => {
      setFormError(
        apiError(err, "Nie udało się zapisać decyzji o pozostałej puli MD."),
      );
      // Konflikt wersji oznacza, że ktoś rozstrzygnął sprawę w innym oknie.
      // Odświeżenie listy usuwa z formularza nieaktualną wersję sprawy.
      queryClient.invalidateQueries({
        queryKey: ["client-order-groups", clientId],
      });
    },
  });

  // ── Cykl życia ────────────────────────────────────────────────────────────

  const removeLine = useMutation({
    mutationFn: ({ groupId, lineId }: { groupId: number; lineId: number }) =>
      orderGroupsApi.removeLine(clientId, groupId, lineId),
    onSuccess: () => {
      invalidate();
      showToast("Usunięto konsultanta z zamówienia", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się usunąć konsultanta."), "error"),
  });

  const removeGroup = useMutation({
    mutationFn: (groupId: number) => orderGroupsApi.remove(clientId, groupId),
    onSuccess: () => {
      invalidate();
      showToast("Usunięto zamówienie", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się usunąć zamówienia."), "error"),
  });

  const closeGroup = useMutation({
    mutationFn: (values: { closure_date: string; closure_reason: string | null }) => {
      const group = endModal.group;
      if (!group) throw new Error("Brak zamówienia");
      return orderGroupsApi.close(clientId, group.id, values);
    },
    onSuccess: () => {
      setEndModal({ open: false, group: null });
      setFormError(null);
      invalidate();
      showToast("Zamówienie zakończone", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zakończyć zamówienia.")),
  });

  const reopenGroup = useMutation({
    mutationFn: (groupId: number) => orderGroupsApi.reopen(clientId, groupId),
    onSuccess: () => {
      invalidate();
      showToast("Zamówienie przywrócone", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się przywrócić zamówienia."), "error"),
  });

  const extendGroup = useMutation({
    mutationFn: async ({
      values,
      file,
    }: {
      values: OrderGroupExtendInput;
      file: File | null;
    }): Promise<GroupSaveResult> => {
      const group = extendModal.group;
      if (!group) throw new Error("Brak zamówienia");
      const created = (await orderGroupsApi.extend(clientId, group.id, values)).data;
      // Ta sama pułapka co przy zakładaniu, tylko dotkliwsza: ponowienie po
      // awarii uploadu założyłoby DRUGIE przedłużenie tego samego zamówienia,
      // czyli dwie równorzędne karty następcy z jednym poprzednikiem.
      return attachFile(created, file);
    },
    onSuccess: (result) => {
      setExtendModal({ open: false, group: null });
      setFormError(null);
      invalidate();
      announceSaved(result, "Utworzono przedłużenie");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się utworzyć przedłużenia.")),
  });

  const groups = useMemo(() => query.data?.groups ?? [], [query.data]);
  const contractors = useMemo(
    () =>
      filterMaterializedContractorShells(
        contractorQuery.data?.contractors ?? [],
        groups,
      ),
    [contractorQuery.data, groups],
  );
  const counts = useMemo(() => {
    const byStatus = {} as Record<UnifiedOrderPill, number>;
    for (const entry of PILLS) {
      byStatus[entry.key] =
        groups.filter((group) => orderGroupMatchesPill(group, entry.key)).length +
        contractors.filter((contractor) =>
          contractorMatchesPill(contractor, entry.key),
        ).length;
    }
    return byStatus;
  }, [contractors, groups]);
  const visibleGroups = useMemo(
    () =>
      filterAndSortOrderGroups(
        groups.filter((group) => orderGroupMatchesPill(group, pill)),
        search,
        filters,
      ),
    [filters, groups, pill, search],
  );
  const visibleContractors = useMemo(
    () =>
      // „Blisko budżetu" opisuje wyłącznie grupy kosztowe/MD. Kontraktorzy
      // okresowi nie mają wspólnego budżetu, więc przy tym filtrze odpadają.
      filters.nearBudget
        ? []
        : filterAndSortContractors(
            contractors.filter((contractor) =>
              contractorMatchesPill(contractor, pill),
            ),
            search,
            filters,
          ),
    [contractors, filters, pill, search],
  );
  const sections = useMemo(
    () =>
      ORDER_TYPE_ORDER.map((type) => ({
        type,
        items: sortUnifiedOrderItems(
          [
            ...visibleGroups
              .filter((group) => effectiveGroupOrderType(group) === type)
              .map((group) => ({ kind: "group" as const, group })),
            ...visibleContractors
              .filter(
                (contractor) =>
                  (contractor.orders.length > 0
                    ? contractorOrderType(contractor, legacyNullOrderType)
                    : suggestedOrderType) === type,
              )
              .map((contractor) => ({
                kind: "contractor" as const,
                contractor,
              })),
          ],
          filters.sort,
        ),
      })).filter((section) => section.items.length > 0),
    [
      filters.sort,
      legacyNullOrderType,
      suggestedOrderType,
      visibleContractors,
      visibleGroups,
    ],
  );
  const resultCount = visibleGroups.length + visibleContractors.length;

  async function exportVisible() {
    setExporting(true);
    try {
      const visibleOrderIds = new Set(
        visibleLegacyOrderIds(visibleContractors, search),
      );
      type ExportItem =
        | { kind: "group"; id: number }
        | { kind: "order"; id: number };
      const items: ExportItem[] = ORDER_TYPE_ORDER.flatMap<ExportItem>((type) =>
        sortUnifiedOrderItems(
          [
            ...visibleGroups
              .filter((group) => effectiveGroupOrderType(group) === type)
              .map((group) => ({ kind: "group" as const, group })),
            ...visibleContractors
              .filter((contractor) =>
                contractor.orders.some(
                  (order) =>
                    visibleOrderIds.has(order.id) &&
                    effectiveClientOrderType(order, legacyNullOrderType) === type,
                ),
              )
              .map((contractor) => ({
                kind: "contractor" as const,
                contractor,
              })),
          ],
          filters.sort,
        ).flatMap<ExportItem>((item) =>
          item.kind === "group"
            ? flattenOrderGroupIds([item.group]).map((id) => ({
                kind: "group" as const,
                id,
              }))
            : item.contractor.orders
                .filter(
                  (order) =>
                    visibleOrderIds.has(order.id) &&
                    effectiveClientOrderType(order, legacyNullOrderType) === type,
                )
                .map((order) => ({ kind: "order" as const, id: order.id })),
        ),
      );
      const result = await postAuthenticatedDownload(
        `/api/clients/${clientId}/orders/export`,
        { items },
      );
      downloadBlob(result.blob, result.filename ?? "Zamowienia.xlsx");
      showToast("Pobrano zamówienia do Excela", "success");
    } catch {
      showToast("Nie udało się przygotować pliku Excel.", "error");
    } finally {
      setExporting(false);
    }
  }

  function renderGroup(group: OrderGroupRead) {
    return (
      <OrderGroupCard
        key={group.id}
        clientId={clientId}
        group={group}
        searchQuery={search}
        canManage={canManage}
        canManageLifecycle={canLifecycle}
        onAddConsultant={(selected) => {
          setFormError(null);
          setLineModal({ open: true, group: selected, line: null });
        }}
        onEditGroup={(selected) => {
          setFormError(null);
          setGroupModal({ open: true, group: selected });
        }}
        onEditLine={(selected, line) => {
          setFormError(null);
          setLineModal({ open: true, group: selected, line });
        }}
        onSwapLine={(selected, line) => {
          setFormError(null);
          setSwapModal({ open: true, group: selected, line });
        }}
        onResolveOffboarding={(selected, line) => {
          setFormError(null);
          setOffboardingModal({ open: true, group: selected, line });
        }}
        onDeleteLine={(selected, line) => {
          if (
            !window.confirm(
              `Czy na pewno chcesz usunąć konsultanta ${line.consultant_name} ` +
                `z zamówienia nr ${selected.order_number}? Tej operacji nie można cofnąć.`,
            )
          ) {
            return;
          }
          removeLine.mutate({ groupId: selected.id, lineId: line.id });
        }}
        onDeleteGroup={(selected) => {
          if (
            !window.confirm(
              `Czy na pewno chcesz usunąć całe zamówienie nr ${selected.order_number} ` +
                `wraz ze wszystkimi konsultantami? Tej operacji nie można cofnąć.`,
            )
          ) {
            return;
          }
          removeGroup.mutate(selected.id);
        }}
        onCloseGroup={(selected) => {
          setFormError(null);
          setEndModal({ open: true, group: selected });
        }}
        onReopenGroup={(selected) => reopenGroup.mutate(selected.id)}
        onExtendGroup={(selected) => {
          setFormError(null);
          setExtendModal({ open: true, group: selected });
        }}
        focusRequest={focusRequest}
        onFocusGroup={(groupId) =>
          setFocusRequest((previous) => ({
            groupId,
            nonce: (previous?.nonce ?? 0) + 1,
          }))
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-foreground">
            Zamówienia klienta
          </h2>
          <p className="text-xs text-muted-foreground">
            Jedna lista zamówień okresowych, kosztowych i rozliczanych w MD.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* `isSuccess`, nie `!isLoading && !isError` — w przerwie między
              ponowieniami dane są puste, a licznik pokazywałby „0 zamówienia",
              czyli tę samą nieprawdę co pusty stan pod spodem. */}
          {query.isSuccess && contractorQuery.isSuccess ? (
            <p className="text-xs text-muted-foreground">
              {countPl(
                groups.length + contractors.length,
                "pozycja na liście",
                "pozycje na liście",
                "pozycji na liście",
              )}
            </p>
          ) : null}
          {canManage ? (
            <button
              type="button"
              disabled={!query.isSuccess || !contractorQuery.isSuccess}
              onClick={() => openNewOrderForm(suggestedOrderType)}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              <Plus className="h-4 w-4" aria-hidden="true" /> Nowe zamówienie
            </button>
          ) : null}
        </div>
      </header>

      {/* Liczniki liczone z POBRANEJ listy, nie z osobnego zapytania — kafel
          będący sumą innych liczb niż widoczne pod nim jest niemożliwy do
          zweryfikowania wzrokiem. Renderujemy je dopiero przy `isSuccess`,
          żeby „(0)" nie udawało wyniku, zanim cokolwiek wiadomo. */}
      {query.isSuccess && contractorQuery.isSuccess ? (
        <div className="flex flex-wrap gap-2">
          {PILLS.map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setPill(entry.key)}
              aria-pressed={pill === entry.key}
              className={
                "rounded-full border px-3 py-1.5 text-sm transition-colors " +
                (pill === entry.key
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-card text-muted-foreground hover:text-foreground")
              }
            >
              {entry.label} ({counts[entry.key]})
            </button>
          ))}
        </div>
      ) : null}

      {query.isSuccess && contractorQuery.isSuccess ? (
        <OrderListControls
          search={search}
          onSearchChange={setSearch}
          filters={filters}
          onFiltersChange={setFilters}
          resultCount={resultCount}
          exporting={exporting}
          onExport={exportVisible}
          showExport={canExport}
        />
      ) : null}

      {query.isSuccess &&
      contractorQuery.isSuccess &&
      (user?.role === "admin" || user?.roles?.includes("admin")) &&
      clientName.toLocaleLowerCase("pl").includes("nordea") ? (
        <NordeaOrderImportPanel clientId={clientId} onApplied={invalidate} />
      ) : null}

      {query.isError || contractorQuery.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać pełnej listy zamówień tego klienta."
          onRetry={() => {
            query.refetch();
            contractorQuery.refetch();
          }}
        />
      ) : !query.isSuccess || !contractorQuery.isSuccess ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          Wczytywanie zamówień…
        </p>
      ) : resultCount === 0 ? (
        <EmptyState
          title={
            search.trim()
              ? "Nie znaleziono zamówienia pasującego do wyszukiwania"
              : pill === "all"
                ? "Brak zamówień"
                : "Brak wyników dla tego filtra"
          }
          description={
            search.trim()
              ? "Zmień wyszukiwaną frazę albo wyczyść aktywne filtry."
              : pill === "all"
                ? "Ten klient nie ma jeszcze zamówień."
                : "Zmień filtr, żeby zobaczyć pozostałe zamówienia."
          }
        />
      ) : (
        <div className="flex flex-col gap-6">
          {sections.map((section) => (
            <section
              key={section.type}
              aria-labelledby={`orders-${section.type}-heading`}
              className="space-y-3"
            >
              <h3
                id={`orders-${section.type}-heading`}
                className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                <OrderTypeBadge type={section.type} />
                {orderTypeLabel(section.type)} ({section.items.length})
              </h3>
              {section.items.map((item) =>
                item.kind === "group" ? (
                  renderGroup(item.group)
                ) : (
                  <ContractorOrderCards
                    key={`contractor-${item.contractor.contract_id}`}
                    clientId={clientId}
                    contractors={[item.contractor]}
                    canViewFinance={canViewFinance}
                    canManageFinance={contractorQuery.data.can_manage_finance}
                    canManageOrders={contractorQuery.data.can_manage_finance}
                    suggestedOrderType={suggestedOrderType}
                    legacyNullOrderType={legacyNullOrderType}
                    allowedOrderTypes={allowedOrderTypes}
                    searching={search.trim().length > 0}
                  />
                ),
              )}
            </section>
          ))}
        </div>
      )}

      <OrderGroupFormModal
        open={groupModal.open}
        onOpenChange={(open) => setGroupModal((s) => ({ ...s, open }))}
        group={groupModal.group}
        clientId={clientId}
        orderType={
          groupModal.group
            ? groupModal.group.order_type === "cost" ||
              groupModal.group.is_cost_based
              ? "cost"
              : "md"
            : newOrderType === "periodic"
              ? "cost"
              : newOrderType
        }
        onOrderTypeChange={(orderType) => openNewOrderForm(orderType)}
        allowedOrderTypes={allowedOrderTypes}
        submitting={saveGroup.isPending}
        error={formError}
        onSubmit={(values, file) => saveGroup.mutate({ values, file })}
        onDeleteFile={async () => {
          const group = groupModal.group;
          if (!group) return;
          await orderGroupsApi.deleteFile(clientId, group.id);
          invalidate();
          showToast("Plik PDF zamówienia usunięty", "success");
        }}
      />

      {standardOrderModalOpen ? (
        <NewContractorOrderDialog
          clientId={clientId}
          canManageFinance={
            contractorQuery.data?.can_manage_finance ?? false
          }
          orderType={newOrderType}
          onOrderTypeChange={openNewOrderForm}
          allowedOrderTypes={allowedOrderTypes}
          onClose={() => setStandardOrderModalOpen(false)}
          onCreated={() => {
            setStandardOrderModalOpen(false);
            invalidate();
          }}
        />
      ) : null}

      <ConsultantLineModal
        open={lineModal.open}
        onOpenChange={(open) => setLineModal((s) => ({ ...s, open }))}
        clientId={clientId}
        group={lineModal.group}
        line={lineModal.line}
        submitting={saveLine.isPending || adjustRemaining.isPending}
        error={formError}
        onSubmit={(values) => saveLine.mutate(values)}
        onAdjustRemaining={
          lineModal.line ? (md) => adjustRemaining.mutate(md) : undefined
        }
      />

      <SwapConsultantModal
        open={swapModal.open}
        onOpenChange={(open) => setSwapModal((s) => ({ ...s, open }))}
        clientId={clientId}
        group={swapModal.group}
        line={swapModal.line}
        submitting={swap.isPending}
        error={formError}
        onSubmit={(values) => swap.mutate(values)}
      />

      <OffboardingDecisionModal
        open={offboardingModal.open}
        onOpenChange={(open) =>
          setOffboardingModal((state) => ({ ...state, open }))
        }
        group={offboardingModal.group}
        line={offboardingModal.line}
        submitting={resolveOffboarding.isPending}
        error={formError}
        onSubmit={(values) => resolveOffboarding.mutate(values)}
      />

      <EndOrderGroupModal
        open={endModal.open}
        onOpenChange={(open) => setEndModal((s) => ({ ...s, open }))}
        group={endModal.group}
        submitting={closeGroup.isPending}
        error={formError}
        onSubmit={(values) => closeGroup.mutate(values)}
      />

      <ExtendOrderGroupModal
        open={extendModal.open}
        onOpenChange={(open) => setExtendModal((s) => ({ ...s, open }))}
        clientId={clientId}
        group={extendModal.group}
        submitting={extendGroup.isPending}
        error={formError}
        onSubmit={(values, file) => extendGroup.mutate({ values, file })}
      />
    </div>
  );
}
