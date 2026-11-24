# Zespół dla klienta: kilka rekrutacji, jeden link (0711, 15.11.2026)
<!-- indeks: `/zespoly/{id}`, `/k/z/{token}`, pojemnik a nie typ rekrutacji, link wyłączony domyślnie, włączenie zespołu włącza panele stanowisk, kształt publiczny z paneli stanowisk, wybór składu bez treści w dzwonku, gotowe składy (automat proponuje, DL zatwierdza), rozmowy z całym składem, podpowiedź stawki z historii klienta, szacunek p25–p75 dla klienta, odczyt maila na stanowiska -->

Decyzje Artura z 15.11.2026 (zakres Z1 + Z2). Makiety:
https://claude.ai/artifact/KAz5WWuPqsyZFBdHFE9ohn. Kod: `api/job_team_panel.py`,
`api/public_job_team_panel.py`, `services/job_team_panel.py`, model
`models/job_team_panel.py`, SQL `services/job_team_schema.py` (lustro w
`entrypoint.sh`, sondy `job_teams` i `job_team_selections` w `/api/health/deep`).
Buduje na panelu rekrutacji: `panel-klienta-pod-linkiem.md` obowiązuje w całości.
Nazwa „zespół” jest tu zajęta: `services/job_team.py` to reguła „Rekruter
rekrutacji”, nie ten moduł.

- **Zespół to pojemnik, nie typ rekrutacji.** Klient prosi o kilka ról naraz,
  NEXUS zakłada zwykłe rekrutacje (każda ze swoim DL-em, Tablicą i CV), a zespół
  je grupuje (`jobs.team_id`). Typów rekrutacji nie ma
  (`rekrutacja-tworzenie/bez-typow-rekrutacji.md`) i zespół ich nie przywraca.
  Rekrutacja należy najwyżej do jednego zespołu; zespół łączy tylko otwarte
  rekrutacje jednego klienta, najwyżej 30. Inny klient, zamknięta rekrutacja albo
  rekrutacja w innym zespole = 409. Ostatniej rekrutacji nie da się zdjąć (422).
- **Kto zarządza:** uprawnienie „Rekrutacje” (`RecruitmentManageUser`) i prawo do
  panelu (`_ensure_panel_manager`) na KAŻDEJ rekrutacji zespołu, bo link zespołu
  włącza panele stanowisk i wypuszcza stawki na zewnątrz. Jedna cudza rekrutacja
  w zespole = 403 na cały zespół. `GET /by-job/{job_id}` (plakietka na rekrutacji)
  ma bramkę karty rekrutacji. Wzorzec dostępu: `tests/data/authz_golden/job_team_panel.json`.
- **Link domyślnie wyłączony** i tylko na żądanie, jak panel rekrutacji. Token
  zespołu: ten sam schemat co panel, inna wiadomość HMAC
  (`job-team-panel:{id}:{nonce}`), w bazie tylko SHA-256. Adres `/k/z/{token}`.
  Nieznany albo wyłączony = 404, wygasły = 410. Ważność przy włączeniu: koniec
  dnia za 60 dni. Włączenie bez otwartej rekrutacji = 409.
- **Włączenie linku zespołu włącza panele otwartych stanowisk** z tą samą ważnością
  i tym samym `show_rate`; wyłączenie wyłącza panele wszystkich stanowisk zespołu.
  Wyjątek: stanowisko, na którym DL wcześniej ukrył stawkę, zostaje z ukrytą, bo
  inaczej samo włączenie linku wypuściłoby ją do klienta (przegląd bezpieczeństwa
  15.11.2026). Jawna zmiana „Pokazuj stawki i cenę zespołu” obejmuje wszystkie
  stanowiska.
  Nowe stanowisko dodane do włączonego zespołu dostaje panel od razu. Zdjęte ze
  zespołu zostaje z panelem w stanie, w jakim było (to ten sam klient).
  Panele stanowisk włącza tylko włączenie linku i dodanie stanowiska
  (`enable_positions` w `sync_position_panels`). Sama zmiana „Pokazuj stawki”
  na włączonym zespole zmienia tylko `show_rate` i nie rusza włączenia ani
  ważności: stanowisko wyłączone przez DL-a zostaje wyłączone (audyt 24.11.2026).
