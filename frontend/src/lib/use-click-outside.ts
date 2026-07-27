import { useEffect, useRef, type RefObject } from "react";

/**
 * Zamknij coś, gdy użytkownik kliknie POZA wskazanym elementem.
 *
 * Nasłuchuje `mousedown` (nie `click`) na `document` — tak jak wszystkie ręczne
 * implementacje, które ten hook zastąpił. Różnica jest istotna: `mousedown`
 * zamyka dropdown w chwili wciśnięcia przycisku, zanim element pod kursorem
 * zdąży się przesunąć, więc kliknięcie „obok" nie gubi się na re-layoucie.
 *
 * @param ref        element uznawany za „wnętrze" — klik w niego NIE zamyka.
 * @param onOutside  wołane przy kliknięciu poza `ref`.
 * @param enabled    czy nasłuchiwać. **Przekaż tu stan otwarcia**, jeśli element
 *                   montuje się dopiero po otwarciu — patrz uwaga niżej.
 *
 * ## Dlaczego `enabled` bywa obowiązkowe, a nie kosmetyczne
 *
 * Gdy przycisk otwierający leży POZA `ref` (menu renderowane warunkowo obok
 * triggera), listener podpięty na stałe złapie to samo `mousedown`, które menu
 * otwiera, i zamknie je w tym samym geście — menu „nie da się otworzyć".
 * Przekazanie `open` jako `enabled` podpina listener dopiero po otwarciu i
 * problem znika.
 *
 * ## Bez stale closure
 *
 * `onOutside` trzymany jest w ref aktualizowanym po każdym renderze, więc
 * callback zawsze widzi świeży stan, a listener NIE jest przepinany przy każdym
 * renderze (co przy inline'owej strzałce działoby się bez przerwy).
 */
export function useClickOutside<T extends HTMLElement>(
  ref: RefObject<T | null>,
  onOutside: () => void,
  enabled = true,
): void {
  const handlerRef = useRef(onOutside);

  useEffect(() => {
    handlerRef.current = onOutside;
  });

  useEffect(() => {
    if (!enabled) return;
    const onMouseDown = (event: MouseEvent) => {
      const element = ref.current;
      if (element && !element.contains(event.target as Node)) {
        handlerRef.current();
      }
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [ref, enabled]);
}
