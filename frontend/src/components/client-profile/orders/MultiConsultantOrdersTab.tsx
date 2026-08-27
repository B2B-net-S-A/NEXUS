"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";
import { OrdersAndContractsTab } from "@/components/OrdersAndContractsTab";
import { useToast } from "@/components/Toast";
import {
  orderGroupsApi,
  type OrderGroupExtendInput,
  type OrderGroupInput,
  type OrderGroupRead,
  type OrderGroupStatus,
  type OrderLineRead,
  type OrderType,
  type SwapConsultantInput,
} from "@/lib/api/orderGroups";
import { countPl } from "@/lib/plural-pl";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  filterAndSortOrderGroups,
  flattenOrderGroupIds,
  type OrderListFilters,
} from "@/lib/client-order-list";
import {
  downloadBlob,
  postAuthenticatedDownload,
} from "@/lib/authenticated-files";
import {
  canManageMultiConsultantOrders,
  canManageOrderLifecycle,
  useAuthStore,
} from "@/store/auth";

import { ConsultantLineModal, type LineFormValues } from "./ConsultantLineModal";
import { DraftOrdersSection } from "./DraftOrdersSection";
import { EndOrderGroupModal } from "./EndOrderGroupModal";
import { ExtendOrderGroupModal } from "./ExtendOrderGroupModal";
import { OrderGroupCard, type OrderGroupFocusRequest } from "./OrderGroupCard";
import { OrderGroupFormModal } from "./OrderGroupFormModal";
import { OrderListControls } from "./OrderListControls";
import { SwapConsultantModal } from "./SwapConsultantModal";

/** Wyciąga czytelny komunikat z odpowiedzi API (detail bywa stringiem lub obiektem). */
function apiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    const code = (detail as { code?: string }).code;
    if (code === "finance_fields_forbidden") {
      return (
        "Stawki linii może ustawiać administrator albo Delivery Lead " +
        "przypisany do tego klienta."
      );
    }
  }
  return fallback;
}

/** Wynik zapisu zamówienia razem z osobnym, drugim wywołaniem — wgraniem PDF-a.
 *
 *  `fileError` niepuste znaczy: zamówienie JEST zapisane, plik nie wszedł.
 *  Rozdzielenie tych dwóch faktów jest tu istotne, bo mylenie ich prowadzi
 *  wprost do duplikatu zamówienia (patrz `attachFile`). */
type GroupSaveResult = { saved: OrderGroupRead; fileError: string | null };

type MainOrderGroupStatus = Exclude<OrderGroupStatus, "scheduled">;
type PillKey = "all" | MainOrderGroupStatus | "ending_30d" | "draft";

// Zestaw bazowy (Polkomtel — klient kosztowy — zostaje przy nim bez zmian,
// wymóg ticketu). Klienci MD (BIK/BNP) dostają dodatkowo „Kończące się 30d"
// i „Draft (do uzupełnienia)" — ten sam słownik pigułek co widok jednoosobowy.
// „Wyczerpane" zostaje także u nich: budżety MD wyczerpują się właśnie tam,
// a zdjęcie pigułki ukryłoby istniejące grupy w tym stanie.
const BASE_PILLS: Array<{ key: PillKey; label: string }> = [
  { key: "all", label: "Wszystkie" },
  { key: "active", label: "Aktywne" },
  { key: "completed", label: "Zakończeni" },
  { key: "exhausted", label: "Wyczerpane" },
];

const MD_CLIENT_PILLS: Array<{ key: PillKey; label: string }> = [
  { key: "all", label: "Wszystkie" },
  { key: "active", label: "Aktywne" },
  { key: "ending_30d", label: "⚠️ Kończące się 30d" },
  { key: "draft", label: "📝 Draft (do uzupełnienia)" },
  { key: "completed", label: "Zakończeni" },
  { key: "exhausted", label: "Wyczerpane" },
];

// Cyfrowy Polsat i Lotte Wedel pokazują standardowe zamówienia w legacy
// rejestrze. Powtarzanie tu pustej pigułki Draft sugerowałoby, że część
// standardowych zamówień zniknęła; grupy kosztowe/MD zachowują natomiast
// przydatny filtr kończących się zamówień.
const MIXED_GROUP_PILLS = MD_CLIENT_PILLS.filter(
  (entry) => entry.key !== "draft",
);

