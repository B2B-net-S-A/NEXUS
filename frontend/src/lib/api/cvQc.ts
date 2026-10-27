// QC CV (Rekrutacja v5, 24.09.2026) — kontrola CV firmowego przed wysłaniem
// do klienta albo do Cpro. Typy są lustrem kontraktu
// `docs/recruitment-v5-contract.md` (backend: `GET/POST
// /api/pipeline/stages/{id}/qc…`). Serwer liczy sprawdzenia i zmienia szkic
// CV; front pokazuje wynik i woła poprawki.

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { apiErrorCode } from "@/lib/cv-qc";

export type QcCheckStatus = "pass" | "fail" | "manual" | "skip";
export type QcSeverity = "blocking" | "warning";
export type QcFixKind =
  | "bold_all"
  | "generate_cv"
  | "upload_consent"
  /** Zrzut zgody nie pasuje do rekrutacji (F37, 27.10.2026) — „Wymień zrzut”. */
  | "replace_consent"
  | "ask_candidate"
  | "remove_term"
  | "ai"
  | "spelling"
  /** „Ułóż od najnowszego” — kolejność stanowisk (16.10.2026). */
  | "role_order";

/** Na czym w odczycie oryginału stoi „oryginał ma tę umiejętność w tej roli”. */
export type QcEvidenceKind = "description" | "technologies" | "title";

export type QcSearchSource = "cv" | "original" | "answers" | "notes";

/** Gdzie QC szukało pozycji i czy znalazło (od 13.10.2026). */
export interface QcSearch {
  source: QcSearchSource;
  found: boolean;
  quote?: string | null;
}

export interface QcItem {
  /** Stały klucz pozycji (sprawdzenie | wymaganie | rola) — od 13.10.2026. */
  key?: string | null;
  requirement?: string | null;
  role?: string | null;
  detail?: string | null;
  fix?: QcFixKind | null;
  term?: string | null;
  /** Numer stanowiska w CV (kolejność ról w sekcji doświadczenia, od 0). */
  role_index?: number | null;
  /** Fragment odczytu oryginalnego CV — przebiegi sprzed 12.10.2026 go nie mają. */
  evidence?: string | null;
  evidence_kind?: QcEvidenceKind | null;
  searched?: QcSearch[];
  /** Tylko w `QcCheck.dismissed_items`: kto, kiedy i dlaczego oznaczył „To nieprawda”. */
  dismissal?: QcDismissal | null;
}

/**
 * Powód „To nieprawda” — lustro `cv_finding_dismissals.REASONS` (13.10.2026, D5).
 * `kept_order` to „Zostaw tę kolejność” przy uwadze „Stanowiska od najnowszego”
 * (16.10.2026), a `kept` — „OK” / „Zostaw” przy uwadze generatora albo kontroli
 * AI w panelu „Do poprawy” (17.10.2026). Żadnego z nich nie ma w formularzu.
 */
export type QcDismissReason = "in_cv" | "other_name" | "wrong_place" | "not_needed" | "other" | "kept_order" | "kept";

/** Pominięcie uwagi („To nieprawda”) — pary kandydat × rekrutacja, nie pliku. */
export interface QcDismissal {
  id: number;
  reason: string;
  reason_label: string;
  note: string | null;
  by_name: string | null;
  at: string;
}

export type QcRoleStateKind = "described" | "missing" | "listed_only" | "not_in_original" | "unverified";

/** „Rola po roli”: stan jednego wymagania w jednej roli z oryginału. */
export interface QcRoleState {
  requirement: string;
  role: string;
  state: QcRoleStateKind;
}

