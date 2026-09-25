/**
 * Czysty stan i reguły generatora CV v3 — bez Reacta i bez sieci.
 *
 * Jedno źródło dla przycisku „Generuj CV”, listy braków pod nim, domyślnego
 * trybu obróbki i języka oraz treści żądania. Komponenty tylko to renderują;
 * dzięki temu reguły da się sprawdzić testem na wartościach, a harness
 * `/preview/cv-generator` pokazuje dokładnie te same zdania co produkcja.
 */

import type { ChampionProfile, CvGeneratePayload } from "@/lib/api";
import {
  clientRuleRequirementProblems,
  stageLabel,
  type CvRequirementRule,
  type RecruitmentOption,
} from "@/lib/cv-generator";

/** Wybór języka: jedna wersja albo obie jednym kliknięciem. */
export type CvLanguageChoice = "pl" | "en" | "both";

/** Dwa kafle obróbki. „Przepisanie” (`basic`) zostaje wyłącznie sufitem klienta. */
export type CvProcessingMode = "polished" | "tailored";

/** Wartość selecta procesu dla „Inny klient (bez procesu)”. */
export const OTHER_CLIENT_CHOICE = "other";

export interface CvClientRef {
  id: number;
  name: string;
}

/** Etykieta procesu w selekcie: „Stanowisko · Klient · Etap”. */
export function processLabel(recruitment: RecruitmentOption): string {
  return [
    recruitment.job_title,
    recruitment.client_name || "bez klienta",
    stageLabel(recruitment.stage),
  ].join(" · ");
}

/**
 * Który proces zaznaczyć samemu. Rekrutacja, z której otwarto generator,
 * wygrywa; jedyny proces osoby wybieramy sami; przy kilku decyduje rekruter.
 * Osoba bez procesów ląduje od razu na „Inny klient (bez procesu)”.
 */
export function autoProcessChoice(
  recruitments: readonly RecruitmentOption[],
  prefillJobId?: number | null,
): string {
  if (prefillJobId != null) {
    const match = recruitments.find((r) => r.job_id === prefillJobId);
    if (match) return String(match.stage_id);
  }
  if (recruitments.length === 1) return String(recruitments[0].stage_id);
  if (recruitments.length === 0) return OTHER_CLIENT_CHOICE;
  return "";
}

/** Domyślna obróbka: jest Champion → „Pod rekrutację”, nie ma → „Redakcja”. */
export function defaultProcessingMode(hasChampion: boolean): CvProcessingMode {
  return hasChampion ? "tailored" : "polished";
}

export interface LanguagePolicy {
  /** Język wymuszony regułą klienta (np. Nordea — tylko EN). */
  forced: "pl" | "en" | null;
  /** Klient oczekuje wersji PL i EN. */
  requiresBoth: boolean;
}

/** Domyślny język: wymuszony → ten; klient chce obu → „Obie”; inaczej PL. */
export function defaultLanguageChoice(policy: LanguagePolicy): CvLanguageChoice {
  if (policy.forced) return policy.forced;
  return policy.requiresBoth ? "both" : "pl";
}

/** Czy dana opcja języka jest dostępna — wymuszony język blokuje resztę. */
export function languageOptionEnabled(
  option: CvLanguageChoice,
  policy: LanguagePolicy,
): boolean {
  return !policy.forced || option === policy.forced;
}

/** Pola `language` + `languages` żądania dla wybranej opcji. */
export function languagePayload(choice: CvLanguageChoice): {
  language: "pl" | "en";
  languages: "one" | "both";
} {
  return choice === "both"
    ? { language: "pl", languages: "both" }
    : { language: choice, languages: "one" };
}

export interface MissingInput {
  flow: "person" | "upload";
  /** Zasady klienta się wczytują / nie dało się ich odczytać. */
  policyPending: boolean;
  policyError: boolean;
  // — ścieżka „osoba z bazy”
  candidateId: number | null;
  processChoice: string;
  recruitment: RecruitmentOption | null;
  recruitmentsLoading: boolean;
  otherClient: CvClientRef | null;
  cvDocumentId: number | null;
  sourcesLoading: boolean;
  sourcesCount: number;
  /** Notatka dopisana w formularzu (zapisze się przed generacją). */
  noteDraft: string;
  /** Champion z pliku, który nie zapisał się w rekrutacji (tylko to CV). */
  championOverride: boolean;
  // — ścieżka „plik z dysku, bez dodawania”
  uploadFile: File | null;
  /** Plik jest, ale rekruter nie zdecydował: dodać do bazy czy bez dodawania. */
  uploadDecisionPending: boolean;
  uploadClient: CvClientRef | null;
  uploadChampion: boolean;
  uploadNotes: string;
  // — wspólne
  rule: CvRequirementRule | null | undefined;
  position: string;
  projectRef: string;
  /** Zrzut zgody blokuje generację (reguła klienta spoza polityki centralnej). */
  consentBlocksGeneration: boolean;
  consentToken: string | null;
}

