# Umiejętności krytyczne i bramka v9 (0405, 30.09.2026)

Audyt `docs/audits/2026-09-30/wyszukiwanie-kandydatow.md` (symulacje na
historii): „każde must ukrywa” (v8) chowało 41,5% osób, które zespół potem
wysłał do klienta, budżet — 32%, dni w biurze — 8%. Decyzje Artura 30.09.2026:

- **Ukrywają tylko umiejętności krytyczne: 0–3 z wyboru Delivery Leada**
  (do 08.10.2026 dwie; `CRITICAL_MAX` w `schemas/champion.py`, lustro
  `lib/critical-skills.ts`), z podpowiedzi z historii najwyżej dwie
  (`critical_skills.SUGGEST_MAX` — działa bez decyzji człowieka, więc trzecia
  automatyczna bramka wymaga pomiaru) (`services/critical_skills.py`,
  `MUST_GATE_POLICY_VERSION`, dziś `critical-v11`). Pole Championa `stack.critical`:
  `None` = DL nie zdecydował (działa podpowiedź), `[]` = „Brak krytycznych”
  (bramka must nie ukrywa nikogo), lista = bramka. Serializer zdejmuje `None`
  (stare profile nie zmieniają kształtu). Wybór nie zmienia wymagań roli
  (`champion_view.without_critical` w `requirement_source` i w `user_edit`):
  nie kasuje kontraktu wymagań i nie odpala przeliczeń. Idzie za listą MUST
  (`_prune_critical`; stracone wszystkie = z powrotem `None`), kopia
  rekrutacji ma `None`, zły wybór = 422 po polsku (`critical_errors`).
- **Krytyczną może być KAŻDA fraza — decyduje Delivery Lead (decyzja Artura
  09.10.2026, `critical-v11`).** System nie odrzuca już branży, języka,
  umiejętności miękkiej, kategorii, roli ani zdania (`critical_selectable`
  i komunikat „Nie może być krytyczne: …” usunięte; `critical_errors` zna tylko
  „za dużo” i „spoza MUST”). Limit trzech zostaje. Bramka szuka **słów wiersza**
  (`stack.rows[].words`) w profilu, CV i notatkach — którekolwiek wystarcza:
  `critical_skills.critical_gate_options(job)` (etykieta → słowa; fraza bez
  wiersza = sama etykieta; tylko przy `source == "dl"`), `DealbreakerInputs.
  critical_options` / `gate_options`, `must_gate_terms.requirement_with_options`.
  Każde `attach_gate_evidence` MUSI nieść `options=` (strażnik AST w
  `test_must_gate_evidence_wiring.py`) — bez nich fraza nie ma dowodu u nikogo
  i ukrywa wszystkich na tym jednym ekranie. Te same słowa czytają QC CV
  (`cv_qc.critical_requirements`) i wiersze „Szukaj ręcznie”
  (`critical_resolution_payload`); pula SQL (`build_job_must_groups`) po
  krytycznej szukanej słowami NIE zawęża (tsquery nie zna odmiany — pula ma być
  nadzbiorem bramki). Zamrożone żądanie niesie słowa w
  `critical_effective["options"]` tylko, gdy są (odcisk rekrutacji bez wyboru DL
  bez zmian). Historia: 30.09 wybór ograniczał słownik (`critical_eligible`),
  08.10 — reguła „wygląda na nazwę technologii”; w 16 rekrutacjach 9 kończyło
  z „Brak krytycznych”. `critical_eligible` (słownik) zostaje dla podpowiedzi
  z historii, wymogu decyzji przy przekazaniu (`job_readiness`) i tytułu dla
  rekrutera — tam nikt wyboru nie potwierdza. `POST …/critical-suggestion`
  oddaje `selectable` = wszystkie etykiety i puste `blocked` (pola zostają dla
  otwartych kart przeglądarki). Edytor wierszy wyłącza „Krytyczne” WYŁĄCZNIE
  limitem; pod krytycznym spoza słownika stoi zdanie, czego szukamy.
- **Edytor wierszy wymagań — klawiatura (zgłoszenie 09.10.2026: „wpisuję jedno
  must-have i nie mogę kolejnego”, „słowo znika albo się podmienia”).** Enter
  po słowie = następne wymaganie (kursor w pustym wierszu niżej, nowym, gdy go
  nie ma — jednym `onRowsChange`; w środku listy kursor zostaje), przecinek =
  wariant „lub” w tym samym wierszu. `ChipField` ma do tego `onEnterCommit`
  i `suggest.quietWhenEmpty` (lista podpowiedzi nie otwiera się na pustym polu
  — zasłaniała wiersz niżej i „Dodaj słowo kluczowe”). Najechanie myszą NIE
  ustawia podświetlenia klawiatury (`KeywordSuggestionList` bez `onHover`,
  podświetlenie pod kursorem to CSS) — Enter wstawia podpowiedź tylko wybraną
  strzałkami, także na liście kandydatów. Wiersze znajdujemy po
  `data-row-index`, nie po kluczu (klucz pustego wiersza różni się między
  serwerem a przeglądarką — hydratacja).
