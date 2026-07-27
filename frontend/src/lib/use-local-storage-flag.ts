import { useCallback, useEffect, useState } from "react";

/**
 * Boolean-owa preferencja UI pamiętana w `localStorage` jako `"1"` / `"0"`.
 *
 * Dla drobnych przełączników („zwiń nagłówek", „pobieraj automatycznie"), które
 * mają przetrwać odświeżenie, ale nie są częścią sesji ani stanu serwera.
 *
 * ## Odczyt jest w `useEffect`, nie w inicjalizatorze `useState` — celowo
 *
 * Czytanie `localStorage` przy pierwszym renderze wygląda zwięźlej, ale serwer
 * renderuje bez `localStorage`, więc pierwszy render klienta może dać inną
 * wartość niż HTML z serwera — to hydration mismatch. Dlatego start jest zawsze
 * na `defaultValue`, a zapamiętana wartość dociąga się tuż po zamontowaniu.
 *
 * ## Zapis siedzi w setterze, nie w osobnym `useEffect`
 *
 * Gdyby zapis wisiał na `useEffect([value])`, odpaliłby się także przy montażu —
 * czyli nadpisałby zapamiętaną preferencję wartością domyślną, zanim efekt
 * odczytu zdążyłby ją wczytać.
 *
 * Każdy dostęp jest w `try/catch`: `localStorage` rzuca `SecurityError`, gdy
 * przeglądarka blokuje dane witryn. Preferencja UI nie jest warta wywrócenia
 * widoku, więc błąd jest połykany, a stan zostaje w pamięci.
 */
export function useLocalStorageFlag(
  key: string,
  defaultValue = false,
): [boolean, (next: boolean | ((previous: boolean) => boolean)) => void] {
  const [value, setValue] = useState(defaultValue);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw !== null) setValue(raw === "1");
    } catch {
      /* storage wyłączony — zostaw wartość domyślną */
    }
  }, [key]);

  const set = useCallback(
    (next: boolean | ((previous: boolean) => boolean)) => {
      setValue((previous) => {
        const resolved = typeof next === "function" ? next(previous) : next;
        try {
          window.localStorage.setItem(key, resolved ? "1" : "0");
        } catch {
          /* preferencja UI — nie przerywamy interakcji */
        }
        return resolved;
      });
    },
    [key],
  );

  return [value, set];
}
