"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  Check,
  Download,
  FilePlus2,
  History,
  Pencil,
  Plus,
  Search,
  TrendingUp,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { contractsApi } from "@/lib/api";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { foldText } from "@/lib/contract-client-filter";
import { PROJECT_PARTS, isEzdrowieClient } from "@/lib/ezdrowie";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import type {
  ClientOrderRead,
  ClientOrderStatus,
  ContractWithOrdersRead,
} from "@/lib/api/dlPortal";
import {
  DATE_PATTERN,
  DATE_PLACEHOLDER,
  normalizeDateInput,
} from "@/lib/dateInput";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { canManageCandidateFinance, useAuthStore } from "@/store/auth";
import { ExtendOrderDialog } from "@/components/ExtendOrderDialog";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";

interface OrdersAndContractsTabProps {
  clientId: number;
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

export function OrdersAndContractsTab({ clientId }: OrdersAndContractsTabProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((state) => state.user);
  const canManageFinance = canManageCandidateFinance(user);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const searching = debouncedSearch.trim().length > 0;
  const [extendingContract, setExtendingContract] = useState<ContractWithOrdersRead | null>(
    null,
  );
  const [newContractor, setNewContractor] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["dl-orders-grouped", clientId],
    queryFn: async () => {
      const res = await dlPortalApi.listContractorsWithOrders(clientId);
      return res.data;
    },
  });

  const filtered = useMemo<ContractWithOrdersRead[]>(() => {
    const contractors = data?.contractors ?? [];
    let byPill = contractors;
    if (filter === "active") {
      byPill = contractors.filter(
        (c) => c.contract_status === "active" || c.contract_status === "ending",
      );
    } else if (filter === "expiring_30d") {
      byPill = contractors.filter(
        (c) =>
          c.days_to_latest_end !== null &&
          c.days_to_latest_end >= 0 &&
          c.days_to_latest_end <= 30,
      );
    } else if (filter === "ended") {
      byPill = contractors.filter(
        (c) => c.contract_status === "ended" || c.contract_status === "completed",
      );
    } else if (filter === "drafts") {
      byPill = contractors.filter(
        (c) =>
          c.contract_status === "draft" ||
          c.orders.some((o) => o.status === "draft"),
      );
    }
    // Filtr tekstowy działa PO stronie klienta, bo GET /orders zwraca pełną
    // listę bez paginacji — jeśli kiedyś dojdzie limit/paginacja, przenieś
    // wyszukiwanie na serwer (?q=), inaczej zacznie cicho gubić trafienia.
    // Dopasowanie po konsultancie ORAZ po numerze KAŻDEGO zamówienia
    // (aktywnego, przyszłego i historycznego), diacritic-insensitive.
    const q = foldText(debouncedSearch.trim());
    if (!q) return byPill;
    return byPill.filter(
      (c) =>
        foldText(c.candidate_name).includes(q) ||
        c.orders.some((o) => foldText(o.title).includes(q)),
    );
  }, [data, filter, debouncedSearch]);

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["dl-orders-grouped", clientId] });
  }

  if (isLoading) {
    return (
      <div className="text-muted-foreground py-8 text-center">
        Ładowanie zamówień & kontraktów…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Szukaj po konsultancie lub numerze zamówienia…"
          aria-label="Szukaj zamówień"
          className="w-full border border-border rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
        />
      </div>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex flex-wrap gap-2 items-center">
          <FilterPill active={filter === "all"} onClick={() => setFilter("all")}>
            Wszyscy ({data?.total_contractors ?? 0})
          </FilterPill>
          <FilterPill active={filter === "active"} onClick={() => setFilter("active")}>
            Aktywni
          </FilterPill>
          <FilterPill
            active={filter === "expiring_30d"}
            onClick={() => setFilter("expiring_30d")}
            warn
          >
            ⚠️ Kończące się 30d
          </FilterPill>
          <FilterPill active={filter === "drafts"} onClick={() => setFilter("drafts")}>
            📝 Draft (do uzupełnienia)
          </FilterPill>
          <FilterPill active={filter === "ended"} onClick={() => setFilter("ended")}>
            Zakończeni
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

      {filtered.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-12 text-center text-muted-foreground">
          <Users className="w-12 h-12 mx-auto mb-2 opacity-40" />
          {/* Pustka po wyszukaniu ≠ brak danych — inaczej czyta się jak utratę
              danych (ten sam wzorzec co ProjectsTab / rejestr umów B2B). */}
          {searching
            ? "Brak zamówień pasujących do wyszukiwania."
            : filter === "all"
              ? "Brak kontraktorów u tego klienta. Dodaj pierwszego kontraktora i zamówienie."
              : "Brak wyników dla wybranego filtra."}
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
    </div>
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

function dateOnly(value: string | null): string | null {
  return value ? value.slice(0, 10) : null;
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

// ── Inline editing primitives ────────────────────────────────────────────────

interface InlineTextProps {
  /** Raw current value used to prefill the editor. */
  value: string;
  /** Rendered value while not editing. */
  display: React.ReactNode;
  ariaLabel: string;
  onSave: (raw: string) => Promise<void>;
  onError: (msg: string) => void;
  placeholder?: string;
  inputMode?: "text" | "decimal";
  sanitize?: (raw: string) => string;
}

/** Click-to-edit text/number field. Enter/blur saves, Esc cancels. */
function InlineText({
  value,
  display,
  ariaLabel,
  onSave,
  onError,
  placeholder,
  inputMode = "text",
  sanitize,
}: InlineTextProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);

  function begin() {
    setDraft(value);
    setEditing(true);
  }

  async function commit() {
    if (saving) return;
    if (draft.trim() === value.trim()) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(draft.trim());
      setEditing(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Nie udało się zapisać");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <span className="inline-flex items-center gap-1">
        {display}
        <button
          type="button"
          onClick={begin}
          aria-label={`Edytuj: ${ariaLabel}`}
          className="text-muted-foreground/50 hover:text-violet-600 transition-colors"
        >
          <Pencil className="w-3 h-3" />
        </button>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1">
      <input
        autoFocus
        value={draft}
        inputMode={inputMode}
        placeholder={placeholder}
        disabled={saving}
        aria-label={ariaLabel}
        onChange={(e) =>
          setDraft(sanitize ? sanitize(e.target.value) : e.target.value)
        }
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        onBlur={commit}
        className="px-1.5 py-0.5 border border-violet-300 rounded bg-background text-sm w-full max-w-[11rem]"
      />
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={commit}
        disabled={saving}
        aria-label="Zapisz"
        className="text-green-600 hover:text-green-700 disabled:opacity-50"
      >
        <Check className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setEditing(false)}
        disabled={saving}
        aria-label="Anuluj"
        className="text-muted-foreground hover:text-destructive disabled:opacity-50"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </span>
  );
}

interface InlinePeriodProps {
  startDate: string | null;
  endDate: string | null;
  onSave: (start: string | null, end: string | null) => Promise<void>;
  onError: (msg: string) => void;
}

/** Click-to-edit order period (start → end / bezterminowo). */
function InlinePeriod({ startDate, endDate, onSave, onError }: InlinePeriodProps) {
  const [editing, setEditing] = useState(false);
  const [start, setStart] = useState(dateOnly(startDate) ?? "");
  const [end, setEnd] = useState(dateOnly(endDate) ?? "");
  const [saving, setSaving] = useState(false);

  function begin() {
    setStart(dateOnly(startDate) ?? "");
    setEnd(dateOnly(endDate) ?? "");
    setEditing(true);
  }

  async function commit() {
    if (saving) return;
    const nextStart = start.trim() ? normalizeDateInput(start) : null;
    const nextEnd = end.trim() ? normalizeDateInput(end) : null;
    if (nextStart === dateOnly(startDate) && nextEnd === dateOnly(endDate)) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(nextStart, nextEnd);
      setEditing(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Nie udało się zapisać");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <span className="inline-flex items-center gap-1">
        <Calendar className="w-3 h-3" />
        <span>
          okres zamówienia: {fmtDate(startDate) ?? "—"} →{" "}
          {fmtDate(endDate) ?? "bezterminowo"}
        </span>
        <button
          type="button"
          onClick={begin}
          aria-label="Edytuj: okres zamówienia"
          className="text-muted-foreground/50 hover:text-violet-600 transition-colors"
        >
          <Pencil className="w-3 h-3" />
        </button>
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1 flex-wrap"
      onBlur={(e) => {
        // Match InlineText's save-on-blur: commit when focus leaves the whole
        // widget (outside click / tab-away), but stay put when moving between
        // the two date inputs or to the save/cancel buttons (they keep focus
        // via onMouseDown preventDefault, so they don't count as "leaving").
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) commit();
      }}
    >
      <span className="text-muted-foreground">okres zamówienia:</span>
      <input
        autoFocus
        type="text"
        inputMode="numeric"
        pattern={DATE_PATTERN}
        placeholder={DATE_PLACEHOLDER}
        value={start}
        disabled={saving}
        aria-label="Data od"
        onChange={(e) => setStart(e.target.value)}
        onBlur={(e) => setStart(normalizeDateInput(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        className="px-1.5 py-0.5 border border-violet-300 rounded bg-background text-sm w-28"
      />
      <span>→</span>
      <input
        type="text"
        inputMode="numeric"
        pattern={DATE_PATTERN}
        placeholder="bezterminowo"
        value={end}
        disabled={saving}
        aria-label="Data do (puste = bezterminowo)"
        onChange={(e) => setEnd(e.target.value)}
        onBlur={(e) => setEnd(normalizeDateInput(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        className="px-1.5 py-0.5 border border-violet-300 rounded bg-background text-sm w-28"
      />
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={commit}
        disabled={saving}
        aria-label="Zapisz"
        className="text-green-600 hover:text-green-700 disabled:opacity-50"
      >
        <Check className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setEditing(false)}
        disabled={saving}
        aria-label="Anuluj"
        className="text-muted-foreground hover:text-destructive disabled:opacity-50"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </span>
  );
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

  const { activeOrder, futureOrders, historyOrders } = useMemo(
    () => splitOrders(contractor.orders),
    [contractor.orders],
  );

  const expiringWarn =
    contractor.days_to_latest_end !== null &&
    contractor.days_to_latest_end >= 0 &&
    contractor.days_to_latest_end <= 30;

  const hasSection = futureOrders.length > 0 || historyOrders.length > 0;

  return (
    <li className="border border-border rounded-lg bg-card p-4 space-y-3">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          {/* Header: samo imię i nazwisko — numer kontraktu usunięty (ticket #4) */}
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-base">
              👤 {contractor.candidate_name}
            </h3>
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
            {activeOrder ? (
              <InlineText
                value={activeOrder.title}
                display={
                  <span className="font-medium text-foreground">
                    {activeOrder.title}
                  </span>
                }
                ariaLabel="Numer zamówienia"
                onError={onError}
                onSave={async (raw) => {
                  if (!raw) throw new Error("Numer zamówienia nie może być pusty");
                  await dlPortalApi.updateOrder(clientId, activeOrder.id, {
                    title: raw,
                  });
                  onSuccess("Numer zamówienia zaktualizowany");
                  onChange();
                }}
              />
            ) : (
              <span className="text-foreground">—</span>
            )}
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
                    await contractsApi.update(contractor.contract_id, {
                      rate_candidate: parseDecimalInput(raw),
                    });
                    onSuccess("Stawka kosztowa zaktualizowana");
                    onChange();
                  }}
                />
              </span>
            )}
            {canManageFinance && activeOrder && (
              <span>
                stawka przychodowa{" "}
                <InlineText
                  value={activeOrder.rate_client != null ? String(activeOrder.rate_client) : ""}
                  display={
                    activeOrder.rate_client != null ? (
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
                    await dlPortalApi.updateOrder(clientId, activeOrder.id, {
                      rate_client: parseDecimalInput(raw),
                    });
                    onSuccess("Stawka przychodowa zaktualizowana");
                    onChange();
                  }}
                />
              </span>
            )}
            {ezdrowie && activeOrder && (
              <span className="flex items-center gap-1">
                część umowy
                <select
                  value={activeOrder.project_part ?? ""}
                  aria-label="Część umowy"
                  disabled={partSaving}
                  onChange={async (e) => {
                    const value = e.target.value || null;
                    // disabled na czas zapisu (bez wyścigu dwóch PATCHy);
                    // po błędzie onChange() re-synchronizuje select z serwera
                    // zamiast zostawiać DOM na niezapisanej wartości (review).
                    setPartSaving(true);
                    try {
                      await dlPortalApi.updateOrder(clientId, activeOrder.id, {
                        project_part: value,
                      });
                      onSuccess("Część umowy zaktualizowana");
                    } catch {
                      onError("Nie udało się zapisać części umowy");
                    } finally {
                      setPartSaving(false);
                      onChange();
                    }
                  }}
                  className={`px-1.5 py-0.5 border rounded bg-background text-xs disabled:opacity-60 ${
                    activeOrder.project_part
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
            {activeOrder ? (
              <InlinePeriod
                startDate={activeOrder.start_date}
                endDate={activeOrder.end_date}
                onError={onError}
                onSave={async (start, end) => {
                  await dlPortalApi.updateOrder(clientId, activeOrder.id, {
                    start_date: start,
                    end_date: end,
                  });
                  onSuccess("Okres zamówienia zaktualizowany");
                  onChange();
                }}
              />
            ) : (
              <span className="flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                okres zamówienia: —
              </span>
            )}
          </div>

          {/* Info o rekrutacji usunięte z widoku Zamówień (ticket #4) —
              pozostaje w Profil → Obecni konsultanci (ConsultantRow). */}
        </div>

        <button
          onClick={onExtend}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-600 text-white rounded hover:bg-violet-700"
        >
          <Plus className="w-4 h-4" />
          Dodaj przedłużenie
        </button>
      </div>

      {hasSection ? (
        <div className="pl-2 border-l-2 border-violet-200 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Przyszłe zamówienie
              {futureOrders.length > 0 ? ` (${futureOrders.length})` : ""}
            </div>
            {historyOrders.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  // Przy aktywnym wyszukiwaniu historia jest wymuszona —
                  // toggle nie może schować dopasowanego zamówienia.
                  if (!searching) setShowHistory((v) => !v);
                }}
                aria-expanded={historyOpen}
                className="text-xs text-muted-foreground hover:text-violet-600 flex items-center gap-1"
              >
                <History className="w-3 h-3" />
                Historia zamówień ({historyOrders.length})
              </button>
            )}
          </div>

          {futureOrders.length > 0 ? (
            futureOrders.map((order) => (
              <FutureOrderRow
                key={order.id}
                order={order}
                candidateName={contractor.candidate_name}
                clientId={clientId}
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

          {historyOpen &&
            historyOrders.map((order) => (
              <HistoryOrderRow
                key={order.id}
                order={order}
                clientId={clientId}
                canManageFinance={canManageFinance}
                rateUnit={contractor.rate_unit}
                onError={onError}
                onSuccess={onSuccess}
                onDeleted={onChange}
              />
            ))}
        </div>
      ) : (
        !activeOrder && (
          <div className="text-xs text-muted-foreground italic pl-2">
            Brak zamówień — Contract bez aktualnego PDF od klienta.
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
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
  onChange: () => void;
}

function FutureOrderRow({
  order,
  candidateName,
  clientId,
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
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
  onDeleted: () => void;
}

function HistoryOrderRow({
  order,
  clientId,
  canManageFinance,
  rateUnit,
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

function fmtDate(d: string | null): string | null {
  if (!d) return null;
  return d.slice(0, 10);
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
