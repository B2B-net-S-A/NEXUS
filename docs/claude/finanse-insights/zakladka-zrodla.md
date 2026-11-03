# Zakładka „Źródła” w Insights: portale i strona kariery, osoby za liczbą
<!-- indeks: tabela Pracuj.pl, JustJoin.IT i RocketJobs, linki; klik w liczbę → osoby w panelu; „Zakres dat” w PeriodPicker; job_id puste w zgłoszeniach z portali; RocketJobs razem z JJIT -->

Decyzje Artura z 03.11.2026 (makiety: https://claude.ai/artifact/2m3SkTySwxqseDyp7fBH4H).
Wcześniej odpowiedź na „ilu mamy kandydatów z Pracuj.pl i linków” leżała w raporcie
„Źródła, portale i linki” 2150 px pod sekcją o scraperach, za haczykiem „Grupuj po UTM”,
pod kodami `pracuj` i `jjit`, a za liczbami nie było osób.

Kod: `api/insights_sources.py`, `services/insights_sources.py`, front
`components/insights/views/ZrodlaView.tsx`, `sections/SourcesPeoplePanel.tsx`.

- **Miejsce:** zakładka między Firmą a Raportami. Start Insights zostaje na Rywalizacji.
  Raport „Źródła, portale i linki” zostaje ze stanem scraperów i błędami importu, a stary
  link `#zrodla` prowadzi do zakładki.
- **Osoby w panelu z boku**, nie pod wierszem: tabela zostaje na miejscu i przy 1280 × 720
  mieści się 11 osób zamiast 4. Klik w źródło rozwija ogłoszenia portalu, a u ról
  z wglądem w cudze wyniki rekruterów albo rekrutacje linków.
- **Liczba i lista to ten sam SQL.** Flagi biorą się z jednego CTE (`flags`), więc liczba
  po kliknięciu zgadza się z listą. Gdy dane zmienią się po policzeniu tabeli (cache 5 min),
  panel pisze obie liczby. Nie ukrywaj tego zdania. „Zgłoszenia” portalu mają wiersz na osobę,
  więc porównują się z `total_applications`, a panel pisze „N zgłoszeń od M osób”.
- **Etap portalu jest po osobie, nie po rekrutacji.** Zgłoszenie z portalu ma `job_id`
  puste, bo ogłoszenie na portalu nie jest połączone z rekrutacją. „CV wysłane” znaczy: po
  pierwszym zgłoszeniu w oknie osoba doszła do CV, w dowolnej rekrutacji. Ściślejszy pomiar
  da się zrobić tylko dla par z auto-matchem (`integration_run_events.matched_jobs`):
  staging 12.10–02.11 daje 9 CV zamiast 68 dla Pracuj.pl. Stąd „Jak liczymy?” przy tabeli.
- **Stempel `max(first_reached_at)`, nie `min`:** `analytics_first_milestones` ma wiersz na
  parę, a osoba zweryfikowana rok temu w innej rekrutacji i znowu po zgłoszeniu ma się
  liczyć. Etap sprzed zgłoszenia się nie liczy.
- **Linki idą regułą „Kto co przyniósł”** (`activities.applied_via_invite`, etap
  w rekrutacji linku, przy linku ogólnym w dowolnej), a nie z `candidate_source_events`:
  te dwa źródła różnią się o pojedyncze zgłoszenia, a obie sekcje stoją na jednym ekranie.
  „Osoby” liczą kandydata raz, pozostałe liczby są po zgłoszeniu.
- **RocketJobs razem z JustJoin.IT** (decyzja Artura 03.11.2026). Scraper zna portal
  ogłoszenia (`job_ad_board`), ale wysyła zawsze `utm_source=jjit`, a ogłoszenie z panelu
  JustJoin.IT wisi też pod rocketjobs.pl. Rozdzielenie to zmiana w scraperze poza repo.
- **Najdalszy etap** układa się kolejnością Tablicy (`_STAGE_RANK`): `interview` należy do
  kolumny „Zweryfikowany” i stoi przed `cv_sent`. Kolejność enuma daje tu zły wynik.
- **Dostęp:** trasy jak `GET /api/reports/sources` (`CandidatePIIAccess`), Rada nadzorcza
  zakładki nie ma. Rozbicie linków i filtr po właścicielu tylko `LinkResultsManager`
  (admin, Head of Recruitment, Delivery Lead), bo to cudze wyniki; pozostali dostają listę
  bez właściciela linku. Tytuł rekrutacji widać bez zawężania, bo każda rola z
  `CandidatePIIAccess` omija bramkę członkostwa (`_JOB_MEMBERSHIP_BYPASS_ROLES`). Eksport
  listy mają role z `LinkResultsManager`.
- **Okno:** domyślnie ostatnie 30 dni, przycięte do 12.10.2026 (`board_start`). Przycisk
  „Zakres dat” jest we wspólnym `PeriodPicker`, więc działa też w Zespole, Firmie
  i Raportach. Backend i tak przyjmował `period=custom`.
