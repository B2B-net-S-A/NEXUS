/**
 * Czysty stan i reguły generatora CV v3 — bez Reacta i bez sieci.
 *
 * Jedno źródło dla przycisku „Generuj CV”, listy braków pod nim, domyślnego
 * trybu obróbki i języka oraz treści żądania. Komponenty tylko to renderują;
 * dzięki temu reguły da się sprawdzić testem na wartościach, a harness
 * `/preview/cv-generator` pokazuje dokładnie te same zdania co produkcja.
 */

import type { ChampionProfile, CvGeneratePayload } from "@/lib/api";
import type { CvAiSourceToggles } from "@/lib/cv-ai-sources";
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

/**
 * Brak dla osoby bez żadnej rekrutacji. Od 13.10.2026 CV powstaje wyłącznie
 * w rekrutacji (decyzja Artura) — „Inny klient (bez procesu)” zniknął.
 */
export const NO_RECRUITMENT_MISSING = "Rekrutacja — dodaj osobę do rekrutacji";

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
  /** Zasady klienta się wczytują / nie dało się ich odczytać. */
  policyPending: boolean;
  /** Reguła CV klienta w drodze — od niej zależą zgoda RODO, stanowisko, numer projektu. */
  rulePending?: boolean;
  policyError: boolean;
  /** Wybrany proces — `null`, dopóki rekruter go nie wskaże. */
  recruitment: RecruitmentOption | null;
  recruitmentsLoading: boolean;
  recruitmentsError: boolean;
  /** Ile rekrutacji ma osoba — bez żadnej CV nie powstanie. */
  recruitmentsCount: number;
  cvDocumentId: number | null;
  sourcesLoading: boolean;
  sourcesError: boolean;
  sourcesCount: number;
  /** Notatka dopisana w formularzu (zapisze się przed generacją). */
  noteDraft: string;
  /** Champion z pliku, który nie zapisał się w rekrutacji (tylko to CV). */
  championOverride: boolean;
  rule: CvRequirementRule | null | undefined;
  position: string;
  projectRef: string;
  /** Zrzut zgody blokuje generację (reguła klienta spoza polityki centralnej). */
  consentBlocksGeneration: boolean;
  consentToken: string | null;
  /** „Z czego powstało” wczytuje się — przełączniki jeszcze nie znają stanu wersji. */
  aiSourcesLoading?: boolean;
}

/**
 * Braki do wygenerowania CV — przycisk jest aktywny dokładnie wtedy, gdy lista
 * jest pusta. Zdania są te same, które zwróci 422 serwera.
 */
export function missingInputs(input: MissingInput): string[] {
  const items: string[] = [];
  if (input.policyPending || input.rulePending) items.push("Zasady CV klienta — wczytuję…");
  if (input.policyError) items.push("Zasady CV klienta — nie udało się ich odczytać, odśwież stronę.");

  if (input.recruitmentsLoading) items.push("Procesy kandydata — wczytuję…");
  else if (input.recruitmentsError) items.push("Procesy kandydata — nie udało się ich wczytać, odśwież stronę.");
  else if (input.recruitmentsCount === 0) {
    items.push(NO_RECRUITMENT_MISSING);
    return items;
  } else if (!input.recruitment) items.push("Proces rekrutacyjny");
  if (input.sourcesLoading) items.push("Plik CV — wczytuję…");
  else if (input.sourcesError) items.push("Pliki CV kandydata — nie udało się ich wczytać, odśwież stronę.");
  else if (input.sourcesCount === 0) items.push("Plik CV kandydata — dodaj go na profilu kandydata");
  else if (!input.cvDocumentId) items.push("Plik CV");
  const recruitment = input.recruitment;
  const withProcess = !!recruitment;
  const notesChars = (recruitment?.notes_chars ?? 0) + input.noteDraft.trim().length;
  const hasChampion = !!recruitment?.has_champion || input.championOverride;
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

  const ruleProblems = clientRuleRequirementProblems(input.rule, {
    mode: withProcess ? "new" : "old",
    notesChars,
    projectRef: input.projectRef,
    position: input.position,
    hasChampionInput: hasChampion,
  });
  for (const problem of ruleProblems) if (!items.includes(problem)) items.push(problem);
  if (input.consentBlocksGeneration && !input.consentToken) items.push("Zrzut zgody kandydata (RODO)");
  // Awaria odczytu źródeł nie blokuje: serwer bierze wtedy ustawienia domyślne.
  if (input.aiSourcesLoading) items.push("Źródła dla AI — wczytuję…");
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
  recruitment: RecruitmentOption;
  cvDocumentId: number;
  projectRef: string;
  language: CvLanguageChoice;
  blind: boolean;
  contentMode: CvProcessingMode | "basic";
  position: string;
  championProfile: ChampionProfile | null;
  consentToken: string | null;
  /** Przełączniki „Z czego powstało”; `null` = serwer bierze domyślne. */
  sources?: CvAiSourceToggles | null;
  /** „Napisz od nowa” (PR 5): uwaga rekrutera dla modelu. */
  instruction?: string;
}

/**
 * Treść `POST /api/cv-generator/generate`. Notatka z formularza zapisuje się
 * w rekrutacji przed generacją, więc w żądaniu jej nie ma.
 */
export function buildGeneratePayload(input: GeneratePayloadInput): CvGeneratePayload {
  const payload: CvGeneratePayload = {
    candidate_id: input.candidateId,
    stage_id: input.recruitment.stage_id,
    // Asercja: serwer i tak bierze klienta z rekrutacji (rozjazd = 422).
    client_id: input.recruitment.client_id ?? null,
    cv_document_id: input.cvDocumentId,
    project_ref: input.projectRef.trim(),
    ...languagePayload(input.language),
    blind_cv: input.blind,
    content_mode: input.contentMode,
  };
  if (input.position.trim()) payload.position = input.position.trim();
  if (input.championProfile) payload.champion_profile = input.championProfile;
  if (input.consentToken) payload.consent_screenshot_token = input.consentToken;
  if (input.sources) payload.sources = { ...input.sources };
  if (input.instruction?.trim()) payload.instruction = input.instruction.trim();
  return payload;
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
