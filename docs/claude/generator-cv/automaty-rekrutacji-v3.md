# Automaty rekrutacji v3 (21.09.2026, migracja 0335)

Cztery automaty, wszystkie WŁĄCZONE domyślnie, każdy za wyłącznikiem env,
którego stan OFF = zachowanie sprzed 21.09. **Nic zewnętrznego ani
nieodwracalnego nie dzieje się bez kliknięcia człowieka**: żaden automat nie
wysyła nic do klienta, nie przesuwa karty i nie dodaje nikogo do pipeline'u
(wyjątki: jawnie ustawione `AUTO_MATCH_MODE=add` i automat E — dopełnianie
„Nowych”, decyzja Artura 23.10.2026). Zdarzenia automatów lądują
w `Activity(entity_type="job_automation", entity_id=<job_id>)` — osobny typ
encji, żeby nie mieszać się z historią rekrutacji — i czyta je
`GET /api/jobs/{id}/background-events` (zakładka „Praca w tle", bramka jak
skrzynka „Propozycje"; nazwisko kandydata tylko dla ról z odczytem kandydatów,
stan auto-CV czytany NA ŻYWO z wiersza dokumentu).

| Automat | Wyłącznik | Kod |
|---|---|---|
| A. nocny pełny przegląd bazy → „Propozycje" (`full_base`) | `AUTO_FULL_REVIEW_ENABLED` | `services/auto_full_review.py`, `tasks/auto_full_review.py` |
| B. nowe CV → „Propozycje" (`new_cv`) | `AUTO_MATCH_MODE=dry_run` | `services/auto_match_service.py` |
| C. auto-CV po ruchu na „Zweryfikowany" — od 21.10.2026 tylko QC istniejącego CV pary, generacja po potwierdzeniu w karcie (`cv-po-potwierdzeniu.md`) | `CV_AUTO_GENERATE_ON_VERIFIED`, `CV_AUTO_GENERATE_WITHOUT_CONFIRMATION` | `services/cv_auto_generate.py` |
| D. podpowiedź stawki/dostępności w arkuszu screeningu | brak (czysty odczyt) | `services/screening_suggestions.py` |
| E. „System trzyma Nowych na 20” (23.10.2026) | `NEW_COLUMN_AUTOFILL_ENABLED` (domyślnie OFF) | `services/new_column_autofill.py`, `tasks/new_column_autofill.py` |

