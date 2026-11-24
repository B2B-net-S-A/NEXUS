# Poligon NEXUSA — onboarding pierwszego dnia na rekrutacji ćwiczebnej
<!-- indeks: `/poligon`, ścieżki per rola (rekruter 27, DL 17, TCM 13), narzędzia rekrutera z 16.11 (telefon, termin u klienta, CV z pliku, zapisane wyszukiwanie, lista, czat, asystent CV, Jarvis bez modelu — `lib/poligon/tools.ts`), terminy od klienta DL-a (wklejony mail bez modelu), wymagany od nadania roli, blokada nowej osoby zamiast Startu, poligon dla obecnych „tylko luki” (`poligon_luki`, „Kto zna NEXUS”), dzień onboardingu poza statystykami (`onboarding_day`), tryb w przeglądarce (`lib/poligon/`), zapisy nie wychodzą do API poza postępem `poligon-*`, zestaw z `build_poligon_dataset.py`, klient ćwiczebny 990501 (`poligon_client_practice.py`, kwoty wg roli w `amounts.ts`, 22.11.2026), CV z nowości: lata w punkcie 1 i gotowe CV z nową zgodą (`poligon_cv_practice.py`, odczyt osoby przed szablonem), strażnik `poligon-dataset.test.ts`, pola wstawiane w zdanie bez `null` (`poligon_person_texts.py`), podgląd pliku = komunikat Poligonu, koniec Poligonu z luk bez zdania o statystykach -->

