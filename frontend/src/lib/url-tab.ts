// Zakładka strony trzymana w `?tab=` — wspólny wzorzec wyniesiony z
// `lib/client-tab.ts` (profil klienta), żeby kolejne strony nie pisały go od
// nowa z tymi samymi pułapkami.
//
// Dwie reguły, dla których ten plik istnieje:
//  1. Efekt zależy od WARTOŚCI parametru, nie od tożsamości `searchParams` —
//     miękka nawigacja App Routera (klik w powiadomienie na tej samej stronie)
//     zmienia adres bez odmontowania komponentu, a sam inicjalizator `useState`
//     odpala się raz. Ręczny wybór innej zakładki nie jest cofany, bo parametr
//     się wtedy nie zmienia.
//  2. Wybór użytkownika trafia do adresu (`history.replaceState`), więc F5
//     i „Wstecz" wracają na tę zakładkę, a nie na domyślną.
import { useCallback, useEffect, useState } from "react";

/**
 * Zakładka z surowej wartości parametru: najpierw alias (stare linki
 * zapisane w bazie powiadomień), potem lista dozwolonych. `null` = parametr
 * nie wskazuje żadnej znanej zakładki.
 */
export function resolveUrlTab<T extends string>(
  raw: string | null | undefined,
  validTabs: readonly T[],
  aliases: Readonly<Record<string, T>> = {},
): T | null {
  if (raw == null) return null;
  const value = raw.trim();
  if (!value) return null;
  if (Object.prototype.hasOwnProperty.call(aliases, value)) return aliases[value];
  return (validTabs as readonly string[]).includes(value) ? (value as T) : null;
}

/**
 * Adres z podmienionym `?tab=`. Zakładka domyślna ZDEJMUJE parametr — czysty
 * link do rekrutacji nie ma nieść `?tab=pipeline`. Pozostałe parametry
 * zostają bez zmian.
 */
export function urlWithTab(
  href: string,
  tab: string,
  defaultTab: string,
  paramName = "tab",
): string {
  const url = new URL(href);
  if (tab === defaultTab) url.searchParams.delete(paramName);
  else url.searchParams.set(paramName, tab);
  return `${url.pathname}${url.search}${url.hash}`;
}

export interface UseUrlTabOptions<T extends string> {
  /** Surowa wartość `searchParams.get("tab")`. */
  requested: string | null | undefined;
  validTabs: readonly T[];
  defaultTab: T;
  aliases?: Readonly<Record<string, T>>;
  paramName?: string;
}

/**
 * `[aktywna zakładka, wybór użytkownika (zapisywany w adresie), zmiana stanu
 * bez dotykania adresu]`.
 */
export function useUrlTab<T extends string>({
  requested,
  validTabs,
  defaultTab,
  aliases,
  paramName = "tab",
}: UseUrlTabOptions<T>): readonly [T, (tab: T) => void, (tab: T) => void] {
  const resolved = resolveUrlTab(requested, validTabs, aliases);
  const [activeTab, setActiveTab] = useState<T>(() => resolved ?? defaultTab);

  useEffect(() => {
    if (resolved !== null) setActiveTab(resolved);
    // Zależność od WARTOŚCI — patrz reguła 1 w nagłówku pliku.
  }, [resolved]);

  const selectTab = useCallback(
    (tab: T) => {
      setActiveTab(tab);
      if (typeof window === "undefined") return;
      const next = urlWithTab(window.location.href, tab, defaultTab, paramName);
      const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      if (next !== current) {
        window.history.replaceState(window.history.state, "", next);
      }
    },
    [defaultTab, paramName],
  );

  return [activeTab, selectTab, setActiveTab] as const;
}