- **E. System trzyma „Nowych” na 20 (decyzje Artura 23.10.2026, makiety
  https://claude.ai/artifact/6qyrJf65QmsQdJteLZWVT2).** Dni robocze 7–19
  (`is_business_day`): pełny przebieg co 15 min po rekrutacjach w pracy,
  między nimi co tick (60 s) rekrutacje, w których człowiek ruszył kartę.
  Brak = `TARGET` (20) − osoby w kolumnie „Nowi” (ta sama reguła kolumny co
  Tablica; osoby dodane przez zespół też się liczą). Dobiera najlepszych
  z `job_autofill_pool` (A) i otwartych propozycji `full_base`/`new_cv` —
  **każdy wynik, także poniżej progu**. Nie dodaje: osób, które kiedykolwiek
  były w tej rekrutacji, pominiętych propozycji, stojących dziś na
  „Zatrudniony”, zgłoszeń z portali (`job_board`), każdego z decyzją bramki
  innej niż „brak przeciwwskazań” (ostrzeżenia zostają człowiekowi) i osób
  off-limits u klienta. Wejście przez `add_candidates_to_job` z
  `entry_source="system"` (0515, CHECK + lustro w `entrypoint.sh`),
  `actor_user_id=None` (puste `moved_by`), `claim=False` — bez blokady 12 h,
  bierze pierwszy, kto ruszy kartę — i `mark_proposals=False`.
  `entry_meta.kind="autofill"` to migawka: wynik, `matched_must`,
  `missing_must`, „Stawka od” (`effective_rate`), dostępność — z niej raport
  odróżni błąd wyszukiwania od braku danych. Wpis „Praca w tle”
  `new_column_autofill` (`kind: "autofill"`, `count`).
  **Bezpiecznik (23.10.2026):** najwyżej `NEW_COLUMN_AUTOFILL_MAX_PER_TICK`
  (100) dodań na tick — każde dodanie pobiera CV z magazynu i zapisuje kopię
  (`create_original_cv_snapshot`), a pierwszy przebieg na produkcji to ok.
  2–3 tys. osób. Przerwany pełny przebieg (`_State.pending`) wraca w następnym
  ticku od miejsca przerwania (także rekrutacja, przy której skończył się
  limit); rekrutacje z ruchem karty idą przed nim.
- **E. Reguły z odrzuceń (decyzje Artura 25.10.2026).** Analiza pierwszego
  dnia: 34 odrzucenia z powodem na 1 557 osób od systemu, z czego 16 to „za
  droga” przy stawce, którą system znał; 31% osób od systemu miało znaną
  „Stawkę od” ponad budżetem (wśród osób wysłanych przez zespół w 180 dni:
  7,8%). Od tej zmiany silnik (`_by_rules` przed bramką kwalifikacji, okno
  `_RULES_WINDOW` = 150 najlepszych):
  * nie dodaje osoby ze znaną stawką PLN ponad `BUDGET_HARD_OVER` (25%) nad
    `resolve_job_budget_hourly` (u osób wysłanych przez zespół 1,5%, u osób
    od systemu 14%); 0–25% nad budżetem = za osobami w budżecie i z nieznaną
    stawką (kolejność wyniku w obrębie poziomu zostaje). Zgoda z rozmowy na
    ofertę poniżej minimum (`accepts_below_min_rate`) i brak budżetu = bez
    reguły; stawka < 20 zł/h to błąd odczytu i liczy się jak nieznana.
    Jedna z 4 pierwszych przyjętych osób była 21% nad budżetem i poszła do
    klienta — stąd próg 25%, nie 0%;
  * nie dodaje osoby, która według LinkedIna albo CV pracuje teraz u klienta
    tej rekrutacji (nazwa, wyświetlana, prawna, aliasy —
    `client_off_limits.client_labels`), także przy wpisie CV bez żadnej daty
    (`find_hit(…, undated_counts=True)`; bramka człowieka zostaje przy
    `entry_says_current`). 3 z 5 „Inne” to „pracuje w Nordei przez inną
    firmę” / „nie chce do Nordei”;
  * nie przywraca osoby usuniętej z rekrutacji (archiwum
    `candidate_stage_removals` tej rekrutacji).
- **E. Reguły z odrzuceń, runda 2 (decyzje Artura 27.10.2026).** Analiza 133
  odrzuceń z powodem (12 osób, 27 rekrutacji) i 2 537 osób od systemu: wynik
  dopasowania nie odróżnia dobrych od złych (65–70 pkt: 45% idzie dalej,
  70–75: 22%), działają reguły na danych, które system zna. Od tej zmiany:
  * `BUDGET_HARD_OVER` = **15%** (było 25%): osoby 15–25% nad budżetem szły
    dalej w 12% (2 z 17), ponad 25% w 15%, a 0–15% w 40% — tyle co w budżecie
    (41%);
  * **biuro i miasto = za resztą, nie odpada** (`office_cautions`, te same
    funkcje co bramka wyszukiwania: `office_days_exceeded`,
    `remote_only_refuses_office`, `office_city_mismatch`; zgoda na więcej
    dni w biurze znosi ostrzeżenie o dniach): przy znanym „mniej dni w biurze”
    dalej szło 18% (7 z 39), przy zgodnych 36%. Poziom w `_by_rules` = poziom
    budżetu + 1 przy ostrzeżeniu o biurze;
  * migawka `entry_meta.cautions` (budżet z procentem, `office_days`,
    `remote_only`, `office_city`) → `autofill_badge.cautions` z napisem
    i dymkiem (liczy serwer) → plakietki na karcie w „Nowych”/„Screeningu”
    i lista „Na co uważać” w `DockAutofillReason`. Karty sprzed tej zmiany
    nie mają ostrzeżeń.
  Jednorazowo `scripts/autofill_withdraw_over_budget.py` (podgląd, `--apply`)
  zdejmuje nietknięte karty od systemu ponad 25% nad budżetem
  (`services/autofill_withdraw.py`: jeden wiersz etapu bez osoby, bez
  „Dzwonię”, decyzji i notatki pary, sprawdzane drugi raz pod blokadą) drogą
  „Usuń z rekrutacji” z archiwum bez autora (`autofill_withdrawn_over_budget`),
  bez wpisu w `autofill_feedback`; „Praca w tle” `autofill_withdrawn`.
  `void_process(actor_user=None)` = system zdejmuje własną kartę, bez
  sprawdzania priorytetu.
- **E. Odrzucenie na cały klient (0606, decyzja Artura 27.10.2026).** 13 z 20
  „Inne” to klient, nie osoba („pracuje w Nordei przez inną kontraktownię”,
  „nie chce do Nordei”), a ci sami ludzie czekali jeszcze na 45 kartach
  w innych rekrutacjach tego klienta. Dwa powody w „Sprawie osoby”:
  `client_employed` („Pracuje u tego klienta (też przez inną firmę)”, kosz
  `data` — pracy przez pośrednika nie ma w CV ani na LinkedInie) i
  `client_refused` („Nie chce do tego klienta”, kosz `person`). Przy nich
  okno pokazuje zaznaczone pole „Dotyczy wszystkich rekrutacji tego klienta”
  (jedna osoba; przy kilku — bez pola). `autofill_whole_client=true` →
  wiersz `autofill_feedback.whole_client` (więz powodów ma jedną definicję
  w `autofill_feedback_schema.WHOLE_CLIENT_DDL`, entrypoint wykonuje ją przy
  każdym starcie), w tej samej transakcji
  `autofill_withdraw.withdraw_at_client` zdejmuje NIETKNIĘTE karty tej osoby
  od systemu z pozostałych rekrutacji klienta (archiwum bez autora,
  `autofill_withdrawn_client`, „Praca w tle” z `why: "client"`), a
  `ranked_picks` nie podsuwa jej żadnej rekrutacji tego klienta. Bez
  zaznaczenia — tylko ta rekrutacja.
- **E. Runda 3: „Nie szuka do…” i trzy nowe powody (0616, decyzja Artura
  28.10.2026).** Analiza 44 odrzuceń z 27–28.10: 9 to „Nie szuka pracy”,
  a żadna z 12 takich osób od 23.10 nie miała tego w profilu i 5 z nich
  czekało w 9 „Nowych” innych rekrutacji; 6 z 10 „Inne” to overqualified,
  błędny numer i zgłoszenie do klienta przez inną firmę. Od tej zmiany:
  * przy „Nie szuka pracy” okno pyta „Do kiedy nie podsuwać?” (3 / 6 / 12
    miesięcy albo data, domyślnie 3 miesiące) → `autofill_not_looking_until`
    (od jutra, najwyżej 2 lata, tylko przy tym powodzie — inaczej 422).
    Serwer w transakcji ruchu ustawia w profilu `availability_status =
    not_looking` i „Dostępny od” = ta data (audyt
    `candidate_availability_changed`), a `autofill_withdraw.withdraw_elsewhere`
    zdejmuje NIETKNIĘTE karty tej osoby od systemu ze wszystkich innych
    rekrutacji (archiwum `autofill_withdrawn_not_looking`, „Praca w tle”
    z `why: "not_looking"`);
  * `ranked_picks` pomija osoby z profilem „Nie szuka” bez daty albo
    z „Dostępny od” w przyszłości (`not_looking_now`); po dacie osoba wraca;
  * nowe powody: `overqualified` (kosz `search`), `wrong_phone` i
    `client_other_vendor` (kosz `data`); `client_other_vendor` jest w
    `CLIENT_WIDE_REASONS` (pole „cały klient” jak przy „Pracuje u tego
    klienta”). Więz powodów: `REASON_CHECK_DDL`.
  Odrzucone na teraz (makiety M3–M4): wygaszanie nietkniętych kart po 5
  dniach roboczych i próg 65 pkt. Raportu poniedziałkowego Artur nie
  potrzebuje — pyta o odrzucenia na bieżąco.
- **E. Dojazd do biura w km (decyzja Artura 29.10.2026, makiety
  https://claude.ai/artifact/ACs6ajioJwfu4tYrNLSTKo).** Produkcja 23–29.10:
  w 115 rekrutacjach z biurem w Warszawie 87 kart od systemu to osoby ponad
  100 km od każdego biura (66 czekało w „Nowych”, 32 weszły już po regule
  „za resztą” z 27.10); dalej poszło 20% tych, o których zdecydowano, wobec
  40% osób do 30 km. Od tej zmiany silnik liczy km w linii prostej z miasta
  w profilu (`location`, `city`) do najbliższego biura rekrutacji
  (`new_column_autofill.office_km`, `location_utils.nearest_km`, słownik
  `pl_places`, Trójmiasto = trzy miasta), gdy rekrutacja chce biura
  (`wants_office`: hybryda, stacjonarnie albo dni w biurze — także bez
  liczby dni):
  * ponad `OFFICE_FAR_KM` (100) = nie dodaje;
  * `OFFICE_NEAR_KM`–100 km (50–100) = za resztą, ostrzeżenie `office_city`
    z `km` → plakietka „Płock · 95 km”;
  * do 50 km = bez ostrzeżenia o mieście (wcześniej Pruszków dostawał „Inne
    miasto”);
  * osoba, która sama wskazała miasto biura (`office_cities`, notatki
    `preferences.locations`, relokacja) — `office_km` = `None`, reguła jej
    nie dotyczy (takie osoby szły dalej w 45%);
  * miasto nieznane albo spoza słownika (zagranica) — jak dotąd: nieznane
    przechodzi, nazwa inna niż biuro = „Inne miasto”, za resztą.
  Wyszukiwanie ręczne, „Propozycje z bazy” i bramka z 27.09 (hybryda 1–3 dni:
  inne miasto to plakietka) bez zmian — zespół może dodać kogoś z daleka sam.
  Karty dodane przed regułą: `scripts/autofill_withdraw_far_from_office.py`
  (podgląd, `--apply`), ta sama droga co karty ponad budżetem
  (`autofill_withdraw.plan_far`, archiwum `autofill_withdrawn_far_from_office`,
  „Praca w tle” z `why: "far"`).
- **E. Na Tablicy i w panelu osoby (PR 3, 23.10.2026).** Karta Tablicy niesie
  `entry_autofill` (`process_entry_meta.autofill_badge`: wynik, wymagania,
  `rate_known`, `availability_known`, `decided`, `waiting_days`,
  `decision_due`) tylko dla wejścia `system`. Karta: osoba = „System”
  (`cardOwner`), plakietka źródła „Od systemu · 81%” (ikona z dymkiem jak
  każde źródło), przycisk „Dzwonię” zamiast „Biorę”, w „Nowych” plakietka
  „N dni bez decyzji”. Panel osoby: blok „Dlaczego system dodał”
  (`DockAutofillReason`) i „Dzwonię — biorę na 12 h”. Filtr „Kto dodał” ma
  pozycję „System” (`?added_by=system`); „Brak danych” jej nie liczy.
  **Termin decyzji** (`services/autofill_decisions.py`, jedna reguła dla
  Tablicy i kolejki decyzji): 2 PEŁNE dni robocze w „Nowych” od dodania albo
  od przypisania pierwszego rekrutera, jeśli przyszedł później
  (`recruiter_since_for_jobs`: najwcześniejsze aktywne przypisanie, prowadzący
  bez przypisania — od utworzenia rekrutacji). Rekrutacja bez rekrutera =
  bez terminu (decyzja Artura 23.10.2026). „Dzwonię” (`POST /api/pipeline/claim`)
  zapisuje w `entry_meta` `decided_at`/`decided_by`/`decision="call"` na
  stałe — wygaśnięcie blokady 12 h nie przywraca terminu. Przesunięcie dalej
  albo odrzucenie zdejmuje kartę z „Nowych”, więc termin znika sam.
  Harness: `/preview/job-detail?autofill=1`.
- **E. Odrzucenie z powodem (PR 4, 0516, decyzja Artura 23.10.2026).** Ruch na
  „Odrzucony” osoby od systemu, która stoi w „Nowych” albo „Screeningu”
  (`gate_stage_row`), wymaga `autofill_reason` (12 kodów w trzech grupach,
  lista w `autofill_feedback_schema.REASONS`) i `autofill_learned_from`
  (`profile` | `call`); bez nich 422 `{code: "AUTOFILL_REASON_REQUIRED"}`, przy
  innej osobie — 422, „Inne” bez `notes` — 422. Walidacja przed zapisem, zapis
  wiersza `autofill_feedback` w tej samej transakcji co ruch. **Kosz raportu**
  (`autofill_feedback.bucket_for`) liczy się z migawki `entry_meta`, nie
  z dzisiejszego profilu: wymagania → `search`; CV nieaktualne i profil się nie
  zgadza → `data`; „za droga” → `search` tylko wtedy, gdy system ZNAŁ stawkę
  powyżej budżetu (`resolve_job_budget_hourly`), inaczej `data`; nie szuka,
  nie odbiera, już u nas → `person`; „Inne” → `other`. „Ile chce?”
  (`autofill_rate_hourly`, PLN/h) idzie do „Stawki od” tą samą drogą co
  stawka z „Zweryfikowanego” (`_record_rate_from_move`). Front: pole
  `AutofillFeedbackField` w `RejectionV2` (prop `autofill`), lustro listy
  w `lib/autofill-feedback.ts`; pytają `usePipelineMove` (Tablica, panel
  osoby) i `ScreeningFullForm` (warsztat screeningu). Przy kilku osobach ten
  sam powód idzie do każdej osoby od systemu, bez stawki.
  **Jedno pytanie o powód (decyzja Artura 27.10.2026, zgłoszenie z zespołu).**
  Przy osobie od systemu okno nie pokazuje listy „Powód” z szablonu: jedyną
  listą jest 12 powodów dla systemu, a powód z szablonu (raport lejka,
  `disqualifies_person`, pytania o stawkę i tryb pracy) liczy
  `templateReasonFor` z mapy `AUTOFILL_TEMPLATE_REASON`; bez odpowiednika —
  „Inne” z nazwą powodu na początku notatki. Bo przez pierwsze 5 dni w 70 na
  132 odrzuceń druga odpowiedź powtarzała pierwszą („Za wysokie oczekiwania”
  + „Za droga” 44 razy), a szablon nie ma „Języka” ani „Lokalizacji”
  (41 razy „Inne”, 7 razy „Nie pasuje kulturowo” przy języku). Nie wracaj
  do dwóch list; nowy powód dla systemu = wpis w mapie.
- **E. Kolejka decyzji i poranny dzwonek (PR 5, 0517).** „Czeka na Ciebie”
  (`board_flow._autofill_decisions`, pole `flow.autofill_decisions` +
  `autofill_decisions_total`, sekcja `BoardAutofillDecisions`) pokazuje
  Rekruterowi osoby od systemu z jego rekrutacji (`_recruiting_job_ids`) po
  terminie decyzji — ta sama reguła co Tablica (`autofill_decisions.due_decisions`):
  „Nowi”, wejście `system`, bez `decided_at`, rekrutacja z rekruterem. Akcje:
  „Dzwonię” (`/claim`) i „Otwórz” (`/jobs/{id}?candidate={cid}`, tam „Odrzuć
  z powodem”). Dzwonek `autofill_decisions_due` (kategoria „Kandydaci”, sekcja
  pipeline, bez maila, `ALTER TYPE` w 0517 + lustro w `entrypoint.sh`):
  `autofill_decisions_bell.send_decision_bells` z `run_all_triggers`, dni
  robocze 8–17, raz dziennie (`app_settings['autofill_decisions_bell_state']`),
  JEDEN na Rekrutera (`job_team.working`) — liczba osób i do trzech rekrutacji,
  link `/dashboard#czeka-na-ciebie`.
- **E. „Jakość podpowiedzi systemu” i raport poniedziałkowy (PR 6, 0518).**
  Ekran `/insights/autofill` (link w nagłówku Insights, okruszek „Jakość
  podpowiedzi systemu”, harness `/preview/autofill-quality`):
  `GET /api/autofill-quality/summary?days=7|30|90` i `GET …/reports` za
  bramką sekcji Insights (agregaty bez nazwisk), decyzja „Robimy / Nie”
  (`POST …/reports/{id}/proposals/{i}/decision`) — admin i Head of
  Recruitment. **Liczby liczy kod** (`autofill_quality.summary`): dodane,
  „Dzwonię”, odrzucenia per kosz i powód, „Zweryfikowany” osób od systemu na
  tle `added_manual`/`proposal`, czekający po terminie, najsłabsze rekrutacje
  (od 3 odrzuceń, sort po udziale błędów wyszukiwania). **Propozycje układa
  model** (klucz `autofill_quality_report`, F35, Sonnet 5, prompt
  `AUTOFILL_QUALITY_REPORT`, do 30 opisów odrzuceń w znacznikach); kod
  odrzuca propozycję bez tytułu albo z koszem spoza `search|data|person`, a
  bez modelu raport idzie z `rule_proposals`. Raport (`autofill_quality_reports`,
  jeden na tydzień, `week_start` = poniedziałek poprzedniego tygodnia) robi
  `run_all_triggers` w pierwszym dniu roboczym tygodnia 8–17; dzwonek
  `autofill_quality_report` do `AUTOFILL_REPORT_RECIPIENT_EMAILS` (bez
  ustawienia — aktywni admini), tylko gdy w tygodniu coś się działo.

- **A. Co noc WSZYSTKIE rekrutacje w pracy (decyzja Artura 30.09.2026).**
  Nocna pętla (okno `AUTO_FULL_REVIEW_WINDOW_START/END_HOUR` = 1–5 w
  `BUSINESS_TZ`, tick co 60 s, heartbeat `auto_full_review`) bierze każdą
  opublikowaną rekrutację w pracy (`IN_WORK_STATES`) bez przeglądu tej nocy:
  najpierw ze zdarzeniem nowszym niż ostatni przegląd, potem „Szukamy”, potem
  najdawniej przeglądane. Do 30.09 sygnałem było samo zdarzenie i propozycje
  dostawało 5 rekrutacji na noc — nowe CV w bazie nie jest zdarzeniem.
  „Bez zmian” (ten sam odcisk) pomija przegląd tylko przez
  `UNCHANGED_MAX_AGE` (20 h). Dysk trzyma retencja: przegląd automatyczny
  zastąpiony nowszym zakończonym przeglądem tej rekrutacji jest kasowany
  (`candidate_search_retention.expired_run_ids`) — stan ustalony to jeden
  przegląd (~75 MB) na rekrutację. Raz na noc przed przeglądami
  (`_nightly_maintenance`): przeliczenie statystyk umiejętności krytycznych
  (co tydzień) i poniedziałkowy skrót propozycji do DL. Zdarzenie zapisują: publikacja, PATCH
  z `_SIGNIFICANT_FIELDS` **albo `_AUTO_REVIEW_EXTRA_FIELDS`** (budżet, tryb
  pracy, dni w biurze — osobna lista, żeby nie wywoływać rescanów Targu) oraz
  zapis Championa. `enqueue_job` pisze też przy `AUTO_MATCH_ENABLED=false`
  (`job_events_enabled`) — wtedy od razu jako `skipped`, bo `pending` bez
  workera wisiałby bez końca i częściowy UNIQUE połykałby kolejne zmiany.
- **A. Przegląd pod starą wersją reguł ma pierwszeństwo jak zdarzenie**
  (07.10.2026, `auto_full_review._reviewed_under_older_versions`): ostatni
  przegląd automatyczny z innym `must_gate_policy`, `must_gate_mode` albo
  `ranker_version` niż dziś daje w oknie propozycji 409 „Request zmienił się”,
  więc idzie na początek kolejki. Przegląd bez tych kluczy nie liczy się jako
  nieaktualny. Bump `MUST_GATE_POLICY_VERSION` w ciągu dnia i tak zostawia
  takie przeglądy do najbliższej nocy — wdrażaj go przed oknem 01–05.
- **A. Limity:** najwyżej jeden przegląd na rekrutację na noc (także nieudany),
  `AUTO_FULL_REVIEW_MAX_PER_NIGHT` (25 od 30.09.2026) łącznie, jeden nowy przegląd na tick,
  odcisk requestu równy ostatniemu nie-nieudanemu przeglądowi automatycznemu =
  pominięcie. **Automat ustępuje ludziom**: nie startuje, gdy JAKIKOLWIEK
  przegląd jest w kolejce/w toku, a worker i tak bierze ręczne pierwsze.
  Wywrotka jednej rekrutacji nie blokuje następnej (`_skipped_tonight`).
- **A. `version_trace.origin = "auto"`** (`candidate_search_store.is_auto_run`,
  `auto_origin_clause`; w `version_trace`, bo `metrics` nadpisuje telemetria):
  autor = `recruiter_id`, `tac_id`, aktywne przypisanie rekrutera, Delivery
  Lead, twórca (`_author_id`; brak wszystkich = pominięcie). Do 23.10.2026
  rekrutacja bez `recruiter_id`/`tac_id` nie miała przeglądu w ogóle (133 z 203
  w pracy) — silnik dopełniania „Nowych” potrzebuje puli każdej. Taki
  przegląd **nie zajmuje żadnego z dwóch slotów autora** (`start_search`),
  **nie jest chroniony przez retencję** (filtr stoi WEWNĄTRZ rankingu
  `protected_run_ids` — inaczej zdjąłby ochronę z ręcznego przeglądu tej samej
  osoby), **nie dzwoni autorowi** i **czyta go każdy, kto przejdzie bramkę
  rekrutacji** (`owned_run` → `shared_auto_run`; cudzy RĘCZNY przegląd zostaje
  404). Policzony profilem punktacji BEZ użytkownika (globalny/klienta), więc
  odczyt też porównuje odcisk tym profilem — osobisty profil oglądającego nie
  daje 409.
- **A. Publikacja:** w transakcji kończącej przegląd, w savepoincie
  (`publish_on_finish`, nigdy nie rzuca): WSZYSTKIE wiersze
  `eligible ∧ measured ∧ fit_score ≥ AUTO_FULL_REVIEW_MIN_SCORE`
  (osobny próg, ta sama skala co `AUTO_MATCH_MIN_SCORE` od 21.10.2026), które
  przechodzą `is_good_match` → `upsert_proposals(source="full_base")` z wersją
  CV i dowodami przez `sanitize_evidence` (same nazwy wymagań). Znacznik
  `metrics.auto_proposals`; `reconcile_unpublished` domyka przeglądy bez niego.
  Od 28.10.2026 przy mniej niż `AUTO_FULL_REVIEW_MIN_COUNT` (40) osobach od
  progu dochodzą najlepsi spod progu do łącznie 40 — liczniki i dzwonek liczą
  tylko od progu (`rekrutacja-tablica/najlepsze-40-i-ukryci-przez-musi-miec.md`).
- **A. Pula dopełniania „Nowych” (0513, decyzja Artura 23.10.2026).** Najnowszy
  przegląd rekrutacji w pracy (ten sam warunek co wygaszanie `expired`) zastępuje
  `job_autofill_pool` rekrutacji: `AUTOFILL_POOL_SIZE` (150) najlepszych
  `eligible ∧ measured`, z KAŻDYM wynikiem i bez `is_good_match` — silnik trzyma
  „Nowych” na 20 także osobami poniżej progu. Dowody = same nazwy wymagań
  (`matched_must`, `missing_must`). Pula przeżywa retencję przeglądu (2 dni) do
  następnego przeglądu tej rekrutacji; przegląd bez wektora jej nie rusza.
  Propozycje bez zmian. Wpis „Praca w tle” niesie `autofill_pool` (liczba).
- **A. Znani zespołowi wyżej (decyzje Artura 07.10.2026, flaga
  `KNOWN_PEOPLE_BOOST_ENABLED`, domyślnie OFF).** `services/known_people_signal.py`:
  punkty za weryfikację (verified+) przy 25 najbardziej podobnych rekrutacjach
  (2,5 × podobieństwo) i za weryfikację gdziekolwiek w ostatnich 90 dniach (3);
  osoba odrzucona przez tego samego klienta (`ended_by='client'`, bez kolumny —
  po wysłaniu CV) punktów nie dostaje. Punkty idą do `evidence.history`
  (same id, etapy, daty; tytuły rozwija `api/job_proposals._history_sources`)
  i zmieniają WYŁĄCZNIE kolejność: `list_for_job` i `compareProposals` sortują
  po wynik + punkty, pokazywany procent bez zmian, bez osobnej sekcji. O tym,
  kto trafia do propozycji, dalej decyduje próg. Badanie 06.10.2026
  (`docs/audits/2026-10-06/voyage-embeddings-research.md`): właściwe osoby w top
  100 z 33% do 52%.
- **A. Bez limitu, `expired`, `added` tylko z człowieka (0422, decyzja Artura
  07.10.2026).** Limitu 60 nie ma (`AUTO_FULL_REVIEW_TOP_K` nieczytane, zostaje
  dla skryptów audytów); publikacja idzie paczkami (`_PUBLISH_PAGE`). Po
  kompletnym przeglądzie (bez niepełnego pokrycia — także zaakceptowanego),
  który jest najnowszym przeglądem rekrutacji z wynikami (`_newest_result_run`,
  także w `reconcile_unpublished`), otwarte `full_base` z innym `run_id`
  dostają `expired` (`job_proposals.expire_full_base`); powrót osoby w kolejnym
  przeglądzie = `proposed`. Wierszy NIE kasujemy (`request_allocation` czyta
  istnienie `full_base`); po 30 dniach `queue_retention` czyści im `evidence`.
  `expired` nie głosuje w statusie pary (`_live()` w każdym liczniku i liście).
  `added` stawia wyłącznie dodanie przez człowieka
  (`add_candidates_to_job(mark_proposals=True)` — trasa bez tokenu integracji
  i przepięcie); karta z integracji i automat propozycji nie zamykają.
  Otwarcie zakładki „Propozycje z bazy” zapisuje `POST …/proposal-inbox/opened`
  (`Activity proposal_inbox_opened`, raz na osobę/rekrutację/dzień), a
  „Czeka na Ciebie” rekrutera ma blok `flow.top_proposals` (3 najlepsze na
  rekrutację, `job_proposals.top_open_by_job`).
- **B. `AUTO_MATCH_MODE = dry_run | propose | add`** (`auto_match_outbox.auto_match_mode`
  — JEDNO miejsce; puste = `propose`, literówka = `dry_run`). W `propose`
  dobry wynik daje decyzję `proposed` w dzienniku i wiersz `job_proposals`
  (`new_cv`, `cv_revision = profile_revision`) **w tej samej transakcji** —
  do pipeline'u nie wchodzi nikt. `proposed` blokuje ponowną ocenę jak inne
  decyzje (do zmiany rekrutacji), `_BLOCKING_WARNINGS` nadal dają `penalized`,
  sufity `AUTO_MATCH_MAX_*` obowiązują. Powiadomienie:
  `NotificationType.auto_match_proposals` — JEDEN dzienny digest na
  (rekrutacja, odbiorca), link `/jobs/{id}?tab=similar`; kolejne propozycje
  tego dnia PODBIJAJĄ licznik w tym samym wpisie i odznaczają „przeczytane".
- **B. Wynik pary = „Dop.” (21.10.2026).** `run_candidate_event` i
  `run_job_event` liczą przez `auto_match_service._canonical_scored`:
  `canonical_fit.score_candidates` z profilem `resolve_active_profile(user_id=None,
  client_id=job.client_id)`, jak nocny przegląd (A). Do tej daty wołały stary
  `rank_jobs_for_candidate` / `rank_candidates_for_job` z `DEFAULT_PROFILE`
  (warstwa screeningu, semantyka z wektora treści oferty), więc próg 70 był inną
  skalą niż procent na ekranach, a panel wag HoR go nie dotyczył. Kanoniczny fit
  nie niesie kar ani ostrzeżeń — czarną listę, konflikt i wykluczenie klienta
  liczy dalej `scoring_service._check_penalties_and_warnings` (`penalized`).
  Para bez pomiaru nie dostaje decyzji: awaria pomiaru (`unavailable`, także
  jednej paczki) cofa całe zdarzenie do kolejki (`AutoMatchUnavailable`, przed
  zapisem); nieaktualny wektor CV (`stale`, `missing_index` — reconciler
  dogania go co 300 s) zostawia parę bez decyzji, zdarzenie kończy się `done`
  z `result.unmeasured`, a osobę ocenia nocny przegląd (A). Zdarzenie CV liczy
  wektory zapytań paczkami (`full_search_measurement.warm_request_vectors`,
  porcje po `_WARM_CHUNK` = 64), bo ocenia średnio 74 rekrutacje. Wyników `candidate_auto_match_log.score` sprzed 21.10.2026
  nie porównuj z nowszymi — to inny scorer (reguła „nie porównuj metryk między
  scorerami” w `kandydaci-wyszukiwanie/talent-radar-…md`).
- **C. Jedna ścieżka walidacji z kliknięciem rekrutera:**
  `api.cv_generator_b2b.enqueue_candidate_generation` (wyjęta z `POST /generate`;
  kontrakt kwoty w `test_cv_generator_ai_master_toggle.py`). Automat nie ma
  łagodniejszej kopii, więc **nie wygeneruje dokumentu łamiącego zatwierdzoną
  regułę klienta**: wymagany zrzut zgody RODO (PKO BP) = pominięcie PRZED
  wołaniem generatora (`consent_screenshot_required`), każde 422 ze wspólnej
  ścieżki (notatki, numer projektu, Champion, język) = `client_rule_inputs_missing`
  z komunikatem. Pominięcie = `Activity(cv_auto_generate_skipped, reason)`,
  bez naliczenia kwoty. Tryb = domyślny z reguły klienta (inaczej `polished`),
  język = wymuszony regułą (inaczej `pl`), nigdy blind, `project_ref` puste.
  **Pod centralnymi regułami CV (`CV_CENTRAL_POLICIES_ENABLED`, 0331)** język
  ustala wspólna ścieżka (język polityki), a tryb — od #1647 — serwer bierze
  z żądania (`central_policies.resolve_mode`: bez kompletnego Championa
  „Pod rekrutację" schodzi do Redakcji z komunikatem w ostrzeżeniach dokumentu,
  nigdy 422; sufit klienta wygrywa). Automat prosi więc o tryb z katalogu
  polityk (`policy_content_mode`, domyślnie „Pod rekrutację") — ten sam, który
  formularz zaznacza domyślnie. Wiersz dostaje ten sam stempel `central_policy`
  co po kliknięciu.
  Od 23.09.2026 (generator v3) automat pod centralnymi regułami NIE pomija PKO:
  zgodę dołącza się po generacji, a do tego czasu blokowane jest pobranie
  (`cv_consent_gate`); numer projektu PKO bierze z rekrutacji
  (`pko_job_reference`). Pomija nadal: numer projektu z
  `managed_policy.require_project_ref` bez wartości do wyprowadzenia (Energa,
  Orlen) = `client_rule_inputs_missing`; polityka czekająca na synchronizację
  (503) = `generation_unavailable`, nie „awaria". Bez centralnych reguł zgoda
  dalej daje 422, czyli pominięcie.
  **Klient dwujęzyczny (Alior, BIK, BNP, Santander): automat robi JEDNĄ wersję**
  (decyzja właściciela 21.09.2026) — `enqueue_candidate_generation(languages=
  "primary_only")`, worker pomija drugą wersję TYLKO w pierwszym przebiegu.
  Drugą dorabia rekruter jednym kliknięciem: ponowienie pakietu odpala to samo
  zadanie gałęzią „pierwszy dokument gotowy" i tam druga wersja powstaje.
  Pakiet pokazuje „Brak wygenerowanej wersji EN." (brak wiersza, nie `failed`),
  `can_retry = true`. Ręczna ścieżka bez zmian (pola nie ma w snapshotcie).
  `position_fallback` = tytuł rekrutacji, tylko z automatu: potoki używają go,
  gdy ani `presentation_position`, ani stanowisko z CV nic nie dają
  (`Candidate` nie ma kolumny `current_position` — `getattr` w `/generate`
  zawsze daje `None`, stanowisko wiersza ustala dopiero finalizacja). Testy:
  `test_cv_auto_generate_central_policies.py` (prawdziwa wspólna ścieżka).
- **C. Odpalenie:** wyłącznie `move_candidate`, PO commicie, przez `_spawn`
  (własna sesja; wyjątek przy odpalaniu jest połykany — ruch zawsze 200).
  `/bulk-move` nie przyjmuje `verified`, importy tędy nie idą. Kwota AI
  i autorstwo (`created_by`) idą na osobę, która przesunęła kartę.
  Idempotencja: `cv_generated_documents.origin='auto'` + `stage_id` +
  `source_cv_revision` z częściowym UNIQUE (0335, lustro w `entrypoint.sh`) —
  ten sam etap z tym samym CV nie generuje drugi raz; nowe CV = nowy dokument.
  W testach automat jest WYŁĄCZONY autouse-fixturą w `conftest.py` (zadanie
  przeżywałoby test, który je odpalił).
- **C. Auto-CV jest odnajdywalne tam, gdzie rekruter wysyła CV.** Istniejący
  przepływ warsztatu: lista `GET /api/cv-generator/generated?candidate_id&job_id`
  → „Zastąp szkic i otwórz edytor" (`select-generated` = SZKIC brandowanego CV
  etapu) → `finalize` (zatwierdzenie, człowiek). Automat robi tylko pierwszy
  krok i tylko bezpiecznie: `attach_as_stage_draft` podpina gotowy dokument
  jako szkic WYŁĄCZNIE, gdy etap nie ma jeszcze żadnego (`branded_status ==
  "none"`, pod blokadą wiersza; wspólna funkcja `apply_generated_to_stage_cv`)
  — istniejącego szkicu nie nadpisuje i NIGDY nie zatwierdza. Niezależnie od
  tego lista przypina na początku auto-CV z `needs_review: true` (`origin:
  "auto"`, `stage_id`; także z parametrem `?stage_id=`), a karta tablicy niesie
  `auto_cv_ready` (jedno zapytanie na tablicę). „Wymaga przeglądu" ma JEDNĄ
  definicję (`services/cv_auto_review.py`): brak zatwierdzonej wersji z tej
  generacji i brak etapu, który ma ją jako `finalized`.
- **C. Rekruter nie czeka w ciemno na CV (14.10.2026, decyzja Artura).**
  Szkic automatu (`attach_as_stage_draft` z domyślnym `ATTACH_ACTION`) →
  `qc_after_attach(notify_ready=True)`: QC (`cv_qc.run_after_move`), potem —
  gdy przebieg ma uwagi, CV jest edytowalne, a karta stoi na „Zweryfikowanym”
  albo dalej — poprawki AI raz z góry (`cv_qc.generate_fixes`, pamięć
  `dz_review_hints` na wierszu z CV, tym samym, na którym otwiera się edytor),
  na końcu dzwonek `cv_ready` do osoby, która przesunęła kartę: „CV gotowe do
  sprawdzenia: <osoba>”, treść „<rekrutacja> · QC: N uwag (M blokuje)” albo
  „· QC bez uwag” (bez QC — sam tytuł), link `…?candidate=…&panel=cv`.
  Ręczna generacja z etapem, `select-generated`, `select-document`,
  `branded/upload` i `select-stage-cv` dostają QC i poprawki (te od
  „Zweryfikowanego”), bez dzwonka. Pominięcie albo awaria, przy których
  rekruter musi zrobić CV sam (`NOT_DONE_REASONS`: brak klienta, brak pliku
  CV, zrzut zgody, dane reguły klienta, generator niedostępny, nieudana
  generacja i każda inna awaria), dzwoni `cv_ready` „Automat nie zrobił CV:
  <osoba>” z polskim powodem (lustro `SKIP_REASON_PL`). Bez dzwonka:
  `pair_cv_exists`, `already_generated`, `no_permission`. `pair_cv_exists`
  sprawdza się PRZED plikiem w profilu i robi QC + poprawki istniejącego CV
  pary. Karta Tablicy: `auto_cv_state: "processing"` (wiersz etapu
  z dokumentem `origin="auto"` w toku), `company_cv` (`company_cv_refs`)
  i `qc.warnings_count`; „Moje następne kroki” ich nie liczą (`None`).
- **Awarie automatów: admin po serii; rekruter przy auto-CV od 14.10.2026**
  (`services/automation_failures.py`). Awaria = wpis z polskim powodem w „Pracy
  w tle" (`auto_full_review_failed`, `auto_match_failed`,
  `cv_auto_generate_failed`) + `logger.error` (→ Sentry). TEN SAM automat 3 razy
  z rzędu (licznik w `app_settings['automation_failure_streaks']`, pod `FOR
  UPDATE`, zerowany pierwszym sukcesem) = JEDNO powiadomienie
  `automation_failing` na serię, tylko dla adminów (`ADMIN_ONLY_NOTIFICATION_TYPES`).
  Pominięcia (reguła klienta, brak CV) NIE są awariami. Sukces bez otwartej
  serii nie dotyka bazy (`_known_clean`) — auto-match księguje go przy każdym CV.
  Rekruter dostaje przy auto-CV tylko `cv_ready` z punktu wyżej (nie serię).
- **Obserwowalność dysku:** `GET /api/admin/index-coverage` → `candidate_search`
  niesie `auto_runs`, `auto_runs_rows` i `auto_runs_estimated_bytes` (szacunek
  proporcjonalny do migawek populacji — dokładny pomiar wymagałby skanu).
- **D. `GET /api/pipeline/stages/{id}/screening` → `suggestions`** z gotowego
  `_notes_insights` (zero wywołań modelu, ZERO zapisów). `rate` tylko dla ról
  z `user_can_edit_rates`; pozostałe dostają `rate_redacted: true`.
  `source_note_id` jest dziś zawsze `null` — `_notes_insights` to agregat ze
  wszystkich notatek i nie pamięta źródła.
- **Front automatów (21.09.2026):** zdania „Pracy w tle" składa JEDEN moduł
  `frontend/src/lib/job-background-events.ts` (serwer daje polski `message`
  tylko przy awariach; kody pominięcia auto-CV → `autoCvSkipReason`). Ten sam
  klucz zapytania (`jobBackgroundEventsQueryKey(jobId, 30)`) czyta zakładka
  w `HistoryChatSlideOver` i `AutoCvSkipNotice` w sekcji CV panelu — nowy kod
  pominięcia dopisz do `SKIP_REASON_PL`, inaczej wyjdzie „powód: <kod>".
  Endpoint nie stronicuje: „Pokaż więcej" podnosi `limit` (sufit 100).
  Podpowiedzi screeningu (`ScreeningSuggestionChips`): stawka WYŁĄCZNIE
  wypełnia stan doku (idzie przy ruchu na „Zweryfikowany"); waluta inna niż
  PLN albo nieznana jednostka = chip bez „Użyj". **Dostępność NIGDY nie trafia
  do „Notatek rekrutera"** — to pole widzi KLIENT w share portalu, a podpowiedź
  pochodzi z wewnętrznych notatek. „Użyj" to jawny zapis w PROFILU
  (`PATCH /api/candidates/{id}` z `availability_date`, bramka `candidate.write`
  — bez niej przycisku nie ma; toast + unieważnienie kanbana i kluczy
  kandydata). Mapowanie ma JEDNO miejsce, `availabilityProfilePatch`: data ISO
  albo jednoznaczne „od razu" (= dziś); `availability_status` to postawa wobec
  ofert, nie termin — nie ustawiamy go. Reszta („za 2 tygodnie", okres
  wypowiedzenia) = chip bez „Użyj" z linkiem „uzupełnij w profilu".
