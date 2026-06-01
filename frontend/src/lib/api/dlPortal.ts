/**
 * Klienty API dla DL Portal: framework contracts, amendments, orders,
 * my-clients, admin overview.
 */

import { api } from "@/lib/api";

// ── Types ───────────────────────────────────────────────────────────────────

export type FrameworkContractStatus =
  | "draft"
  | "pending_signature"
  | "active"
  | "expired"
  | "terminated"
  | "superseded";

export type FrameworkContractSignedVia = "upload" | "autenti";

export interface FrameworkContractRead {
  id: number;
  client_id: number;
  name: string;
  status: FrameworkContractStatus;
  effective_date: string | null;
  expiry_date: string | null;
  signed_via: FrameworkContractSignedVia;
  currency: string | null;
  parent_contract_id: number | null;
  contract_terms_id: number | null;
  filename: string | null;
  has_file: boolean;
  content_type: string | null;
  size_bytes: number | null;
  uploaded_by: number | null;
  uploaded_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  amendments_count: number;
  days_to_expiry: number | null;
}

export interface FrameworkContractListResponse {
  items: FrameworkContractRead[];
  total: number;
}

export interface FrameworkContractUpdate {
  name?: string;
  status?: FrameworkContractStatus;
  effective_date?: string | null;
  expiry_date?: string | null;
  signed_via?: FrameworkContractSignedVia;
  currency?: string | null;
  parent_contract_id?: number | null;
  contract_terms_id?: number | null;
  notes?: string | null;
}

export interface AmendmentRead {
  id: number;
  framework_contract_id: number;
  name: string;
  effective_date: string;
  changes_summary: string | null;
  old_terms: Record<string, unknown> | null;
  new_terms: Record<string, unknown> | null;
  filename: string | null;
  has_file: boolean;
  content_type: string | null;
  size_bytes: number | null;
  uploaded_by: number | null;
  uploaded_at: string | null;
  created_at: string;
  updated_at: string;
}

export type ClientOrderStatus =
  | "draft"
  | "active"
  | "paused"
  | "completed"
  | "cancelled";

export interface ClientOrderRead {
  id: number;
  client_id: number;
  contract_id: number;
  job_id: number | null;
  framework_contract_id: number | null;
  title: string;
  description: string | null;
  status: ClientOrderStatus;
  start_date: string | null;
  end_date: string | null;
  rate_client: number | null;
  total_value: string | number | null;
  currency: string | null;
  filename: string | null;
  has_file: boolean;
  content_type: string | null;
  size_bytes: number | null;
  created_by_user_id: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  // Computed:
  candidate_id: number | null;
  candidate_name: string | null;
  contract_status: string | null;
  job_title: string | null;
  monthly_margin: number | null;
  days_to_end: number | null;
}

export interface ContractWithOrdersRead {
  contract_id: number;
  candidate_id: number;
  candidate_name: string;
  contract_status: string;
  contract_start_date: string | null;
  contract_end_date: string | null;
  rate_candidate: number | null;
  initial_job_id: number | null;
  initial_job_title: string | null;
  latest_order_id: number | null;
  latest_order_end_date: string | null;
  latest_order_rate_client: number | null;
  latest_order_monthly_margin: number | null;
  days_to_latest_end: number | null;
  orders: ClientOrderRead[];
}

export interface ClientOrdersGroupedResponse {
  contractors: ContractWithOrdersRead[];
  total_contractors: number;
}

export interface ClientOrderUpdate {
  title?: string;
  description?: string | null;
  status?: ClientOrderStatus;
  start_date?: string | null;
  end_date?: string | null;
  rate_client?: number | null;
  total_value?: string | null;
  currency?: string | null;
  framework_contract_id?: number | null;
  job_id?: number | null;
  notes?: string | null;
}

export interface NewContractorOrderRequest {
  candidate_id: number;
  job_id?: number | null;
  framework_contract_id?: number | null;
  contract_start_date: string;
  contract_end_date?: string | null;
  title: string;
  order_start_date: string;
  order_end_date?: string | null;
  rate_client: number;
  rate_candidate: number;
  rate_unit?: "monthly" | "daily" | "hourly";
  billing_hours_per_month?: number;
  currency?: string;
  total_value?: number | null;
  notes?: string | null;
}

export interface NewContractorOrderResponse {
  contract_id: number;
  order_id: number;
  candidate_name: string;
  monthly_margin: number;
}

export interface MyClientRow {
  client_id: number;
  name: string;
  industry: string | null;
  is_head_dl: boolean;
  active_orders_count: number;
  total_revenue_all_time: string | number | null;
  active_revenue: string | number | null;
  expiring_soon_count: number;
  framework_contract_status: string | null;
  framework_expiry_date: string | null;
  last_activity_at: string | null;
}

export interface ExpiringAlert {
  kind: "framework_contract" | "order";
  entity_id: number;
  label: string;
  days_to_expiry: number;
  expiry_date: string;
}

