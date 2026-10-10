# Profil Championa — sześć sekcji + karta klienta (przebudowa 09.2026)

Szablon skrócony do sześciu sekcji: **1. Podstawowe informacje · 2. Co wpisać
(search) · 3. Stack technologiczny · 4. O projekcie · 5. Pytania screeningowe ·
6. O kliencie**. Powód: Delivery Leadowie opisywali 80% starego profilu jako
szum. Sekcja 6 niesie WYŁĄCZNIE treść zależną od roli (co przekona kandydata
do tej oferty, insight konsultanta, historyczne pytania, branże). Standardy
klienta i dokumenty żyją w **karcie klienta** (`client_playbooks`, osobna
sekcja niżej), nie w profilu rekrutacji. Schemat `app/schemas/champion.py`
(nadal deklaruje siedem sekcji — patrz niżej), warstwa odczytu
`app/services/champion_view.py`, wzór Word `scripts/generate_champion_template.py`.

- **Skrócenie „O projekcie" do 2 zdań jest bezpieczne WYŁĄCZNIE dzięki sekcji 3.**
  Do 09.2026 jedynym maszynowym sygnałem wymagań dla oferty z Championem był
  `_extract_skills_from_champion` — regex po prozie, szukający 153 kanonicznych
  skilli i 277 aliasów. Im mniej tekstu, tym mniej trafień, więc samo skrócenie
  narracji byłoby regresem retrievalu (Champion ma zmierzony wpływ: P@5 +67%,
  R@20n +87%, 15.08). Strukturalny stack usuwa zgadywanie: `_extract_skills_from_champion`
  ma teraz **Tier 0**, który zwraca `stack.must` wprost i nie dotyka regexa.
  **Nie skracaj sekcji 4 w oderwaniu od wypełnionej sekcji 3.**
- **Nazwy spoza taksonomii przechodzą surowe.** Delivery Lead wpisujący technologię,
  której nie ma w alias mapie, opisuje realne wymaganie, nie literówkę — odsianie
  jej zamieniłoby jawnie podane wymaganie w ciszę.
- **`PUT .../champion-profile` synchronizuje stack do `Job.must_skills`/`nice_skills`.**
  Kolumny wygrywają wszędzie indziej (scoring, `requirement_map` = kafelki
  interaktywnego CV, filtry wyszukiwarki) i są puste na ~88% ofert. Stack wpisany
  i niezsynchronizowany byłby niewidoczny dla wszystkiego, co go naprawdę czyta.
- **Zapis z UI kasował 12 z 16 pól sparsowanego dokumentu** — do 09.2026
  `ChampionProfile` nie deklarowało kluczy zapisywanych przez parser, a Pydantic
  z domyślnym `extra="ignore"` wyrzucał je przy `model_dump()`. Ginęły m.in.
  `rate_value` (twardy sufit stawki w `dealbreaker_filters`) i `seniority_min_years`
  (kara seniority, zmierzona +4% P@5). Objaw był **niewidoczny**: profil dalej się
  otwierał, tylko dwa filtry cicho przestawały działać. Nowy schemat zna wszystkie
  te pola, a handler dodatkowo scala payload NA zapisanym profilu.
- **Migracja jest LENIWA, przy odczycie** (`model_validator(mode="before")`), nie
  jednorazowym przepisaniem JSONB. 949 ofert niesie stary kształt; przepisanie
  wsadowe jest odwracalne tylko z kopii, której off-site nie mamy.
- **Kolejność w `PUT` jest load-bearing: NAJPIERW normalizacja starego profilu,
  POTEM nałożenie payloadu.** Migracja uzupełnia PUSTE pole nowej sekcji wartością
  ze starego klucza — to jej sens. Gdyby scalać wprost na surowym profilu,
  wyczyszczenie frazy w edytorze nigdy by się nie zapisało, bo migracja wpisywałaby
  ją z powrotem z `sourcing.keywords`. Scalanie jest o jeden poziom w głąb: klient
  API wysyłający samo `{"basics": {"language": "EN"}}` nie może zgubić stawki.
