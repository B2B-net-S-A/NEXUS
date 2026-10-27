"use client";

/**
 * Typy i drobne helpery pipeline'u kanbanowego, wydzielone z
 * `KanbanBoardV2.tsx` (krok 04 Pipeline, program „flow w języku C2", PR 3/7).
 *
 * Powód wydzielenia: `KanbanBoardV2` renderuje `PipelineCandidateDock` i
 * `PipelineFiltersRail`, a oba potrzebują tych samych typów/identyfikatorów
 * kolumn (`KanbanItem`, `KanbanColumn`, `colId`, `columnLabel`) i tego samego
 * pierścienia wyniku (`ScoreRing`, żeby dok pokazywał TEN SAM wizualny
 * element co karta — „ten sam `pipelineScores`"). Import tego z samego
 * `KanbanBoardV2.tsx` zamknąłby cykl (KanbanBoardV2 → dok/rail →
 * KanbanBoardV2); ten moduł nie importuje niczego z żadnego z nich, więc
 * cyklu nie ma.
 */

import type { CardPreContract } from "@/lib/api/preContracts";
import type { EmploymentMarker } from "@/lib/employment-marker";
import type { CardAgreement } from "@/lib/b2b-agreement";
import type { ClientAcceptanceBadge } from "@/lib/client-acceptance";
import { memo } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { RateUnit } from "@/lib/api";
import type { FollowupCardBadge } from "@/lib/api/candidateFollowups";
import type { CandidateContactSummary } from "@/lib/candidate-contact";
import type {
 DebriefSummary,
 Prep2Skip,
 Prep2SkipStatus,
 SlotRequest,
 StepKey,
 StepState,
} from "@/lib/interview-cycle";
import type { InterviewPhase } from "@/lib/pipeline-next-action";
import type { RateChangeBadge } from "@/lib/rate-change";
import type { OffLimitsBadge } from "@/lib/off-limits";

// ── Types ─────────────────────────────────────────────────────────────

/** Inna rekrutacja, w której osoba stoi w „Nowych”/„Screeningu” (karta „+1 rekrutacja”). */
export interface OtherOpenJob {
 job_id: number;
 title: string;
 client_name: string | null;
 column: string;
}

