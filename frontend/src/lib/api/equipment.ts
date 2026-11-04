// „Ludzie w NEXUSIE” — Sprzęt i protokoły recepcji (kroki S1–S3).
//
// Lustro `backend/app/api/equipment.py`. Wartości techniczne (kategorie,
// stany, decyzje importu) są po polsku w ASCII jak w bazie; etykiety
// interfejsu w `components/equipment/equipment-format.ts`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  downloadAuthenticatedFile,
  downloadBlob,
  fetchAuthenticatedDownload,
} from "@/lib/authenticated-files";

export type EquipmentCategory =
  | "laptop"
  | "telefon"
  | "monitor"
  | "karta_sim"
  | "karta_dostepu"
  | "akcesorium"
  | "inne";
export type EquipmentItemStatus =
  | "na_stanie"
  | "wydany"
  | "serwis"
  | "wycofany"
  | "zgubiony";
export type EquipmentOwnership = "nasz" | "klienta";
/** Posiadacz: konto, kontrakt, osoba spoza NEXUSA albo uczestnik Akademii (id zgłoszenia). */
export type EquipmentHolderKind = "user" | "contract" | "external" | "academy";
export type ReturnCondition = "sprawny" | "uszkodzony" | "niekompletny" | "zgubiony";
export type ProtocolKind = "wydanie" | "zwrot";
export type ProtocolStatus = "oczekuje" | "podpisany" | "potwierdzony" | "anulowany";
export type SignatureMethod = "brak" | "link" | "papier" | "profil_zaufany";
export type EquipmentTaskKind = "wydanie" | "zwrot" | "podpis" | "zakup";
export type EquipmentTaskStatus = "otwarte" | "zrobione" | "anulowane";
export type ImportDecision = "przyjmij" | "pomin" | "konflikt" | "do_wyjasnienia";
export type EquipmentProvider = "nasz" | "klienta" | "nieznany";

export interface EquipmentModel {
  id: number;
  category: EquipmentCategory;
  name: string;
  manufacturer: string | null;
  price_pln: string | null;
  is_active: boolean;
  items?: number;
}

export interface EquipmentHolderRef {
  kind: EquipmentHolderKind;
  id: number;
  name: string;
  client_name?: string | null;
  assignment_id?: number;
  issued_at?: string | null;
}

export interface EquipmentHolder {
  kind: EquipmentHolderKind;
  id: number;
  name: string;
  email: string | null;
  detail: string | null;
}

export interface EquipmentItem {
  id: number;
  model: EquipmentModel;
  category: EquipmentCategory;
  inventory_number: string | null;
  serial_number: string | null;
  imei: string | null;
  iccid: string | null;
  phone_number: string | null;
  access_card_number: string | null;
  status: EquipmentItemStatus;
  ownership: EquipmentOwnership;
  purchase_date: string | null;
  location: string | null;
  notes: string | null;
  holder: EquipmentHolderRef | null;
  issue_protocol: { id: number; number: string; status: ProtocolStatus } | null;
}

export interface AssignmentRow {
  assignment_id: number;
  item_id: number;
  category: EquipmentCategory;
  model_name: string;
  inventory_number: string | null;
  serial_number: string | null;
  imei: string | null;
  phone_number: string | null;
  access_card_number: string | null;
  ownership: EquipmentOwnership;
  item_status: EquipmentItemStatus;
  holder: { kind: EquipmentHolderKind; id: number; name: string; client_name: string | null };
  issued_at: string;
  returned_at: string | null;
  return_condition: ReturnCondition | null;
  return_notes: string | null;
  issue_protocol: string | null;
  issue_protocol_id: number | null;
  return_protocol: string | null;
  return_protocol_id: number | null;
  unit_value: string | null;
}

export interface EquipmentItemDetail extends EquipmentItem {
  history: AssignmentRow[];
}

export interface ProtocolRef {
  id: number;
  number: string;
  kind: ProtocolKind;
  status: ProtocolStatus;
  protocol_date: string;
}

export interface HolderEquipment {
  active: AssignmentRow[];
  history: AssignmentRow[];
  protocols: ProtocolRef[];
}

export interface ProtocolLine {
  position: number;
  item_id: number | null;
  category: EquipmentCategory;
  name: string;
  identifier: string | null;
  quantity: number;
  unit_value: string | null;
  condition: ReturnCondition | null;
  notes: string | null;
  /** Szczegół wydania: nazwa z rejestru i dodatki recepcji (``null`` = dodatków nie da się poprawić). */
  base_name?: string | null;
  accessories?: string | null;
}

