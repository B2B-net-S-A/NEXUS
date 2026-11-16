// Szkolenia od strony NEXUSA (decyzja Artura 13.11.2026, zamiast Akademii Compassa).
//
// Lustro `backend/app/api/trainings.py` (prefiks `/api/trainings`) i kształtów
// z `backend/app/services/trainings/core.py` (`staff_view`, `list_row`, `library`)
// oraz `people.py`. Kwoty przychodzą jako tekst dziesiętny i tylko tam, gdzie
// serwer je zwraca (TCM, Finanse, admin). Biblioteka i zapisy są dla każdego.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";

const BASE = "/api/trainings";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type TrainingStatus =
  | "draft"
  | "ordered"
  | "quoted"
  | "returned"
  | "accepted"
  | "trainer_signed"
  | "signed"
  | "cancelled";

export type TrainerKind = "consultant" | "employee";
export type DeliverableKey = "materials" | "presentation" | "audio" | "other";
export type FeeKey = "fee_prep" | "fee_delivery" | "fee_presentation" | "fee_audio" | "fee_rights";
export type HandoverState = "missing" | "submitted" | "accepted" | "returned";
export type TrainingFileKind = "deliverable" | "recording" | "invoice" | "internal";
export type TrainingFileStatus = "submitted" | "accepted" | "returned" | "replaced";
export type AgreementVersion = "draft" | "trainer" | "signed";

export interface TrainingsMe {
  can_manage: boolean;
  can_read: boolean;
  can_pay: boolean;
  is_company_signer: boolean;
  /** 0697: spotkanie Teams zakłada NEXUS, więc formularz nie pyta o link. */
  teams_ready?: boolean;
}

export interface TrainingDeliverable {
  key: DeliverableKey;
  label: string;
  required: boolean;
  format: string;
  due_days: number | null;
}

export interface TrainingAgendaItem {
  title: string;
  minutes: number | null;
}

export interface TrainingFileRow {
  id: number;
  kind: TrainingFileKind;
  deliverable_key: DeliverableKey | null;
  status: TrainingFileStatus;
  file_name: string;
  content_type: string | null;
  size_bytes: number | null;
  uploaded_at: string | null;
  review_note: string | null;
  reviewed_at: string | null;
  fix_due_on: string | null;
  for_participants: boolean;
}

export interface TrainingHandoverItem {
  key: DeliverableKey;
  label: string;
  format: string;
  due_days: number | null;
  required: boolean;
  state: HandoverState;
  files: TrainingFileRow[];
}

export interface TrainingFee {
  key: FeeKey;
  label: string;
  needs: DeliverableKey | null;
  amount: string | null;
}

export interface TrainingFees {
  items: TrainingFee[];
  total: string | null;
}

export interface TrainingOrder {
  title: string;
  topic: string;
  description: string;
  session_date: string | null;
  time_from: string;
  time_to: string;
  duration_minutes: number | null;
  platform: string;
  expected_participants: number | null;
  quote_due_on: string | null;
  participant_materials: string;
  deliverables: TrainingDeliverable[];
  knowledge_test: boolean;
  extra_terms: string;
  seat_limit?: number | null;
}

export interface TrainingQuote {
  agenda: TrainingAgendaItem[];
  own_materials: string;
  third_party_materials: string;
  quote_note: string;
  return_note: string | null;
  quoted_at: string | null;
}

export interface TrainingAgreement {
  number: string | null;
  generated_at: string | null;
  trainer_signed_at: string | null;
  company_signed_at: string | null;
}

export interface TrainingPayment {
  invoice_ready_at: string | null;
  paid_at: string | null;
}

export interface TrainingChapter {
  title: string;
  start_minute: number;
}

