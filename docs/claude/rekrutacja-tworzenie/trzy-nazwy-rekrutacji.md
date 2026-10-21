# Trzy nazwy rekrutacji (0380, 25.09.2026)

Decyzja Artura: rekruter ma widzieć, czego szukamy, a klient dostaje swoje nazwy.

- **`jobs.title` = nazwa od klienta** — bez zmiany znaczenia: idzie do klienta
  (stanowisko w CV, nazwa pliku, Cpro) i do wektora oferty, podobnych
  rekrutacji i strony kariery. Tytuł dla rekrutera tam NIE wchodzi (zmiana
  wektorów = osobne A/B).
- **`client_reference`** = numer zapytania klienta (ZOB, SAP…). Numer projektu
  w CV (`cv_packages.pko_job_reference`) czyta go przed regexem ZOB z tytułu;
  podpowiedź w generatorze dostaje każda reguła z `require_project_ref`.
  Kolejka Cpro kopiuje go do schowka. Bez UNIQUE.
- **`working_title` + `working_title_auto`** = tytuł dla rekrutera, składany
  KODEM (`services/job_working_title.py`, lustro `lib/job-names.ts`, wspólny
  `__fixtures__/job-working-title-cases.json`): rola · 2 must · N+ lat ·
  dziedzina „must”. Przelicza się przy zapisie Championa i PATCH
  `title`/`must_skills`, dopóki nikt go nie wpisze ręcznie; PATCH z pustym
  przywraca automat. Ekrany wewnętrzne pokazują `working_title ?? title`
  (`jobDisplayTitle`, SQL `job_display_title_expr`); nigdy do klienta.
- Odczyt maila (`JOB_REQUEST_INTAKE` v3) daje `client_title`/`client_reference`
  wyłącznie jako dosłowny cytat (`_in_text`) i `working_title_suggestion`.
- Kolumny są w `NEXUS_OWNED` (Traffit ich nie pisze). Istniejące rekrutacje
  uzupełnił jednorazowy krok `job-names-backfill` w `entrypoint.sh`.

## Rekrutacje osoby na ekranach kandydata (16.10.2026)

Zgłoszenie Artura: w nagłówku rekrutacja to „numer + tytuł dla rekrutera”, a profil
i listy kandydata pokazywały samą nazwę od klienta, więc nie dało się ich połączyć.

- **Odpowiedzi kandydata** niosą `job_working_title` i `job_client_reference` obok
  `job_title`: lista (`active_recruitments`), szybki podgląd, `/history`, oś czasu,
  `GET /api/notes`. `job_title` dalej = nazwa od klienta (profil rozpoznaje z niej kody
  CV dla klientów). Wyjątek: `LastRecruitment.job_title` (okno dodawania) od początku
  jest tytułem dla rekrutera, obok idzie tylko `job_client_reference`.
- **Kształty rekomendacji**: `_shape_seek_job` („Szukają projektu”) ma `working_title`
  i `client_reference`; `title` zostaje dla maila z listą rekrutacji. Te same pola
  w `_shape_recommended_job` („Moi ludzie”, propozycje na profilu) dokłada PR okien
  wyboru rekrutacji.
- **Front:** wiersz = `JobNameLabel` (`components/v2/jobs/JobNameLabel.tsx`: numer
  kopiuje, `copyable={false}` wewnątrz innego przycisku, `stretched` dla wiersza-linku,
  `wrap` gdy tytuł ma się łamać), tekst = `jobNameText` (`lib/job-name-text.ts`),
  pola kandydata → `candidateJobNames`. Okna, które mówią do klienta (generator CV,
  podgląd CV, maile), dostają dalej `job_title`.
- `_enriched_select()` w `api/notes.py` ma stałą kolejność kolumn — API integracyjne
  rozpakowuje ją po pozycjach; nazwy dokłada lista notatek przez `add_columns`.

## Numer u klienta na ekranach i z nazwy od klienta (15.10.2026)

Prośba DL Nordei: tytuły dla rekrutera są uogólnione, więc bez numeru requestu
nie wiadomo, która rekrutacja to który projekt. Decyzja Artura: wariant A
i D1–D6 z makiet https://claude.ai/artifact/NWv2twJNrZkp9c5x8ruAwz, dla
wszystkich klientów.

- **Gdzie widać numer** (`ClientReferenceChip`): przed nazwą w wierszu listy
  `/jobs`, w linii 1 nagłówka rekrutacji (też po „Zwiń”), w miejscu ikony na
  szynie „Otwarte karty” (`Tab.reference`, `openTab(…, reference)`)
  i w okruszkach. Klik kopiuje cały numer. Kilka numerów (jedna rekrutacja
  na kilka zapytań) zapisujemy „42928, 42927”, a znacznik pokazuje pierwszy
  i „+N” (`clientReferenceParts`). Lista szuka po numerze od 0380.
