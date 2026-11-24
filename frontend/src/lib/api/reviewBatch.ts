// Porcja dnia od Nexusa (decyzje Artura z 07.11.2026) — typy są lustrem
// `backend/app/api/review_batch.py` i `services/review_batch.py`.

import { useQuery, type QueryClient } from "@tanstack/react-query"

import api from "@/lib/api"
import { pluralPl } from "@/lib/plural-pl"
import { REVIEW_BATCH_STATUS_POLL_MS } from "@/lib/polling"
import { hasSectionAccess } from "@/lib/section-access"
import type { KnownFacts } from "@/lib/new-column-queue"
import { useAuthStore } from "@/store/auth"

export interface ReviewBatchJob {
  job_id: number
  title: string
  /** Osoby z porcji czekające u patrzącego w tej rekrutacji. */
  pending: number
  p0: boolean
  /** Poziom, z którego porcja bierze osoby: P0 najpierw, potem niżej (10.11.2026). */
  group?: ReviewBatchSource
  /** Jak osoba jest przypisana: prowadzi, przypisanie, dopisana ręcznie. */
  via?: "owner" | "assignment" | "collaborator" | null
  p0_until?: string | null
}

/** Dlaczego osoba z porcji trafiła do patrzącego (decyzje Artura 10.11.2026). */
export type ReviewBatchSource = "p0" | "p1" | "p2" | "accepting"

export interface ReviewBatchWhy {
  source: ReviewBatchSource
  via: "owner" | "assignment" | "collaborator" | null
  p0_until?: string | null
  /** Rekrutacja wybrana przez patrzącego na dziś (`review_batch_focus`). */
  chosen?: boolean
}

/** Rekrutacja wybrana na dziś: porcja bierze osoby najpierw stamtąd. */
export interface ReviewBatchFocus {
  job_id: number
  at: string
}

/** Kto już wybrał tę rekrutację na dziś: kto pierwszy, ten bierze. */
export interface ReviewBatchFocusPick {
  user_id: number
  name: string
  at: string
  /** Osoby z porcji, które ta osoba ma teraz w tej rekrutacji. */
  cards: number
}

/** Rekrutacja do wyboru: Twoje osoby z porcji, przypisani i kto już ją wybrał. */
export interface ReviewBatchFocusOption extends ReviewBatchJob {
  team_size: number
  picked_by: ReviewBatchFocusPick[]
}

/**
 * Co się stanie po wyborze jednej rekrutacji — ten sam plan co wybór, z liczbą
 * osób po regułach dopełniania (`batch_capacity`), nie szacunkiem z puli.
 */
export interface ReviewBatchFocusPreview {
  job_id: number
  /** Ile osób rekrutacja może dać teraz: karty bez właściciela i pula po regułach. */
  available: number
  /** Ile osób przyjdzie stąd po wyborze. */
  take: number
  /** Ile nieruszonych osób z innych rekrutacji wróci do puli zespołu (nadwyżka ponad porcję). */
  release: number
}

export interface ReviewBatchFocusOptions {
  items: ReviewBatchFocusOption[]
  focus: ReviewBatchFocus | null
  /** Ile osób porcja może jeszcze dziś dać: poziom minus decyzje z dziś. */
  seats: number
}

export interface ReviewBatchOpenScreening {
  job_id: number
  job_title: string
  candidate_id: number
  name: string
  /** Minęły 2 dni robocze bez wyniku: blokuje wyszukiwanie. */
  overdue?: boolean
  /** Osobę zdjęto z rekrutacji (np. zejście z priorytetu): bez terminu, nie blokuje. */
  parked?: boolean
  /** „Nie odebrał” po decyzji: termin liczy się od ostatniej próby. */
  attempts?: number
  last_attempt_at?: string | null
}

export interface ReviewBatchStatus {
  enabled: boolean
  /** Porcja dotyczy patrzącego (konto z rolą rekrutera). */
  applies: boolean
  minimum: number
  done_today: number
  pending: number
  /** Ile decyzji trzeba dziś podjąć: minimum albo cała porcja, gdy mniejsza. */
  required: number
  remaining: number
  met: boolean
  /** Niezrobione minimum teraz blokuje wyszukiwanie (wyłącznik HoR, pilot, dzień roboczy od 7:00). */
  blocks?: boolean
  /** „Do screeningu” z ostatnich 2 dni roboczych, jeszcze bez wyniku. */
  open_screenings?: number
  /** Własne „Do screeningu” bez wyniku (zakładka „Do domknięcia”). */
  open_today_screenings?: ReviewBatchOpenScreening[]
  /** Ile z nich jest po terminie; dopóki > 0, wyszukiwanie stoi. */
  overdue_screenings?: number
  jobs: ReviewBatchJob[]
  team_jobs: ReviewBatchJob[]
  /** Ile osób dokłada „Dodaj kolejnych”: 20 w porcji, 10 przy celu wg tempa. */
  more_cards?: number
  /** Skład porcji: ile osób z P0, ile z niższych priorytetów; poziom jutro (do 50). */
  sources?: ReviewBatchSources
  /** Rekrutacja wybrana na dziś; brak = kolejność z poziomów (najpierw pilne). */
  focus?: ReviewBatchFocus | null
}

