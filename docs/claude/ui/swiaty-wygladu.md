# Światy wyglądu: galeria w menu „Wygląd”, zapis na koncie, sezony, świętowanie i strój robota
<!-- indeks: 18 światów + Gra (`THEME_WORLDS`, `data-world`), galeria `WorldGallery`, `users.appearance_prefs` (0693), kalendarz `lib/worlds/seasons.ts`, `WORLD_CELEBRATIONS`, `JarvisOutfit`, kontrakt kontrastu -->

Decyzja Artura z 13.11.2026: „ludzie lubią tryb gracza”, więc oprócz trybu gry
są światy, także spokojne i estetyczne (w zespole przeważają kobiety) i mocniejsze
(Pit stop, Góry, Stadion, ciemne). Wybrane: wszystkie 18 (z Retro), zapis na
koncie, kalendarz sezonów, świętowanie w stylu świata i robot w stroju. Makiety:
https://claude.ai/artifact/P1G9Hr7ETZcmaXAv5xhcjd

- **Świat = cały wygląd naraz.** `data-world="<id>"` na `<html>` podmienia tokeny
  i dokłada tło, krawędzie kart i nagłówki (`globals.css`, sekcje „ŚWIATY”).
  Układ, rozmiary i treść się nie zmieniają. Warstwa „Wyraźny” jest pod światem
  wyłączona (`:not([data-world])`). Gra to dalej `kidsMode`; na koncie zapisuje
  się jako świat `game`.
- **Świat wybiera jasny albo ciemny** (`scheme` w `THEME_WORLDS`): `ThemeProvider`
  dokłada albo zdejmuje `.dark`, skrypt startowy w `app/layout.tsx` robi to przed
  pierwszym malowaniem (lustro `DARK_WORLD_IDS`). Bez tego komponenty z wariantem
  `dark:` świeciły jasno na ciemnym świecie. Przy włączonym świecie menu chowa
  „Motyw koloru” i „Tryb ciemny”.
- **Wybór jest w galerii** (`WorldGallery`, jedno okno w powłoce,
  `openWorldGallery()`): menu „Wygląd” pokazuje tylko bieżący świat i „Zmień”,
  na telefonie przycisk „Świat” w szufladzie. Kafelki po klimacie: jasne
  i spokojne, kolorowe, ciemne, sport i przygoda, sezonowe. Nazwy po klimacie,
  nie po płci. Miniatury czytają kolory z klas `.world-thumb-<id>` w arkuszu.
- **Czerwień zostaje dla „pilne”.** Żaden świat nie ma czerwonych przycisków
  (pierwsza Zima miała i myliła się z „P0”). Każda para tekstu ma kontrast co
  najmniej 4,5:1. Pilnuje `lib/__tests__/theme-worlds-contract.test.ts`; nowy
  świat bez tokenów, kółka (`.world-swatch-<id>`) albo miniatury go zatrzyma.
- **Zapis na koncie** (`users.appearance_prefs`, migracja 0693, lustro
  w `entrypoint.sh`): `GET/PATCH /api/users/me/preferences` → `appearance`
  `{world, world_before_season}`. Przy wczytaniu wygrywa konto; konto bez zapisu
  dostaje wybór z przeglądarki (`AppearanceSync`, tylko przy własnej sesji).
  Lista światów ma lustro na serwerze (`services/appearance_prefs.py` ↔
  `lib/worlds/world-ids.ts`, test `test_appearance_prefs.py`). Ile osób
  wybiera który świat (read-only, `prod_readonly`):
  `SELECT appearance_prefs->>'world', count(*) FROM users WHERE is_active GROUP BY 1`.
  Po kilku tygodniach światy, których nikt nie używa, zdejmujemy z galerii.
- **Kalendarz sezonów** (`lib/worlds/seasons.ts`, daty w Europe/Warsaw): Zima
  1.12–6.01, Tulipany 1–8.03 (Dzień Kobiet), Dzień Chłopaka 30.09 (wyróżnione
  Pit stop i Góry). Świat sezonowy jest w galerii tylko w swoim terminie i nigdy
  nie włącza się sam: kropka „nowe” przy „Wyglądzie” do pierwszego otwarcia
  galerii, jedno powitanie robota na sezon z **wspólnego budżetu dymków**
  (`bubble-budget.ts`, nie osobne źródło). Po terminie osoba wraca do świata
  sprzed sezonu (`worldBeforeSeason`).
- **Świętowanie** (`celebrate()`, `WORLD_CELEBRATIONS`): ten sam moment co w Grze
  (placement, awans), efekt w stylu świata — płatki w Sakurze, szachownica
  w Pit stopie, śnieg w Zimie, gwiazdy w Kosmosie. Zen celowo bez efektu,
  dźwięk tylko w Grze, „ogranicz ruch” wyłącza cząstki.
- **Robot w stroju** (`JarvisOutfit`): czapka w Zimie, kask w Pit stopie, szalik
  na Stadionie, wianek w Tulipanach, kwiat w Sakurze, kapelusz w Górach, hełm
  w Kosmosie, słuchawki w Arcade. Ubieramy tylko robota (inne postaci mają inne
  kształty); kolory w klasach `.jo-*`.
- **Ruch tylko w tle:** płatki i śnieg stoją przy „ogranicz ruch”, tęczowa
  obwódka RGB kręci się tylko po najechaniu.
