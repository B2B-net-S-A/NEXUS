import type { WheelEvent } from "react";

/**
 * Kółko myszy nad AKTYWNYM polem `type="number"` zmienia w Chrome jego
 * wartość — przewinięcie strony zaraz po wpisaniu „1” w „Dni w biurze”
 * zapisywało 0 (zgłoszenie 30.09.2026). Zdjęcie fokusu zostawia wartość
 * i pozwala stronie przewinąć się normalnie.
 */
export function blurNumberInputOnWheel(event: WheelEvent<HTMLInputElement>): void {
  if (document.activeElement === event.currentTarget) event.currentTarget.blur();
}
