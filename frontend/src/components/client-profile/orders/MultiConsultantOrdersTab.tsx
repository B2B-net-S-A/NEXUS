"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";
import { DeleteOrderDialog } from "@/components/orders/DeleteOrderDialog";
import { DeleteOrderGroupDialog } from "@/components/orders/DeleteOrderGroupDialog";
import {
  CancelOrderGroupDialog,
  cancelRefusalMessage,
} from "@/components/client-profile/orders/CancelOrderGroupDialog";
import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { Button } from "@/components/ui/button";
import { useRowNavigation } from "@/hooks/useRowNavigation";
import { writeUrlParams } from "@/lib/url-selection";
import { useToast } from "@/components/Toast";
import { useClientDefaultRateUnit } from "@/hooks/useClientDefaultRateUnit";
import { dlPortalApi, type ContractWithOrdersRead } from "@/lib/api/dlPortal";
import { orderMailApi } from "@/lib/api/orderMail";
import {
  orderGroupsApi,
  type OrderGroupExtendInput,
  type OrderGroupInput,
  type OrderGroupRead,
  type OrderLineInput,
  type OrderLineRead,
  type OrderLineTakeoverInput,
  type OrderOffboardingResolutionInput,
  type OrderType,
  type SwapConsultantInput,
} from "@/lib/api/orderGroups";
import { apiErrorMessage } from "@/lib/api-error";
import { countPl } from "@/lib/plural-pl";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  ORDER_TYPE_ORDER,
  consultantMatchesQuery,
  buildOrderGroupFamilies,
  contractorMatchesPill,
  contractorOrderType,
  effectiveClientOrderType,
  effectiveGroupOrderType,
  filterMaterializedContractorShells,
  filterAndSortContractors,
  filterAndSortOrderGroups,
  flattenOrderGroupIds,
  resolveOrderFocus,
  orderGroupMatchesPill,
  sortUnifiedOrderItems,
  usesSharedMdPool,
  visibleLegacyOrderIds,
  type LegacyClientOrderType,
  type OrderListFilters,
  type UnifiedOrderPill,
} from "@/lib/client-order-list";
import {
  downloadBlob,
  fetchAuthenticatedBlob,
  postAuthenticatedDownload,
} from "@/lib/authenticated-files";
import { cn } from "@/lib/utils";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import {
  canViewClientFinance,
  canEditOrderLineAmounts,
  canManageMultiConsultantOrders,
  canManageOrderLifecycle,
  hasRole,
  useAuthStore,
} from "@/store/auth";

import { AssignToOrderModal } from "./AssignToOrderModal";
import {
  ConsultantLineModal,
  type LineFormValues,
} from "./ConsultantLineModal";
import { EndOrderGroupModal } from "./EndOrderGroupModal";
import { ExtendOrderGroupModal } from "./ExtendOrderGroupModal";
import { NordeaOrderImportPanel } from "./NordeaOrderImportPanel";
import { OffboardingDecisionModal } from "./OffboardingDecisionModal";
import { EndedLineDecisionDialog } from "./EndedLineDecisionDialog";
import { OrderGroupPanel, type OrderGroupActions } from "./OrderGroupPanel";
import { OrderLinePanel } from "./OrderLinePanel";
import { OrdersTable, type LinePanelTab } from "./OrdersTable";
import { ContractorOrderPanel, type ContractorOrderFocus } from "./ContractorOrderPanel";
import {
  buildSectionRows,
  findGroup,
  findLine,
  groupRoster,
  selectableKeys,
  selectionFromKey,
  selectionKey,
  type OrderSelection,
  type OrdersTableSection,
} from "./orders-table-model";
import { OrderGroupFormModal } from "./OrderGroupFormModal";
import {
  commonFieldsOfPeriodic,
  periodicDraftForReturn,
  type CarriedOrderFields,
  type PeriodicOrderDraft,
} from "@/lib/order-type-switch";
import { OrderExportButton, OrderListControls } from "./OrderListControls";
import { ReplaceWithTakeoverModal } from "./ReplaceWithTakeoverModal";
import { SwapConsultantModal } from "./SwapConsultantModal";

/** Czytelny komunikat z odpowiedzi API — wspólną regułą `apiErrorMessage`
 *  (audyt 24.09.2026, S12: lokalna kopia przepuszczała surowe komunikaty
 *  po angielsku). Odmowę kwot (`finance_fields_forbidden`) nazywa ta sama
 *  reguła: z `message` serwera albo zdaniem zastępczym bez nazw ról. */
function apiError(err: unknown, fallback: string): string {
  return apiErrorMessage(err, fallback);
}

/** Wynik zapisu zamówienia razem z osobnym, drugim wywołaniem — wgraniem PDF-a.
 *
 *  `fileError` niepuste znaczy: zamówienie JEST zapisane, plik nie wszedł.
 *  Rozdzielenie tych dwóch faktów jest tu istotne, bo mylenie ich prowadzi
 *  wprost do duplikatu zamówienia (patrz `attachFile`). */
type GroupSaveResult = {
  saved: OrderGroupRead;
  fileError: string | null;
  /** Osoby dopisane, ale aktywacja szkicu nie weszła — zamówienie jest zapisane. */
  activationError?: string | null;
};

/** Komunikat złożony przez nas (etap zapisu) — nie mylić z błędem axiosa bez
 *  odpowiedzi (sieć, timeout), który też jest `Error`, ale po angielsku. */
class SaveStepError extends Error {}

function saveErrorMessage(err: unknown, fallback: string): string {
  return err instanceof SaveStepError ? err.message : apiError(err, fallback);
}

/** „Wymaga decyzji" (wersja B) — zamówienia z osobą zakończoną, o której
 *  Delivery Lead jeszcze nie zdecydował. Liczone z tej samej reguły co sekcja
 *  „Zakończone" w tabeli (`requiresDecision`). */
type OrdersPill = UnifiedOrderPill | "decision";

// Etykiety krótkie, żeby pigułki mieściły się w jednym rzędzie na laptopie
// 1280 px (menu 240 px) — pełne brzmienie niesie `title`.
const PILLS: Array<{ key: OrdersPill; label: string; title?: string }> = [
  { key: "all", label: "Wszystkie" },
  { key: "active", label: "Aktywne" },
  { key: "ending_30d", label: "Bez kontynuacji 30 dni" },
  { key: "completed", label: "Zakończeni" },
  { key: "exhausted", label: "Wyczerpane" },
  { key: "cancelled", label: "Anulowane" },
  { key: "draft", label: "Draft", title: "Szkice do uzupełnienia" },
  { key: "decision", label: "Wymaga decyzji" },
];

const TYPE_FILTERS: Array<{ key: OrderType | "all"; label: string }> = [
  { key: "all", label: "Wszystkie typy" },
  { key: "md", label: "MD" },
  { key: "cost", label: "Kosztowe" },
  { key: "periodic", label: "Okresowe" },
];

