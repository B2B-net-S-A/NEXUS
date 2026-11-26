# Nowości do przeklikania zamiast artefaktu „co nowego”
<!-- indeks: rejestr `app/data/novelties/novelties.json`, lekcje `lessons.json` (pokaz → sam → pytanie, 23.11.2026), poranna porcja `/nowosci-dnia` na Poligonie, najwyżej 5 lekcji dziennie, odłóż do 15:00, admin pomija, piątek powtórka, Szkolenia → Nowości w NEXUSIE, panel admin + HoR, `novelty_progress` (0625), `novelty_lesson_progress` i `novelty_daily_state` (0760) -->

Decyzja Artura z 28.10.2026 (makiety: https://claude.ai/artifact/Qmy51h287jZy4r9oCaA1i4).
Ludzie nie czytali artefaktów „co nowego” ani dymków: w 30 dni do 27.10
Jarvis pokazał 478 dymków 46 osobom, a przewodnik ekranu otworzyła jedna.
Nowość ma więc wejść w drogę pracy i zaliczać się z pracy.

## Lekcje zamiast przeklikania (decyzje Artura z 23.11.2026)

Makiety: https://claude.ai/artifact/LDcWTSmpHXeTeRhQamp1cy. Przeklikanie nie
uczyło: od 19.11 mediana 12 s na nowość, 38% poniżej 10 s, 61% przeklikań to
sam „Rozumiem”, a kroki w stylu „Kliknij wiersz dowolnego kontraktu” nie
wymagały żadnej decyzji (Igor: „nikt się nie przykłada, tylko przeklikuje”).
Artur: „trzeba zmusić, żeby każdą zmianę zrozumieli i potrafili korzystać”.

- **Każdy wpis od 12.11.2026 należy do dokładnie jednej lekcji** w
  `backend/app/data/novelties/lessons.json` (test
  `test_every_novelty_since_the_floor_is_in_exactly_one_lesson`). Lekcja łączy
  wpisy jednej funkcji albo ekranu (1–6), ma zadanie samodzielne (`task`,
  `solo_href`), warunek zaliczenia (`check`) i 2–4 pytania po 3 odpowiedzi.
  Nowy wpis = nowa lekcja albo dopisek do istniejącej, w tym samym PR-ze.
- **Trzy etapy, wszystko na Poligonie:** (1) pokaz — dotychczasowe kroki
  wpisów z podświetleniem, wpis po wpisie (`NoveltyLayer`), pokaz niczego nie
  zalicza; (2) sam — to samo bez podświetlenia, na innych danych (`LessonLayer`);
  (3) pytanie „po co / kiedy”. Nie wyszło samemu („Pokaż jeszcze raz”) albo dwa
  razy źle z rzędu na pytanie → z powrotem do pokazu. Pokazów można oglądać,
  ile się chce. Lekcja zalicza się po etapie „sam” i dobrej odpowiedzi; serwer
  pilnuje kolejności (`apply_lesson_event`) i zalicza wtedy wpisy lekcji jako
  `tour`, więc panel i archiwum ✦ widzą to bez zmian.
- **Warunek `check`, deklaratywnie, bez kodu na lekcję:** `click` (kotwica
  `data-tour`/`data-help`, test frontu pilnuje, że istnieje), `move` (ruch karty
  na rekrutacji ćwiczebnej do etapu, opcjonalnie z powodem, z podpowiedzią przy
  złym ruchu) i `page` (dojście do ekranu; test pilnuje, że ekran startowy go
  nie spełnia). Pierwszy krok pokazu („kliknij wiersz”) nie jest dobrym warunkiem.
- **Jedna furtka:** element z zadania bywa ukryty dla części odbiorców (poziom
  „Generowanie”, sama edycja w Sprzedaży, brak kart w porcji). Po 45 s w etapie
  „sam” z warunkiem `click` pojawia się „Nie widzę tego u siebie — przejdź do
  pytania”; pytanie trzeba zaliczyć. Ta sama zasada co „Nie mam tego — dalej”:
  nikt nie może utknąć na zawsze (30.10.2026). Lepiej dobrać warunek, który
  zrobi cała grupa odbiorców.
- **Element z zadania nie może zależeć od prawdziwych danych osoby (25.11.2026).**
  Test wszystkich lekcji na stagingu (kopia produkcji, 6 ról, 1280 × 720)
  znalazł lekcje do zaliczenia tylko furtką: „Pracuj po kolei” (DL i TCM bez
  własnych kart), „Terminy przy ruchu” (pusta kolumna „CV wysłane”), „Zajęcia
  i spory” (plan przelewów to POST, Poligon odpowiadał 409), „Najważniejsze
  zadanie” (`null` w tekście wywracał „Edytuj”), „Musi mieć” (żadna karta nie
  miała listy ze schodkami). Dlatego: ekran, z którego zadanie korzysta, czyta
  na Poligonie odpowiedź z zestawu (`OWNED_PATHS` / `READ_POSTS` w
  `lib/poligon/store.ts`, moduł `backend/scripts/poligon_*_practice.py`), a nie
  dane osoby; kolumna, z której zadanie każe ruszyć kartę, ma osobę ćwiczebną.
  Od 26.11.2026 także Porcja: na produkcji „Oddaj do Nowych” zaliczały
  wyłącznie furtką (pusta porcja, brak rekrutacji niżej niż P0), więc
  `/api/review-batch/me`, `/me/queue` i `/me/focus` idą na Poligonie z zestawu
  (`poligon_review_batch_practice.py`: karty z „Nowych”, „Do domknięcia” ze
  „Screeningu”, P0 to druga rekrutacja ćwiczebna). Lekcja startuje od „Do decyzji”.
- **Pokaz prowadzi tą drogą, której wymaga zadanie.** Krok, który każe coś
  kliknąć albo przejść, nie jest `ack` (strażnik
  `test_step_that_says_click_is_not_passed_with_understood`); wpis bez kroków
  ma `practice_href` na ekranie z elementem (panel osoby `?candidate=`,
  `stSub=rules` w Rozliczeniach). Warunek `page` sprawdza adres także po
  zmianie samego query (zakładki robią `replaceState`) i dopiero na
  `solo_href` po przeładowaniu — pokaz kończący się na ekranie z warunku nie
  zalicza „sam”.
- **Etap „sam” przechodzi się drogą z pokazu — pilnuje tego CI (26.11.2026).**
  Na produkcji 26.11 „Wysyłkę do podpisu”, „Porcję: kartę”, „Arkusz rozmowy”,
  „CV do klienta” i „Karty bez śladu” zaliczało furtką 4–6 osób, „Oddaj do
  Nowych” 3 z 3, a Delivery Lead sześć razy w minutę wracał do pokazu i nie
  mógł pracować. Każda poprawka łatała jedną lekcję, a nowe wchodziły co dzień
  bez sprawdzenia etapu „sam”. Zasady:
  - `solo_href` = ekran, na którym pokaz wskazał element z zadania
    (`practice_href` tego wpisu). „Sam” u innej osoby albo na gołej Tablicy
    wymaga kroków, których pokaz nie pokazał (panel osoby, „Rozwiń”, zwinięta
    sekcja CV);
  - element z warunku `click` jest krokiem pokazu (choćby `ack`); droga do
    niego (zakładka „Do domknięcia”, „Edytuj CV”) też — wpis bez kroków
    dostaje kroki;
  - `e2e/lessons-solo.spec.ts` (projekt `poligon-chromium`, kolejka merge'ów)
    przechodzi każdą lekcję rekrutera i DL-a obiema rolami przy 1280 × 720:
    start na `solo_href`, kroki pokazu po kolei (widoczne, nie zasłonięte,
    nie wyłączone; wolno przewinąć, zwinąć kartę zadania i wpisać treść),
    potem element z zadania. Pada na lekcję, której tak nie da się przejść.
    `KNOWN_GAPS` w tym pliku to lekcje sprzed strażnika — lista tylko maleje
    (test pada na wpis, który już przechodzi), nowa lekcja na nią nie wchodzi.
  - furtka „Coś nie działa — zalicz i dalej” jest przyciskiem, a od drugiego
    powrotu do pokazu w przebiegu (`soloTries`) przyciskiem głównym karty z
    jednym zdaniem wyjaśnienia (`BrokenButton prominent`).
- **Najwyżej 5 lekcji dziennie** (Olaf: „nie chcę mieć z rana 40 funkcji, kiedy
  muszę wejść na daily”); reszta przechodzi na kolejne dni, nic nie przepada.
  Zaliczenie lekcji nie wciąga następnej tego samego dnia. To zastępuje „porcja
  nie ma limitu” z 18.11.
- **„Odłóż na później”:** raz dziennie, za 30 min, na 12:00 albo na 15:00 —
  najpóźniej 15:00. O tej godzinie porcja wraca jak rano. Kto odłożył w ostatni
  dzień z porcją (do 4 dni wstecz), ten dziś nie odkłada.
- **Admin może pominąć dzień** („Pomiń na dziś”, `POST /novelties/daily/skip`,
  tylko rola admin). Pominięcie niczego nie zalicza; lekcje czekają w porcji
  i w Szkoleniach. Innym rolom „Pomiń” się nie pokazuje.
- **Piątek: powtórka** — 3 lekcje zaliczone od poniedziałku, od razu etap „sam”
  bez pytania, w limicie 5. Nieudana wraca jako lekcja od pokazu.
- **Wpisy przeklikane przed 23.11** zaliczają lekcję, gdy osoba przeszła
  wszystkie jej wpisy (`legacy_done`) — nikt nie robi drugi raz tego, co już
  przeklikał. Lekcja z częścią nowych wpisów idzie normalnie.
- **Szkolenia → „Nowości w NEXUSIE”** (pomysł Igora): wszystkie lekcje z roli
  osoby, po miejscu w NEXUSIE, z wyszukiwarką; „Powtórz na Poligonie” idzie tym
  samym przebiegiem, nigdy na prawdziwych danych.
- **HoR widzi, kto utknął:** „Utknęli w lekcjach nowości” w Ustawienia →
  Nowości — 3 i więcej nieudanych prób „sam” bez zaliczenia
  (`GET /novelties/lessons/struggles`, admin i HoR).
- **W porcji bez słowa „praca”** (Olaf): „zmiany w NEXUSIE”, „Dalej do NEXUSA”.

## Rejestr wpisów i reszta zasad

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
  Od 23.11.2026 porcja to lekcje z limitem 5 dziennie (sekcja wyżej). Pierwsza porcja to nowości z 7 dni
  przed jej wdrożeniem (`DAILY_FLOOR` = 12.11.2026); starszych nikt nie nadrabia.
  Powód: od 28.10 do 18.11 weszło 185 wpisów (ok. 9 na dzień roboczy), osoba
  miała średnio 46 nieprzeklikanych, a 700 z 939 zaliczeń to przypadkowe
  pierwsze kliknięcie kropki w pracy, nie nauka.
- **Wpis sprzed `DAILY_FLOOR` bez postępu to stan końcowy, nie błąd
  (24.11.2026).** Od 18.11 front nie wysyła `seen` ani `dot_clicked`, a porcja
  i lekcje biorą tylko wpisy od 12.11. Starszy wpis mógł więc dostać wiersz
  w `novelty_progress` tylko w czasie kropek (od wdrożenia wpisu do 18.11),
  gdy jego `dot_anchor` stanął na ekranie osoby z odbiorców. Kopia produkcji
  z 24.11: z 118 wpisów `dot` sprzed 12.11 dziesięć nie ma żadnego wiersza,
  a przy reszcie ostatni zapis jest z 18.11. Wszystkie 47 wpisów `dot`
  z 12–17.11 mają postęp z porcji. Zero tych dziesięciu ma trzy przyczyny:
  element nie miał się z czym pokazać (żadnego ogłoszenia, wysyłki do
  e-podpisu ani dokumentu do startu, a QC w stanie „sprawdź ręcznie” trafił
  się osobie dopiero 20.11); odbiorcami były 2 osoby, które tam nie zajrzały
  (automat przydziału, słownik, mapa decyzyjna w szansie, jakość podpowiedzi);
  albo element stał niżej niż pierwszy ekran (licznik P1 na Daily pod
  „Zmianami od wczoraj”). Dlatego odstających pozycji szukaj tylko wśród
  wpisów od `DAILY_FLOOR`. Zero przy starszym wpisie nie jest sprawą, a nauka
  takiej funkcji to nowa lekcja wyłącznie na decyzję Artura, bo starszych
  nikt nie nadrabia.
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
  Pokaz lekcji też startuje z `practice_href ?? href`: wpis z lekcji, który
  zaczyna na liście `/jobs`, może mieć pierwszy krok tylko na kotwicy listy
  (`jobs.list.*`), reszta potrzebuje `practice_href` (test
  `test_lesson_show_starts_where_its_first_step_is_not_on_the_jobs_list`;
  24.11.2026 pokaz „Arkusz rozmowy” zaczynał na liście). Panel osoby od razu
  rozwinięty na screeningu otwiera `?candidate=<id>&panel=screening`.
  Ta sama zasada obejmuje każdy wpis, bo powtórka z archiwum ✦ też startuje
  z `practice_href ?? href` (test
  `test_practice_starts_where_the_first_step_is_not_on_the_jobs_list`;
  24.11.2026 56 wpisów zaczynało na liście). Wyjątek jest tylko dla wpisu,
  którego elementu na Poligonie nie ma, bo zestaw nie ma danych, przy których
  się pokazuje (ogłoszenie, aplikacje, QC z błędem, podpis elektroniczny):
  `JOBS_LIST_START_EXCEPTIONS` z powodem. Ekran dobierasz pomiarem na
  stagingu z Poligonem, nie z kodu: zakładki Profilu Championa to
  `?tab=champion&ptab=client|team`, notatki osoby `&panel=notes`, karta
  „CV do klienta” `&panel=cv`, przegląd Delivery Leada `&review=1`.
  Element w oknie (odrzucenie, edytor CV) ma ekran z przyciskiem, który
  to okno otwiera.
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
- **Zaliczenie = lekcja (od 23.11.2026; wcześniej przeklikanie `toured`).**
  Przycisku „Przeczytałem” ani „Pomiń” (poza adminem) nie ma i nie dokładamy go. Kropek i zaliczenia z pracy (`used`, `dot_clicked`) front
  od 18.11.2026 nie wysyła; API je przyjmuje, a panel pokazuje stare zaliczenia.
- **Kroki chodzą po kotwicach `data-tour="<id>"`** na prawdziwych elementach.
  Krok przechodzi po kliknięciu kotwicy, nie po „Dalej”. Krok, którego nie
  wolno wykonać naprawdę (zapis zakończenia kontraktu), ma `ack: true`
  i przechodzi przyciskiem „Rozumiem”. Kotwica bez elementu we froncie
  oznacza czerwony test frontu.
- **Karta nad otwartym oknem Radix.** Radix zamyka okno po kliknięciu poza
  nim, a karta kroku leży poza oknem. „Rozumiem” w oknie zamyka je bez zapisu,
  chyba że następny krok stoi w tym samym oknie: wtedy okno zostaje
  (`nextStepInSameDialog` w `lib/novelties/logic.ts`; 24.11.2026 „Rozumiem”
  przy polu treści zamykało „Co zmienił klient?” i krok „Przygotuj zmiany”
  nie miał czego wskazać). Karta lekcji („teraz sam”, pytanie) i okno
  ćwiczenia Poligonu nie zamykają okna nigdy (`keepDialogsOpen`).
- **Podświetlenie to prawdziwy, widoczny element (zgłoszenie Artura, 02.11.2026).**
  Pozycję mierzymy na żywo, nigdy ze zrzutu ani ze stałych pikseli. Sam rozmiar
  elementu nie wystarcza, bo ludzie mają różne okna: przy 1280 × 650 krok bywał
  poza ekranem, a przy otwartym panelu wycięcie świeciło na puste pole. Dlatego
  krok raz przewija do elementu, wycięcie obejmuje tylko widoczną część, z wielu
  elementów bierze widoczny, a element pod panelem nie dostaje podświetlenia,
  tylko komunikat. Pomiar na stagingu robi nocny Tester.
- **Kotwica na plakietce karty Tablicy stoi też na `card-low-state` (24.11.2026).**
  Przy oknie niższym niż 800 px wiersz plakietek ma `low-screen:hidden`, a widać
  tylko skrócony stan karty dwuliniowej. Lekcja „Karta zatrzymana do podpisu
  przedwstępnej” na laptopie 1280 × 720 nie widziała kotwicy i kończyła się tylko
  wyjściem po 45 s (PR #3856). Ta sama `data-tour` idzie na oba warianty, w linii
  z `data-tour` (strażnik `novelty-anchors.test.ts`), a lekcję przeklikujesz
  przy 1280 × 720 i przy wysokości ≥ 800 px.
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
- **Schemat:** `novelty_progress` (0625) oraz `novelty_lesson_progress`
  i `novelty_daily_state` (0760), DDL w `app/services/novelty_schema.py`
  (`TABLE_DDL`, `LESSON_DDL`), lustro w `entrypoint.sh`, sonda w `/api/health/deep`.