/** `core.staff_view` — karta szkolenia. `fees` = `null`, gdy serwer nie pokazuje kwot. */
export interface TrainingView {
  id: number;
  status: TrainingStatus;
  status_label: string;
  trainer_kind: TrainerKind;
  trainer_contract_id: number | null;
  trainer_user_id: number | null;
  trainer_name: string;
  application_id: number | null;
  join_url: string;
  order: TrainingOrder;
  quote: TrainingQuote;
  fees: TrainingFees | null;
  agreement: TrainingAgreement;
  payment: TrainingPayment;
  handover: TrainingHandoverItem[];
  files: TrainingFileRow[];
  registrations: number;
  attendance: number;
  teams?: TrainingTeams;
  shared_registered_at?: string | null;
  feedback?: TrainingFeedbackSummary;
  transcript?: boolean;
  published_at: string | null;
  can_publish: boolean;
  chapters: TrainingChapter[];
  cancelled_at: string | null;
  cancel_reason: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Spotkanie Teams założone przez NEXUS (0697) i stan nagrania z Teams. */
export interface TrainingTeams {
  status: "created" | "failed" | "cancelled" | null;
  error: string | null;
  synced_at: string | null;
  recording: "waiting" | "imported" | "none" | "failed" | null;
}

export interface TrainingFeedbackSummary {
  count: number;
  average: number | null;
  comments?: string[];
}

/** `core.list_row` — wiersz rejestru „Organizuję”. */
export interface TrainingRow {
  id: number;
  title: string;
  status: TrainingStatus;
  status_label: string;
  trainer_kind: TrainerKind;
  trainer_contract_id: number | null;
  trainer_name: string;
  session_date: string | null;
  total: string | null;
  invoice_ready_at: string | null;
  paid_at: string | null;
  published_at: string | null;
  can_publish: boolean;
}

export interface LibraryFile {
  id: number;
  kind: TrainingFileKind;
  file_name: string;
  content_type: string | null;
  size_bytes: number | null;
}

export interface LibraryRecording {
  id: number;
  title: string;
  topic: string;
  description: string;
  session_date: string | null;
  duration_minutes: number | null;
  trainer_kind: TrainerKind;
  /** „registered” = nagranie tylko dla zapisanych (przed zapłatą trenera B2B). */
  scope?: "library" | "registered";
  registered?: boolean;
  chapters: TrainingChapter[];
  files: LibraryFile[];
}

export interface LiveTraining {
  id: number;
  title: string;
  topic: string;
  session_date: string | null;
  time_from: string;
  time_to: string;
  platform: string;
  description?: string;
  trainer_kind?: TrainerKind;
  seat_limit?: number | null;
  taken?: number;
  registered: boolean;
  /** Ja prowadzę to szkolenie: bez zapisu, z linkiem prowadzącego. */
  leading?: boolean;
  join_url: string | null;
  /** Spotkanie założył NEXUS: zapis wysyła zaproszenie do kalendarza. */
  invited?: boolean;
}

export interface TranscriptHit {
  second: number;
  text: string;
}

export interface TranscriptSearch {
  available: boolean;
  hits: TranscriptHit[];
}

export interface TrainingLibrary {
  recordings: LibraryRecording[];
  live: LiveTraining[];
}

export interface TrainerApplication {
  id: number;
  contract_id: number;
  trainer_name: string;
  email: string | null;
  topics: string[];
  experience: string;
  proposal_title: string;
  proposal_hours: string;
  audience: string;
  availability: string;
  materials: string;
  sample_name: string | null;
  case_id: number | null;
  sent_at: string;
}

export interface PendingSignature {
  id: number;
  title: string;
  number: string;
  trainer_name: string;
  trainer_signed_at: string | null;
}

export interface TrainingPartner {
  full_name: string;
  company: string;
  address: string;
  postal_city: string;
  nip: string;
  regon: string;
  phone: string;
  email: string;
}

export interface TrainingPartnerResponse {
  partner: Partial<TrainingPartner> & Record<string, unknown>;
  /** Polskie nazwy brakujących pól wymaganych do umowy. */
  missing: string[];
  company_email: string;
}

export interface TrainingPeople {
  registrations: { name: string; email: string | null; who: "staff" | "consultant" }[];
  attendance: { name: string; email: string | null; minutes: number | null; matched: boolean }[];
}

export interface TrainingSettings {
  sharepoint: boolean;
  share_url: string | null;
}

export interface DeliverableInput {
  key: DeliverableKey;
  label: string;
  required: boolean;
  format: string;
  due_days: number | null;
}

export interface OrderInput {
  title: string;
  topic: string;
  description: string;
  session_date: string | null;
  time_from: string;
  time_to: string;
  duration_minutes: number | null;
  platform: string;
  join_url: string;
  expected_participants: number | null;
  quote_due_on: string | null;
  participant_materials: string;
  deliverables: DeliverableInput[];
  knowledge_test: boolean;
  extra_terms: string;
  seat_limit?: number | null;
}

export interface CreateInput extends OrderInput {
  trainer_contract_id: number | null;
  trainer_user_id: number | null;
  application_id: number | null;
}

export interface DirectoryUser {
  id: number;
  name: string;
  email: string;
}

type TrainingResponse = { training: TrainingView };

export const trainingKeys = {
  all: ["trainings"] as const,
  me: ["trainings", "me"] as const,
  library: ["trainings", "library"] as const,
  list: ["trainings", "list"] as const,
  detail: (id: number) => ["trainings", "detail", id] as const,
  partner: (id: number) => ["trainings", "partner", id] as const,
  people: (id: number) => ["trainings", "people", id] as const,
  applications: ["trainings", "applications"] as const,
  pending: ["trainings", "signatures", "pending"] as const,
  settings: ["trainings", "settings"] as const,
  users: (q: string) => ["trainings", "users", q] as const,
};

export const trainingPaths = {
  agreementPdf: (id: number, version: AgreementVersion) =>
    `${BASE}/${id}/agreement.pdf?version=${version}`,
  file: (id: number, fileId: number) => `${BASE}/${id}/files/${fileId}?download=true`,
  libraryFile: (fileId: number) => `${BASE}/library/files/${fileId}?download=true`,
  sample: (applicationId: number) => `${BASE}/applications/${applicationId}/sample`,
};

// ── Odczyty ──────────────────────────────────────────────────────────────────

export function useTrainingsMe(enabled = true) {
  return useQuery({
    queryKey: trainingKeys.me,
    queryFn: async () => (await api.get<TrainingsMe>(`${BASE}/me`)).data,
    enabled,
    retry: false,
    staleTime: 60_000,
  });
}

export function useTrainingLibrary(enabled = true) {
  return useQuery({
    queryKey: trainingKeys.library,
    queryFn: async () => (await api.get<TrainingLibrary>(`${BASE}/library`)).data,
    enabled,
    retry: false,
  });
}

export function useTrainingList(enabled = true) {
  return useQuery({
    queryKey: trainingKeys.list,
    queryFn: async () =>
      (await api.get<{ trainings: TrainingRow[] }>(BASE)).data.trainings,
    enabled,
    retry: false,
  });
}

export function useTraining(id: number, enabled = true) {
  return useQuery({
    queryKey: trainingKeys.detail(id),
    queryFn: async () => (await api.get<TrainingResponse>(`${BASE}/${id}`)).data.training,
    enabled: enabled && Number.isInteger(id) && id > 0,
    retry: false,
  });
}

export function useTrainingPartner(id: number, enabled = true) {
  return useQuery({
    queryKey: trainingKeys.partner(id),
    queryFn: async () =>
      (await api.get<TrainingPartnerResponse>(`${BASE}/${id}/partner`)).data,
    enabled,
    retry: false,
  });
}

export function useTrainingPeople(id: number, enabled = true) {
  return useQuery({
    queryKey: trainingKeys.people(id),
    queryFn: async () => (await api.get<TrainingPeople>(`${BASE}/${id}/people`)).data,
    enabled,
    retry: false,
  });
}

export function useTrainerApplications(enabled = true) {
  return useQuery({
    queryKey: trainingKeys.applications,
    queryFn: async () =>
      (await api.get<{ applications: TrainerApplication[] }>(`${BASE}/applications`)).data
        .applications,
    enabled,
    retry: false,
  });
}

export function usePendingSignatures(enabled = true) {
  return useQuery({
    queryKey: trainingKeys.pending,
    queryFn: async () =>
      (await api.get<{ trainings: PendingSignature[] }>(`${BASE}/signatures/pending`)).data
        .trainings,
    enabled,
    retry: false,
  });
}

export function useTrainingSettings(enabled = true) {
  return useQuery({
    queryKey: trainingKeys.settings,
    queryFn: async () => (await api.get<TrainingSettings>(`${BASE}/settings`)).data,
    enabled,
    retry: false,
  });
}

/** Pracownicy do wyboru trenera (katalog `/api/users`, szukanie po nazwisku). */
export function useTrainerUserOptions(q: string, enabled = true) {
  const term = q.trim();
  return useQuery({
    queryKey: trainingKeys.users(term),
    queryFn: async () =>
      (await api.get<DirectoryUser[]>("/api/users", { params: { q: term } })).data,
    enabled: enabled && term.length >= 2,
    staleTime: 60_000,
  });
}

// ── Zapisy ───────────────────────────────────────────────────────────────────

function useInvalidateTrainings() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: trainingKeys.all });
}

