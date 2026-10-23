// Kolejka „Czeka na Ciebie" (0348, Rekrutacja v5) — praca na Tablicach, której
// nikt nie widzi.
//
// Typy są lustrem `backend/app/api/board_tasks.py` i kontraktu
// `docs/recruitment-v5-contract.md`. Serwer rozstrzyga, co należy do danej
// osoby (przegląd DL: osoby w kolumnie „QC CV" poza Nordeą; Cpro: JEDNA osoba
// na całą firmę, decyzja Artura 23.09.2026). Front tylko pokazuje i woła
// zwykły ruch w pipeline — bez własnej ścieżki zapisu etapu. Przegląd DZ
// (0353) zastąpiło QC CV (`lib/api/cvQc.ts`).

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { FollowupRow } from "@/lib/api/candidateFollowups";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import type { RateChangeTaskRow } from "@/lib/rate-change";
import type { PriorityLevel } from "@/lib/request-priority";
import { warsawToday } from "@/lib/warsaw-date";

export type BoardTaskKind = "cpro_to_send" | "cpro_sent" | "dl_review";

/** Wynik QC CV pary (najnowszy przebieg) — lustro `qc_status` z serwera. */
export type QcStatus = "passed" | "failed" | "overridden" | "unchecked";

export interface BoardTaskRow {
  kind: BoardTaskKind;
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  /** 0380: tytuł dla rekrutera (ekrany wewnętrzne); `job_title` = nazwa od klienta. */
  job_working_title?: string | null;
  client_reference?: string | null;
  client_id: number | null;
  client_name: string | null;
  since: string;
  process_state_version: number;
  /** Etap, na który prowadzi akcja („Wysłane do Cpro", a przy przeglądzie
   *  DL — „CV wysłane"). */
  target_stage_def_id: number | null;
  assignee_id: number | null;
  assignee_name: string | null;
  // Tylko przegląd DL (`dl_review`); przy pozostałych rodzajach puste.
  /** Etap „Odrzucony" szablonu rekrutacji — cel „Odrzuć (DL)". */
  rejected_stage_def_id?: number | null;
  verified_by_id?: number | null;
  verified_by_name?: string | null;
  verified_at?: string | null;
  /** Migawka stawki kandydata z wiersza „Zweryfikowany". */
  expected_rate_value?: number | null;
  expected_rate_unit?: "hourly" | "daily" | "monthly" | null;
  expected_rate_currency?: string | null;
  /** Wiersz etapu z zapisanym arkuszem screeningu (zwykle „Screening"). */
  screening_stage_id?: number | null;
  /** v5: wynik QC CV (przegląd DL = osoby w kolumnie „QC CV"). */
  qc_status?: QcStatus | null;
  qc_blocking_failed?: number | null;
  /** Przegląd DL: etap z CV firmowym pary (po QC) — z niego podgląd i DOCX. */
  cv_stage_id?: number | null;
  /** Etap powrotu do poprawy: przegląd DL — „Zweryfikowany” („Wróć do
   *  poprawy”), kolejka Cpro — „QC CV”. */
  return_stage_def_id?: number | null;
  /** Przegląd DL: stan karty rekomendacji; `null` = para nie ma karty. */
  card_status?: "complete" | "partial" | "empty" | null;
  card_missing?: number | null;
  // „Do wysłania do klienta” (13.10.2026) — tylko przegląd DL. Starszy serwer
  // pól nie oddaje (`undefined`) — wiersz liczy się wtedy jak dotąd.
  /** QC zdane albo przepuszczone: ruch ma Delivery Lead. `false` = karta jest
   *  jeszcze u rekrutera (QC do poprawy albo niesprawdzone). */
  ready?: boolean;
  /** Od kiedy gotowe: wejście do „QC CV” albo zaliczenie QC, co później. */
  ready_since?: string | null;
  waiting_workdays?: number;
  urgency?: DlSendUrgency | null;
  /** Etap z importu Traffita, którego nikt nie ruszył w NEXUSIE — poza
   *  licznikami i przypomnieniami. */
  imported?: boolean;
  handed_over_by_name?: string | null;
  budget_min_hourly?: number | null;
  budget_max_hourly?: number | null;
  deadline?: string | null;
  /** Przegląd DL u Nordei (13.10.2026): akceptacja do kolejki Cpro —
   *  `target_stage_def_id` to wtedy etap „Wysłać do Cpro”. */
  cpro?: boolean;
}

/** Plakietka wiersza Nordei w pasie „Do wysłania do klienta” i w okienku paska
 *  (14.10.2026). Stoi poza linią rekrutacji, bo ta ucina się przy 1280 px. */
