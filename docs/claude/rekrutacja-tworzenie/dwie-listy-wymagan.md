# Dwie listy wymagań (13.10.2026)

Słowa do szukania i „Rekruter sprawdza w rozmowie” — wariant A.

Decyzja Artura 13.10.2026 (D1–D6, makiety https://claude.ai/artifact/8qx5WrueDSLHht7VezW2L5).
Pomiar na produkcji: 30% pozycji „musi mieć” w 206 opublikowanych rekrutacjach to zdania,
kategorie, branże, języki, role i umiejętności miękkie. Wyszukiwanie szuka słów dosłownie
(„doświadczenie w przetargach” ma w CV 1 osoba z 65 924, „przetarg*” — 727), w propozycjach AI
takie pozycje miały „? brak potwierdzenia” w 95–100% przypadków, a jako krytyczne ukrywały
prawie wszystkich (789128: „architektura chmury” → 0 osób w „Szukaj w bazie”).

- **Dwie listy (D1).** „Szukamy po tych słowach” = wiersze wymagań (`stack.rows`).
  „Rekruter sprawdza w rozmowie” = sekcja 4 Championa `experience` z nowym rodzajem `skills`
  („Doświadczenie i umiejętności”: zdania, poziom, miękkie) obok dziedzin, certyfikatów
  i regulacji; język pracy zostaje w `basics.language` (jedno źródło — nie dokładaj rodzaju
  „język”). Lista nie filtruje kandydatów: w formularzu screeningu każda pozycja jest punktem
  „Sprawdź w rozmowie” (`ExperienceCheck`, rodzaj `skills` znają schemat, arkusz i odpowiedź
  profilu kandydata). `experience.skills` NIE ma plakietki „ślad w CV” (`experience_evidence`
  zostaje przy trzech rodzajach) i NIE wchodzi do `champion_view.requirement_source` — edycja
  listy nie kasuje kontraktu wymagań ani nie odpala przeliczeń.
  - Zdania z listy dalej czytają: generator CV (dokłada je do must/nice promptu), strona kariery
    i ogłoszenie na portale (`job_public_profile._stack_names`), przegląd DL, brief „po ludzku”
    i tekst wektora rekrutacji (tylko gdy lista jest — tekst bez niej bajt w bajt jak dotąd).
- **Czytanie frazy** (`services/requirement_phrase.read_phrase`, bez bazy): `technology` /
  `keyword` / `prose` / `soft` / `language` / `domain` / `category` / `role` / `city`, słowo do
  szukania (`keyword`), komentarz z nawiasu, dokąd idzie do rozmowy i podpowiedzi słów (technologie
  ze zdania, rdzeń z gwiazdką, odpowiedniki z `keyword_equivalents.json` — grupa przetargów:
  przetarg*, PZP, SIWZ, SWZ, OPZ, tender*). Decyzji wymagają `prose`, `soft`, `language`
  i branża opisana zdaniem; miasto to podpowiedź („Usuń wiersz” / „Zostaw”). Kategoria
  i rola są słowem tylko do 3 słów i 40 znaków (granica `rows_from_legacy`) — dłuższe
  („Knowledge of card lifecycle management”) to zdanie. Krótka nazwa spoza słownika, której
  PIERWSZE słowo ma dwie wielkie litery, cyfrę przy literze albo „&+#” („MITRE ATT&CK”,
  „SailPoint IdentityIQ (IIQ)”, „GitLab CI/CD”), zostaje słowem do szukania — bramka jej
  nie zna, ale wyszukiwanie znajdzie ją w CV; „Zarządzanie projektami IT” zostaje zdaniem. Odczyt oddaje
  `POST /api/job-intake/critical-suggestion` w polu `readings` (bez nowej trasy).
- **Zdanie nie zostaje słowem bez decyzji (D3).** Edytor wierszy pod zdaniem pokazuje słowa
  z podpowiedzi z liczbą osób i „Do rozmowy”; „Utwórz i opublikuj” (brak `decision`) i zapis
  Championa nie wysyłają nic, dopóki decyzja nie zapadnie. Serwer i tak przy zapisie
  (`champion_requirement_rows.separate_talk_items`, wołane w `save_champion_core` przed
  `expand_patch`) przenosi słowa NOWYCH albo ZMIENIONYCH wierszy: zdanie → `experience.skills`
  (branża → `domains`), język → `basics.language`, technologia z komentarzem → słowo, poziom do
  rozmowy; krytyczne idzie za wierszem. Rekrutacja już przekazana nie traci ostatniego wiersza
  obowiązkowego (inaczej 422 `handoff_regression`) — zapis zostawia wiersze i mówi to uwagą.
  Uwagi wracają w `notices` odpowiedzi zapisu. „Uprość do słów kluczowych” wysyła zdania do
  `experience.skills`, nie do `stack.notes`; „Zdania klienta” z odczytu maila zostają w niuansach.