/**
 * Braki do wygenerowania CV — przycisk jest aktywny dokładnie wtedy, gdy lista
 * jest pusta. Zdania są te same, które zwróci 422 serwera.
 */
export function missingInputs(input: MissingInput): string[] {
  const items: string[] = [];
  if (input.policyPending) items.push("Zasady CV klienta — wczytuję…");
  if (input.policyError) items.push("Zasady CV klienta — nie udało się ich odczytać, odśwież stronę.");

  let notesChars = 0;
  let hasChampion = false;
  let withProcess = false;
  if (input.flow === "person") {
    if (!input.candidateId) {
      items.push("Kandydat");
      return items;
    }
    if (input.recruitmentsLoading) items.push("Procesy kandydata — wczytuję…");
    else if (!input.processChoice) items.push("Proces albo klient");
    else if (input.processChoice === OTHER_CLIENT_CHOICE && !input.otherClient) items.push("Klient");
    if (input.sourcesLoading) items.push("Plik CV — wczytuję…");
    else if (input.sourcesCount === 0) items.push("Plik CV kandydata — dodaj go na profilu kandydata");
    else if (!input.cvDocumentId) items.push("Plik CV");
    withProcess = !!input.recruitment;
    notesChars = (input.recruitment?.notes_chars ?? 0) + input.noteDraft.trim().length;
    hasChampion = !!input.recruitment?.has_champion || input.championOverride;
    const recruitment = input.recruitment;
    if (recruitment) {
      const minNotes = recruitment.required_notes_min_chars ?? 0;
      const localFix = !!input.noteDraft.trim() || input.championOverride;
      if (recruitment.required_champion && !hasChampion) {
        items.push("Profil Championa — ten klient go wymaga");
      }
      if (minNotes > 0 && notesChars < minNotes) {
        items.push(`Notatki ze screeningu — co najmniej ${minNotes} znaków (jest ${notesChars})`);
      }
      if (!recruitment.ready && !localFix && !recruitment.required_champion && minNotes === 0) {
        items.push(...(recruitment.missing_inputs ?? []).filter((problem) => !/\bCV\b.*(PDF|DOCX|plik)/i.test(problem)));
      }
    }
  } else {
    if (!input.uploadFile) items.push("Plik CV");
    else if (input.uploadDecisionPending) items.push("Decyzja: dodać osobę do bazy czy generować bez dodawania");
    else if (!input.uploadClient) items.push("Klient");
    notesChars = input.uploadNotes.trim().length;
    hasChampion = input.uploadChampion;
  }

  const ruleProblems = clientRuleRequirementProblems(input.rule, {
    mode: withProcess ? "new" : "old",
    notesChars,
    projectRef: input.projectRef,
    position: input.position,
    hasChampionInput: hasChampion,
  });
  for (const problem of ruleProblems) if (!items.includes(problem)) items.push(problem);
  if (input.consentBlocksGeneration && !input.consentToken) items.push("Zrzut zgody kandydata (RODO)");
  return items;
}

export interface AdvancedAttention {
  positionRequired: boolean;
  position: string;
  projectRefRequired: boolean;
  projectRef: string;
}

/** „Zaawansowane” rozwijają się same, gdy wymagane pole w środku jest puste. */
export function advancedNeedsAttention(input: AdvancedAttention): boolean {
  return (
    (input.positionRequired && !input.position.trim()) ||
    (input.projectRefRequired && !input.projectRef.trim())
  );
}

export interface GeneratePayloadInput {
  candidateId: number;
  recruitment: RecruitmentOption | null;
  otherClient: CvClientRef | null;
  cvDocumentId: number;
  projectRef: string;
  language: CvLanguageChoice;
  blind: boolean;
  contentMode: CvProcessingMode | "basic";
  position: string;
  championProfile: ChampionProfile | null;
  consentToken: string | null;
  /** Notatki z formularza — wysyłane tylko bez procesu. */
  notes?: string;
}