export interface EquipmentProtocol {
  id: number;
  kind: ProtocolKind;
  number: string;
  protocol_date: string;
  holder: { kind: EquipmentHolderKind | null; id: number | null; name: string; email: string | null };
  issuer_name: string;
  total_value: string;
  status: ProtocolStatus;
  signature_method: SignatureMethod;
  signed_at: string | null;
  signer_name: string | null;
  has_signed_file: boolean;
  confirmed_at: string | null;
  cancelled_at?: string | null;
  cancel_reason?: string | null;
  template_version: string;
  created_at: string | null;
  link: { expires_at: string; used_at: string | null; created_at: string | null } | null;
  lines?: ProtocolLine[];
}

export interface EquipmentTask {
  id: number;
  kind: EquipmentTaskKind;
  status: EquipmentTaskStatus;
  title: string;
  due_on: string | null;
  overdue_days: number;
  holder: { kind: EquipmentHolderKind | null; id: number | null; name: string | null };
  /**
   * `categories` = skład protokołu (ikony w agendzie „Do zrobienia”);
   * `client_name` i `link_sent_on` (dzień ostatniego linku) — druga linia zadania podpisu.
   */
  protocol: {
    id: number;
    number: string;
    status?: ProtocolStatus;
    categories?: EquipmentCategory[];
    client_name?: string | null;
    link_sent_on?: string | null;
  } | null;
  details: Record<string, unknown>;
}

export interface EquipmentSummary {
  free_by_category: Record<EquipmentCategory, number>;
  by_status: Record<EquipmentItemStatus, number>;
  /** Stan per kategoria (kafle „Ewidencji”: wydane / wolne / serwis). */
  by_category?: Record<EquipmentCategory, Record<EquipmentItemStatus, number>>;
  protocols_waiting: number;
  /** Data najstarszego protokołu, który czeka na podpis albo potwierdzenie. */
  oldest_waiting_on?: string | null;
  /** Sztuki wydane z protokołem bez podpisu (chip „Bez podpisu”). */
  unsigned_items?: number;
  import_unresolved: number;
}

export interface ImportBatch {
  id: number;
  file_name: string;
  status: "nowa" | "zatwierdzona";
  summary: {
    sheets?: { name: string; header_row: number | null; rows: number; skipped: string | null }[];
    removed_columns?: { sheet: string; column: string; reason: string }[];
    ignored_columns?: { sheet: string; column: string }[];
    removed_values?: Record<string, number>;
    counts?: Partial<Record<ImportDecision, number>>;
  };
  created_at: string | null;
  applied_at: string | null;
  pending: number | null;
}

export interface ImportRowData {
  category?: EquipmentCategory;
  model?: string;
  inventory_number?: string | null;
  serial_number?: string | null;
  imei?: string | null;
  iccid?: string | null;
  phone_number?: string | null;
  access_card_number?: string | null;
  holder_text?: string | null;
  project?: string | null;
  status_text?: string | null;
  notes?: string | null;
  item_status?: EquipmentItemStatus;
}

export interface ImportRow {
  id: number;
  sheet: string;
  row_number: number;
  data: ImportRowData;
  decision: ImportDecision;
  reason: string | null;
  holder_user_id: number | null;
  holder_contract_id: number | null;
  holder_name: string | null;
  item_id: number | null;
  applied: boolean;
}

export interface ItemFilters {
  category?: EquipmentCategory | "";
  status?: EquipmentItemStatus | "";
  holder?: "none" | EquipmentHolderKind | "";
  q?: string;
  free?: boolean;
  /** Wydane z protokołem, który czeka na podpis albo potwierdzenie. */
  unsigned?: boolean;
  /** Ile pozycji naraz (serwer: 200 domyślnie, najwyżej 500). */
  limit?: number;
}

export interface ItemInput {
  model_id?: number;
  inventory_number?: string | null;
  serial_number?: string | null;
  imei?: string | null;
  iccid?: string | null;
  phone_number?: string | null;
  access_card_number?: string | null;
  ownership?: EquipmentOwnership;
  purchase_date?: string | null;
  location?: string | null;
  notes?: string | null;
  status?: EquipmentItemStatus;
}

export interface IssueInput {
  holder_kind: EquipmentHolderKind;
  holder_id: number;
  protocol_date?: string | null;
  lines: { item_id: number; unit_value?: string | null; accessories?: string | null }[];
  send_link: boolean;
}

export interface ReturnInput {
  protocol_date?: string | null;
  lines: { assignment_id: number; condition: ReturnCondition; notes?: string | null }[];
}