- **Konsumenci czytają WYŁĄCZNIE przez `champion_view`** (scoring, `canonical_text`,
  `embedding_service`, generator CV, Talent Radar, uzasadnienia dopasowań,
  `champion_draft_service`). Odczyt wprost widzi jeden kształt — ten, którego akurat
  nie ma w bazie — i zwraca pustkę nie do odróżnienia od „nie ma takich danych".
- **`embedding_parts` jest CELOWO węższe niż `narrative_parts`.** Dla starego profilu
  zwraca dokładnie `about` + `responsibilities` + `selling_points`, czyli bit w bit
  to samo co przed przebudową: wektory 949 ofert nie drgnęły, indeks nie wymaga
  przeliczenia, a przebudowa formularza nie miesza się w pomiarze ze zmianą
  retrievalu. **Rozszerzenie tego zakresu (o pytania screeningowe, słowa kluczowe)
  jest osobną zmianą jakości wyszukiwania i wymaga własnego A/B** — pilnuje tego
  `test_embedding_text_for_legacy_profile_is_unchanged`.
- **Parser dokumentu rozpoznaje sekcje po NAZWACH nagłówków, nie po numeracji**
  (`_NUM` jest opcjonalne). Przenumerowanie jest bezpieczne, **przemianowanie nie**.
  Stare nagłówki ZOSTAJĄ obok nowych („Pytania od Delivery Leada" wystąpiło w 783
  z 1095 sparsowanych dokumentów, a po firmie krąży kilkaset kopii starego wzoru).
  Zdjęcie któregokolwiek zamieniłoby te pliki w CV bez sekcji — po cichu, bo brak
  sekcji jest u nas poprawnym wynikiem, nie błędem. Pilnuje tego
  `test_champion_template_agenda.py` czytający tytuły WPROST z generatora wzoru.
- **Prompt parsera to v6** (`champion_parse:v6:haiku-4.5`), opisuje TRZY układy
  (6 sekcji, 7 sekcji, stary) i NIE wydobywa pól karty klienta
  (`client.about/priority_rules/offlimit/contract_type/cv_language`, `documents`)
  — `build_champion_dict` emituje dla nich puste wartości, a kształt siedmiu
  kluczy JSONB zostaje (konsumenci czytają `.get()`, test kształtu tego pilnuje).
  `schemas/champion.py` CELOWO nadal deklaruje te pola: migracja leniwa starych
  profili i 949 wierszy produkcji. `ingest_parsed_profile` czyta skille
  z `stack.must` **oraz** z płaskiego `must_skills` — czytanie jednego kształtu
  zepsułoby albo każdy nowy dokument, albo każde ponowne przetworzenie starego,
  a objaw byłby ten sam i cichy.
- **Publiczna karta Championa dostaje WĄSKĄ projekcję**, nie surowy JSONB
  (`_public_champion_projection`). Do 09.2026 endpoint zwracał cały profil, więc
  każdy z linkiem miał w JSON-ie także NASZĄ stawkę dla kandydata, firmy docelowe,
  dyskwalifikatory i reguły priorytetu klienta — niewidoczne na ekranie, ale obecne
  w odpowiedzi, a odbiorcą linku jest strona trzecia.
- **Notatkę meetingową podpina do rekrutacji JEDNA bramka**
  (`services/note_job_link.ensure_note_linkable_to_job`, UAT M03-B13): „Powiąż
  + AI” i briefing DL odmawiają 422 notatki podpiętej do innej rekrutacji oraz
  notatki kandydata spoza pipeline'u tej rekrutacji. Bez tego rozmowa
  z kandydatem innego klienta trafiała do cudzego profilu Championa i do AI.
  Panel „Meetingi bez powiązania” pyta `GET /api/notes?unattached=true`.
- **Weryfikacja dwustronna i briefing DL NIE są sekcjami** — mają własne
  endpointy, są server-stamped i zwykły zapis profilu ich nie dotyka. Trzymanie
  ich poza siódemką jest decyzją produktową (19.08→09.2026), nie przeoczeniem.
  Rekomendowane wyszukiwania (AI) usunięte 25.09.2026 — klucz
  `recommended_searches` zostaje w JSONB jako dane historyczne bez konsumenta.