/** Skład porcji. Od 22.11.2026 (R2): pilne (P0 + P1) i pozostałe, ile miejsc
 * czeka na niepilne (8 z 20) i ile kart odłożono na koniec (R5). */
export interface ReviewBatchSources {
  p0: number
  rest: number
  level_next: number
  level_cap: number
  urgent?: number
  other?: number
  other_seats?: number
  stale?: number
}

export interface ReviewBatchSentBefore {
  count: number
  last_days: number
  last_job_title: string
}

export interface ReviewBatchClientRecent {
  days: number | null
  job_id: number
  job_title: string
}

export interface ReviewBatchCaution {
  key: string
  label: string
  title: string
}

/** Dowód krytycznej: oś technologii z CV / tylko wzmianka / nigdzie (12.11.2026). */
export type KeyEvidence = "experience" | "mention" | "none"
export interface ReviewBatchKeyFacts {
  critical: { label: string; state: KeyEvidence; detail: string }[]
  polish: { state: "native" | "level" | "no" | "unknown"; detail: string }
}

export interface ReviewBatchItem {
  process_id: number
  stage_id: number | null
  job_id: number
  job_title: string
  candidate_id: number
  name: string
  city: string | null
  years: number | null
  position: string | null
  score: number
  matched_must: string[]
  missing_must: string[]
  rate_from_hourly: number | null
  rate_currency: string | null
  availability_status: string | null
  cautions: ReviewBatchCaution[]
  budget_hourly: number | null
  known?: KnownFacts | null
  order_active?: boolean
  order_in_budget?: boolean
  /** Polski nieojczysty albo bez danych w rekrutacji wymagającej polskiego (16.11.2026). */
  order_polish_later?: boolean
  /** Rekrutacja na lidera, osoba wykonawca (16.11.2026). */
  order_leader_gap?: boolean
  /** Wysłany do klienta w innej rekrutacji w ostatnim roku (20.11.2026). */
  sent_before?: ReviewBatchSentBefore | null
  why?: ReviewBatchWhy
  /** Wysłany w ostatnich 14 dniach do tego klienta w innej rekrutacji (R4). */
  client_recent?: ReviewBatchClientRecent | null
  /** Bez decyzji od 2 dni roboczych: na końcu kolejki, nie zajmuje miejsca (R5). */
  stale?: boolean
  /** Dzień dodania karty (kalendarz firmy), RRRR-MM-DD. */
  opened_on?: string | null
  /** „Kluczowe w tej rekrutacji”: krytyczne z dowodem i polski. */
  key_facts?: ReviewBatchKeyFacts | null
  /** Schodki po wymaganiach (23.11.2026): „Musi mieć 7 z 10”, mile widziane. */
  requirements?: ReviewBatchRequirements | null
}

/** Liczniki schodków — te same na Tablicy (`entry_autofill.steps`). */
export interface RequirementStepCounts {
  critical_missing: number
  must_met: number
  must_total: number
  nice_met: number
  nice_total: number
}

export interface ReviewBatchRequirements extends RequirementStepCounts {
  /** „Musi mieć” bez krytycznych, z dowodem z CV. */
  must: { label: string; state: KeyEvidence }[]
  nice: { label: string; state: KeyEvidence }[]
}

export interface ReviewBatchTeamRow {
  user_id: number
  name: string
  absent: boolean
  done_today: number
  /** Minimum tej osoby na dziś: rośnie o 10 po każdym zrobionym, do 50. */
  minimum: number
  required: number
  pending: number
  /** Godzina zrobienia minimum, `null` = jeszcze nie. */
  minimum_at: string | null
  screened: number
  rejected: number
  open_screenings: number
  /** Wpisy `review_batch.blocked`, jeden na 10 minut. */
  blocked_today: number
}

export interface ReviewBatchStreamsWeek {
  start: string
  system: number
  manual: number
  all: number
  complete: boolean
  found_via: Record<string, number>
}

export interface ReviewBatchTeam {
  day: string
  enabled: boolean
  minimum: number
  rows: ReviewBatchTeamRow[]
  good_before_11: number
  measured: number
  streams: {
    weeks: ReviewBatchStreamsWeek[]
    baseline_week: { system: number; manual: number; all: number }
    stop_drop_percent: number
    stop_weeks: number
    stop: boolean
  }
}

