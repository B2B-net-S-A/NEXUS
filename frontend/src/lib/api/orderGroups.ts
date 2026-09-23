// Zamówienia wielo-konsultantowe (BIK / Polkomtel / BNP / CP / Lotte Wedel)
// + import zużycia MD.
//
// Lista klientów objętych tym modelem NIE jest tu duplikowana. Backend liczy
// capability z konfiguracji oraz jawnych predykatów klientowych; front czyta
// gotowe flagi z odpowiedzi `GET /api/clients/{id}`.

import { api } from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";
import type { OrderType } from "@/lib/api/dlPortal";
import type { ExecutiveContractBrief } from "@/lib/api/executiveContracts";

export type { OrderType } from "@/lib/api/dlPortal";

export type OrderInputMode = "md" | "amount";

export type OrderOffboardingAction = "remove" | "transfer" | "restore";
export type OrderOffboardingRateBasis = "departing" | "recipient";

/** Trwała sprawa decyzyjna tworzona po zakończeniu kontraktu konsultanta MD.
 *
 *  Snapshoty pozwalają pokazać Delivery Leadowi dokładnie stan z chwili
 *  zakończenia współpracy, nawet jeśli zamówienie zostało później odświeżone.
 *  Pola finansowe są `null` dla ról bez VIEW_FINANCE. */
export interface OrderOffboardingCaseRead {
  id: number;
  contract_id: number;
  order_id: number;
  order_group_id: number | null;
  client_id: number;
  effective_date: string;
  status: "pending" | "resolved";
  version: number;
  uses_shared_md_pool: boolean;
  remaining_md_snapshot: number;
  rate_cost_snapshot: number | null;
  rate_revenue_snapshot: number | null;
  currency_snapshot: string | null;
  order_number_snapshot: string | null;
  resolution: OrderOffboardingAction | null;
  target_order_id: number | null;
  rate_basis: OrderOffboardingRateBasis | null;
  resolution_payload: Record<string, unknown> | null;
  resolved_at: string | null;
  resolved_by_user_id: number | null;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export type OrderOffboardingResolutionInput =
  | {
      action: "remove";
      expected_version: number;
    }
  | {
      action: "transfer";
      target_order_id: number;
      rate_basis: OrderOffboardingRateBasis;
      expected_version: number;
    }
  | {
      /** Współpraca trwa dalej — linia wraca na aktywną obsadę, pula MD
       *  zostaje nienaruszona. */
      action: "restore";
      /** Do kiedy współpraca trwa. `null` = bezterminowo, dozwolone tylko dla
       *  zamówienia bez daty zakończenia (serwer odrzuca puste pole, gdy
       *  zamówienie ma swój koniec — linia nie może go przeżyć). Oryginalna
       *  data końca linii przepadła przy offboardingu, więc to jest decyzja,
       *  nie odtworzenie. */
      restore_end_date: string | null;
      expected_version: number;
    };

export interface OrderLineRead {
  source_rate_cost?: number | null;
  source_rate_revenue?: number | null;
  rate_candidate_currency?: string | null;
  rate_client_currency?: string | null;
  id: number;
  group_id: number | null;
  contract_id: number;
  candidate_id: number | null;
  consultant_name: string;
  job_id: number | null;
  job_title: string | null;
  status: string;
  is_active: boolean;
  start_date: string | null;
  end_date: string | null;
  /** Zerowane dla ról bez uprawnień finansowych. */
  rate_cost: number | null;
  rate_revenue: number | null;
  input_value: number | null;
  input_mode: OrderInputMode | null;
  /** Liczby MD są operacyjne — widoczne także bez dostępu do stawek. */
  md_total: number | null;
  md_remaining: number | null;
  md_manual_adjustment: number | null;
  predecessor_order_id: number | null;
  predecessor_consultant_name: string | null;
  /** Zamówienie kosztowe: suma PEŁNYCH kwot faktur tej osoby.
   *  `null` = linia nie jest na zamówieniu kosztowym; `0` = jest, ale nic
   *  jeszcze nie zafakturowano (te dwa stany renderują się inaczej). */
  invoiced_total: number | null;
  /** Ile z faktur tej osoby nie zmieściło się w budżecie zamówienia. */
  unsettled_total: number | null;
  /** Ostatni zaimportowany miesiąc bez zejścia dla tej linii („2026-07"). */
  missing_consumption_month: string | null;
  /** Decyzja po zakończeniu współpracy na zamówieniu MD. `pending` oznacza,
   *  że linia zostaje oznaczona alarmowo do czasu decyzji Delivery Leada. */
  offboarding_case?: OrderOffboardingCaseRead | null;
  /** `document` — osoba z PDF-a zamówienia; `manual` — dopisana przez
   *  człowieka (ręcznie albo jako zastępstwo); `null` — sprzed ewidencji. */
  origin?: "document" | "manual" | null;
  added_by_user_id?: number | null;
  added_by_name?: string | null;
  added_at?: string | null;
  /** Za kogo ta osoba jest zastępstwem. */
  replaces_name?: string | null;
  /** Usunięta z zamówienia, ale z wykorzystaniem — zostaje widoczna, a jej
   *  zużycie nie wraca do puli. */
  removed_from_order?: boolean;
  /** Data zakończenia współpracy, gdy się skończyła (linia zostaje). */
  cooperation_ended_on?: string | null;
  /** Zaraportowane MD tej osoby na zamówieniu (operacyjne). */
  md_used?: number | null;
  /** Decyzja „Zostaw jako historię". */
  history_kept_at?: string | null;
  history_kept_by_name?: string | null;
  /** Centrum e-Zdrowia (Faza B, 09.2026): `md_total` to zakres PODSTAWOWY,
   *  a to zakres OPCJONALNY z umowy. `null` = umowa nie ma opcji — to nie to
   *  samo co `0` (opcja jest, ale pusta), więc pasek opcji renderuje się
   *  inaczej w obu przypadkach. Zużycie z wpisów miesięcznych wypełnia
   *  NAJPIERW podstawę, dopiero potem opcję. */
  md_optional_total: number | null;
  /** Ile z `md_used` przypadło na podstawę / opcję (serwer dzieli; front nie
   *  liczy tego sam, żeby dwie powierzchnie nie rozjechały się przy zmianie
   *  reguły podziału). `null` = linia bez rozbicia na zakresy. */
  md_base_used: number | null;
  md_optional_used: number | null;
  /** Linia następcy, gdy ta osoba została zastąpiona (odwrotność
   *  `predecessor_order_id`). Nazwisko obok, żeby wiersz nie musiał szukać
   *  następcy po id w liście — bywa poza obsadą aktywną. */
  replaced_by_order_id: number | null;
  replaced_by_consultant_name: string | null;
}

export type OrderGroupStatus =
  "draft" | "active" | "scheduled" | "completed" | "exhausted";

export interface OrderGroupRead {
  md_budget_mode?: "per_person" | "shared" | null;
  md_budget_mode_locked?: boolean;
  id: number;
  client_id: number;
  order_number: string;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  created_at: string;
  /** `null` oznacza historyczną grupę obsługiwaną przez dotychczasowe reguły. */
  order_type?: OrderType | null;

