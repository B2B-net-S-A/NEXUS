"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  Download,
  FilePlus2,
  History,
  Plus,
  TrendingUp,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { countPl } from "@/lib/plural-pl";
import { PROJECT_PARTS, isEzdrowieClient } from "@/lib/ezdrowie";
import {
  downloadAuthenticatedFile,
  downloadBlob,
  postAuthenticatedDownload,
} from "@/lib/authenticated-files";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  filterAndSortContractors,
  visibleLegacyOrderIds,
  type OrderListFilters,
} from "@/lib/client-order-list";
import type {
  ClientOrderRead,
  ClientOrderStatus,
  ClientOrderUpdate,
  ContractWithOrdersRead,
  CreateDraftOrder,
} from "@/lib/api/dlPortal";
import {
  InlinePeriod,
  InlineText,
  dateOnly,
  fmtDate,
} from "@/components/orders/InlineOrderFields";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { EditOrderDialog } from "@/components/EditOrderDialog";
import { ExtendOrderDialog } from "@/components/ExtendOrderDialog";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";
import { TerminateContractModal } from "@/components/client-profile/actions/TerminateContractModal";
import { OrderListControls } from "@/components/client-profile/orders/OrderListControls";
import { NordeaOrderImportPanel } from "@/components/client-profile/orders/NordeaOrderImportPanel";
import { useAuthStore } from "@/store/auth";

interface OrdersAndContractsTabProps {
  clientId: number;
  clientName?: string;
}

type Filter = "all" | "active" | "expiring_30d" | "ended" | "drafts";

const STATUS_LABELS: Record<ClientOrderStatus, string> = {
  draft: "Draft",
  active: "Aktywne",
  paused: "Wstrzymane",
  completed: "Zakończone",
  cancelled: "Anulowane",
};

const STATUS_COLORS: Record<ClientOrderStatus, string> = {
  draft: "bg-yellow-100 text-yellow-800",
  active: "bg-green-100 text-green-800",
  paused: "bg-orange-100 text-orange-800",
  completed: "bg-zinc-200 text-zinc-700",
  cancelled: "bg-red-100 text-red-700",
};

/** Stany TERMINALNE kontraktu — jedyne, w których nie ma już czego kończyć. */
const TERMINAL_CONTRACT_STATUSES: ReadonlySet<string> = new Set([
  "ended",
  "void",
]);

/**
 * Czy pokazać „Zakończ". Bramka stoi na stanach TERMINALNYCH, świadomie NIE na
 * `active` — kontraktor bywa `draft`, bo „Nowy kontraktor" zakłada szkic
 * (dialog nie zbiera typu umowy ani trybu pracy), a konsultant realnie
 * pracuje. Jedyna droga rozstania — `POST /contracts/{id}/terminate`, który
 * żadnej bramki statusu nie ma, a `draft → ended` jest legalną krawędzią
 * cyklu życia — była zasłonięta przyciskiem, który się nie renderował.
 *
 * Uwaga historyczna: pierwotnym powodem tej bramki było to, że kontrakt
 * BEZTERMINOWY (profil body-leasingu, np. Bank Pocztowy) NIGDY nie wychodził
 * z Draftu, bo `ACTIVATION_REQUIRED_FIELDS` wymagało `end_date`. Tamta
 * przyczyna została usunięta (data końca zniknęła z bramki aktywacji), ale
 * reguła zostaje: szkic z pracującym konsultantem powstaje też innymi
 * drogami, a „nie ma czego kończyć" to nadal wyłącznie stan terminalny.
 *
 * Reguła jest SZERSZA niż predykat pigułki „Aktywni" niżej i to jest zamierzone:
 * tamta odpowiada na pytanie „kto dziś pracuje", ta na „czy jest jeszcze co
 * kończyć". Obie mieszkają w tym pliku, żeby rozjazd między nimi był widoczny.
 */
export function canTerminateContractor(contractStatus: string | null): boolean {
  return !TERMINAL_CONTRACT_STATUSES.has(contractStatus ?? "");
}