export const CPRO_ROW_BADGE = "do Cpro";
export const CPRO_ROW_HINT = "Nordea: przegląd kończy akceptacja do kolejki Cpro — nic nie idzie do klienta.";
/** Przycisk przeglądu u Nordei — pas i karta Tablicy. Krótka, bo przy 1280 px
 *  z przypiętym menu kolumna przycisku w pasie ma 131 px treści: „Przejrzyj
 *  i zaakceptuj” (150 px) wychodził poza komórkę (pomiar 14.10.2026). */
export const CPRO_REVIEW_LABEL = "Przejrzyj → Cpro";

/** Pilność w dniach roboczych od gotowości: 0 / 1 / 2 i więcej. */
export type DlSendUrgency = "fresh" | "due" | "late";

/** Wiersz, który budzi licznik i przypomnienia Delivery Leada — lustro
 *  `dl_send_queue.counts_for_reviewer`. Starszy serwer (bez `ready`): każdy
 *  wiersz przeglądu, jak przed 13.10.2026. */
export function countsForDlSend(row: BoardTaskRow): boolean {
  return row.ready !== false && row.imported !== true;
}

/** Podział kolejki przeglądu na grupy pasa „Do wysłania do klienta”. Gotowe —
 *  najdłużej czekające pierwsze (od `ready_since`). */
export function splitDlSendRows(rows: readonly BoardTaskRow[]): {
  ready: BoardTaskRow[];
  notReady: BoardTaskRow[];
  imported: BoardTaskRow[];
} {
  const since = (row: BoardTaskRow) => row.ready_since ?? row.since;
  return {
    ready: rows.filter(countsForDlSend).sort((a, b) => since(a).localeCompare(since(b))),
    notReady: rows.filter((row) => row.ready === false && row.imported !== true),
    imported: rows.filter((row) => row.imported === true),
  };
}

/** Okienko „Do wysłania” w górnym pasku — wąski wiersz, celowo BEZ pól
 *  przeglądu (wersja procesu, etapy ruchu). Przegląd otwiera się z pełnego
 *  wiersza (`fetchDlReviewRow`), nie z tego. */
export interface DlSendRow {
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  job_working_title?: string | null;
  client_name: string | null;
  ready_since: string;
  waiting_workdays: number;
  urgency: DlSendUrgency;
  handed_over_by_name?: string | null;
  /** Nordea: osoba czeka na akceptację do kolejki Cpro. */
  cpro?: boolean;
}

export interface DlSendQueueResponse {
  ready: DlSendRow[];
  ready_total: number;
  not_ready_total: number;
  imported_total: number;
  worst_urgency: DlSendUrgency | null;
}

/** Pod prefiksem `["board-tasks"]` — każdy ruch karty, wynik QC i zdarzenie
 *  `pipeline_changed` odświeża licznik razem z kolejką pulpitu. */
export const DL_SEND_QUEUE_QUERY_KEY = ["board-tasks", "dl-send"] as const;

/** „Do wysłania do klienta” patrzącego — licznik górnego paska i menu.
 *  Liczy stan kolejki, nie zdarzenia. `enabled` = konto z rolą Delivery Leada
 *  (inne dostałyby zera). */
export function useDlSendQueue(enabled: boolean) {
  return useQuery<DlSendQueueResponse>({
    queryKey: DL_SEND_QUEUE_QUERY_KEY,
    queryFn: () => api.get<DlSendQueueResponse>("/api/board-tasks/dl-send").then((r) => r.data),
    enabled,
    refetchInterval: enabled ? WS_BACKED_SAFETY_POLL_MS : false,
    staleTime: 30_000,
  });
}

/** Auto-CV gotowe do sprawdzenia (ikona „CV”, `services/cv_topic.py`). */
export interface CvCheckRow {
  document_id: number;
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  job_working_title: string | null;
  client_name: string | null;
  since: string;
}

export interface CvTopicRecruiter {
  to_check: CvCheckRow[];
  to_fix: CvTransitRow[];
  with_dl: CvTransitRow[];
  sent: CvTransitRow[];
}

export interface CvTopicDl {
  to_send: DlSendRow[];
  to_send_total: number;
  worst_urgency: DlSendUrgency | null;
  /** W „QC CV”, ale ruch ma rekruter (QC do poprawy albo niesprawdzone). */
  with_recruiters_total: number;
  sent_today: CvTransitRow[];
}

/** Ikona „CV” w górnym pasku (16.10.2026) — stan, nie zdarzenia. */
export interface CvTopicResponse {
  /** Do sprawdzenia + do poprawy (rekruter) + do wysłania (Delivery Lead). */
  badge: number;
  recruiter: CvTopicRecruiter | null;
  dl: CvTopicDl | null;
}