- **Krytyczne (D2).** Zdanie nie może być krytyczne (edytor wyłącza „Krytyczne” do decyzji).
  Gdy krytyczne razem zostawiają mniej niż 20 osób (`CRITICAL_PEOPLE_MIN`, liczba z tego samego
  zapytania co licznik „W bazie”), edytor ostrzega, a „Utwórz” i „Zapisz” pytają przez
  `useConfirmV2`. To potwierdzenie, nie blokada — niszowa technologia bywa rzadka.
- **Bramka (`critical-v12`).** Nawias po technologii ze słownika to komentarz:
  „SQL (bardzo dobra znajomość)” = SQL, „Python (DAG-i Airflow, ETL, API, LLM)” = Python;
  alternatywą jest tylko „(lub X)” albo lista samych technologii ze słownika („SQL (PostgreSQL,
  Oracle)”, „Java (np. Spring)”). Wstęp wokół jednej nazwy ze słownika („Bardzo dobra znajomość
  SQL”) daje tę nazwę; odmiana spoza słownika („znajomość Kafki”) zostaje prozą. „OWASP Top 10”
  nie traci „10”. Pomiar przed/po (`eval_matching`, 40 rekrutacji): metryki bez zmian.
- **Propozycje (B3, B4, D5).** Propozycja z nowego CV zapisuje `evidence.requirements` ze
  statusem `met` / `unknown` — bez „✕”, bo brak w liście umiejętności to nie dowód.
  `non_technology_must` czyta słowa krytycznych DL (`critical_gate_options`).
  `GET …/proposal-counts` niesie `talk_checks` (sekcja 4, język, must spoza bramki); karta
  propozycji ma „Sprawdzone w CV, profilu i notatkach” (✓ / ? / ✕ tylko dla słów) i „Zapytaj
  w rozmowie”; „Szukaj w bazie” pokazuje „Wymagane (krytyczne)”, „Musi mieć (Delivery Lead)”,
  „Mile widziane”, „Lokalizacja kandydata” i „Rekruter sprawdza w rozmowie” — filtry bez zmian.
- **Gotowość (D6).** Blokada `search` mówi: „Dodaj co najmniej jedno słowo do szukania…”.
  Zdania nie liczą się już jako wiersze, więc rekrutacja z samymi zdaniami nie przejdzie do
  searchu (5 z 6 takich rekrutacji nie miało ani jednej propozycji AI).
- **„Wymagania do poprawy” (D4).** `services/requirement_cleanup.build_proposal(job)` liczy na
  żywo propozycję dla otwartej rekrutacji (powody: `prose_column`, `paren`, `prose_rows`,
  `critical_not_searchable`, `no_search_words`, `rare_word` — ten ostatni:
  `rzadkie-slowo-w-wymaganiach-do-poprawy.md`). Propozycji nie zapisujemy; tabela
  `requirement_cleanup_decisions` (0438, lustro DDL w entrypoincie, sonda w `/api/health/deep`)
  trzyma ostatnią decyzję i odcisk profilu — odrzucona wraca dopiero po zmianie profilu.
  Nic nie znika po „Zatwierdź”: limity wierszy (10 + 20) liczone są PO przeniesieniu zdań
  do rozmowy, a nadmiar wierszy i listy rozmowy (20) idzie do opisu wymagań
  (`stack.notes`, „Nie zmieściło się…”, „Do sprawdzenia w rozmowie: …”); okno pokazuje
  nadmiar wierszy. Gdy wszystkie krytyczne DL schodzą do „musi mieć”, decyzja zostaje
  „Brak krytycznych” (`[]`), nie `None` — inaczej zapis dokłada blokadę i kończy się 422.
  `GET/POST /api/jobs/{id}/requirement-proposal[/apply|/dismiss]`; decyduje Delivery Lead tej
  rekrutacji (albo twórca), Head of Recruitment i admin (`can_decide`), zatwierdzenie to zwykły
  zapis Championa z `expected_profile_hash` (rozjazd = 409 z nową propozycją). Lista w
  `GET /api/board-tasks` (`requirement_fixes`), sekcja „Wymagania do poprawy” na pulpicie
  i baner w Profilu Championa. Sonda 13.10.2026: 133 z 202 otwartych z propozycją.