export interface QcCheck {
  key: string;
  label: string;
  severity: QcSeverity;
  status: QcCheckStatus;
  summary: string | null;
  items: QcItem[];
  roles?: QcRoleState[];
  /** Informacje bez zadania — nie liczą się do uwag ani bramki (od 13.10.2026). */
  info?: QcItem[];
  /** Pozycje oznaczone „To nieprawda” — nie liczą się, można je przywrócić (D5). */
  dismissed_items?: QcItem[];
  /** Uwaga wyciszona w „Jakość QC” (D6): widać ją, ale nie liczy się do uwag. */
  muted?: boolean;
}

export interface QcCvRun {
  t: string;
  b: boolean;
}

export interface QcCvBlock {
  kind: "h" | "p" | "li";
  section: string | null;
  runs: QcCvRun[];
  /** Poziom nagłówka (1–4); brak w wynikach sprzed 12.10.2026. */
  level?: number | null;
}

export interface QcCv {
  source: "branded_draft" | "branded_finalized" | "generated" | "document";
  editable: boolean;
  stage_id: number | null;
  generated_document_id: number | null;
  document_id: number | null;
  filename: string | null;
  /** `false` = pogrubień nie da się odczytać (CV z PDF-a). */
  bold_known: boolean;
  updated_at: string | null;
  /** Wersja szkicu CV etapu, na której policzono QC; brak dla CV bez szkicu. */
  edit_revision?: number | null;
  blocks: QcCvBlock[];
}

export interface QcOverride {
  reason: string;
  by_name: string | null;
  at: string | null;
}

/** „Potwierdzone z kandydatem” — notatka pary zapisana z okna QC. */
export interface QcConfirmation {
  text: string;
  by_name: string | null;
  at: string;
}

/** Skąd są umiejętności krytyczne: wybór Delivery Leada, podpowiedź z historii albo brak. */
export type QcCriticalSource = "dl" | "suggested" | "none";

export interface QcClientRequest {
  must: string[];
  nice: string[];
  /** Podzbiór `must` — tylko braki tych umiejętności zatrzymują wysyłkę. */
  critical?: string[];
  critical_source?: QcCriticalSource;
}

export interface QcResult {
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_name: string | null;
  passed: boolean;
  blocking_failed: number;
  warnings_count: number;
  override: QcOverride | null;
  /** QC doradza, nie blokuje (`CV_QC_ADVISORY`). */
  advisory?: boolean;
  /** Czy TA osoba może przesunąć kartę mimo uwag QC. */
  can_override?: boolean;
  confirmations?: QcConfirmation[];
  run_id: number | null;
  computed_at: string | null;
  cv: QcCv | null;
  original_cv: { source: "snapshot" | "profile_text" | null; filename: string | null; text: string | null };
  client_request: QcClientRequest;
  checks: QcCheck[];
}

export interface QcFix {
  id: string;
  check_key: string;
  requirement: string | null;
  role: string | null;
  role_index?: number | null;
  /** Etykieta stanowiska tak, jak stoi w CV (`role` = etykieta z oryginału). */
  cv_role_label?: string | null;
  current_text: string | null;
  /** `**x**` = pogrubienie — renderowane jako tekst, nigdy HTML. */
  proposed_text: string;
  source: "original" | "answers" | "notes";
  source_quote: string | null;
}

export interface QcFixesResponse {
  status: "ok" | "unavailable" | "no_cv" | "not_editable";
  cached: boolean;
  fixes: QcFix[];
}

/**
 * Jedna poprawka QC: zdanie AI, pogrubienie wymagań, usunięcie terminu albo
 * pisownia. Od 17.10.2026 (panel „Do poprawy”, PR 2) tylko w edytorze CV
 * (`qc/transform`): lata według historii, tytuł z rekrutacji (serwer bierze
 * go sam), stawka i kontakt kandydata, linia wskazana przez kontrolę AI.
 */
export type QcFixAction =
  | { action: "ai_fix"; fix_id: string; text?: string }
  | { action: "bold_all"; scope: "must" | "nice" }
  | { action: "remove_term"; term: string }
  | { action: "spelling" }
  | { action: "role_order" }
  | { action: "years" }
  | { action: "title" }
  | { action: "strip_client_rules" }
  | { action: "remove_line"; text: string };

