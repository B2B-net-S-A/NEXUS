"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";
import {
  ContractorOrderCards,
  type ContractorOrderFocus,
} from "@/components/OrdersAndContractsTab";
import { useToast } from "@/components/Toast";
import { useClientDefaultRateUnit } from "@/hooks/useClientDefaultRateUnit";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { orderMailApi } from "@/lib/api/orderMail";
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
import {
  canViewClientFinance,
  canManageMultiConsultantOrders,
  canManageOrderLifecycle,
  hasRole,
  useAuthStore,
} from "@/store/auth";

import {
  ConsultantLineModal,
  type LineFormValues,
} from "./ConsultantLineModal";
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
  /** Cel obsłużony (albo niewidoczny) — strona zdejmuje parametry z adresu. */
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
  clientName = "",
  legacyNullOrderType = "periodic",
  orderMailDocId = null,
  onOrderMailDocDone,
  focusOrderId = null,
  focusGroupId = null,
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
  const canLifecycle = canManageOrderLifecycle(user);
  const canExport =
    !hasRole(user, "talent_community_manager") ||
    hasRole(user, "admin", "delivery_lead", "finance");
  const allowedOrderTypes = ALL_ORDER_TYPES;

  const [pill, setPill] = useState<UnifiedOrderPill>("all");
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
  const [mailSource, setMailSource] = useState<MailSource | null>(null);
  // Przejście z wpisu „transfer_md" do zamówienia powiązanego. Żądanie leci do
  // WSZYSTKICH kart, bo cel bywa zagnieżdżony w przyszłych zamówieniach innej
  // karty — tylko ona wie, że go zawiera, i tylko ona umie się rozwinąć.
  const [focusRequest, setFocusRequest] =
    useState<OrderGroupFocusRequest | null>(null);

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
  // Rodziny przedłużeń liczone z PEŁNEJ listy: pigułka i filtr dostają już
  // przefiltrowane grupy, a następca zamówienia może w tym podzbiorze nie być.
  const groupFamilies = useMemo(() => buildOrderGroupFamilies(groups), [groups]);
  const counts = useMemo(() => {
    const byStatus = {} as Record<UnifiedOrderPill, number>;
    for (const entry of PILLS) {
      byStatus[entry.key] =
        groups.filter((group) =>
          orderGroupMatchesPill(group, entry.key, undefined, groupFamilies),
        ).length +
        contractors.filter((contractor) =>
          contractorMatchesPill(contractor, entry.key),
        ).length;
    }
    return byStatus;
  }, [contractors, groups, groupFamilies]);
  const visibleGroups = useMemo(
    () =>
      filterAndSortOrderGroups(
        groups.filter((group) =>
          orderGroupMatchesPill(group, pill, undefined, groupFamilies),
        ),
        search,
        filters,
        undefined,
        groupFamilies,
      ),
    [filters, groups, groupFamilies, pill, search],
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

  // Deep link z panelu „Moi klienci" (`?order=` / `?group=`). Czeka na obie
  // listy, zdejmuje filtry (cel mógłby być schowany pod pigułką albo
  // wyszukiwaniem), a potem przewija do grupy (istniejący mechanizm
  // `focusRequest`) albo do karty kontraktora. Raz na wartość parametru —
  // odświeżenie listy nie przewija ekranu drugi raz. Cel, którego nie ma,
  // dostaje komunikat zamiast cichego „nic się nie stało".
  const [contractorFocus, setContractorFocus] =
    useState<ContractorOrderFocus | null>(null);
  const focusServed = useRef<string | null>(null);
  const clearContractorFocus = useCallback(() => setContractorFocus(null), []);
  useEffect(() => {
    const key = focusGroupId ? `group:${focusGroupId}` : focusOrderId ? `order:${focusOrderId}` : null;
    if (!key) {
      focusServed.current = null;
      return;
    }
    if (!query.isSuccess || !contractorQuery.isSuccess) return;
    if (focusServed.current === key) return;
    focusServed.current = key;
    const target = resolveOrderFocus(groups, contractors, {
      orderId: focusOrderId,
      groupId: focusGroupId,
    });
    if (target === null) {
      showToast("Zamówienie nie jest już widoczne na liście tego klienta.", "error");
    } else {
      setPill("all");
      setSearch("");
      setFilters({ ...DEFAULT_ORDER_LIST_FILTERS });
      if (target.kind === "group") {
        setFocusRequest((previous) => ({
          groupId: target.groupId,
          nonce: (previous?.nonce ?? 0) + 1,
        }));
      } else {
        setContractorFocus((previous) => ({
          contractId: target.contractId,
          orderId: target.orderId,
          openEditor: target.isDraft,
          nonce: (previous?.nonce ?? 0) + 1,
        }));
      }
    }
    onFocusHandled?.();
  }, [
    focusGroupId,
    focusOrderId,
    query.isSuccess,
    contractorQuery.isSuccess,
    groups,
    contractors,
    showToast,
    onFocusHandled,
  ]);

  async function exportVisible() {
    setExporting(true);
    try {
      const visibleOrderIds = new Set(
        visibleLegacyOrderIds(visibleContractors, search),
      );
      type ExportItem =
        { kind: "group"; id: number } | { kind: "order"; id: number };
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
          setLineModal({ open: true, group: selected, line: null, replaces: null });
        }}
        onReplaceLine={(selected, line) => {
          setFormError(null);
          setLineModal({ open: true, group: selected, line: null, replaces: line });
        }}
        onKeepHistory={(selected, line) =>
          keepHistory.mutate({ groupId: selected.id, lineId: line.id })
        }
        onEditGroup={(selected) => {
          setFormError(null);
          setGroupModal({ open: true, group: selected });
        }}
        onEditLine={(selected, line) => {
          setFormError(null);
          setLineModal({ open: true, group: selected, line, replaces: null });
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
                `z zamówienia nr ${selected.order_number}? Usunięte zostanie tylko ` +
                `jego miejsce na tym zamówieniu — nie powstanie nowe zamówienie, ` +
                `a umowa i inne zamówienia tej osoby się nie zmienią.`,
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
                    focusOrder={
                      contractorFocus?.contractId === item.contractor.contract_id
                        ? contractorFocus
                        : null
                    }
                    onFocusOrderServed={clearContractorFocus}
                  />
                ),
              )}
            </section>
          ))}
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
        onOrderTypeChange={(orderType, file, orderNumber) => {
          // Okno okresowe nie zna dokumentów z maila — dokument zostaje w kolejce.
          if (orderType === "periodic") releaseMailSource();
          openNewOrderForm(orderType, file, orderNumber);
        }}
        allowedOrderTypes={allowedOrderTypes}
        initialFile={carriedFile}
        initialOrderNumber={carriedOrderNumber}
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
          onOrderTypeChange={openNewOrderForm}
          allowedOrderTypes={allowedOrderTypes}
          initialFile={carriedFile}
          initialOrderNumber={carriedOrderNumber}
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