/** Treść `POST /api/cv-generator/generate`. Bez procesu klient jest jawny. */
export function buildGeneratePayload(input: GeneratePayloadInput): CvGeneratePayload {
  const payload: CvGeneratePayload = {
    candidate_id: input.candidateId,
    stage_id: input.recruitment?.stage_id ?? null,
    // Przy procesie to asercja (serwer i tak bierze klienta z rekrutacji,
    // rozjazd = 422); bez procesu — jedyne źródło klienta.
    client_id: input.recruitment
      ? (input.recruitment.client_id ?? null)
      : (input.otherClient?.id ?? null),
    cv_document_id: input.cvDocumentId,
    project_ref: input.projectRef.trim(),
    ...languagePayload(input.language),
    blind_cv: input.blind,
    content_mode: input.contentMode,
  };
  if (input.position.trim()) payload.position = input.position.trim();
  if (input.championProfile) payload.champion_profile = input.championProfile;
  if (input.consentToken) payload.consent_screenshot_token = input.consentToken;
  // Bez procesu notatka nie może stać się trwałą notatką kandydata bez
  // rekrutacji — trafiałaby do CV pod każdego kolejnego klienta.
  if (!input.recruitment && input.notes?.trim()) payload.screening_notes = input.notes.trim();
  return payload;
}

export interface UploadPayloadInput {
  file: File;
  client: CvClientRef;
  projectRef: string;
  language: CvLanguageChoice;
  blind: boolean;
  contentMode: CvProcessingMode | "basic";
  position: string;
  notes: string;
  championFile: File | null;
  championProfile: ChampionProfile | null;
  consentToken: string | null;
}

/** Treść multipart `POST /api/cv-generator/generate-upload` (osoba spoza bazy). */
export function buildUploadFormData(input: UploadPayloadInput): FormData {
  const fd = new FormData();
  fd.append("cv_file", input.file);
  fd.append("client_id", String(input.client.id));
  if (input.position.trim()) fd.append("position", input.position.trim());
  if (input.projectRef.trim()) fd.append("project_ref", input.projectRef.trim());
  const { language, languages } = languagePayload(input.language);
  fd.append("language", language);
  fd.append("languages", languages);
  fd.append("blind_cv", String(input.blind));
  fd.append("content_mode", input.contentMode);
  if (input.notes.trim()) fd.append("screening_notes", input.notes);
  if (input.championFile) fd.append("champion_file", input.championFile);
  // Poprawiony w podglądzie profil jedzie tylko razem z plikiem, z którego
  // powstał — bez pliku generacja czyta dokument sama, deterministycznie.
  if (input.championFile && input.championProfile) {
    fd.append("champion_profile_json", JSON.stringify(input.championProfile));
  }
  if (input.consentToken) fd.append("consent_screenshot_token", input.consentToken);
  return fd;
}

// Sekcje i klucze, których import z dokumentu NIE przysyła: notatki zespołu
// (sekcja 8 — brak klucza = sekcja nietknięta), blok maszynowy historii
// klienta i weryfikacja, które stempluje serwer.
const IMPORT_SKIPPED_KEYS = new Set(["insights", "client_history", "verification"]);

function withoutEmpty(value: unknown): unknown {
  if (value === null || value === undefined) return undefined;
  if (typeof value === "string") return value.trim() ? value : undefined;
  if (Array.isArray(value)) return value.length ? value : undefined;
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      const kept = withoutEmpty(item);
      if (kept !== undefined) out[key] = kept;
    }
    return Object.keys(out).length ? out : undefined;
  }
  return value;
}

/**
 * Ładunek `apply-import` z generatora CV: tylko pola, które dokument
 * NAPRAWDĘ niesie. Generator nie zna zapisanego profilu (brak `current`),
 * więc pełny profil z dokumentu nadpisywał zapisane pola pustymi wartościami,
 * a pusta lista `insights` kasowała notatki zespołu (audyt 25.09.2026, r3).
 */
export function championImportPayload(profile: ChampionProfile): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(profile as unknown as Record<string, unknown>)) {
    if (IMPORT_SKIPPED_KEYS.has(key)) continue;
    const kept = withoutEmpty(value);
    if (kept !== undefined) out[key] = kept;
  }
  return out;
}

/** Nazwa pliku do pobrania HTML (ta sama nazwa co DOCX). */
export function htmlFilename(docxFilename: string): string {
  return docxFilename.replace(/\.docx$/i, "") + ".html";
}

/** Data na liście „Moje CV”: „dziś 12:40”, „wczoraj 16:02”, „19.09”. */
export function formatCvListDate(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  const startOf = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(date)) / 86_400_000);
  if (days === 0) return `dziś ${time}`;
  if (days === 1) return `wczoraj ${time}`;
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  return date.getFullYear() === now.getFullYear() ? `${dd}.${mm}` : `${dd}.${mm}.${date.getFullYear()}`;
}
