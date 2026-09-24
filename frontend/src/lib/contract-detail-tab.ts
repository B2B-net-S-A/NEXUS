// Zakładka szczegółów kontraktu wybierana adresem (`/contracts/{id}?tab=`).
//
// Audyt 24.09.2026 (S9): zakładka żyła wyłącznie w `useState`, więc linki
// z backendu prowadziły zawsze na „Szczegóły” — wzmianka w notatce
// (`mention_dispatch.py`: `?tab=notes&note=`), alert dokumentu
// (`?tab=documents`) i zwrotu sprzętu (`?tab=equipment`). Lustro wzorca
// `lib/client-tab.ts`.
import { useCallback, useEffect, useState } from "react";

export type ContractDetailTab =
  | "details"
  | "documents"
  | "amendments"
  | "onboarding"
  | "equipment"
  | "notes"
  | "invoices"
  | "rateHistory"
  | "timeline";

export const CONTRACT_DETAIL_TAB_KEYS: readonly ContractDetailTab[] = [
  "details",
  "documents",
  "amendments",
  "onboarding",
  "equipment",
  "notes",
  "invoices",
  "rateHistory",
  "timeline",
] as const;

export function isContractDetailTab(
  value: string | null | undefined,
): value is ContractDetailTab {
  return (
    value != null &&
    (CONTRACT_DETAIL_TAB_KEYS as readonly string[]).includes(value)
  );
}

/**
 * Adres z wybraną zakładką — pozostałe parametry (np. kontekst powrotu do
 * listy) zostają. „Szczegóły” to zakładka domyślna, więc zdejmuje parametr.
 */
export function contractDetailTabHref(
  pathname: string,
  search: string,
  tab: ContractDetailTab,
): string {
  const params = new URLSearchParams(search);
  if (tab === "details") params.delete("tab");
  else params.set("tab", tab);
  // `note=` dotyczy wyłącznie zakładki notatek.
  if (tab !== "notes") params.delete("note");
  const qs = params.toString();
  return qs ? `${pathname}?${qs}` : pathname;
}

/**
 * Zakładka sterowana adresem, ale nadal przełączalna ręcznie. Efekt zależy od
 * WARTOŚCI parametru (miękka nawigacja App Routera nie odmontowuje strony,
 * więc sam inicjalizator `useState` nie wystarcza).
 */
export function useContractDetailTab(
  requestedTab: string | null,
  onSelectTab?: (tab: ContractDetailTab) => void,
): readonly [ContractDetailTab, (tab: ContractDetailTab) => void] {
  const [activeTab, setActiveTab] = useState<ContractDetailTab>(() =>
    isContractDetailTab(requestedTab) ? requestedTab : "details",
  );
  useEffect(() => {
    setActiveTab(isContractDetailTab(requestedTab) ? requestedTab : "details");
  }, [requestedTab]);
  const selectTab = useCallback(
    (tab: ContractDetailTab) => {
      setActiveTab(tab);
      if (tab !== requestedTab) onSelectTab?.(tab);
    },
    [onSelectTab, requestedTab],
  );
  return [activeTab, selectTab] as const;
}
