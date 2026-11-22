// Zakładka szczegółów kontraktu wybierana adresem (`/contracts/{id}?tab=`).
//
// Audyt 24.09.2026 (S9): zakładka żyła wyłącznie w `useState`, więc linki
// z backendu prowadziły zawsze na „Szczegóły” — wzmianka w notatce
// (`mention_dispatch.py`: `?tab=notes&note=`), alert dokumentu
// (`?tab=documents`) i zwrotu sprzętu (`?tab=equipment`). Lustro wzorca
// `lib/client-tab.ts`.
//
// Przebudowa 19.11.2026 (wariant A, decyzja Artura po makietach): 10 zakładek
// → 7. Stare klucze zostają jako aliasy, bo niosą je linki zapisane w bazie
// (powiadomienia, wzmianki, alerty) i inne ekrany NEXUSA.
import { useCallback, useEffect, useState } from "react";

export type ContractDetailTab =
  | "overview"
  | "money"
  | "documents"
  | "amendments"
  // Opieka nad konsultantem (karta opieki) + notatki i rozmowy; cel dzwonka
  // `care_contact_due` (`/contracts/{id}?tab=care`) i wzmianki (`?tab=notes&note=`).
  | "care"
  // Start u klienta: lista wejścia, panel konsultanta, sprzęt.
  | "start"
  | "history";

/** Klucze sprzed 19.11.2026 — nadal poprawne w adresie. */
export type LegacyContractDetailTab =
  | "details"
  | "rateHistory"
  | "invoices"
  | "notes"
  | "onboarding"
  | "equipment"
  | "timeline";

export const CONTRACT_DETAIL_TAB_KEYS: readonly ContractDetailTab[] = [
  "overview",
  "money",
  "documents",
  "amendments",
  "care",
  "start",
  "history",
] as const;

export const LEGACY_CONTRACT_DETAIL_TABS: Readonly<Record<LegacyContractDetailTab, ContractDetailTab>> = {
  details: "overview",
  rateHistory: "money",
  invoices: "money",
  notes: "care",
  onboarding: "start",
  equipment: "start",
  timeline: "history",
};

/** Klucz z adresu (nowy albo dawny) → zakładka; nieznany → `null`. */
export function resolveContractDetailTab(value: string | null | undefined): ContractDetailTab | null {
  if (value == null) return null;
  if ((CONTRACT_DETAIL_TAB_KEYS as readonly string[]).includes(value)) return value as ContractDetailTab;
  return LEGACY_CONTRACT_DETAIL_TABS[value as LegacyContractDetailTab] ?? null;
}

/** Czy wartość z adresu to znana zakładka (nowy albo dawny klucz). */
export function isContractDetailTab(
  value: string | null | undefined,
): value is ContractDetailTab | LegacyContractDetailTab {
  return resolveContractDetailTab(value) != null;
}

/**
 * Adres z wybraną zakładką — pozostałe parametry (np. kontekst powrotu do
 * listy) zostają. „Przegląd” to zakładka domyślna, więc zdejmuje parametr.
 * Przyjmuje też dawne klucze (linki z innych ekranów), zapisując je bez zmian.
 */
export function contractDetailTabHref(
  pathname: string,
  search: string,
  tab: ContractDetailTab | LegacyContractDetailTab,
): string {
  const params = new URLSearchParams(search);
  const target = resolveContractDetailTab(tab);
  if (target === "overview") params.delete("tab");
  else params.set("tab", tab);
  // `note=` dotyczy wyłącznie notatek (dziś w zakładce „Opieka i rozmowy”).
  if (target !== "care") params.delete("note");
  const qs = params.toString();
  return qs ? `${pathname}?${qs}` : pathname;
}

/**
 * Zakładka sterowana adresem, ale nadal przełączalna ręcznie. Efekt zależy od
 * WARTOŚCI parametru (miękka nawigacja App Routera nie odmontowuje strony,
 * więc sam inicjalizator `useState` nie wystarcza). Dawne klucze trafiają
 * na swoje nowe zakładki.
 */
export function useContractDetailTab(
  requestedTab: string | null,
  onSelectTab?: (tab: ContractDetailTab) => void,
): readonly [ContractDetailTab, (tab: ContractDetailTab) => void] {
  const [activeTab, setActiveTab] = useState<ContractDetailTab>(
    () => resolveContractDetailTab(requestedTab) ?? "overview",
  );
  useEffect(() => {
    setActiveTab(resolveContractDetailTab(requestedTab) ?? "overview");
  }, [requestedTab]);
  const selectTab = useCallback(
    (tab: ContractDetailTab) => {
      setActiveTab(tab);
      if (tab !== resolveContractDetailTab(requestedTab)) onSelectTab?.(tab);
    },
    [onSelectTab, requestedTab],
  );
  return [activeTab, selectTab] as const;
}