- **Formaty z nazwy od klienta** (`reference_from_title`, zmierzone na
  produkcji): ZOB (PKO, jak od 0380), `RITM…` (BNP), `PKN…`/`EITE…` (Orlen,
  Energa), 4–6 cyfr w nawiasie (Nordea „(42946)”, Alior „(6762)”). Wygrywa
  pierwszy format, który coś znajdzie. Rok 1900–2099 i końcówka naszego numeru
  („…/IT/4918”) to nie numer klienta. eZdrowie i klienci bez numeru w nazwie —
  pole wpisuje się ręcznie („Edytuj” → „Numer u klienta”). Nowy format klienta
  = nowy wzorzec w tej funkcji i przypadek w `test_job_working_title.py`.
- **Nowe rekrutacje** (D5): numer w znanym formacie z cytowanej nazwy wygrywa
  z numerem od modelu, gdy ten nie jest w znanym formacie (model brał
  „PEP4989”, „TP#…” zamiast „(42970)”). Kilka numerów nie jest cytatem — pole
  zostaje puste, a serwer przy zakładaniu czyta je z nazwy.
- **Jednorazowe uzupełnienie**: krok `client-reference-from-title` w
  `entrypoint.sh` (`fill_client_references_from_titles`, marker
  `client_reference_from_title_2026_10`, paragon same liczby). Wypełnia puste
  pola; nadpisuje tylko kod PEP/TP, gdy nazwa ma numer w nawiasie (D4), i zdejmuje
  nawiasy z „(42855)”. `updated_at` bez zmian. Puste pole bywa też numerem
  usuniętym ręcznie — po tym kroku wraca, jeśli stoi w nazwie.
- **Tytuł dla rekrutera bez klienta i numeru** (D6): rola z Championa traci
  prefiks klienta i swój numer („Nordea: Expert IT Analyst … (42758)” →
  „Expert IT Analyst …”), ale nie każdy nawias z cyfrą („(K8s)” zostaje).
- Dzwonek Cpro (`_cpro_job_label`) nie dokleja numeru, który już stoi w nazwie.

## Okna wyboru rekrutacji nazywają ją jak nagłówek (16.10.2026)

Zgłoszenie Artura: w „Przypisz do rekrutacji” rekrutacja nazywała się
„AI Engineer (ZOB-…)” (nazwa od klienta), a jej nagłówek mówi „Senior AI
Engineer · Java, LLM · 5+ lat”. W tym samym oknie „Ostatnio otwierane”
pokazywało już tytuł dla rekrutera (z karty), a reszta — `jobs.title`.

- **Wiersz wyboru** = `JobPickName` (`components/v2/jobs/JobPickName.tsx`):
  numer u klienta jako etykieta (nie przycisk kopiowania — wiersz bywa sam
  przyciskiem) + `jobDisplayTitle`. Nazwa od klienta i wszystkie numery są
  w dymku. Druga linia: klient · miasto (· seniority).
- **Gdzie**: „Przypisz do rekrutacji” (`QuickAssignV2`, wszystkie trzy
  sekcje i „AI sugestie”), `JobPicker` (lista kandydatów, wyszukiwarka,
  porównanie, „Szukaj z requestu”), „Pasuje też do” (`ClientReferenceTag`),
  wybór rekrutacji w Talent Radarze.
- **Komunikaty** („Dodano … do „…””, „Nie przypisano do …”, „Dodaj do „…””,
  „Przywrócono …”) biorą `jobDisplayTitle`.
- **API**: AI sugestie (`_shape_recommended_job`) oddają `working_title`,
  `client_reference` i `client_name` (klient przez `selectinload(Job.client)`);
  „Pasuje też do” oddaje `client_reference`. Pole `title` zostaje nazwą od
  klienta.
- `JobPickerJob.title` to nadal nazwa od klienta (z karty: tytuł dla
  rekrutera) — ekran, który pokazuje wybraną rekrutację, bierze
  `jobDisplayTitle(job)`, nie `job.title`.
- Listy, w których osoba już jest (profil → Rekrutacje, „ostatnio: …”
  w oknie dodawania, „Moi ludzie”), robi osobny PR.

## Numer u klienta nie może być nazwą roli (21.10.2026)

Nordea 20.10.2026: nazwa „PL_IT_Developer_expert_TP#40379 (43020)”, a numer
u klienta „PL_IT_Developer_expert_TP#40379”. `cv_role_title` wycinał numer
z nazwy i zostawał sam „(43020)” — cztery CV dostały nagłówek
„(43020) – Imię Nazwisko”, a QC przepuszczało je, bo nagłówek z payloadu
potwierdzał sam siebie.

- Numer, po którego wycięciu z nazwy nie zostaje żadna litera, to nazwa roli
  (`reference_swallows_role`). Przy zapisie (`POST`/`PATCH /api/jobs`,
  odczyt maila) ustępuje numerowi z nazwy (`client_reference_for_title` →
  `reference_from_title`) albo pustce. Lustro na froncie: `clientReferenceFor`.
- `cv_role_title` nigdy nie zwraca nagłówka bez liter, gdy nazwa je ma —
  wtedy liczy rolę z pełnej nazwy, ignorując numer.
- QC CV nie uznaje nagłówka bez liter za zgodny tytuł.