- **Zmiana klienta rekrutacji w zespole = 409** („zdejmij ją z zespołu przed
  zmianą klienta”), przed każdą zmianą w `PATCH /api/jobs/{id}`. Link zespołu
  pomija też rekrutację, której `client_id` różni się od klienta zespołu
  (`public_positions`), na wypadek danych zapisanych z pominięciem API
  (audyt 24.11.2026).
  „Odwołaj link” zmienia token zespołu i tokeny paneli stanowisk, więc przestają
  działać też ramki w już wysłanych CV tych rekrutacji. Audyt: `Activity` na
  każdej rekrutacji (`job_team_added`, `job_team_removed`, `job_team_panel_enabled`,
  `job_team_panel_disabled`, `job_team_panel_link_rotated`).
- **Kształt publiczny powstaje z paneli stanowisk.** Każde otwarte stanowisko
  z działającym panelem to `{key, short, headcount, view}`: `key` to bieżący token
  panelu stanowiska, `view` to `public_panel_view` tego panelu. Szczegóły osoby,
  CV, pliki, pytania i rozmowy idą dalej trasami `/api/public/panel/{key}/…`,
  więc blind CV, zgoda RODO, ukrycie osoby i limity działają bez zmian. Poziom
  zespołu niesie tylko nazwę zespołu, nazwę klienta, ważność i imię osoby
  prowadzącej (DL pierwszego stanowiska). Bez identyfikatorów, oczekiwań, marż,
  adresów i telefonów; pilnuje tego `test_public_team_shape_has_no_private_fields`.
  Zamknięte stanowisko i stanowisko z wyłączonym panelem znikają z widoku.
- **Wybór składu** (`POST /api/public/team-panel/{token}/selection`): klient
  wskazuje osoby per stanowisko (`{key: [public_id]}`); nieznany klucz albo osoba
  spoza listy tego stanowiska = 422. Zapis w `job_team_selections` jako
  `[{job_id, candidate_ids}]`. Autor niezweryfikowany, jak w panelu; IP tylko jako
  skrót z solą dnia. Dzwonek DL-i stanowisk (`client_panel_request`,
  `related_entity_type = job_team_selection`, link `/zespoly/{id}`) nie niesie
  treści od autora. Dzienny limit zespołu: 30 (429). Wybór niczego nie przesuwa
  na Tablicy: decyzja i rozmowy zostają u DL-a.
- **Cena = suma stawek do klienta, bez rabatu**, 168 godzin w miesiącu
  (`hours_per_month`); liczy ekran. Kropki wymagań tylko w szczegółach stanowiska.
- **Odłożone:** cennik z `rate_cards`. Bez AI w żądaniu publicznym. Odczyt
  maila i podpowiedź stawki: sekcja Z4 niżej.

## Z3: gotowe składy i rozmowy z całym składem (0713, 15.11.2026)

Kod: `services/job_team_variants.py` (reguły bez bazy, zapis, otwarty wniosek),
widok klienta `public_variants` w `services/job_team_panel.py`. Kolumny
`job_teams.variants`, `variants_approved_at`, `variants_approved_by`
(`VARIANTS_DDL` w `services/job_team_schema.py`, lustro w `entrypoint.sh`,
sonda `job_teams` czyta je przez model).

- **Automat proponuje, DL zatwierdza, klient widzi tylko zatwierdzone.**
  `GET /api/job-teams/{id}/variants/proposal` liczy trzy składy na żądanie
  i niczego nie zapisuje: „Najszybszy start” (najwcześniejsza dostępność, data
  z przeszłości = dziś, brak daty na końcu; remis → tańszy), „Najniższa cena”
  (stawka godzinowa do klienta, inna jednostka albo brak = na końcu; remis →
  wcześniejszy start), „Najwięcej w CV” (`in_projects` z dowodów jak w panelu;
  remis → tańszy). Ostatni remis: kolejność wysyłki CV. Kandydaci to pary
  z widoku DL-a (wysłane, proces otwarty), bez osób ukrytych w panelu i „nie
  pasuje”; zamknięte stanowisko pomijane. Na każde miejsce jedna osoba,
  stanowisko z mniejszą liczbą osób dostaje wszystkie, puste znika ze składu.
  Takie same składy zostają, ekran je pokazuje. `hourly_total` = suma znanych
  stawek godzinowych (`null`, gdy żadnej), `start` = najpóźniejsza znana
  dostępność, `unknown_start` = osoby bez daty.
