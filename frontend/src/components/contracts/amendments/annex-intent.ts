// Parametr adresu `aneks=` zakładki „Aneksy” (wariant A, 19.11.2026): przycisk
// „Dodaj aneks” w nagłówku kontraktu prowadzi na zakładkę od razu z właściwym
// oknem (`?tab=amendments&aneks=rate_change`). Zakładka zdejmuje parametr po
// otwarciu okna, żeby odświeżenie strony nie otwierało go drugi raz.
import { contractDetailTabHref } from "@/lib/contract-detail-tab";
import { B2B_EXTENSION_HINT } from "@/lib/contract-end-date";
import { permissionLabel } from "@/lib/permissions";

export const ANNEX_PARAM = "aneks";

export const ANNEX_INTENTS = [
  "rate_change",
  "scope_change",
  "extension",
  "early_termination",
  "document",
] as const;

export type AnnexIntent = (typeof ANNEX_INTENTS)[number];

/** Wartość z adresu → okno; nieznana wartość → `null` (parametr i tak znika). */
export function parseAnnexIntent(value: string | null | undefined): AnnexIntent | null {
  return (ANNEX_INTENTS as readonly string[]).includes(value ?? "") ? (value as AnnexIntent) : null;
}

/** Te same bramki co pozycje menu „Dodaj aneks”. */
export interface AnnexIntentGates {
  readOnly: boolean;
  canAmendRates: boolean;
  extensionLocked: boolean;
  /** Strona przekazała „Zakończ współpracę” (`onRequestTermination`). */
  canTerminate: boolean;
}

export type AnnexIntentAction =
  | { kind: "form"; type: "rate_change" | "scope_change" | "extension" }
  | { kind: "terminate" }
  | { kind: "document" }
  | { kind: "refused" };

export function resolveAnnexIntent(intent: AnnexIntent, gates: AnnexIntentGates): AnnexIntentAction {
  if (gates.readOnly) return { kind: "refused" };
  switch (intent) {
    case "rate_change":
      return gates.canAmendRates ? { kind: "form", type: intent } : { kind: "refused" };
    case "scope_change":
      return { kind: "form", type: intent };
    case "extension":
      return gates.extensionLocked ? { kind: "refused" } : { kind: "form", type: intent };
    case "early_termination":
      return gates.canTerminate ? { kind: "terminate" } : { kind: "refused" };
    case "document":
      return { kind: "document" };
  }
}

/**
 * Dlaczego okno z adresu się nie otworzyło — zdanie zamiast ciszy.
 * `extensionHint` to podpowiedź z menu (umowa B2B bezterminowa albo
 * wypowiedzenie do wycofania).
 */
export function annexRefusalText(
  intent: AnnexIntent,
  gates: AnnexIntentGates,
  extensionHint: string = B2B_EXTENSION_HINT,
): string {
  if (gates.readOnly) return "Kontrakt jest otwarty w trybie podglądu — aneksu nie da się tu dodać.";
  switch (intent) {
    case "rate_change":
      return `Zmiana stawki aneksem wymaga uprawnienia „${permissionLabel("amounts_edit")}” u tego klienta.`;
    case "extension":
      return extensionHint;
    case "early_termination":
      return `Zakończenie wcześniej wymaga uprawnienia „${permissionLabel("contract_status")}”.`;
    default:
      return "";
  }
}

/**
 * Adres zakładki „Aneksy” z oknem do otwarcia — dla przycisku „Dodaj aneks”
 * w nagłówku (`replaceUrl`/`pushUrl` z `useUrlWriter`). Pozostałe parametry
 * (kontekst powrotu do listy) zostają.
 */
export function annexIntentHref(pathname: string, search: string, intent: AnnexIntent): string {
  const url = new URL(contractDetailTabHref(pathname, search, "amendments"), "http://localhost");
  url.searchParams.set(ANNEX_PARAM, intent);
  return `${url.pathname}${url.search}`;
}

/** Ten sam adres bez `aneks=` — ścieżka, pozostałe parametry i kotwica zostają. */
export function hrefWithoutAnnexParam(href: string): string {
  const url = new URL(href, "http://localhost");
  url.searchParams.delete(ANNEX_PARAM);
  return `${url.pathname}${url.search}${url.hash}`;
}