  status: OrderGroupStatus;
  status_label: string;
  closure_date: string | null;
  closure_reason: string | null;

  is_cost_based: boolean;
  /** Flaga przechowywania wspólnej puli; nowe zamówienia mają jawny md_budget_mode. */
  is_md_budget_based: boolean;
  /** Trzy liczby, nie jedna: kwota / wykorzystano / pozostało. Ticket nazywa
   *  „zużyciem" wartość, która maleje — czyli resztę; jedno pole podpisane
   *  „zużycie", a pokazujące resztę, myli w rozmowie o pieniądzach. */
  budget_amount: number | null;
  budget_used: number | null;
  budget_remaining: number | null;
  budget_manual_adjustment: number | null;
  md_budget_total: number | null;
  md_budget_used: number | null;
  md_budget_remaining: number | null;
  md_budget_manual_adjustment: number | null;
  predecessor_group_id: number | null;
  filename: string | null;
  has_file: boolean;
  content_type: string | null;
  size_bytes: number | null;
  file_uploaded_at: string | null;
  /** Wyliczane serwerowo — front nie zna reguły „wyczerpane blokuje dodawanie",
   *  a przycisk kończący się 409 czyta się jak „zapis nie działa". */
  can_add_consultant: boolean;

  /** Umowa wykonawcza (Centrum e-Zdrowia), pod którą wisi zamówienie.
   *  `null` u każdego innego klienta i u zamówień sprzed struktury umów. */
  executive_contract: ExecutiveContractBrief | null;
  /** Suma limitów MD wszystkich pozycji (podstawa + opcja) i suma zużycia —
   *  liczby OPERACYJNE, widoczne bez uprawnień finansowych. `null` = zamówienie
   *  bez rozbicia na zakresy (BIK/Polkomtel — nagłówek bez paska). */
  md_positions_total: number | null;
  md_used_total: number | null;
  /** Wartość umowy i wykorzystana kwota w PLN. `null` dla ról bez finansów —
   *  nagłówek pokazuje wtedy wyłącznie MD, a nie „0 zł". */
  contract_value_pln: number | null;
  used_value_pln: number | null;