const BASE = "/api/equipment";

export const equipmentKeys = {
  all: ["equipment"] as const,
  summary: ["equipment", "summary"] as const,
  models: ["equipment", "models"] as const,
  items: (filters: ItemFilters) => ["equipment", "items", filters] as const,
  item: (id: number) => ["equipment", "item", id] as const,
  holders: (q: string) => ["equipment", "holders", q] as const,
  holder: (kind: EquipmentHolderKind, id: number) => ["equipment", "holder", kind, id] as const,
  protocols: (status: string, kind: string, q: string) =>
    ["equipment", "protocols", status, kind, q] as const,
  protocol: (id: number) => ["equipment", "protocol", id] as const,
  tasks: (status: string) => ["equipment", "tasks", status] as const,
  imports: ["equipment", "imports"] as const,
  importBatch: (id: number, decision: string) => ["equipment", "import", id, decision] as const,
  contract: (id: number) => ["equipment", "contract", id] as const,
  provider: (clientId: number) => ["equipment", "provider", clientId] as const,
  person: (userId: number) => ["equipment", "person", userId] as const,
  me: ["equipment", "me"] as const,
};

function itemParams(filters: ItemFilters): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.category) params.category = filters.category;
  if (filters.status) params.status = filters.status;
  if (filters.holder) params.holder = filters.holder;
  if (filters.q?.trim()) params.q = filters.q.trim();
  if (filters.free) params.free = "true";
  if (filters.unsigned) params.unsigned = "true";
  if (filters.limit) params.limit = String(filters.limit);
  return params;
}

export function useEquipmentSummary(enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.summary,
    queryFn: async () => (await api.get<EquipmentSummary>(`${BASE}/summary`)).data,
    enabled,
  });
}

export function useEquipmentModels(enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.models,
    queryFn: async () =>
      (await api.get<{ items: EquipmentModel[] }>(`${BASE}/models`)).data.items,
    enabled,
  });
}

export function useEquipmentItems(filters: ItemFilters, enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.items(filters),
    queryFn: async () =>
      (
        await api.get<{ items: EquipmentItem[]; total: number }>(`${BASE}/items`, {
          params: itemParams(filters),
        })
      ).data,
    enabled,
  });
}

export function useEquipmentItem(id: number | null) {
  return useQuery({
    queryKey: equipmentKeys.item(id ?? 0),
    queryFn: async () => (await api.get<EquipmentItemDetail>(`${BASE}/items/${id}`)).data,
    enabled: id != null && id > 0,
  });
}

export function useHolderSearch(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: equipmentKeys.holders(term),
    queryFn: async () =>
      (
        await api.get<{ items: EquipmentHolder[] }>(`${BASE}/holders`, { params: { q: term } })
      ).data.items,
    enabled: term.length >= 2,
    staleTime: 30_000,
  });
}

export function useHolderEquipment(kind: EquipmentHolderKind | null, id: number | null) {
  return useQuery({
    queryKey: equipmentKeys.holder(kind ?? "user", id ?? 0),
    queryFn: async () =>
      (
        await api.get<HolderEquipment & { holder: EquipmentHolder }>(
          `${BASE}/holders/${kind}/${id}`,
        )
      ).data,
    enabled: kind != null && id != null && id > 0,
  });
}

export function useProtocols(status: string, kind: string, q: string) {
  return useQuery({
    queryKey: equipmentKeys.protocols(status, kind, q),
    queryFn: async () =>
      (
        await api.get<{ items: EquipmentProtocol[] }>(`${BASE}/protocols`, {
          params: {
            ...(status ? { status } : {}),
            ...(kind ? { kind } : {}),
            ...(q.trim() ? { q: q.trim() } : {}),
          },
        })
      ).data.items,
  });
}

export function useProtocol(id: number | null) {
  return useQuery({
    queryKey: equipmentKeys.protocol(id ?? 0),
    queryFn: async () => (await api.get<EquipmentProtocol>(`${BASE}/protocols/${id}`)).data,
    enabled: id != null && id > 0,
  });
}

export function useEquipmentTasks(status: EquipmentTaskStatus | "all" = "otwarte", enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.tasks(status),
    queryFn: async () =>
      (
        await api.get<{ items: EquipmentTask[] }>(`${BASE}/tasks`, { params: { status } })
      ).data.items,
    enabled,
  });
}

export function useImports() {
  return useQuery({
    queryKey: equipmentKeys.imports,
    queryFn: async () => (await api.get<{ items: ImportBatch[] }>(`${BASE}/imports`)).data.items,
  });
}

