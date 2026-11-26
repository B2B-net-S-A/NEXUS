// Kwoty klienta ćwiczebnego na Poligonie (22.11.2026). Zestaw ma kwoty
// w całości, a ten moduł zdejmuje je tak, jak serwer zdejmuje je prawdziwym
// odpowiedziom. Poligon widzi tylko to, do czego rola ma dostęp:
//
// - kwoty klienta: `canViewClientFinance` — „view_finance” albo „Stawki i
//   kwoty: podgląd”; klient ćwiczebny jest w portfelu ćwiczącego Delivery
//   Leada (`withPracticeClient`), jak jego własni klienci;
// - redakcja kontraktu: `_redact_contract_finance` w `api/contracts.py`;
// - profil klienta: `api/clients.py` (`get_client_profile`);
// - marża na liście kontraktów dla kwot całej firmy bez „Wyników firmy”:
//   `_hide_company_margin`.

type Json = unknown;

export interface PoligonViewer {
  /** Widzi kwoty klienta ćwiczebnego. */
  amounts: boolean;
  /** Widzi marżę w wierszach listy kontraktów. */
  companyMargin: boolean;
}

interface ViewerUser {
  role?: string;
  roles?: string[] | null;
  effective_action_access?: Record<string, string> | null;
  analytics_capabilities?: string[] | null;
  capabilities?: string[] | null;
}

/** Konto bez kwot (domyślnie, gdy nie znamy osoby): bezpieczniej zdjąć niż pokazać. */
export const NO_AMOUNTS: PoligonViewer = { amounts: false, companyMargin: false };

function granted(user: ViewerUser, permission: string): boolean {
  const access = user.effective_action_access;
  if (access && "delivery_view" in access) return access[permission] === "manage";
  // Profil sprzed uprawnień: domyślne role (`lib/permission-catalog.json`).
  const roles = new Set([user.role, ...(user.roles ?? [])]);
  const defaults: Record<string, string[]> = {
    amounts_view: ["finance", "delivery_lead", "back_office"],
    company_results: [],
  };
  return roles.has("admin") || (defaults[permission] ?? []).some((r) => roles.has(r));
}

/** Lustro `access_scope.is_delivery_lead_governed`: kwoty tylko z portfela DL-a. */
function deliveryLeadGoverned(user: ViewerUser): boolean {
  const roles = new Set([user.role, ...(user.roles ?? [])]);
  return roles.has("delivery_lead") && !roles.has("admin") && !roles.has("finance");
}

export function viewerFrom(user: ViewerUser | null | undefined): PoligonViewer {
  if (!user) return NO_AMOUNTS;
  const caps = new Set([...(user.analytics_capabilities ?? []), ...(user.capabilities ?? [])]);
  const amountsView = granted(user, "amounts_view");
  // Kwoty każdego klienta (`_contract_finance_read_scope` w `api/contracts.py`):
  // „view_finance” albo podgląd kwot bez portfela Delivery Leada.
  const globalFinance = caps.has("view_finance") || (amountsView && !deliveryLeadGoverned(user));
  const amounts = globalFinance || amountsView;
  return { amounts, companyMargin: amounts && (!globalFinance || granted(user, "company_results")) };
}

/** Pola kwot w kontrakcie, profilu klienta, kolejce zamówień z maila i kartach rozliczeń. */
const MONEY = new Set([
  "rate_candidate", "rate_client", "framework_rate", "target_rate_min", "target_rate_max",
  "margin", "monthly_rate_candidate", "monthly_rate_client", "monthly_margin", "eur_pln_rate",
  "hourly_rate_client", "hourly_rate_candidate", "active_mrr", "ltv", "salary_min", "salary_max",
  "total_revenue", "rate_client_md", "rate_client_gross", "total_value", "rate_document_change",
  "net", "cost", "margin_pct", "quote", "rate", "nexus_rate", "legal_name",
]);
const SCHEDULES = new Set(["candidate_rate_schedule", "client_rate_schedule", "framework_rate_schedule"]);
/** Waluta i jednostka stawki znikają tylko z kontraktu (serwer: `_redact_contract_finance`). */
const CONTRACT_ONLY = ["currency", "rate_client_currency", "rate_candidate_currency", "rate_unit", "billing_hours_per_month"];
const ZEROED = new Set(["active_mrr_unpriced_contracts", "active_mrr_fx_missing_contracts"]);
const FLAGS = new Set(["amounts_visible", "can_see_amounts"]);

function redact(value: Json, inContract: boolean): Json {
  if (Array.isArray(value)) return value.map((v) => redact(v, inContract));
  if (!value || typeof value !== "object") return value;
  const obj = value as Record<string, Json>;
  const contract = inContract || "contract_type" in obj;
  const out: Record<string, Json> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (MONEY.has(k)) out[k] = null;
    else if (SCHEDULES.has(k)) out[k] = [];
    else if (ZEROED.has(k)) out[k] = 0;
    else if (FLAGS.has(k)) out[k] = false;
    else if (contract && CONTRACT_ONLY.includes(k)) out[k] = null;
    else out[k] = redact(v, contract && k === "group_members");
  }
  return out;
}

function hideMargin(value: Json): Json {
  const list = value as { items?: Array<Record<string, Json>> } | null;
  if (!list || !Array.isArray(list.items)) return value;
  return {
    ...list,
    items: list.items.map((item) => ({
      ...item,
      margin: null,
      monthly_margin: null,
      group_members: Array.isArray(item.group_members)
        ? (item.group_members as Array<Record<string, Json>>).map((m) => ({ ...m, margin: null }))
        : item.group_members,
    })),
  };
}

/** Odpowiedź klienta ćwiczebnego dla tej osoby: bez kwot, jeśli ich nie widzi. */
export function forViewer(path: string, data: Json, viewer: PoligonViewer): Json {
  // Zadania asystenta prawnego: serwer daje pustą listę osobie bez podglądu
  // kwot (bramka treści umowy), więc Poligon też.
  if (path === "/api/legal/tasks" && !viewer.amounts) return { items: [] };
  if (!viewer.amounts) return redact(data, false);
  if (!viewer.companyMargin && path === "/api/contracts") return hideMargin(data);
  return data;
}

/**
 * `/api/auth/me` w trybie Poligonu: klient ćwiczebny w portfelu Delivery
 * Leada, który ćwiczy (front liczy z tego `canViewClientFinance` i zakres
 * „Moich klientów”). Prawdziwe przypisania zostają bez zmian.
 */
export function withPracticeClient(me: Json, clientId: number): Json {
  if (!me || typeof me !== "object") return me;
  const user = me as Record<string, Json>;
  const scope = user.data_scope as Record<string, Json> | null | undefined;
  if (!scope || scope.kind !== "delivery_clients") return me;
  const add = (ids: Json): Json => (Array.isArray(ids) && !ids.includes(clientId) ? [...ids, clientId] : ids);
  return {
    ...user,
    data_scope: {
      ...scope,
      allowed_client_ids: add(scope.allowed_client_ids),
      ...(Array.isArray(scope.finance_client_ids) && granted(user as ViewerUser, "amounts_view")
        ? { finance_client_ids: add(scope.finance_client_ids) }
        : {}),
    },
  };
}