/** Odpowiedź z kartą od razu w pamięci podręcznej, reszta rejestru odświeża się w tle. */
function useTrainingCommand<TArgs>(call: (args: TArgs) => Promise<TrainingView>) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateTrainings();
  return useMutation({
    mutationFn: call,
    onSuccess: (training) => {
      queryClient.setQueryData(trainingKeys.detail(training.id), training);
      return invalidate();
    },
  });
}

const post = async (path: string, payload?: unknown): Promise<TrainingView> =>
  (await api.post<TrainingResponse>(`${BASE}${path}`, payload ?? {})).data.training;

const postFile = async (
  path: string,
  fields: Record<string, string | Blob>,
  onProgress?: (fraction: number) => void,
): Promise<TrainingView> => {
  const body = new FormData();
  for (const [key, value] of Object.entries(fields)) body.append(key, value);
  return (
    await api.post<TrainingResponse>(`${BASE}${path}`, body, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (onProgress && event.total) onProgress(event.loaded / event.total);
      },
    })
  ).data.training;
};

/**
 * Nagranie (do 2 GB) jako surowe ciało z nazwą w nagłówku: serwer sprawdza uprawnienia,
 * zanim przeczyta bajty (multipart był parsowany przed bramką).
 */
const postRawFile = async (
  path: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<TrainingView> =>
  (
    await api.post<TrainingResponse>(`${BASE}${path}`, file, {
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name),
      },
      onUploadProgress: (event) => {
        if (onProgress && event.total) onProgress(event.loaded / event.total);
      },
    })
  ).data.training;