export interface ClientDashboardResponse {
  client_id: number;
  client_name: string;
  total_revenue_all_time: string | number | null;
  active_revenue: string | number | null;
  completed_revenue: string | number | null;
  currency_breakdown: Record<string, string | number>;
  monthly_margin_total: number | null;
  monthly_margin_pct: number | null;
  active_consultants: number;
  completed_consultants: number;
  avg_days_to_fill: number | null;
  framework_contracts_count: number;
  active_orders_count: number;
  completed_orders_count: number;
  alerts: ExpiringAlert[];
}

export interface OverviewRow {
  client_id: number;
  name: string;
  industry: string | null;
  head_dl_id: number | null;
  head_dl_name: string | null;
  total_revenue_all_time: string | number | null;
  active_revenue: string | number | null;
  monthly_margin_total: number | null;
  active_orders_count: number;
  active_consultants: number;
  framework_status: string | null;
  framework_expiry_date: string | null;
}

export interface DlKpiRow {
  dl_user_id: number;
  dl_name: string;
  dl_email: string;
  managed_clients_count: number;
  head_clients_count: number;
  total_revenue: string | number | null;
  active_revenue: string | number | null;
  monthly_margin_total: number | null;
  active_orders_count: number;
  active_consultants: number;
}

// ── API helpers ─────────────────────────────────────────────────────────────

export const dlPortalApi = {
  // Framework contracts
  listFrameworkContracts: (clientId: number, statusFilter?: FrameworkContractStatus) =>
    api.get<FrameworkContractListResponse>(
      `/api/clients/${clientId}/framework-contracts`,
      { params: statusFilter ? { status_filter: statusFilter } : undefined }
    ),

  getFrameworkContract: (clientId: number, fcId: number) =>
    api.get<FrameworkContractRead>(`/api/clients/${clientId}/framework-contracts/${fcId}`),

  createFrameworkContract: (clientId: number, formData: FormData) =>
    api.post<FrameworkContractRead>(
      `/api/clients/${clientId}/framework-contracts`,
      formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    ),

  updateFrameworkContract: (clientId: number, fcId: number, payload: FrameworkContractUpdate) =>
    api.patch<FrameworkContractRead>(
      `/api/clients/${clientId}/framework-contracts/${fcId}`,
      payload
    ),

  deleteFrameworkContract: (clientId: number, fcId: number) =>
    api.delete(`/api/clients/${clientId}/framework-contracts/${fcId}`),

  downloadFrameworkContractUrl: (clientId: number, fcId: number) =>
    `/api/clients/${clientId}/framework-contracts/${fcId}/file`,

  // Amendments
  listAmendments: (clientId: number, fcId: number) =>
    api.get<AmendmentRead[]>(
      `/api/clients/${clientId}/framework-contracts/${fcId}/amendments`
    ),

  createAmendment: (clientId: number, fcId: number, formData: FormData) =>
    api.post<AmendmentRead>(
      `/api/clients/${clientId}/framework-contracts/${fcId}/amendments`,
      formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    ),

  deleteAmendment: (clientId: number, fcId: number, amendmentId: number) =>
    api.delete(
      `/api/clients/${clientId}/framework-contracts/${fcId}/amendments/${amendmentId}`
    ),

  // Orders (grouped by Contract – 1 kontraktor = 1 karta)
  listContractorsWithOrders: (clientId: number) =>
    api.get<ClientOrdersGroupedResponse>(`/api/clients/${clientId}/orders`),

  listActiveContractsForExtension: (clientId: number) =>
    api.get<ContractWithOrdersRead[]>(
      `/api/clients/${clientId}/contracts-with-orders`
    ),

  getOrder: (clientId: number, orderId: number) =>
    api.get<ClientOrderRead>(`/api/clients/${clientId}/orders/${orderId}`),

  /** Flow A: tworzy Order pod istniejącym Contract (przedłużenie). */
  createOrderExtension: (clientId: number, formData: FormData) =>
    api.post<ClientOrderRead>(`/api/clients/${clientId}/orders`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    }),

  /** Flow B: atomic Contract + Order create (nowy kontraktor). */
  createContractWithOrder: (
    clientId: number,
    payload: NewContractorOrderRequest
  ) =>
    api.post<NewContractorOrderResponse>(
      `/api/clients/${clientId}/contract-with-order`,
      payload
    ),

  updateOrder: (clientId: number, orderId: number, payload: ClientOrderUpdate) =>
    api.patch<ClientOrderRead>(`/api/clients/${clientId}/orders/${orderId}`, payload),

  deleteOrder: (clientId: number, orderId: number) =>
    api.delete(`/api/clients/${clientId}/orders/${orderId}`),

  downloadOrderUrl: (clientId: number, orderId: number) =>
    `/api/clients/${clientId}/orders/${orderId}/file`,

  // My clients
  listMyClients: () => api.get<MyClientRow[]>("/api/my-clients"),

  getDashboard: (clientId: number) =>
    api.get<ClientDashboardResponse>(`/api/my-clients/${clientId}/dashboard`),

  // Admin overview
  adminOverview: () => api.get<OverviewRow[]>("/api/admin/clients-overview"),
  adminByDl: () => api.get<DlKpiRow[]>("/api/admin/clients-overview/by-dl"),
};