Decyzje Artura z 14.11.2026 (makiety: https://claude.ai/artifact/FQGjXqm7T4Bpoi4fYCpmsk).
Co miesiąc dochodzi 7–14 nowych kont i każdą osobę HoR szkolił osobno. Start
w NEXUSIE (`start-w-nexusie.md`) idzie po prawdziwych danych, więc 7 z 15 kroków
rekrutera kończyło się przyciskiem „Rozumiem” zamiast wykonaniem. Na poligonie
osoba naprawdę przesuwa karty, wypełnia screening, odrzuca i przypisuje z bazy —
na wymyślonych danych.

## Ścieżka roli, cała pierwszego dnia

- **Bez poziomów i egzaminów** (Artur, 14.11.2026, drugie podejście): wszystko
  od razu w onboardingu. 19 ćwiczeń w 6 modułach (`lib/poligon/exercises.ts`;
  od 16.11.2026 27 w 8 modułach, sekcja „Narzędzia rekrutera”):
  lista rekrutacji, Tablica (Biorę, ruch, źródła, Moi ludzie), panel osoby
  (notatka, „@”, odrzucenie z powodem), screening i weryfikacja (formularz,
  bramka „Zweryfikowany”, zapis, weryfikacja), rekomendacja (CV dla klienta,
  QC CV) i baza kandydatów (szukanie, profil, przypisanie). Od 15.11.2026
  ścieżki są per rola (rekruter, Delivery Lead, TCM) — sekcja niżej.
- **Blokuje pracę nowej osoby.** `GET /api/novelties/start` zwraca `poligon`
  i `redirect`. Osoba z poligonem wymaganym jest zatrzymana (`useStartGate`)
  i prowadzona na `/poligon`, dopóki nie zaliczy wymaganych ćwiczeń
  (`poligon.exercise_ids`). Po „Zakończ onboarding” na `/onboarding` idzie
  od razu na `/poligon`, nie na pulpit (`afterOnboardingPath`, 22.11.2026) —
  pulpit zostaje wolny od blokady, więc inaczej Poligon widziała dopiero po
  kliknięciu innego ekranu. Poligon zastępuje jej przeklikania Startu
  z `replaces` (mapa rola → przeklikania). Obecne osoby mogą wejść na mapę,
  ale poligon ich nie blokuje.
- **Wymagany od nadania roli, nie od założenia konta** (Artur, 15.11.2026:
  „Od nadania roli, brakujące ćwiczenia”). Pierwsze logowanie SSO zakłada
  konto „Pracownik” (`employee`) — poligonu nie ma, nic nie blokuje, dzień nie
  wypada ze statystyk. Rolę z poligonem (`required_roles`: rekruter, Delivery
  Lead, TCM) nadaje potem ktoś w „Osoby i role” albo grupa Entra:
  - wymagane = ćwiczenia ścieżki obecnych ról, których nie obejmowała ścieżka
    ról osoby z dnia `required_since` (`onboarding_day.PoligonRequirement`).
    Role z tego dnia odtwarza się wstecz z historii zmian ról w `activities`
    (`role_changed`, `roles_changed`, `sso_aad_role_assigned`,
    `sso_aad_roles_updated`, `admin_aad_role_resynced`,
    `admin_aad_roles_resynced`; wiersze jednej transakcji mają ten sam
    `created_at`). Konto założone później nie miało żadnej roli;
  - zmiana roli = tylko ćwiczenia nowej roli, których osoba jeszcze nie
    zaliczyła (wspólne moduły liczą się raz, z istniejących wierszy
    `novelty_progress`). Rekruter sprzed 15.11, który zostaje DL-em, robi tylko
    przegląd DL-a. Powrót do roli, którą już przeszła, i rola bez ścieżki nie
    wymagają niczego;
  - ścieżka KPI (co minutę dla każdego) pyta bazę tylko u osób z szybkiego
    filtra `poligon_may_be_required` (rola z poligonem i konto albo
    onboarding roli od `required_since` — zmiana roli rekrutera i DL-a zeruje
    `profile_completed_at`); test na jedno `db.execute` w
    `test_kpi_milestone_snapshot_round7.py`.
  Podgląd jako inna osoba zdejmuje tę blokadę. Wyłącznik Startu
  (`app_settings.start_gate`) jej nie zdejmuje, bo dotyczy tylko przeklikań
  Startu (Artur, 15.11.2026: Start był wyłączony od 30.10, więc poligon nikogo
  nie zatrzymywał). Blokadę Poligonu zdejmuje jej własny wyłącznik
  `app_settings.poligon_gate` (brak wiersza = włączona): przycisk „Wyłącz
  blokadę” w Ustawienia → „Nowości — kto już umie” (admin, HoR; ten sam
  `PUT /api/novelties/start/gate` z polem `poligon`). To zabezpieczenie na
  wypadek, gdyby ćwiczenie przestało się zaliczać (Artur, 15.11.2026). Stack
  E2E wyłącza go w `scripts/seed_e2e.py`.
- **Dzień onboardingu nie liczy się do statystyk.** To dzień (Europe/Warsaw)
  pierwszego wymaganego ćwiczenia zaliczonego po nadaniu roli (przy
  założeniu konta z rolą i przy każdej zmianie, która wnosi rolę z
  `required_roles`), tylko u osoby, której poligon jest wymagany
  (`app/services/onboarding_day.py`). Zmiana roli może więc dać drugi taki
  dzień — `onboarding_days` zwraca zbiór dni. Taki dzień nie jest dniem pracy
  w żadnym mianowniku ani w żadnej normie:
  - `person_workdays.absence_by_user` (przy każdym źródle urlopów), co obejmuje
    Weryf./dz., cele KPI i Rytm;
  - `kpi_engine.personal_days_off` (tempo);
  - próg i plakietka Wyścigu Rekomendacji;
  - Porcja dnia: tego dnia osoba nie dostaje porcji (`review_batch.absent_today`).

  Rytm liczy osobę od dnia po pierwszym onboardingu. Weryfikacje i rekomendacje zrobione
  mimo to tego dnia liczą się normalnie, bo to prawdziwa praca.
- **Postęp na serwerze.** `novelty_progress` z id `poligon-…`, zdarzenie
  `used` na `POST /api/novelties/{id}/events` (bez nowej trasy i bez migracji).
  Rejestr id: `backend/app/data/novelties/poligon.json`. Test frontu pilnuje,
  że ma te same id i role co `exercises.ts`. Ćwiczenie spoza ścieżki ról osoby
  dostaje 404. `localStorage` służy tylko jako pamięć
  podręczna mapy.

## Poligon dla obecnych: tylko luki (16.11.2026)

Analiza 60 dni pracy 16 rekruterów (nocna kopia produkcji z 15.11): rdzeń
procesu używa 16 z 16 osób, a luki są różne u każdej (2–11 funkcji). Najwięcej
mają osoby z kontem z października i listopada. Artur wybrał 16.11.2026: obecni
nie przechodzą całego poligonu, tylko luki, z terminem.

- **Funkcje i sygnały użycia** są w `app/services/poligon_luki.py` (`FEATURES`,
  24 funkcje). Sygnał to zdarzenie w pracy z 60 dni: `activities`,
  `user_activities`, notatki, przeglądy bazy, kalendarz itd. Brak użycia przez dwa
  miesiące traktujemy jako lukę. Nową funkcję rekrutera dopisujesz tam razem z
  sygnałem i ćwiczeniami, które zalicza.
- **Kampania** (`POST /api/novelties/poligon/luki`, admin i HoR, przycisk
  „Wyślij poligon z lukami” w „Nowości — kto już umie”):
  - obejmuje aktywnych rekruterów bez roli admina i HoR;
  - ćwiczenia z używanych funkcji (i lista rekrutacji) zalicza wiersz
    `novelty_progress` z `completed_via = 'used'` („użyciem w pracy”, bez migracji);
  - termin domyślnie za tydzień;
  - stan leży w `app_settings.poligon_luki` (termin i lista zaliczonych z pracy na osobę).
- **Do terminu poligon prosi:** pasek `PoligonLukiNotice` nad treścią ekranu,
  a na mapie luki i znaczki „z pracy”. **Po terminie blokuje** jak u nowej
  osoby (`required`, `redirect=/poligon`) i zdejmuje to ten sam wyłącznik
  `poligon_gate`. Dzień ćwiczeń nie wypada ze statystyk, bo to kilkanaście–
  kilkadziesiąt minut.
- **„Kto zna NEXUS”** (`GET /api/novelties/poligon/luki`, admin i HoR) to macierz
  osoba × funkcja, z liczbą luk i postępem poligonu po wysłaniu.
- Osiem funkcji z luk ma od 16.11.2026 ćwiczenia (sekcja niżej), a ich
  `exercises` w `FEATURES` zaliczają je z pracy. Funkcje bez ćwiczenia
  („Dlaczego ten kandydat”, zmiana stawki, dostępność i tryb pracy) macierz
  liczy, ale z pracy nic nie zaliczają.

## Narzędzia rekrutera na poligonie (16.11.2026)

Artur 16.11.2026: „uczyć na poligonie”, także funkcji prawie nieużywanych
(analiza 60 dni: zapisane wyszukiwania 0/16, listy 2/16, czat 7/16, Jarvis
10/16). Osiem ćwiczeń, każde zalicza wykonanie na rekrutacji ćwiczebnej:

| Ćwiczenie | Moduł | Role | Zalicza | Funkcja w `poligon_luki` |
|---|---|---|---|---|
| `baza-lista` — „Na listę” na profilu Laury | Baza kandydatów | rekruter, TCM | `pool_add` | `pula` |
| `baza-zapisane-wyszukiwanie` | Baza kandydatów | rekruter, TCM | zapis z „Powiadamiaj…” i z kryterium | `zapisane_wyszukiwanie` |
| `zrodla-cv-z-pliku` — „Dodaj” → „Dodaj z pliku CV” | Źródła i kalendarz | rekruter | `cv_upload` | `cv_z_pliku` |
| `kalendarz-telefon` — „Umów telefon” | Źródła i kalendarz | rekruter | `screening_call` | `screening_kalendarz` |
| `kalendarz-termin-klienta` — „Wybierz termin z kandydatem” | Źródła i kalendarz | rekruter | drugi z trzech terminów | `terminy_klient` |
| `zespol-czat` — „Czat zespołu” z „@” | Zespół i AI | rekruter, DL | wiadomość ze wzmianką | `czat` |
| `zespol-cv-ai` — „Otwórz i popraw”, polecenie w asystencie | Zespół i AI | rekruter | nałożona zmiana (`cv-ai/applied`) | `polecenie_ai_cv` |
| `zespol-jarvis` — pytanie o osobę z Tablicy | Zespół i AI | rekruter | odpowiedź o osobie z Tablicy | `jarvis` |

- **Stan w pamięci, nic do API** (`lib/poligon/tools.ts`, podpięte w `store.ts`):
  telefon (`booked_call` na karcie), wybór terminu (odznaka „czeka na DL”,
  prepy z okna też tylko w pamięci), osoba z pliku CV (stała osoba ćwiczebna
  Ewa Jesionowska, „Pewność” odczytu z polami do sprawdzenia, potem „Nowi”),
  zapisane wyszukiwania i listy należą do zalogowanej osoby (`viewerId`
  z `nexus_user`), czat, CV firmowe z autozapisem. Odpowiedź narzędzia to
  kopia stanu — ta sama tablica dwa razy daje w react-query „bez zmian”.
- **„Terminy u klienta” rekrutera = wybór terminu.** Terminy wpisuje DL
  (`POST /api/interview-cycle/slots` daje rekruterowi 403), a rekruter używa
  funkcji, wybierając termin z kandydatem. Ćwiczenie DL-a jest w sekcji
  „Terminy od klienta Delivery Leada” niżej.
- **AI bez modelu.** Plan asystenta CV to stałe reguły („pogrub Scrum i Jira”,
  „+ Punkt do podsumowania”; inne polecenie = pusty plan z podpowiedzią).
  Jarvis (`lib/poligon/jarvis.ts`): rozmowa idzie natywnym `fetch` (SSE),
  który omija adapter axiosa — do 16.11 pytanie z poligonu szło do modelu
  i zakładało rozmowę w bazie. W trybie poligonu `JarvisRoot` dostaje
  podstawiony `fetch` ze stałą odpowiedzią o osobie z Tablicy, a
  `/api/jarvis/status` odpowiada poligon („dostępny”). Nowe wywołanie AI
  natywnym `fetch` na ekranie z poligonu = taki sam podstawiony `fetch`.
- **CV ćwiczebne** do edytora jest w `lib/poligon/cv-fiction.ts` (zestaw nie
  przyjmuje tekstu spoza słownika), a plik do wgrania w
  `public/poligon/cv-cwiczebne-ewa-jesionowska.txt` (link w oknie ćwiczenia,
  pole `download`). Na poligonie każdy plik daje tę samą osobę.
- **Kotwice „Pokaż mi”:** nowa jest tylko `jobs.board.chat` (dymek „Historia
  i czat”, `data-help` w przewodniku `jobs.board`). `data-tour` musi należeć do
  nowości z rejestru (`novelty-anchors.test.ts`), a przewodnik ma najwyżej
  6 kotwic — `candidate.profile` i `jobs.person` mają komplet, więc lista
  wskazuje sąsiedni „Przypisz do rekrutacji”, a termin u klienta cały panel osoby.
- **Daty `@relt:<n>T<HH:MM>`** w zestawie = za `n` dni roboczych o pełnej
  godzinie UTC (terminy u klienta i podpowiedzi prepów), żeby okno nie
  pokazywało „13:27” ani soboty.
- Nowa osoba, która zaliczyła 19 ćwiczeń przed wdrożeniem, po wdrożeniu ma
  8 nowych do zrobienia (blokada wraca do ich zaliczenia). 16.11.2026 rano
  w nocnej kopii nikt nie miał postępu `poligon-*`.

## Terminy od klienta Delivery Leada (16.11.2026)

Ćwiczenie `dl-terminy-klienta` (moduł „Przegląd Delivery Leada”, role DL,
admin, HoR) idzie po wysyłce CV: Weronika Cisowska stoi w „CV wysłane”, DL
otwiera jej panel → „Terminy od klienta” (`SlotRequestDialog`) i wpisuje
terminy z maila klienta podanego w treści ćwiczenia
(`POLIGON_CLIENT_MAIL` w `exercises.ts`).

- **Zalicza** zdarzenie `slot_request`: wśród terminów są godziny z maila
  (10:00 i 13:00 czasu przeglądarki) i czas rozmowy 45 min. Inne godziny albo
  inna długość = informacja zwrotna; poprawka idzie przez „Zastąp otwarte
  terminy” (409 `SLOTS_ALREADY_OPEN`, jak na serwerze).
- **Stan w pamięci** (`tools.ts`): `POST /api/interview-cycle/slots` tworzy
  wniosek `awaiting_recruiter` z rekruterem poligonu, przenosi kartę
  z „CV wysłane” na „Rozmowę u klienta” (jak `create_slot_request_for_pair`)
  i daje jej odznakę „Wybierz termin” ze wzoru nagranej odznaki Kamila.
  Terminy wpisuje się tylko w „CV wysłane” i „Rozmowie u klienta” (tam jest
  przycisk); inna kolumna, przeszłość, brak terminu = 422.
  `GET …/slots/recipient` odpowiada „Jakub Szkoleniowy” bez zastępstwa.
  Rekruter przycisku nie ma (`canAddClientSlots` = DL, HoR, admin), więc
  poligon nie powtarza odmowy 403.
- **„Wklej maila od klienta” bez modelu.** `…/slots/from-mail` na poligonie
  nie woła modelu: mail z ćwiczenia (oba cytaty terminów w tekście) daje stały
  odczyt — dwa najbliższe dni robocze o 10:00 i 13:00, 45 min, online. Inny
  tekst dostaje `status: "empty"` z komunikatem, że poligon czyta tylko mail
  z ćwiczenia i terminy można wpisać ręcznie.
- **Przeładowanie strony** cofa wysyłkę, więc „CV wysłane” jest puste; treść
  ćwiczenia każe wtedy wysłać Weronikę z „QC CV” jeszcze raz.
- **Bez nagrania.** Odczytów okna nie dogrywano ze stagingu: panel osoby
  w „CV wysłane” i „Rozmowie u klienta” podaje zestaw przez osobę-szablon,
  a jedyny nowy odczyt (adresat terminów) to stała odpowiedź narzędzia
  z trenerem poligonu. Nagranie miałoby tu prawdziwe nazwisko rekrutera.
- **Z pracy** zalicza je funkcja `terminy_klient` w `poligon_luki.py`.
  Sygnał liczy obie strony wniosku (`recruiter_id` i `created_by`), a
  `credited_exercises` zalicza tylko ćwiczenie ze ścieżki osoby: rekruterowi
  wybór terminu, DL-owi wpisanie terminów. Kampania luk obejmuje rekruterów,
  więc DL-a z pracy liczy to tylko przy roli rekrutera.
- Rekruter sprzed 15.11, który zostaje DL-em, ma do zrobienia cztery
  ćwiczenia DL-a (przegląd, wysyłka, poprawki, terminy).

## Klient ćwiczebny: karta klienta, kontrakty, Finanse (22.11.2026)

Artur 22.11.2026 wybrał „klient ćwiczebny”: wpisy Nowości z ekranów klienta,
kontraktów i Finansów nie miały na Poligonie drogi do elementu (Strażnik
Nowości zgłaszał ok. 15 takich wpisów co noc).

- **Dane są wymyślone w `backend/scripts/poligon_client_practice.py`**, bez
  nagrania: „Bank Północny” (990501) z kartą, Konsultantami i rozliczeniem
  poprzedniego miesiąca; kontrakt B2B Filipa Bukowca (990521, zamówienie kończy
  się za 40 dni, aneks 2 z dokumentu ze stawką do wprowadzenia, opieka, start,
  dokumenty, aneksy); zakończony kontrakt Mai Wierzbickiej (990522) z
  zamówieniem po końcu; jeden wpis „Zamówienia z maila” do sprawdzenia;
  w Finansach rozjazd stawki i zamówienie do korekty po zmianie stawki Partnera.
  Kwoty pasują do rekrutacji ćwiczebnej (Partner 105 zł/h, klient 122 zł/h).
- **Bez nagrania:** `python3 scripts/build_poligon_dataset.py --practice-only`
  (z `backend/`) nakłada wymyślone odczyty na zestaw w repo. Pełna przebudowa
  z nagrania dokłada je sama. Test `tests/test_poligon_client_practice.py`
  pada, gdy zestaw w repo nie zgadza się z generatorem.
- **Listy idą z zestawu, nie z API** (`OWNED_PATHS` w `store.ts`): lista
  klientów, lista kontraktów z licznikami pigułek, kolejka zamówień z maila,
  rozjazdy stawek i korekty kosztu. Do 22.11 te listy w trybie Poligonu
  pokazywały prawdziwych klientów osoby, która ćwiczyła. Licznik pigułki ma
  własny klucz zestawu (`contract_list_keys`); bez niego store wziąłby
  pierwszą nagraną listę i wszystkie pigułki miałyby tę samą liczbę.
- **Kwoty tylko dla ról z kwotą.** Zestaw ma kwoty w całości, a
  `lib/poligon/amounts.ts` zdejmuje je tak jak serwer:
  - osoba bez „Stawki i kwoty: podgląd” i bez `view_finance` (np. TCM) nie
    dostaje stawek, marży, waluty kontraktu, harmonogramów, cytatu z dokumentu
    ani marży klienta (`_redact_contract_finance`, profil klienta);
  - Finanse bez „Wyników firmy” nie widzą marży w wierszach listy kontraktów
    (`_hide_company_margin`);
  - nieznana osoba nie widzi kwot;
  - redakcja dotyczy tylko odpowiedzi z `meta.fiction_responses`. Rekrutacja
    ćwiczebna z nagrania zostaje bez zmian.
- **Klient ćwiczebny jest w portfelu ćwiczącego Delivery Leada.** Adapter
  dopisuje 990501 do `data_scope` w odpowiedzi `/api/auth/me`, tylko w trybie
  Poligonu (`withPracticeClient`). Bez tego front liczyłby
  `canViewClientFinance` jak dla obcego klienta i schował DL-owi rozliczenie
  i dokumenty. Do `finance_client_ids` trafia tylko u osoby z podglądem kwot.
- **Sekcji nikt nie omija:** rekruter bez podglądu Delivery dostaje na
  `/clients/990501` to samo 403 co na prawdziwym kliencie (middleware).
- **Strażnik zestawu** sprawdza odpowiedzi z `meta.fiction_responses`
  osobno: identyfikatory 990000+, osoby tylko ćwiczebne, trenerzy i
  `meta.client_people` (kontakt klienta), bez e-maili i adresów. Słownik kluczy
  nagrania (`safe-keys.json`) ich nie dotyczy.
- **Wpisy Nowości** z klienta, kontraktów i Finansów mają `practice_href`
  na te ekrany (`/clients/990501`, `?tab=konsultanci`, `/contracts`,
  `/finance?view=rate-divergences`). Nowy ekran klienta albo kontraktu
  z nowością = odpowiedzi w `poligon_client_practice.py` i jeden ekran
  przeklikany w trybie Poligonu: adapter pisze w konsoli
  `[poligon] brak odpowiedzi w zestawie`, a zły kształt kończy się błędem
  ekranu (22.11: notatki opieki bez `at`).

## CV z nowości: lata w punkcie 1 i gotowe CV z nową zgodą (22.11.2026)

Strażnik Nowości zgłaszał dwa wpisy z rekrutacji bez drogi do elementu:
„Lata w punkcie 1 i daty stanowisk” (`cv-editor.tenure-split`) i „Gotowe CV
z nową zgodą RODO” (`cv.ready-cv-new-consent`). Odczyty są wymyślone
w `backend/scripts/poligon_cv_practice.py`, a `--practice-only` nakłada je na
zestaw razem z klientem ćwiczebnym.

- **Lata w punkcie 1.** CV ćwiczebne (`cv-fiction.ts`) ma od 22.11 punkt 1
  „9 lat jako Project Manager…” i starszą rolę „Analityk biznesowy”, więc
  cały staż z dat ról jest o ponad rok dłuższy. Uwaga `years_breakdown`
  w QC edytora to wynik serwera na tym CV; test
  `tests/test_poligon_cv_practice.py` liczy ją od nowa kodem `cv_qc`, a punkt
  i role muszą stać w `cv-fiction.ts`. Propozycję klikniesz naprawdę:
  `POST …/qc/transform` z samym `tenure_split` podmienia frazę w pamięci
  (`tools.ts`); inne poprawki QC dalej dostają 409.
- **Lista „Do poprawy” w edytorze widoczna od 22.11.** Edytor chowa listę QC,
  gdy `qc.cv.stage_id` nie jest otwartym etapem. Odczyty edytora nagrano na
  etapie innej osoby (`--cv-stage`), więc do 22.11 lista na Poligonie nigdy się
  nie pokazywała. Wymyślone QC edytora ma etap osoby-szablonu.
- **Gotowe CV z nową zgodą.** Bartosz Brzozowski (990106, Screening) nie ma
  CV do klienta (`status: none`, bez wierszy generatora), a jego „sources”
  mają zatwierdzone CV z innej rekrutacji u tego klienta
  (`consent_carried: false`). Klient ćwiczebny ma w regule CV „Zrzut zgody
  RODO” jak PKO BP, więc karta „CV do klienta” i screening pokazują też żółty
  pasek prośby o zgodę (każdej osobie; generacji i wysyłki na Poligonie nikt
  nie robi).
- **Odczyt zapisany dla osoby wygrywa z osobą-szablonem** (`store.read`).
  Do 22.11 każda osoba dostawała odczyty Heleny ze swoim imieniem; klucz
  z `entry_id` albo `candidate_id` konkretnej osoby pozwala dać jej inny stan
  bez zmian w kodzie ekranów.
- **QC edytora jest w `meta.fiction_responses`**, bo uwaga ma klucze spoza
  słownika nagrania (`term`, `proposal`, `quote`, `dates`). `quote` jest też
  na liście kwot w `amounts.ts`, więc osoba bez kwot dostaje uwagę bez cytatu
  (ekran go nie używa); narzędzie czyta QC bez zdejmowania kwot.
- **Kroki** prowadzą przez dok: nagłówek sekcji „CV” (`person.dock.cv`),
  potem „Edytuj CV” (`person.cv.edit`) albo „CV do klienta: strony i wersje”
  (`person.dock.cv-to-client`). Adres `?candidate=…&panel=cv` miał od razu
  otwierać warsztat na zakładce CV, ale 22.11 na Tablicy gubił `panel`
  i otwierał zwykły dok.

## Stop do podpisu przedwstępnej (lekcje Nowości, 23.11.2026)

Dwie lekcje funkcji z `rekrutacja-tablica/stop-do-podpisu-przedwstepnej.md`:
DL i HoR ustawiają przedwstępną dla rekrutacji i robią wyjątek dla osoby
(`lekcja-stop-do-podpisu-przedwstepnej`), rekruter rozpoznaje kartę, która
stoi do podpisu (`lekcja-stop-przedwstepnej-na-karcie`). Stan jest wymyślony
w `backend/scripts/poligon_pre_contract_practice.py` i nakładany przez
`--practice-only`:

- rekrutacja ćwiczebna ma ustawienie „przed wysłaniem CV”, karta stoi do
  podpisu (ustawiła Anna Poligonowa);
- Szymon Grabowiec w „QC CV”: prośba wysłana, plakietka „Stop ·” i kłódka na
  strzałce; Weronika Cisowska obok ma przedwstępną podpisaną, więc ćwiczenie
  wysyłki DL-a idzie jak dotąd, a „Wróć do poprawy” na Szymonie działa;
- `store.ts` odmawia ruchu za blokadę (409 `PRE_CONTRACT_NOT_SIGNED`), pokazuje
  blokującą pozycję w oknie „Przesuń dalej” i ustawia `can_set_stop` w parze
  z roli oglądającego (adapter: `canSetPreContractStop`), więc rekruter nie
  widzi „Wyjątek dla tej osoby”. Test: `tests/test_poligon_pre_contract_practice.py`.

## Ścieżka per rola: rekruter, Delivery Lead, TCM (15.11.2026)

Artur 15.11.2026 wybrał „Osobna sesja” dla ćwiczeń DL i TCM. Od tego dnia
poligon jest wymagany także od nowego Delivery Leada i TCM. Do tej pory obie
role dostawały stary Start z przyciskami „Rozumiem”.

- **Ćwiczenie ma role** (`roles` w `exercises.ts` i w `poligon.json`, test
  frontu pilnuje, że to te same listy). Osoba przechodzi ćwiczenia każdej swojej
  roli, w kolejności rejestru:
  - `exercisesFor` / `usePoligonPath` we froncie;
  - `PoligonPlan.exercises_for` / `poligon_exercises` na serwerze.

  Admin i Head of Recruitment widzą na mapie wszystkie ćwiczenia, ale poligon
  ich nie blokuje.
- **Ścieżki:**
  - wspólne (wszystkie trzy role):
    - lista rekrutacji;
    - Tablica (przesunięcie, źródła);
    - panel osoby (notatka, „@”, odrzucenie z powodem);
    - baza kandydatów (szukanie, profil, przypisanie).

    To ćwiczeniowy odpowiednik czterech przeklikań Startu, które wszystkie trzy
    role miały w `start.json`;
  - rekruter (27 ćwiczeń, od 16.11.2026; wcześniej 19):
    - „Biorę” i „Moi ludzie”;
    - screening i weryfikacja;
    - CV dla klienta i przekazanie do QC CV;
    - narzędzia rekrutera (osiem ćwiczeń z sekcji wyżej);
  - Delivery Lead (17 ćwiczeń, z czatem rekrutacji):
    - CV dla klienta;
    - moduł „Przegląd Delivery Leada”:
      - otwarcie przeglądu osoby z „QC CV” (odczyt `/api/dl-review/context`);
      - wysyłka do klienta ze stawką (ocena kwot, niżej);
      - „Wróć do poprawy” z zaznaczonymi polami (`fix_fields`; bez pól nie
        zalicza);
      - terminy od klienta (od 16.11.2026, sekcja wyżej).

    Bez „Biorę” (DL bez roli rekrutera go nie ma) i bez screeningu: DL omija
    bramki pól (`dl-przesuwa-bez-blokad.md`);
  - TCM (13 ćwiczeń): wspólne moduły, lista i zapisane wyszukiwanie.

  DL z dodatkową rolą rekrutera przechodzi sumę ścieżek.
- **Treść mówi z perspektywy roli** (`primaryRole`). Rekruter oznacza w notatce
  Delivery Leada („Anna Poligonowa”), a DL i TCM rekrutera („Jakub
  Szkoleniowy”). Laurę z bazy rekruterowi poleca DL, a pozostałym rekruter.
- **Kwoty w ćwiczeniu wysyłki** liczy stała reguła. Kandydat chce 105 zł/h,
  a budżet rekrutacji wynosi do 115 zł/h. Stawka do klienta (zł/h, dzień ÷ 8,
  miesiąc ÷ 168):
  - ponad budżet nie zalicza;
  - równa stawce kandydata albo niższa (brak marży) nie zalicza;
  - w innej walucie niż PLN albo bez stawki nie zalicza.

  Każda informacja zwrotna każe cofnąć kartę na „QC CV” i wysłać jeszcze raz.
- **Serwer liczy tylko ćwiczenia roli osoby:**
  - `poligon_status` liczy wymagane ćwiczenia, a `GET /api/novelties/start`
    zwraca je jako `poligon.exercise_ids`. Mapa i okno ćwiczenia idą po tej
    liście (`usePoligonPath`). Zaliczony screening rekrutera nie przybliża
    DL-a do końca;
  - `POST /api/novelties/poligon-…/events` z ćwiczeniem spoza ścieżki osoby
    (np. TCM i przegląd DL) zwraca 404;
  - `replaces` jest mapą rola → przeklikania Startu. Osobie zastępuje sumę dla
    jej ról z `required_roles`.
- **Kopia bramki „Zweryfikowany” w `store.ts`** działa tylko przy wejściu
  z „Nowych” i „Screeningu”, jak `assert_verified_requirements` na serwerze.
  Zwrot z „QC CV” do poprawy jej nie przechodzi.

## Jak działa tryb

- **Tryb w przeglądarce, nie osobna baza.** `sessionStorage["nexus.poligon"]`
  włącza w `lib/api.ts` adapter `lib/poligon/adapter.ts`.
  - Zestaw `lib/poligon/dataset.json` podaje:
    - odczyty o rekrutacji ćwiczebnej (identyfikatory 990000+);
    - `/api/jobs`;
    - bazę kandydatów (`/api/candidates` = 14 osób ćwiczebnych);
    - „Moi ludzie”;
    - listę do „@” (trenerzy poligonu).
  - Pozostałe odczyty, np. pasek górny, idą do API.
  - **Jedyny zapis, który wychodzi z przeglądarki, to zaliczone ćwiczenie**
    (`POLIGON_PROGRESS` w `store.ts`).
  - Ruch karty, „Biorę”, notatka, screening (`PUT /api/screening-form`)
    i przypisanie z profilu zmieniają tylko stan w pamięci. Reszta dostaje 409
    z komunikatem.
- **Bramka „Zweryfikowany” jest w `store.ts`**: ten sam zestaw braków co serwer
  (arkusz, lokalizacja, tryb pracy, „Dlaczego ten kandydat”). Liczy go
  i okno „Przesuń dalej” (`move-requirements`), i odmowa 409
  `VERIFIED_REQUIREMENTS_MISSING`. Zmiana reguły na serwerze
  (`pipeline_move_rules.py`) = przegląd tej kopii.
- **Ćwiczenia** zalicza zdarzenie, nigdy „Rozumiem”:
  - klik w kotwicę `data-tour`/`data-help`;
  - akcja na rekrutacji ćwiczebnej;
  - otwarcie ekranu (zdarzenie `view` z odczytu).

  Informacja zwrotna to stałe reguły, bez modelu AI.
- **Warstwa** `components/poligon/PoligonLayer.tsx`:
  - żółty pasek „Poligon” nad treścią;
  - okno ćwiczenia w lewym dolnym rogu, które da się zwinąć; nie zasłania
    panelu osoby po prawej.

  W trybie poligonu `NoveltyLayer` milczy, a `useStartGate` nie blokuje.

## Zestaw danych

- Buduje go `backend/scripts/build_poligon_dataset.py` z nagrania na stagingu
  z laptopa, zrobionego kontem rekrutera. Nagranie obejmuje:
  - listę rekrutacji;
  - Tablicę;
  - panel osoby ze wszystkimi zakładkami, w tym „Screening”;
  - pasek źródeł;
  - „Moi ludzie”;
  - bazę kandydatów;
  - profil i okno przypisania.

  Od 16.11.2026 nagranie dogrywa fazy z `ADD_ONLY_PHASES` (`rec4`: okno
  wyboru terminu, odczyty edytora CV zapytaniami API, czat, zapisane
  wyszukiwania, listy, CV z pliku). Dogranie tylko dokłada adresy, których
  nie ma, i uczy filtr nazw wyłącznie z odpowiedzi, które wchodzą do zestawu.
  Odczyty edytora nagrane na etapie innej osoby z CV firmowym (`--cv-stage`,
  `--cv-candidate`) trafiają pod osobę-szablon. Odznaka „Wybierz termin”,
  podpowiedzi prepów, „Praca w tle” i „Historia requestów” są wymyślone
  (nagrane mają nazwiska organizatorów i prawdziwe rekrutacje).

  Od 15.11.2026 nagranie ma też fazy `dl-review*` z konta Delivery Leada:
  przegląd jednej osoby z „QC CV” innej rekrutacji (ten sam szablon etapów).
  Skrypt kładzie je pod osobę-szablon (`--dl-job`, `--dl-client`,
  `--dl-candidate`, `--dl-stage`). Odpowiedź, którą ma już nagranie rekrutera,
  zostaje z nagrania rekrutera. Kolumna „QC CV” dostaje dwie karty z „CV
  wysłane” nagranej rekrutacji (QC zdane). Kontekst przeglądu (wymagania,
  ocena, punkty odniesienia, pola do poprawy) jest wymyślony (`dl_context`),
  a „Pasuje też do” jest puste.

  Nagranie ma prawdziwe dane i zostaje w scratchpadzie sesji, nigdy w repo.
- Repo jest publiczne. Skrypt zamienia:
  - osoby na wymyślone (`PEOPLE`, trenerzy „Anna Poligonowa”,
    „Jakub Szkoleniowy”);
  - firmę na „Bank Północny”;
  - CV osoby na CV ćwiczebne;
  - identyfikatory na zakres 990000+;
  - daty na względne (`@rel:-3.2`);
  - kwoty (stawki, budżety, marże) na wymyślone: kandydat 105 zł/h, budżet
    do 115 zł/h (`money_value`). Stawki osób i marże klientów to tajemnica
    firmy.

  Tekst spoza `safe-keys.json` znika, a tekst spod tych kluczy przechodzi przez
  filtr prawdziwych imion, nazwisk i firm z nagrania. Gdy ekran nie znosi
  `null`, wycięty tekst zastępuje stała `REQUIRED_TEXT` (np. pytanie
  screeningowe z nazwą klienta). Pozycję listy bez nazwy skrypt usuwa
  (`prune_dropped`).
- **Strażnik** `lib/poligon/__tests__/poligon-dataset.test.ts` pilnuje, że
  w zestawie nie ma:
  - e-maili;
  - telefonów;
  - adresów WWW;
  - tekstów spoza dozwolonych kluczy.

  Nowy klucz do `safe-keys.json` dopisujesz tylko dla etykiet interfejsu
  i treści rekrutacji, nigdy dla notatek, CV ani osób.
- **Ekran zmienił się od nagrania:** adapter pisze w konsoli
  `[poligon] brak odpowiedzi w zestawie: <adres>`. Wtedy nagraj ekran jeszcze raz
  i przebuduj zestaw (opis wywołania w nagłówku skryptu). Przed commitem
  przejrzyj `--report` i przejdź całą ścieżkę w przeglądarce.
- **Test całej ścieżki w CI** (`frontend/e2e/poligon-walk.spec.ts`, projekt
  `poligon-chromium`, od 15.11.2026). W kolejce merge'ów po buildzie frontendu
  przechodzi ścieżkę rekrutera (27 ćwiczeń), Delivery Leada (17) i TCM (13)
  na podstawionym backendzie (bez bazy). Pada na każdy brak
  w zestawie, zapis poza postępem `poligon-*` i błąd strony, bo taki brak blokuje
  nową osobę na cały dzień. Odczyt, na który serwer odpowiada 404 (np.
  rekrutacja bez migawki rekomendacji), zapisuje się w zestawie jako
  `{"@status": 404}`, nie jako brak. Powłoka (pasek, powiadomienia) dostaje 404,
  poza szablonem etapów z `e2e/fixtures/poligon-shell.json`. Nowe ćwiczenie
  dopisujesz też do tego testu.
- Stan poligonu żyje w pamięci karty: przeładowanie strony cofa ruchy,
  notatki i screening z ćwiczeń (postęp ćwiczeń zostaje).
- Nowe ćwiczenie dopisujesz w czterech miejscach:
  - `exercises.ts`;
  - `poligon.json` (to samo id z przedrostkiem `poligon-`);
  - test oceny w `store.test.ts`;
  - krok w `e2e/poligon-walk.spec.ts`.

## Awaria 24.11.2026: osoby z lukami nie mogły skończyć Poligonu

Dzień po terminie kampanii „tylko luki” Poligon zablokował rekruterów i nikt
nie mógł go skończyć; Artur wyłączył porcję i blokadę (`poligon_gate`,
`novelty_daily_gate`). Trzy przyczyny, każda z testem w `e2e/poligon-walk.spec.ts`
(„rekruter z lukami…”):

- **Zaliczenie gubiło ćwiczenia z serwera.** `PoligonLayer.complete` brał
  stan z `markDone`, który zwraca tylko pamięć przeglądarki, więc po pierwszej
  luce „Dalej” cofało do ćwiczenia 1 z 27. Stan okna rośnie teraz od
  poprzedniego (serwer + przeglądarka).
- **Ćwiczenie „zajrzyj” nie może wisieć na zapytaniu ekranu.** „Zajrzyj do CV
  dla klienta” czekało na `…/cv/branded/sources`, o które karta „CV do klienta”
  pyta tylko u części osób. Takie ćwiczenia zalicza widoczna kotwica
  (`doneWhenVisible`). Treść ćwiczenia ma prowadzić tam, gdzie element jest:
  panel osoby ze „Zweryfikowanego” nie ma zakładek, dopóki nie „Rozwiń”.
- **Okno ćwiczenia jest nad oknami ekranu** (`z-[121]`, jak karta lekcji
  nowości), a klik w nie nie zamyka okna Radix. Edytor CV (`z-[110]`) zasłaniał
  „Zaliczone → Dalej”; ludzie klikali „Gotowe” i dostawali odmowę zapisu
  poligonu. Test E2E zamykał wtedy edytor przed „Dalej” — obejście w teście
  zamiast poprawki. Nie zamykaj w teście tego, co zasłania okno ćwiczenia.
- Testy przechodziły wcześniej tylko ścieżkę nowej osoby od zera. Zmiana
  w Poligonie albo w kampanii luk = także bieg „rekruter z lukami”.

## Drobiazgi z testu 24.11.2026 (Poligon z lukami i poranna porcja)

- **Zdanie o statystykach tylko dla nowej osoby.** Koniec Poligonu pisze „dziś
  nie liczy się do Twoich statystyk” tylko przy `poligon.required` bez
  `poligon.luki` (dzień onboardingu z `onboarding_day`). Serwer daje `luki`
  wyłącznie osobie bez wymogu onboardingu, a dzień ćwiczeń z luk się liczy
  (sekcja „Poligon dla obecnych”). E2E sprawdza oba końce.
- **Podgląd pliku na Poligonie = komunikat Poligonu.** `FilePreviewContent`
  w trybie Poligonu nie pobiera bajtów (szłyby do API z identyfikatorem
  990000+) i nie pisze „format nieobsługiwany, pobierz plik”, tylko to samo co
  „CV firmowe”: „Na poligonie podgląd tego pliku nie działa…”
  (`POLIGON_FILE_MESSAGE` w `lib/authenticated-files.ts`). Zgłoszenie Marka:
  „CV oryginalne” osoby ćwiczebnej (kopia ze zgłoszenia bez nazwy pliku).
- **Pole, które ekran wstawia w zdanie, nie może zostać `null`.** Filtr
  nagrania zostawia `null` w miejscu wyciętego tekstu, a profil pisał „null ·
  poziom nieznany” (języki), arkusz rozmowy „„null”” (wcześniejsza odpowiedź).
  Takie pola dostają wymyśloną treść w `scripts/poligon_person_texts.py`
  (`--practice-only`, odpowiedzi w `meta.fiction_responses`); odpowiedzi są bez
  rodzaju gramatycznego, bo odczyt osoby-szablonu dostaje każda osoba.
  Strażnik `poligon-dataset.test.ts` sprawdza te pola, a E2E przed każdym
  „Dalej” szuka napisu „null” na ekranie (`noNullText`).
- **Pokaz lekcji i okna:** start pokazu w miejscu elementu i karta, która nie
  zamyka okna Radix — `nowosci-do-przeklikania.md`.
