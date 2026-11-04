// W odróżnieniu od `useDebouncedValue` (`./use-debounced-value`, porównuje
// referencje) ten hook porównuje wartość po treści (JSON), więc znosi obiekt
// budowany na nowo w każdym renderze.

import { useEffect, useState } from "react";

/** Opóźnia wartość, żeby podgląd nie pytał serwera przy każdej literze. */
/**
 * Wartość po `delayMs` bez zmian. Porównanie po treści (JSON), nie po
 * referencji: okno buduje `{start, end}` i dane wniosku na nowo w każdym
 * renderze, a porównanie referencji zapętlało rendery i nie dawało podglądowi
 * dogonić formularza („Wyślij do akceptacji” zostawał zablokowany).
 */
export function useDebounced<T>(value: T, delayMs: number): T {
  const key = JSON.stringify(value);
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(
      () => setDebounced(key === undefined ? (undefined as T) : (JSON.parse(key) as T)),
      delayMs,
    );
    return () => clearTimeout(timer);
  }, [key, delayMs]);
  return debounced;
}
