# Insights (`/insights`) — parytet z DynaReporterem na danych NEXUSA

`/insights` odtwarza raporty DynaReportera (`infrareporter.onrender.com`)
**licząc je od zera z operacyjnych danych NEXUSA**, a nie z wchłoniętych tabel
`dr_*` (te są zamrożone: `dr_*` stanęły na tygodniu 21/2026, `clients-mrr` jest
puste, a finanse zarządu mają `0.0` we wszystkich 36 miesiącach). Zakres:
Rekrutacja · Liga Mistrzów · Delivery Lead · Klienci/MRR · Zarząd. **Poza
zakresem świadomie:** Sales, AI Analytics, Przetargi, Premie (moduł sprzedaży).
Decyzje D1–D7 i pełna specyfikacja: `docs/insights-dynareporter-migration-plan.md`
§0 oraz `docs/insights-etap0-specs.md`.

- **PIĘĆ widoków od 24.09.2026** (makiety: https://claude.ai/artifact/Mkmo9FeBiMbhAyLBgxNh3Q;
  do tego dnia 2 zakładki i 27 bloków — Artur: „za dużo tego wszystkiego").
  Każdy widok odpowiada na JEDNO pytanie, ma najwyżej cztery kafle z punktem
  odniesienia i jedno zdanie wniosku (`lib/insights-views.ts`, czyste funkcje):
  **Rywalizacja** (pierwsza dla każdego; kampania, obie Ligi Mistrzów, oba
  wyścigi miesiąca z podświetlonym wierszem zalogowanej osoby, skróty Hall of
  Fame i ścieżki — BEZ paska okresu; Artur: „Liga i wyścigi — bardzo ważne"),
  **Mój miesiąc** (role z własnymi KPI: rekruter, sourcer, TAC, DL; `/api/kpis/me/panel`,
  bieżący miesiąc, bez paska okresu), **Zespół** (kafle i lejek dla każdego;
  „Do uwagi" i tabela ludzi z przełącznikiem Rekruterzy / Delivery Leadzi tylko
  z `view_team_kpi`), **Firma** (TYLKO admin i Finanse — `FIRMA_ROLES`
  i `BoardReader`) oraz **Raporty** (`lib/insights-reports.ts` — rejestr
  z pytaniem, oknem i bramką; `?tab=raporty&report=<id>` na całą stronę).
  Widoki: `components/insights/views/`, harness `/preview/insights?as=&view=`.
  Nowa treść = najpierw pytanie, na które odpowiada; jeśli nie jest jednym
  z czterech pytań widoków, to jest raport, nie kolejny blok na widoku.
- **Head of Recruitment NIE widzi pieniędzy (decyzja Artura 24.09.2026).**
  `BoardReader` = admin + finance (`/board`, `/clients/ranking`, narzędzie
  Jarvisa `insights_board`); `/board/yoy` stoi na `BoardTrendReader` (+ HoR),
  a HoR dostaje odpowiedź przez `without_money` (bez metryk `pln`,
  `margin_pct` i kwot w `component_series`, `money_redacted: true`). Mail
  zarządu (`kpi_email_reports._BOARD_ROLES`) idzie tylko do admina i Finansów.
  `/api/competitions/monthly-races` nie oddaje marży/h z rozstrzygania remisu
  (`_MARGIN_EXTRAS`) — do 24.09 widział ją każdy zalogowany.
- **Tabele osób bez kont administracyjnych** (24.09.2026): Zespół → Ludzie,
  Aktywność zespołu, Analiza placementów i Time-to-hire biorą role Hall of Fame
  + Talent Community Manager (`services/insights_person_scope.py`,
  `PEOPLE_TABLE_ROLES`). Konta bez takiej roli to jeden wiersz „Konta
  administracyjne”, sumy firmy bez zmian. Nowa tabela osób = ten sam helper.
- **Precyzja (30 dni) to kohorta**: z par zweryfikowanych w 30 dniach, ile doszło
  do „CV wysłane” (`kpi_panel.PRECISION_COHORT_CTE`, Zespół i Mój miesiąc).
  Nigdy ponad 100% (do 24.09 było 900%). Konwersja w Lejku po etapach liczy się
  względem ostatniego etapu, przez który ludzie przeszli (`stageConversion`).
- **Link z widoku do raportu niesie okres** (`reportHref(id, period)`); przy
  liczbach o świadomie innej definicji (Liga DL: kwartał, rekrutacje zamknięte;
  Portfele DL: rok, wszystkie zapytania) stoi zdanie „liczone: …”. Tabela DL
  w Zespole liczy rok. „Do uwagi” cache'uje 5 min; „bez ruchu” pomija requesty
  „Zakończone” i „Klient milczy”.
- **Widok Zespół ma własne trasy** (`api/insights_team_signals.py`, capability
  `VIEW_TEAM_KPI`): `/team/people` (atrybucja verifier-anchored jak wyścigi
  i „Mój miesiąc", precyzja 30 dni, weryfikacje na dzień roboczy, placementy
  z TEGO SAMEGO odcinka poprzedniego okresu), `/team/attention` (tylko sygnały
  ponad próg: rekrutacje bez ruchu 14 dni, precyzja < 50%, słabe prepy — ostatnie
  tylko admin/HoR) i `/recruitment/stale-jobs`. Kafle bieżącego miesiąca
  porównują dni 1–N z dniami 1–N poprzedniego (`previousComparablePeriod`).
- **Tabele rok-do-roku Rady (`GET /api/insights/board/yoy`)** — dwanaście
  miesięcy × trzy lata, z deltą i kolumną „Ocena". Endpoint świadomie NIE
  przyjmuje paska okresu: patrzy na pełne lata kalendarzowe, a wpuszczenie tam
  `period`/`offset` dałoby siatkę „ostatnie 12 miesięcy" podpisaną nazwami
  miesięcy, czyli dwie różne rzeczy pod jedną etykietą. Okno wybiera się
  latami (`end_year`, `years`; 2–5, domyślnie 3).
  - **Backend zwraca WYŁĄCZNIE liczby.** Delta, „Ocena" i wiersz podsumowania
    to czysta arytmetyka w `frontend/src/lib/insights-yoy.ts` — testowana na
    wartościach, nie na zrzucie ekranu.
  - **Każda metryka niesie `aggregate`** (`sum` przepływy, `avg` stany,
    `ratio` wskaźniki, `distinct` liczności zbioru) oraz `lower_is_better`.
    Bez pierwszego widok potrzebuje własnej listy „co się sumuje", czyli
    drugiego lustra tej wiedzy — w DynaReporterze go nie było i wiersz „Suma"
    pod kolumną procentów pokazywał 874%. Bez drugiego wzrost zejść i kosztów
    dostaje zieloną strzałkę w górę, czyli komunikat odwrotny do prawdy.
  - **Wskaźnik za rok liczy się OD NOWA: Σlicznik / Σmianownik** (od 18.09.2026).
    Średnia dwunastu miesięcznych procentów to ŚREDNIA ILORAZÓW, a mianowniki
    miesięcy różnią się pięciokrotnie — miesiąc z 9 zamkniętymi rekrutacjami
    ważył tyle samo co miesiąc z 200. Zmierzone na produkcji: hit ratio 2024
    pokazywane 14,57% przy realnych 17,4% (134/770), 2025 — 16,58% przy
    realnych 14,5% (195/1342); delta zmieniała ZNAK (+2,0 pp „Lepiej" zamiast
    −2,9 pp „Gorzej"). Dlatego `ratio` niesie `components` (klucze licznika
    i mianownika), a odpowiedź osobne `component_series` — to NIE są wiersze
    tabeli. Nowy wskaźnik bez składowych = błąd kontraktu, nie brak danych
    (`test_insights_board_yoy.py`).
  - **Liczności zbioru (`unique_clients`) nie da się złożyć z miesięcy żadnym
    działaniem** — klient obsłużony w marcu i w lipcu to jeden klient.
    DynaReporter pokazywał 4,33 / 6,75 / 8,63 przy realnych 18 / 23 / 25.
    Rok przychodzi gotowy w `yearly`; wiersze miesięcy zostają miesięczne,
    bo to prawda o miesiącu. Porównania YTD ta metryka NIE ma — rok jest rokiem.
  - **Miesiąc PRZYSZŁY to `null`, miesiąc BIEŻĄCY jest oznaczony**
    (`partial_month`). Zera w kolumnie bieżącego roku czytają się jak awaria,
    a siedem dni danych — jak załamanie wyniku.
  - **Podsumowanie roku niepełnego porównuje się z TYMI SAMYMI miesiącami**
    roku poprzedniego (YTD). To jedyne miejsce, gdzie mianownik porównania jest
    inny niż liczba w komórce obok — i dlatego wiersz to mówi. **Trwający
    miesiąc nie wchodzi do YTD w żadnym z lat** (od 11.09.2026): 1 lutego YTD
    porównuje jeden pełny miesiąc, w styczniu pokazuje „—”, a wiersz „(trwa)”
    nie ma delty ani oceny. Wcześniej kilka dni bieżącego miesiąca stawało
    naprzeciw pełnego miesiąca roku poprzedniego i dawało fałszywy spadek.
  - **Pieniądze liczy `insights_board_money.fold_money`, ta sama funkcja co
    kafle** — wyniesiona z `insights_board.py` w chwili, gdy pojawił się drugi
    konsument. Kopia przechodziłaby każdy test wartości do dnia, w którym ktoś
    poprawi jedną z nich; wtedy kafel „Marża / mc" i komórka „Marża" w tabeli
    obok pokazują dwie różne kwoty pod jedną nazwą, na jednym ekranie.
    Pilnuje tego test TOŻSAMOŚCI obiektu funkcji, nie zachowania.
    **Kwoty kontraktu są zaokrąglane do pełnych złotych PRZED sumowaniem**
    (`to_whole_pln`, UAT M06-B04) — tak samo w rankingu klientów, profilu,
    portalu DL i przeglądzie admina; suma zaokrągleń ≠ zaokrąglenie sumy,
    a różnica wychodzi między kaflem a rankingiem na jednej zakładce.
    Pilnuje `test_margin_rounding_parity.py`.
  - **Rezygnacje to PODZBIÓR zejść** (`consultant_resigned`, `better_offer`,
    `personal_reasons`); `poached_by_client` świadomie poza — to klient zabiera
    człowieka, inne zjawisko i inny wniosek. Data zejścia to
    `COALESCE(end_date, terminated_at)` (od rundy 8 — pierwsze wypowiedzenie
    przeżywa aneks przedłużenia, więc nie może wygrywać z datą końca umowy).
  - **Marża na godzinę wyklucza ryczałt z LICZNIKA i MIANOWNIKA naraz.**
    Kwota miesięczna nie niesie godzin, a podstawienie 160 zamieniłoby
    wskaźnik w marżę podzieloną przez wymyśloną stałą.
  - **EWIDENCJA KONTRAKTÓW JEST MŁODSZA NIŻ FIRMA — i bez tego tabela kłamie.**
    Zmierzone na produkcji 08.09.2026: styczeń 2024 → **17** wycenionych
    kontraktów, sierpień 2026 → **452**, przy realnej liczbie ~320 konsultantów
    w 2024 (dane DynaReportera). Placementy przyszły z importu Traffita
    i sięgają lat wstecz; kontrakty zaczęły powstawać w NEXUSIE później i nie
    zostały uzupełnione wstecz. Pierwsze wydanie pokazywało to jako **+935%
    wzrostu przychodu** — liczbę arytmetycznie poprawną i semantycznie
    fałszywą. Dlatego każda metryka niesie `basis` (`contracts` | `pipeline`),
    odpowiedź niesie `coverage.contracts_by_year`, a widok stawia ostrzeżenie
    PRZY grupach liczonych z kontraktów. **Nie usuwaj tego ostrzeżenia „bo
    brzydkie" — usuń je dopiero, gdy historia kontraktów zostanie uzupełniona
    wstecz.** Ostrzeżenie stoi przy grupach, a nie jednym banerem na górze:
    Dywersyfikacja i hit ratio liczą się z pipeline'u i są porównywalne, więc
    baner zbiorczy podważałby także je, a ostrzeżenie podważające wszystko
    uczy ignorować ostrzeżenia.
  - **Poza zakresem świadomie: „Zysk" (marża − pozostałe koszty)** — NEXUS nie
    zna „pozostałych kosztów", a w DynaReporterze ta tabela była pusta we
    wszystkich 36 miesiącach. Tabela rok-do-roku NIE wchodzi też do eksportu
    CSV zakładki: tamten jest przycinany oknem z paska, a ta siatka jest
    latami — jeden plik pod jedną nazwą oznaczałby dwa różne zakresy.
- **Stare identyfikatory zakładek, rozdziałów i kotwic ŻYJĄ jako aliasy**
  (`LEGACY_TAB_ALIASES`, `LEGACY_CHAPTERS`, `LEGACY_ANCHORS` w `InsightsView.tsx`):
  `body-leasing` (+`ch=wyniki`) → Zespół, `ch=klienci`/`delivery-lead`/`klienci`
  → raport Portfele DL, `rada`/`zarzad` → Firma (bez uprawnień: raport Rok do
  roku bez kwot); stara kotwica (`#zrodla` → raport Źródła) wygrywa z aliasem.
  Nie kasuj ich: te linki są w zakładkach przeglądarki, w zapisanych
  powiadomieniach i mailach. Rozstrzyga czyste `resolveInsightsLocation`.
- **Każdy widok ma własny domyślny okres i zmiana widoku go zeruje**
  (Zespół: bieżący miesiąc, Firma: kwartał, Portfele DL: rok). Portfele stoją
  na roku, bo hit ratio stoi na rekrutacjach ZAMKNIĘTYCH w oknie, a tych
  w miesiącu jest kilkanaście na cały zespół — wskaźnik z takiej próbki
  skacze o dziesiątki punktów i czyta się jak awaria.
- **Portfele DL (`/api/insights/delivery-leads/portfolio`) liczą nagłówek DL
  i wiersze klientów TĄ SAMĄ definicją co `/delivery-leads`** — suma wierszy
  zgadza się z nagłówkiem. Nie mieszaj z `/clients/hit-ratio` (inna definicja
  hit ratio, bez filtra body_leasing).

- **`/api/insights/*` jest ODDZIELNĄ powierzchnią od `/api/reports/*`
  i `/api/admin/*`.** Tamte trasy są współdzielone z innymi stronami, więc
  poszerzenie ich guardu (D7) albo zmiana semantyki okresu zmieniałaby po cichu
  liczby i widoczność gdzie indziej. Kopiowanie SQL-a też nie: logika wspólna
  z zakładką Klienci mieszka w `services/insights_clients.py`.
- **Placement = D2: PIERWSZE `hired` dla pary (kandydat, oferta)**, czytane
  z widoku `analytics_first_milestones`. `candidate_stages` nie ma unikalności
  na `(candidate_id, job_id, stage)`, a import Traffita dopisuje wiersz na każde
  zdarzenie — liczenie surowych wierszy dubluje powroty na etap.
- **Weryfikacje i rekomendacje też liczymy per para (kandydat, rekrutacja),
  nie per osoba** (decyzja Artura 21.10.2026). Osoba zweryfikowana
  i zarekomendowana w trzech rekrutacjach to trzy weryfikacje i trzy
  rekomendacje, także tego samego dnia. Zespół zgłosił, że DynaReporter
  liczył ją raz; Artur zostawił definicję, bo każda rekrutacja to osobna
  praca. Nie deduplikuj po `candidate_id` w liczniku celów, Insights ani
  ligach. Od 12.10 do 21.10.2026 było 254 par `verified` na 210 osób
  i 220 par `cv_sent` na 187 osób.
- **`analytics_first_milestones` niesie DOKŁADNIE SZEŚĆ etapów**
  (`verified`, `cv_sent`, `interview`, `client_interview`, `acceptance`,
  `hired`). Reszta lejka idzie z `candidate_stages`. Lejek trzyma **dwie
  niezależne flagi** (`in_milestones`, `mapped_from_traffit`), bo mylą się
  w obie strony: `new`/`screening` NIE są w widoku, ale są mapowane z Traffita,
  a `acceptance`/`client_interview` są w widoku i z Traffita nie przychodzą.
  Test porównujący dwa pola TEJ SAMEJ odpowiedzi przechodzi niezależnie od tego,
  czy odpowiedź jest prawdziwa — tak ten defekt przeżył pierwsze podejście.
- **Zero mianownika to `None`, nigdy `0.0`, i nigdy nie przycinamy do 100%.**
  „Nie da się policzyć" i „policzone, wyszło zero" to dwa różne zdania
  o zespole; konwersja powyżej stu procent jest sygnałem o kolejności etapów
  w imporcie, a sufit osi go chowa.
- **Awaria NIE MOŻE renderować się jako pustka** (`resolveViewState`
  z `isSuccess`). Bez tego przerwa między ponowieniami react-query pokazuje
  awarię jako „brak danych". Dotyczy też 403: pustka czyta się jak utrata
  danych, nie jak brak uprawnień.
- **D7: `/insights` widzi KAŻDA zalogowana rola — poza widokiem Firma
  (24.09.2026, patrz wyżej).** Guard rolowy zdjęty
  z sześciu luster; `ROLE_CAPABILITIES` i middleware nietknięte. Poszerzone do
  `CurrentUser`: `/api/competitions/current`, `/monthly-races` oraz `/history`
  (ta ostatnia dopiero wtedy, gdy zyskała konsumenta — sekcję „Hall of Fame").
  Zapisy zostają wąskie: CRUD kampanii i nadawanie plakietek to `AdminUser`.
- **Ścieżka rozwoju (D6) liczy się PRZY ODCZYCIE, zero mutacji w GET.** Każdy
  poziom ma DWA alternatywne progi połączone przez LUB („6 placementów w 6
  miesięcy **lub** 12 w 12"), a **zegar eksperta jest kotwiczony na dacie awansu
  na seniora** — bez tej kotwicy jedna dobra passa kupuje oba awanse naraz
  i „ścieżka" staje się jednym progiem z dwiema nazwami. Poziom jest ZAPADKĄ:
  cichy kwartał go nie odbiera. Progi są konfigurowalne
  (`insights_scoring_config`), więc żyją w TRZECH kopiach — kod, migracje
  (`0256` + `0260`), lustro w `entrypoint.sh` — pilnowanych przez
  `test_insights_scoring_config.py`.
- **Dni robocze (D5) idą z COMPASSA** (`nexus_workdays_export` →
  `/api/internal/workdays` → `user_workday_periods`). Metryka to **dni robocze
  minus zatwierdzony urlop**, NIE „dni przepracowane" — chorobowego w źródle nie
  ma (trigger B2B go blokuje). Bez sekretów (`WORKDAYS_EXPORT_SECRET`,
  `COMPASS_WORKDAYS_*`) endpoint zwraca 503, a (usunięty 23.09.2026) Power
  Calling raportował `not_assessable` — mówił wprost, że nie wie, zamiast dzielić przez zmyśloną
  stałą (usunięte `POWER_CALLING_WORKDAYS = 5` stawiało osoby na urlopie
  na imiennej liście „poniżej progu").
- **Plakietki wygaszamy, nie kasujemy** (`user_performance_flags`, 0258):
  `is_active=false` + data i autor. Jedna AKTYWNA plakietka danego typu na osobę
  — częściowy UNIQUE `WHERE is_active`, bo pełny zablokowałby historię.
  Kontrolka admina renderuje się TAKŻE przy zerze plakietek; inaczej pierwszego
  ostrzeżenia nie da się nadać nikomu.
- **Kampania: brak kampanii → baner renderuje NIC**, nie pustą ramkę „0/0"
  (ta twierdziłaby, że kampania trwa i idzie fatalnie). Okno odwrócone odbija
  CHECK `ck_recruitment_campaigns_window` — pusty przedział dałby „0 z N"
  i „0 dni do końca", czyli liczby poprawne arytmetycznie, opisujące
  nieistniejącą kampanię.
- **Domyślny okres to `offset = -1` (poprzedni pełny miesiąc)**, nie bieżący.
  Pierwszego dnia miesiąca `offset=0` znaczy jeden dzień danych i cały ekran
  pokazuje zera, które wyglądają jak awaria.
- **Kampania: `active`/`ending` liczą się jako rezygnacja DOPIERO od dnia,
  w którym ich data końca nadeszła** (`ended` — zawsze, bo status jest
  stwierdzeniem faktu). Te dwa statusy są w katalogu po to, żeby złapać
  kontrakty przed nocnym `_promote_statuses`; bez sufitu ta sama reguła
  wciągała każdą PRZYSZŁĄ datę końca w oknie, więc trzymiesięczna kampania
  miała pierwszego dnia policzone odejścia z miesiąca drugiego i trzeciego.
  Sufit to `business_today()`, nie `CURRENT_DATE`, i wchodzi w klucz cache'u.
  Slug definicji zbumpowany do `..._v2` — baner drukuje notatkę DOSŁOWNIE,
  więc definicja, która zmieniła znaczenie pod tym samym kluczem, byłaby
  niewykrywalna dla konsumenta.
- **Wypłata konkursów = `award_order` + zamknięcie okresu (0344, decyzje
  Artura 22.09.2026).** Ekran (`compose_monthly_races`) i `freeze_competition`
  biorą kolejność nagród z JEDNEJ funkcji `award_order`: kwalifikacja →
  wykluczenie lidera kwartału, do którego należy DANY miesiąc
  (`monthly_race_excluded_user_ids`: zamrożony zwycięzca kwartału → remis
  w kwartale czekający na admina, wykluczeni wszyscy remisujący → ranking od
  początku kwartału do końca tego miesiąca) → remisy
  (`services/competition_rules.py`). Do 22.09 zamrożenie pomijało wykluczenie
  i lider Q2 dostał też nagrody miesięczne za maj i czerwiec — te okresy
  zostały świadomie bez korekty. Remisy: wyścig placementów rozstrzyga suma
  marży/h (`fold_money`, stawki z dnia placementu), brak marży albo równość
  co do grosza → admin; wyścig rekomendacji — precyzja, potem wcześniejsza
  ostatnia rekomendacja, bez admina; Liga i liga DL — każdy remis na płatnym
  miejscu → admin. Każde zamrożenie zapisuje `competition_period_closures`
  (`frozen`/`no_winner`/`tie_pending`/`tie_resolved`), więc okres bez
  zwycięzcy albo z remisem nie jest liczony od nowa. Miejsca z remisu nie mają
  wierszy podium (0 zł) do `POST /api/competitions/{type}/{period}/resolve-tie`
  (admin, baner „Remis do rozstrzygnięcia” w Rywalizacji). Autofreeze zamraża
  dopiero od 3. polskiego dnia roboczego po końcu okresu (`business_today()`)
  i, przy włączonym syncu Traffita, po udanym `__daily__` z `last_synced_at`
  późniejszym niż koniec okresu (do 22.09 zamrażał ok. 02:00 czasu PL, PRZED
  importem ostatniego dnia); kwartał zamraża przed miesiącami. Liga DL liczy
  pary (kandydat, oferta) z `analytics_first_milestones`, hit ratio =
  placementy / rekrutacje zamknięte w kwartale.
- **Wykluczone placementy (0343, decyzja Artura 22.09.2026).** Tabela
  `placement_exclusions` (jedna para kandydat × rekrutacja = jeden wiersz).
  Wykluczona para nie jest placementem w ŻADNEJ statystyce: widok
  `analytics_first_milestones` i `VERIFIER_ANCHORED_CTE` (gałąź
  `classified_stage_ranked`) pomijają wszystkie jej wiersze `hired`; inne
  etapy liczą się normalnie, `candidate_stages` nigdy nie jest kasowane.
  Reguła (`services/placement_exclusions.py` — jedyne źródło SQL dla
  migracji, entrypointu i wykrywania): seria = jedno konto z ≥ 10 pierwszymi
  zatrudnieniami pary w jednym dniu warszawskim; wykluczane są pary serii bez
  `cv_sent`, na CAŁEJ historii (na prodzie ~217 par: 12.07.2024, 26.03.2025,
  3–4.04.2025, 23.07.2025, 24–25.09.2025), a seria 24–25.09.2025 cała (także
  pary z CV). To masowe rejestracje z Traffita, nie placementy. Żadnych ID
  w kodzie. Wykrywanie po pełnym imporcie Traffita i w pętli
  `competition_autofreeze` przed zamrożeniem; nigdy nie zdejmuje wykluczeń.
  Nowy licznik czytający `hired` wprost z `candidate_stages` MUSI dostać
  `not_excluded_placement(...)` (surowe SQL — `excluded_hired_sql(alias)`).
  Lista: `GET /api/admin/placement-exclusions`, Ustawienia → System →
  „Wykluczone placementy”. Kreator metryk pulpitu przypisujący ruchy ludziom
  (moje / zespół / po rekruterze) kredytuje jak „Moje KPI”
  (`VERIFIER_ANCHORED_CTE.credit_user`); liczby całej firmy liczy z widoku.
- **Hall of Fame liczy TAK SAMO jak „Analiza placementów" (D2), ale INACZEJ
  niż wyścigi, które płacą.** Od 2026-09-01 `competitions.hall_of_fame` czyta
  `analytics_first_milestones.first_moved_by` — pierwsze wejście pary
  (kandydat, oferta) na etap „Zatrudniony", przypisane osobie, która ten etap
  przesunęła. `monthly_most_placements` i mistrzowie kwartału ZOSTAJĄ przy
  `_rank_recruiters_by_stage` (verifier-anchored): wypłacają 1500 zł i
  10 000 zł, mają zamrożoną historię, a ich docstring mówi wprost, po co ta
  atrybucja istnieje — „pozwalało osobie klikającej końcowy etap przejąć
  credit pierwszego verifiera". **Nie reużywaj `_rank_recruiters_by_stage`
  w Hall of Fame i nie ruszaj `VERIFIER_ANCHORED_CTE` „przy okazji"** — to
  jedyne dwie ścieżki, którymi ta zmiana mogłaby ruszyć pieniądze. Hall of
  Fame ich nie rusza: `_prize_for` daje mu 0, autofreeze go nie zna
  (`competition_autofreeze.py` mrozi cztery inne typy), żaden ekran nie woła
  `POST /freeze`, a `competition_winners` dla `hall_of_fame` jest puste
  (sprawdzone na produkcji 2026-09-01).
- **Zakres ról jest tym, co oddziela „kto dowiózł" od „kto kliknął".**
  `HALL_OF_FAME_ROLES` = sourcer, tac, recruiter, delivery_lead,
  head_of_recruitment — świadomie SZERSZY niż w wyścigach (te trzymają się
  sourcer/tac/recruiter i nie wolno ich zlać w jedną listę). Konta `admin`
  zostają poza rankingiem, bo w ostatnim roku pięć z nich zebrało **147 z 314
  placementów przy CZTERECH weryfikacjach łącznie** — to podpis masowego
  domykania pipeline'u. Delivery w tym samym oknie: 69 placementów przy 2186
  weryfikacjach, czyli praca, którą wąski filtr wyścigów by wyciął.
  Odpowiedź niesie `scope` (ile w rankingu, ile poza nim), bo TOP 5 bez tej
  liczby czyta się jako całość bazy.
- **Kod definicji jest DOKŁADNIE ten sam string** co w `/placement-analysis`,
  `/insights/board` i banerze kampanii: `first_hired_per_candidate_job`.
  Własny wariant („..._by_mover") wygląda precyzyjniej, a daje maszynowo
  „różne" tam, gdzie reguła jest identyczna — czyli odwrotność tego, do czego
  to pole służy. Dwie powierzchnie liczą to jednak DWOMA osobnymi
  zapytaniami, więc wspólny kod jest tylko obietnicą: pilnuje jej test, który
  porównuje obie odpowiedzi liczba po liczbie
  (`test_hall_of_fame_agrees_with_placement_analysis_number_by_number`).
- **Hall of Fame NIE filtruje `is_active`.** Ranking wszech czasów mówi, co
  ktoś osiągnął — odejście z firmy tego nie cofa. Byli pracownicy zostają
  z chipem, tak jak w tabeli „Performance per osoba" na tym samym ekranie.
  `is_active` jedzie w `extras` i przez `CompetitionRankingEntry`, żeby dało
  się ich OZNACZYĆ zamiast ukryć.
- **Testy jednostkowe `hall_of_fame` mockują `db.execute` i asertują KSZTAŁT
  SQL-a — nigdy go nie uruchamiają.** Literówka w nazwie kolumny przeszłaby
  przez nie na zielono, a 500 zobaczyłby użytkownik. Dlatego
  `test_insights_competitions_open.py` ma test, który przechodzi całą ścieżkę
  router → serwis → Postgres.
- **`/api/admin/schema-drift` robi `rollback()` w każdej gałęzi błędu** —
  zabezpieczenie ścieżki TIMEOUTU, gdzie `asyncio.wait_for` anuluje zapytanie
  w locie i zostawia sesję w zepsutej transakcji. Uwaga na zakres dowodu:
  po usunięciu wszystkich rollbacków test kontraktowy nadal przechodzi
  (`get_db` commituje taką sesję bez `PendingRollbackError`), więc guard broni
  KSZTAŁTU ODPOWIEDZI (200 + `error` + `alembic`), a nie tych linijek.
- **Fixture'y testowe nie mogą stać na stałym roku.** Baza testowa jest wspólna
  dla przebiegu i NIE jest czyszczona, więc rok zajęty przez sąsiedni plik wraca
  jako „regresja" w kodzie, którym nikt nie ruszał. Zanim wybierzesz rok:
  `grep -rhoE 'datetime\((1[89][0-9]{2}|20[0-9]{2})|date\((1[89][0-9]{2}|20[0-9]{2})|"(1[89][0-9]{2}|20[0-9]{2})-' backend/tests/ | grep -oE '(1[89][0-9]{2}|20[0-9]{2})' | sort -u`

## Wyniki 2026 sprzed NEXUS-a — DynaReporter do 11.10.2026 (decyzja Artura 15.10.2026)

Zespół liczy wyniki w NEXUS-ie od **12.10.2026**. Do 11.10 wynik rekrutera to
jego tygodniowy wpis w DynaReporterze (baza `infrareporter-db` na Renderze,
projekt JARVIS) — z tych liczb ogłaszano Ligę i wyścigi. NEXUS liczył te same
okresy z historii Traffita (punkt dostaje ten, kto przesunął kartę, często DL),
stąd inne podia. Kod: `app/services/competition_history.py`.

- **Jedno źródło na dzień, nigdy suma.** Okres w całości przed 12.10 —
  rozliczony regułami DynaReportera i zamrożony; okres przecinający 12.10
  (Q4 2026, październik 2026) — dni do 11.10 z `dr_kpi_body_leasing`, od 12.10
  na żywo (`live_window` / `dr_window`); po 12.10 — tylko NEXUS. Liga DL
  i Hall of Fame zawsze z NEXUS-a (DynaReporter ich nie prowadził).
- **Reguły DynaReportera** (odtworzone 12/12 na jego oficjalnych wynikach I–VI):
  liga 150/15/5, próg 3 placementy; wyścig rekomendacji: ≥ 4 weryfikacje na
  dzień **przepracowany** (`days_worked` z wpisu), precyzja ≥ 75% od 2026-04;
  wyścig placementów bez progu; lider kwartału wykluczony tylko w **ostatnim**
  miesiącu kwartału. Wyścig placementów liczył się z tygodniowych wpisów,
  nie z listy `placement_details` (czerwiec zgadza się tylko z wpisami).
- **Okres zamknięty pokazuje zamrożenie** (`frozen_result`): `/current`
  i `/monthly-races` z `period` zamkniętym oddają podium z `competition_winners`
  i listę z migawki zamknięcia (`rows`, `ranking`), plus `is_frozen`,
  `closure_status`, `source` (`nexus` | `dynareporter` | `mixed`) i `source_note`.
  `freeze_competition` od 15.10 zapisuje `rows`, `ranking` i źródło.
- **Rozliczenie jednorazowe:** `scripts/settle_competitions_from_dynareporter.py`
  (wejście na stdin: mapa kont DR → NEXUS i wpisy, same ID; domyślnie na sucho,
  `--apply` w jednej transakcji, paragon `dynareporter_settlement_2026` ze stanem
  sprzed podmiany). Konta z `dynareporter_legacy_id` to nieaktywne duplikaty —
  wynik idzie na konto, na którym osoba pracuje (albo konto z Traffita, gdy
  odeszła). Remis bez rozstrzygnięcia → `tie_pending`, decyduje admin w panelu
  remisów; marża/h z NEXUS-a nie liczy placementów z DynaReportera.
- **Ekran Rywalizacja:** wybór kwartału i miesiąca od Q1 2026 / stycznia 2026
  (stan ekranu, nie adres), pasek źródła i „Zamknięte” zamiast odliczania.
- **Rozliczone na produkcji 17.10.2026** (`--apply`, paragon
  `dynareporter_settlement_2026`, 796 wpisów). Statystyki poza Rywalizacją —
  sekcja niżej (od 17.10.2026 licznik celów też liczy dni 1–11.10
  z DynaReportera).

## Statystyki sprzed 12.10.2026 wyłącznie z DynaReportera (decyzje Artura 17 i 18.10.2026)

Zespół klika w NEXUS-ie od **12.10.2026**. Ruchy Tablicy sprzed tego dnia to
import Traffita (zasługa dla tego, kto przesunął kartę, 10–30% więcej
rekomendacji niż raport) — **do statystyk nie wchodzą wcale**, także przed
2026. Źródłem dni do 11.10.2026 jest DynaReporter (albo Excel zespołu); czego
DynaReporter nie prowadził, to „brak danych — do uzupełnienia”, nigdy liczba
z Tablicy. Granice to fakty biznesowe (`competition_history.DR_HISTORY_START`
= 1.01.2026, `RESULTS_CUTOVER` = 12.10.2026), pilnuje
`tests/test_kpi_milestones_dynareporter.py`.

- **Źródła sprzed 12.10.2026** (tabele `dr_*`, wgrane
  `scripts/load_dynareporter_history.py`, paragon `dynareporter_history_load_2026`):
  - 1.01–11.10.2026 — tygodniowe wpisy rekruterów (`dr_kpi_body_leasing`):
    weryfikacje → `verified`, rekomendacje → `cv_sent`, rozmowy →
    `client_interview`, placementy → `hired`;
  - przed 2026 — placementy firmy z raportu Rady
    (`dr_board_monthly_report`, bez osoby; od 0472 tylko reszta ponad
    ręcznie uzupełnione tygodnie rekruterów — akapit „Ręczne uzupełnienie”);
  - klienci — `dr_placement_details` (2026) i `dr_board_placement_clients`
    (przed 2026), nazwa łączona z klientem NEXUS-a po nazwie / nazwie
    wyświetlanej (`history_client_placements`);
  - Delivery Leadzi — miesięczne wpisy DL (`dr_kpi_delivery_lead`).
- **Widok `analytics_kpi_milestones`** (migracje 0454, 0467, 0472, lustro w
  `entrypoint.sh`): Tablica od 12.10 (`nexus`) + wpisy rekruterów
  (`dynareporter`) + placementy Rady przed 2026 (`dynareporter_board`).
  `credited` w `VERIFIER_ANCHORED_CTE` czyta te same wiersze spoza Tablicy;
  surowe ruchy w `credited_nexus` (diagnostyka adopcji, rekonsyliacja).
- **Z widoku liczą:** licznik celów i KPI coach, Mój miesiąc, „Twój tydzień”,
  Zespół (lejek, Ludzie, Do uwagi), „Aktywność rekrutacyjna”, kafle metryk,
  tabela i aktywność zespołu, Firma (etapy, placementy, seria 12 miesięcy),
  Rok do roku (liczba placementów), Analiza placementów (osoby), Ścieżka
  rozwoju, Hall of Fame (placementy przed 2026 bez osoby = „nieprzypisane”),
  kampanie.
- **Klienci** (Analiza placementów, Rok do roku): z `history_client_placements`
  z własną sumą `client_placements` — przed 12.10 inna tabela DynaReportera niż
  liczba placementów, więc sumy bywają różne; UI to pisze.
- **Liczone dopiero od 12.10.2026** (`competition_history.board_start`), bo
  DynaReporter tego nie prowadził: reszta lejka i „Zamknięci” w Lejku po
  etapach (cztery kamienie mają dni z DynaReportera, `history` w odpowiedzi),
  źródła kandydatów, czas do zatrudnienia (zatrudnienie od 12.10; start
  procesu z historii pary — jedyny wyjątek, bez niego czasu nie ma), hit ratio
  (rekrutacje zamknięte od 12.10; obsadzenie pary sprawdzane w całej historii).
- **Delivery Leadzi:** portfel DL przed 12.10 = wiersz „DynaReporter — bez
  klienta” z wpisów DL (`HISTORY_CLIENT_ID = 0`); `dl_portfolio_counts`
  (Liga DL, cele DL) = wpisy DL + Tablica od 12.10, mianownik hit ratio od
  12.10. **Liga DL Q1–Q3 2026** przeliczona z wpisów DL
  (`scripts/settle_dl_league_from_dynareporter.py`, paragon
  `dynareporter_dl_league_2026`): placementy, próg 3, bez progu hit ratio.
- **Lista „Kto się liczy”:** `period_total` = licznik celów, `history_total` =
  ile z tego to wpisy; lista pokazuje tylko pary z NEXUS-a.
- **Precyzja 30 dni:** kohorta par z NEXUS-a + rekomendacje / weryfikacje
  wpisów z okna (obcięte do 100%). **Dogrywki ligi** — tylko pary z NEXUS-a.
- **Okno inne niż miesiąc:** wpis tygodniowy idzie na dzień `report_date`,
  miesięczny (DL, Rada) na pierwszy dzień miesiąca.
- **UI:** `PeriodPicker` (Zespół, Firma, Raporty) pisze, skąd są dni do
  11.10.2026, gdy okno zaczyna się wcześniej (`lib/insights-history.ts`).
- **Testy sprawdzające ruchy Tablicy** mają daty od 12.10.2026 (np. 2027,
  +728 dni = ten sam dzień tygodnia) — wcześniejsze ruchy celowo się nie liczą.
- **Ręczne uzupełnienie** (decyzja Artura 18.10.2026: „jak nie ma tam danych,
  to uzupełnimy ręcznie”): braki wpisuje się do tych samych tabel `dr_*`,
  nigdy jako ruchy Tablicy. Arkusz robi i czyta lokalnie
  `scripts/dr_manual_fill_sheet.py` (szablon z zakładką „Braki” z
  `import_dr_manual_fill.py --gaps`, listy wyboru z `--lists` — z nazwiskami,
  tylko do pliku; arkusz → JSON z samymi id kont), wgrywa
  `scripts/import_dr_manual_fill.py`: na sucho w transakcji tylko do odczytu
  z raportem „przed → po”, `--apply` w jednej transakcji z paragonem
  `dr_manual_fill_<czas>` (każdy wiersz przed i po), zapis na produkcji
  dopiero po zgodzie Artura na suchy przebieg. Wgrywa tylko przekazane wiersze
  (puste pole = bez zmiany), odmawia całości przy dniu od 12.10.2026, koncie
  bez odpowiednika w NEXUS-ie albo koncie-duplikacie z DynaReportera, nieznanym
  kliencie (literówka byłaby nowym klientem) i drugim wpisie tego samego
  tygodnia. Gdzie co trafia: tydzień rekrutera → `dr_kpi_body_leasing`
  (tydzień przez koniec miesiąca = dwa wpisy, drugi od 1. dnia miesiąca);
  placement z klientem 1.01–11.10.2026 → `dr_placement_details`; miesiąc DL →
  `dr_kpi_delivery_lead`; przed 2026 placementy firmy i klientów w miesiącu →
  `dr_board_monthly_report.placements` i `dr_board_placement_clients`. Żeby
  wpis się liczył: od **0472** widok bierze tygodnie rekruterów także przed
  2026, a Rada przed 2026 daje już tylko resztę bez osoby (placementy Rady
  minus placementy z wpisów tego miesiąca, nie mniej niż 0 — suma firmy
  zostaje z Rady); wpis DL za październik 2026 to dni **1–11.10** i wchodzi do
  portfela DL w Insights (wcześniej październik był pomijany), ale nie do Ligi
  DL ani celu DL (`competitions.dl_portfolio_counts`): mianownik hit ratio —
  rekrutacje zamknięte — liczy się od 12.10, więc placementy 1–11.10 zawyżyłyby
  próg 30% przy wypłatach (rozstrzygnięte 18.10: październik DL zostaje
  pusty — niżej „Temat zamknięty”). Uzupełnienie miesięcy
  1–9.2026 zmienia statystyki, nie zamrożone wyniki konkursów (paragony
  `dynareporter_settlement_2026`, `dynareporter_dl_league_2026`). Etapów Tablicy
  poza czterema kamieniami, źródeł, czasu do zatrudnienia i hit ratio sprzed
  12.10 tak nie uzupełnimy — nie mają tabeli `dr_*`, z której liczą ekrany.
  `load_dynareporter_history.py` nie uruchamiaj ponownie: kasuje wpisy DL
  i placementy z klientem sprzed 12.10, także ręczne.
- **Temat zamknięty 18.10.2026** (Artur: „chcę już zamknąć cały ten temat”,
  działaj według rekomendacji). Ręcznego uzupełnienia nie robimy — dane sprzed
  12.10 są w NEXUS-ie w takim stanie, w jakim prowadził je DynaReporter, od
  12.10 liczą ruchy w NEXUS-ie. Co `--gaps` nadal pokazuje i dlaczego to nie
  są braki:
  - miesiące DL bez wpisu w 1–9.2026 i „brakujące” tygodnie rekruterów w
    październiku — osoba w tym czasie nie pełniła tej roli (role się zmieniały:
    DL bywał rekruterem, rekruter przechodził do innej roli; pojedyncze
    placementy w tygodniach rekrutera u osób, które dziś są DL albo `finance`,
    to ślad dawnej roli, nie luka). Nie wpisuj tam zer;
  - październik 2026 (1–11.10) bez wpisów DL — DynaReporter wpisywał miesiąc DL
    po jego końcu, a październik się w nim nie skończył. Zostaje pusty:
    portfel DL w Insights, Liga DL i cel DL liczą IV kwartał 2026 jednakowo,
    od 12.10. Placementy 1–11.10 są w statystykach rekruterów i firmy
    (`dr_kpi_body_leasing`, `dr_placement_details`), tylko nie w portfelu DL;
  - KPI rekruterów 2025 — DynaReporter ich nie prowadził; 2025 = placementy
    Rady (firma i klienci w miesiącu).
  Narzędzie (`dr_manual_fill_sheet.py`, `import_dr_manual_fill.py`) zostaje na
  wypadek, gdyby ktoś znalazł konkretną pomyłkę w danych DynaReportera.

## Zespół → Ludzie: aktywny rekruter bez ruchu ma wiersz (20.10.2026)

Zgłoszenie: nowa rekruterka (konto z 19.10, rola `recruiter`, 4 rekrutacje,
zero ruchów kart) nie pojawiała się w tabeli „Rekruterzy”, bo
`isPeopleRowWorthShowing` (`lib/insights-views.ts`) chował każdy wiersz
z samymi zerami — wyglądało to na brak uprawnień. Decyzja Artura: aktywne
konto z rolą `recruiter` stoi w tabeli także z zerami (API i tak sortuje je
na koniec). Inne role bez ruchu (np. Delivery Lead) nadal idą do dopisku
„Pominięto osoby bez ruchu w tym okresie: N”; nieaktywnych bez ruchu API nie
zwraca wcale.

## Zespół → Ludzie: byli pracownicy i sortowanie (19.10.2026)

Prośba rekrutera: osoby, które już u nas nie pracują, wisiały w tabelach
„Rekruterzy” i „Delivery Leadzi” (wyniki z okresu, gdy pracowały, w tym DL
z DynaReportera przez cały rok). Decyzja Artura — wiersz zbiorczy, nie
usuwanie:

- „Były pracownik” = konto `users.is_active = false` (ten sam sygnał co Liga
  i cele). Dane już to niosą (`TeamPeopleRow.is_active`,
  `InsightsDlPortfolioLead.is_active`), podział robi front
  (`lib/insights-people-table.ts`), bez zmian API.
- Takie osoby schodzą z listy do jednego wiersza „Byli pracownicy (N)” pod
  listą osób, z sumami kolumn liczbowych; wskaźniki (weryf./dzień, precyzja,
  hit ratio) mają tam „—”. Sumy firmy się nie zmieniają — nie wycinaj ich
  liczb ani w API, ani we froncie.
- Przełącznik „Pokaż byłych pracowników” (wspólny dla obu zakładek,
  domyślnie wyłączony) przywraca ich jako zwykłe wiersze z plakietką
  „były pracownik”.
- Klik w nagłówek sortuje: liczby najpierw od najwyższej, drugi klik
  odwraca, nazwisko od A do Z. „—” (`null`) zawsze na końcu w obu
  kierunkach; remis po nazwisku. „Placementy vs poprzednio” sortuje po
  różnicy. Wiersze zbiorcze zawsze pod listą osób. Bez kliknięcia — kolejność
  z API. Ten sam `SortableHeader` (`sections/_shared.tsx`) ma „Performance
  per osoba”.

## Akceptacje, „W drodze” i „Mój miesiąc” v3 (22.10.2026)

Makiety i decyzje Artura: https://claude.ai/artifact/H4QgdE9ou92M1dtr9QrygF
(„nic nie wycinać hurtem — co bez sensu, zwinąć albo do raportu”).

- **Akceptacje są w lejku, ale tylko od 12.10.2026.** Traffit ich nie znał,
  DynaReporter nie prowadził. `/recruitment/funnel` oddaje przy etapie
  `counted_from` (dzień, od którego etap jest liczony w oknie), a konwersja
  między etapami liczonymi od różnych dni ma `pct = null` i `partial_window`.
  Ekran pokazuje wtedy „od 12.10”, nie zero i nie procent.
- **„W drodze” (`/recruitment/in-flight`) = stan na dziś**, kolumna pary
  regułą Tablicy (ta sama co „Teraz” w „Lejku po etapach”), „od kiedy” =
  wejście do KOLUMNY (odznaka „Umowa wysłana” nie zeruje licznika, powrót na
  rozmowę — tak). Lista akceptacji ma klientów i DL, więc tylko z
  `VIEW_TEAM_KPI`; nazwisk kandydatów nie ma tam nigdy.
- **Prognoza z akceptacji**: skuteczność = placementy / akceptacje
  rozstrzygnięte od 12.10.2026, pokazywana od 10 rozstrzygnięć i zawsze jako
  przedział („ok. 8–9”). Skuteczność jest firmowa także w widoku osoby —
  próbka jednej osoby jest za mała.
- **`/recruitment/in-flight/me`**: `mine` = pary, które osoba zweryfikowała
  (zasługa jak w celach i wyścigach), `portfolio` = rekrutacje Delivery Leada
  (403 dla innych ról). Nazwiska kandydatów tylko z odczytem sekcji Rekrutacja.
- **„Mój miesiąc” rekrutera**: cele z tempem z TEGO SAMEGO modelu co licznik
  w pasku (`buildKpiTopbarModel`) plus precyzja jako wiersz celu, lejek
  5 etapów (porównanie z zespołem bierze akceptacje tylko, gdy lejek firmy
  liczy je przez cały miesiąc), „Moje osoby w drodze”, „Moja premia” (dane
  `/api/hr/payroll/me` — tylko własna; Płace wyłączone albo brak kartoteki =
  karty nie ma), „Kto się liczy do celów” zwinięte (to samo jest w panelu
  celów), wyścig rekomendacji obok wyścigu placementów.
- **Delivery Lead ma własny „Mój miesiąc”** („Jak idzie mój portfel?”): cele
  DL z kwartału, „W drodze u moich klientów” z kolejką „Do wysłania”, Liga DL,
  premia, „Moi klienci” z raportu „Portfele DL”. Do 22.10 DL widział ekran
  i cele rekrutera.
- **Zespół v3**: „Cele zespołu” dla każdego, kto widzi Insights
  (`/recruitment/team-goals` = `integration_insights.company_team_goals`, te
  same sumy co licznik HoR, bez osób) z prognozą miesiąca („ok. 29–30” =
  placementy + szacunek z akceptacji); jeden lejek 5 etapów „w okresie” z
  wierszem „stoi dziś” zamiast czterech kafli i słupków z tymi samymi
  liczbami; „Ostatnie 8 tygodni” (`/recruitment/weekly-trend`, tydzień od
  poniedziałku, akceptacje sprzed 12.10 = `null`); „Do uwagi” + akceptacje
  stojące ponad 14 dni; tabela Ludzie + „Akceptacje”, „Placementy / cel”
  (tylko okno miesiąca — cel jest miesięczny) i „W drodze dziś” (pierwszy
  weryfikujący, ta sama liczba co „Moje osoby w drodze”). Długi przypis pod
  tabelą zwinięty w „Jak liczymy tabelę?”.
- **Firma v3** („Jak idzie firma?”): zdanie podsumowania (`lib/insights-firma.ts`),
  kafle kwot bez zmian, „Ruch konsultantów w okresie” z
  `/api/insights/board/flows` (`BoardReader`, jak kokpit): przyszli /
  odeszli (w tym rezygnacje) / netto z `integration_insights.contract_flows`
  (te same funkcje co rok do roku i API integracyjne) i kontrakty kończące
  się w 30 dni bez kontynuacji (`order_continuation.ending_without_successor`,
  reguła pigułki „Kończące się 30d”); lejek z „stoi dziś” (ten sam komponent
  co Zespół); prognoza „z akceptacjami” tylko dla okresu, który trwa;
  zwinięta lista akceptacji (bez kandydatów); „Skuteczność i popyt” (hit
  ratio, otwarte i nowe rekrutacje). Akapit o ewidencji kontraktów przeniesiony
  do „Jak liczymy widok Firma?”.
- **Rada nadzorcza: zakładki Firma · Zespół · Raporty · Rywalizacja**
  (`getVisibleInsightTabIds`), adres bez widoku ląduje na pierwszym widoku
  osoby — u Rady na Firmie (decyzja Artura 22.10.2026).
- **Rywalizacja v3**: kampanii już nie prowadzimy (Artur, 22.10.2026) —
  baner i panel „Kampanie rekrutacyjne” zdjęte z ekranu, a frontowy kod
  kampanii (komponenty, `/preview/insights-campaign`, klient API) usunięty;
  backendowe API i dane kampanii zostają. Zasady lig i wyścigów zwinięte
  pod „Zasady…” (treść bez zmian), pasek źródła okresu to plakietka, a notka
  „Dni do 11.10.2026 z DynaReportera” przy pasku okresu — zwijana (treść
  i `data-testid` bez zmian).
- **Raporty v3**: nowy raport „Akceptacje w toku” (pełna lista z
  `/in-flight`, `VIEW_TEAM_KPI`; prowadzi do niego „Do uwagi” i lista na
  Firmie). Rada nadzorcza nie widzi raportów-narzędzi zespołu: „Kompetencje
  w toku”, „Źródła, portale i linki”, „Zamknięcia i hit ratio” (`notBoard`
  w `lib/insights-reports.ts`); „Rekrutacje bez ruchu” zostaje, bo prowadzi
  do niego „Do uwagi”, a Hall of Fame i Ścieżka — bo Rada widzi Rywalizację.