export function OrdersAndContractsTab({
  clientId,
  clientName = "",
}: OrdersAndContractsTabProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((state) => state.user);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [listFilters, setListFilters] = useState<OrderListFilters>({
    ...DEFAULT_ORDER_LIST_FILTERS,
  });
  const [exporting, setExporting] = useState(false);
  const searching = search.trim().length > 0;
  const [extendingContract, setExtendingContract] = useState<ContractWithOrdersRead | null>(
    null,
  );
  // „Zakończ" obok „Dodaj przedłużenie" (ticket #5 krok 3) — reuse modal
  // terminacji; backend synchronizuje kontrakt + zamówienia jedną datą.
  const [terminatingContract, setTerminatingContract] =
    useState<ContractWithOrdersRead | null>(null);
  const [newContractor, setNewContractor] = useState(false);
  const [editingOrder, setEditingOrder] = useState<{
    /** `null` = kontraktor nie ma jeszcze żadnego zamówienia (tryb tworzenia). */
    order: ClientOrderRead | null;
    rateCandidate: number | null;
    createOrder: CreateDraftOrder;
  } | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["dl-orders-grouped", clientId],
    queryFn: async () => {
      const res = await dlPortalApi.listContractorsWithOrders(clientId);
      return res.data;
    },
  });

  // Serwer wylicza to per klient (admin albo przypisany Delivery Lead). Front
  // nie zna przypisań DL, więc bramkowanie po samej roli pokazywałoby pola
  // stawek komuś, kto na zapisie dostanie 403.
  const canManageFinance = data?.can_manage_finance ?? false;

  // Predykaty pigułek w JEDNYM miejscu — filtr i licznik MUSZĄ liczyć to samo.
  // Dwie kopie tej samej reguły rozjeżdżają się przy pierwszej zmianie i dają
  // licznik, który nie zgadza się z listą pod nim.
  const PILL_PREDICATES: Record<
    Exclude<Filter, "all">,
    (c: ContractWithOrdersRead) => boolean
  > = useMemo(
    () => ({
      // Pigułki liczyły WYŁĄCZNIE status kontraktu, a uzupełnianie zamówienia
      // zmienia status ZAMÓWIENIA. Kontraktor z draftowym kontraktem i
      // kompletnym, aktywnym zamówieniem siedział więc w „Draft" na stałe i
      // nie pojawiał się w „Aktywni" — czyli uzupełnienie czterech pól nie
      // dawało żadnego widocznego skutku, mimo że backend promował zamówienie
      // (`_auto_activate_unless_status_explicit`).
      // Zawężone do kontraktu SZKICOWEGO. Szersze „którekolwiek zamówienie jest
      // aktywne" wciągało do „Aktywni" kontrakty ZAKOŃCZONE i unieważnione,
      // którym został wiszący wiersz `active` (zamówienia domyka nocny skaner
      // `dl_portal_expiry_scanner` po dacie, więc taki rozjazd to norma, nie
      // wyjątek) — kontraktor pokazywałby się jednocześnie w „Aktywni"
      // i „Zakończeni".
      active: (c) =>
        c.contract_status === "active" ||
        c.contract_status === "ending" ||
        (c.contract_status === "draft" &&
          c.orders.some((o) => o.status === "active")),
      expiring_30d: (c) =>
        c.days_to_latest_end !== null &&
        c.days_to_latest_end >= 0 &&
        c.days_to_latest_end <= 30,
      ended: (c) =>
        c.contract_status === "ended" || c.contract_status === "completed",
      // „Do uzupełnienia" = został jeszcze szkic zamówienia, albo kontrakt jest
      // szkicem i nie ma nic aktywnego, co by go wyprzedzało. Świadomie NIE
      // dodajemy tu kontraktora bez ani jednego zamówienia: to cała populacja
      // z poprawki przycisku „Uzupełnij zamówienie", więc licznik urósłby o
      // ludzi, których nikt tu wcześniej nie szukał.
      drafts: (c) =>
        c.orders.some((o) => o.status === "draft") ||
        (c.contract_status === "draft" &&
          !c.orders.some((o) => o.status === "active")),
    }),
    [],
  );

  // „Kończące się 30d" jest PODZBIOREM „Aktywni" — suma liczników świadomie
  // nie równa się liczbie z „Wszyscy". To zamierzone, nie błąd arytmetyki.
  const counts = useMemo(() => {
    const contractors = data?.contractors ?? [];
    return {
      active: contractors.filter(PILL_PREDICATES.active).length,
      expiring_30d: contractors.filter(PILL_PREDICATES.expiring_30d).length,
      ended: contractors.filter(PILL_PREDICATES.ended).length,
      drafts: contractors.filter(PILL_PREDICATES.drafts).length,
    };
  }, [data, PILL_PREDICATES]);

  const filtered = useMemo<ContractWithOrdersRead[]>(() => {
    const contractors = data?.contractors ?? [];
    const byPill =
      filter === "all" ? contractors : contractors.filter(PILL_PREDICATES[filter]);
    return filterAndSortContractors(byPill, search, listFilters);
  }, [data, filter, search, listFilters, PILL_PREDICATES]);

  async function exportVisible() {
    setExporting(true);
    try {
      const result = await postAuthenticatedDownload(
        `/api/clients/${clientId}/orders/export`,
        { order_ids: visibleLegacyOrderIds(filtered, search) },
      );
      downloadBlob(result.blob, result.filename ?? "Zamowienia.xlsx");
      showToast("Pobrano zamówienia do Excela", "success");
    } catch {
      showToast("Nie udało się przygotować pliku Excel.", "error");
    } finally {
      setExporting(false);
    }
  }

  // Rejestr jest PUSTY tylko wtedy, gdy klient naprawdę nie ma kontraktorów —
  // i to jedyny warunek, pod którym wolno napisać „Dodaj pierwszego".
  // Wyliczanie tego z „pigułka = Wszyscy ORAZ nie szukam" jest kruche: każdy
  // DOŁOŻONY filtr (daty, budżet, „kończące się", sortowanie) musiałby dopisać
  // się do tamtej listy, a jeden zapomniany zamienia zawężony wynik w komunikat
  // zaprzeczający danym, które są w pamięci przeglądarki — i zapraszający do
  // założenia duplikatu. Warunek liczony ze ŹRÓDŁA nie wymaga wyliczania
  // filtrów, więc nie zdezaktualizuje się przy dokładaniu kolejnych.
  const contractorCount = data?.contractors.length ?? 0;

  // Panel filtrów bywa zwinięty, więc użytkownik może nie widzieć, że coś
  // filtruje — pusty stan musi dawać wyjście, nie tylko diagnozę.
  function clearFilters() {
    setFilter("all");
    setSearch("");
  }

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["dl-orders-grouped", clientId] });
    // Ten sam plik żyje w sekcji „Dokumenty zamówień" w zakładce Dokumenty
    // kontraktu i w Plikach osoby (read-time bridge, zero kopii). Bez tego
    // wgrany PDF pokazuje się tam dopiero po przeładowaniu strony.
    queryClient.invalidateQueries({ queryKey: ["order-documents"] });
  }

  if (isLoading) {
    return (
      <div className="text-muted-foreground py-8 text-center">
        Ładowanie zamówień & kontraktów…
      </div>
    );
  }

  // Awaria pobrania NIE może renderować się jak pusty stan — „Brak
  // kontraktorów" po nieudanym zapytaniu czyta się jak utrata danych.
  if (isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać zamówień i kontraktów tego klienta."
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex flex-wrap gap-2 items-center">
          <FilterPill active={filter === "all"} onClick={() => setFilter("all")}>
            Wszyscy ({data?.total_contractors ?? 0})
          </FilterPill>
          <FilterPill active={filter === "active"} onClick={() => setFilter("active")}>
            Aktywni ({counts.active})
          </FilterPill>
          <FilterPill
            active={filter === "expiring_30d"}
            onClick={() => setFilter("expiring_30d")}
            warn
          >
            ⚠️ Kończące się 30d ({counts.expiring_30d})
          </FilterPill>
          <FilterPill active={filter === "drafts"} onClick={() => setFilter("drafts")}>
            📝 Draft (do uzupełnienia) ({counts.drafts})
          </FilterPill>
          <FilterPill active={filter === "ended"} onClick={() => setFilter("ended")}>
            Zakończeni ({counts.ended})
          </FilterPill>
        </div>
        <button
          onClick={() => setNewContractor(true)}
          className="flex items-center gap-1.5 px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700"
        >
          <UserPlus className="w-4 h-4" />
          Nowy kontraktor / zamówienie
        </button>
      </div>

      <OrderListControls
        search={search}
        onSearchChange={setSearch}
        filters={listFilters}
        onFiltersChange={setListFilters}
        showMdSort={false}
        showBudgetFilter={false}
        resultCount={filtered.length}
        exporting={exporting}
        onExport={exportVisible}
      />

      {(user?.role === "admin" || user?.roles?.includes("admin")) &&
      clientName.toLocaleLowerCase("pl").includes("nordea") ? (
        <NordeaOrderImportPanel clientId={clientId} onApplied={refresh} />
      ) : null}

      {filtered.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-12 text-center text-muted-foreground">
          <Users className="w-12 h-12 mx-auto mb-2 opacity-40" />
          {/* Pustka po zawężeniu ≠ brak danych — inaczej czyta się jak utratę
              danych (ten sam wzorzec co ProjectsTab / rejestr umów B2B). */}
          {contractorCount === 0 ? (
            <p>
              Brak kontraktorów u tego klienta. Dodaj pierwszego kontraktora i
              zamówienie.
            </p>
          ) : (
            <>
              <p>
                {searching
                  ? "Brak zamówień pasujących do wyszukiwania."
                  : "Brak wyników dla aktywnych filtrów."}
              </p>
              <p className="mt-1 text-xs">
                Ten klient ma{" "}
                {countPl(
                  contractorCount,
                  "kontraktora",
                  "kontraktorów",
                  "kontraktorów",
                )}{" "}
                w rejestrze — ukryły ich aktywne filtry.
              </p>
              <button
                type="button"
                onClick={clearFilters}
                className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-muted focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="w-4 h-4" aria-hidden="true" />
                Wyczyść filtry
              </button>
            </>
          )}
        </div>
      ) : (
        <ul className="space-y-3">
          {filtered.map((contractor) => (
            <ContractorCard
              key={contractor.contract_id}
              contractor={contractor}
              clientId={clientId}
              canManageFinance={canManageFinance}
              searching={searching}
              onExtend={() => setExtendingContract(contractor)}
              onTerminate={() => setTerminatingContract(contractor)}
              onEditOrder={(order, createOrder) =>
                setEditingOrder({
                  order,
                  rateCandidate: contractor.rate_candidate,
                  createOrder,
                })
              }
              onChange={refresh}
              onError={(msg) => showToast(msg, "error")}
              onSuccess={(msg) => showToast(msg, "success")}
            />
          ))}
        </ul>
      )}

      {extendingContract && (
        <ExtendOrderDialog
          clientId={clientId}
          contract={extendingContract}
          onClose={() => setExtendingContract(null)}
          onCreated={() => {
            setExtendingContract(null);
            refresh();
          }}
        />
      )}

      {newContractor && (
        <NewContractorOrderDialog
          clientId={clientId}
          onClose={() => setNewContractor(false)}
          onCreated={() => {
            setNewContractor(false);
            refresh();
          }}
        />
      )}

      {terminatingContract && (
        <TerminateContractModal
          contractId={terminatingContract.contract_id}
          candidateName={terminatingContract.candidate_name}
          clientId={clientId}
          onClose={() => setTerminatingContract(null)}
          onTerminated={refresh}
        />
      )}

      {editingOrder && (
        <EditOrderDialog
          clientId={clientId}
          order={editingOrder.order}
          rateCandidate={editingOrder.rateCandidate}
          onCreate={editingOrder.createOrder}
          canManageFinance={canManageFinance}
          onClose={() => setEditingOrder(null)}
          onSaved={() => {
            setEditingOrder(null);
            refresh();
          }}
          onChanged={refresh}
        />
      )}
    </div>
  );
}