export const REVIEW_BATCH_QUERY_KEY = ["review-batch"] as const
export const REVIEW_BATCH_STATUS_KEY = [...REVIEW_BATCH_QUERY_KEY, "me"] as const
export const REVIEW_BATCH_QUEUE_KEY = [...REVIEW_BATCH_QUERY_KEY, "queue"] as const

/** Kod odpowiedzi 423, gdy rekruter szuka ręcznie przed minimum. */
export const REVIEW_BATCH_BLOCK_CODE = "REVIEW_MINIMUM_PENDING"

export function useReviewBatchStatus(options: { enabled?: boolean } = {}) {
  const readsJobs = useAuthStore((s) => hasSectionAccess(s.user, "pipeline"))
  return useQuery<ReviewBatchStatus>({
    queryKey: REVIEW_BATCH_STATUS_KEY,
    queryFn: async () => (await api.get<ReviewBatchStatus>("/api/review-batch/me")).data,
    enabled: readsJobs && (options.enabled ?? true),
    staleTime: 30_000,
    refetchInterval: REVIEW_BATCH_STATUS_POLL_MS,
    retry: false,
  })
}

/**
 * Reguła rekrutacji z powtarzanych braków (12.11.2026): 3 odrzucenia z tą samą
 * pozycją → silnik wymaga jej śladu („trace”) albo doświadczenia („experience”).
 */
export interface ReviewBatchLearnedRule {
  label: string
  level: "trace" | "experience"
  count: number
}

/** Poziom w profilu „Kogo szukamy” (lustro `job_role_profile_schema.LEVELS`). */
export type ReviewBatchRoleLevel = "wykonawca" | "lider" | "dowolny"

export interface ReviewBatchExcludedRole {
  label: string
  /** Ile odrzuceń „Inna rola” z „Osoba to:” tej etykiety w rekrutacji. */
  count: number
  source: "manual" | "rejections"
}

/**
 * Profil „Kogo szukamy” rekrutacji (16.11.2026). Bez zapisu (`saved: false`)
 * liczy się z tytułu i krytycznych Championa. „Nie proponujemy” = wpisy
 * ręczne i etykiety z odrzuceń od `exclude_min` takich samych.
 */
export interface ReviewBatchRoleProfile {
  job_id: number
  role: string | null
  specialty: string | null
  technology: string | null
  level: ReviewBatchRoleLevel
  saved: boolean
  excluded: ReviewBatchExcludedRole[]
  /** Etykiety z odrzuceń jeszcze poniżej progu (albo zdjęte z listy). */
  learning: { label: string; count: number; dismissed: boolean }[]
  exclude_min: number
  can_edit?: boolean
}

export interface ReviewBatchRoleProfileIn {
  role: string | null
  specialty: string | null
  technology: string | null
  level: ReviewBatchRoleLevel
  /** Cała lista „Nie proponujemy”, jaka ma zostać. */
  excluded: string[]
}

export interface ReviewBatchQueue {
  items: ReviewBatchItem[]
  /** Klucz to id rekrutacji jako tekst. */
  job_rules?: Record<string, ReviewBatchLearnedRule[]>
  /** Profil „Kogo szukamy”; klucz to id rekrutacji jako tekst. */
  job_profiles?: Record<string, ReviewBatchRoleProfile>
  /** Ile osób z której rekrutacji idzie po kolei w całej kolejce (17.11.2026). */
  runs?: ReviewBatchQueueRun[]
  /** Odłożone (R5) w całej kolejce, nie tylko na tej stronie (24.11.2026). */
  stale?: ReviewBatchQueueStale | null
}

export interface ReviewBatchQueueStale {
  count: number
  /** Najstarszy i najnowszy dzień otwarcia karty, RRRR-MM-DD. */
  first: string
  last: string
}

export interface ReviewBatchQueueRun {
  job_id: number
  count: number
}

export async function saveRoleProfile(
  jobId: number,
  body: ReviewBatchRoleProfileIn,
): Promise<ReviewBatchRoleProfile> {
  const res = await api.put<ReviewBatchRoleProfile>(`/api/review-batch/jobs/${jobId}/profile`, body)
  return res.data
}

export function useReviewBatchQueue(options: { enabled?: boolean } = {}) {
  return useQuery<ReviewBatchQueue>({
    queryKey: REVIEW_BATCH_QUEUE_KEY,
    queryFn: async () =>
      (await api.get<ReviewBatchQueue>("/api/review-batch/me/queue", {
        params: { limit: 20 },
      })).data,
    enabled: options.enabled ?? true,
    staleTime: 0,
    retry: false,
  })
}