export function useImportBatch(id: number | null, decision: ImportDecision | "") {
  return useQuery({
    queryKey: equipmentKeys.importBatch(id ?? 0, decision),
    queryFn: async () =>
      (
        await api.get<ImportBatch & { rows: ImportRow[] }>(`${BASE}/imports/${id}`, {
          params: decision ? { decision } : undefined,
        })
      ).data,
    enabled: id != null && id > 0,
  });
}

export function useContractEquipmentRegister(contractId: number, enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.contract(contractId),
    queryFn: async () =>
      (await api.get<HolderEquipment>(`${BASE}/contracts/${contractId}`)).data,
    enabled: enabled && contractId > 0,
    // Wyłączony moduł (404) i brak uprawnienia (403) nie są awarią do ponawiania.
    retry: false,
  });
}

export function usePersonEquipment(userId: number, enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.person(userId),
    queryFn: async () => (await api.get<HolderEquipment>(`${BASE}/people/${userId}`)).data,
    enabled: enabled && userId > 0,
    retry: false,
  });
}

export function useMyEquipment(enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.me,
    queryFn: async () => (await api.get<HolderEquipment>(`${BASE}/me`)).data,
    enabled,
    retry: false,
  });
}

export function useClientProvider(clientId: number, enabled = true) {
  return useQuery({
    queryKey: equipmentKeys.provider(clientId),
    queryFn: async () =>
      (
        await api.get<{ equipment_provider: EquipmentProvider }>(
          `${BASE}/clients/${clientId}/provider`,
        )
      ).data.equipment_provider,
    enabled: enabled && clientId > 0,
    retry: false,
  });
}

function useInvalidateEquipment() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: equipmentKeys.all });
    // Zakładka „Sprzęt” kontraktu czyta własny klucz.
    void queryClient.invalidateQueries({ queryKey: ["contract-equipment"] });
  };
}