- **Podpowiedź z historii:** technologia z MUST (każda opcja w słowniku,
  także narzędzia/standardy/AI — `must_gate_terms.critical_eligible`), którą
  ≥90% osób wysłanych w innych rekrutacjach ma w profilu, CV albo notatce
  (≥5 rekrutacji); najpierw z tytułu, potem wg odsetka; najwyżej 2. Statystyki:
  `compute_stats` → `app_settings['critical_skill_stats']` co tydzień w nocnej
  pętli, do pierwszego przeliczenia seed `app/data/critical_skill_stats_seed.json`;
  proces czyta je z pamięci (odświeżanie co godzinę). Pusta lista w
  `POST /api/job-intake/critical-suggestion` (niezapisane MUST, /jobs/new).
- **Krytyczne są zamrażane w żądaniu** (`request_matching_context`,
  `critical_effective` w `job_data`) — zmiana podpowiedzi po przeliczeniu
  statystyk zmienia odcisk, a worker bramkuje zestawem z chwili startu.
- **Słowna wersja jest wersją** (v9.1, `skill_normalize._VERSION_WORD`):
  „Java (minimalna 11)”, „Oracle (min. 19c)”, „Java od 11” odcinają się jak
  „Java 11+”. Do 30.09.2026 taka pozycja nie bramkowała i nie dało się jej
  oznaczyć jako krytycznej.