- **Etykiety pól mówią to, co robi kod (rewizja 09.2026).** „Lokalizacja biura",
  nie „kandydata" — `scoring_service._score_location` porównuje
  `basics.candidate_location_pref` z miastem KANDYDATA, więc pole od zawsze
  znaczyło „dokąd trzeba dojechać", a stara etykieta mówiła coś odwrotnego.
  **Klucz w JSONB zostaje historyczny**: przemianowanie to migracja 949 profili
  i ośmiu konsumentów po to, żeby użytkownik zobaczył dokładnie to samo.
- **Dwa różne języki, dwa pola.** `basics.language` to JĘZYK PRACY wymagany od
  kandydata (zasila wektor oferty); `ClientCvRule.cv_language` to język
  DOKUMENTU CV — per klient i to jego słucha generator. W edytorze język CV jest
  **tylko do odczytu**, bo edytowalne pole obok reguły klienta byłoby drugim
  źródłem prawdy, które przy pierwszej zmianie zaczyna kłamać.
- **Wzór Word NIE ma ramki standardów ani sekcji „Dokumenty"** — wskazówka pod
  nagłówkiem sekcji 6 kieruje do karty klienta w NEXUSIE. Do 09.2026 ramka
  „Standardy tego klienta" i sekcja 7 niosły treść per klient kopiowaną do
  każdej rekrutacji; teraz ma ona jedno miejsce.
- **Wzór Word leży na SharePoincie, nie w repo** — NEXUS trzyma do niego wyłącznie
  link (`help_materials`). Jest JEDEN, ogólny; 14 wzorów per klient wycofano
  z Pomocy migracją 0272 (`is_published=false`; wiersze zostają, bo przegląd
  reguł CV linkuje je po slugu; pliki na SharePoincie zostają w bibliotece).
  Generator: `scripts/generate_champion_template.py --out-dir …` (bez
  `--client`/`--all`).
- **Treść kliencka dawnych wzorów żyje w `app/data/client_playbooks/seed.json`**
  — źródło seeda migracji 0272 i lustra w entrypoint. Dawny
  `scripts/champion_template_clients.json` został usunięty po jednorazowej
  konwersji skryptem `scripts/build_client_playbook_seed.py`, który sprawdza
  KOMPLETNOŚĆ: każda linia 14 wzorów musi trafić do karty (inaczej pada).
