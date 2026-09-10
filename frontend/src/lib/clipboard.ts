/**
 * Kopiuje tekst do schowka i MÓWI, czy się udało.
 *
 * `navigator.clipboard` bywa niedostępne (połączenie bez HTTPS, ramka bez
 * uprawnień, starsza przeglądarka) albo odrzuca zapis — np. Safari, gdy
 * między kliknięciem a zapisem minęło żądanie sieciowe i wygasła „aktywacja
 * użytkownika". Wołający, który po cichu połyka ten błąd i pokazuje toast
 * „skopiowano", kłamie dokładnie wtedy, gdy stawką jest jednorazowy sekret
 * linku — dlatego wynik jest wartością, nie domysłem.
 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      return false;
    }
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