function groupNeedsDecision(group: OrderGroupRead): boolean {
  return groupRoster(group).pendingDecisions > 0;
}

interface Props {
  clientId: number;
  /** Zachowuje klientowe dodatki dotychczasowego rejestru okresowego (np. import Nordei). */
  clientName?: string;
  /** Jak klasyfikować historyczne zamówienia bez jawnego typu — liczone przez
   *  SERWER (`legacy_null_order_type` klienta). U klientów rozliczanych w MD
   *  (BNP, BIK, Polkomtel, Wedel) to „md", u pozostałych „periodic". */
  legacyNullOrderType?: LegacyClientOrderType;
  /** Dokument z kolejki zamówień z maila (`?orderMailDoc=`) — osoba
   *  nieaktywna/nieznaleziona do rozstrzygnięcia w oknie zamówienia. */
  orderMailDocId?: number | null;
  /** Wywoływane, gdy dokument z maila jest obsłużony albo porzucony
   *  (strona zdejmuje wtedy parametr z adresu). */
  onOrderMailDocDone?: () => void;
  /** Deep link z panelu „Moi klienci": konkretne zamówienie okresowe albo
   *  linia grupy (`?order=`) i zamówienie MD/kosztowe (`?group=`). */
  focusOrderId?: number | null;
  focusGroupId?: number | null;
  /** Panel kontraktora bez zamówienia (karta szkicu) — `?contract=`. */
  focusContractId?: number | null;
  /** Celu nie ma na liście — strona zdejmuje parametry z adresu. Cel
   *  znaleziony ZOSTAJE w adresie jako otwarty panel (wersja B). */
  onFocusHandled?: () => void;
}

/** PDF dokumentu z maila otwarty w oknie zamówienia. */
interface MailSource {
  docId: number;
  file: File;
}

/** Od 09.2026 każdy klient ma wszystkie trzy typy — bez blokady per klient.
 *  Formularz jedynie podpowiada typ najczęstszy u klienta. */
const ALL_ORDER_TYPES: readonly OrderType[] = ["periodic", "cost", "md"];

/**
 * Jedna zakładka i jeden zestaw kontrolek dla wszystkich typów zamówień.
 * Renderowanie kart pozostaje domenowe: okresowe korzystają z kart kontraktora,
 * a kosztowe/MD z grup, ale użytkownik dostaje jedną posortowaną listę.
 */