/** Pod prefiksem `["board-tasks"]` — ruchy kart odświeżają ikonę jak kolejkę. */
export const CV_TOPIC_QUERY_KEY = ["board-tasks", "cv"] as const;

/** `enabled` = konto z rolą rekrutera albo Delivery Leada (lustro serwera). */
/** Granica z serwerem: zły kształt to awaria zapytania (ikona się chowa),
 *  nie wyjątek w renderze paska. */
function parseCvTopic(data: unknown): CvTopicResponse {
  const topic = data as Partial<CvTopicResponse> | null;
  const recruiterOk =
    topic?.recruiter === null ||
    (Array.isArray(topic?.recruiter?.to_check) &&
      Array.isArray(topic?.recruiter?.to_fix) &&
      Array.isArray(topic?.recruiter?.with_dl) &&
      Array.isArray(topic?.recruiter?.sent));
  const dlOk =
    topic?.dl === null ||
    (Array.isArray(topic?.dl?.to_send) && Array.isArray(topic?.dl?.sent_today));
  if (!topic || typeof topic.badge !== "number" || !recruiterOk || !dlOk) {
    throw new Error("Nieoczekiwana odpowiedź /api/board-tasks/cv");
  }
  return topic as CvTopicResponse;
}

export function useCvTopic(enabled: boolean) {
  return useQuery<CvTopicResponse>({
    queryKey: CV_TOPIC_QUERY_KEY,
    queryFn: () =>
      api.get<CvTopicResponse>("/api/board-tasks/cv").then((r) => parseCvTopic(r.data)),
    enabled,
    refetchInterval: enabled ? WS_BACKED_SAFETY_POLL_MS : false,
    staleTime: 30_000,
  });
}

/** 0370: prep przed rozmową u klienta, który wymaga uwagi. Widzi go
 *  organizator prepu, admin i Head of Recruitment. */
export type PrepAttentionReason = "missing" | "late" | "weak" | "unrecorded";

export interface PrepAttentionRow {
  reason: PrepAttentionReason;
  /** 1 = prep prowadzi Delivery Lead, 2 = rekruter. */
  prep_no: 1 | 2;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  interview_event_id: number;
  /** Start rozmowy u klienta (ISO). */
  interview_start: string;
  prep_event_id: number | null;
  owner_id: number | null;
  /** Rozmowa tuż-tuż — wiersz wyróżniony. */
  urgent: boolean;
}

/** Plakietka wiersza mówi, którego prepu dotyczy: przy zaplanowanym Prepie 1
 *  „brak prepu” czytało się jak brak obu (przeklikanie 18.10.2026). Te same
 *  słowa co tytuł dzwonka w `notification_triggers.py`. */
export function prepAttentionLabel(row: Pick<PrepAttentionRow, "reason" | "prep_no">): string {
  const n = row.prep_no;
  switch (row.reason) {
    case "missing":
      return `brak Prepu ${n}`;
    case "late":
      return `Prep ${n} po rozmowie`;
    case "weak":
      return `Prep ${n} słaby`;
    case "unrecorded":
      return `Prep ${n} bez nagrania`;
  }
}

/** Karta kandydata w kalendarzu „Rozmowy u klienta” (`?cycle=c-j`). */
export function prepAttentionLink(row: Pick<PrepAttentionRow, "candidate_id" | "job_id">): string {
  return `/calendar?cycle=${row.candidate_id}-${row.job_id}`;
}

/** Jak osoba pasuje do kategorii requestu: 1. priorytet, 2. priorytet, spoza kategorii. */
export type AllocationFit = "first" | "second" | "other";

/**
 * Propozycja automatu przydziału czekająca na decyzję (02.10.2026). Wiersze
 * dostaje wyłącznie osoba, która o nich decyduje (admin, Head of Recruitment);
 * decyzja idzie przez `decideProposal` / `acceptProposals`
 * z `lib/api/requestAllocation`.
 */
export interface AllocationProposalRow {
  job_id: number;
  title: string;
  client_name: string | null;
  category_id: number | null;
  category_name: string | null;
  category_slug: string | null;
  delivery_lead_name: string | null;
  priority_level: PriorityLevel;
  /** Termin requestu (`RRRR-MM-DD`). */
  deadline: string | null;
  /** Ile osób z tego requestu dotarło już do klienta. */
  sent: number;
  /** Proponowana osoba. */
  user_id: number;
  user_name: string;
  fit: AllocationFit;
  /** Ile requestów „Szukamy” bez championa ta osoba ma teraz w pracy. */
  load: number;
  /** Do kiedy osoba jest dziś na urlopie (`RRRR-MM-DD`); `null` = pracuje,
   *  a przy `allocation_leave_known: false` — nie wiadomo. */
  leave_until: string | null;
  /** Pasujący w bazie z nocnego przeglądu; `null` = przeglądu nie było. */
  base_matches: number | null;
  proposed_at: string;
}

