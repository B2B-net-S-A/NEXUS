/**
 * Zapis Profilu Championa z edytora (audyt 06.10.2026, N1/N2/N4/N5).
 *
 * Serwer scala `PUT …/champion-profile` z zapisanym profilem o jeden poziom
 * w głąb, więc edytor wysyła WYŁĄCZNIE sekcje najwyższego poziomu, które
 * Delivery Lead zmienił względem profilu, od którego zaczynał. Do tej daty
 * jechał cały szkic: zapis nadpisywał sekcje zmienione w międzyczasie przez
 * kogoś innego, a pełna lista notatek kasowała cudze notatki. Do zapisu
 * dochodzi `expected_profile_hash` — odcisk profilu wczytanego z serwera;
 * profil zmieniony od tego czasu = 409 `champion_profile_conflict`.
 *
 * Czyste funkcje — bez Reacta i sieci.
 */

import type { ChampionProfile, ChampionProfileResponse } from "@/lib/api";
import { championSavePayload, type ChampionSaveSeed } from "@/lib/champion-job-seed";
import { CHAMPION_SECTIONS, type ChampionSectionId } from "@/lib/champion-section-state";

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** Klucze najwyższego poziomu, którymi szkic różni się od profilu wyjściowego. */
export function changedSectionKeys(
  draft: ChampionProfile,
  baseline: ChampionProfile,
): string[] {
  const keys = new Set([...Object.keys(draft), ...Object.keys(baseline)]);
  return [...keys].filter(
    (key) =>
      !same(
        (draft as unknown as Record<string, unknown>)[key],
        (baseline as unknown as Record<string, unknown>)[key],
      ),
  );
}

/**
 * Ładunek `PUT …/champion-profile`: tylko zmienione sekcje (w kształcie
 * `championSavePayload` — bez nietkniętych pól wczytanych z rekrutacji),
 * `stack` w całości (wiersze i krytyczne razem), notatki tylko przy ich
 * zmianie, plus odcisk profilu, od którego zaczęła się edycja.
 */
export function championChangedPayload(
  draft: ChampionProfile,
  baseline: ChampionProfile,
  seed: ChampionSaveSeed,
  expectedProfileHash: string | null,
): Record<string, unknown> {
  const full = championSavePayload(draft, seed) as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of changedSectionKeys(draft, baseline)) {
    if (key in full) out[key] = full[key];
  }
  if (expectedProfileHash) out.expected_profile_hash = expectedProfileHash;
  return out;
}

/** Profil z serwera po konflikcie: kontekst jak w `GET` i zdanie dla DL-a. */
export interface ChampionConflict extends ChampionProfileResponse {
  message: string | null;
}

/** 409 `champion_profile_conflict` z błędu axios albo `null`, gdy to inny błąd. */
export function championConflictFrom(error: unknown): ChampionConflict | null {
  const response = (error as { response?: { status?: unknown; data?: unknown } } | null)
    ?.response;
  if (response?.status !== 409) return null;
  const detail = (response.data as { detail?: unknown } | undefined)?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const raw = detail as Record<string, unknown>;
  if (raw.code !== "champion_profile_conflict") return null;
  const profile = raw.champion_profile;
  return {
    ...(raw as unknown as ChampionProfileResponse),
    champion_profile:
      profile && typeof profile === "object" ? (profile as ChampionProfile) : {},
    message: typeof raw.message === "string" && raw.message.trim() ? raw.message.trim() : null,
  };
}

/**
 * Kod braku bramki (`__fixtures__/job-readiness-blockers.json`) → sekcja
 * Profilu Championa, w której się go usuwa. Braki spoza profilu (hiring
 * manager, termin, kategoria, liczba osób) nie mają sekcji.
 */
const BLOCKER_SECTION: Record<string, ChampionSectionId> = {
  context: "project",
  questions: "screening_questions",
  deal_breaker: "screening_questions",
  must: "stack",
  critical: "stack",
  search: "search",
  budget: "basics",
  work_mode: "basics",
  office_days: "basics",
  office_city: "basics",
};

/** Sekcja (etykieta i kotwica) dla kodu braku; `champion:<kod>` i obce — `null`. */
export function blockerSection(
  code: string,
): { label: string; anchor: string } | null {
  const id = BLOCKER_SECTION[code];
  if (!id) return null;
  const meta = CHAMPION_SECTIONS.find((section) => section.id === id);
  return meta ? { label: meta.label, anchor: meta.anchor } : null;
}