export type QcApplyBody = QcFixAction & { expected_revision?: number };

/**
 * Poprawki liczone na treści z edytora CV (`POST …/qc/transform`) — serwer
 * niczego nie zapisuje w szkicu, edytor nakłada wynik jednym cofalnym krokiem.
 * `bulk` = „Popraw wszystko”: serwer sam pomija poprawki, które zatwierdza się
 * pojedynczo (usunięcie terminu, zdanie AI z własnym tekstem).
 */
export interface QcTransformBody {
  content_html: string;
  actions: QcFixAction[];
  bulk?: boolean;
}

export interface QcTransformApplied {
  action: string;
  fix_id?: string | null;
  /** Zakres pogrubienia (`bold_all`) i usunięty termin (`remove_term`, do 120 znaków). */
  scope?: string | null;
  term?: string | null;
  count?: number | null;
}

export interface QcTransformSkipped {
  action: string;
  code: string;
  /** Zdanie dla rekrutera — dlaczego tej poprawki nie nałożono. */
  message: string;
}

export interface QcTransformResult {
  content_html: string;
  changed: boolean;
  applied: QcTransformApplied[];
  skipped: QcTransformSkipped[];
}

/** 409 z `qc/apply`: szkic zmienił się od wczytania listy QC. */
export const CV_CHANGED_CODE = "CV_CHANGED";

export const cvQcQueryKey = (stageId: number) => ["cv-qc", stageId] as const;
export const cvQcFixesQueryKey = (stageId: number) => ["cv-qc", stageId, "fixes"] as const;