- **14.10.2026 — poprawki po audycie 13.10 (nic nie znika, nic nie blokuje).**
  - „Do rozmowy”, „Zamień na słowa” i „Rozdziel teraz” szukają słowa wiersza tak,
    jak czyta je serwer (`replaceRowWord`: sito 100 znaków na granicy wyrazu,
    bez kropki na końcu, NFC). Do tej daty „Doświadczenie w przetargach.”
    i zdanie ponad 100 znaków nie dawały się przenieść, a „Zapisz” zostawało
    zablokowane. Przy słowie przyciętym przez serwer do rozmowy idzie całe
    wpisane zdanie (`talkTextFor`).
  - „Zatwierdź” i „Uprość” zachowują poziom: zdanie z „mile widziane” idzie
    do rozmowy jako „Mile” (`rows_from_legacy` oddaje `descriptive_nice`).
    Technologia z wersją („Java 17+”, „Java (min. 11)”) zostaje wierszem bez
    wersji, a cała pozycja idzie do rozmowy — wcześniej wersja znikała. Sama
    wersja nie jest powodem propozycji (silnik czyta „Java 17+” bez niej).
  - „Uprość” liczy limit listy jak D4 (`talkFromDescriptive`): ponad 20 pozycji
    i pełne brzmienie zdania dłuższego niż 160 znaków (na liście zostaje skrót)
    idą do `stack.notes` („Do sprawdzenia w rozmowie: …”). Wcześniej zapis
    zostawiał 20 zdań, resztę gubił bez ostrzeżenia. D4 tak samo zapisuje
    całe zdanie dłuższe niż 160 znaków.
  - Zapis: gdy ostatnia krytyczna (poziom wiersza, `critical: null`) idzie do
    rozmowy, decyzja zostaje „Brak krytycznych” (`[]`) — `None` kończył się
    422 `handoff_regression`. `keep_required` to ten sam warunek co ochrona
    przed nowym brakiem (`status == published`), nie `is_open` — rekrutacja
    z Traffita bez przekazania też nie traci ostatniego wiersza.
  - Edycja samej listy `experience.skills` nie przestemplowuje `intake`
    (`champion_intake.user_edit`, jak wiersze wyszukiwania i krytyczne), więc
    nie odpala przeliczeń ani auto-matchu — wcześniej obietnica z D1 nie działała.
  - Sama alternatywa („Docker/Kubernetes”) nie ma komentarza: słowo zostaje,
    jak je wpisano, bez uwagi „komentarz pominięty” i bez powodu `paren`.
  - `requirement_cleanup.load_fixes_safely` przy awarii oddaje `None`, nie
    pustą listę — awaria nie może wyglądać jak „nic do poprawy”.
  - `critical_not_searchable` — patrz decyzja B w `umiejetnosci-krytyczne-i-bramka-v9.md`.
- **27.10.2026 — rzadkie słowo „musi mieć” (pomiar 129 profili z wierszami, kopia z 22.10).**
  Zdań w wierszach już nie ma, ale 49 z 886 wierszy „musi mieć” miało mniej niż 10 osób
  w bazie (12 zero): pojęcia przepisane z requestu klienta („Crisis plans” 0 obok
  „Business Continuity” 773), polska odmiana („monitoringu produkcji” 2) i warianty
  sklejone ukośnikiem bez spacji („SoapUI/ReadyAPI” 5, SoapUI osobno 2 289). W 50
  rekrutacjach wszystkie „musi mieć” razem dawały 0 osób, a edytor pokazywał samo „~0”.
  - Wiersz obowiązkowy z mniej niż `RARE_WORD_PEOPLE` (20) osobami dostaje
    `RareWordCallout`: „Do rozmowy”, „Zostaw” i — gdy `gluedVariants` rozbija słowo, a części
    mają więcej osób niż całość — „Rozdziel”. Nic nie blokuje; niszowa technologia bywa rzadka.
    Przy zerze nie piszemy już „sprawdź pisownię” — pisownia zwykle jest dobra, to inne słowo.
  - Gdy „wszystkie naraz” < 20, podsumowanie wymienia do trzech najrzadszych wierszy
    („Najbardziej zawężają: …”). AI i „Szukaj w bazie” dalej filtrują tylko po krytycznych.
  - Ukośnik bez spacji nie dzieli słowa przy wpisie („CI/CD”, „PL/SQL”) — „Rozdziel” pojawia
    się dopiero przy rzadkim wierszu, więc popularne słowa z ukośnikiem zostają nietknięte.
  - Licznik osób nie wysyła wiersza ze słowem krótszym niż 2 znaki („C”): lista kandydatów
    odpowiada wtedy 422 i całe „naraz” kończyło się „nie policzono” (789124). Ta sama reguła
    co `jobListFilters` w „Szukaj w bazie”.
