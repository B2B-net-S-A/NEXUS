import type {
  ContractStatusValue,
  ContractTypeValue,
} from "@/lib/filter-options";

export interface ContractsListState {
  search: string;
  statusFilter: ContractStatusValue[];
  typeFilter: ContractTypeValue[];
  endingSoon: boolean;
  page: number;
}

export interface ParsedContractsListState {
  state: ContractsListState;
  /**
   * `false` means a fresh, queryless module entry. Only an explicit list URL
   * is eligible for restoring the previous scroll position.
   */
  explicit: boolean;
}

export interface ContractsReturnContext {
  fromContracts: boolean;
  hasReturnTarget: boolean;
  returnTarget: string;
}

export type ContractorsTab = "draft" | "active" | "ending";

export interface ContractorsListState {
  tab: ContractorsTab;
  page: number;
}

export interface ClientContractRegisterState {
  search: string;
  statusFilter: ContractStatusValue[];
  periodFrom: string;
  periodTo: string;
  subcategoryFilter: string[];
  page: number;
}

const LIST_PARAM_NAMES = [
  "q",
  "status",
  "contract_type",
  "ending",
  "page",
] as const;

const CONTRACT_STATUS_VALUES = new Set<ContractStatusValue>([
  "draft",
  "active",
  "ending",
  "ended",
]);

const CONTRACT_TYPE_VALUES = new Set<ContractTypeValue>([
  "b2b",
  "uop",
  "uzlecenie",
]);

const CONTRACTOR_TABS = new Set<ContractorsTab>([
  "draft",
  "active",
  "ending",
]);

const SCROLL_STORAGE_PREFIX = "nexus:contracts-list-scroll:";
const SCROLL_MAX_AGE_MS = 30 * 60 * 1000;

function uniqueValues<T>(values: T[]): T[] {
  return [...new Set(values)];
}

function positivePage(raw: string | null): number {
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}

/**
 * Queryless `/contracts` is deliberately a fresh session and therefore starts
 * at Active. `status=all` is an explicit sentinel: without it an intentionally
 * cleared status filter would be indistinguishable from a new module entry.
 */
export function parseContractsListState(
  search: string,
): ParsedContractsListState {
  const params = new URLSearchParams(search);
  const explicit = LIST_PARAM_NAMES.some((name) => params.has(name));
  const rawStatuses = params.getAll("status");
  const wantsAllStatuses = rawStatuses.includes("all");
  const validStatuses = uniqueValues(
    rawStatuses.filter((value): value is ContractStatusValue =>
      CONTRACT_STATUS_VALUES.has(value as ContractStatusValue),
    ),
  );
  const endingSoon = params.get("ending") === "30";

  return {
    explicit,
    state: {
      search: params.get("q") ?? "",
      statusFilter: wantsAllStatuses
        ? []
        : validStatuses.length > 0
          ? validStatuses
          : endingSoon
            ? []
            : ["active"],
      typeFilter: uniqueValues(
        params
          .getAll("contract_type")
          .filter((value): value is ContractTypeValue =>
            CONTRACT_TYPE_VALUES.has(value as ContractTypeValue),
          ),
      ),
      endingSoon,
      page: positivePage(params.get("page")),
    },
  };
}

/**
 * Serialises only the global-register state owned by this view. Status is
 * always present so a return URL can never be mistaken for a fresh entry, and
 * parameters from the operations/client-register views cannot leak into it.
 */
export function buildContractsListUrl(
  state: ContractsListState,
): string {
  const params = new URLSearchParams();

  if (state.statusFilter.length > 0) {
    state.statusFilter.forEach((status) => params.append("status", status));
  } else {
    params.set("status", "all");
  }
  state.typeFilter.forEach((type) => params.append("contract_type", type));
  if (state.search) params.set("q", state.search);
  if (state.endingSoon) params.set("ending", "30");
  if (state.page > 1) params.set("page", String(state.page));

  const query = params.toString();
  return `/contracts${query ? `?${query}` : ""}`;
}

export function parseContractorsListState(search: string): {
  state: ContractorsListState;
  explicit: boolean;
} {
  const params = new URLSearchParams(search);
  const rawTab = params.get("tab");
  return {
    explicit:
      params.has("tab") ||
      params.has("contractors_page"),
    state: {
      tab: CONTRACTOR_TABS.has(rawTab as ContractorsTab)
        ? (rawTab as ContractorsTab)
        : "active",
      page: positivePage(params.get("contractors_page")),
    },
  };
}

export function buildContractorsListUrl(state: ContractorsListState): string {
  const params = new URLSearchParams({
    view: "operations",
    tab: state.tab,
  });
  if (state.page > 1) params.set("contractors_page", String(state.page));
  return `/contracts?${params.toString()}`;
}

function validIsoDate(raw: string | null): string {
  return raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : "";
}

