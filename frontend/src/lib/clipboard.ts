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

/**
 * Kopiuje treść w dwóch postaciach naraz: HTML (edytor z formatowaniem wklei
 * nagłówki i listy) i zwykły tekst (pole bez formatowania wklei wiersze).
 *
 * Przeglądarka bez `ClipboardItem` albo odmawiająca zapisu HTML dostaje sam
 * tekst — wynik dalej mówi prawdę o tym, czy COKOLWIEK trafiło do schowka.
 */
export async function copyHtmlToClipboard(html: string, text: string): Promise<boolean> {
  try {
    if (
      html &&
      typeof navigator !== "undefined" &&
      typeof navigator.clipboard?.write === "function" &&
      typeof ClipboardItem !== "undefined"
    ) {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        }),
      ]);
      return true;
    }
  } catch {
    // Zapas niżej: sam tekst.
  }
  return copyTextToClipboard(text);
}
