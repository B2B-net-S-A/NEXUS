# Start w NEXUSIE — obowiązkowe przeklikanie najważniejszych funkcji roli
<!-- indeks: rejestr `app/data/novelties/start.json`, twarda blokada `useStartGate` (tylko pulpit i `/start`), wyłącznik `app_settings.start_gate` w „Nowości — kto już umie”, kotwice `data-help` -->

Decyzja Artura z 30.10.2026: kto jest w NEXUSIE (nowa osoba i każdy obecny),
przeklikuje najważniejsze funkcje swojej roli, zanim wejdzie dalej niż pulpit.
Twarda blokada, wszyscy obowiązkowo. Nowa osoba bez przeklikania nie wiedziała,
gdzie co jest, a samo „zaproszenie” do przewodnika otwierała jedna osoba na 46
(`nowosci-do-przeklikania.md`).

- **Treść: `backend/app/data/novelties/start.json`**, ten sam kształt co
  nowość, ale tylko `tour` z id `start-…`, bez terminu ważności, bez kropki,
  karty i licznika ✦. Odbiorcy przez `audience.roles`. Dziś: rekrutacja
  (admin, HoR, DL, TCM, rekruter) — lista rekrutacji, Tablica, panel osoby,
  baza kandydatów; `finance` — kontrakty i Finanse; `employee` — Mój czas.
  Praktykant i Automatyzacje nie mają Startu, więc nic ich nie zatrzymuje.
- **Kroki chodzą po kotwicach `data-tour` albo `data-help`** (przewodniki
  Jarvisa). Wybieraj element widoczny od razu po wejściu na ekran — krok na
  elemencie, który pojawia się dopiero po kliknięciu (np. formularz
  screeningu), pokazuje „Nie widzę tego miejsca”. Krok bez elementu na
  ekranie da się minąć przyciskiem „Nie mam tego — dalej” (pusta tablica nie
  może nikogo zablokować na zawsze). Test kotwic czyta oba rejestry.
- **Blokada: `components/novelties/useStartGate.ts`** w `AppShellV2`. Dopóki
  `GET /api/novelties/start` mówi `enforced`, każdy ekran poza `/start`,
  `/` i `/dashboard`, `/login`, `/onboarding` i `/settings/nowosci`
  przekierowuje na `/start`. W trakcie przeklikania Startu wszystkie ekrany
  są otwarte (przeklikanie prowadzi z listy na Tablicę i do panelu). Awaria
  zapytania = brak blokady. Podgląd jako inna osoba niczego nie blokuje.
- **Wyłącznik: `PUT /api/novelties/start/gate`** (`HeadOfRecruitmentPlus`),
  wiersz `app_settings.start_gate`; brak wiersza = blokada włączona. Przycisk
  „Wyłącz blokadę” stoi na górze Ustawienia → „Nowości — kto już umie”. To
  zabezpieczenie na wypadek, gdyby przeklikanie kogoś zatrzymało — bez deployu.
- **Postęp** liczy się w `novelty_progress` jak nowości (przeklikanie albo
  użycie); panel „kto już umie” pokazuje pozycje Startu z plakietką „Start”.
- **Nowa funkcja, która zmienia podstawy pracy roli**, może dojść do Startu
  (wtedy zatrzyma też tych, którzy Start już mają) — to decyzja Artura,
  nie dopisuj jej sam. Zwykła nowość idzie do `novelties.json`.