export function useCreateModel() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (payload: Omit<EquipmentModel, "id" | "items">) =>
      (await api.post<EquipmentModel>(`${BASE}/models`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateModel() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({ id, ...payload }: Partial<EquipmentModel> & { id: number }) =>
      (await api.patch<EquipmentModel>(`${BASE}/models/${id}`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useCreateItem() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (payload: ItemInput & { model_id: number }) =>
      (await api.post<EquipmentItemDetail>(`${BASE}/items`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateItem(id: number) {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (payload: ItemInput) =>
      (await api.patch<EquipmentItemDetail>(`${BASE}/items/${id}`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteItem() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`${BASE}/items/${id}`);
    },
    onSuccess: invalidate,
  });
}

export function useCreateExternalPerson() {
  return useMutation({
    mutationFn: async (payload: { full_name: string; work_email?: string | null; note?: string | null }) =>
      (
        await api.post<{ id: number; full_name: string; work_email: string | null; note: string | null }>(
          `${BASE}/external-people`,
          payload,
        )
      ).data,
  });
}

export interface MoveToUserResult {
  holder: EquipmentHolder;
  assignments: number;
  protocols: number;
  confirmed_protocols: number;
  tasks: number;
}

/** „Przepisz na konto”: niezwrócony sprzęt osoby spoza NEXUSA na jej konto. */
export function useMoveExternalToUser() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({ personId, userId }: { personId: number; userId: number }) =>
      (
        await api.post<MoveToUserResult>(`${BASE}/external-people/${personId}/move-to-user`, {
          user_id: userId,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useReturnEquipment() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (payload: ReturnInput) =>
      (await api.post<{ protocol: EquipmentProtocol }>(`${BASE}/return`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useCreateProtocolLink() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (protocolId: number) =>
      (
        await api.post<{ url: string; expires_at: string; holder_email: string | null }>(
          `${BASE}/protocols/${protocolId}/link`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useUploadSignedProtocol() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({
      protocolId,
      file,
      method,
    }: {
      protocolId: number;
      file: File;
      method: "papier" | "profil_zaufany";
    }) => {
      const body = new FormData();
      body.append("file", file);
      body.append("method", method);
      return (
        await api.post<EquipmentProtocol>(`${BASE}/protocols/${protocolId}/signed-file`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useConfirmProtocol() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({
      protocolId,
      method,
      signer_name,
    }: {
      protocolId: number;
      method?: "papier" | "profil_zaufany";
      signer_name?: string | null;
    }) =>
      (
        await api.post<EquipmentProtocol>(`${BASE}/protocols/${protocolId}/confirm`, {
          ...(method ? { method } : {}),
          ...(signer_name ? { signer_name } : {}),
        })
      ).data,
    onSuccess: invalidate,
  });
}

export interface ProtocolLineFix {
  position: number;
  unit_value?: string | null;
  accessories?: string | null;
  condition?: ReturnCondition;
  notes?: string | null;
}

export interface ProtocolFix {
  protocol_date?: string;
  holder_name?: string;
  lines?: ProtocolLineFix[];
}

/** Poprawka protokołu przed podpisem (decyzja 28.10.2026) — unieważnia wysłany link. */
export function useCorrectProtocol() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({ protocolId, fix }: { protocolId: number; fix: ProtocolFix }) =>
      (
        await api.patch<EquipmentProtocol & { link_revoked: boolean }>(
          `${BASE}/protocols/${protocolId}`,
          fix,
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** Anulowanie niepotwierdzonego protokołu z powodem (wydanie → sprzęt wraca na stan). */
export function useCancelProtocol() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({ protocolId, reason }: { protocolId: number; reason: string }) =>
      (await api.post<EquipmentProtocol>(`${BASE}/protocols/${protocolId}/cancel`, { reason }))
        .data,
    onSuccess: invalidate,
  });
}

export function useSetTaskStatus() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({ id, status }: { id: number; status: EquipmentTaskStatus }) =>
      (await api.patch<{ id: number; status: EquipmentTaskStatus }>(`${BASE}/tasks/${id}`, { status }))
        .data,
    onSuccess: invalidate,
  });
}

export interface RemindResult {
  /** Konto NEXUSA dostało dzwonek i mail; osobie bez konta pisze recepcja. */
  channel: "powiadomienie" | "mail";
  email: string | null;
  reminded_on: string;
}

/** „Przypomnij” przy zwrocie po terminie (`POST /tasks/{id}/remind`). */
export function useRemindTaskHolder() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (taskId: number) =>
      (await api.post<RemindResult>(`${BASE}/tasks/${taskId}/remind`)).data,
    onSuccess: invalidate,
  });
}

export function useUploadImport() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return (
        await api.post<ImportBatch>(`${BASE}/imports`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useUpdateImportRow(batchId: number) {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async ({
      rowId,
      ...payload
    }: {
      rowId: number;
      decision: ImportDecision;
      holder_user_id?: number | null;
      holder_contract_id?: number | null;
    }) => (await api.patch<ImportRow>(`${BASE}/imports/${batchId}/rows/${rowId}`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useApplyImport() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (batchId: number) =>
      (await api.post<{ created: number; conflicts: number }>(`${BASE}/imports/${batchId}/apply`))
        .data,
    onSuccess: invalidate,
  });
}

export function useCreateReturnTask() {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (contractId: number) =>
      (
        await api.post<{
          task: { id: number; title: string; due_on: string | null; status: EquipmentTaskStatus } | null;
        }>(`${BASE}/contracts/${contractId}/return-task`)
      ).data,
    onSuccess: invalidate,
  });
}

export function useSetClientProvider(clientId: number) {
  const invalidate = useInvalidateEquipment();
  return useMutation({
    mutationFn: async (equipment_provider: EquipmentProvider) =>
      (
        await api.put<{ equipment_provider: EquipmentProvider }>(
          `${BASE}/clients/${clientId}/provider`,
          { equipment_provider },
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** Pobranie pliku protokołu (Word albo PDF) z tokenem sesji. */
export function downloadProtocolDocument(
  protocol: Pick<EquipmentProtocol, "id" | "number">,
  format: "docx" | "pdf",
): Promise<void> {
  const name = `Protokol_${protocol.number.replaceAll("/", "_")}.${format}`;
  return downloadAuthenticatedFile(`${BASE}/protocols/${protocol.id}/document.${format}`, name);
}

/** Skan albo PDF z podpisem — nazwa i rozszerzenie z odpowiedzi serwera. */
export async function downloadSignedProtocol(
  protocol: Pick<EquipmentProtocol, "id" | "number">,
): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(
    `${BASE}/protocols/${protocol.id}/signed-file`,
  );
  downloadBlob(blob, filename ?? `Protokol_${protocol.number.replaceAll("/", "_")}.pdf`);
}

export function downloadImportControlSheet(batchId: number) {
  return downloadAuthenticatedFile(
    `${BASE}/imports/${batchId}/control-sheet.xlsx`,
    `Arkusz_kontrolny_importu_${batchId}.xlsx`,
  );
}
