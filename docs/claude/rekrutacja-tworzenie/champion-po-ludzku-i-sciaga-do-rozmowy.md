# „Champion po ludzku” i ściąga do rozmowy (0403, 29.09.2026)

Decyzje Artura 29.09.2026 (makiety https://claude.ai/artifact/WEVyKuavTdd8JVggXQ9mD3):
blok „Po ludzku” na górze Podglądu Championa i „Ściąga do rozmowy” w doku osoby
(Nowi/Screening). Kontrakt API: `docs/champion-plain-brief-contract.md`.

- **Wiedza ogólna jest wspólna i powstaje RAZ** (research w internecie,
  F26 `plain_knowledge_research`, Sonnet 5 — `web_search` działa tylko
  u Anthropic): `plain_terms` (słowniczek, klucz = `skill_normalize.canonical_of`,
  bez FK do `skills` i BEZ dopisywania `skill_aliases` — to zmieniłoby scoring),
  `role_profiles` (biblioteka ról, `jobs.role_profile_id`, dopasowanie
  `plain_knowledge/role_matcher.py` bez AI, `manual` nigdy nienadpisywany),
  opis klienta w `client_playbooks.about_for_candidate` z `about_for_candidate_origin`
  (`web`/`manual`). Do wyszukiwarki idzie WYŁĄCZNIE nazwa (technologii, roli,
  firmy) — nigdy profil, kandydat ani notatki. Research nie trzyma blokady:
  wiersz zajmuje `INSERT … ON CONFLICT` ze `status='researching'`.
- **Teksty rekrutacji w `job_plain_briefs`, NIE w `champion_profile`**
  (`champion_intake.fingerprint` hashuje cały profil — zapis w tle dawałby
  fałszywe 409 przy imporcie). Klucz AI `champion_draft`. Kod usuwa zdanie
  z liczbą albo technologią spoza danych wejściowych, pytania kandydata są stałą
  listą (brak danych = `answer: null`), `screening_plain` to wyłącznie istniejące
  `screening_questions` (bez nowych warunków; brak deal breakera = brak „Odpada”).
- **GET nic nie zapisuje** i nie woła AI; `stale` mówi, że profil zmienił się od
  generacji. Odświeża `POST …/plain-brief/refresh` (osobny moduł z limitem
  10/min, w `READ_ONLY_POST_ROUTE_TEMPLATES`, 403 w „podglądzie jako”): w żądaniu
  tylko research nowej roli i brakującego opisu klienta (zmieniają teksty), hasła
  słowniczka są od razu zajmowane („Szukam opisu…”) i badane w tle — pomiar
  29.09: trzy researche w żądaniu + teksty = 99 s przy limicie frontu 120 s. Front
  woła odświeżenie sam tylko dla otwartych rekrutacji i dociąga widok co 10 s,
  dopóki hasło jest w researchu (najwyżej 30 razy). Nazwa nowej roli bez poziomu,
  nawiasów i prefiksu klienta przed dwukropkiem (`role_matcher.clean_role_name`),
  bez oznaczeń zamówień i zespołów („_moduł V”, „x1 Zapotrzebowanie…”, „PL_”,
  „ON HOLD”) i bez słów nazwy klienta tej rekrutacji z jej skrótami
  (`client_words`: „PKO Bank Polski” → „BP”). Tytuł bez nazwy zawodu
  (`ROLE_NOUNS`) roli nie zakłada — research 29.09 dał role „PL” i „AKADEMIA”,
  a nazwy z klientem trafiłyby do publicznego `roles.json`. Słowniczek nie
  bada zwykłych polskich słów (`knowledge._generic_phrase`: hasło spoza słownika
  umiejętności pisane małymi literami albo złożone z polskich rzeczowników
  i przymiotników — „dokumentacja”, „testy web”, „Bankowość”); skróty i nazwy
  narzędzi („AML”, „SoapUI”, „RedMine”) zostają. Nie dokładaj haka w zapis Championa — `stale` obejmuje
  każdą ścieżkę zapisu profilu.
- **Stawka i nazwa klienta idą do kandydata od razu; statystyki roli BEZ stawek**
  (liczba rekrutacji, klientów, zatrudnień, stanowiska zatrudnionych od 3
  zatrudnień, tylko tytuły wspólne dla ≥ 2 osób). Bez wersji EN i bez
  wiadomości do kandydata (wycofane 29.09). **Stawkę w odpowiedzi „Ile płacą?”
  i w tekście na start wstawia KOD** z budżetu profilu (`job_brief.rate_sentence`)
  — model gubił ją przy budżecie 150 zł/h (prod 30.09). Źródła pokazujemy
  najwyżej 3 (`view.MAX_SOURCES`, `SourceLinks`); research zapisuje ich więcej.
- **Poprawki biblioteki ról i słowniczka: admin + Head of Recruitment**
  (`HeadOfRecruitmentPlus`, historia `plain_knowledge_events`, `origin=manual`).
  Opis klienta nadal edytuje karta klienta (DL/admin); ręczny zapis zdejmuje `web`.
- **Zasiew z repo** (`app/data/plain_knowledge/terms.json`, `roles.json`) biegnie
  w migracji i przy każdym starcie; nadpisuje wiersze `seed`/`ai`, nigdy `manual`.
  Opisy klientów NIE trafiają do repo (repo publiczne) — `scripts/build_plain_knowledge.py
  --apply-clients` na produkcji. Bazę startową buduje ten sam skrypt (`--plan`
  → przegląd arkusza → `--write-seed`).
- **Scalona rola pamięta inne nazwy** (`match_rules.title_alternatives`, lista
  zestawów słów): „Tester automatyzujący” trafia też w „Test Automation Engineer”.
  Zestaw złożony z samych ogólnych słów („developer”, „it”) nie trafia do listy —
  pasowałby do każdej rekrutacji. `--write-seed` wycina źródła z domen klientów
  (słowo z nazwy klienta w adresie) — w repo nie ma nazw klientów.
- **Rola z całym tytułem wygrywa z rolą dopasowaną częściowo** (`best_role`,
  30.09.2026): „Senior IT Automation Tester” szedł do „ETL Tester” (samo
  „tester” + jedyna umiejętność SQL). Zmiana wagi punktów zamiast tej reguły
  psuła inne role (13× Python Developer → DataStage) — mierz na produkcji
  wszystkie rekrutacje przed zmianą matchera.
- **„Jak wygląda rekrutacja u klienta?” to etapy dla kandydata** — zasady
  wysyłki CV z karty klienta (nazwa pliku, notatka) wycina `candidate_facing`.