export function useCvQc(stageId: number | null, enabled = true) {
  return useQuery<QcResult>({
    queryKey: cvQcQueryKey(stageId ?? 0),
    queryFn: () => api.get<QcResult>(`/api/pipeline/stages/${stageId}/qc`).then((r) => r.data),
    enabled: stageId != null && enabled,
    // CV poprawia się też poza oknem (edytor, generator) — każde otwarcie
    // liczy QC od nowa.
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/**
 * Zrzut zgody RODO przy CV z QC (miniatura przy `consent_matches`, 27.10.2026).
 * Klucz pod `cvQcQueryKey`: „Wymień zrzut” odświeża QC, a z nim obraz.
 */
export function useQcConsentScreenshot(stageId: number) {
  return useQuery<Blob>({
    queryKey: [...cvQcQueryKey(stageId), "consent-screenshot"],
    queryFn: () =>
      api
        .get<Blob>(`/api/pipeline/stages/${stageId}/qc/consent-screenshot`, { responseType: "blob" })
        .then((r) => r.data),
    retry: false,
  });
}

/**
 * Propozycje poprawek AI — POST, bo pierwszy odczyt danej treści płaci za
 * model; serwer pamięta wynik per treść i od 14.10.2026 liczy go sam zaraz po
 * automacie CV (D5). `enabled` = są uwagi z poprawką AI — propozycje ładują się
 * bez kliknięcia (dawne „Zaproponuj poprawki (AI)”).
 */
export function useCvQcFixes(stageId: number | null, enabled: boolean) {
  return useQuery<QcFixesResponse>({
    queryKey: cvQcFixesQueryKey(stageId ?? 0),
    queryFn: () => api.post<QcFixesResponse>(`/api/pipeline/stages/${stageId}/qc/fixes`).then((r) => r.data),
    enabled: stageId != null && enabled,
    staleTime: Infinity,
  });
}

/** Po każdej zmianie QC: karta na Tablicy (oba klucze) i kolejki pulpitu. */
export function invalidateAfterQcChange(queryClient: QueryClient, jobId: number): void {
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
}

function useQcWrite<TBody>(
  stageId: number | null,
  path: string | ((body: TBody) => string),
  onChanged?: () => void,
  prepare?: (body: TBody, cached: QcResult | undefined) => unknown,
) {
  const queryClient = useQueryClient();
  const key = cvQcQueryKey(stageId ?? 0);
  return useMutation<QcResult, unknown, TBody>({
    mutationFn: (body) =>
      api
        .post<QcResult>(
          `/api/pipeline/stages/${stageId}/qc/${typeof path === "function" ? path(body) : path}`,
          prepare ? prepare(body, queryClient.getQueryData<QcResult>(key)) : body,
        )
        .then((r) => r.data),
    onSuccess: (result) => {
      queryClient.setQueryData(cvQcQueryKey(stageId ?? result.stage_id), result);
      invalidateAfterQcChange(queryClient, result.job_id);
      onChanged?.();
    },
    onError: (error) => {
      // Szkic zmienił się poza tym oknem (edytor obok) — lista jest nieaktualna.
      if (apiErrorCode(error) === CV_CHANGED_CODE) void queryClient.invalidateQueries({ queryKey: key, exact: true });
    },
  });
}

/**
 * Zastosowanie poprawki — serwer zwraca świeży wynik QC, który zastępuje cache.
 * Żądanie niesie wersję szkicu, na której policzono listę: poprawka nie
 * nadpisuje zmian z edytora otwartego obok (409 `CV_CHANGED`).
 */
export function useQcApply(stageId: number | null, onChanged?: () => void) {
  return useQcWrite<QcApplyBody>(stageId, "apply", onChanged, (body, cached) => {
    const revision = cached?.cv?.edit_revision;
    return typeof revision === "number" ? { ...body, expected_revision: revision } : body;
  });
}

/** Gotowy powód (`reason_code`) z opcjonalnym opisem; opis wymagany przy „Inny powód". */
export interface QcOverrideBody {
  reason_code: string;
  reason?: string;
  /** Blokady oznaczone „QC się myli” (D4) — klucze pozycji z bieżącego przebiegu. */
  wrong_keys?: string[];
}

/**
 * „Przepuść mimo QC" — osoba z uprawnieniem wysyłki CV do klienta, a w trybie
 * doradczym także rekruter z rekrutacji (serwer odmawia reszcie).
 */
export function useQcOverride(stageId: number | null, onChanged?: () => void) {
  return useQcWrite<QcOverrideBody>(stageId, "override", onChanged);
}

/** Pozycja „spoza oryginału” z listy QC i to, co powiedział kandydat. */
export interface QcConfirmBody {
  term: string;
  text?: string;
}

/** „Potwierdzone z kandydatem” — serwer zapisuje notatkę pary i zwraca świeży wynik QC. */
export function useQcConfirm(stageId: number | null, onChanged?: () => void) {
  return useQcWrite<QcConfirmBody>(stageId, "confirm", onChanged);
}

/** „To nieprawda”: która pozycja (klucz z wyniku QC) i dlaczego. */
export interface QcDismissBody {
  check_key: string;
  key: string;
  reason: QcDismissReason;
  note?: string;
  /** Fragment źródła — tylko „pod inną nazwą” przy treści spoza oryginału. */
  quote?: string;
}

/**
 * „To nieprawda” — serwer zapisuje pominięcie pary i zwraca świeży wynik QC.
 * Uwagę blokującą pomija tylko osoba, która może przesunąć kartę mimo uwag
 * (403 dla reszty); brak CV i reguł klienta nie da się pominąć (422).
 */
export function useQcDismiss(stageId: number | null, onChanged?: () => void) {
  return useQcWrite<QcDismissBody>(stageId, "dismiss", onChanged);
}

/** Przywrócenie pominiętej uwagi — bez ciała, świeży wynik QC w odpowiedzi. */
export function useQcRestore(stageId: number | null, onChanged?: () => void) {
  return useQcWrite<number>(stageId, (dismissalId) => `dismissals/${dismissalId}/restore`, onChanged, () => undefined);
}