export function MultiConsultantOrdersTab({
  clientId,
  legacyNullOrderType = "periodic",
  orderMailDocId = null,
  onOrderMailDocDone,
  focusOrderId = null,
  focusGroupId = null,
  focusContractId = null,
  onFocusHandled,
}: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((s) => s.user);
  const canViewFinance = canViewClientFinance(user, clientId);
  // Domyślna jednostka stawki dopasowana do klienta (nigdy `monthly`) dla
  // osadzonych formularzy zamówień; wspólny cache z dialogami.
  const { data: defaultRateUnit } = useClientDefaultRateUnit(clientId);
  const canManage = canManageMultiConsultantOrders(user, clientId);
  // Finanse: wyłącznie kwoty linii (S11) — reszta obsady przy admin/DL.
  const canEditAmounts = canEditOrderLineAmounts(user, clientId);
  const amountsOnly = canEditAmounts && !canManage;
  const canLifecycle = canManageOrderLifecycle(user);
  // Eksport niesie stawki, więc dostaje go ten, kto widzi kwoty tego klienta
  // („Stawki i kwoty: podgląd” — trasa eksportu pyta o to samo). Sam podgląd
  // Delivery, np. Talent Community Manager, zostaje bez eksportu.
  const canExport = canViewFinance;
  const allowedOrderTypes = ALL_ORDER_TYPES;

  const [pill, setPill] = useState<OrdersPill>("all");
  const [typeFilter, setTypeFilter] = useState<OrderType | "all">("all");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<OrderListFilters>({
    ...DEFAULT_ORDER_LIST_FILTERS,
  });
  const [exporting, setExporting] = useState(false);
  const [newOrderType, setNewOrderType] = useState<OrderType>("periodic");
  // PDF wgrany w jednym formularzu przechodzi do drugiego przy zmianie typu
  // (MD/kosztowe ↔ okresowe) — bez ponownego wgrywania.
  const [carriedFile, setCarriedFile] = useState<File | null>(null);
  // Numer zamówienia wpisany przed zmianą typu — jedzie za użytkownikiem do
  // drugiego formularza tak jak plik; do 09.2026 przepadał (UAT B03).
  const [carriedOrderNumber, setCarriedOrderNumber] = useState("");
  // Runda 10 (F02): okres/notatka jadą między formularzami przy zmianie typu,
  // a roboczy stan formularza okresowego czeka na powrót do „Okresowego".
  const [carriedCommon, setCarriedCommon] = useState<CarriedOrderFields | null>(
    null,
  );
  const [carriedPeriodicDraft, setCarriedPeriodicDraft] =
    useState<PeriodicOrderDraft | null>(null);
  const [standardOrderModalOpen, setStandardOrderModalOpen] = useState(false);
  const [groupModal, setGroupModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
  }>({ open: false, group: null });
  const [lineModal, setLineModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
    line: OrderLineRead | null;
    /** „Zastąp kimś innym" — nowa osoba dołączy obok tej linii. */
    replaces?: OrderLineRead | null;
  }>({ open: false, group: null, line: null, replaces: null });
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
  const [endModal, setEndModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
  }>({
    open: false,
    group: null,
  });
  const [extendModal, setExtendModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
  }>({ open: false, group: null });
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteLineTarget, setDeleteLineTarget] = useState<{
    group: OrderGroupRead;
    line: OrderLineRead;
  } | null>(null);
  const [deleteGroupTarget, setDeleteGroupTarget] =
    useState<OrderGroupRead | null>(null);
  const [cancelGroupTarget, setCancelGroupTarget] =
    useState<OrderGroupRead | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [mailSource, setMailSource] = useState<MailSource | null>(null);
  // „Przypisz do zamówienia" z karty szkicu (CeZ) i „Zastąp kimś innym"
  // z przejęciem pozostałych MD (ticket 09.2026).
  const [assignModal, setAssignModal] = useState<{
    contractor: ContractWithOrdersRead;
    openCompleteOrder: () => void;
  } | null>(null);
  const [replaceModal, setReplaceModal] = useState<{
    group: OrderGroupRead;
    line: OrderLineRead;
  } | null>(null);
  // Panel szczegółów (wersja B, 29.09.2026): zaznaczony wiersz tabeli.
  const [selection, setSelection] = useState<OrderSelection | null>(null);
  const [lineTab, setLineTab] = useState<LinePanelTab | null>(null);
  const [expandedEnded, setExpandedEnded] = useState<ReadonlySet<number>>(new Set());
  const [collapsedEnded, setCollapsedEnded] = useState<ReadonlySet<number>>(new Set());
  const [decisionTarget, setDecisionTarget] = useState<{
    group: OrderGroupRead;
    line: OrderLineRead;
  } | null>(null);
  const tableRef = useRef<HTMLDivElement | null>(null);

  const query = useQuery({
    queryKey: ["client-order-groups", clientId],
    queryFn: async () => (await orderGroupsApi.list(clientId)).data,
  });
  const contractorQuery = useQuery({
    queryKey: ["dl-orders-grouped", clientId],
    queryFn: async () => (await dlPortalApi.listContractorsWithOrders(clientId)).data,
  });
  const serverSuggestedOrderType =
    query.data?.suggested_order_type ?? "periodic";
  const suggestedOrderType = allowedOrderTypes.includes(
    serverSuggestedOrderType,
  )
    ? serverSuggestedOrderType
    : allowedOrderTypes[0];

  function openNewOrderForm(
    orderType: OrderType,
    file: File | null = null,
    orderNumber = "",
  ) {
    const allowedType = allowedOrderTypes.includes(orderType)
      ? orderType
      : allowedOrderTypes[0];
    setFormError(null);
    setCarriedFile(file);
    setCarriedOrderNumber(orderNumber);
    setNewOrderType(allowedType);
    if (allowedType === "periodic") {
      setGroupModal({ open: false, group: null });
      setStandardOrderModalOpen(true);
      return;
    }
    setStandardOrderModalOpen(false);
    setGroupModal({ open: true, group: null });
  }

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] }),
      queryClient.invalidateQueries({ queryKey: ["dl-orders-grouped", clientId] }),
      queryClient.invalidateQueries({ queryKey: ["order-group-events", clientId] }),
      queryClient.invalidateQueries({ queryKey: ["contract-documents"] }),
      // The backend marks the alert handled in the decision transaction.
      queryClient.invalidateQueries({ queryKey: ["dl-alerts"] }),
      // Kafle profilu (MRR, obsada) liczą się z tych samych zamówień (N10).
      queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] }),
    ]);
  };

  /** Dokument z maila zostaje w kolejce — okno zamknięte bez zapisu. */
  function releaseMailSource() {
    if (!mailSource) return;
    setMailSource(null);
    onOrderMailDocDone?.();
  }

  // „Rozstrzygnij w oknie zamówienia" z kolejki maila: pobierz PDF dokumentu
  // i otwórz TO SAMO okno co przy ręcznym wgraniu pliku — „Uzupełnij
  // zamówienie", gdy u klienta jest otwarte zamówienie o tym numerze, inaczej
  // „Nowe zamówienie". Karta osoby nieaktywnej/nieznalezionej daje tam wybór
  // zostaw / wznów / zastąp / usuń. Raz na dokument (ref), bo odświeżenie listy
  // nie może otwierać okna drugi raz.
  const mailDocHandled = useRef<number | null>(null);
  useEffect(() => {
    if (!orderMailDocId || !query.isSuccess || !canManage) return;
    if (mailDocHandled.current === orderMailDocId) return;
    mailDocHandled.current = orderMailDocId;
    const docId = orderMailDocId;
    const knownGroups = query.data?.groups ?? [];
    void (async () => {
      try {
        const { data: target } = await orderMailApi.orderTarget(docId);
        if (target.client_id !== clientId) {
          throw new SaveStepError("Dokument z maila dotyczy innego klienta.");
        }
        const blob = await fetchAuthenticatedBlob(orderMailApi.fileUrl(docId));
        const file = new File([blob], target.attachment_name || "zamowienie.pdf", {
          type: "application/pdf",
        });
        const group =
          target.order_group_id !== null
            ? (knownGroups.find((item) => item.id === target.order_group_id) ?? null)
            : null;
        if (target.order_group_id !== null && group === null) {
          // Zamówienie o tym numerze istnieje, ale nie ma go na tej liście —
          // „Nowe zamówienie" założyłoby drugie o tym samym numerze.
          throw new SaveStepError(
            `Zamówienie nr ${target.order_number ?? target.order_group_id} już ` +
              "istnieje, ale nie ma go na liście zamówień tego klienta — " +
              "rozstrzygnij dokument z maila ręcznie.",
          );
        }
        setFormError(null);
        setCarriedFile(null);
        // Numer przeniesiony przy zmianie typu w porzuconym formularzu nie może
        // wjechać do okna otwartego z kolejki maila — tam numer czyta PDF.
        setCarriedOrderNumber("");
        setCarriedCommon(null);
        setCarriedPeriodicDraft(null);
        setMailSource({ docId, file });
        setStandardOrderModalOpen(false);
        setNewOrderType(target.order_type);
        setGroupModal({ open: true, group });
      } catch (err) {
        showToast(
          saveErrorMessage(err, "Nie udało się otworzyć PDF-a z maila zamówień."),
          "error",
        );
        onOrderMailDocDone?.();
      }
    })();
  }, [
    orderMailDocId,
    query.isSuccess,
    query.data,
    canManage,
    clientId,
    showToast,
    onOrderMailDocDone,
  ]);

  /** Zamówienie z okna zapisane — dokument z maila schodzi z kolejki. */
  async function settleMailSource(saved: OrderGroupRead) {
    const source = mailSource;
    if (!source) return;
    setMailSource(null);
    try {
      await orderMailApi.resolvedInOrder(source.docId, saved.id);
      queryClient.invalidateQueries({ queryKey: ["order-mail"] });
      showToast("Dokument z maila zamówień oznaczono jako rozstrzygnięty", "success");
    } catch (err) {
      showToast(
        `Zamówienie jest zapisane, ale dokument #${source.docId} nadal czeka w ` +
          `kolejce zamówień z maila (${apiError(err, "błąd zapisu")}). Oznacz go ` +
          "tam jako odrzucony — NIE zapisuj zamówienia drugi raz.",
        "error",
      );
    } finally {
      onOrderMailDocDone?.();
    }
  }

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
      let activationError: string | null = null;
      if (groupModal.group) {
        const groupId = groupModal.group.id;
        const newLines = values.lines ?? [];
        // Aktywacja pustego szkicu razem z osobami z PDF-a: serwer odmawia
        // aktywacji bez konsultantów, więc kolejność to nagłówek (jeszcze jako
        // szkic) → osoby → aktywacja, a nie aktywacja przed dopisaniem osób.
        const activateAfterLines =
          newLines.length > 0 &&
          values.status === "active" &&
          groupModal.group.status === "draft";
        saved = (
          await orderGroupsApi.update(clientId, groupId, {
            order_number: values.order_number,
            start_date: values.start_date,
            end_date: values.end_date,
            notes: values.notes,
            ...(values.md_consumption_month
              ? {
                  md_consumption_month: values.md_consumption_month,
                  md_consumption_value: values.md_consumption_value,
                }
              : {}),
            ...(values.md_budget_mode != null
              ? { md_budget_mode: values.md_budget_mode }
              : {}),
            ...(values.status && !activateAfterLines ? { status: values.status } : {}),
            ...(values.budget_amount != null
              ? { budget_amount: values.budget_amount }
              : {}),
            ...(values.md_budget_total != null
              ? { md_budget_total: values.md_budget_total }
              : {}),
          })
        ).data;
        // Osoby z PDF-a spoza zamówienia — jednym zapisem, razem albo wcale.
        // Nagłówek jest już zapisany: ponowienie po błędzie powtarza ten sam
        // PATCH (bez skutków ubocznych) i dopiero wtedy dopisuje osoby.
        if (newLines.length > 0) {
          try {
            saved = (await orderGroupsApi.addLines(clientId, groupId, newLines)).data;
          } catch (err) {
            throw new SaveStepError(
              "Numer, okres i budżet zamówienia są zapisane, ale osób z dokumentu " +
                `nie dopisano: ${apiError(err, "błąd zapisu")} Popraw karty i ` +
                "zapisz ponownie.",
            );
          }
        }
        if (activateAfterLines) {
          // Osoby już są na zamówieniu — ponowienie całego zapisu dopisałoby
          // je drugi raz, więc awarię aktywacji zgłaszamy jako częściowy sukces.
          try {
            saved = (
              await orderGroupsApi.update(clientId, groupId, { status: "active" })
            ).data;
          } catch (err) {
            activationError = apiError(err, "błąd zapisu");
          }
        }
      } else {
        saved = (await orderGroupsApi.create(clientId, values)).data;
      }
      return { ...(await attachFile(saved, file)), activationError };
    },
    onSuccess: (result) => {
      if (!groupModal.group || groupModal.group.status === "draft") {
        setPill(result.saved.status === "draft" ? "draft" : "all");
      }
      setGroupModal({ open: false, group: null });
      setFormError(null);
      invalidate();
      announceSaved(result, "Zapisano zamówienie");
      if (result.activationError) {
        showToast(
          "Zamówienie i osoby z dokumentu są zapisane, ale zamówienie zostało " +
            `szkicem — aktywacja nie weszła: ${result.activationError} Aktywuj je ` +
            "przez „Uzupełnij zamówienie” (bez ponownego dopisywania osób).",
          "error",
        );
      }
      void settleMailSource(result.saved);
    },
    onError: (err) =>
      setFormError(saveErrorMessage(err, "Nie udało się zapisać zamówienia.")),
  });

  const saveLine = useMutation({
    mutationFn: async (values: LineFormValues) => {
      const group = lineModal.group;
      if (!group) throw new Error("Brak zamówienia");
      if (lineModal.line && amountsOnly) {
        // Finanse: serwer odrzuca 403 `finance_amounts_only` każde pole
        // niebędące kwotą — wysyłamy wyłącznie stawki i ich waluty.
        return (
          await orderGroupsApi.updateLine(clientId, group.id, lineModal.line.id, {
            rate_candidate_currency: values.rate_candidate_currency,
            rate_client_currency: values.rate_client_currency,
            rate_cost: values.rate_cost,
            rate_revenue: values.rate_revenue,
          })
        ).data;
      }
      if (lineModal.line) {
        return (
          await orderGroupsApi.updateLine(
            clientId,
            group.id,
            lineModal.line.id,
            {
              rate_candidate_currency: values.rate_candidate_currency,
              rate_client_currency: values.rate_client_currency,
              rate_cost: values.rate_cost,
              rate_revenue: values.rate_revenue,
              ...(values.input_mode ? { input_mode: values.input_mode } : {}),
              ...(values.input_value != null
                ? { input_value: values.input_value }
                : {}),
              // `null` jest znaczące (zdejmuje opcję) — przepuszczamy je,
              // pomijamy wyłącznie `undefined` (tryb kwoty / pula / kosztowe).
              ...(values.optional_md !== undefined
                ? { optional_md: values.optional_md }
                : {}),
              end_date: values.end_date,
            },
          )
        ).data;
      }
      return (
        await orderGroupsApi.addLine(clientId, group.id, {
          ...values,
          ...(lineModal.replaces ? { replaces_order_id: lineModal.replaces.id } : {}),
        })
      ).data;
    },
    onSuccess: () => {
      setLineModal({ open: false, group: null, line: null, replaces: null });
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
      showToast(
        "Zapisano decyzję i zaktualizowano obsadę zamówienia",
        "success",
      );
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

  const joinOrder = useMutation({
    mutationFn: async ({ groupId, values }: { groupId: number; values: OrderLineInput }) =>
      (await orderGroupsApi.addLine(clientId, groupId, values)).data,
    onSuccess: () => {
      setAssignModal(null);
      setFormError(null);
      invalidate();
      showToast("Osoba dołączyła do zamówienia", "success");
    },
    onError: (err) =>
      setFormError(apiError(err, "Nie udało się dopisać osoby do zamówienia.")),
  });

  // Jedna mutacja dla trzech wejść: karta szkicu, decyzja o MD z nową osobą
  // i „Zastąp kimś innym". Po sukcesie zamyka każde z tych okien.
  const takeover = useMutation({
    mutationFn: async ({
      groupId,
      values,
    }: {
      groupId: number;
      values: OrderLineTakeoverInput;
    }) => (await orderGroupsApi.takeover(clientId, groupId, values)).data,
    onSuccess: (line) => {
      setAssignModal(null);
      setReplaceModal(null);
      setOffboardingModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast(
        line.status === "draft"
          ? `Zaplanowano zastępstwo od ${line.start_date ?? "dnia wejścia"}`
          : "Zapisano zastępstwo — pozostałe MD przeszły na nową osobę",
        "success",
      );
    },
    onError: (err) => {
      setFormError(apiError(err, "Nie udało się zapisać zastępstwa."));
      queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] });
    },
  });

  // ── Cykl życia ────────────────────────────────────────────────────────────

  const removeLine = useMutation({
    mutationFn: ({ groupId, lineId }: { groupId: number; lineId: number }) =>
      orderGroupsApi.removeLine(clientId, groupId, lineId),
    onSuccess: () => {
      setDeleteLineTarget(null);
      invalidate();
      showToast("Usunięto konsultanta z zamówienia", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się usunąć konsultanta."), "error"),
  });

  const keepHistory = useMutation({
    mutationFn: ({ groupId, lineId }: { groupId: number; lineId: number }) =>
      orderGroupsApi.keepLineHistory(clientId, groupId, lineId),
    onSuccess: () => {
      invalidate();
      showToast("Zostawiono konsultanta na zamówieniu jako historię", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się zapisać decyzji."), "error"),
  });

  const removeGroup = useMutation({
    mutationFn: (groupId: number) => orderGroupsApi.remove(clientId, groupId),
    onSuccess: () => {
      setDeleteGroupTarget(null);
      invalidate();
      showToast("Usunięto zamówienie", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się usunąć zamówienia."), "error"),
  });

  const closeGroup = useMutation({
    mutationFn: (values: {
      closure_date: string;
      closure_reason: string | null;
    }) => {
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

  const cancelGroup = useMutation({
    mutationFn: ({ groupId, reason }: { groupId: number; reason: string | null }) =>
      orderGroupsApi.cancel(clientId, groupId, reason),
    onSuccess: () => {
      setCancelGroupTarget(null);
      setCancelError(null);
      invalidate();
      showToast("Zamówienie anulowane", "success");
    },
    onError: (err) =>
      setCancelError(
        cancelRefusalMessage(err) ?? apiError(err, "Nie udało się anulować zamówienia."),
      ),
  });

  const restoreGroup = useMutation({
    mutationFn: (groupId: number) => orderGroupsApi.restore(clientId, groupId),
    onSuccess: () => {
      invalidate();
      showToast("Anulowane zamówienie przywrócone", "success");
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
  // Osoby z kart szkicu — „Nowe osoby u klienta" w decyzji o MD.
  const draftPeople = useMemo(
    () => contractors.filter((contractor) => contractor.draft_card === true),
    [contractors],
  );
  // Rodziny przedłużeń liczone z PEŁNEJ listy: pigułka i filtr dostają już
  // przefiltrowane grupy, a następca zamówienia może w tym podzbiorze nie być.
  const groupFamilies = useMemo(() => buildOrderGroupFamilies(groups), [groups]);
  const groupMatchesPill = useCallback(
    (group: OrderGroupRead, key: OrdersPill) =>
      key === "decision"
        ? groupNeedsDecision(group)
        : orderGroupMatchesPill(group, key, undefined, groupFamilies),
    [groupFamilies],
  );
  const counts = useMemo(() => {
    const byStatus = {} as Record<OrdersPill, number>;
    for (const entry of PILLS) {
      byStatus[entry.key] =
        groups.filter((group) => groupMatchesPill(group, entry.key)).length +
        (entry.key === "decision"
          ? 0
          : contractors.filter((contractor) =>
              contractorMatchesPill(contractor, entry.key as UnifiedOrderPill),
            ).length);
    }
    return byStatus;
  }, [contractors, groups, groupMatchesPill]);
  const visibleGroups = useMemo(
    () =>
      filterAndSortOrderGroups(
        groups.filter((group) => groupMatchesPill(group, pill)),
        search,
        filters,
        undefined,
        groupFamilies,
      ),
    [filters, groups, groupFamilies, groupMatchesPill, pill, search],
  );
  const visibleContractors = useMemo(
    () =>
      // „Blisko budżetu" opisuje wyłącznie grupy kosztowe/MD. Kontraktorzy
      // okresowi nie mają wspólnego budżetu, więc przy tym filtrze odpadają.
      // „Wymaga decyzji" dotyczy wyłącznie osób na zamówieniach MD/kosztowych.
      filters.nearBudget || pill === "decision"
        ? []
        : filterAndSortContractors(
            contractors.filter((contractor) =>
              contractorMatchesPill(contractor, pill as UnifiedOrderPill),
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
      }))
        .filter((section) => typeFilter === "all" || section.type === typeFilter)
        .filter((section) => section.items.length > 0),
    [
      filters.sort,
      legacyNullOrderType,
      suggestedOrderType,
      typeFilter,
      visibleContractors,
      visibleGroups,
    ],
  );
  const resultCount = sections.reduce((sum, section) => sum + section.items.length, 0);
  const tableSections: OrdersTableSection[] = useMemo(
    () =>
      sections.map((section) => ({
        type: section.type,
        itemCount: section.items.length,
        rows: buildSectionRows(section.items, {
          expandedEnded,
          collapsedEnded,
          matchesSearch: search.trim()
            ? (name) => consultantMatchesQuery(name, search)
            : undefined,
        }),
      })),
    [collapsedEnded, expandedEnded, search, sections],
  );
  const rowKeys = useMemo(() => selectableKeys(tableSections), [tableSections]);

  // ── Zaznaczenie i panel (wersja B, 29.09.2026) ─────────────────────────────
  // Otwarty panel żyje w adresie: `?group=` (zamówienie), `?order=` (linia MD
  // albo zamówienie okresowe) i `?contract=` (kontraktor bez zamówienia). To te
  // same parametry, które niosą linki z powiadomień i alertów DL zapisane
  // w bazie — link otwiera więc od razu właściwy panel.
  const focusServed = useRef<string | null>(null);
  const [contractorFocus, setContractorFocus] =
    useState<ContractorOrderFocus | null>(null);
  const clearContractorFocus = useCallback(() => setContractorFocus(null), []);

  const writeSelectionToUrl = useCallback((next: OrderSelection | null) => {
    const patch: Record<string, string | null> = { group: null, order: null, contract: null };
    let key: string | null = null;
    if (next?.kind === "group") {
      patch.group = String(next.groupId);
      key = `group:${next.groupId}`;
    } else if (next?.kind === "line") {
      patch.order = String(next.lineId);
      key = `order:${next.lineId}`;
    } else if (next?.kind === "contractor") {
      patch.contract = String(next.contractId);
      key = `contract:${next.contractId}`;
    }
    // Nasz własny zapis w adresie nie jest „nowym linkiem" do obsłużenia.
    focusServed.current = key;
    writeUrlParams(patch);
  }, []);

  const select = useCallback(
    (next: OrderSelection | null, tab: LinePanelTab | null = null) => {
      setSelection(next);
      setLineTab(tab);
      writeSelectionToUrl(next);
    },
    [writeSelectionToUrl],
  );
  const closePanel = useCallback(() => select(null), [select]);
  const selectKey = useCallback(
    (key: string, tab?: LinePanelTab) => {
      const next = selectionFromKey(key, tableSections);
      if (next) select(next, tab ?? null);
    },
    [select, tableSections],
  );

  /** Cel poza bieżącym filtrem — zdejmij filtry, żeby wiersz był widoczny. */
  const revealAll = useCallback(() => {
    setPill("all");
    setTypeFilter("all");
    setSearch("");
    setFilters({ ...DEFAULT_ORDER_LIST_FILTERS });
  }, []);
  const scrollRowIntoView = useCallback((anchorId: string) => {
    window.requestAnimationFrame(() => {
      document.getElementById(anchorId)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }, []);
  const selectGroupById = useCallback(
    (groupId: number) => {
      if (!rowKeys.includes(`g:${groupId}`)) revealAll();
      select({ kind: "group", groupId });
      scrollRowIntoView(`order-group-anchor-${groupId}`);
    },
    [revealAll, rowKeys, scrollRowIntoView, select],
  );
  const selectLineById = useCallback(
    (groupId: number, lineId: number) => {
      const found = findLine(groups, lineId);
      if (!found) return;
      if (!rowKeys.includes(`l:${lineId}`)) {
        revealAll();
        setExpandedEnded((previous) => new Set(previous).add(found.group.id));
      }
      select({ kind: "line", groupId: found.group.id ?? groupId, lineId });
      scrollRowIntoView(`order-line-${lineId}`);
    },
    [groups, revealAll, rowKeys, scrollRowIntoView, select],
  );

  useRowNavigation({
    keys: rowKeys,
    activeKey: selection ? selectionKey(selection) : null,
    onChange: (key) => selectKey(key),
    containerRef: tableRef,
  });

  // Link z powiadomienia (`?order=` / `?group=` / `?contract=`). Czeka na obie
  // listy, zdejmuje filtry (cel mógłby być schowany pod pigułką), otwiera
  // panel i przewija do wiersza. Raz na wartość parametru — odświeżenie listy
  // nie przewija ekranu drugi raz. Cel, którego nie ma, dostaje komunikat.
  useEffect(() => {
    const key = focusGroupId
      ? `group:${focusGroupId}`
      : focusOrderId
        ? `order:${focusOrderId}`
        : focusContractId
          ? `contract:${focusContractId}`
          : null;
    if (!key) {
      focusServed.current = null;
      return;
    }
    if (!query.isSuccess || !contractorQuery.isSuccess) return;
    if (focusServed.current === key) return;
    focusServed.current = key;
    if (focusContractId && !focusGroupId && !focusOrderId) {
      const contractor = contractors.find((item) => item.contract_id === focusContractId);
      if (!contractor) {
        showToast("Zamówienie nie jest już widoczne na liście tego klienta.", "error");
        onFocusHandled?.();
        return;
      }
      revealAll();
      setSelection({ kind: "contractor", contractId: focusContractId });
      scrollRowIntoView(`contractor-row-${focusContractId}`);
      return;
    }
    const target = resolveOrderFocus(groups, contractors, {
      orderId: focusOrderId,
      groupId: focusGroupId,
    });
    if (target === null) {
      showToast("Zamówienie nie jest już widoczne na liście tego klienta.", "error");
      onFocusHandled?.();
      return;
    }
    revealAll();
    if (target.kind === "group") {
      if (target.lineId != null) {
        const found = findLine(groups, target.lineId);
        if (found) setExpandedEnded((previous) => new Set(previous).add(found.group.id));
        setSelection({ kind: "line", groupId: target.groupId, lineId: target.lineId });
        scrollRowIntoView(`order-line-${target.lineId}`);
      } else {
        setSelection({ kind: "group", groupId: target.groupId });
        scrollRowIntoView(`order-group-anchor-${target.groupId}`);
      }
    } else {
      setSelection({ kind: "contractor", contractId: target.contractId });
      setContractorFocus((previous) => ({
        contractId: target.contractId,
        orderId: target.orderId,
        openEditor: target.isDraft,
        nonce: (previous?.nonce ?? 0) + 1,
      }));
      scrollRowIntoView(`contractor-row-${target.contractId}`);
    }
  }, [
    focusGroupId,
    focusOrderId,
    focusContractId,
    query.isSuccess,
    contractorQuery.isSuccess,
    groups,
    contractors,
    showToast,
    onFocusHandled,
    revealAll,
    scrollRowIntoView,
  ]);

  // Zaznaczony obiekt zniknął z listy (usunięty, anulowany i schowany) —
  // zamknij panel zamiast pokazywać nieaktualne dane.
  const selectedGroup =
    selection?.kind === "group" ? findGroup(groups, selection.groupId) : null;
  const selectedLine = selection?.kind === "line" ? findLine(groups, selection.lineId) : null;
  const selectedContractor =
    selection?.kind === "contractor"
      ? (contractors.find((item) => item.contract_id === selection.contractId) ?? null)
      : null;
  const selectionMissing =
    selection !== null &&
    query.isSuccess &&
    contractorQuery.isSuccess &&
    !selectedGroup &&
    !selectedLine &&
    !selectedContractor;
  useEffect(() => {
    if (selectionMissing) closePanel();
  }, [selectionMissing, closePanel]);

  async function exportVisible() {
    setExporting(true);
    try {
      const visibleOrderIds = new Set(
        visibleLegacyOrderIds(visibleContractors, search),
      );
      type ExportItem =
        { kind: "group"; id: number } | { kind: "order"; id: number };
      const items: ExportItem[] = ORDER_TYPE_ORDER.filter(
        (type) => typeFilter === "all" || type === typeFilter,
      ).flatMap<ExportItem>((type) =>
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

  // Te same callbacki, które wołała dawna karta zamówienia — panele
  // otwierają TE SAME okna, hostowane niżej w tym komponencie.
  const groupActions: OrderGroupActions & {
    onReplaceLine: (group: OrderGroupRead, line: OrderLineRead) => void;
    onKeepHistory: (group: OrderGroupRead, line: OrderLineRead) => void;
    onSwapLine: (group: OrderGroupRead, line: OrderLineRead) => void;
    onResolveOffboarding: (group: OrderGroupRead, line: OrderLineRead) => void;
    onDeleteLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  } = {
    onAddConsultant: (selected) => {
      setFormError(null);
      setLineModal({ open: true, group: selected, line: null, replaces: null });
    },
    onReplaceLine: (selected, line) => {
      setFormError(null);
      // Pula per osoba z pozostałymi MD: nowa osoba je przejmuje (B1).
      // Kosztowe i wspólna pula nie mają puli osoby — zwykłe dodanie.
      if (!selected.is_cost_based && !usesSharedMdPool(selected) && line.takeover_source) {
        setReplaceModal({ group: selected, line });
        return;
      }
      setLineModal({ open: true, group: selected, line: null, replaces: line });
    },
    onKeepHistory: (selected, line) => keepHistory.mutate({ groupId: selected.id, lineId: line.id }),
    onEditGroup: (selected) => {
      setFormError(null);
      setGroupModal({ open: true, group: selected });
    },
    onEditLine: (selected, line) => {
      setFormError(null);
      setLineModal({ open: true, group: selected, line, replaces: null });
    },
    onSwapLine: (selected, line) => {
      setFormError(null);
      setSwapModal({ open: true, group: selected, line });
    },
    onResolveOffboarding: (selected, line) => {
      setFormError(null);
      setOffboardingModal({ open: true, group: selected, line });
    },
    // Audyt 22.09 r2 (FE-N02): dialog ze skutkami liczonymi przez serwer
    // zamiast `window.confirm` — usunięcie linii zabiera jej krok stawki klienta.
    onDeleteLine: (selected, line) => setDeleteLineTarget({ group: selected, line }),
    onDeleteGroup: (selected) => setDeleteGroupTarget(selected),
    onCloseGroup: (selected) => {
      setFormError(null);
      setEndModal({ open: true, group: selected });
    },
    onReopenGroup: (selected) => reopenGroup.mutate(selected.id),
    onCancelGroup: (selected) => {
      setCancelError(null);
      setCancelGroupTarget(selected);
    },
    onRestoreGroup: (selected) => restoreGroup.mutate(selected.id),
    onExtendGroup: (selected) => {
      setFormError(null);
      setExtendModal({ open: true, group: selected });
    },
  };

  function parentOf(groupId: number): OrderGroupRead | null {
    const visit = (list: readonly OrderGroupRead[]): OrderGroupRead | null => {
      for (const group of list) {
        if (group.future_orders.some((future) => future.id === groupId)) return group;
        const nested = visit(group.future_orders);
        if (nested) return nested;
      }
      return null;
    };
    return visit(groups);
  }

  let panel: React.ReactNode = null;
  if (selectedGroup) {
    panel = (
      <OrderGroupPanel
        key={`g-${selectedGroup.id}`}
        clientId={clientId}
        group={selectedGroup}
        parent={parentOf(selectedGroup.id)}
        canManage={canManage}
        canManageLifecycle={canLifecycle}
        searchQuery={search}
        onClose={closePanel}
        onSelectLine={selectLineById}
        onSelectGroup={selectGroupById}
        {...groupActions}
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
        canManageLifecycle={canLifecycle}
        initialTab={lineTab}
        onClose={closePanel}
        onEditLine={groupActions.onEditLine}
        onSwapLine={groupActions.onSwapLine}
        onDeleteLine={groupActions.onDeleteLine}
        onDecide={(group, line) => setDecisionTarget({ group, line })}
        onSelectLine={selectLineById}
        onSelectGroup={selectGroupById}
      />
    );
  } else if (selectedContractor && contractorQuery.data) {
    panel = (
      <ContractorOrderPanel
        key={`c-${selectedContractor.contract_id}`}
        clientId={clientId}
        contractor={selectedContractor}
        canViewFinance={canViewFinance}
        canManageFinance={contractorQuery.data.can_manage_finance}
        canManageOrders={contractorQuery.data.can_manage_finance}
        suggestedOrderType={suggestedOrderType}
        legacyNullOrderType={legacyNullOrderType}
        allowedOrderTypes={allowedOrderTypes}
        searching={search.trim().length > 0}
        focusOrder={
          contractorFocus?.contractId === selectedContractor.contract_id ? contractorFocus : null
        }
        onFocusOrderServed={clearContractorFocus}
        onAssignToOrder={
          isEzdrowieClient(clientId) && canManage
            ? (contractor, openCompleteOrder) => {
                setFormError(null);
                setAssignModal({ contractor, openCompleteOrder });
              }
            : undefined
        }
        onClose={closePanel}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Nagłówek to dwa rzędy (restyle 02.10.2026): pigułki z akcjami oraz
          wyszukiwarka z filtrami. Tytuł i podpowiedź zostają dla czytników
          ekranu — zakładka nazywa się „Zamówienia”, a wiersz sam mówi, że
          jest klikalny. */}
      <h2 className="sr-only">Zamówienia klienta</h2>
      <p className="sr-only">Kliknij wiersz, żeby zobaczyć szczegóły i akcje.</p>

      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        {/* Liczniki liczone z POBRANEJ listy, nie z osobnego zapytania — kafel
            będący sumą innych liczb niż widoczne pod nim jest niemożliwy do
            zweryfikowania wzrokiem. Renderujemy je dopiero przy `isSuccess`,
            żeby „(0)" nie udawało wyniku, zanim cokolwiek wiadomo. */}
        {query.isSuccess && contractorQuery.isSuccess ? (
          <div
            className="flex min-w-0 flex-[1_1_28rem] flex-wrap items-center gap-1.5"
            data-help="client.orders.pills"
          >
            {PILLS.filter((entry) => entry.key !== "decision" || counts.decision > 0 || pill === "decision").map((entry) => {
              const count = counts[entry.key];
              const selected = pill === entry.key;
              return (
                <button
                  key={entry.key}
                  type="button"
                  onClick={() => setPill(entry.key)}
                  aria-pressed={selected}
                  title={entry.title}
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium transition-colors pointer-coarse:min-h-10",
                    selected
                      ? "border-foreground bg-foreground text-background"
                      : entry.key === "decision"
                        ? "border-transparent bg-destructive-muted text-destructive-muted-foreground hover:bg-destructive-muted/80"
                        : count === 0
                          ? // Pusta pigułka zostaje klikalna, ale nie konkuruje z resztą.
                            "border-border/60 bg-transparent text-muted-foreground/70 hover:text-foreground"
                          : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {/* Nazwa dostępna przycisku to nadal „Aktywne (1)” — nawiasy
                      są w tekście, tylko niewidoczne (liczba stoi pogrubiona). */}
                  {entry.label}{" "}
                  <span className="sr-only">(</span>
                  <span
                    className={cn(
                      "tabular-nums",
                      selected || entry.key === "decision"
                        ? "font-semibold"
                        : count === 0
                          ? "font-normal"
                          : "font-semibold text-foreground",
                    )}
                  >
                    {count}
                  </span>
                  <span className="sr-only">)</span>
                </button>
              );
            })}
          </div>
        ) : null}
        <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">
          {query.isSuccess && contractorQuery.isSuccess && canExport ? (
            <OrderExportButton exporting={exporting} disabled={resultCount === 0} onExport={exportVisible} />
          ) : null}
          {canManage ? (
            <Button
              type="button"
              size="sm"
              disabled={!query.isSuccess || !contractorQuery.isSuccess}
              onClick={() => {
                // Świeże „Nowe zamówienie" — bez roboczego stanu porzuconego okna.
                setCarriedCommon(null);
                setCarriedPeriodicDraft(null);
                openNewOrderForm(suggestedOrderType);
              }}
              data-help="client.orders.new"
            >
              <Plus className="h-4 w-4" aria-hidden="true" /> Nowe zamówienie
            </Button>
          ) : null}
        </div>
      </div>

      {query.isSuccess && contractorQuery.isSuccess ? (
        <OrderListControls
          search={search}
          onSearchChange={setSearch}
          filters={filters}
          onFiltersChange={setFilters}
          resultCount={resultCount}
          extraControls={
            <select
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value as OrderType | "all")}
              aria-label="Typ zamówienia"
              className="h-8 shrink-0 rounded-md border border-border bg-card px-2 text-xs text-foreground pointer-coarse:h-10"
            >
              {TYPE_FILTERS.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {entry.label}
                </option>
              ))}
            </select>
          }
          // `isSuccess`, nie `!isLoading && !isError` — w przerwie między
          // ponowieniami dane są puste, a licznik pokazywałby „0 pozycji”,
          // czyli tę samą nieprawdę co pusty stan pod spodem.
          trailing={countPl(
            groups.length + contractors.length,
            "pozycja na liście",
            "pozycje na liście",
            "pozycji na liście",
          )}
        />
      ) : null}

      {query.isSuccess &&
      contractorQuery.isSuccess &&
      // Import CSV zostaje wyłącznie dla administratora (także jako rola
      // dodatkowa — stąd `hasRole`, nie porównanie `user.role`).
      hasRole(user, "admin") &&
      // Klient z polityki Nordei liczony na serwerze (S13) — nazwa klienta
      // nie jest regułą (Traffit ją nadpisuje, „Nordea" bywa w kilku nazwach).
      contractorQuery.data.nordea_order_import_enabled === true ? (
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
        <div ref={tableRef}>
          <ListDetailLayout
            panelLabel="Szczegóły zamówienia"
            onClose={closePanel}
            panel={panel}
            list={
              <OrdersTable
                sections={tableSections}
                selectedKey={selection ? selectionKey(selection) : null}
                onSelect={selectKey}
                onToggleEnded={(groupId, open) => {
                  setExpandedEnded((previous) => {
                    const next = new Set(previous);
                    if (open) next.add(groupId);
                    else next.delete(groupId);
                    return next;
                  });
                  setCollapsedEnded((previous) => {
                    const next = new Set(previous);
                    if (open) next.delete(groupId);
                    else next.add(groupId);
                    return next;
                  });
                }}
                searchQuery={search}
                canDecide={canManage || canLifecycle}
                canManage={canManage}
                canViewFinance={canViewFinance}
              />
            }
          />
        </div>
      )}

      <OrderGroupFormModal
        open={groupModal.open}
        onOpenChange={(open) => {
          setGroupModal((s) => ({ ...s, open }));
          // W trakcie zapisu dokument z maila czeka na wynik (`settleMailSource`)
          // — zamknięcie okna Esc-em nie może go wtedy odpiąć.
          if (!open && !saveGroup.isPending) releaseMailSource();
        }}
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
        onOrderTypeChange={(orderType, file, orderNumber, common) => {
          // Okno okresowe nie zna dokumentów z maila — dokument zostaje w kolejce.
          if (orderType === "periodic") releaseMailSource();
          setCarriedCommon(common ?? null);
          openNewOrderForm(orderType, file, orderNumber);
        }}
        allowedOrderTypes={allowedOrderTypes}
        initialFile={carriedFile}
        initialOrderNumber={carriedOrderNumber}
        initialCommon={carriedCommon}
        autoReadFile={mailSource?.file ?? null}
        sourceNotice={
          mailSource
            ? `PDF z kolejki zamówień z maila (dokument #${mailSource.docId}). ` +
              "Po zapisaniu zamówienia dokument zejdzie z kolejki."
            : null
        }
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
          defaultRateUnit={defaultRateUnit}
          orderType={newOrderType}
          onOrderTypeChange={(orderType, file, orderNumber, draft) => {
            setCarriedPeriodicDraft(draft ?? null);
            setCarriedCommon(draft ? commonFieldsOfPeriodic(draft) : null);
            openNewOrderForm(orderType, file, orderNumber);
          }}
          allowedOrderTypes={allowedOrderTypes}
          initialFile={carriedFile}
          initialOrderNumber={carriedOrderNumber}
          initialDraft={periodicDraftForReturn(carriedPeriodicDraft, carriedCommon)}
          onClose={() => setStandardOrderModalOpen(false)}
          onCreated={async () => {
            await invalidate();
            setStandardOrderModalOpen(false);
          }}
        />
      ) : null}

      <ConsultantLineModal
        open={lineModal.open}
        onOpenChange={(open) => setLineModal((s) => ({ ...s, open }))}
        clientId={clientId}
        group={lineModal.group}
        line={lineModal.line}
        replaces={lineModal.replaces ?? null}
        submitting={saveLine.isPending || adjustRemaining.isPending}
        error={formError}
        onSubmit={(values) => saveLine.mutate(values)}
        amountsOnly={amountsOnly}
        onAdjustRemaining={
          lineModal.line && !amountsOnly
            ? (md) => adjustRemaining.mutate(md)
            : undefined
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
        submitting={resolveOffboarding.isPending || takeover.isPending}
        error={formError}
        onSubmit={(values) => resolveOffboarding.mutate(values)}
        newPeople={draftPeople}
        onTakeover={(values) => {
          const group = offboardingModal.group;
          if (group) takeover.mutate({ groupId: group.id, values });
        }}
      />

      <AssignToOrderModal
        open={assignModal !== null}
        onOpenChange={(open) => {
          if (!open) setAssignModal(null);
        }}
        contractor={assignModal?.contractor ?? null}
        groups={groups}
        submitting={joinOrder.isPending || takeover.isPending}
        error={formError}
        onJoin={(groupId, values) => joinOrder.mutate({ groupId, values })}
        onTakeover={(groupId, values) => takeover.mutate({ groupId, values })}
        onNewOrder={() => assignModal?.openCompleteOrder()}
      />

      <ReplaceWithTakeoverModal
        open={replaceModal !== null}
        onOpenChange={(open) => {
          if (!open) setReplaceModal(null);
        }}
        clientId={clientId}
        group={replaceModal?.group ?? null}
        line={replaceModal?.line ?? null}
        submitting={takeover.isPending}
        error={formError}
        onSubmit={(values) => {
          const group = replaceModal?.group;
          if (group) takeover.mutate({ groupId: group.id, values });
        }}
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

      {deleteLineTarget ? (
        <DeleteOrderDialog
          clientId={clientId}
          orderId={deleteLineTarget.line.id}
          title={deleteLineTarget.group.order_number}
          context="group_line"
          heading={`Usunąć konsultanta ${deleteLineTarget.line.consultant_name} z zamówienia nr ${deleteLineTarget.group.order_number}?`}
          confirmLabel="Usuń konsultanta"
          pending={removeLine.isPending}
          onConfirm={() =>
            removeLine.mutate({
              groupId: deleteLineTarget.group.id,
              lineId: deleteLineTarget.line.id,
            })
          }
          onClose={() => setDeleteLineTarget(null)}
        />
      ) : null}

      {deleteGroupTarget ? (
        <DeleteOrderGroupDialog
          clientId={clientId}
          orderNumber={deleteGroupTarget.order_number}
          lines={deleteGroupTarget.lines}
          hasFile={deleteGroupTarget.has_file}
          pending={removeGroup.isPending}
          onConfirm={() => removeGroup.mutate(deleteGroupTarget.id)}
          onClose={() => setDeleteGroupTarget(null)}
        />
      ) : null}

      <EndedLineDecisionDialog
        group={decisionTarget?.group ?? null}
        line={decisionTarget?.line ?? null}
        onClose={() => setDecisionTarget(null)}
        canManage={canManage}
        canManageLifecycle={canLifecycle}
        onKeepHistory={groupActions.onKeepHistory}
        onReplaceLine={groupActions.onReplaceLine}
        onDeleteLine={groupActions.onDeleteLine}
        onResolveOffboarding={groupActions.onResolveOffboarding}
      />

      <CancelOrderGroupDialog
        key={cancelGroupTarget?.id ?? "none"}
        group={cancelGroupTarget}
        pending={cancelGroup.isPending}
        error={cancelError}
        onConfirm={(reason) =>
          cancelGroupTarget &&
          cancelGroup.mutate({ groupId: cancelGroupTarget.id, reason })
        }
        onClose={() => {
          setCancelGroupTarget(null);
          setCancelError(null);
        }}
      />
    </div>
  );
}
