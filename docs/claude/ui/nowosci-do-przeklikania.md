# Nowości do przeklikania zamiast artefaktu „co nowego”
<!-- indeks: rejestr `app/data/novelties/novelties.json`, poranna porcja `/nowosci-dnia` na Poligonie (18.11.2026), bez kropek i okien w ciągu dnia, panel admin + HoR, `novelty_progress` (0625) -->

Decyzja Artura z 28.10.2026 (makiety: https://claude.ai/artifact/Qmy51h287jZy4r9oCaA1i4).
Ludzie nie czytali artefaktów „co nowego” ani dymków: w 30 dni do 27.10
Jarvis pokazał 478 dymków 46 osobom, a przewodnik ekranu otworzyła jedna.
Nowość ma więc wejść w drogę pracy i zaliczać się z pracy.

- **Każda nowość, którą ludzie mają zauważyć, to wpis w
  `backend/app/data/novelties/novelties.json`** w PR-ze, który ją wdraża.
  Ten wpis zastępuje artefakt „co nowego” i ręczne „daj znać”. Treść jest dla
  użytkownika: bez tras, nazw tabel i numerów zgłoszeń w `why`.
- **Pilnuje tego strażnik w sicie (30.10.2026)**, krok „Nowości — wpis przy
  nowej funkcji” w wymaganym jobie „Backend (lint + migrations)”
  (`.github/scripts/novelty_guard.py`). PR z tytułem `feat…`, który zmienia
  `frontend/src` (poza testami i `/preview`), dopisuje wpis albo ma w opisie
  osobną linię `Nowość: nie — <powód>`. Powód: od 26 do 29.10 na main weszło
  ok. 90 commitów `feat`, a rejestr miał trzy wpisy. Opis strażnik czyta
  z API, więc po dopisaniu linii wystarczy ponowić job.
- **Poranna porcja zamiast kropek i okien (decyzja Artura z 18.11.2026).**
  Przy pierwszym wejściu dnia `useDailyNoveltyGate` przekierowuje na
  `/nowosci-dnia`: wszystko, co weszło do roli osoby od `DAILY_FLOOR` do
  wczoraj i czego jeszcze nie przeszła (`GET /api/novelties/daily`). Potem do
  jutra nic nie wyskakuje: bez kropek, kart „Przeklikaj” i okien na ekranach.
  Dzisiejsze nowości czekają do jutra, więc porcja nie rośnie w ciągu dnia.
  Porcja nie ma limitu, także po urlopie. Pierwsza porcja to nowości z 7 dni
  przed jej wdrożeniem (`DAILY_FLOOR` = 12.11.2026); starszych nikt nie nadrabia.
  Powód: od 28.10 do 18.11 weszło 185 wpisów (ok. 9 na dzień roboczy), osoba
  miała średnio 46 nieprzeklikanych, a 700 z 939 zaliczeń to przypadkowe
  pierwsze kliknięcie kropki w pracy, nie nauka.
- **Przeklikanie idzie na Poligonie.** Pozycja porcji włącza tryb ćwiczebny
  na tej karcie (`enterPoligon(…, "novelty")`): prawdziwe ekrany, rekrutacja
  ćwiczebna, zapisy wyłączone, więc kroki mogą klikać naprawdę. Na serwer
  wychodzi tylko zaliczenie (`toured`). Po ostatnim kroku albo „Przerwij” karta
  wraca na `/nowosci-dnia`. Drobiazg bez kroków dostaje jeden krok „Rozumiem”
  na `dot_anchor`.
- **Każdy wpis prowadzi do swojego elementu.** Gdy `href` to tylko lista,
  a element stoi głębiej (Tablica, CV, Profil Championa), wpis ma
  `practice_href` — ekran na rekrutacji ćwiczebnej `/jobs/990001` — albo kroki,
  które tam prowadzą. Brakujący element kończy się komunikatem „Nie widzę tego
  miejsca” i po 2 s „Nie mam tego — dalej”: porcja nikogo nie zatrzyma, ale
  taki wpis niczego nie uczy. Kroki do wpisów z dnia pisze i sprawdza nocna
  rutyna Strażnik Nowości. Od 22.11.2026 Poligon ma też klienta ćwiczebnego
  (`/clients/990501`), kontrakty (`/contracts`, 990521 i 990522) i Finanse
  (`/finance?view=rate-divergences`) — wpis z tych ekranów prowadzi tam
  (`poligon-nexusa-onboarding.md`, sekcja „Klient ćwiczebny”).
- **Wyłączniki na `/settings/nowosci`** (admin i HoR) są trzy i niezależne:
  porcja (`novelty_daily_gate`), Start (`start_gate`) i Poligon nowych osób
  (`poligon_gate`). Start jest wyłączony od 30.10, dlatego porcja ma własny.
  Stack E2E ma wszystkie trzy wyłączone w `seed_e2e.py`. Dopóki osoba nie
  skończy Startu (`start-w-nexusie.md`), porcja czeka.
- **Każdy przeklikuje tylko to, do czego ma dostęp:** `audience` (rola albo
  uprawnienie z faktycznej bramki ekranu) i `section` — sekcja ekranu z
  middleware (`/jobs` → pipeline, `/candidates` → sourcing, `/contracts` →
  delivery, `/finance` → finance, `/insights` → insights). Bez odczytu w tej
  sekcji osoba nie dostaje nowości ani okna. Test pilnuje, że wpis na ekranie
  z sekcją ma `section`. Audyt 30.10 na kopii produkcji: 38 osób, 0 pozycji
  bez dostępu.
- **Poziom (`tier`) mówi, jak duża jest zmiana:** `dot` (drobiazg, kroki
  opcjonalne), `tour` (nowa funkcja, co najmniej 2 kroki), `process` (zmiana
  sposobu pracy, `path_prefix` ekranu). Każdy poziom trafia do porcji. Nie
  dopisuj wpisu przy poprawce, której nikt nie musi się uczyć: każdy wpis to
  kilkadziesiąt sekund porannej porcji u każdej osoby z roli.
- **Klik liczy się po elemencie z `pointerdown`** (`onEveryClick` w
  `lib/novelties/logic.ts`), bo menu Radix (DropdownMenu, Select) kieruje
  `click` na `<html>` (14.11.2026: „Zmień plik” przez 10 dni nie zaliczył się
  nikomu).
- **Zaliczenie = przeklikanie (`toured`).** Przycisku „Przeczytałem” nie ma
  i nie dokładamy go. Kropek i zaliczenia z pracy (`used`, `dot_clicked`) front
  od 18.11.2026 nie wysyła; API je przyjmuje, a panel pokazuje stare zaliczenia.
- **Kroki chodzą po kotwicach `data-tour="<id>"`** na prawdziwych elementach.
  Krok przechodzi po kliknięciu kotwicy, nie po „Dalej”. Krok, którego nie
  wolno wykonać naprawdę (zapis zakończenia kontraktu), ma `ack: true`
  i przechodzi przyciskiem „Rozumiem”. Kotwica bez elementu we froncie
  oznacza czerwony test frontu.
- **Podświetlenie to prawdziwy, widoczny element (zgłoszenie Artura, 02.11.2026).**
  Pozycję mierzymy na żywo, nigdy ze zrzutu ani ze stałych pikseli. Sam rozmiar
  elementu nie wystarcza, bo ludzie mają różne okna: przy 1280 × 650 krok bywał
  poza ekranem, a przy otwartym panelu wycięcie świeciło na puste pole. Dlatego
  krok raz przewija do elementu, wycięcie obejmuje tylko widoczną część, z wielu
  elementów bierze widoczny, a element pod panelem nie dostaje podświetlenia,
  tylko komunikat. Pomiar na stagingu robi nocny Tester.
- **Odbiorcy:** `audience.roles` albo `audience.permissions` (wystarczy jedno,
  pusto = wszyscy). Przycisk widoczny dla uprawnienia opisujesz uprawnieniem.
  W archiwum ✦ nowość żyje 45 dni (`active_days`), w panelu do 90 dni,
  a w porcji, dopóki osoba jej nie przejdzie.
- **Panel „Nowości — kto już umie” (`GET /api/novelties/adoption`)** widzą
  tylko admin i Head of Recruitment (`HeadOfRecruitmentPlus`), bo pokazuje
  imiennie, kto jeszcze nie umie. „Przypomnij” nie wysyła maila; od 18.11.2026
  nic nie zmienia na ekranie osoby, bo niezaliczona nowość i tak czeka w porcji.
- **W trybie podglądu jako inna osoba** porcja nie blokuje, a zdarzenia się
  nie zapisują.
- **Schemat:** `novelty_progress` (0625), DDL w `app/services/novelty_schema.py`,
  lustro w `entrypoint.sh`, sonda w `/api/health/deep`.