- **v10.1 (07.10.2026, PR #2056)**: fraza przechodzi przez nawias, dwukropek,
  przecinek i kropkę („Spring (Boot, Data)” = Spring Boot), must-have liczy
  się w odmianie (rdzeń ≥ 4 litery) w CV i notatkach, a kandydat z CV
  czekającym na odczyt tekstu nie jest „bez danych” (`must_text_evidence`).
  To zmienia, kogo bramka ukrywa — stąd bump `MUST_GATE_POLICY_VERSION`.
- **Budżet i dni w biurze to plakietki** (`rate_fit`, `office_fit`); ocena
  stawki jest neutralna z opisem „ponad budżet o X%”. Wiersz pełnego przeglądu (Radar, cała
  baza) niesie `fit` (`rate`/`office` z chwili przeglądu) → plakietki `fullSearchFitBadges`. **Kandydat bez CV,
  umiejętności i notatek jest ukryty zawsze** (`no_data`) na listach AI.
  Dowód z CV i notatek dołącza się RAZ dla wszystkich technologii must+nice
  (`DealbreakerInputs.gate_evidence_labels`; `evidence_for` przyjmuje
  nadzbiór) — czyta go bramka, plakietki i ocena (`_score_skills` liczy
  technologię z profilu/CV/notatki, mianownik tylko z technologii).
- **Reguła „co jest technologią”** (`must_gate_terms`): nazwa ze słownika
  w kategorii `role_*` albo `methodology` nie bramkuje („QA”, „Software
  developer”, „Scrum”); przykłady z nawiasu tylko po głowie-kategorii albo
  technologii („Bazy danych (Oracle, PostgreSQL)”), nie po zdaniu.
- **Przekazanie do searchu wymaga decyzji** o krytycznych, gdy MUST ma
  technologię ze słownika (`MSG_CRITICAL`, lustro frontu; kod `critical`
  w brakach /jobs/new).
- **„Pomiń” propozycję wymaga powodu** (`job_proposals.dismiss_reason`:
  `missing_critical`, `too_expensive`, `location_office`, `too_junior`,
  `outdated_cv`, `other` + notatka ≤500; 0405, lustro w `entrypoint.sh`),
  telemetria `reject` z `reason_code`, raport Insights „Propozycje AI”
  (`GET /api/insights/proposals/outcomes`, admin/HoR/DL portfela) i
  poniedziałkowy dzwonek do DL z liczbą propozycji bez decyzji
  (`proposals_digest`, typ `auto_match_proposals`, dedup po tygodniu ISO).
  Do 30.09 żadna z 57 nocnych propozycji nie miała decyzji.
- **Plakietka „CV z RRRR”** czyta `proposal-facts.cv_uploaded_on` — tylko
  prawdziwą datę wgrania głównego CV, nigdy dnia importu.
- **Wyłącznik `MUST_GATE_MODE=all`** przywraca v8 w całości (każde must,
  budżet i dni ukrywają, stawka w punktach) — na nim stoją stare testy
  bramki (przypięte fixturą `_v8_must_gate`). Nowy test trybu domyślnego:
  `tests/test_critical_gate.py`.
- **QC CV blokuje na tych samych krytycznych** (02.10.2026,
  `cv_qc.critical_requirements` = `effective_critical(job)` dopasowane do must
  rekrutacji): wybór DL, a bez niego podpowiedź z historii — niezależnie od
  `MUST_GATE_MODE`. Podpowiedź przelicza się co tydzień, więc werdykt QC
  rekrutacji bez wyboru DL może się zmienić bez zmiany CV; okno QC nazywa źródło.
- **Warstwa `prior_screening` — odpowiedzi z wcześniejszych rozmów
  (07.10.2026, `services/prior_screening.py`), wyłącznik
  `PRIOR_SCREENING_LAYER_ENABLED` domyślnie OFF.** Materiał: najnowszy
  wypełniony arkusz kandydata w każdej INNEJ rekrutacji (bez `skipped`
  i `reassign_suggested`). Pytanie tej rekrutacji pasuje bez AI: Jaccard
  rdzeni słów ≥ 0,6 i każda technologia ze słownika z tego pytania stoi też
  we wcześniejszym; pytania o stawkę, dostępność, lokalizację i tryb pracy są
  pomijane. Punkty `MAX_POINTS × tak/(tak+nie)` (wydźwięk: `is_negative_answer`
  + jawne potwierdzenie), same „nie wiadomo” = warstwa bez oceny (wynik bez
  zmian). Deal-breaker (warunek przy pytaniu TEJ rekrutacji + wcześniejsza
  odpowiedź oceniona jako trafienie; samo „nie” nim nie jest) = 0 pkt
  i plakietka `fit.prior_screening`, nigdy ukrycie. Uwaga przed włączeniem:
  przeskalowanie ×100/105 przy jednym „nie” spycha wynik 72 poniżej progu
  nocnych propozycji (70) — zmierzyć w etapie 2. Decyzję niesie żądanie (`versions["prior_screening"]`), nie flaga
  z chwili oceny — przy OFF odcisk, `scoring_algorithm_version` i
  `ScoreBreakdown.as_dict` są bajt w bajt jak bez warstwy. Zmiana progu,
  budżetu albo reguły = podbij `prior_screening.VERSION`. Włączenie dopiero po
  pomiarze (`scripts/eval_prior_screening.py`, etap 0: pokrycie wysłanych
  ≥ 5%, tylko rekrutacje z `opened_at`) i po zapisie arkuszy z notatek.
- **v10 (07.10.2026, audyt AI Search, `critical-v10`):**
  - Dowód z notatek: z `_notes_insights` liczą się tylko `skills_evidenced`
    i `certifications` (`must_text_evidence._NOTES_INSIGHTS_EVIDENCE_FIELDS`)
    — braki („nie zna Kafki”) i weta dawały 1 791 fałszywych trafień. W karcie
    rekomendacji (`card`, `screening_facts`) pytanie z przeczącą odpowiedzią
    znika razem z odpowiedzią (`evidence_note_text`, słownik
    `_NEGATIVE_ANSWER_RE`; „podstawy”, „słabo” to wciąż znajomość). Ten sam
    tekst czytają statystyki podpowiedzi (`critical_skills.compute_stats`).
  - „Tylko zdalnie” z notatek ukrywa wyłącznie przy pracy stacjonarnej, od
    4 dni w biurze albo przy jawnym `exclude_remote_only`
    (`DealbreakerInputs.remote_only_hides`); przy hybrydzie wiersz niesie
    plakietkę `remote_fit = "prefers_remote"` („Preferuje pracę zdalną”) —
    76% osób z tą flagą zweryfikowanych do biura zespół wysłał do klienta.
  - Podpowiedź krytycznych tylko z tytułu albo z pierwszych 3 pozycji listy
    must, która ma najwyżej 8 pozycji (`SUGGEST_MAX_POSITION`,
    `SUGGEST_MAX_LIST`); ukryci zweryfikowani 7,1% → 2,7%. Dotyczy też QC CV.
  - Dopasowanie nazw: krótkie formy ze znakiem (`C#`, `F#`, `C++`) bez
    rozróżniania wielkości liter; implikacje `skill_normalize.IMPLIED_BY`
    (rodzina SQL ⇒ SQL, PlantUML ⇒ UML — jednokierunkowe, NIE alias); „rest
    of”, „the rest”, „at rest” to nie REST API (`_patterns`,
    `is_technology_mention`).