- **27.10.2026 — „To słowo do szukania?” pod listą do rozmowy.** Pomiar na 129 profilach:
  technologia wpisana tylko w `experience.skills` to rzadkość, ale wtedy wyszukiwanie gubi
  prawdziwe wymaganie (663525: „Alteryx (good/advanced)”, w wierszach „Data handling”,
  „Reporting”). Edytor Championa czyta pozycje listy tym samym odczytem co wiersze
  (`critical-suggestion` → `readings`, każda pozycja i jej nazwa bez komentarza — „ — poziom”,
  „(poziom)” — jako osobny wiersz) i przy `technology` / `keyword`, którego żadne słowo nie
  stoi w wierszach (ani każdy człon: „Python + SQL” przy wierszach Python i SQL), pokazuje
  liczbę osób w bazie i przycisk. Pozycja z poziomem, komentarzem, notatką albo latami zostaje
  na liście („Dodaj do słów do szukania”), sama nazwa się przenosi („Przenieś…”). Nowy wiersz
  ma poziom pozycji („Mile” → mile widziane). Nic nie zapisuje się bez „Zapisz”.
  `components/champion/TalkSearchWordHints.tsx`, inwentarz `champ.talk-search-word`.
- Harness `/preview/new-job?state=readings`, karta propozycji `/preview/recruitment-v3`,
  „Szukaj w bazie” `/preview/job-detail?sources=search`, lista `/preview/custom-dashboard`.
- **27.10.2026 — fraza klienta bez ludzi w bazie → słowo z CV (odczyt requestu v14).**
  Pomiar na 129 Profilach Championa (kopia z 22.10): 97 z 886 wierszy „musi mieć” miało
  mniej niż 50 osób. 61 z nich przyszło z jednorazowego importu dokumentów Championa
  z Traffita (22.09, `scripts/champion_backfill.py`; frazy stały 1:1 w „MUST-HAVE” pliku
  DL-a, np. 646394 „Crisis plans”), 31 — z odczytu requestu w `/jobs/new` (65 z 68
  profili założonych w NEXUSIE miało `champion_draft` autora do 2 h przed założeniem),
  bo prompt każe brać słowa wyłącznie z maila. Import z Traffita nie działa od 14.10.
  - `JOB_REQUEST_INTAKE` v14 prosi przy wierszu o `cv_words` (1–2 słowa, którymi ludzie
    piszą to w CV; nie muszą stać w mailu). `job_request_intake.apply_people_reach`
    liczy osoby (`services/requirement_reach.people_reach` — ten sam filtr co licznik
    „W bazie”: aktywni i pasywni, semantyka 2, `q_any_group`, liczone do progu 20 przez
    `LIMIT`, bo pełna liczba „Java” to ~20 s). Wiersz z mniej niż 20 osobami dostaje słowo
    z CV, które samo ma co najmniej 20 osób; fraza klienta idzie do `experience.skills`
    („Rekruter sprawdza w rozmowie”), a uwaga odczytu pokazuje oba słowa. Słowo, które
    jest już innym wierszem, nie wchodzi jako wariant (wiersz się scala). Bez słowa z CV
    ≥ 20 wiersz zostaje, jak go odczytano — edytor ostrzega (#2698).
  - Wynik to dodatek: awaria bazy albo sufit 8 s (`REACH_TIMEOUT_S`) zostawia odczyt bez
    zmian. Słowa z CV oznaczają źródło wierszy jako „ai”, nie „z maila”.
- **30.10.2026 — pełne brzmienie wiersza z zamiennikami (zgłoszenie: „dodałem prince2 lub agile,
  a tylko agile się pokazuje”).** `row_label` dopisuje zamienniki tylko dla różnych technologii
  ze słownika (tak czyta je bramka), więc wiersz „Prince2* / Agile / Prince2” miał etykietę „Agile”.
  Kopia z 22.10: 164 z 1 523 wierszy w 74 rekrutacjach pokazywało mniej, niż wpisano. Etykiety
  nie zmieniamy (bramka, kontrakt wymagań, krytyczne); `response_context` niesie
  `requirement_full_labels` (etykieta → „Agile lub Prince2”, tylko gdy dłuższe), a czytają je
  Brief, „Wymagania” w panelu osoby i pasek nad CV. Bez innej pisowni tej samej nazwy i bez rdzenia
  będącego początkiem pokazanego słowa. Klucze, krytyczne i słownik zostają po etykiecie.
  Lupa „Szukaj w CV” dostaje słowa wiersza także przy wymaganiu niekrytycznym.
