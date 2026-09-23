# Prepy w Teams — transkrypt, notatka i ocena prepu (0362) — raport

Data: 23.09.2026. Zastępuje integrację z Fireflies.

## Dlaczego

Integracja z Fireflies nigdy nie działała na produkcji: klucz API był pusty,
powstało 0 notatek, synchronizację uruchamiał tylko przycisk w Ustawieniach.
W NEXUSIE nie powstał też ani jeden prep (0 wydarzeń `prep_call`), a Microsoft 365
ma podłączone 2 z ~30 osób (rekruterzy 0/16).

## Decyzje właściciela (23.09.2026)

- Przed każdą rozmową u klienta są dwa prepy przez Teams: Prep 1 prowadzi
  Delivery Lead, Prep 2 rekruter. Telefon po rozmowie zostaje zwykłym telefonem
  z ręcznym debriefem.
- Wciągamy tylko prepy założone w NEXUSIE. Transkrypcja startuje automatycznie.
- Dostęp do M365 przez aplikację, w imieniu organizatora.
- Pełny transkrypt jest trzymany bez limitu czasu. Czyta go zespół rekrutacji; od #1742 (23.09) bramka rekrutacji wpuszcza
  każdą rolę wewnętrzną, więc transkrypt też.
- Ocenia GPT-6 Luna, Sonnet 5 jest zapasem. Kryteria: must-have z Championa,
  pytania tego klienta, udział kandydata w rozmowie.
- Każdy prep ma osobną ocenę. Punkt omówiony w Prepie 1 nie obniża oceny Prepu 2.
- Bramki są miękkie. Zadania dostaje organizator prepu i HoR.
- RODO: stały akapit w zaproszeniu i baner Teams.
- Start od razu dla całego zespołu.

## Co zmieniono

**Backend**
- Migracja `0362_teams_prep_transcripts` i lustro w `entrypoint.sh`:
  tabele `prep_meetings`, `prep_transcripts`, `prep_reviews`, klucz AI
  `prep_review`, typ powiadomienia `prep_attention`, sondy w `/api/health/deep`.
- `services/m365/teams_prep_auth.py`: osobna rejestracja aplikacji
  „NEXUS Teams Prep”. `AppGraphClient` przyjmuje dostawcę tokenu.
- `services/m365/teams_prep_graph.py`: wydarzenie w kalendarzu organizatora,
  spotkanie Teams, automatyczna transkrypcja, lista transkryptów, treść VTT,
  odświeżenie terminu, odwołanie.
- `services/prep_meetings.py` i `api/prep_meetings.py`: podpowiedź organizatora,
  zakładanie prepu (bramka Pipeline, członkostwo, organizator z zespołu,
  409 przy duplikacie, 503 przy wyłączonej integracji), stan prepu, transkrypt,
  raport jakości dla HoR.
- `api/calendar.py`: edycja i odwołanie prepu idą przez aplikację.
- `services/teams_vtt.py`: parser VTT i role mówców.
- `services/prep_transcripts.py` i `tasks/teams_prep_transcripts.py`: pętla
  pobierania z ponowieniami, stanami „bez nagrania” i „brak dostępu”
  oraz sondą `checks.teams_prep`.
- `services/prep_review.py`: punkty buduje kod, model daje status i cytat,
  cytaty są sprawdzane, poziom liczy kod. Zapisuje notatkę z podsumowaniem.
- `services/interview_cycle.py`: numer i jakość prepu, Prep 2 wymagany zawsze,
  zadania `prep_weak`/`prep_unrecorded`, pilne na dobę przed rozmową,
  plakietki `prep_weak`/`prep_missing`.
- `services/prep_attention.py`: kolejka „Czeka na Ciebie” i dzwonek
  `prep_attention`.
- Usunięcie kandydata usuwa transkrypty i oceny, a liczba trafia do audytu.
- Usunięto Fireflies (API, synchronizacja, dopasowanie po tytule, klucz, testy).

**Frontend**
- Okno `PlanPrepDialog` (organizator z podpowiedzią, uczestnicy, informacja
  o nagrywaniu) i okno `PrepReviewDialog` (ocena, punkty z cytatami, udział
  kandydata, lista „Na Prep 2 zostało”, transkrypt).
- Agenda, stepper i lista zadań pokazują jakość prepu.
- Kolejka „Czeka na Ciebie”: sekcja prepów. Kanban: dwie nowe plakietki.
- Insights → Wyniki → „Jakość prepów” (admin i HoR).
- Ustawienia → System → „Prepy w Teams” zastępuje kartę Fireflies.
- Harness `/preview/calendar-cycle` pokazuje prep z oceną i transkryptem.

## Weryfikacja

- Testy backendu na zmigrowanej bazie (przed decyzją „bez lokalnego Dockera”):
  prepy, cykl rozmów, powiadomienia, kontrakty sekcji, heartbeat, rejestr modeli
  i lustra enumów — 218 zielonych, 1 czerwony (rejestr modeli nie znał F23,
  poprawione; plik potem 47/47).
- Przegląd kodu znalazł dwa błędy blokujące i kilka mniejszych. Wszystkie są
  poprawione i mają testy:
  - kolejna runda rozmów u klienta nie mogła dostać nowych prepów;
  - prep bez nagrania nie dało się zaplanować ponownie;
  - pusty transkrypt dostawał ocenę „słaby”;
  - blokady wierszy były trzymane w trakcie wywołań Grapha;
  - dzwonki o braku Prep 1 i Prep 2 się zjadały;
  - czas był liczony źle przy kilku plikach transkryptu;
  - nie było odzyskiwania linku Teams.
- CI na PR-ze: frontend (ESLint, type-check, vitest zmienionych plików) zielony.
  Sito backendu wskazało 3 testy spoza zmienionych plików. Wszystkie poprawione:
  - lista znanych kluczy AI nie znała `prep_review`;
  - dwa testy budowały prepy bez numeru, więc `prep_slot` numeruje je teraz sam.
- Harness `/preview/calendar-cycle` przeklikany w przeglądarce (tekst okien odczytany
  z DOM; zrzutu nie było, bo okno aplikacji było zminimalizowane):
  - zadania „Prep słaby — popraw przed rozmową” i „Prep 2 bez terminu”;
  - okno „Ocena prepu”: ocena „Słaby”, kandydat mówił 22%, cytaty przy punktach,
    lista „Na Prep 2 zostało”, transkrypt z mówcami;
  - okno „Zaplanuj Prep 2”: organizator podpowiedziany (rekruter), informacja
    o nagrywaniu.

## Czego nie da się sprawdzić bez konfiguracji w Azure

- Automatyczny start transkrypcji przez `recordAutomatically` na naszej licencji.
- Polski jako język transkrypcji.
- `User.ReadBasic.All` jako uprawnienie aplikacyjne i ścieżki `onlineMeetings`
  po identyfikatorze obiektu.
- Czy odczyt transkryptów jest płatny.

Procedura: `docs/teams-prep-setup.md`.