export function useCreateTraining() {
  return useTrainingCommand(async (input: CreateInput) => post("", input));
}

export function useUpdateTraining(id: number) {
  return useTrainingCommand(
    async (input: OrderInput) =>
      (await api.put<TrainingResponse>(`${BASE}/${id}`, input)).data.training,
  );
}

export function useSendOrder(id: number) {
  return useTrainingCommand(async () => post(`/${id}/send`));
}

export function useCancelTraining(id: number) {
  return useTrainingCommand(async (reason: string) => post(`/${id}/cancel`, { reason }));
}

export function useReturnQuote(id: number) {
  return useTrainingCommand(async (note: string) => post(`/${id}/return`, { note }));
}

export function useAcceptQuote(id: number) {
  return useTrainingCommand(async () => post(`/${id}/accept`));
}

export function useGenerateAgreement(id: number) {
  return useTrainingCommand(
    async (input: { partner: TrainingPartner; company_email: string }) =>
      post(`/${id}/agreement`, input),
  );
}

export function useCompanySignature(id: number) {
  return useTrainingCommand(async (file: File) =>
    postFile(`/${id}/agreement/company-signature`, { file }),
  );
}

/** To samo z listy „Do podpisu” — reprezentant nie musi mieć wglądu w kartę. */
export function useCompanySignatureFor() {
  const invalidate = useInvalidateTrainings();
  return useMutation({
    mutationFn: async ({ id, file }: { id: number; file: File }) =>
      postFile(`/${id}/agreement/company-signature`, { file }),
    onSuccess: invalidate,
  });
}