/** Dni do końca zamówienia liczone datami kalendarzowymi (bez stref). */
function daysToEnd(end: string | null): number | null {
  if (!end) return null;
  const endDate = new Date(`${end.slice(0, 10)}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((endDate.getTime() - today.getTime()) / 86_400_000);
}

/** Aktywna grupa kończąca się w ciągu 30 dni — lustro `expiring_30d`
 *  z widoku jednoosobowego (przedział [0, 30], bez już zakończonych). */
function isEndingSoon(group: OrderGroupRead): boolean {
  if (group.status !== "active") return false;
  const days = daysToEnd(group.end_date);
  return days !== null && days >= 0 && days <= 30;
}

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
  /** CP/Lotte Wedel: obok grup kosztowych/MD zachowują legacy zamówienia
   *  standardowe i dostają jedno, wspólne wejście tworzenia. */
  mixedOrderTypesEnabled?: boolean;
}

/**
 * Wspólna zakładka „Zamówienia" dla każdego klienta. Zamówienia okresowe i
 * samodzielne drafty zachowują dotychczasowy rejestr kontraktorów, a kosztowe
 * oraz MD korzystają z grup ze wspólnym budżetem.
 */
export function MultiConsultantOrdersTab({
  clientId,
  clientName = "",
  costOrdersEnabled = false,
  mixedOrderTypesEnabled = false,
}: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((s) => s.user);
  const canManage = canManageMultiConsultantOrders(user);
  const canLifecycle = canManageOrderLifecycle(user);

  const [pill, setPill] = useState<PillKey>("all");
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

  function openNewOrderForm(orderType: OrderType) {
    setFormError(null);
    setNewOrderType(orderType);
    if (orderType === "periodic") {
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
  const draftOrders = useMemo(
    () => query.data?.draft_orders ?? [],
    [query.data],
  );
  const pills = mixedOrderTypesEnabled
    ? MIXED_GROUP_PILLS
    : costOrdersEnabled
      ? BASE_PILLS
      : MD_CLIENT_PILLS;
  const counts = useMemo(() => {
    const byStatus: Record<PillKey, number> = {
      all: groups.length,
      active: 0,
      completed: 0,
      exhausted: 0,
      // „Kończące się" jest PODZBIOREM „Aktywne" — suma pigułek świadomie
      // nie równa się „Wszystkie" (ta sama reguła co w widoku jednoosobowym).
      ending_30d: groups.filter(isEndingSoon).length,
      draft: draftOrders.length,
    };
    for (const group of groups) {
      if (group.status !== "scheduled") byStatus[group.status] += 1;
    }
    return byStatus;
  }, [groups, draftOrders]);
  const visible = useMemo(() => {
    if (pill === "draft") return [];
    const byPill =
      pill === "all"
        ? groups
        : pill === "ending_30d"
          ? groups.filter(isEndingSoon)
          : groups.filter((group) => group.status === pill);
    return filterAndSortOrderGroups(byPill, search, filters);
  }, [groups, pill, search, filters]);

  async function exportVisible() {
    setExporting(true);
    try {
      const result = await postAuthenticatedDownload(
        `/api/clients/${clientId}/order-groups/export`,
        { group_ids: flattenOrderGroupIds(visible) },
      );
      downloadBlob(result.blob, result.filename ?? "Zamowienia.xlsx");
      showToast("Pobrano zamówienia do Excela", "success");
    } catch {
      showToast("Nie udało się przygotować pliku Excel.", "error");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-foreground">
            Zamówienia klienta
          </h2>
          <p className="text-xs text-muted-foreground">
            {mixedOrderTypesEnabled
              ? "Zamówienia okresowe, kosztowe i rozliczane wspólną pulą MD."
              : "Jedno zamówienie może obejmować wielu konsultantów, każdego z własnym budżetem MD."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* `isSuccess`, nie `!isLoading && !isError` — w przerwie między
              ponowieniami dane są puste, a licznik pokazywałby „0 zamówienia",
              czyli tę samą nieprawdę co pusty stan pod spodem. */}
          {query.isSuccess ? (
            <p className="text-xs text-muted-foreground">
              {mixedOrderTypesEnabled ? "Grupy kosztowe/MD: " : ""}
              {countPl(
                query.data.total_groups,
                "zamówienie",
                "zamówienia",
                "zamówień",
              )}{" "}
              ·{" "}
              {countPl(
                query.data.total_consultants,
                "konsultant",
                "konsultanci",
                "konsultantów",
              )}
            </p>
          ) : null}
          {canManage ? (
            <button
              type="button"
              disabled={!query.isSuccess}
              onClick={() => {
                openNewOrderForm(
                  query.data?.suggested_order_type ?? "periodic",
                );
              }}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              <Plus className="h-4 w-4" aria-hidden="true" /> Nowe zamówienie
            </button>
          ) : null}
        </div>
      </header>

      {mixedOrderTypesEnabled ? (
        <section
          aria-labelledby="standard-orders-heading"
          className="rounded-xl border border-border bg-card p-4"
        >
          <h3
            id="standard-orders-heading"
            className="mb-3 text-sm font-semibold uppercase tracking-wide text-foreground"
          >
            Zamówienia okresowe i drafty do uzupełnienia
          </h3>
          <OrdersAndContractsTab
            clientId={clientId}
            clientName={clientName}
            hideCreateButton
            suggestedOrderType={query.data?.suggested_order_type ?? "periodic"}
          />
        </section>
      ) : null}

      {mixedOrderTypesEnabled ? (
        <h3 className="text-sm font-semibold uppercase tracking-wide text-foreground">
          Zamówienia kosztowe i na MD
        </h3>
      ) : null}

      {/* Liczniki liczone z POBRANEJ listy, nie z osobnego zapytania — kafel
          będący sumą innych liczb niż widoczne pod nim jest niemożliwy do
          zweryfikowania wzrokiem. Renderujemy je dopiero przy `isSuccess`,
          żeby „(0)" nie udawało wyniku, zanim cokolwiek wiadomo. */}
      {query.isSuccess ? (
        <div className="flex flex-wrap gap-2">
          {pills.map((entry) => (
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

      {/* Wyszukiwarka/sortowanie/eksport operują na GRUPACH — w zakładce
          szkiców ukryte, żeby nie obiecywać filtrowania, które ich nie
          obejmuje (krótka kolejka do uzupełnienia, nie rejestr). */}
      {query.isSuccess && pill !== "draft" ? (
        <OrderListControls
          search={search}
          onSearchChange={setSearch}
          filters={filters}
          onFiltersChange={setFilters}
          resultCount={visible.length}
          exporting={exporting}
          onExport={exportVisible}
        />
      ) : null}

      {query.isError ? (
        /* Awaria pobrania MUSI mieć własną gałąź — pusty stan czytałby się jak
           „klient nie ma zamówień", czyli jak utrata danych. */
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać zamówień tego klienta."
          onRetry={() => query.refetch()}
        />
      ) : !query.isSuccess ? (
        /* Warunek na `isSuccess`, a NIE `isLoading`: w przerwie między
           ponowieniami react-query ma `isLoading === false` i `isError ===
           false` przy pustym `data`, więc pusty stan wygrywał i ekran mówił
           „brak zamówień", zanim wiadomo było cokolwiek. */
        <p className="py-10 text-center text-sm text-muted-foreground">
          Wczytywanie zamówień…
        </p>
      ) : pill === "draft" ? (
        <DraftOrdersSection
          clientId={clientId}
          drafts={draftOrders}
          canManage={canManage}
          onError={(msg) => showToast(msg, "error")}
          onSaved={({ activated, orderNumber }) => {
            invalidate();
            // Szkice żyją też w listingu jednoosobowym (`/orders`) — sekcja
            // „Dokumenty zamówień" i alerty DL czytają ten sam wiersz.
            queryClient.invalidateQueries({
              queryKey: ["dl-orders-grouped", clientId],
            });
            showToast(
              activated
                ? `Zamówienie aktywowane i przypisane: ${orderNumber}`
                : "Zapisano zmiany szkicu",
              "success",
            );
          }}
        />
      ) : visible.length === 0 ? (
        <EmptyState
          title={
            search.trim()
              ? "Nie znaleziono zamówienia pasującego do wyszukiwania"
              : pill === "all"
                ? mixedOrderTypesEnabled
                  ? "Brak zamówień kosztowych i na MD"
                  : "Brak zamówień"
                : "Brak wyników dla tego filtra"
          }
          description={
            search.trim()
              ? "Zmień wyszukiwaną frazę albo wyczyść aktywne filtry."
              : pill === "all"
              ? mixedOrderTypesEnabled
                ? "Zamówienia okresowe pozostają w rejestrze powyżej."
                : "Ten klient nie ma jeszcze zamówień wielo-konsultantowych."
              : "Zmień filtr, żeby zobaczyć pozostałe zamówienia."
          }
        />
      ) : (
        <div className="flex flex-col gap-4">
          {visible.map((group) => (
            <OrderGroupCard
              key={group.id}
              clientId={clientId}
              group={group}
              searchQuery={search}
              canManage={canManage}
              canManageLifecycle={canLifecycle}
              onAddConsultant={(g) => {
                setFormError(null);
                setLineModal({ open: true, group: g, line: null });
              }}
              onEditGroup={(g) => {
                setFormError(null);
                setGroupModal({ open: true, group: g });
              }}
              onEditLine={(g, line) => {
                setFormError(null);
                setLineModal({ open: true, group: g, line });
              }}
              onSwapLine={(g, line) => {
                setFormError(null);
                setSwapModal({ open: true, group: g, line });
              }}
              onDeleteLine={(g, line) => {
                if (
                  !window.confirm(
                    `Czy na pewno chcesz usunąć konsultanta ${line.consultant_name} ` +
                      `z zamówienia nr ${g.order_number}? Tej operacji nie można cofnąć.`,
                  )
                ) {
                  return;
                }
                removeLine.mutate({ groupId: g.id, lineId: line.id });
              }}
              onDeleteGroup={(g) => {
                if (
                  !window.confirm(
                    `Czy na pewno chcesz usunąć całe zamówienie nr ${g.order_number} ` +
                      `wraz ze wszystkimi konsultantami? Tej operacji nie można cofnąć.`,
                  )
                ) {
                  return;
                }
                removeGroup.mutate(g.id);
              }}
              onCloseGroup={(g) => {
                setFormError(null);
                setEndModal({ open: true, group: g });
              }}
              onReopenGroup={(g) => reopenGroup.mutate(g.id)}
              onExtendGroup={(g) => {
                setFormError(null);
                setExtendModal({ open: true, group: g });
              }}
              focusRequest={focusRequest}
              onFocusGroup={(groupId) =>
                setFocusRequest((prev) => ({
                  groupId,
                  nonce: (prev?.nonce ?? 0) + 1,
                }))
              }
            />
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
          orderType={newOrderType}
          onOrderTypeChange={openNewOrderForm}
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
