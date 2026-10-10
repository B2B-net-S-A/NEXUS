# Automaty rekrutacji v3 (21.09.2026, migracja 0335)

Cztery automaty, wszystkie WŁĄCZONE domyślnie, każdy za wyłącznikiem env,
którego stan OFF = zachowanie sprzed 21.09. **Nic zewnętrznego ani
nieodwracalnego nie dzieje się bez kliknięcia człowieka**: żaden automat nie
wysyła nic do klienta, nie przesuwa karty i nie dodaje nikogo do pipeline'u
(wyjątek: jawnie ustawione `AUTO_MATCH_MODE=add`). Zdarzenia automatów lądują
w `Activity(entity_type="job_automation", entity_id=<job_id>)` — osobny typ
encji, żeby nie mieszać się z historią rekrutacji — i czyta je
`GET /api/jobs/{id}/background-events` (zakładka „Praca w tle", bramka jak
skrzynka „Propozycje"; nazwisko kandydata tylko dla ról z odczytem kandydatów,
stan auto-CV czytany NA ŻYWO z wiersza dokumentu).

| Automat | Wyłącznik | Kod |
|---|---|---|
| A. nocny pełny przegląd bazy → „Propozycje" (`full_base`) | `AUTO_FULL_REVIEW_ENABLED` | `services/auto_full_review.py`, `tasks/auto_full_review.py` |
| B. nowe CV → „Propozycje" (`new_cv`) | `AUTO_MATCH_MODE=dry_run` | `services/auto_match_service.py` |
| C. auto-CV po ruchu na „Zweryfikowany" | `CV_AUTO_GENERATE_ON_VERIFIED` | `services/cv_auto_generate.py` |
| D. podpowiedź stawki/dostępności w arkuszu screeningu | brak (czysty odczyt) | `services/screening_suggestions.py` |

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
  autor = `recruiter_id` albo `tac_id` (brak obu = pominięcie), ale taki
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
  (osobny próg — przegląd punktuje kanonicznym fitem, auto-match starszym
  scoringiem), które
  przechodzą `is_good_match` → `upsert_proposals(source="full_base")` z wersją
  CV i dowodami przez `sanitize_evidence` (same nazwy wymagań). Znacznik
  `metrics.auto_proposals`; `reconcile_unpublished` domyka przeglądy bez niego.
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
- **Awarie automatów: rekruter bez dzwonka, admin po serii**
  (`services/automation_failures.py`). Awaria = wpis z polskim powodem w „Pracy
  w tle" (`auto_full_review_failed`, `auto_match_failed`,
  `cv_auto_generate_failed`) + `logger.error` (→ Sentry). TEN SAM automat 3 razy
  z rzędu (licznik w `app_settings['automation_failure_streaks']`, pod `FOR
  UPDATE`, zerowany pierwszym sukcesem) = JEDNO powiadomienie
  `automation_failing` na serię, tylko dla adminów (`ADMIN_ONLY_NOTIFICATION_TYPES`).
  Pominięcia (reguła klienta, brak CV) NIE są awariami. Sukces bez otwartej
  serii nie dotyka bazy (`_known_clean`) — auto-match księguje go przy każdym CV.
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
