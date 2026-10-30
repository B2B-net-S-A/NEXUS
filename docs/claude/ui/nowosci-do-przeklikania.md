# Nowości do przeklikania zamiast artefaktu „co nowego”
<!-- indeks: rejestr `app/data/novelties/novelties.json`, trzy poziomy (dot/tour/process), zaliczenie z pracy, panel admin + HoR, `novelty_progress` (0625) -->

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
- **Każdą nowość do przeklikania trzeba przejść (decyzja Artura z 30.10.2026).**
  `tour` i `process` mają okno na swoim ekranie (`path_prefix`, a bez niego
  `href`); odłożyć można raz, do 8:00 następnego dnia. Najwyżej jedno okno na
  wejście na ekran; po „Przerwij” albo odłożeniu okno wraca dopiero po
  ponownym wejściu. Krok bez elementu na ekranie przez 2 s ma „Nie mam tego —
  dalej” — okno nie może nikogo zablokować. Dopóki osoba nie skończy Startu
  (`start-w-nexusie.md`), okna nowości milczą. Wyłącznik Startu na
  `/settings/nowosci` zdejmuje też obowiązek z nowości (zostaje okno zmiany
  procesu); stack E2E ma go wyłączonego w `seed_e2e.py`.
- **Każdy przeklikuje tylko to, do czego ma dostęp:** `audience` (rola albo
  uprawnienie z faktycznej bramki ekranu) i `section` — sekcja ekranu z
  middleware (`/jobs` → pipeline, `/candidates` → sourcing, `/contracts` →
  delivery, `/finance` → finance, `/insights` → insights). Bez odczytu w tej
  sekcji osoba nie dostaje nowości ani okna. Test pilnuje, że wpis na ekranie
  z sekcją ma `section`. Audyt 30.10 na kopii produkcji: 38 osób, 0 pozycji
  bez dostępu.
- **Poziom (`tier`) decyduje, jak mocno nowość wchodzi w drogę:**
  `dot` (drobiazg) to sama kropka na elemencie, zaliczona pierwszym kliknięciem;
  `tour` (nowa funkcja) to kropka i karta „Przeklikaj” z krokami;
  `process` (zmiana procesu, czyli coś, co trzeba teraz robić inaczej) to okno
  przy pierwszym wejściu na `path_prefix`, które można odłożyć raz, do 8:00
  następnego dnia. Nie podnoś poziomu „na wszelki wypadek”: okno przy każdej
  nowości nauczy ludzi klikać „dalej” na ślepo.
- **Zaliczenie = przeklikanie (`tour`) albo użycie w pracy (`used`, klik
  w `used_anchor` poza przeklikaniem)**. Przycisku „Przeczytałem” nie ma
  i nie dokładamy go. Demo wideo odrzucone 28.10.
- **Kroki chodzą po kotwicach `data-tour="<id>"`** na prawdziwych elementach.
  Krok przechodzi po kliknięciu kotwicy, nie po „Dalej”. Krok, którego nie
  wolno wykonać naprawdę (zapis zakończenia kontraktu), ma `ack: true`
  i przechodzi przyciskiem „Rozumiem”. Kotwica bez elementu we froncie
  oznacza czerwony test frontu.
- **Odbiorcy:** `audience.roles` albo `audience.permissions` (wystarczy jedno,
  pusto = wszyscy). Przycisk widoczny dla uprawnienia opisujesz uprawnieniem.
  Nowość żyje 45 dni (`active_days`), a panel pokazuje ją do 90 dni.
- **Panel „Nowości — kto już umie” (`GET /api/novelties/adoption`)** widzą
  tylko admin i Head of Recruitment (`HeadOfRecruitmentPlus`), bo pokazuje
  imiennie, kto jeszcze nie umie. „Przypomnij” przywraca kartę przy kropce
  i nie wysyła maila.
- **Karta przy kropce wchodzi do wspólnego budżetu dymków (3 dziennie,
  `lib/jarvis/bubble-budget.ts`)**. Nie dokładaj osobnego źródła dymków.
  W trybie podglądu jako inna osoba zdarzenia się nie zapisują.
- **Schemat:** `novelty_progress` (0625), DDL w `app/services/novelty_schema.py`,
  lustro w `entrypoint.sh`, sonda w `/api/health/deep`.