/** Porcja zespołu dziś (HoR i admin), liczona dopiero po rozwinięciu tabeli. */
export function useReviewBatchTeam(enabled: boolean) {
  return useQuery<ReviewBatchTeam>({
    queryKey: [...REVIEW_BATCH_QUERY_KEY, "team"],
    queryFn: async () => (await api.get<ReviewBatchTeam>("/api/review-batch/team")).data,
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

export function useReviewBatchFocusOptions(enabled: boolean) {
  return useQuery<ReviewBatchFocusOptions>({
    queryKey: [...REVIEW_BATCH_QUERY_KEY, "focus"],
    queryFn: async () =>
      (await api.get<ReviewBatchFocusOptions>("/api/review-batch/me/focus")).data,
    enabled,
    staleTime: 0,
    retry: false,
  })
}

export function useReviewBatchFocusPreview(jobId: number | null) {
  return useQuery<ReviewBatchFocusPreview>({
    queryKey: [...REVIEW_BATCH_QUERY_KEY, "focus", jobId],
    queryFn: async () =>
      (await api.get<ReviewBatchFocusPreview>(`/api/review-batch/me/focus/${jobId}`)).data,
    enabled: jobId !== null,
    staleTime: 0,
    retry: false,
  })
}

/** Wybór rekrutacji na dziś; `null` = powrót do kolejności z poziomów. */
export async function setReviewBatchFocus(
  jobId: number | null,
): Promise<{ focus: ReviewBatchFocus | null; released: number; added: number }> {
  const res = await api.put<{ focus: ReviewBatchFocus | null; released: number; added: number }>(
    "/api/review-batch/me/focus",
    { job_id: jobId },
  )
  return res.data
}

export async function addMoreFromNexus(jobId: number): Promise<number> {
  const res = await api.post<{ added: number }>(`/api/review-batch/jobs/${jobId}/more`)
  return res.data.added
}

export type NewColumnTempoState =
  | { enabled: false }
  | {
      enabled: true
      tier: "quiet" | "moderate" | "hot" | "new" | "p0"
      target: number
      /** Decyzje ludzi o kartach z „Nowych” w 21 dni. */
      decisions: number
      /** Czekające karty od systemu. */
      waiting: number
      more_cards: number
      can_add_more: boolean
    }

function newColumnTempoKey(jobId: number) {
  return [...REVIEW_BATCH_QUERY_KEY, "tempo", jobId] as const
}

/** Cel kart od systemu wg tempa rekrutacji (`GET …/jobs/{id}/tempo`). */
export function useNewColumnTempo(jobId: number) {
  const readsJobs = useAuthStore((s) => hasSectionAccess(s.user, "pipeline"))
  return useQuery<NewColumnTempoState>({
    queryKey: newColumnTempoKey(jobId),
    queryFn: async () =>
      (await api.get<NewColumnTempoState>(`/api/review-batch/jobs/${jobId}/tempo`)).data,
    enabled: readsJobs,
    staleTime: 60_000,
    retry: false,
  })
}

export function invalidateNewColumnTempo(queryClient: QueryClient, jobId: number): void {
  void queryClient.invalidateQueries({ queryKey: newColumnTempoKey(jobId) })
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] })
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] })
}

/** Dymek plakietki „cel N”: skąd ten cel i kiedy kolumna się dopełnia. */
export function newColumnTargetHint(tempo: Extract<NewColumnTempoState, { enabled: true }>): string {
  const refills = tempo.tier === "hot" || tempo.tier === "new" || tempo.tier === "p0"
  const why =
    tempo.tier === "p0"
      ? "P0"
      : tempo.tier === "new"
        ? "rekrutacja do 14 dni"
        : tempo.decisions === 0
          ? "bez decyzji w 21 dni"
          : `${tempo.decisions} ${pluralPl(tempo.decisions, "decyzja", "decyzje", "decyzji")} w 21 dni`
  return `Cel ${tempo.target}: ${why}. ${refills ? "Dopełnia się po ruchu karty." : "Reszta przyciskiem."}`
}

export function invalidateReviewBatch(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: REVIEW_BATCH_QUERY_KEY })
}

/** Odpowiedź serwera to blokada porcji (423 `REVIEW_MINIMUM_PENDING`). */
export function reviewBatchBlock(
  error: unknown,
): { message: string; remaining: number; required: number; overdue: number } | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response
  if (response?.status !== 423) return null
  const detail = response.data?.detail as
    | { code?: string; message?: string; remaining?: number; required?: number; overdue?: number }
    | undefined
  if (!detail || detail.code !== REVIEW_BATCH_BLOCK_CODE) return null
  return {
    message: detail.message ?? "Najpierw porcja od Nexusa.",
    remaining: Number(detail.remaining ?? 0),
    required: Number(detail.required ?? 0),
    overdue: Number(detail.overdue ?? 0),
  }
}