export interface KanbanItem {
 id: number;
 candidate_id: number;
 stage: string;
 stage_def_id?: number | null;
 rating?: number;
 /** Kiedy karta weszła na bieżący etap (ISO). */
 moved_at?: string | null;
 days_in_stage?: number;
 name?: string;
 lastname?: string;
 // Kto przypisał kandydata do tej rekrutacji (rekruter z najwcześniejszego
 // etapu pary kandydat/oferta) i kiedy — pokazywane w tooltipie karty.
 added_to_job_by_name?: string | null;
 /** Numer tej osoby — filtr „Kto dodał” na Tablicy (14.10.2026). */
 added_to_job_by_id?: number | null;
 added_to_job_at?: string | null;
 /** Kto zweryfikował (pierwszy weryfikujący pary, jak premia rekrutera;
  *  21.10.2026) — od tej kolumny karta pokazuje tę osobę zamiast dodającej. */
 verified_by_name?: string | null;
 verified_by_id?: number | null;
 verified_at?: string | null;
 /** „Prowadzi” (25.10.2026): osoba przypisana przez admina albo HoR —
  *  wygrywa z weryfikującym i dodającym na karcie, w panelu i w filtrze.
  *  Pola są tylko przy przypisaniu. */
 owner_user_id?: number | null;
 owner_name?: string | null;
 owner_assigned_by_name?: string | null;
 owner_assigned_at?: string | null;
 owner_previous_name?: string | null;
 /** „Biorę” zmienia osobę karty (27.10.2026): ostatnia osoba, która wzięła,
  *  także po 12 h — do pierwszej weryfikacji. Wygrywa z dodającym. */
 taken_by_user_id?: number | null;
 taken_by_name?: string | null;
 /** Komentarz z okna ruchu (przy odrzuceniu — wpisany w oknie powodu). */
 notes?: string | null;
 // Karty w „Odrzuconych” i „Rezygnacjach” (19.10.2026): etykieta powodu
 // i kto zamknął kartę — `lib/closed-reason.ts`. Brak pola = starszy serwer.
 rejection_reason_name?: string | null;
 closed_by_name?: string | null;
 // „W bazie od” (0437): kiedy osoba weszła do bazy, czy data jest dokładna
 // (import z Traffita bez daty u źródła = nie) i kto ją dodał. Tylko z Tablicy.
 candidate_added_at?: string | null;
 candidate_added_exact?: boolean;
 candidate_added_by_name?: string | null;
 /** Żywy champion tej rekrutacji (D3, 15.10.2026) — oznacza Delivery Lead
  *  w nagłówku rekrutacji; karta i panel osoby tylko to pokazują. */
 is_champion?: boolean;
 // Stawka z ruchu na „Zweryfikowany" (0056). `verification_status` nadal
 // przychodzi z serwera, ale od 17.09.2026 NIC nie reaguje na "pending"
 // (bramka zdjęta, migracja 0323 odblokowała stare karty).
 verification_status?:"active" |"pending" |"rejected";
 expected_rate_value?: string | number | null;
 expected_rate_unit?: RateUnit | null;
 expected_rate_currency?: string | null;
 budget_max_at_move?: number | null;
 // Stawka zapisana przy ruchu przekracza budżet rekrutacji — informacja
 // (odznaka „ponad budżet"), nie blokada. Bramka „Pending" wyłączona 17.09.2026.
 budget_exceeded?: boolean;
 // Reakcja kandydata na ofertę (migracja 0066) — zapisywana przy wycofaniu po
 // akceptacji. `null`/brak = nie zapisano; `pending` to JAWNE „czekamy”.
 candidate_offer_response?: "pending" |"accepted" |"declined" | null;
 // Hiring manager tej oferty odrzucił już tego kandydata po rozmowie na innej
 // rekrutacji. Manager jest domyślny (to manager tej oferty), więc chip nie
 // niesie nazwiska — kto/kiedy/dlaczego siedzi w tooltipie.
 hm_veto?: {
  hiring_manager_contact_id: number;
  hiring_manager_name?: string | null;
  source_job_id: number;
  source_job_title?: string | null;
  rejected_at: string;
  rejection_reason_name: string;
  rejection_note?: string | null;
 } | null;
 contact_case?: CandidateContactSummary | null;
 // F05: `RecruitmentProcess.state_version` z tablicy (0 = brak procesu).
 // Pojedynczy ruch odsyła ją jako `expected_state_version`.
 process_state_version?: number | null;
 // Odznaki (17.09.2026, „okna po ruchu → odznaki"): czy NA TYM wierszu jest
 // zapisany arkusz screeningu / scorecard. Karta pokazuje „do uzupełnienia"
 // zamiast otwierać formularz zaraz po ruchu.
 screening_done?: boolean;
 // Rekrutacja bez pytań screeningowych (13.10.2026): zamiast arkusza wymagane
 // jest „Dlaczego ten kandydat” — `screening_done` znaczy wtedy „ocena
 // wpisana”. Brak pola albo `null` = zwykły arkusz.
 screening_requirement?: "why_candidate" | null;
 // Minimum dla Delivery Leada (21.10.2026): klucze pól karty bez treści —
 // lokalizacja, tryb pracy, dostępność, „Dlaczego ten kandydat”, pola
 // klienta. Ta sama reguła co bramka „Zweryfikowany”. Brak pola = nie wiadomo.
 minimum_missing?: string[] | null;
 // 22.10.2026: ostatni ruch Delivery Leada mimo braków — klucze braków
 // (jak `missing` bramki serwera) i kto przesunął. Brak pola = nie było.
 requirements_skipped?: string[] | null;
 requirements_skipped_by_name?: string | null;
 scorecard_done?: boolean;
 // Automaty (21.09.2026): na TYM etapie leży gotowe auto-CV czekające na
 // przegląd człowieka. Brak pola (starsza odpowiedź) = brak odznaki.
 auto_cv_ready?: boolean;
 // Droga rekrutera do DL (14.10.2026): automat CV właśnie generuje szkic dla
 // TEGO etapu („CV w przygotowaniu…”). Brak pola = starszy serwer.
 auto_cv_state?: "processing" | null;
 // Para ma CV firmowe (szkic albo zatwierdzone) — `knownForwardGap` z
 // „Zweryfikowany” na „QC CV”. Brak pola / `null` = nie wiadomo (bez blokady).
 company_cv?: boolean | null;
 // 0521: klient bierze formularz CV zamiast CV firmowego — `template` = jest
 // wzór w Plikach, `missing` = puste pola (`null` = jeszcze nie wypełniony).
 // Brak pola / `null` = klient bierze CV firmowe.
 client_form?: { template: boolean; missing: number | null } | null;
 // Stawka z profilu kandydata (PLN/h) — podpowiedź w oknie „Zweryfikowany".
 candidate_expected_rate_hourly?: string | number | null;
 // „Stawka od” (0414): najniższa stawka z 18 miesięcy — podpowiedź, gdy karta
 // tej rekrutacji nie ma stawki.
 candidate_rate_from_hourly?: string | number | null;
 // Widok „rekrutacja = jedna tabela" (wersja 3, 09.2026). Wszystkie pola są
 // opcjonalne: starsza odpowiedź ich nie niesie, a tabela ma wtedy powiedzieć
 // „—", nie zgadywać.
 // Rekruter karty: właściciel procesu, a gdy go nie ma — osoba, która dodała
 // kandydata do rekrutacji.
 recruiter_id?: number | null;
 recruiter_name?: string | null;
 // 0348: kto wysyła osobę do Cpro — tylko na etapie „Wysłać do Cpro".
 task_assignee_id?: number | null;
 task_assignee_name?: string | null;
 // Postawa kandydata wobec nowych projektów (`AvailabilityStatus`) i data,
 // od której jest dostępny.
 availability_status?: string | null;
 availability_date?: string | null;
 // „Do wysłania do klienta”: karta liczy się do „Czeka na Ciebie” (rekrutacja
 // opublikowana, etap nie z importu Traffita — `dl_send_queue`). `false` =
 // poza licznikami; brak pola (starszy serwer) = jak dotąd.
 dl_send_counts?: boolean | null;
 // Kody ostrzeżeń karty w stałej kolejności (`hm_veto`, `budget_exceeded`,
 // kody polityki dopuszczalności — konflikt z klientem itd.).
 warnings?: string[];
 // Znacznik „Pracuje u nas”; `elsewhere` względem klienta tej rekrutacji.
 employment_marker?: EmploymentMarker | null;
 // „+1 rekrutacja” (14.10.2026): inne niezamknięte rekrutacje, w których ta
 // osoba stoi w „Nowych”/„Screeningu” (`services/also_fits.py`), najwyżej 5.
 other_open_jobs?: OtherOpenJob[];
 // Kto ma ruch według serwera — lustro `NextActionOwner` z
 // `lib/pipeline-next-action.ts` (unia wpisana wprost: tamten moduł importuje
 // typy stąd, więc import w drugą stronę zamknąłby cykl).
 next_action_owner?: "recruiter" | "client" | "candidate" | "delivery" | "none";
 // ── Pipeline v4 (0352, 23.09.2026) — odznaki karty (`lib/board-card-badges.ts`) ─
 // Kto zakończył proces (wiersz terminalny).
 ended_by?: "candidate" | "recruiter" | "delivery_lead" | "client" | null;
 // Stawka, za którą osobę wysłano do klienta.
 client_rate_value?: string | number | null;
 client_rate_unit?: RateUnit | null;
 client_rate_currency?: string | null;
 // Skąd osoba weszła do rekrutacji; `null` = proces sprzed 0352.
 entry_source?:
  | "added_manual"
  | "application"
  | "proposal"
  | "reassign"
  | "auto_match"
  | "import"
  // 0515 (23.10.2026): silnik „System trzyma Nowych na 20”.
  | "system"
  | null;
 /**
  * Osoba od systemu (23.10.2026) — plakietka „Od systemu · 81%”, powód
  * w panelu osoby i termin decyzji (`services/autofill_decisions.py`).
  * `waiting_days` = dni robocze bez decyzji; `null` = zdecydowano albo
  * rekrutacja bez rekrutera (termin startuje od przypisania).
  */
 entry_autofill?: {
  score: number;
  matched_must: string[];
  missing_must: string[];
  rate_known: boolean;
  availability_known: boolean;
  decided: boolean;
  waiting_days: number | null;
  decision_due: boolean;
  /**
   * 27.10.2026: co przemawia przeciw, a system to wiedział (budżet, biuro,
   * miasto) — napis i dymek liczy serwer (`process_entry_meta._caution`).
   */
  cautions?: { key: string; label: string; title: string }[];
 } | null;
 /**
  * 0399: wynik automatu przy wejściu — plakietka „Auto-match 67/100 · JJIT”
  * (do 29.09.2026 automaty pisały go jako notatkę w historii kandydata).
  */
 entry_auto_match?: {
  score: number;
  source: string;
  must_hit: string[];
  must_total: number | null;
 } | null;
 /**
  * 0404: przegląd AI zgłoszenia z linku rekrutacji — plakietka „AI: pasuje”,
  * „AI: do sprawdzenia”, „AI nie oceniło”; `null` = wejście bez przeglądu.
  */
 entry_ai_screening?: {
  verdict: "fits" | "unclear" | "not_fit";
  assessed: boolean;
  must_found: number | null;
  must_total: number | null;
  overridden: boolean;
 } | null;
 /**
  * Off-limits (21.10.2026): osoba z firmy z aktywnym zamówieniem dodana po
  * potwierdzeniu „sam(a) się zgłosił(a)” — kto, kiedy i jak.
  */
 entry_off_limits?: OffLimitsBadge | null;
 /**
  * Etap 2 linków (19.10.2026): właściciel linku rekrutacji, z którego osoba
  * się zgłosiła — plakietka „Z Twojego linku” / „Z linku Marty”.
  */
 entry_link_owner_id?: number | null;
 entry_link_owner_name?: string | null;
 /**
  * …i właściciele innych linków, z których osoba zgłosiła się ponownie, gdy
  * już była w rekrutacji — „Zgłosił się też z Twojego linku”.
  */
 reapplied_via_links?: { owner_id: number; owner_name?: string | null }[];
 reassign_from_job_id?: number | null;
 reassign_from_title?: string | null;
 /** Numer rekrutacji źródłowej („ZOB-1725”) — odznaka „↻ z …”. */
 reassign_from_reference?: string | null;
 // Blokada 12 h w „Nowych" (tylko aktywna) i czy patrzący może „Biorę/Przejmij".
 claim_user_id?: number | null;
 claim_user_name?: string | null;
 claim_until?: string | null;
 can_take?: boolean;
 // Terminarz rozmowy u klienta — gotowa odznaka z serwera.
 interview_badge?: {
  kind: InterviewBadgeKind;
  label: string;
  tone: "wait" | "info" | "ok" | "urgent";
  at?: string | null;
  /**
   * Siedem kroków cyklu (kreski postępu na karcie i w doku); starszy serwer = brak.
   * `at` kroku „interview” to termin rozmowy — liczy względem niego okno prepu w doku.
   */
  steps?: Array<{ key: StepKey; state: StepState; at?: string | null; event_id?: number | null }>;
  /** Rozmowa u klienta pary — debrief otwiera się prosto z doku. */
  interview_event_id?: number | null;
  /** Termin rozmowy czekający jeszcze na wybór albo potwierdzenie (ISO). */
  tentative_interview_at?: string | null;
  /** Prep zaplanowany po rozmowie u klienta — do przełożenia, nie do planowania od nowa. */
  late_prep_event_id?: number | null;
  /** PR 6: otwarty wniosek o terminy od klienta — wybór i potwierdzenie z panelu osoby. */
  slot_request?: SlotRequest | null;
  /** PR 6: prepy pary (ocena prepu z panelu osoby). */
  preps?: Array<{
   id: number;
   prep_no: number | null;
   start: string | null;
   review_status: string | null;
   transcript_status: string | null;
  }>;
  /** 04.10.2026: skrót zapisanego debriefu (warunek kandydata, pytania klienta). */
  debrief?: DebriefSummary | null;
  /**
   * 05.10.2026: faza cyklu dla kroku na karcie („kto ma ruch”,
   * `lib/pipeline-next-action.ts`); starszy serwer = brak.
   */
  phase?: InterviewPhase | null;
  /** Dzień rozmowy (RRRR-MM-DD, strefa firmy) — tylko przy fazie `scheduled`. */
  interview_date?: string | null;
  /** 0482: rozmowa bez Prepu 2 — przycisk, zapisany powód i telefon w doku. */
  prep2_skip_status?: Prep2SkipStatus;
  prep2_skip?: Prep2Skip | null;
  prep1_remaining?: string[];
 } | null;
 // „Zatrudniony": czy jest uzupełnione zamówienie.
 order_status?: "complete" | "missing" | null;
 // 17.10.2026: karta na „Zatrudniony” (z ostatniego roku), a w Kontraktach
 // nie ma żadnej umowy tej osoby u klienta rekrutacji — „Pracuje u nas”
 // liczy się wyłącznie z umowy, więc karta mówi, czego brakuje.
 missing_contract?: boolean;
 // 04.10.2026: umowa B2B z Generatora tej pary — stan z rejestru, w każdej kolumnie.
 agreement?: CardAgreement | null;
 // 0451 (16.10.2026): ostatnia akceptacja klienta pary — karta i panel
 // pokazują ją wyłącznie w kolumnie „Akceptacja i umowa”.
 client_acceptance?: ClientAcceptanceBadge | null;
 /** 0506: umowa przedwstępna pary — plakietka z serwera (`services/pre_contracts.badge`). */
 pre_contract?: CardPreContract | null;
 // 0372: follow-up z kandydatem, gdy klient milczy — kto dzwoni i kiedy
 // (liczone dla OSOBY, ze wszystkimi jej procesami).
 followup?: FollowupCardBadge | null;
 // 0418: otwarta sprawa zmiany stawki kandydata (zgłoszona / w negocjacji / ustalona).
 rate_change?: RateChangeBadge | null;
 // Rekrutacja v5 (0361): najnowszy przebieg QC CV pary. Brak pola = starszy
 // serwer — karta w „QC CV” mówi wtedy „QC nie sprawdzone”, nie „✓”.
 qc?: {
  status: "passed" | "failed" | "overridden" | "unchecked";
  blocking_failed: number;
  /** Kiedy QC przeszło albo ktoś je przepuścił (ISO) — od tej chwili karta
   *  czeka na wysłanie do klienta. Brak = starszy serwer albo QC bez zaliczenia. */
  ok_at?: string | null;
  /** Uwagi nieblokujące najnowszego przebiegu (14.10.2026) — „CV gotowe · QC: N do poprawy”. */
  warnings_count?: number;
 } | null;
 // Karta rekomendacji (0413): stan karty pary i liczba notatek „nie odebrał”.
 // `card: null` = pary nie ma jeszcze w kartach.
 card?: {
   status: "complete" | "partial" | "empty";
   missing: number;
   answers: number;
   /** Stawka kandydata z karty (PLN/h) — podpowiedź w oknie stawki. */
   rate_hourly?: number | null;
 } | null;
 contact_attempts?: number;
}

