/**
 * Ostrzeżenia dopuszczalności na karcie i w wierszu Tablicy (12.10.2026).
 *
 * Tablica dostaje z serwera kody ostrzeżeń pary (`warnings`: konflikt
 * z klientem, czarna lista…), ale do tej zmiany rysowała tylko dwa z nich —
 * weto hiring managera i „ponad budżet”. Reszta była widoczna dopiero przy
 * próbie ruchu karty.
 *
 * Jedna mapa po kodzie `EligibilityReason` z backendu
 * (`services/candidate_job_eligibility.py`): krótka etykieta na odznakę,
 * pełne zdanie do dymka. Mapy w `bulk-result-summary.ts` i `assign-error.ts`
 * mają inne klucze albo same pełne zdania.
 */
import type { EmploymentMarker } from "@/lib/employment-marker";

/** Kody, które karta i wiersz rysują własnymi odznakami. */
const DRAWN_ELSEWHERE: ReadonlySet<string> = new Set(["hm_veto", "budget_exceeded"]);

const SHORT_LABEL: Record<string, string> = {
  blacklisted: "czarna lista",
  client_blacklist: "czarna lista klienta",
  client_nda: "NDA z klientem",
  client_competitor: "konkurent klienta",
  client_current_employment: "pracuje u tego klienta",
  client_excluded_by_candidate: "wykluczył klienta",
};

/** Lustro `_REASON_LABELS_PL` — pełne zdanie do dymka. */
const FULL_LABEL: Record<string, string> = {
  blacklisted: "Kandydat na globalnej czarnej liście",
  client_blacklist: "Konflikt: klient ma kandydata na czarnej liście",
  client_nda: "Konflikt: NDA z klientem",
  client_competitor: "Konflikt: klient konkurencyjny",
  client_current_employment: "Kandydat obecnie pracuje u tego klienta",
  client_excluded_by_candidate: "Kandydat wykluczył tego klienta",
};

export interface EligibilityWarningBadge {
  code: string;
  label: string;
  title: string;
  tone: "warning" | "danger";
}

/**
 * Odznaki ostrzeżeń pary, których nic innego na karcie nie mówi.
 * „Pracuje u tego klienta” pomijamy, gdy mówi to już znacznik zatrudnienia.
 */
export function eligibilityWarningBadges(
  warnings: readonly string[] | null | undefined,
  marker?: EmploymentMarker | null,
): EligibilityWarningBadge[] {
  const out: EligibilityWarningBadge[] = [];
  for (const code of warnings ?? []) {
    if (DRAWN_ELSEWHERE.has(code)) continue;
    if (code === "client_current_employment" && marker?.elsewhere === false) continue;
    const blocked = code === "blacklisted";
    const full = FULL_LABEL[code] ?? `Ostrzeżenie: ${code}`;
    out.push({
      code,
      label: SHORT_LABEL[code] ?? "ostrzeżenie",
      title: blocked ? full : `${full}. Ostrzeżenie — ruch jest możliwy po potwierdzeniu.`,
      tone: blocked ? "danger" : "warning",
    });
  }
  return out;
}