/** Skąd rekrutacja ma rekrutera prowadzącego. */
export type NewJobLeadSource = "auto" | "manual";

/**
 * Dlaczego rekrutacja nie ma jeszcze prowadzącego: automat właśnie przydziela,
 * priorytet „Przyjmujemy kandydatów” (automat takich nie obsadza) albo po
 * prostu nikt nie jest przypisany. `not_handed_off` = rekrutacja opublikowana,
 * której nikt nigdy nie przekazał do searchu (`handed_off_at` niesie wtedy
 * datę założenia).
 */
export type NewJobLeadPendingReason = "assigning" | "passive" | "none" | "not_handed_off";

/** Co zaczęło bieżący cykl listy „Nowe rekrutacje P1 — kto prowadzi”. */
export type NewJobLeadSinceReason = "handoff" | "reopen" | "p1";

/**
 * „Nowe rekrutacje — kto prowadzi”: rekrutacje świeżo przekazane do searchu
 * z rekruterem prowadzącym. Lista informacyjna — w trybie „auto” automat
 * przydziela od razu, a Head of Recruitment zmienia tylko to, z czym się nie
 * zgadza. Wiersze dostaje wyłącznie admin i Head of Recruitment.
 */
export interface NewJobLeadRow {
  job_id: number;
  title: string;
  client_name: string | null;
  category_id: number | null;
  category_name: string | null;
  category_slug: string | null;
  /** Ile osób z kategorii jest uczestnikami rekrutacji. */
  participants: number;
  /** `PriorityLevel`; nieznaną wartość traktujemy jak brak plakietki. */
  priority_level: string;
  delivery_lead_name: string | null;
  /**
   * Początek bieżącego cyklu listy (ISO): przekazanie do searchu, ponowne
   * otwarcie albo wejście na P1 — co, mówi `since_reason`.
   */
  handed_off_at: string;
  since_reason?: NewJobLeadSinceReason;
  lead_user_id: number | null;
  lead_name: string | null;
  lead_role: string | null;
  lead_source: NewJobLeadSource | null;
  /** Kto wskazał prowadzącego ręcznie. */
  assigned_by_name: string | null;
  /** Prowadzący to propozycja automatu czekająca na akceptację („shadow”). */
  proposed: boolean;
  pending_reason: NewJobLeadPendingReason | null;
  /**
   * Wiersz wrócił: w tym cyklu Head of Recruitment zdecydował o innej osobie —
   * kto to był.
   */
  returned_from_user_id?: number | null;
  returned_from_name?: string | null;
}

/** „Twoje CV w drodze” — lustro `services/cv_in_transit.py`. */
export type CvTransitKind =
  | "rejected_by_dl"
  | "sent_back"
  | "cpro_returned"
  | "in_review"
  | "cpro_queue"
  | "sent";

export interface CvTransitRow {
  kind: CvTransitKind;
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  job_working_title?: string | null;
  client_name?: string | null;
  since: string;
  /** Kto odrzucił, cofnął albo wysłał. */
  actor_name?: string | null;
  /** U kogo karta czeka (w przeglądzie). */
  holder_name?: string | null;
  reason?: string | null;
  /** Uwaga dla rekrutera zostawiona przy decyzji (początek; całość w notatkach). */
  remark?: string | null;
  /** D4 (04.10.2026): kto inny poprawił kartę rekomendacji od przekazania. */
  card_edited_by?: string | null;
  /** Nazwy poprawionych pól karty (jak na ekranie karty). */
  card_edited_fields?: string[];
  /** D6 (08.10.2026): pola, które Delivery Lead wskazał do poprawy. */
  fix_labels?: string[];
  // 13.10.2026 — tylko „QC CV” poza Nordeą (`in_review`). Starszy serwer i
  // pozostałe rodzaje wierszy pól nie niosą.
  /** Stan QC pary: `failed` / `unchecked` = ruch ma jeszcze rekruter. */
  qc_status?: QcStatus | null;
  /** Od kiedy CV jest gotowe i czeka na Delivery Leada (`null` = jeszcze nie). */
  ready_since?: string | null;
  /** Dni robocze od gotowości. */
  waiting_workdays?: number;
  /** Gotowe CV czeka co najmniej 2 dni robocze — rekruter może przypomnieć. */
  can_nudge?: boolean;
}

export interface CvInTransit {
  returned: CvTransitRow[];
  in_review: CvTransitRow[];
  sent: CvTransitRow[];
  /** Liczby przed przycięciem list przez serwer. */
  returned_total: number;
  in_review_total: number;
  sent_total: number;
  returned_window_days: number;
  sent_window_days: number;
}