- **Walidacja szkicu v4 (#1477) jest doradcza: `CHAMPION_INTAKE_GATE_ENABLED`
  (domyślnie OFF, #1481).** Włączona blokuje search, handoff i generację CV
  (`enforce_operation` → 422 „Profil Championa wymaga poprawy przed
  użyciem”) dla profili ostemplowanych `policy_version=1` — a stempel dostaje
  każdy profil przy zapisie zmieniającym treść, klonowaniu oferty, imporcie
  z Traffita i akceptacji draftu AI. 10.09 zablokowało to pracę zespołu, stąd
  domyślne OFF.
- **Zapis profilu normalizuje TYLKO zmienione pola (od 11.09.2026).**
  `prepare_profile(previous=…)` porównuje z zapisanym profilem; pole, którego
  użytkownik nie ruszył, zostaje takie, jakie było. Do 11.09 każdy zapis
  (niezależnie od flagi bramki) zerował stawkę podaną zakresem i wycinał z
  `jobs.must_skills` pozycje MUST dłuższe niż 12 słów/120 znaków. Teraz:
  pozycje stacku nigdy nie znikają z powodu długości (tylko flaga), limit
  pozycji 500 znaków, dłuższa zostaje w `unresolved`.
  `requirement_contract.contract_names` przycina nazwę do 100 znaków — bez tego
  must-have dłuższy niż 100 znaków wywalał walidację KAŻDEGO wyszukiwania tej
  rekrutacji. `jobs.py` porównuje intake po normalizacji, więc zapis bez zmian
  nie robi zapisu ani powiadomienia.
- **Stawka: NIEZMIENIONA liczba nigdy nie jest wyliczana ponownie z tekstu**
  (`prepare_profile(previous=…)` porównuje ją jako liczbę, niezależnie od
  `rate_raw` w żądaniu): zostaje zapisana wartość, tekst i notatki. Kopia
  rekrutacji (`from_job_id`) przenosi stawkę tak, jak była zapisana. Bez tego
  „Uzgodnij profil i pola rekrutacji”, import dokumentu na rekrutację, która ma
  już stawkę, i kopia rekrutacji kasowały budżet profilom z importu 08.2026
  („140 zł netto/h” itp.), a przy zaznaczonej synchronizacji także
  `jobs.rate_budget_hourly` — z którego czytają dealbreaker stawki i scoring
  (przegląd adwersarialny drugiej rundy, 11.09).
- **Tekst ŚWIEŻEGO dokumentu jest źródłem prawdy o stawce** (`document_rate`,
  `pln_hourly_bounds` w `champion_intake.py`; parser AI, komórka formularza
  Word v4, tekst odesłany przez okno importu przy nietkniętej stawce
  z dokumentu): jedna wartość PLN/h → budżet; zakres „120–140 zł/h”, „120/140”,
  „od 120 do 140” albo „do 140” → GÓRNA granica z notatką w `intake.advisory`
  (pole to „Maksymalna stawka PLN/h”, a dealbreaker czyta je jako sufit —
  środek zakresu z parsera zaniżał budżet). Gramatyka przyjmuje netto/+VAT/
  „(netto, B2B)”, „zł/godz.”, „za godzinę”, „PLN 140/h”. Inna waluta, stawka za
  dzień/MD/miesiąc, brutto, brak jednostki → `unresolved` + `missing_budget`,
  budżet pusty. Liczba wpisana ręcznie (bez tekstu) jest budżetem bez notatki.
  Okno importu (`ChampionIntake.tsx`) odsyła `rate_raw` WYŁĄCZNIE przy imporcie
  dokumentu (`sourceIsDocument`), nigdy przy uzgadnianiu zapisanego szkicu.
- **Walidacja sprawdza profil tak, jak jest zapisany.** Wymagania odłożone do
  `intake.unresolved` wracają do stacku wyłącznie przy zapisie, który edytuje
  ten stack — `validation()` ich nie wskrzesza (wskrzeszanie dawało fałszywy
  konflikt z kolumnami rekrutacji, który przy włączonej bramce blokował search).
  Odłożony MUST, którego obecny normalizator nie przyjąłby (np. dłuższy niż
  limit pozycji), daje OSTRZEŻENIE — nigdy błąd ani blokadę. Konflikt kolumn
  NICE to ostrzeżenie, nie błąd.
- **Pusty ZAPISANY stack MUST/NICE dziedziczy kolumny rekrutacji** (17.09.2026,
  lustro `missing_role` → `job.title`): `validation()` czyta wtedy
  `effective_skill_names(job, key)` zamiast zgłaszać `missing_requirements`/
  `missing_must` na profilu, który po prostu jeszcze nie ma swojego stacku —
  `ineligible_must` liczy się wtedy na liście odziedziczonej, a
  `skill_column_conflict` pomija klucz, którego zapisana lista jest pusta
  (dziedziczenie nie jest konfliktem). `job_handoff_blockers`
  (`job_readiness.py`) dodatkowo pomija kody z `_MIRRORED_VALIDATION_CODES` —
  te same braki (rola, klient, kontekst, pytania, must-have, budżet, tryb
  pracy, dni/miasto biura) inaczej wychodziły DWA RAZY, raz jako zdanie
  briefu/rubryki, raz jako issue Championa; realne dodatki (`column_conflict`,
  `skill_column_conflict`, `unresolved_value`, `ineligible_must`, ...) zostają.
  `response_context()["job_values"]` niesie też `role_name` (= `job.title`) i
  `deadline` (ISO) — `fingerprint()` obejmuje `deadline`.
