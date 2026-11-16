# Styl interfejsu: tylko „Wyraźny” (cienie), bez wyboru w menu
<!-- indeks: `softUi` zdjęty ze store'u motywu (v9), `data-soft="true"` zawsze, menu „Wygląd” bez sekcji „Styl interfejsu” -->

Decyzja Artura z 13.11.2026: „tryb interfejsu wyłącz to i zostaw tylko tryb
wyraźny cienie i nie pokazuj tego”.

- Menu „Wygląd” (`shell/AppearanceMenu.tsx`, pozycje z `PaletteMenuItems`)
  nie ma sekcji „Styl interfejsu” ani pozycji „Klasyczny (płaski)”.
- `<html>` dostaje `data-soft="true"` zawsze: skrypt startowy w
  `app/layout.tsx` i `ThemeProvider`. Pole `softUi` zniknęło ze store'u
  `nexus-theme` (wersja 9 — migracja usuwa je z zapisanego stanu), więc kto
  miał wybrany styl płaski, po wdrożeniu widzi cienie.
- Warstwa CSS `[data-soft="true"]` w `globals.css` zostaje bez zmian; nowy
  wygląd kart projektuj pod nią, a nie pod styl płaski. Przywrócenie wyboru
  stylu = najpierw pytanie do Artura.