/** Rodzaje odznaki terminarza — lustro `compute_badge`
 *  (`backend/app/services/interview_cycle.py`). Etykietę i ton daje serwer. */
export type InterviewBadgeKind =
 | "call_due"
 | "choose_slot"
 | "awaiting_dl"
 // 0370: prepy w Teams — przypomnienie, nie bramka.
 | "prep_weak"
 | "prep_missing"
 // 0453: kandydat odrzucił prep albo proponuje inny termin.
 | "prep_refused"
 // 0482: rozmowa bez Prepu 2 (z powodem) — telefon przed rozmową.
 | "prep2_skipped"
 | "prep2"
 | "prep_done"
 | "slot"
 | "debrief_done";

export interface KanbanColumn {
 stage: string;
 category?:"internal" |"external" |"terminal";
 count: number;
 items: KanbanItem[];
 stage_def_id?: number | null;
 name?: string | null;
 order?: number | null;
 /** KTÓRY terminal, nie tylko „czy terminal".
  *
  *  Kolumna bez mapowania na legacy enum raportuje `stage: "new"`, więc
  *  rozpoznawanie terminala po `stage` gubiło WŁASNE etapy terminalne:
  *  „odrzucony" nie otwierał modala powodu (backend odbijał 422), a
  *  „zatrudniony" pomijał potwierdzenie mimo skutków ubocznych. */
 terminal_type?: "hired" | "rejected" | "withdrawn" | null;
}

