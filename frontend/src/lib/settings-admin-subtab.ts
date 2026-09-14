// Podzakładka Ustawienia → Administracja wybierana adresem (`?sub=`) — B42.
//
// Główna zakładka jest w `?tab=` (`settings-tab.ts`), ale podzakładka
// (Użytkownicy / Uprawnienia / System / …) żyła w `useState("users")`:
// F5 na „Uprawnieniach" wracało do „Użytkowników". Ten sam wzorzec co
// `useSettingsTab`: efekt zależy od WARTOŚCI parametru (miękka nawigacja),
// a wybór użytkownika trafia do adresu przez History API.
import { useCallback, useEffect, useState } from "react";

export type AdminSubTab =
  | "users"
  | "permissions"
  | "system"
  | "audit"
  | "import"
  | "tools";

export const ADMIN_SUBTAB_KEYS: readonly AdminSubTab[] = [
  "users",
  "permissions",
  "system",
  "audit",
  "import",
  "tools",
] as const;

export const DEFAULT_ADMIN_SUBTAB: AdminSubTab = "users";

/** Nazwa parametru w adresie: `/settings?tab=administracja&sub=permissions`. */
export const ADMIN_SUBTAB_PARAM = "sub";

export function isAdminSubTab(value: string | null): value is AdminSubTab {
  return (
    value !== null && (ADMIN_SUBTAB_KEYS as readonly string[]).includes(value)
  );
}

/** Zapisz podzakładkę w adresie bez nawigacji; domyślna nie zostawia `?sub=`. */
export function writeAdminSubTabToUrl(sub: AdminSubTab): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  if (sub === DEFAULT_ADMIN_SUBTAB) params.delete(ADMIN_SUBTAB_PARAM);
  else params.set(ADMIN_SUBTAB_PARAM, sub);
  const query = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
  );
}

export function useAdminSubTab(
  requestedSub: string | null,
  onSelectSub: (sub: AdminSubTab) => void = writeAdminSubTabToUrl,
): readonly [AdminSubTab, (sub: AdminSubTab) => void] {
  const [subTab, setSubTab] = useState<AdminSubTab>(() =>
    isAdminSubTab(requestedSub) ? requestedSub : DEFAULT_ADMIN_SUBTAB,
  );
  // Brak parametru to też wartość — link `/settings?tab=administracja`
  // kliknięty na „Uprawnieniach" ma wrócić do „Użytkowników".
  useEffect(() => {
    setSubTab(isAdminSubTab(requestedSub) ? requestedSub : DEFAULT_ADMIN_SUBTAB);
  }, [requestedSub]);
  const selectSub = useCallback(
    (sub: AdminSubTab) => {
      setSubTab(sub);
      onSelectSub(sub);
    },
    [onSelectSub],
  );
  return [subTab, selectSub] as const;
}