/**
 * Rekrutacja do dokończenia albo zamknięcia (Rekrutacja bez szkiców): stary
 * szkic (`legacy_draft`, zamyka się sam po terminie `autoclose_on`) albo
 * rekrutacja opublikowana, której nikt nie przekazał do searchu
 * (`published_not_handed_off`). DL widzi swoje, Head of Recruitment i admin
 * — wszystkie.
 */
export type PendingJobKind = "legacy_draft" | "published_not_handed_off";

export interface PendingJobRow {
  job_id: number;
  title: string;
  client_name: string | null;
  kind: PendingJobKind;
  /** Kiedy rekrutację założono (ISO). */
  created_at: string;
  delivery_lead_name: string | null;
  /** Braki do przekazania do searchu, zdaniami z serwera. */
  missing: string[];
}

export interface PendingJobs {
  /** Dzień (`RRRR-MM-DD`), od którego system zamyka niedokończone szkice;
   *  `null` = automat nie jest zaplanowany. */
  autoclose_on: string | null;
  items: PendingJobRow[];
}

/** Formularz nowej rekrutacji zapisany na koncie i niewysłany (starszy niż 2 dni). */
export interface UnfinishedJobForm {
  id: number | string;
  label: string;
  client_name: string | null;
  updated_at: string;
}

/** „Wymagania do poprawy” (13.10.2026, D4) — lustro `requirement_cleanup.load_fixes`. */
export interface RequirementFixRow {
  job_id: number;
  title: string;
  reasons: { code: string; text: string }[];
  /** `false` = brak słów do szukania — zatwierdzić się nie da, trzeba uzupełnić. */
  can_apply: boolean;
  rows: number;
  talk: number;
}

/** Sprawa z grupy „Umowy” — lustro `services/agreement_tasks.py` (04.10.2026). */
export type AgreementTaskReason =
  | "requested"
  | "hired_unsigned"
  | "closed_unsigned"
  | "closed_signed_active";

export interface AgreementTaskRow {
  generated_id: number;
  contract_number: string;
  reason: AgreementTaskReason;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_name: string | null;
  since: string | null;
  requested_by_name: string | null;
  contract_id: number | null;
}

export interface AgreementTasks {
  /** Do potwierdzenia podpisu — osoby z uprawnieniem „Podpis B2B”. */
  to_confirm: AgreementTaskRow[];
  /** Karta zamknięta przy żywej umowie: anuluj albo zakończ współpracę. */
  to_close: AgreementTaskRow[];
  /** Twoje prośby o potwierdzenie podpisu, na które czekasz. */
  waiting_on_others: AgreementTaskRow[];
}

export const AGREEMENT_TASK_REASON_LABEL: Record<AgreementTaskReason, string> = {
  requested: "Prośba o potwierdzenie podpisu",
  hired_unsigned: "„Zatrudniony”, umowa bez podpisu",
  closed_unsigned: "Proces zamknięty, umowa „W trakcie”",
  closed_signed_active: "Proces zamknięty, kontrakt trwa",
};

/** „Twój ruch” — Ogłoszenia jednej rekrutacji (`services/board_flow.py`). */
export interface FlowPostingRow {
  job_id: number;
  job_title: string;
  job_working_title?: string | null;
  client_name?: string | null;
  count: number;
  /** Najstarsze zgłoszenie w Ogłoszeniach (ISO). */
  oldest_at: string;
}

/** `why_candidate`: rekrutacja bez pytań screeningowych — brakuje oceny zamiast arkusza. */
export type FlowMissing = "sheet" | "why_candidate" | "rate";

/** Jedna osoba w jednej rekrutacji (Nowi z blokadą, Screening, Zweryfikowany, DL). */
export interface FlowPairRow {
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  job_working_title?: string | null;
  client_name?: string | null;
  since: string;
  claimed_until?: string | null;
  missing?: FlowMissing[];
  qc_status?: string | null;
}

/** Jedna osoba z „Najlepszych propozycji z bazy” (07.10.2026). */
export interface FlowProposalPerson {
  candidate_id: number;
  candidate_name: string;
  score?: number | null;
}

/** Najlepsze otwarte propozycje nocnego przeglądu jednej rekrutacji. */
export interface FlowJobProposals {
  job_id: number;
  job_title: string;
  job_working_title?: string | null;
  client_name?: string | null;
  /** Wszystkie otwarte propozycje z bazy tej rekrutacji. */
  total: number;
  people: FlowProposalPerson[];
}

/**
 * Osoba od systemu (silnik „Nowi na 20”, 23.10.2026) po 2 dniach roboczych
 * w „Nowych” bez decyzji — „Dzwonię” albo odrzucenie z powodem.
 */
