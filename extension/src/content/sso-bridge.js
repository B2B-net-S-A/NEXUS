// Most SSO: strona NEXUS-a -> wtyczka.
//
// Wtyczka miala JEDYNA sciezke logowania - email + haslo - a produkcja
// odrzuca ja od 19 lipca ("Logowanie haslem jest wylaczone. Zaloguj sie przez
// Microsoft"). Rekruter, ktory zainstalowal wtyczke, wyczyscil profil Chrome
// albo dostal zmiane roli (co bumpuje `authorization_version` i uniewaznia
// refresh token), NIE MIAL jak sie zalogowac. Jedyna sciezka "jednym
// klknieciem z LinkedIna do bazy" byla dla nowego uzytkownika martwa.
//
// Backend ma komplet SSO od dawna (/authorize -> Microsoft -> /callback ->
// /exchange). Brakowalo wylacznie sposobu, zeby wtyczka odebrala wynik.
//
// Dlaczego `window.postMessage`, a nie `externally_connectable`: tamto wymaga,
// zeby STRONA znala ID wtyczki, a ten manifest nie ma pola `key`, wiec ID jest
// niestabilne miedzy instalacjami. Most dziala bez znajomosci ID.
//
// Trzy warunki, ktore musza byc spelnione LACZNIE, zeby cokolwiek przyjac:
//   * `event.source === window` - wiadomosc z TEJ karty, nie z ramki,
//   * `event.origin === location.origin` - z tego samego pochodzenia,
//   * `data.source === "nexus-app"` - z naszego kodu, nie z przypadkowego
//     skryptu na stronie.
// Content script chodzi WYLACZNIE na sciezce callbacku SSO (patrz manifest),
// wiec powierzchnia jest jedna strona, a nie cala aplikacja.

import { MSG } from "../shared/messages.js";

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (event.origin !== window.location.origin) return;

  const data = event.data;
  if (!data || data.source !== "nexus-app") return;
  if (data.type !== "NEXUS_EXT_AUTH") return;
  if (!data.access_token || !data.refresh_token) return;

  chrome.runtime.sendMessage({
    type: MSG.SSO_TOKENS,
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    email: data.email || null,
  });
});