  lines: OrderLineRead[];
  active_consultants: number;
  event_count: number;
  /** Zaplanowane przedłużenia, chronologicznie po dacie startu. */
  future_orders: OrderGroupRead[];
}

/** Samodzielny szkic zamówienia — zakładka „Draft (do uzupełnienia)".
 *
 *  Szkice z hooka zatrudnienia („Oznacz jako podpisane" / pipeline „hired")
 *  nie mają jeszcze grupy; przy aktywacji (komplet 4 pól z Ticketu 1) backend
 *  materializuje grupę o numerze z pola „numer zamówienia". */
export interface OrderDraftRead {
  id: number;
  contract_id: number;
  consultant_name: string;
  title: string;
  order_type?: OrderType | null;
  start_date: string | null;
  end_date: string | null;
  /** Zerowane dla ról bez uprawnień finansowych (jak w liniach). */
  rate_cost: number | null;
  rate_revenue: number | null;
  /** Liczba MD jest operacyjna — widoczna także bez dostępu do stawek. */
  md_quantity: number | null;
  created_at: string | null;
}

export interface OrderGroupListResponse {
  groups: OrderGroupRead[];
  total_groups: number;
  total_consultants: number;
  suggested_order_type?: OrderType;
  /** Szkice pokazywane przez historyczną sekcję grupową. */
  draft_orders?: OrderDraftRead[];
  total_draft_orders?: number;
}

export interface OrderGroupEvent {
  id: number;
  /** Slug z backendu. Celowo `string`, a nie unia: nieznany typ ma się
   *  wyrenderować z ikoną domyślną, a nie wywalić bundla po stronie klienta. */
  event_type: string;
  event_label: string;
  description: string;
  order_id: number | null;
  payload: Record<string, unknown> | null;
  /** Zamówienie powiązane wpisem `transfer_md`. Pola stoją OBOK `payload`,
   *  bo `payload` jest redagowany do `null` rolom bez uprawnień finansowych —
   *  a to właśnie one najczęściej oglądają tę zakładkę. Numer i id zbudowane
   *  z payloadu znikałyby więc dokładnie tym, którym mają służyć. */
  related_group_id: number | null;
  related_order_number: string | null;
  created_by_user_id: number | null;
  /** Wykonawca (UAT B50). `null` przy pustym `created_by_user_id` = zdarzenie
   *  automatyczne; `null` przy wypełnionym id = konto usunięte. */
  created_by_name: string | null;
  created_at: string;
}

/** Skąd pochodzi osoba na liście wyboru konsultanta. */
export type ConsultantOptionSource = "client_recruitment" | "nexus_base";

export interface ConsultantOption {
  candidate_id: number;
  /** `null` = osoba bez kontraktu u tego klienta; zapis linii go założy. */
  contract_id: number | null;
  full_name: string;
  first_name: string;
  last_name: string;
  source: ConsultantOptionSource;
  /** Etykieta z serwera — front jej NIE tłumaczy, żeby nie rozjechała się
   *  z tekstem zapisywanym do historii zamówienia. */
  source_label: string;
  job_title: string | null;
  /** Legacy: kanoniczna podpowiedź w PLN/MD. Semantyka pozostaje niezmienna,
   *  żeby starszy frontend był bezpieczny podczas wdrożenia mieszanego. */
  suggested_rate_cost: number | null;
  /** Surowa efektywna stawka z kontraktu. Nowy frontend wybiera ją tylko, gdy
   *  pole faktycznie istnieje; w przeciwnym razie używa legacy PLN/MD wyżej. */
  suggested_contract_rate_cost?: number | null;
  /** Jednostka i waluta surowej podpowiedzi. */
  suggested_rate_cost_unit?: "hourly" | "daily" | "monthly" | null;
  suggested_rate_cost_currency?: string | null;
  /** Kurs jednej jednostki waluty kontraktu do PLN, używany dopiero przy
   *  zapisie kanonicznej stawki linii w PLN/MD. */
  suggested_rate_cost_rate_to_pln?: number | null;
  /** Inne kontrakty tej osoby u TEGO klienta mają różne stawki kosztowe. */
  has_different_client_contract_rates: boolean;
}

export interface ConsultantOptionsResponse {
  options: ConsultantOption[];
  /** Wszyscy pasujący, także poza `limit` — służy do ostrzeżenia o przycięciu. */
  total: number;
}

/** Kontrakt u klienta dopasowany (albo do wyboru) do osoby z PDF-a. */
export interface OrderPlanContract {
  contract_id: number;
  candidate_id: number;
  /** Zapis dokładnie z kontraktu — z dopiskiem, jeśli jest („Active …"). */
  contractor_name: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
  rate_cost: number | null;
  rate_cost_unit: "hourly" | "daily" | "monthly" | null;
  rate_cost_currency: string | null;
  rate_cost_rate_to_pln: number | null;
  rate_cost_per_md_pln: number | null;
  /** Kontrakt ZAKOŃCZONY: komunikat „nie ma już aktywnej współpracy" (ten sam
   *  co przy odznace „Zakończył współpracę"). Wybór takiego kontraktu z listy
   *  prowadzi do pytania zostaw / wznów / zastąp / usuń, nie do cichego wznowienia. */
  inactive_reason?: string | null;
}

/** Wynik dopasowania osoby z dokumentu do kontraktu (odznaka karty). */
export type OrderPlanMatchStatus =
  | "auto"
  | "confirm"
  | "ambiguous"
  /** Osoba jest w systemie, ale jej współpraca u klienta jest zakończona. */
  | "inactive"
  | "none";

/** Jedna pozycja osobowa z PDF-a — karta konsultanta w oknie. */
export interface OrderPlanLine {
  ordinal: number;
  document_name: string | null;
  /** Numer pozycji tabeli PDF-a („10") — `null`, gdy nie dało się go ustalić. */
  position_label: string | null;
  rate_revenue: number | null;
  rate_revenue_unit: "hour" | "day" | "month" | null;
  rate_revenue_gross: number | null;
  md_total: number | null;
  start_date: string | null;
  end_date: string | null;
  match_status: OrderPlanMatchStatus;
  match_reason: string;
  contract: OrderPlanContract | null;
  options: OrderPlanContract[];
  nearest_names: string[];
  warnings: string[];
}

/** `POST /order-groups/extract` — całe zamówienie z jednego PDF-a. */
export interface OrderGroupExtraction {
  order_number: string | null;
  start_date: string | null;
  end_date: string | null;
  total_value: number | null;
  currency: string | null;
  md_total: number | null;
  suggested_order_type: OrderType;
  client_policy: string | null;
  consultant_ref: string | null;
  title_needs_review: boolean;
  /** Reguła klienta mówi „bezterminowo" (BIK) — brak daty końca to odczyt,
   *  nie jego brak; formularz czyści pole „do". */
  open_ended?: boolean;
  /** Wariant liczby MD w dokumencie: przy każdej osobie albo jedna liczba na
   *  całe zamówienie. `null` = dokument MD nie podaje (zamówienie kosztowe). */
  md_scope?: "per_consultant" | "order" | null;
  document_incomplete: boolean;
  uncertain: boolean;
  uncertain_reasons: string[];
  lines: OrderPlanLine[];
}

export interface OrderLineInput {
  rate_candidate_currency?: string | null;
  rate_client_currency?: string | null;
  /** Dokładnie jedno z pól: kontrakt u tego klienta ALBO osoba z bazy Nexus. */
  contract_id?: number | null;
  candidate_id?: number | null;
  rate_cost: number;
  rate_revenue: number;
  /** Budżet MD per linia. Pomijany na zamówieniu KOSZTOWYM i zachowanych
   *  istniejących wspólnych pulach MD. */
  input_mode?: OrderInputMode | null;
  input_value?: number | null;
  /** Zakres opcjonalny MD z umowy (CeZ). `null`/pominięte = brak opcji. */
  optional_md?: number | null;
  start_date: string;
  end_date?: string | null;
  job_id?: number | null;
  /** Osoba z zakończoną współpracą zostaje na zamówieniu jako historia —
   *  linia powstaje zakończona, z datą końca udziału w `end_date`. */
  historical?: boolean;
  /** Imię i nazwisko tak, jak w PDF-ie — linia pochodzi z dokumentu. */
  document_name?: string | null;
  /** Osoba z dokumentu, za którą ta linia jest zastępstwem. */
  replaces_name?: string | null;
  /** Linia tego zamówienia, za którą ta osoba jest zastępstwem. */
  replaces_order_id?: number | null;
}

export interface OrderGroupInput {
  md_consumption_month?: string;
  md_consumption_value?: number;
  status?: "draft" | "active";
  md_budget_mode?: "per_person" | "shared" | null;
  md_budget_mode_locked?: boolean;
  order_type?: Exclude<OrderType, "periodic">;
  order_number: string;
  start_date: string;
  end_date?: string | null;
  notes?: string | null;
  is_cost_based?: boolean;
  /** Wspólna pula MD na poziomie zamówienia. */
  is_md_budget_based?: boolean;
  budget_amount?: number | null;
  md_budget_total?: number | null;
  lines?: OrderLineInput[];
  /** Umowa wykonawcza (wymagana u Centrum e-Zdrowia, 422 u innych). */
  executive_contract_id?: number | null;
}

export interface OrderGroupPatch {
  md_consumption_month?: string;
  md_consumption_value?: number;
  status?: "draft" | "active";
  md_budget_mode?: "per_person" | "shared" | null;
  md_budget_mode_locked?: boolean;
  order_number?: string;
  start_date?: string;
  end_date?: string | null;
  notes?: string | null;
  budget_amount?: number | null;
  budget_manual_adjustment?: number | null;
  md_budget_total?: number | null;
  md_budget_manual_adjustment?: number | null;
}

export interface OrderGroupCloseInput {
  closure_date: string;
  closure_reason?: string | null;
}

export interface OrderGroupExtendInput {
  order_number: string;
  start_date: string;
  end_date?: string | null;
  notes?: string | null;
  budget_amount?: number | null;
  md_budget_total?: number | null;
  lines?: OrderLineInput[];
}

export interface OrderLinePatch {
  rate_candidate_currency?: string | null;
  rate_client_currency?: string | null;
  rate_cost?: number;
  rate_revenue?: number;
  input_mode?: OrderInputMode;
  input_value?: number;
  /** `null` zdejmuje zakres opcjonalny z linii. */
  optional_md?: number | null;
  end_date?: string | null;
  md_remaining?: number;
}

// ── Rozliczenia miesięczne linii MD (CeZ) ───────────────────────────────────

export type LineConsumptionStatus = "accepted" | "protocol";

/** Jeden miesiąc zużycia MD osoby na zamówieniu. `status` jest etapem
 *  rozliczenia u klienta (protokół → akceptacja), nie stanem importu. Etykiety
 *  PL żyją w warstwie prezentacji (`LineMonthlyHistoryDialog`), NIE tutaj —
 *  testy mockują `@/lib/api` w całości, więc stałe stąd wychodziłyby w nich
 *  jako `undefined`. */
export interface LineConsumptionRow {
  period_month: string;
  md_reported: number;
  status: LineConsumptionStatus | null;
  note: string | null;
  source: "import" | "manual";
  import_id: number | null;
  created_by_name: string | null;
  updated_at: string | null;
}

export interface LineConsumptionsResponse {
  rows: LineConsumptionRow[];
}

export interface LineConsumptionUpsert {
  md_reported: number;
  status?: LineConsumptionStatus | null;
  note?: string | null;
}

export interface SwapConsultantInput {
  contract_id: number;
  rate_cost: number;
  rate_revenue: number;
  swap_date: string;
}

// ── Import MD (moduł Finanse) ───────────────────────────────────────────────

/** `cost_only` (FIN-MD-06): wiersz z samą fakturą, bez liczby MD. */
export type ImportRowStatus =
  | "applied"
  | "needs_assignment"
  | "unmatched"
  | "cost_only";

/** Wynik dopasowania KOSZTOWEGO — niezależny od `status` (dopasowanie MD po
 *  nazwisku). `null` = wiersz nie dotyczy zamówień kosztowych, co jest czym
 *  innym niż „nie udało się dopasować". */
export type ImportCostStatus =
  | "applied"
  | "unmatched_number"
  | "unmatched_consultant"
  /** FIN-MD-06: korekta faktury / kwota ≤ 0 — do ręcznego rozliczenia. */
  | "non_positive_amount";

export interface ImportLineOption {
  order_id: number;
  order_number: string;
  client_id: number;
  client_name: string;
  consultant_name: string;
  md_remaining: number | null;
}

export interface ImportRow {
  id: number;
  row_number: number;
  consultant_name: string;
  md_reported: number;
  status: ImportRowStatus;
  status_label: string;
  matched_order_id: number | null;
  matched: ImportLineOption | null;
  options: ImportLineOption[];
  resolved_at: string | null;
  notes_raw: string | null;
  order_number_hint: string | null;
  invoice_amount: number | null;
  cost_status: ImportCostStatus | null;
  cost_status_label: string | null;
}

export interface ImportSummary {
  id: number;
  period_month: string;
  filename: string | null;
  rows_total: number;
  rows_applied: number;
  rows_ambiguous: number;
  rows_unmatched: number;
  rows_cost_applied: number;
  rows_cost_unmatched: number;
  uploaded_by_user_id: number | null;
  created_at: string;
}

export interface ImportDetail extends ImportSummary {
  rows: ImportRow[];
  skipped_rows: Array<{
    row: number;
    reason: string;
    consultant_name?: string;
  }>;
  sheet_name: string | null;
}

export type PolkomtelReprocessTargetKind = "md_line" | "shared_md" | "cost";

export interface PolkomtelReprocessTarget {
  kind: PolkomtelReprocessTargetKind;
  order_id: number | null;
  group_id: number;
  order_number: string;
  row_ids: number[];
  row_ids_to_update: number[];
  /** Decimal z backendu może być serializowany jako string zależnie od kodeka. */
  current_value: number | string | null;
  expected_value: number | string;
  write_required: boolean;
}

export interface PolkomtelReprocessResponse {
  import_id: number;
  period_month: string;
  client_id: number;
  applied: boolean;
  rows_scanned: number;
  rows_to_update: number;
  targets_to_recalculate: number;
  conflicts: string[];
  targets: PolkomtelReprocessTarget[];
}

export const orderGroupsApi = {
  list: (clientId: number) =>
    api.get<OrderGroupListResponse>(`/api/clients/${clientId}/order-groups`),

  create: (clientId: number, payload: OrderGroupInput) =>
    api.post<OrderGroupRead>(`/api/clients/${clientId}/order-groups`, payload),

  update: (clientId: number, groupId: number, payload: OrderGroupPatch) =>
    api.patch<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}`,
      payload,
    ),

  /** Kasuje zamówienie WRAZ z liniami. Linia z historią (plik PO, zużycie MD,
   *  faktury) jest odpinana od zamówienia, nie kasowana — decyduje o tym
   *  serwer, front nie musi znać tej reguły. */
  remove: (clientId: number, groupId: number) =>
    api.delete(`/api/clients/${clientId}/order-groups/${groupId}`),

  removeLine: (clientId: number, groupId: number, lineId: number) =>
    api.delete(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}`,
    ),

  close: (clientId: number, groupId: number, payload: OrderGroupCloseInput) =>
    api.post<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/close`,
      payload,
    ),

  reopen: (clientId: number, groupId: number) =>
    api.post<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/reopen`,
      {},
    ),

  extend: (clientId: number, groupId: number, payload: OrderGroupExtendInput) =>
    api.post<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/extend`,
      payload,
    ),

  replaceFile: (clientId: number, groupId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.put<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/file`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
  },

  deleteFile: (clientId: number, groupId: number) =>
    api.delete(`/api/clients/${clientId}/order-groups/${groupId}/file`),

  /** „Zczytaj i uzupełnij całe zamówienie" — jeden odczyt PDF-a dla
   *  wszystkich osób, z dopasowaniem do kontraktów. Nic nie zapisuje. */
  extractPlan: (clientId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.post<OrderGroupExtraction>(
      `/api/clients/${clientId}/order-groups/extract`,
      form,
      {
        // Bez jawnego nagłówka instancja wysłałaby FormData jako JSON (422).
        headers: { "Content-Type": "multipart/form-data" },
        // Model czyta cały dokument — domyślne 30 s jest skrojone pod CRUD-y.
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      },
    );
  },

  /** Kogo można dołożyć do zamówienia: osoby z kontraktem u tego klienta
   *  ORAZ pozostali aktywni konsultanci z bazy — jedna lista, z etykietą
   *  pochodzenia przy każdej pozycji. Filtrowanie po `q` robi SERWER, więc
   *  ostrzeżenie o przycięciu (`total`) dotyczy wyniku wyszukiwania, a nie
   *  przypadkowego okna pobranych wierszy. */
  consultantOptions: (clientId: number, q: string, limit = 100) =>
    api.get<ConsultantOptionsResponse>(
      `/api/clients/${clientId}/order-groups/consultant-options`,
      { params: { q, limit } },
    ),

  addLine: (clientId: number, groupId: number, payload: OrderLineInput) =>
    api.post<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines`,
      payload,
    ),

  /** „Uzupełnij zamówienie" z PDF-a — osoby z dokumentu razem albo wcale. */
  addLines: (clientId: number, groupId: number, lines: OrderLineInput[]) =>
    api.post<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/batch`,
      { lines },
    ),

  /** „Zostaw jako historię" — osoba z zakończoną współpracą zostaje
   *  na zamówieniu; zapis kto i kiedy zdecydował. */
  keepLineHistory: (clientId: number, groupId: number, lineId: number) =>
    api.post<void>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}/keep-history`,
    ),

  updateLine: (
    clientId: number,
    groupId: number,
    lineId: number,
    payload: OrderLinePatch,
  ) =>
    api.patch<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}`,
      payload,
    ),

  swapLine: (
    clientId: number,
    groupId: number,
    lineId: number,
    payload: SwapConsultantInput,
  ) =>
    api.post<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}/swap`,
      payload,
    ),

  /** Wpisy miesięczne jednej linii MD (podgląd i ręczna korekta). */
  listConsumptions: (clientId: number, groupId: number, lineId: number) =>
    api.get<LineConsumptionsResponse>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}/consumptions`,
    ),

  /** Upsert po miesiącu — powtórka miesiąca NADPISUJE wpis (ten sam mechanizm
   *  idempotencji co import z Finansów). Zwraca linię z przeliczonym zużyciem. */
  putConsumption: (
    clientId: number,
    groupId: number,
    lineId: number,
    periodMonth: string,
    payload: LineConsumptionUpsert,
  ) =>
    api.put<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}/consumptions/${periodMonth}`,
      payload,
    ),

  deleteConsumption: (
    clientId: number,
    groupId: number,
    lineId: number,
    periodMonth: string,
  ) =>
    api.delete<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}/consumptions/${periodMonth}`,
    ),

  resolveOffboardingCase: (
    clientId: number,
    groupId: number,
    caseId: number,
    payload: OrderOffboardingResolutionInput,
  ) =>
    api.post<OrderOffboardingCaseRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/offboarding-cases/${caseId}/resolve`,
      payload,
    ),

  events: (clientId: number, groupId: number) =>
    api.get<{ events: OrderGroupEvent[] }>(
      `/api/clients/${clientId}/order-groups/${groupId}/events`,
    ),
};

export const mdConsumptionApi = {
  listImports: (limit = 100) =>
    api.get<{ imports: ImportSummary[] }>("/api/md-consumption/imports", {
      params: { limit },
    }),

  getImport: (importId: number) =>
    api.get<ImportDetail>(`/api/md-consumption/imports/${importId}`),

  upload: (file: File, periodMonth: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("period_month", periodMonth);
    return api.post<ImportDetail>("/api/md-consumption/imports", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  assignRow: (importId: number, rowId: number, orderId: number) =>
    api.post<ImportRow>(
      `/api/md-consumption/imports/${importId}/rows/${rowId}/assign`,
      { order_id: orderId },
    ),

  reprocessPolkomtel: (importId: number, apply = false) =>
    api.post<PolkomtelReprocessResponse>(
      `/api/md-consumption/imports/${importId}/reprocess-polkomtel`,
      { apply },
    ),
};