export const colId = (col: KanbanColumn) =>
 col.stage_def_id ? `def:${col.stage_def_id}` : `stage:${col.stage}`;

export const columnLabel = (col: KanbanColumn) => col.name ?? col.stage;

// ── AI match score ring ──────────────────────────────────────────────
// Circular badge mirroring the hybrid AI match score (0-100): colored arc +
// number. Tiers use FIXED hues (not --primary) so the traffic-light reading
// stays stable across the user-selectable theme palettes / kids mode.

function scoreRingColor(score: number): string {
 if (score >= 75) return "text-emerald-500";
 if (score >= 50) return "text-sky-500";
 if (score >= 25) return "text-amber-500";
 return "text-rose-400";
}

// `score == null` → loading placeholder (muted, pulsing, no number); shown
// while the scores query is still resolving so cold pipelines don't look broken.
export const ScoreRing = memo(function ScoreRing({
 score,
 density,
}: {
 score: number | null;
 density: "cozy" |"compact";
}) {
 const compact = density === "compact";
 const size = compact ? 28 : 40;
 const stroke = compact ? 3 : 3.5;
 const r = (size - stroke) / 2;
 const circ = 2 * Math.PI * r;

 if (score == null) {
 return (
 <div
 className={cn("relative shrink-0 self-center animate-pulse",
 compact ?"h-7 w-7" :"h-10 w-10"
 )}
 aria-label="Obliczanie dopasowania AI…"
 >
 <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full">
 <circle
 cx={size / 2}
 cy={size / 2}
 r={r}
 fill="none"
 strokeWidth={stroke}
 className="stroke-current text-muted-foreground/20"
 />
 </svg>
 </div>
 );
 }

 const pct = Math.max(0, Math.min(100, Math.round(score)));
 const dash = (pct / 100) * circ;
 const color = scoreRingColor(pct);
 return (
 <Tooltip>
 <TooltipTrigger asChild>
 <div
 className={cn("relative shrink-0 self-center", compact ?"h-7 w-7" :"h-10 w-10")}
 aria-label={`Dopasowanie AI: ${pct} na 100`}
 >
 <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full -rotate-90">
 <circle
 cx={size / 2}
 cy={size / 2}
 r={r}
 fill="none"
 strokeWidth={stroke}
 className="stroke-current text-muted-foreground/20"
 />
 <circle
 cx={size / 2}
 cy={size / 2}
 r={r}
 fill="none"
 strokeWidth={stroke}
 strokeLinecap="round"
 strokeDasharray={`${dash} ${circ - dash}`}
 className={cn("stroke-current transition-all", color)}
 />
 </svg>
 <span
 className={cn("absolute inset-0 flex items-center justify-center font-bold",
 compact ?"text-[10px]" :"text-xs",
 color
 )}
 >
 {pct}
 </span>
 </div>
 </TooltipTrigger>
 <TooltipContent side="top">Dopasowanie AI: {pct}/100</TooltipContent>
 </Tooltip>
 );
});
