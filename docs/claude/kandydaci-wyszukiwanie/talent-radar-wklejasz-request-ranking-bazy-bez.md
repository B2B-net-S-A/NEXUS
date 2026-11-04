# Talent Radar (wklejasz request → ranking bazy, bez zakładania rekrutacji)

Sekcja `/talent-radar` + `POST /api/talent-radar/search`. Rekruter wybiera
klienta, wkleja treść requestu i dostaje ranking kandydatów. **Nie tworzy
oferty** — to przeszukanie bazy, nie krok pipeline'u. PR-y: #1115 (silnik),
#1116 (rename źródła), #1119 (UI).

- **Nazwa kolidowała i kolizja została rozstrzygnięta na korzyść modułu.**
  `talent_radar` funkcjonował od maja jako *legacy źródło importu* z Supabase.
  Migracja `0222` przepisała je na `tr_legacy` (15 wierszy — nie 40 745, ta
  liczba z docstringu importera opisuje rekordy POBIERANE, a importer scala).
  Ograniczenia `CHECK` **nadal akceptują starą wartość** (widen-then-migrate),
  a typ we froncie ma obie — dlatego zmiana niczego nie zerwała. Trasy techniczne
  zostają: `/api/admin/import-talent-radar` to wciąż tamten import.
- **`client_id` jest WYMAGANY, nie opcjonalny.** Filtr dopuszczalności sprawdza
  względem niego blacklistę klienta, NDA, konflikty konkurencyjne i weto hiring
  managera. Opcjonalny klient dałby listę, w której te kontrole cicho nie
  zaszły — dokładnie defekt naprawiony w `/ai-matches` (#1109). Dlatego UI ma
  **własny picker** (`TalentRadarClientPicker`), a nie `ContractsClientPicker`:
  tamten oferuje „Wszyscy klienci (lista globalna)" jako wybór, co tutaj jest
  zaproszeniem do czegoś, co z definicji nie może zadziałać.
- **`meta.degraded` MUSI renderować się jako awaria, nigdy jako pusty stan.**
  Gdy Qdrant albo Voyage milczy, backend zwraca zero wyników z tą flagą.
  „Brak dopasowań" byłoby wtedy kłamstwem w najgorszą stronę — rekruter uznałby,
  że w bazie nie ma nikogo takiego. Harness `/preview/talent-radar` (publiczny,
  same mocki, zero wywołań API) pokazuje te stany obok siebie właśnie po to,
  żeby różnica nie zniknęła przy kolejnej zmianie.
- **Ranking bez cache'u.** `rank_candidates_for_job`, NIE `bulk_get_or_compute`:
  klucz cache'u to `(kandydat, oferta, profil)`, a ta oferta nie ma `id`, więc
  cache albo kolidowałby między niezwiązanymi wyszukiwaniami, albo wywracał się
  na pustym kluczu. Z tego samego powodu `build_ephemeral_job` ma **`id=None`
  jako rzecz znaczącą, nie zaślepkę** — `build_job_scoring_context` filtruje
  `CandidateStage.job_id == job.id`, więc puste id oznacza brak historii
  pipeline'u, co dla wyszukiwania ad hoc jest poprawne.
- **`SimpleNamespace`, nie nieprzypisany `Job`.** Instancja ORM niesie deskryptory
  relacji, które przy dostępie do atrybutu potrafią odpalić lazy load — w async
  SQLAlchemy to `MissingGreenlet`, nie wartość domyślna. Test wychodzi wymagane
  atrybuty **AST-em po źródle** `scoring_service`/`embedding_service`/
  `pipeline_eligibility`, a nie z ręcznej listy, bo ręczna lista przechodzi
  dalej w dniu, w którym scoring zacznie czytać nowe pole.
- **Wyniki niosą tożsamość węższą niż profil** — bez e-maila, telefonu i stawki.
  Lista rankingowa służy do decyzji KOGO otworzyć; kontakt jest za kliknięciem.
  Warstwa wynagrodzenia jest wygaszana (`status: "not_applicable"`), bo radar
  nie ma widełek i surowe zero czytałoby się jako „nie pasuje finansowo".
- **Role: KAŻDA zalogowana** (decyzja produktowa Artura 19.08 — poszła po
  zrzucie 403 od Head of Recruitment; wcześniej `require_candidate_write` bez
  HoR). PIĘĆ lustrzanych miejsc: backend oba endpointy na `CurrentUser`,
  middleware BEZ wpisu `/talent-radar` (brak wpisu = brak zawężenia ról, sam
  login wymagany), sidebar bez `roles`, `nav.talent_radar = ALL_ROLES` w
  `CAPABILITY_ROLES` (paleta ⌘K czyta stamtąd) oraz SAM `page.tsx` BEZ
  `RequireRole` — piąta kopia starej listy ról (in-page `RequireRole` z
  fallbackiem „Brak uprawnień") przeżyła otwarcie #1212 i wyszła dopiero ze
  zrzutu użytkownika, zdjęta w follow-upie. Test kontraktowy pilnuje, że
  guard rolowy (`_check`) NIE wróci na trasy radaru cichym refaktorem.
  **Granice, które ZOSTAJĄ**: wyniki niosą tożsamość węższą niż profil (bez
  kontaktu i stawek), a „Otwórz profil" renderuje się tylko dla ról z
  `nav.candidates` — po decyzji z 19.08 (finance = pełny dostęp operacyjny)
  poza tą capability jest już wyłącznie viewer `user`.
- **Pułapka przy dokładaniu endpointów**: moduł z `@limiter.limit` nie może mieć
  `from __future__ import annotations` (PEP 563 + slowapi #579 → body ląduje jako
  parametr Query). Pilnuje tego test czytający AST, nie treść pliku — docstring
  wspomina ten import, żeby przed nim ostrzec, więc szukanie stringu wywalało
  się na własnym ostrzeżeniu.

### Pełny przegląd bazy (#1428): retencja, cykl życia, bramka must-have (10.09.2026)

Od #1428 Radar i „cała baza” w rekrutacji oceniają CAŁĄ populację (~60 tys.)
w trwałym przeglądzie (`candidate_search_runs` + wiersz na kandydata
w `candidate_search_results`, ~100–130 MB na przegląd). Worker działa w procesie
web — jeden przegląd naraz, ~3 min.

- **Retencja (decyzja 10.09):** pętla `candidate_search_retention` kasuje
  zakończone przeglądy (`complete`/`partial`/`failed`) starsze niż
  `CANDIDATE_SEARCH_RETENTION_DAYS` (7), ale najnowszy przegląd z wynikami
  zostaje dłużej — na (autor, OTWARTA rekrutacja), a bez rekrutacji jeden na
  autora — najwyżej `CANDIDATE_SEARCH_RETENTION_PROTECT_MAX_DAYS` (90).
  **Nie chroń per odcisk requestu ani bez limitu czasu:** każda nowa treść
  requestu i każdy bump wersji polityki dawałyby nową, wiecznie chronioną
  partycję, a tabela rosłaby z liczbą par zamiast z czasem (przegląd
  adwersarialny 10.09). Kill-switch `CANDIDATE_SEARCH_RETENTION_ENABLED`
  (pętla kończy się przed `while True`). Indeksy z migracji 0305 (`completed_at`
  przeglądu, `candidate_id` wyników) mają lustro w `_INDEX_STATEMENTS`.
  Rozmiar tabeli widać w `GET /api/admin/index-coverage` (blok `candidate_search`).
- **Stan `failed`:** przejęcie przeglądu zwiększa `metrics.claims` w tym samym
  UPDATE; zgłoszona porażka od trzeciego przejęcia (`MAX_FAILED_ATTEMPTS`)
  kończy przegląd jako `failed`, a przejęcia bez raportu — proces zabity
  w trakcie, u nas zwykle deploy — mają szerszy budżet (`MAX_CLAIMS` = 8).
  Reaper kończy przejęte przeglądy bez postępu od 30 min. Do 10.09 przegląd,
  który padł, był podejmowany na nowo w nieskończoność i trwale zajmował jeden
  z dwóch slotów autora. `failed` nie liczy się do limitu; front pokazuje
  „Uruchom ponownie”. Odpytywanie staje tylko po błędzie OSTATECZNYM
  (409/404/403 — `searchErrorIsFinal`); chwilowa awaria (sieć, 5xx, deploy)
  odpytuje dalej co 5 s i trzyma blokadę przycisku startu, żeby nikt nie
  odpalił drugiego trzyminutowego skanu. „Spróbuj ponownie” czyta przegląd,
  a nie odpala nowego skanu.
- **RODO:** twarde usunięcie kandydata kasuje jego wiersze wyników, a aktywne
  przeglądy z tą osobą kończy jako `failed` (`candidate_erased`) —
  `finish_run` wymaga rozliczenia całej migawki.
- **Bramka must-have: `requirement_contract.search_dealbreaker_inputs`
  to JEDNO miejsce polityki dla wszystkich powierzchni.** Od v8 (decyzja Artura
  27.09.2026, `anywhere-evidence-v8`) must jest spełniony, gdy technologia stoi
  w profilu, tekście CV albo notatce z rozmowy (bez maili;
  `services/must_text_evidence.py`, `attach_gate_evidence` przed KAŻDYM
  `apply_dealbreakers` — pilnuje `test_must_gate_evidence_wiring.py`); brak
  wszędzie = ukryty, osoba bez CV, umiejętności i notatek = `no_data`. Bramkują
  tylko technologie (`services/must_gate_terms.py`: wersje odcięte, przykłady
  klienta i „A lub B” = którakolwiek; język, branża, kategorie, role, zdania nie).
  Inne miasto ukrywa dopiero od 4 dni w biurze / pracy stacjonarnej, przy
  hybrydzie 1–3 dni to plakietka `city_mismatch`. `exclude` dokłada tylko
  weryfikację rekrutera „nieznane” jako brak. Pomiar i świadomy koszt (długie
  listy must z maila chowają prawie wszystkich): `docs/audits/2026-09-26/
  tworzenie-rekrutacji-a-wyszukiwanie.md`, sekcja „Wdrożenie reguł wyszukiwania”.
  **Od v9 (`critical-v9`, 30.09.2026) ukrywają WYŁĄCZNIE umiejętności
  krytyczne** — sekcja „Umiejętności krytyczne i bramka v9” niżej; opis v8 wyżej
  działa tylko przy `MUST_GATE_MODE=all`.
  `MUST_GATE_POLICY_VERSION` jest częścią odcisku requestu — zmiana znaczenia
  polityki = bump, inaczej stare rankingi udają aktualne. Kill-switch
  `RUBRIC_DEALBREAKERS_ENABLED` działa raz, w `apply_dealbreakers`.
- **„Przekaż do searchu” liczy must-have podane prozą jako podane**
  (`must_skills or must_skills_ignored` w `job_readiness.py`). Do 10.09 rekrutacja
  z samą prozą dostawała 422, choć dok gotowości pokazywał ✓.
- **Podobieństwo liczy Qdrant, nie Python (od 11.09.2026).**
  `full_search_measurement.measure_candidates` robi JEDNO wyszukiwanie dokładne
  z filtrem po ID (`HasIdCondition`, `SearchParams(exact=True)`, kwantyzacja
  ignorowana) i ściąga tylko payload pochodzenia (`content_hash`,
  `embedding_model`). Wcześniej przegląd ściągał 256×1024 liczby na paczkę jako
  JSON i liczył cosinus w Pythonie (1,48 s → 0,08 s na 3000 kandydatów; parytet
  do 4e-8). **Odpowiedź 4xx i dokładne 0.0 wracają na ścieżkę referencyjną**
  `_measure_by_retrieval` — zerowy wektor też punktuje 0.0, a zepsuty wektor nie
  może udawać zmierzonego zera. Pętle CPU (`canonical_fit`,
  `full_candidate_scan`, pomiar) oddają pętlę zdarzeń co 32 elementy, bo worker
  żyje w procesie web.
- **Konsumenci kanonicznego fitu pytają pulę bez rerankera**
  (`retrieve_candidate_pool(use_rerank=False)`: `/ai-matches`, rekomendacje,
  propozycje, digest). Pula = `final_top_k`, więc reranker zmieniał wyłącznie
  kolejność, którą i tak nadpisuje sortowanie po `fit_score` — był czystym
  kosztem (wywołanie Voyage i SELECT puli). `None` = `RERANKER_ENABLED`.
- **Higiena indeksu: `GET/POST /api/admin/index-cleanup`** (admin JWT). GET to
  plan tylko do odczytu z odciskiem: punkty kandydatów bez wiersza (sieroty)
  i oferty bez punktu lub stempla `embedding_id`. POST z odciskiem i licznikami
  kolejkuje DOKŁADNIE ten plan w outboxie indeksu (plan się zmienił → 409).
  Kasowania sierot niosą `desired_hash="orphan-point"` i worker przy wykonaniu
  sprawdza, że wiersza kandydata nadal nie ma — tą ścieżką nie da się skasować
  punktu istniejącego kandydata. Plan czyta najpierw indeks, potem SQL, więc
  kandydat dodany w trakcie nie wygląda na sierotę. Odcisk obejmuje tylko części
  wykonawcze (sieroty, oferty do embeddingu) — globalne liczniki są w odpowiedzi,
  ale nie w odcisku, inaczej każdy niezwiązany embedding między GET a POST
  dawałby 409.
- **Kolumna dopasowania w wyszukiwarce ręcznej i pierścień „Dopasowanie” to
  kanoniczny fit** (ten sam, co na ekranach C2), a nie `CandidateJobMatchScore`
  — żaden ekran go już nie czyta. `/api/search/candidates/scores` liczy na
  żądanie najwyżej 20 ID (422 powyżej), limit 60/min **per zalogowany
  użytkownik** (`user_or_ip_key` — biuro za jednym NAT-em nie dzieli kubełka;
  ten sam klucz ma ocena opisu „Dopasowanie”), **za tą samą bramką co
  pełny przegląd (`_authorized_job` z `candidate_search.py`)** — rekruter,
  sourcer i TAC spoza zespołu widzą ten sam wynik na ekranach C2, więc kolumna
  nie może być ostrzejsza (pierwsza wersja z `ensure_job_read_access` chowała go
  im bez słowa); stawki redagowane bez `view_finance`. Front pyta tylko
  o wiersze na ekranie (`useVisibleMatchScores`, anulowanie AbortControllerem,
  cache per `profile_key` z odpowiedzi): niezmierzony = „Ocena niepełna”,
  403 = „brak dostępu”, inny błąd = „nie policzono — ponów” (429 ponawia sam
  z backoffem — jedna runda dla WSZYSTKICH wierszy czekających na ponowienie,
  także z kilku równoległych paczek) — nigdy puste pole ani 0. Modal porównania pokazuje błąd
  z „Ponów”, nie „Brak kryteriów”.
- **Pierścień „Dopasowanie” liczy się we własnej sesji** (`display_fit`, tylko
  do odczytu, nigdy nie rzuca): wcześniej wyjątek w nim robił rollback sesji
  requestu, wygaszał `current_user` i zakładka kończyła się 500
  (`MissingGreenlet`), a współdzielona instancja kandydata przestawiała stare
  rozbicie i hash opisu (płatne regeneracje). **Opis AI nie podaje liczby
  punktów** (`MATCH_JUSTIFICATION` v2 bez `{score}`) — liczbę pokazuje pierścień,
  a opis tłumaczy mocne strony i luki. Zapisane opisy odświeżają się leniwie
  przy następnym otwarciu (wersja promptu jest w hashu).
- **Telemetria jest podpięta.** Strona wyników pełnego przeglądu zapisuje
  impresje obsłużonych wierszy jednym INSERT-em (`match_impressions`, `run_id`
  = id przeglądu). Dodanie do pipeline'u (`proposals_bulk`) przypina outcome
  `add_to_pipeline` WYŁĄCZNIE do przeglądu, który klient zadeklarował (`run_id`
  + `source`), i tylko gdy to przegląd tej osoby, tej rekrutacji i z impresją
  tego kandydata — w innym wypadku `run_id` = NULL. Żadnego zgadywania po
  „ostatnio widzianym” (to zawyżało pozytywy C2 dodaniami z wyszukiwarki
  ręcznej). `source` (`full_search` | `manual_search` | `historical` |
  `quick_add` — każdy ekran dodawania wysyła swój) żyje w
  `match_outcomes.reason_code` (stały słownik, bez migracji). Zapis we własnej sesji po commicie, nigdy nie rzuca, najwyżej 100
  wierszy. Tabele nie mają FK do kandydatów (celowo: analityka, pseudonimy,
  rozbicie wyłącznie liczbowe) ani jeszcze retencji — świadomy dług.
- **Eval: nigdy nie porównuj metryk między scorerami.**
  `scripts/eval_matching.py --scorer canonical` domyślnie maskuje dowody wymagań
  zweryfikowane przez rekruterów (wyciek etykiety, jak `champion_fit`);
  `--include-reviewed-evidence` je przywraca. `weekly_eval` mierzy canonical
  i porównuje tylko biegi tego samego scorera (bieg bez klucza `scorer` =
  legacy), więc pierwszy bieg canonical to `baseline: "scorer_changed"`, nie
  regresja. A/B na prodzie: `coolify-ops.yml` `action=eval-ab-scorer` (legacy to
  ramię kontrolne, ma odtworzyć baseline 18.08). `--pool full` nie ma sensu:
  pełny przegląd ukrywa kandydatów już w rekrutacji, czyli wszystkie pozytywy.
- **Komenda zadania Coolify ma najwyżej 255 znaków** (`scheduled_tasks.command`
  = VARCHAR(255) — dłuższa kończy `POST /scheduled-tasks` gołym HTTP 500). Oba
  kanały A/B wysyłają więc tylko `python -m scripts.eval_ab_run …`, a ramiona,
  zamrożoną listę ofert i sekcje raportu liczy skrypt; workflow pilnuje długości
  przed wysłaniem. Do 11.09 komenda A/B miała ~1,6 tys. znaków (dwie listy 50
  ofert w YAML-u) i żaden bieg nie mógł wystartować. Długie zadanie potrzebuje
  też jawnego `timeout` (Coolify od 11.2025 ubija po domyślnych 300 s). Każdy
  nowy kanał operacyjny: logika w `scripts/`, w komendzie tylko argumenty.
- **Surowy SQL (`text()`) musi przejść `PREPARE`** — `= ANY(:ids)`, nie
  rozwijane `IN :ids` (strażnik `test_raw_sql_prepares`).