/** „Uzupełnij zamówienie" — dostępne dla każdego statusu i w każdym slocie
 *  karty, RÓWNIEŻ gdy kontraktor nie ma jeszcze żadnego zamówienia.
 *
 *  Do 2026-08 przycisk wisiał na `activeOrder &&`, więc widzieli go wyłącznie
 *  klienci z zaimportowanymi zamówieniami (Nordea, Alior). Reszta dostawała
 *  samo „Dodaj przedłużenie" i zgłaszała to jako funkcję włączoną wybranym
 *  klientom — a to była różnica DANYCH, dokładnie ta sama, którą wcześniej
 *  naprawiono dla pól inline (patrz `saveOntoOrder`). */
function CompleteOrderButton({
  onClick,
  compact,
}: {
  onClick: () => void;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        compact
          ? "inline-flex items-center gap-1 text-xs text-violet-700 hover:underline"
          : "flex items-center gap-1.5 px-3 py-1.5 text-sm border border-violet-300 text-violet-700 rounded hover:bg-violet-50"
      }
    >
      <FilePlus2 className={compact ? "w-3.5 h-3.5" : "w-4 h-4"} />
      Uzupełnij zamówienie
    </button>
  );
}

interface FilterPillProps {
  active: boolean;
  warn?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function FilterPill({ active, warn, onClick, children }: FilterPillProps) {
  return (
    <button
      onClick={onClick}
      className={
        "px-3 py-1.5 text-sm rounded-full border transition-colors " +
        (active
          ? warn
            ? "bg-orange-100 border-orange-300 text-orange-800"
            : "bg-violet-100 border-violet-300 text-violet-800"
          : "bg-card border-border text-muted-foreground hover:text-foreground")
      }
    >
      {children}
    </button>
  );
}

// ── Order timeline split ─────────────────────────────────────────────────────

/** Local calendar date (YYYY-MM-DD). The host runs UTC+2, so a UTC "today"
 *  could misclassify an order that starts today — use the local wall date. */
function todayLocalISO(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

interface SplitOrders {
  /** Current position — drives the top of the card. */
  activeOrder: ClientOrderRead | null;
  /** Not-yet-started orders (queued przedłużenia). */
  futureOrders: ClientOrderRead[];
  /** Past/superseded + cancelled orders, kept behind a "Historia" toggle. */
  historyOrders: ClientOrderRead[];
}

/**
 * Splits a contractor's order timeline into the current position, the queued
 * future orders, and the historical ones. Date-driven on purpose: a
 * "przedłużenie" is created with `status=active` but a future `start_date`, so
 * the moment its start date arrives it naturally promotes to the top of the
 * card without any backend cron. `orders` arrives sorted by start_date desc.
 */
export function splitOrders(orders: ClientOrderRead[]): SplitOrders {
  const today = todayLocalISO();
  const nonCancelled = orders.filter((o) => o.status !== "cancelled");
  const cancelled = orders.filter((o) => o.status === "cancelled");

  const future = nonCancelled.filter((o) => {
    const start = dateOnly(o.start_date);
    return start !== null && start > today;
  });
  const started = nonCancelled.filter((o) => {
    const start = dateOnly(o.start_date);
    return start === null || start <= today;
  });

  let activeOrder: ClientOrderRead | null = null;
  let futureOrders: ClientOrderRead[] = future;
  if (started.length > 0) {
    activeOrder = started[0]; // latest started (input is start_date desc)
  } else if (future.length > 0) {
    // No order has started yet — the soonest upcoming one is the current one.
    const soonestFirst = [...future].sort((a, b) =>
      (dateOnly(a.start_date) ?? "").localeCompare(dateOnly(b.start_date) ?? ""),
    );
    activeOrder = soonestFirst[0];
    futureOrders = soonestFirst.slice(1);
  }

  const historyOrders = [
    ...started.filter((o) => o.id !== activeOrder?.id),
    ...cancelled,
  ].sort((a, b) =>
    (dateOnly(b.start_date) ?? "").localeCompare(dateOnly(a.start_date) ?? ""),
  );

  return { activeOrder, futureOrders, historyOrders };
}

// ── Contractor card ──────────────────────────────────────────────────────────

interface ContractorCardProps {
  contractor: ContractWithOrdersRead;
  clientId: number;
  canManageFinance: boolean;
  /** Aktywne wyszukiwanie — wymusza rozwinięcie historii, żeby trafienie
      w historycznym zamówieniu nie było schowane za zwiniętym togglem. */
  searching: boolean;
  onExtend: () => void;
  onTerminate: () => void;
  /** `order === null` → kontraktor nie ma jeszcze zamówienia (tryb tworzenia). */
  onEditOrder: (order: ClientOrderRead | null, createOrder: CreateDraftOrder) => void;
  onChange: () => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
}

function ContractorCard({
  contractor,
  clientId,
  canManageFinance,
  searching,
  onExtend,
  onTerminate,
  onEditOrder,
  onChange,
  onError,
  onSuccess,
}: ContractorCardProps) {
  const [showHistory, setShowHistory] = useState(false);
  const historyOpen = searching ? true : showHistory;
  // „Część umowy" — uzupełnianie/edycja bezpośrednio na karcie (to jest
  // powierzchnia kompletacji draftu ClientOrder); tylko Centrum e-Zdrowia.
  const ezdrowie = isEzdrowieClient(clientId);
  const [partSaving, setPartSaving] = useState(false);
  // Część wybrana ZANIM powstało zamówienie. `POST /orders` wymaga jej dla
  // e-Zdrowia (`validate_project_part(..., require=True)`), a select renderował
  // się dotąd tylko przy `activeOrder` — więc kontraktor bez zamówienia nie
  // miał ani jak jej podać, ani skąd wiedzieć, że jej brakuje.
  const [pendingPart, setPendingPart] = useState("");
  // Id szkicu założonego w TEJ sesji karty. `onChange()` odświeża listę
  // asynchronicznie, więc między utworzeniem szkicu a nadejściem danych
  // `activeOrder` jest jeszcze `null` — bez tej pamięci kolejny zapis w tym
  // okienku wpadałby w gałąź tworzenia i zakładał DRUGI szkic tego samego
  // zamówienia. Ryzyko istniało od pierwszej wersji tej ścieżki, ale wybór
  // części umowy dokłada obowiązkowy krok bezpośrednio przed innymi edycjami,
  // czyli robi z rzadkiego wyścigu zwykłą kolejność klikania.
  const [draftOrderId, setDraftOrderId] = useState<number | null>(null);

  // Ten sam fakt co `draftOrderId`, ale czytany REFEM, nie z domknięcia.
  // Dialog dostaje `createDraftOrder` przez stan rodzica (`editingOrder`), więc
  // trzyma JEDNĄ instancję przez całe swoje życie — domknięcie zamrożone
  // w chwili otwarcia widziałoby `draftOrderId === null` nawet po tym, jak
  // zapis właśnie założył szkic, i zakładało drugie zamówienie.
  const knownOrderIdRef = useRef<number | null>(null);

  const { activeOrder, futureOrders, historyOrders } = useMemo(
    () => splitOrders(contractor.orders),
    [contractor.orders],
  );
  knownOrderIdRef.current = activeOrder?.id ?? draftOrderId;

  /**
   * Zapis pola karty, gdy kontraktor NIE MA jeszcze żadnego zamówienia.
   *
   * Tu leży przyczyna zgłoszenia „u Banku Pocztowego nie da się nic wpisać":
   * numer, okres i stawka przychodowa wisiały na `activeOrder`, więc kontraktor
   * bez ani jednego `ClientOrder` widział nieedytowalne „—", a stawka kosztowa
   * renderowała się, ale zapis rzucał wyjątkiem. U Aliora te pola działają
   * wyłącznie dlatego, że jego zamówienia zostały kiedyś zaimportowane — to
   * różnica DANYCH, nie konfiguracji klienta.
   *
   * Dlatego poprawka jest jedna i globalna: pierwszy zapis zakłada szkic
   * zamówienia i od razu stosuje wpisaną wartość. Klient z zamówieniami nie
   * wchodzi w tę ścieżkę w ogóle.
   */
  const createDraftOrder = useCallback<CreateDraftOrder>(
    async (patch, opts) => {
      // Szkic mógł już powstać: albo z edycji inline w tej samej karcie, albo
      // z POPRZEDNIEGO, nieudanego zapisu tego samego dialogu (`onError` tylko
      // toastuje — okienko zostaje otwarte i wciąż w trybie tworzenia, bo
      // `editingOrder.order` to zamrożony snapshot ze stanu rodzica). Bez tego
      // sprawdzenia drugie kliknięcie „Zapisz" zakładało DRUGIE zamówienie na
      // tym samym kontrakcie — pierwsze zostawało sierotą w pigułce „Draft".
      // Guard mieszkał dotąd wyłącznie w `saveOntoOrder`; ścieżka dialogowa
      // omijała go, bo woła to wołanie wprost.
      const existingId = knownOrderIdRef.current;
      if (existingId !== null && existingId !== undefined) {
        const merged: Partial<ClientOrderUpdate> = { ...patch };
        // `title` i `project_part` bywają wyłącznie w `opts` (edycja inline
        // części umowy woła `saveOntoOrder({}, {projectPart})` z PUSTYM patchem).
        if (opts?.title?.trim()) merged.title = opts.title.trim();
        if (ezdrowie && merged.project_part == null && opts?.projectPart) {
          merged.project_part = opts.projectPart;
        }
        await dlPortalApi.updateOrder(clientId, existingId, merged);
        if (opts?.file) {
          await dlPortalApi.replaceOrderPo(clientId, existingId, opts.file);
        }
        return existingId;
      }
      // Centrum e-Zdrowia: bez części umowy `POST /orders` zwraca 422, a
      // użytkownik zobaczyłby surowe „Request failed with status code 422".
      // Odmawiamy tutaj, własnym zdaniem po polsku, wskazującym pole do
      // uzupełnienia — inaczej ta ścieżka „nie da się nic wpisać" wracałaby
      // u jednego klienta mimo poprawki.
      const projectPart = opts?.projectPart ?? pendingPart;
      if (ezdrowie && !projectPart) {
        throw new Error(
          "Najpierw wybierz część umowy — bez niej nie da się założyć zamówienia u Centrum e-Zdrowia.",
        );
      }
      const form = new FormData();
      form.append("contract_id", String(contractor.contract_id));
      if (ezdrowie) form.append("project_part", projectPart);
      // Numer bywa nieznany w chwili, gdy uzupełniany jest okres albo stawka.
      // „(bez numeru)" jest uczciwe i widoczne — pusty tytuł odrzuca walidacja,
      // a zmyślony numer wyglądałby jak dane z dokumentu klienta.
      form.append("title", opts?.title?.trim() || "(bez numeru)");
      // `draft`, nie `active`: zamówienie powstaje z jednego wpisanego pola, więc
      // nie jest jeszcze kompletne — trafia do pigułki „Draft (do uzupełnienia)",
      // czyli dokładnie tam, gdzie ma się dopominać o resztę. Komplet pól
      // z dialogu i tak promuje je od razu — robi to `_activate_complete_draft`
      // po stronie serwera, nie ten formularz.
      form.append("order_status", "draft");
      if (contractor.initial_job_id != null) {
        form.append("job_id", String(contractor.initial_job_id));
      }
      if (patch.start_date) form.append("start_date", patch.start_date);
      if (patch.end_date) form.append("end_date", patch.end_date);
      if (patch.rate_client != null) {
        form.append("rate_client", String(patch.rate_client));
      }
      if (patch.description) form.append("description", patch.description);
      // `POST /orders` przyjmuje plik w tym samym żądaniu, więc tworzenie
      // z dialogu (razem z PDF-em) to JEDEN request — nie create + upload,
      // który przy błędzie drugiego kroku zostawiałby zamówienie bez pliku.
      if (opts?.file) form.append("file", opts.file);
      const created = await dlPortalApi.createOrderExtension(clientId, form);
      // Ref PRZED stanem: ponowny „Zapisz" po nieudanej dopłacie stawki
      // kosztowej leci, zanim React zdąży przerenderować kartę.
      knownOrderIdRef.current = created.data.id;
      setDraftOrderId(created.data.id);
      // Stawka KOSZTOWA mieszka na kontrakcie, a `POST /orders` jej nie
      // przyjmuje — dosyłamy ją PATCH-em na świeżo utworzone zamówienie, którego
      // handler przepisuje ją na kontrakt.
      if (patch.rate_candidate != null) {
        await dlPortalApi.updateOrder(clientId, created.data.id, {
          rate_candidate: patch.rate_candidate,
        });
      }
      return created.data.id;
    },
    [
      clientId,
      contractor.contract_id,
      contractor.initial_job_id,
      ezdrowie,
      pendingPart,
    ],
  );

  /**
   * Otwiera „Uzupełnij zamówienie" dla wskazanego slotu karty.
   *
   * Wiersze przyszłe i historyczne zawsze mają zamówienie, więc dostają to
   * wołanie już zawężone do `(order) => void` — tylko slot aktualny potrafi
   * podać `null`.
   */
  const openOrderDialog = useCallback(
    (order: ClientOrderRead | null) => onEditOrder(order, createDraftOrder),
    [onEditOrder, createDraftOrder],
  );

  // Jedno wejście dla obu ścieżek zapisu (inline i dialog) — guard „czy szkic
  // już istnieje" siedzi w `createDraftOrder`, więc nie da się go ominąć.
  async function saveOntoOrder(
    patch: Partial<ClientOrderUpdate>,
    opts?: { title?: string; projectPart?: string },
  ) {
    await createDraftOrder(patch, opts);
  }

  const expiringWarn =
    contractor.days_to_latest_end !== null &&
    contractor.days_to_latest_end >= 0 &&
    contractor.days_to_latest_end <= 30;

  const hasSection = futureOrders.length > 0 || historyOrders.length > 0;

  return (
    <li className="border border-border rounded-lg bg-card p-4 space-y-3">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          {/* Header: imię i nazwisko + numer kontraktu szarą, mniejszą czcionką.
              Numer BEZ dopisku statusu — słowo „draft" obok nazwiska mówiło
              o stanie rekordu, nie o czymkolwiek, co rekruter może z tym zrobić.
              (Wcześniejszy ticket zdjął ten numer w całości; obecny go
              przywraca — to nowsze zamówienie produktowe.) */}
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-base">
              👤 {contractor.candidate_name}
            </h3>
            <span className="text-xs text-muted-foreground">
              Contract {contractor.contract_id}
            </span>
            {expiringWarn && (
              <span className="text-xs text-orange-700 bg-orange-100 px-2 py-0.5 rounded flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                kończy się za {contractor.days_to_latest_end} dni
              </span>
            )}
          </div>
          {/* Numer zamówienia (from the active order's title) */}
          <div className="mt-1 text-sm">
            <span className="text-muted-foreground">Numer zamówienia </span>
            <InlineText
              value={activeOrder?.title ?? ""}
              display={
                activeOrder ? (
                  <span className="font-medium text-foreground">
                    {activeOrder.title}
                  </span>
                ) : (
                  <em className="text-muted-foreground">wpisz numer</em>
                )
              }
              ariaLabel="Numer zamówienia"
              placeholder="np. 45767"
              onError={onError}
              onSave={async (raw) => {
                if (!raw) throw new Error("Numer zamówienia nie może być pusty");
                await saveOntoOrder({ title: raw }, { title: raw });
                onSuccess("Numer zamówienia zaktualizowany");
                onChange();
              }}
            />
          </div>

          {/* Finance + period row */}
          <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
            {canManageFinance && (
              <span>
                stawka kosztowa{" "}
                <InlineText
                  value={contractor.rate_candidate != null ? String(contractor.rate_candidate) : ""}
                  display={
                    contractor.rate_candidate != null ? (
                      <strong className="text-foreground">
                        {fmtMoney(contractor.rate_candidate)}
                        {rateUnitSuffix(contractor.rate_unit)}
                      </strong>
                    ) : (
                      <em className="text-muted-foreground">ustaw stawkę</em>
                    )
                  }
                  ariaLabel="Stawka kosztowa"
                  inputMode="decimal"
                  sanitize={sanitizeDecimalInput}
                  placeholder="np. 12000"
                  onError={onError}
                  onSave={async (raw) => {
                    // Zapis idzie przez zamówienie, nie przez PATCH
                    // /api/contracts/{id}: tamten handler ma własną, admin-only
                    // bramkę na 17 pól finansowych, więc przypisany Delivery
                    // Lead dostawał tam 403 mimo prawa do tego klienta.
                    // Kontraktor bez zamówienia dostaje je przy pierwszym
                    // zapisie — wcześniej ta gałąź rzucała wyjątkiem i pole
                    // wyglądało na zepsute.
                    await saveOntoOrder({ rate_candidate: parseDecimalInput(raw) });
                    onSuccess("Stawka kosztowa zaktualizowana");
                    onChange();
                  }}
                />
              </span>
            )}
            {/* Warunek NIE obejmuje już `activeOrder`: bez zamówienia to pole
                po prostu ZNIKAŁO, więc karta pokazywała stawkę kosztową bez
                przychodowej i wyglądała, jakby tej drugiej u tego klienta nie
                było wcale. */}
            {canManageFinance && (
              <span>
                stawka przychodowa{" "}
                <InlineText
                  value={
                    activeOrder?.rate_client != null
                      ? String(activeOrder.rate_client)
                      : ""
                  }
                  display={
                    activeOrder?.rate_client != null ? (
                      <strong className="text-foreground">
                        {fmtMoney(activeOrder.rate_client)}
                        {rateUnitSuffix(contractor.rate_unit)}
                      </strong>
                    ) : (
                      <em className="text-muted-foreground">ustaw stawkę</em>
                    )
                  }
                  ariaLabel="Stawka przychodowa"
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
            )}
            {ezdrowie && (
              <span className="flex items-center gap-1">
                część umowy
                <select
                  value={activeOrder ? (activeOrder.project_part ?? "") : pendingPart}
                  aria-label="Część umowy"
                  disabled={partSaving}
                  onChange={async (e) => {
                    const value = e.target.value || null;
                    // disabled na czas zapisu (bez wyścigu dwóch PATCHy);
                    // po błędzie onChange() re-synchronizuje select z serwera
                    // zamiast zostawiać DOM na niezapisanej wartości (review).
                    setPartSaving(true);
                    try {
                      if (activeOrder) {
                        await dlPortalApi.updateOrder(clientId, activeOrder.id, {
                          project_part: value,
                        });
                        onSuccess("Część umowy zaktualizowana");
                      } else if (value) {
                        // Bez zamówienia część jest tym POLEM, które je zakłada
                        // — dopiero wtedy numer, okres i stawki mają dokąd
                        // trafić. Wartość idzie jawnie, bo `pendingPart` nie
                        // zdąży się jeszcze zaktualizować w tym samym handlerze.
                        await saveOntoOrder({}, { projectPart: value });
                        setPendingPart(value);
                        onSuccess("Część umowy zapisana");
                      } else {
                        setPendingPart("");
                      }
                    } catch {
                      onError("Nie udało się zapisać części umowy");
                    } finally {
                      setPartSaving(false);
                      onChange();
                    }
                  }}
                  className={`px-1.5 py-0.5 border rounded bg-background text-xs disabled:opacity-60 ${
                    (activeOrder ? activeOrder.project_part : pendingPart)
                      ? "border-border"
                      : "border-amber-400 text-amber-700"
                  }`}
                >
                  <option value="">— uzupełnij —</option>
                  {PROJECT_PARTS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </span>
            )}
            <InlinePeriod
              startDate={activeOrder?.start_date ?? null}
              endDate={activeOrder?.end_date ?? null}
              onError={onError}
              onSave={async (start, end) => {
                await saveOntoOrder({ start_date: start, end_date: end });
                onSuccess("Okres zamówienia zaktualizowany");
                onChange();
              }}
            />
          </div>

          {/* Rekrutacja, z której wyszedł ten kontraktor. Dane przychodzą
              z `/orders` od dawna (`initial_job_title`) — wcześniejszy ticket
              zdjął tylko render, obecny go przywraca. */}
          {contractor.initial_job_title && (
            <div className="mt-1 text-xs text-muted-foreground">
              z rekrutacji:{" "}
              <span className="text-foreground">
                {contractor.initial_job_title}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Bez `activeOrder &&` — kontraktor bez zamówienia też musi mieć
              czym je założyć; dialog otwiera się pusty, a POST leci dopiero
              przy zapisie. */}
          <CompleteOrderButton onClick={() => openOrderDialog(activeOrder)} />
          <button
            onClick={onExtend}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-600 text-white rounded hover:bg-violet-700"
          >
            <Plus className="w-4 h-4" />
            Dodaj przedłużenie
          </button>
          {/* „Zakończ" (ticket #5 krok 3) — ukryte WYŁĄCZNIE w stanach
              terminalnych; uzasadnienie przy `canTerminateContractor`. */}
          {canTerminateContractor(contractor.contract_status) && (
            <button
              onClick={onTerminate}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-destructive border border-destructive/40 rounded hover:bg-destructive/10"
            >
              <Trash2 className="w-4 h-4" />
              Zakończ
            </button>
          )}
        </div>
      </div>

      {hasSection ? (
        <div className="space-y-3">
          {/* „Przyszłe zamówienie" i „Historia zamówień" to DWA osobne
              kontenery, nie jedna sekcja z przełącznikiem. Wcześniej wiersze
              historii renderowały się pod nagłówkiem sekcji przyszłych i miały
              badge „Draft" — czyli pod nagłówkiem „Przyszłe zamówienie" stały
              zamówienia zakończone, oznaczone słowem, którego ten ticket
              zabrania właśnie w tym miejscu. */}
          <div className="pl-2 border-l-2 border-violet-200 space-y-2">
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Przyszłe zamówienie
              {futureOrders.length > 0 ? ` (${futureOrders.length})` : ""}
            </div>

            {futureOrders.length > 0 ? (
              futureOrders.map((order) => (
                <FutureOrderRow
                  key={order.id}
                  order={order}
                  candidateName={contractor.candidate_name}
                  clientId={clientId}
                  onEditOrder={openOrderDialog}
                  onError={onError}
                  onSuccess={onSuccess}
                  onChange={onChange}
                />
              ))
            ) : (
              <div className="text-xs text-muted-foreground italic">
                Brak przyszłych zamówień.
              </div>
            )}
          </div>

          {historyOrders.length > 0 && (
            <div className="pl-2 border-l-2 border-border space-y-2">
              <button
                type="button"
                onClick={() => {
                  // Przy aktywnym wyszukiwaniu historia jest wymuszona —
                  // toggle nie może schować dopasowanego zamówienia.
                  if (!searching) setShowHistory((v) => !v);
                }}
                aria-expanded={historyOpen}
                className="text-xs font-medium text-muted-foreground hover:text-violet-600 flex items-center gap-1 uppercase tracking-wide"
              >
                <History className="w-3 h-3" />
                Historia zamówień ({historyOrders.length})
              </button>

              {historyOpen &&
                historyOrders.map((order) => (
                  <HistoryOrderRow
                    key={order.id}
                    order={order}
                    clientId={clientId}
                    canManageFinance={canManageFinance}
                    rateUnit={contractor.rate_unit}
                    onEditOrder={openOrderDialog}
                    onError={onError}
                    onSuccess={onSuccess}
                    onDeleted={onChange}
                  />
                ))}
            </div>
          )}
        </div>
      ) : (
        !activeOrder && (
          <div className="text-xs text-muted-foreground italic pl-2">
            Brak zamówień — uzupełnij numer, okres i stawki powyżej, a zamówienie
            powstanie automatycznie jako szkic.
          </div>
        )
      )}
    </li>
  );
}

// ── Future order row (queued przedłużenie) ───────────────────────────────────

interface FutureOrderRowProps {
  order: ClientOrderRead;
  candidateName: string;
  clientId: number;
  onEditOrder: (order: ClientOrderRead) => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
  onChange: () => void;
}

function FutureOrderRow({
  order,
  candidateName,
  clientId,
  onEditOrder,
  onError,
  onSuccess,
  onChange,
}: FutureOrderRowProps) {
  const deleteMutation = useMutation({
    mutationFn: () => dlPortalApi.deleteOrder(clientId, order.id),
    onSuccess: () => {
      onSuccess("Zamówienie usunięte / anulowane");
      onChange();
    },
    onError: (err: unknown) => {
      onError(err instanceof Error ? err.message : "Błąd usuwania");
    },
  });

  return (
    <div className="flex items-start justify-between gap-3 text-sm border border-border rounded p-2 bg-background">
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="font-medium">{candidateName}</div>
        <div className="text-xs">
          <span className="text-muted-foreground">Numer zamówienia: </span>
          <InlineText
            value={order.title}
            display={<span className="font-medium">{order.title}</span>}
            ariaLabel="Numer zamówienia (przyszłe)"
            onError={onError}
            onSave={async (raw) => {
              if (!raw) throw new Error("Numer zamówienia nie może być pusty");
              await dlPortalApi.updateOrder(clientId, order.id, { title: raw });
              onSuccess("Numer zamówienia zaktualizowany");
              onChange();
            }}
          />
        </div>
        {(order.start_date || order.end_date) && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Calendar className="w-3 h-3" />
            {fmtDate(order.start_date)} → {fmtDate(order.end_date) || "bezterminowo"}
          </div>
        )}
        <CompleteOrderButton onClick={() => onEditOrder(order)} compact />
      </div>
      <button
        type="button"
        onClick={() => {
          if (confirm(`Anulować zamówienie "${order.title}"?`)) deleteMutation.mutate();
        }}
        className="text-muted-foreground hover:text-destructive p-1"
        title="Usuń / anuluj"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

// ── History order row (past / superseded / cancelled) ────────────────────────

interface HistoryOrderRowProps {
  order: ClientOrderRead;
  clientId: number;
  canManageFinance: boolean;
  /** Jednostka stawek kontraktu — surowy rate_client jest w tej jednostce. */
  rateUnit: string;
  onEditOrder: (order: ClientOrderRead) => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
  onDeleted: () => void;
}

function HistoryOrderRow({
  order,
  clientId,
  canManageFinance,
  rateUnit,
  onEditOrder,
  onError,
  onSuccess,
  onDeleted,
}: HistoryOrderRowProps) {
  const deleteMutation = useMutation({
    mutationFn: () => dlPortalApi.deleteOrder(clientId, order.id),
    onSuccess: () => {
      onSuccess("Zamówienie usunięte / anulowane");
      onDeleted();
    },
    onError: (err: unknown) => {
      onError(err instanceof Error ? err.message : "Błąd usuwania");
    },
  });

  // The file endpoint is Bearer-guarded — a raw <a href> sends no Authorization
  // header. Fetch the bytes with the token and download the same-origin blob.
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
    <div className="flex items-start justify-between gap-3 text-sm border border-border rounded p-2 bg-background">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLORS[order.status]}`}>
            {STATUS_LABELS[order.status]}
          </span>
          <span className="font-medium">{order.title}</span>
        </div>
        <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
          {(order.start_date || order.end_date) && (
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {fmtDate(order.start_date)} → {fmtDate(order.end_date) || "bezterminowo"}
            </span>
          )}
          {canManageFinance && order.rate_client !== null && (
            <span>
              przychód {fmtMoney(order.rate_client)}
              {rateUnitSuffix(rateUnit)}
            </span>
          )}
          {/* Marża zostaje /mc — jest znormalizowana miesięcznie po stronie BE. */}
          {canManageFinance && order.monthly_margin !== null && (
            <span className="flex items-center gap-1 text-green-700">
              <TrendingUp className="w-3 h-3" />
              marża {fmtMoney(order.monthly_margin)}/mc
            </span>
          )}
          {order.has_file && (
            <button
              type="button"
              onClick={handleDownloadPo}
              className="flex items-center gap-1 hover:text-violet-600"
            >
              <Download className="w-3 h-3" />
              PDF
            </button>
          )}
          <CompleteOrderButton onClick={() => onEditOrder(order)} compact />
        </div>
      </div>
      <button
        type="button"
        onClick={() => {
          if (confirm(`Anulować zamówienie "${order.title}"?`)) deleteMutation.mutate();
        }}
        className="text-muted-foreground hover:text-destructive p-1"
        title="Usuń / anuluj"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

function fmtMoney(v: number | string | null): string {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("pl-PL");
}

// Surowe stawki (rate_candidate / rate_client) są w jednostce kontraktu —
// etykieta musi za nią podążać (Alior ma stawki godzinowe; „164,375/mc" to
// był bug). Marża NIE używa tego sufiksu — jest normalizowana do /mc na BE.
const RATE_UNIT_SUFFIX: Record<string, string> = {
  hourly: "/h",
  daily: "/dzień",
  monthly: "/mc",
};

export function rateUnitSuffix(unit: string | null | undefined): string {
  return RATE_UNIT_SUFFIX[unit ?? "monthly"] ?? "/mc";
}

export { FilePlus2 };
