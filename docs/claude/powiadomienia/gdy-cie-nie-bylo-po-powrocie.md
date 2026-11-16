# „Gdy Cię nie było” — praca z nieobecności po powrocie (16.11.2026)
<!-- indeks: cichy wiersz zastępcy (Notification.quiet) zamiast skip, on_behalf_of jako źródło, sekcja nad „Twój ruch”, załatwione przez osobę albo zastępcę, ACTION_TYPES, 0722 -->

Zgłoszenie z 16.11.2026 (DL przez Teams): rekruterka wróciła z urlopu i nie
wiedziała, że dwie rekrutacje z jej kandydatami u klienta zostały zamknięte.
Zamknął je jej zastępca, a reguła „autor ruchu nie dostaje dzwonka”
(`praca-nieobecnego-idzie-do-zastepcy.md`) wyrzucała wtedy wiersz w całości —
nie dostał go nikt, choć okno zamykania obiecywało „damy znać”. Pozostałe
29 powiadomień z jej pracy poszło do zastępcy i po powrocie nie widziała
żadnego. Makiety i decyzja Artura (wariant A):
https://claude.ai/artifact/4cnT834R5R1mbkzWac5gvx

- **Wiersz nie znika.** Gdy zastępca sam wykonuje ruch za nieobecną osobę,
  `notification_route` zwraca `Route(quiet=True)`, a `emit` zapisuje wiersz
  u zastępcy z `on_behalf_of_user_id`, od razu przeczytany i z
  `Notification.quiet` — bez dymka i bez maila (outbox i mail ruchu karty
  pomijają `quiet`). Nie przywracaj `skip`.
- **Źródło sekcji to `on_behalf_of_user_id`.** Wszystko, co w nieobecności
  poszło do zastępcy (także ciche wiersze), z ostatnich 30 dni i bez
  `away_dismissed_at`. Nie licz tego z urlopów — źródło nieobecności bywa
  w Compassie albo w NEXUSIE, a wiersze już mówią, za kogo przyszły.
- **Sekcja stoi na górze „Czeka na Ciebie”** (`WhileAwaySection`), także gdy
  panel jest pusty. Nie pokazuje się, póki osoba jest zastępowana.
- **Do załatwienia** są typy z `ACTION_TYPES` (dziś zamknięcie rekrutacji
  z osobami w toku); reszta to licznik per kategoria dzwonka. Nowy typ do
  załatwienia = wpis w `ACTION_TYPES`, nie osobna sekcja.
- **„Załatwione”** może oznaczyć osoba albo jej zastępca — to jeden wiersz,
  więc oboje widzą ten sam stan i kandydat nie dostaje dwóch wiadomości.
  „Zamknij podsumowanie” ustawia `away_dismissed_at` tylko u tej osoby.
- **Strona zastępcy (16.11.2026):** wątek okienka „Rekrutacje”
  (`GET /api/notifications/jobs`) niesie `away_case` — najnowsze
  niezałatwione zamknięcie z `ACTION_TYPES`, które przyszło do zastępcy
  w zastępstwie, także ciche (`while_away.deputy_cases`). Pod wierszem
  pasek „W zastępstwie za …” z przyciskiem „Dałem znać” (ta sama trasa
  `…/while-away/{id}/handled`), po zapisie „Załatwione · <imię>”. Pasek
  stoi pod wierszem, nie w nim, bo wiersz jest przyciskiem do rekrutacji.
  Okno 7 dni okienka obowiązuje: później zostaje sekcja u osoby po powrocie.
- Kolumny: `quiet`, `handled_at`, `handled_by_user_id`, `away_dismissed_at`
  (0722 + lustro w `entrypoint.sh`).