export interface FlowAutofillDecision {
  job_id: number;
  job_title: string;
  job_working_title?: string | null;
  client_name?: string | null;
  candidate_id: number;
  candidate_name: string;
  score?: number | null;
  /** Dni robocze bez decyzji. */
  waiting_days: number;
}

export interface FlowContractRow {
  id: number;
  contract_number: string;
  partner_name?: string | null;
  client_name?: string | null;
  created_at: string;
  /** Umowa w podpisie w NEXUSIE (etap 1b) — nikt nie musi dzwonić do Partnera. */
  esign_status?: "sent" | "contractor_signed" | null;
}

/**
 * „Nowe requesty dla Ciebie” — rekrutacja przypisana tej osobie w ostatnich
 * `new_request_days` dniach, w której nikt jeszcze nie ruszył karty.
 */
export interface FlowNewRequestRow {
  job_id: number;
  job_title: string;
  job_working_title?: string | null;
  client_name?: string | null;
  /** Kiedy przypisano (ISO). */
  assigned_at: string;
  /** Kto przypisał; `null` = przydział automatu. */
  assigned_by_name: string | null;
}

export interface FlowBlock {
  /** Rola ma sekcje przepływu (rekruter, TCM, DL) — panel mówi wtedy wprost,
   *  że nic nie czeka, zamiast znikać. */
  applies: boolean;
  /** Opcjonalne w typie — starszy backend pola nie oddaje (brak = pusta lista). */
  new_requests?: FlowNewRequestRow[];
  new_request_days?: number;
  postings: FlowPostingRow[];
  postings_total: number;
  claimed: FlowPairRow[];
  screening: FlowPairRow[];
  verified: FlowPairRow[];
  waiting_client: FlowPairRow[];
  waiting_client_days: number;
  unsigned_contracts: FlowContractRow[];
  order_mail_review: number;
  /** 07.10.2026 — starszy serwer pola nie zna (brak = pusta lista). */
  top_proposals?: FlowJobProposals[];
  top_proposals_per_job?: number;
  /** 23.10.2026 — osoby od systemu czekają na decyzję (brak = pusta lista). */
  autofill_decisions?: FlowAutofillDecision[];
  autofill_decisions_total?: number;
}

export interface FinanceBlock {
  gaps_open: number;
  pdfs_new: number;
  order_mail_failed: number;
  hired_without_order: FlowPairRow[];
  hired_without_order_total: number;
}

export interface BoardTasksResponse {
  cpro_to_send: BoardTaskRow[];
  cpro_sent: BoardTaskRow[];
  // Pola Pipeline v4 serwer wysyła zawsze; opcjonalne w typie (panel traktuje
  // brak jak pustą listę / bramkę z ról).
  /** v5: osoby w kolumnie „QC CV" poza Nordeą czekające na przegląd DL. */
  dl_review?: BoardTaskRow[];
  window_days: number;
  dl_review_window_days?: number;
  /** Ruch na „CV wysłane" ze stawką do klienta — admin i Delivery Lead. */
  can_send_to_client?: boolean;
  /** 0370: brak prepu, prep słaby albo bez nagrania. Opcjonalne w typie —
   *  harnessy zasiewają kolejkę sprzed 0355 (brak = pusta lista). */
  prep_attention?: PrepAttentionRow[];
  /** 0372: follow-upy z kandydatami do zrobienia przez Ciebie (termin do
   *  jutra). Opcjonalne w typie — brak = pusta lista. */
  followups?: FollowupRow[];
  /** 0372: Twoi kandydaci, z którymi follow-up robi ktoś inny. */
  followups_by_others?: FollowupRow[];
  /** Osobę od Cpro ustawia admin albo Delivery Lead Nordei (25.09.2026) —
   *  przełącznik stoi także wtedy, gdy sekcja Cpro jest pusta. */
  can_set_cpro_sender?: boolean;
  /** 02.10.2026: propozycje automatu przydziału do akceptacji. Opcjonalne
   *  w typie — starszy backend ich nie oddaje (brak = pusta lista). */
  allocation_proposals?: AllocationProposalRow[];
  /** Czy pytający rozstrzyga propozycje (admin, Head of Recruitment). */
  can_decide_proposals?: boolean;
  /** Czy urlopy z Compassa są świeże; bez tego brak urlopu znaczy „nie wiadomo”. */
  allocation_leave_known?: boolean;
  /** „Nowe rekrutacje — kto prowadzi” — tylko admin i Head of Recruitment
   *  (reszta dostaje pustą listę); starszy backend pola nie oddaje. */
  new_job_leads?: NewJobLeadRow[];
  /** „Twoje CV w drodze” — co dzieje się z CV po przekazaniu karty. `null`
   *  albo brak = osoba usunęła listę z pulpitu (albo serwer jej nie policzył). */
  cv_in_transit?: CvInTransit | null;
  /** Rekrutacje do dokończenia albo zamknięcia. Starszy backend pola nie
   *  oddaje; `null` = nic do pokazania. Do „czeka” się nie liczy. */
  pending_jobs?: PendingJobs | null;
  /** Twoje niedokończone formularze nowej rekrutacji. */
  unfinished_forms?: UnfinishedJobForm[] | null;
  /** Porządki wymagań otwartych rekrutacji — DL swoich, HoR i admin wszystkich. */
  /** `null` = serwer nie policzył listy (awaria), `[]` = nic do poprawy. */
  requirement_fixes?: RequirementFixRow[] | null;
  /** Umowy z Generatora do potwierdzenia albo zamknięcia (04.10.2026).
   *  `null`/brak = serwer jej nie policzył albo starszy backend. */
  agreements?: AgreementTasks | null;
  /** 04.10.2026: cały przepływ (Ogłoszenia → umowa). `null` = rola bez sekcji. */
  flow?: FlowBlock | null;
  /** 04.10.2026: praca Finansów. `null` = konto bez roli Finanse. */
  finance?: FinanceBlock | null;
  // 0418: zmiany stawki kandydata (decyzja DL, negocjacja) i zgłoszenia,
  // które czekają na innych.
  rate_changes?: RateChangeTaskRow[];
  rate_changes_by_others?: RateChangeTaskRow[];
}

