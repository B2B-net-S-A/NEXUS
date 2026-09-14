/**
 * Przypięcie kotwicy na czas doczytywania treści nad nią.
 *
 * Powód (reaudyt 14.09.2026, R03): sekcje Insights montują się leniwie
 * (`DeferUntilVisible`), a potem dociągają dane. Kliknięcie „Źródła” ustawiało
 * poprawną pozycję na chwilę — sekcje NAD celem zamieniały placeholdery na
 * wyższą treść i cel odjeżdżał 3180 px w dół. Kotwica HTML nie koryguje
 * pozycji po zmianie układu, więc robimy to tutaj: przez krótki czas
 * sprawdzamy, czy cel się przesunął, i przewijamy do niego ponownie.
 *
 * Przypięcie ustępuje człowiekowi: pierwsze kółko myszy, dotyk, klawisz albo
 * kliknięcie kończy je natychmiast. Aktywne jest co najwyżej jedno przypięcie
 * naraz — kolejna kotwica zastępuje poprzednią.
 */

/** Jak długo pilnujemy celu. Pokrywa doczytanie danych przez sekcje nad nim. */
export const ANCHOR_PIN_MAX_MS = 12_000;
/** Co ile sprawdzamy położenie celu. */
export const ANCHOR_PIN_CHECK_MS = 200;
/** Przesunięcie, poniżej którego nie ruszamy widoku (zaokrąglenia układu). */
export const ANCHOR_PIN_DRIFT_PX = 4;

const USER_INPUT_EVENTS = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

let stopActivePin: (() => void) | null = null;

export function pinAnchor(id: string): () => void {
  stopActivePin?.();
  if (typeof document === "undefined") return () => {};
  const target = document.getElementById(id);
  if (!target) return () => {};

  const scrollToTarget = () => {
    target.scrollIntoView({ block: "start" });
    return target.getBoundingClientRect().top;
  };

  let settledTop = scrollToTarget();
  const startedAt = Date.now();

  const stop = () => {
    window.clearInterval(timer);
    for (const name of USER_INPUT_EVENTS) {
      window.removeEventListener(name, stop, true);
    }
    if (stopActivePin === stop) stopActivePin = null;
  };

  const timer = window.setInterval(() => {
    if (!target.isConnected || Date.now() - startedAt >= ANCHOR_PIN_MAX_MS) {
      stop();
      return;
    }
    const top = target.getBoundingClientRect().top;
    if (Math.abs(top - settledTop) > ANCHOR_PIN_DRIFT_PX) {
      settledTop = scrollToTarget();
    }
  }, ANCHOR_PIN_CHECK_MS);

  for (const name of USER_INPUT_EVENTS) {
    window.addEventListener(name, stop, { capture: true, passive: true });
  }
  stopActivePin = stop;
  return stop;
}