export function useUploadTrainingFile(id: number) {
  return useTrainingCommand(
    async (input: {
      kind: "recording" | "internal";
      file: File;
      onProgress?: (fraction: number) => void;
    }) => postRawFile(`/${id}/files?kind=${input.kind}`, input.file, input.onProgress),
  );
}

export function useReviewFile(id: number) {
  return useTrainingCommand(
    async (input: { fileId: number; accept: boolean; note: string }) =>
      post(`/${id}/files/${input.fileId}/review`, { accept: input.accept, note: input.note }),
  );
}

export function useFileForParticipants(id: number) {
  return useTrainingCommand(
    async (input: { fileId: number; value: boolean }) =>
      (
        await api.put<TrainingResponse>(`${BASE}/${id}/files/${input.fileId}/participants`, {
          value: input.value,
        })
      ).data.training,
  );
}

export function useMarkPaid(id: number) {
  return useTrainingCommand(async (paid: boolean) => post(`/${id}/paid`, { paid }));
}

export function usePublishTraining(id: number) {
  return useTrainingCommand(async (publish: boolean) => post(`/${id}/publish`, { publish }));
}

export function useShareWithRegistered(id: number) {
  return useTrainingCommand(async (share: boolean) => post(`/${id}/share`, { share }));
}

export function useRetryTeams(id: number) {
  return useTrainingCommand(async () => post(`/${id}/teams`));
}

export function useRateTraining() {
  const invalidate = useInvalidateTrainings();
  return useMutation({
    mutationFn: async ({ id, rating, comment }: { id: number; rating: number; comment: string }) =>
      (await api.post<{ rating: number }>(`${BASE}/library/${id}/feedback`, { rating, comment })).data,
    onSuccess: invalidate,
  });
}

export async function searchTranscript(id: number, q: string): Promise<TranscriptSearch> {
  return (await api.get<TranscriptSearch>(`${BASE}/library/${id}/transcript`, { params: { q } })).data;
}

export function useImportAttendance(id: number) {
  const invalidate = useInvalidateTrainings();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return (
        await api.post<{ imported: number; matched: number }>(`${BASE}/${id}/attendance`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useRegistration() {
  const invalidate = useInvalidateTrainings();
  return useMutation({
    mutationFn: async ({ id, join }: { id: number; join: boolean }) =>
      (await api.post<{ registered: boolean }>(`${BASE}/library/${id}/registration`, { join }))
        .data,
    onSuccess: invalidate,
  });
}

export function useSaveTrainingSettings() {
  const invalidate = useInvalidateTrainings();
  return useMutation({
    mutationFn: async (shareUrl: string) =>
      (await api.put<TrainingSettings>(`${BASE}/settings`, { share_url: shareUrl })).data,
    onSuccess: invalidate,
  });
}

// ── Pliki ────────────────────────────────────────────────────────────────────

/** Pobranie pliku z tokenem, pod nazwą z serwera (zwykły `<a href>` nie niesie tokenu). */
export async function downloadTrainingPath(path: string, fallbackName: string): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(path);
  downloadBlob(blob, filename ?? fallbackName);
}

/**
 * Adres pliku dla `<video>`/`<audio>`. Odtwarzacz nie wyśle nagłówka z tokenem,
 * więc serwer wydaje bilet jednego pliku (`/api/public/training-media/...`).
 */
export async function trainingMediaUrl(
  fileId: number,
  trainingId?: number,
): Promise<string> {
  const path =
    trainingId === undefined
      ? `${BASE}/library/files/${fileId}/ticket`
      : `${BASE}/${trainingId}/files/${fileId}/ticket`;
  const { url } = (await api.get<{ url: string }>(path)).data;
  return url.startsWith("/") ? `${API_BASE}${url}` : url;
}