export const BOARD_TASKS_QUERY_KEY = ["board-tasks"] as const;

export function useBoardTasks() {
  return useQuery<BoardTasksResponse>({
    queryKey: BOARD_TASKS_QUERY_KEY,
    queryFn: () => api.get<BoardTasksResponse>("/api/board-tasks").then((r) => r.data),
    // Ruch na Tablicy unieważnia klucz sam (`pipeline_changed`); odpytywanie
    // to tylko siatka bezpieczeństwa.
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    staleTime: 30_000,
  });
}

export interface DlReviewRowResponse {
  row: BoardTaskRow;
  can_send_to_client: boolean;
}

/** Przegląd DL jednej pary — ten sam wiersz co na pulpicie (z etapem CV po
 *  QC, osobą weryfikującą i stanem karty). Tablica i link z dzwonka
 *  („?review=1”) otwierają przegląd z tego wiersza. 404 = osoba nie czeka
 *  na przegląd. */
export function fetchDlReviewRow(candidateId: number, jobId: number) {
  return api
    .get<DlReviewRowResponse>("/api/board-tasks/dl-review-row", {
      params: { candidate_id: candidateId, job_id: jobId },
    })
    .then((r) => r.data);
}

export interface DlSendNudgeResult {
  sent: boolean;
  /** Ilu Delivery Leadów dostało dzwonek (przy `sent`). */
  recipients?: number;
  /** `already_today` — dziś już przypomniano o tej karcie. */
  reason?: string;
}

/** „Przypomnij” w „Twoje CV w drodze”: dzwonek do Delivery Leada o gotowym CV,
 *  które czeka na wysyłkę do klienta. Najwyżej raz dziennie na kartę. */
export function nudgeDlSend(stageId: number) {
  return api.post<DlSendNudgeResult>(`/api/board-tasks/dl-send/${stageId}/nudge`).then((r) => r.data);
}

// ── Cpro: jedna osoba na firmę (v5) ─────────────────────────────────────────

export interface CproSender {
  /** `null` = nikt nie jest ustawiony. */
  user_id: number | null;
  user_name: string | null;
  /** Zastępstwo do tego dnia (ISO), potem wraca `fallback_*`. */
  until: string | null;
  fallback_user_id: number | null;
  fallback_user_name: string | null;
  set_by_name: string | null;
  set_at: string | null;
  /** Czy pytający może zmienić osobę (admin albo Delivery Lead Nordei). */
  can_set?: boolean;
}

export interface CproQueueItem {
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  since: string;
  process_state_version: number;
  /** Etap „Wysłane do Cpro" — cel „✓ Wrzucone". */
  target_stage_def_id: number | null;
  /** Etap „QC CV" — cel „Zwróć do rekrutera". */
  return_stage_def_id: number | null;
  client_rate_value: number | null;
  client_rate_unit: "hourly" | "daily" | "monthly" | null;
  client_rate_currency: string | null;
  availability: string | null;
  qc_status: QcStatus | null;
  /** `stage_id` = CV firmowe etapu (po QC) — ma pierwszeństwo przed generatorem. */
  cv: {
    stage_id?: number | null;
    generated_document_id: number | null;
    document_id: number | null;
  } | null;
  /** Kto włożył osobę do kolejki i kiedy. Od 13.10.2026 robi to wyłącznie
   *  Delivery Lead po akceptacji; `accepted: false` = karta sprzed tej zmiany,
   *  włożona przez rekrutera („Bez akceptacji DL”). */
  accepted?: boolean;
  accepted_by_name?: string | null;
  accepted_at?: string | null;
  /** Uwaga Delivery Leada zapisana przy akceptacji. */
  dl_note?: string | null;
}