export function parseClientContractRegisterState(search: string): {
  state: ClientContractRegisterState;
  explicit: boolean;
} {
  const params = new URLSearchParams(search);
  const rawStatuses = params.getAll("register_status");
  const wantsAllStatuses = rawStatuses.includes("all");
  const validStatuses = uniqueValues(
    rawStatuses.filter((value): value is ContractStatusValue =>
      CONTRACT_STATUS_VALUES.has(value as ContractStatusValue),
    ),
  );
  return {
    explicit: [
      "register_q",
      "register_status",
      "register_period_from",
      "register_period_to",
      "register_subcategory",
      "register_page",
    ].some((name) => params.has(name)),
    state: {
      search: params.get("register_q") ?? "",
      statusFilter: wantsAllStatuses ? [] : validStatuses,
      periodFrom: validIsoDate(params.get("register_period_from")),
      periodTo: validIsoDate(params.get("register_period_to")),
      subcategoryFilter: uniqueValues(
        params
          .getAll("register_subcategory")
          .map((value) => value.trim())
          .filter(Boolean),
      ),
      page: positivePage(params.get("register_page")),
    },
  };
}

export function buildClientContractRegisterUrl(
  clientId: number,
  clientName: string | undefined,
  state: ClientContractRegisterState,
): string {
  const params = new URLSearchParams({ client: String(clientId) });
  if (clientName) params.set("clientName", clientName);
  if (state.search) params.set("register_q", state.search);
  if (state.statusFilter.length > 0) {
    state.statusFilter.forEach((status) =>
      params.append("register_status", status),
    );
  } else {
    params.set("register_status", "all");
  }
  if (state.periodFrom) {
    params.set("register_period_from", state.periodFrom);
  }
  if (state.periodTo) params.set("register_period_to", state.periodTo);
  state.subcategoryFilter.forEach((subcategory) =>
    params.append("register_subcategory", subcategory),
  );
  if (state.page > 1) params.set("register_page", String(state.page));
  return `/contracts?${params.toString()}`;
}

function validatedContractsReturnTarget(raw: string | null): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return null;
  try {
    const base = new URL("https://nexus.invalid");
    const parsed = new URL(raw, base);
    if (parsed.origin !== base.origin || parsed.pathname !== "/contracts") {
      return null;
    }
    const params = parsed.searchParams;
    if (params.get("view") === "operations") {
      return buildContractorsListUrl(parseContractorsListState(parsed.search).state);
    }
    const clientId = Number(params.get("client"));
    if (Number.isInteger(clientId) && clientId > 0) {
      return buildClientContractRegisterUrl(
        clientId,
        params.get("clientName") ?? undefined,
        parseClientContractRegisterState(parsed.search).state,
      );
    }
    return buildContractsListUrl(parseContractsListState(parsed.search).state);
  } catch {
    return null;
  }
}

export function safeContractsReturnTarget(raw: string | null): string {
  return validatedContractsReturnTarget(raw) ?? "/contracts";
}

export function parseContractsReturnContext(
  search: string,
): ContractsReturnContext {
  const params = new URLSearchParams(search);
  const fromContracts = params.get("from") === "contracts";
  const validatedTarget = validatedContractsReturnTarget(params.get("returnTo"));
  return {
    fromContracts,
    hasReturnTarget: validatedTarget !== null,
    returnTarget: validatedTarget ?? "/contracts",
  };
}

export function buildContractDetailHref(
  contractId: number,
  returnTarget: string,
  source: "contracts" | "contractors" | "client-register" = "contracts",
): string {
  const params = new URLSearchParams({
    from: source,
    returnTo: safeContractsReturnTarget(returnTarget),
  });
  return `/contracts/${contractId}?${params.toString()}`;
}

export function rememberContractsListScroll(returnTarget: string): void {
  if (typeof window === "undefined") return;
  try {
    const scrollContainer = document.getElementById("main");
    window.sessionStorage.setItem(
      `${SCROLL_STORAGE_PREFIX}${safeContractsReturnTarget(returnTarget)}`,
      JSON.stringify({
        y: scrollContainer?.scrollTop ?? window.scrollY,
        savedAt: Date.now(),
      }),
    );
  } catch {
    // Storage can be disabled by the browser. URL state still restores the
    // filters/page; scroll restoration then falls back to browser behaviour.
  }
}

export function restoreContractsListScroll(y: number): void {
  if (typeof window === "undefined") return;
  const scrollContainer = document.getElementById("main");
  if (scrollContainer) {
    scrollContainer.scrollTop = y;
    return;
  }
  window.scrollTo(0, y);
}

export function takeContractsListScroll(returnTarget: string): number | null {
  if (typeof window === "undefined") return null;
  const key = `${SCROLL_STORAGE_PREFIX}${safeContractsReturnTarget(returnTarget)}`;
  try {
    const raw = window.sessionStorage.getItem(key);
    window.sessionStorage.removeItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { y?: unknown; savedAt?: unknown };
    if (
      typeof parsed.y !== "number" ||
      parsed.y < 0 ||
      typeof parsed.savedAt !== "number" ||
      Date.now() - parsed.savedAt > SCROLL_MAX_AGE_MS
    ) {
      return null;
    }
    return parsed.y;
  } catch {
    return null;
  }
}