- **`PUT /api/job-teams/{id}/variants`** (0–3 składy) zapisuje to, co DL
  zatwierdził albo podmienił: rekrutacja spoza zespołu, osoba spoza wysłanych
  CV stanowiska, więcej osób niż miejsc, powtórzone stanowisko lub klucz albo
  skład bez nikogo = 422. Nazwa (1–60) i uzasadnienie (0–240) idą do klienta:
  zwykły tekst bez znaków sterujących, żadnej treści od klienta. `[]` =
  wycofanie (`variants_approved_at` = `null`). Audyt `job_team_variants_approved`
  / `job_team_variants_withdrawn` na każdej rekrutacji. Bramka jak reszta zespołu.
- **Klient** dostaje `variants: [{key, name, why, picks: {klucz stanowiska:
  [public_id]}}]` w `GET /api/public/team-panel/{token}`. Osoba, której klient
  już nie widzi na liście stanowiska (ukryta, wycofana, stanowisko zamknięte
  albo z wyłączonym panelem), wypada; skład bez nikogo wypada.
- **Rozmowy z całym składem** (`POST /api/public/team-panel/{token}/interviews`,
  jedna siatka terminów i `picks`) to N wniosków przez wspólny serwis
  `create_slot_request_for_pair`, dokładnie jak prośba o jedną osobę z panelu
  stanowiska: normalizacja terminów i limit 6, karta na „Rozmowę u klienta”,
  dzwonek rekrutera i DL-a, sprawa `interview` w panelu stanowiska. Czekający
  wniosek = `skipped` z `open_request`, stanowisko z wyłączonymi prośbami =
  `actions_disabled`; to nie są błędy. Dzienny limit panelu stanowiska (30) daje
  429 dla całego żądania przed zapisem. Każdy wniosek jest zatwierdzany osobno,
  bo wspólny serwis przy wyścigu o otwarty wniosek cofa całą transakcję.

## Z4 i odczyt maila (bez migracji, 15.11.2026)

Kod: `services/job_team_rates.py` (podpowiedź stawki), `services/team_request_split.py`
(odczyt maila), trasa `POST /api/job-intake/team-positions` w `api/job_request_intake.py`,
prompt `TEAM_REQUEST_SPLIT` w `services/llm_prompts.py`.

- **Podpowiedź stawki to historia TEGO klienta, nie cennik.** Stanowisko zespołu
  dostaje `rate_hint: {p25, median, p75, count}` (zł/h): stawki do klienta
  z wierszy etapu (najnowsza na parę kandydat–rekrutacja, ta sama reguła co
  `stage_client_rate.latest_client_rates`) z rekrutacji tego klienta w tej
  samej kategorii kompetencji z 365 dni (`business_today()`), bez samego
  stanowiska. Tylko godzinowe w złotych: para, której najnowsza stawka jest
  dzienna albo w innej walucie, nie wchodzi. Mniej niż 3 pary albo brak
  kategorii = `null`; innych klientów nie dobieramy, bo stawka jednego klienta
  nie może wyciec do drugiego. Kwartyle: interpolacja liniowa.
- **Klient widzi tylko szacunek p25–p75 i tylko bez prawdziwych stawek.**
  W `GET /api/public/team-panel/{token}` każde stanowisko ma
  `estimate: {min, max} | null`: widełki tylko wtedy, gdy panel stanowiska
  pokazuje stawki, a na liście stanowiska nie ma żadnej stawki godzinowej.
  Nigdy liczby par, mediany ani niczego o innych klientach. Ekran podpisuje
  widełki jako szacunek z historii zleceń klienta. Ukryta stawka na panelu =
  brak szacunku, bo inaczej ukrycie dałoby się obejść.
- **Odczyt maila na stanowiska to dodatek.** `POST /api/job-intake/team-positions`
  `{text}` (20–20 000 znaków) → `{positions: [{title, headcount, seniority,
  words}], model}`. Ten sam model i ta sama telemetria co odczyt requestu
  (`ai_feature(champion_draft)`, `model_for(champion_draft)`): osobny klucz
  `aifeaturekey` wymagałby migracji. Ugruntowanie jak w wierszach wymagań
  (`job_request_intake._grounded_search_word`): słowo spoza maila wypada
  (najwyżej 8), liczba osób przechodzi tylko z dosłownym cytatem zawierającym
  tę liczbę (`_headcount`, 1–50), inaczej 1; poziom tylko `junior`, `regular`,
  `senior` albo `null`. Awaria modelu albo zła odpowiedź = 200 z pustą listą
  i wpis w logu bez treści maila. Bramka jak odczyt requestu
  (`RecruitmentManageUser`), limit 20/min.