export interface CproQueueJob {
  job_id: number;
  job_title: string;
  /** 0380: tytuł dla rekrutera (ekrany wewnętrzne); `job_title` = nazwa od klienta. */
  job_working_title?: string | null;
  client_reference?: string | null;
  client_name: string | null;
  oldest_since: string;
  items: CproQueueItem[];
}

export interface CproQueueResponse {
  sender: CproSender;
  jobs: CproQueueJob[];
  sent_today: number;
}

export const CPRO_SENDER_QUERY_KEY = ["board-tasks", "cpro", "sender"] as const;
export const CPRO_QUEUE_QUERY_KEY = ["board-tasks", "cpro", "queue"] as const;

export function useCproSender(enabled = true) {
  return useQuery<CproSender>({
    queryKey: CPRO_SENDER_QUERY_KEY,
    queryFn: () => api.get<CproSender>("/api/board-tasks/cpro/sender").then((r) => r.data),
    enabled,
    staleTime: 60_000,
  });
}

export function useCproQueue(enabled = true) {
  return useQuery<CproQueueResponse>({
    queryKey: CPRO_QUEUE_QUERY_KEY,
    queryFn: () => api.get<CproQueueResponse>("/api/board-tasks/cpro/queue").then((r) => r.data),
    enabled,
    // Ruch z okna unieważnia kolejkę sam; odpytywanie to siatka bezpieczeństwa.
    refetchInterval: enabled ? WS_BACKED_SAFETY_POLL_MS : false,
  });
}

/** Osoba od Cpro dla CAŁEJ firmy; `until` = zastępstwo (potem wraca poprzednia). */
export function setCproSender(body: { user_id: number; until: string | null }) {
  return api.put<CproSender>("/api/board-tasks/cpro/sender", body).then((r) => r.data);
}

export interface CproJobGroup {
  job_id: number;
  job_title: string;
  client_name: string | null;
  /** Najdłużej czekający na górze — ta sama kolejność co lista z serwera. */
  rows: BoardTaskRow[];
}

/** „Do wrzucenia do Cpro" pogrupowane po rekrutacji — jedna linia na proces. */
export function groupCproByJob(rows: BoardTaskRow[]): CproJobGroup[] {
  const groups = new Map<number, CproJobGroup>();
  for (const row of rows) {
    let group = groups.get(row.job_id);
    if (!group) {
      group = { job_id: row.job_id, job_title: row.job_title, client_name: row.client_name, rows: [] };
      groups.set(row.job_id, group);
    }
    group.rows.push(row);
  }
  return [...groups.values()];
}

export interface AssigneeOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

// Osoby, które mogą wysłać kandydata do Cpro — ten sam katalog, z którego
// wybiera się zespół rekrutacji (+ Head of Recruitment).
const ASSIGNEE_ROLES = [
  "recruiter",
  "delivery_lead",
  "talent_community_manager",
  "head_of_recruitment",
  "admin",
];

export function useCproAssigneeOptions(enabled = true) {
  return useQuery<AssigneeOption[]>({
    queryKey: ["users-directory", "cpro-assignees"],
    queryFn: () =>
      api
        .get<AssigneeOption[]>("/api/users", {
          params: { roles: ASSIGNEE_ROLES },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function assigneeLabel(option: AssigneeOption): string {
  return option.name || option.email || `Użytkownik #${option.id}`;
}

/**
 * „od dziś", „od wczoraj", „od 3 dni" — ile czeka osoba w kolejce.
 *
 * Runda 10 (R10-X1-5): dni KALENDARZOWE w Europe/Warsaw, nie pełne doby —
 * osoba, która weszła wczoraj o 17:00, o 9:00 czeka „od wczoraj”, nie „od dziś”.
 */
export function waitingFor(since: string, now: Date = new Date()): string {
  const sinceDate = new Date(since);
  if (Number.isNaN(sinceDate.getTime())) return "od dziś";
  const dayNumber = (d: Date) => Date.parse(`${warsawToday(d)}T00:00:00Z`) / 86_400_000;
  const days = Math.round(dayNumber(now) - dayNumber(sinceDate));
  if (days <= 0) return "od dziś";
  if (days === 1) return "od wczoraj";
  return `od ${days} dni`;
}
