# Ogłoszenie = jedna treść; strona kariery jednym kliknięciem (21.10.2026)

<!-- indeks: „Opublikuj na stronie”, opis publiczny z ogłoszenia, „Kariera” na liście, kolejka zaległych -->

Decyzje Artura 21.10.2026 (makiety https://claude.ai/artifact/1wcS1zr1hc73nFMKSPwm7P).
Pomiar tego dnia: 203 z 205 otwartych rekrutacji bez strony kariery, 3 opisy
publiczne w ogóle (ostatni 28.09), 27 ogłoszeń na portale, 12 z nich nigdy
nieoznaczonych, żadna rekrutacja z opisem publicznym i ogłoszeniem naraz.
Zespół miał trzy osobne ścieżki dla jednej rekrutacji („Opis publiczny”
w oknie „Udostępnij”, okno kopiuj-wklej na portale, portale API za flagami).

Kod: `services/job_ad/career.py`, trasa `POST /api/jobs/{id}/portal-ad/career`
(`api/job_ads.py`), `jpp.approve_profile` i `jpp.keep_published_text`
(`services/job_public_profile.py`), `career_board.ensure_own_job_link`; front
`components/v2/job-ad/AdChannels.tsx`, przycisk `open-job-ad`
w `JobDetailCompactHeader`, plakietka „Kariera” w `JobAdPublicationsCell`.
Harness `/preview/job-ad?state=ready|published`.

- **Jedna treść.** Strona `kariera.b2bnetwork.pl/r/<slug>` dostaje treść
  ogłoszenia: podtytuł = wstęp (`lead`, przycięty jak szkic), opis =
  „O projekcie” + akapit „Czym się zajmiesz: …; ….” (EN: „What you will do”).
  Opis tnie się na granicy akapitu (`ABOUT_MAX`), nigdy w pół zdania.
  Wymagania, miasto, tryb i start strona bierze z rekrutacji (migawka
  zatwierdzenia) — bez zmian.
- **Tytuł strony zostaje tytułem publicznym rekrutacji.** Ogłoszenie i tak od
  niego zaczyna, a tytuł wchodzi do odcisku materiału
  (`material._HASH_FIELDS`): przepisanie go z ogłoszenia zapalałoby w oknie
  „Rekrutacja zmieniła się od przygotowania ogłoszenia” i mogło zmieniać slug.
- **„Opublikuj na stronie” = zatwierdzenie tą samą drogą co „Udostępnij”**
  (`jpp.approve_profile`: kontrola strony kariery, migawka, rotacja
  niebezpiecznych slugów, aktualizacja żywych ogłoszeń API). Nie dokładaj
  drugiej ścieżki zatwierdzenia.
- **Publikuje się wersja z ekranu i tylko czysta treść:** inny
  `expected_updated_at` = 409 `job_ad_changed`; znalezisko blokujące
  ogłoszenia = 409 `job_ad_blocked`; zamknięta rekrutacja = 409
  `job_not_open`; pusta treść = 422; kontrola strony kariery (czyta też kody
  wewnętrzne RITM/REQ i numer u klienta, które ogłoszenie tylko odradza) =
  422 `PUBLIC_PROFILE_FINDINGS` i nic się nie zapisuje (rollback).
  Okno wyłącza przycisk także przy otwartej poprawce — na stronę idzie
  zapisana treść.
- **Link osoby powstaje od razu** (`ensure_own_job_link`, etykieta
  „Ogłoszenie”, ślad `invite_link_created` z `via=job_ad_career`, blokada
  doradcza jak tablica). Kto swój link do tej rekrutacji wyłączył, nie dostaje
  nowego — okno pokazuje wtedy link z tablicy (`canonical_job_slug`).
- **Stan strony w odpowiedzi okna** (`career`): `none` / `live` /
  `outdated`. `outdated` = strona działa, ale pokazuje inną treść niż obecne
  ogłoszenie (poprawka po publikacji albo opis z dawnego okna „Udostępnij”);
  kandydaci widzą starą wersję (`published_version`), dopóki ktoś nie kliknie
  „Zaktualizuj na stronie”. Adres: własny aktywny link osoby, bez niego link
  z tablicy.
- **Okno „Ogłoszenie”** (dawniej „Ogłoszenie na portale”): prawa kolumna
  „Gdzie publikujesz” = kontrola (`AdChecksPanel`, „Kontrola przed
  publikacją”) + strona kariery + oznaczenia obu portali naraz
  (`AdPublications`), niezależnie od zakładki. Zakładki Pracuj.pl i
  JustJoin.IT zostają jako teksty do wklejenia — do PR-ów z mailem do
  opiekuna Pracuj.pl i JustJoin.IT przez API.
- **Nagłówek rekrutacji:** widoczny przycisk „Ogłoszenie” z trzema kropkami
  (kariera, Pracuj, JJIT) z `GET /api/jobs/{id}` (`career_page`,
  `ad_publications`); na 1280 px sama ikona z kropkami (napis od 1440 px —
  napis zabierał tytułowi ok. 80 px, K-D4), nazwa w dymku i dla czytnika,
  pełna pozycja także w menu „⋯”. Zamknięcie okna odświeża rekrutację.
- **Lista rekrutacji:** `career_page` (otwarta rekrutacja z zatwierdzonym
  opisem, jedno zapytanie na stronę — przybliżenie bez sprawdzania migawki
  klienta) daje plakietkę „Kariera” przed portalami; plakietki stoją w wierszu
  z zawijaniem, żeby nie podnosić wiersza listy.
- **Zaległe rekrutacje — kolejka „Strona kariery do uzupełnienia”**
  (`/jobs/strona-kariery`, `CareerQueue.tsx`, `GET /api/job-ads/career-queue`):
  otwarte rekrutacje bez zatwierdzonego opisu, od najnowszej. „Wszystkie” =
  te, w których osoba może publikować (`job_scope_clause`, ten sam zakres co
  `ensure_job_membership` przy `POST …/career`), „Moje” = Rekruter albo
  Delivery Lead rekrutacji; bez „swoich” ekran sam przechodzi na „Wszystkie”
  (HoR, admin). `limit=0` = same liczby — przycisk „Strona kariery · N” na
  liście rekrutacji (`CareerQueueLink`, 403 albo zero = brak przycisku).
  Publikuje zawsze człowiek, po jednej rekrutacji, wersją z ekranu; pasek
  akcji jest przyklejony do dołu panelu (laptop 720 px). Harness
  `/preview/career-queue`.
- **Nocne przygotowanie treści** (`tasks/job_ad_prepare.py`,
  `services/job_ad/prepare.py`): między 0:00 a 6:00 czasu firmy otwarte
  rekrutacje bez ogłoszenia, od najnowszej, po 40 na przebudzenie co 30 min,
  każda we własnej transakcji. Zapis jak pierwsze „Przygotuj”: model albo
  złożenie z pól (`template`), `INSERT … ON CONFLICT DO NOTHING`,
  `generated_by` puste = przygotował NEXUS. Nic nie publikuje. Pętla jest
  w `loop_heartbeat.EXEMPT` (brak = przycisk „Przygotuj treść” w kolejce).
- **Kolejne kroki (decyzje Artura 21.10.2026):** portale publikuje Delivery Lead rekrutacji,
  admin i Head of Recruitment, rekruter tylko stronę kariery („Poproś DL”);
  Pracuj.pl = mail z całym ogłoszeniem do opiekuna Pracuj.pl ze skrzynki M365
  DL; JustJoin.IT przez API (adapter jest, brak klucza na produkcji).
