# Audyt 25.09.2026 — reguły po naprawie

<!-- indeks: rundy 1–13: poczta zamówień, zamówienia MD, kontrakty, rekrutacja, wyszukiwanie, bezpieczeństwo i logi, integracje, usuwanie kandydata, konkursy, get_db, tokeny -->

Raport: https://claude.ai/artifact/BtnT7zb5kwPk5gNLvg56x6 (commit `eed680914`). Reguły,
które łatwo cofnąć „przy okazji”:

- **Poczta zamówień.** `titles_collide`: krótsza forma numeru („30751” ↔ „4500030751”)
  to ten sam numer WYŁĄCZNIE, gdy oba są z samych cyfr (słowny przedrostek, np. „SAP”,
  dozwolony); numery z `/`, `-` albo literami porównuje się w całości — do 25.09
  „830/2026” był tym samym co „1830/2026” i automat nadpisywał szkic. Szkic LINII
  zamówienia MD/kosztowego nigdy nie jest `FILL_DRAFT` (planer: `ACTION_GROUP`, writer
  odmawia starego planu). Mail bez wpisu w dzienniku (błąd `/attachments`, brak
  `contentBytes`) zatrzymuje `last_seen_received_at` na swoim `received_at − 1 s`,
  także cofając znacznik; bieg ma `partial` i `stats.unprocessed_messages`, a
  `checks.order_mail` = `degraded` (`order_mail_health_verdict`). Trzyma najwyżej
  `ORDER_MAIL_UNPROCESSED_HOLD_HOURS` (24 h) — starszy dostaje wpis „Nieudane”
  i przestaje trzymać (jeden zepsuty mail nie może zamrozić skrzynki). Wpis `failed` NIE jest
  końcowy: ponowna weryfikacja przetwarza go z zapisanego PDF-a (młodszy niż 7 dni,
  najwyżej 3 próby, `document_meta.failed_retry`, próba liczona przed odczytem);
  `_first_with_sha` pomija `failed`. Kolejka ma zakładkę „Nieudane”.
- **Zamówienia MD.** „Zamiany kontraktora” nie ma na osobie z zaplanowanym „Wejdź za
  konsultanta” (409); gdy zamiana już jest, `activate_due_takeovers` anuluje zastępstwo
  z wpisem w historii zamiast przenosić pulę drugi raz. `close_order_group` /
  `reopen_order_group` decydują na nagłówku spod `_lock_group_row` (jak cancel/restore).
  Korekta FIN-MD-02 celu przejęcia schodzi najpierw z opcji, potem z podstawy, nigdy
  poniżej zera. Rekrutację zamówienia sprawdza jedna `_assert_job_of_client` (POST
  `/orders`, PATCH, Flow B — 422 po polsku). PATCH zamówienia spoza grupy: szkic →
  `active` przechodzi bramkę kompletności (422 `order_incomplete` + `missing`), szkic →
  `completed` = 409 `order_is_draft`. `works_until_md_exhausted` i `still_billing_md`
  dotyczą wyłącznie linii grupy (M10). `run_daily_order_cost_sync` czyta stan spod blokady.
- **Kontrakty i Finanse.** „Cofnij zakończenie” z migawką `ending` idzie
  `ended → active → ending`; bez daty albo z datą miniona — `active`. Cofnięcie bez
  migawki zachowuje datę końca umowy zlecenie/UoP (B2B nadal bezterminowa). PATCH daty
  końca na umowie „Zakończony” to reaktywacja przez `reopen_contract` (wpis historii,
  Generator B2B wraca, migawka `superseded`) — CHYBA ŻE umowa ma rozwiązanie
  (`agreement_termination_mode`): wtedy to korekta daty (`ended → active → ending`),
  rozwiązanie, wiersz Generatora i migawka zostają. Przepięcie na innego klienta odmawia
  (`duplicate_contract_at_target`), gdy osoba ma tam żywy kontrakt. Reguła „obecny
  kontrakt” w SQL ma JEDNĄ definicję: `contractor_identity.current_contract_clause(as_of)`
  (katalog, analityka kontraktów, `consultant_population`). Marża % Rady dzieli przez
  `margin_revenue` (składowa `margin_revenue_pln`, redagowana w `without_money`).
  Finanse → Zmiany niosą `old_currency`; stara strona = `old_currency ?? currency`.
- **Rekrutacja.** Bez osoby od Cpro na firmę zadanie „do wrzucenia” z osobą zapasową
  rekrutacji (`jobs.cpro_sender_id`, `task_assignee_id`) widzi ona oraz admin i HoR,
  a wrzucić może ona (`can_send_to_cpro(..., fallback_sender_ids=…)`); osoba firmowa
  zawsze wygrywa. Ruch z „Zamkniętych” liczy bramki (QC, Cpro, debrief) od ostatniej
  kolumny sprzed zamknięcia (`pipeline_move_rules.gate_stage_row`). Okno „Przesuń dalej”
  nie blokuje QC na etapie Cpro u Nordei. Efekty uboczne `/move` po commicie idą przez
  `_post_commit_effect` (savepoint), odpowiedź liczy się przed nimi. Rozmowę u klienta
  (i debrief) otwiera każdy z dostępem do jej rekrutacji; `recruiter_id` wniosku
  o terminy = aktywna osoba z rolą wewnętrzną i dostępem (422). „Porządek w requestach”:
  zamknięta rekrutacja przyjmuje tylko „Zakończony” (409), wiersz niesie `closed`.
- **Wyszukiwanie.** Całe słowo dostaje też `'{słowo}.js':*` i (tylko `DOT_PREFIXES`)
  `'{słowo}.net':*` — NIGDY ogólnego `'{słowo}.':*` (klauzula „B2B.net S.A.”, adresy
  e-mail). Filtry dat listy liczą dobę w Europe/Warsaw (`business_date_range`); daty
  spoza 1900–2100 = 422. Weto HM nie zwalnia z „tylko umowa o pracę”.
- **Bezpieczeństwo i logi.** Każdy eksport CSV/XLSX przepuszcza tekst przez
  `app.core.export_safety.safe_cell`/`safe_row` (`'` przed `= + - @ \t \r`; wyjątek:
  same cyfry i separatory, np. telefon `+48 …`); lokalne kopie zakazane
  (`test_export_formula_injection.py`, AST). Pętle Slacka logują tylko kod HTTP albo klasę
  wyjątku (adres webhooka to sekret). Silnik bazy ma `hide_parameters=True`. Dokument
  kandydata idzie inline wyłącznie dla PDF/PNG/JPEG/GIF/WebP (`_safe_document_disposition`).
- **Integracje.** Fazy Traffita z paczkami (aktywności, pliki, CV, rekrutacje) zapisują
  wiersz w savepoincie; błąd wiersza → `add_error` z `ext=`, nigdy `rollback()` sesji.
  Kursory stron niosą `carried_errors` (wznowienie blokuje `__daily__`). `skip_on_5xx`
  przy nieznanej liczbie stron kończy się wyjątkiem po `TRAFFIT_MAX_CONSECUTIVE_5XX` (5).
  Faza `jobs` commituje co 200 wierszy. Zadania w tle z endpointów uruchamia wyłącznie
  `app.core.tasks.spawn`. Handlery async wysyłają maile przez `asyncio.to_thread`.
  `send_system_email` zwraca True/False/None (`DELIVERY_UNCERTAIN`) — przy None wołający
  nie zwalnia rezerwacji (`email_delivery_uncertain`), log ma tylko `to_ref`. Outbox
  indeksu ponawia `failed` po 1/5/15/60 min; awaria Voyage nie zużywa prób. Nowa
  publikacja na portal anuluje zaległe zamknięcie starych `failed` tej pary. Jarvis
  wiąże rozmowę z kandydatem po każdym narzędziu (od razu w bazie), blokada tury to
  `TurnClaim` przedłużany co krok, `JARVIS_MAX_TOKENS_PER_STEP` = 4000.

### Runda 2 (25.09.2026, po PR #1833)

Raport: https://claude.ai/artifact/Hcs6cYoiaJ187RmuFMZspY. Główna przyczyna rundy 2:
poprawka w jednej ścieżce, a ta sama reguła żyła w bliźniaczej — przy każdej poprawce
grep wzorca w całym katalogu; nowy zapis do tabeli z częściowym UNIQUE sprawdzaj na
przypadek drugiego wiersza.

- **Poczta.** Wpis bez sha (`uq_order_mail_documents_message_no_attachment`) jest jeden
  na wiadomość — kolejne załączniki bez treści dopisują się do opisu istniejącego wpisu
  „Nieudane” i nie trzymają znacznika; wpisy dziennika zapisuje `_add_journal_row`
  (savepoint + `IntegrityError`); wpis główny po `process_pdf_bytes` przy konflikcie
  wycofuje CAŁĄ transakcję (mógł już zapisać zamówienie) i liczy się jako pominięty.
  Za duży PDF = wpis „Nieudane” z sha, bez pliku.
  `_first_with_sha` pomija `failed` i `duplicate_attachment`. „Nieudane” da się odrzucić
  (admin albo przypisany DL); zdanie „system ponawia sam” liczy serwer
  (`failed_retry_pending` — lustro `_failed_candidate_ids`). `error` wpisów i stanu biegu
  = klasa wyjątku po polsku, nigdy `repr`.
- **Kontrakty.** Cofnięcie zakończenia z celem Aktywny/Kończący się i minioną datą końca
  = bloker `end_date_passed` (najpierw aneks); bez migawki i aneksu data końca równa
  dniu zakończenia jest śladem zakończenia → umowa wraca bezterminowa. Reaktywacja
  i korekta daty rozwiązanej umowy w `PATCH /contracts/{id}` WYŁĄCZNIE przy zmianie
  `end_date` w tym żądaniu. Skaner wygasania domyka datą każde samodzielne zamówienie
  (także z `md_total`); wyjątek „budżet, nie kalendarz” dotyczy tylko linii grup MD.
- **Rekrutacja.** Para bez żadnego wiersza etapu liczy bramki od „Nowi” — bez CV
  firmowego QC odmawia 409 `CV_QC_FAILED` (`stage_id: null`), przechodzi tylko obejście
  DL/admina. `gate_stage_row` liczy kolumny jednym odczytem definicji etapów.
  Bulk-add (`proposals/bulk`, także `assignable-stages`) przyjmuje wyłącznie etapy
  kolumn „Nowi”/„Screening” (`_is_entry_column`) — dalsze mają bramki `/move`.
  Samoleczenie „Zakończony” w PATCH bez zmiany daty nie dotyczy umowy z
  `terminated_at` albo rozwiązaniem.
  `/bulk-move` robi efekty po commicie per osoba przez `_post_commit_effect`. Rekruter
  wniosku o terminy (jawny i podpowiadany) przechodzi `slot_recruiter_eligible`.
  Przekazanie od praktykanta osoby `employment_only` PRZECHODZI (decyzja Artura
  25.09.2026) — propozycja niesie `evidence.trainee.employment_only` i plakietkę
  „Tylko umowa o pracę”.
- **Wyszukiwanie.** Odwrócony zakres stawki/stażu = 422 także na liście i w eksporcie
  (`reversed_range_message`); niepusty tekst dosłowny krótszy niż 2 znaki = 422
  (`LiteralTextTooShort`). Północ dnia firmy: `app.core.scheduling.local_day_start_utc`.
- **Integracje.** Każdy savepoint w importerze Traffita decyduje o sesji przez
  `_recover_session` (rollback tylko po utracie połączenia / `PendingRollbackError`;
  utracona paczka = błąd nieprzypisany, watermark stoi) — pilnuje
  `test_every_savepoint_handler_decides_about_the_session`. Nowa publikacja na portal,
  która anulowała zaległe zamknięcie wiersza `failed`, dziedziczy sprzątanie
  (`remote_state='inherited_cleanup'`) — wycofanie przed workerem kolejkuje `close`.
  Test `spawn` skanuje całe `app/` (wyjątki z powodem).
- **Frontend.** Każdy picker z listą z zapytania: `PickerQueryState` (albo `loadState`
  w `MultiSelectFilter`), `CommandEmpty` wyłącznie przy `isSuccess`; `isLoading ? … :
  <CommandEmpty>` to błąd (v5: po awarii `isLoading=false`). Wyszukiwarka włączana po
  otwarciu listy podaje `isLoading` jako `isPending`.

### Runda 3 (25.09.2026, po PR #1836)

Raport: https://claude.ai/artifact/CN4ffWLKsPQYm38pgGN2Dr. Decyzje Artura: przeskok
„Zweryfikowany → Rozmowa u klienta” bez QC zostaje (blokuje tylko front); progi wyścigu
to migawka na okres; prywatne spotkania importujemy bez treści.

- **Umowy B2B.** Podpisane w Generatorze rozwiązanie/wypowiedzenie (także Partnera) nie
  zamyka wiersza od razu — zapisuje tryb (`mark_pending_dissolution`), a wiersz zamyka ta
  sama synchronizacja co po „Zakończ współpracę”, z migawką, gdy kontrakt jest „Zakończony”.
  Ręczna zmiana statusu w rejestrze czyści `termination_restore`; wiersz dopasowany po
  osobie dostaje `contract_id` (fill-only). „Cofnij zakończenie” bez migawki traktuje datę
  końca jako ślad zakończenia tylko przy `terminated_at` — UZ/UoP zakończona cronem
  zachowuje datę z treści umowy.
- **Konkursy.** `GET /api/competitions/current` liczy podium przez `award_order` (jak
  zamrożenie); miejsce z remisem ma `prize_pln=0` i `tied: true`. Progi wyścigu
  miesięcznego żyją w `app_settings['monthly_race_thresholds'][RRRR-MM]` (pierwszy zapis
  wygrywa; pisze pętla autofreeze i `freeze_competition`, GET tylko czyta) — zmiana celu
  KPI działa od następnego miesiąca, cel precyzji > 100 = 422. `POST /freeze` przyjmuje
  tylko okres zakończony („RRRR-MM” albo „Q1 2026”). Liga DL liczy rolę DL także
  dodatkową. Metryki pulpitu porównują ten sam odcinek poprzedniego okresu
  (`previous_matching_window`), a kwoty wyceniają na `min(koniec okresu, dziś)`.
- **Rekrutacja i Champion.** Każde wejście dodające osobę do rekrutacji (bulk-add,
  wtyczka LinkedIn) przyjmuje tylko kolumny „Nowi”/„Screening”
  (`board_stage_badges.is_entry_column`). Zapis Championa bez zmiany `requirement_source`
  (notatki, wiersze wyszukiwania) nie woła `refresh_job_matching` ani `enqueue_job_safe`.
  Stawka ze szkicu AI trafia do budżetu tylko z dosłownego cytatu (`pln_hourly_bounds`),
  pytania szkicu są deduplikowane po treści. Zatwierdzenie opisu publicznego zapisuje
  migawkę must/nice, miasta, startu i długości w
  `job_public_profiles.sections["_approved_content"]` — strona kariery i portale serwują
  migawkę, zmiana tych pól wymaga ponownego zatwierdzenia. Import Championa z generatora
  CV wysyła tylko pola niepuste i nigdy klucza `insights`.
- **M365, Jarvis, poczta.** Callback M365 przyjmuje wyłącznie skrzynkę właściciela konta
  (`users.email` albo `microsoft_upn`, bez wielkości liter); brak adresu = odmowa, bo
  podpisany `state` nie dowodzi, czyja skrzynka wróciła. Spotkanie prywatne z Outlooka
  (`sensitivity` private/confidential) i iCal (`CLASS`) to sam termin „Spotkanie
  prywatne” (`services/calendar_privacy.py`); zmiana `EVENT_SELECT` wymaga jednorazowego
  pełnego odczytu kalendarzy (stary kursor delty pamięta swój `$select`). Mail o etapie
  przechodzi bramkę odbiorcy dzwonka. Karta akcji Jarvisa bierze nazwy wyłącznie
  z odczytu API, debrief czyta kandydata z wydarzenia. Mail odrzucenia commituje
  rezerwację przed Graphem. Poczta zamówień łapie `IntegrityError` tylko na
  `uq_order_mail_documents_*`, a odrzucony wpis „Nieudane” nie jest oryginałem sha.

### Runda 4 (25.09.2026, po PR #1840)

Raport: https://claude.ai/artifact/RzX9M85qz2QpzzTFRU6gDY. Decyzje Artura: osoba od Cpro
widzi stawki do klienta (wyjątek), ale ustawia ją tylko admin albo DL Nordei; pytania
z archiwum zostają przypięte także do otwartych rekrutacji; aneks przedłużenia i
„Cofnij zakończenie” anulują zaplanowane zastępstwo.

- **Nieaktywne konto = brak osoby — wszędzie.** Osoba od Cpro (także po zastępstwie
  i jako osoba zapasowa rekrutacji), przypisania `job_work_assignments` (zwalniane
  z powodem `inactive`, także ręczne i z kandydatami w toku), pulpit „Requesty
  i obłożenie” i filtr „Kto pracuje / Nikt nie pracuje”. Ręczne zdjęcie aktywnego
  rekrutera automatu zdejmuje też prowadzącego wpisanego przez automat.
- **Konkursy.** Ranking do wyświetlenia składa `award_ranked_rows`: miejsca 1..n
  w kolejności nagrodowej, potem osoby bez miejsca (`rank: null`). `/current`,
  `/my-position` i Liga na pulpicie nie numerują po pozycji na liście. Punktacja Ligi
  Mistrzów to migawka kwartału `app_settings['league_scoring_config']` (bliźniak
  `monthly_race_thresholds`; czytaj przez `league_scoring_config`, nigdy
  `get_scoring_config`).
- **Umowy i MD.** Rozwiązanie umowy rozpoznaje wyłącznie
  `contract_termination_sync.contract_dissolved_by_agreement` (kontrakt ALBO wiersz
  rejestru: tryb + migawka albo znacznik czekającego rozwiązania). Wyczyszczenie daty
  „Kończącego się” woła `undo_contract_termination`. „Cofnij zakończenie” blokuje
  istniejący „Powrót po przerwie” (`returned_after_break`). Zaplanowane zastępstwo
  anulują aneks przedłużenia, bulk-extend i `undo_contract_termination`
  (`cancel_scheduled_takeovers_for_contract`, wpis z `cancel_reason`); szkic zastępstwa
  nie jest następcą dla skanera, a zastępstwo za osobę z wyczerpaną pulą jest
  anulowane. „Inny numer zamówienia” w Zużyciu MD / Importach MD tylko dla liczby,
  którą wiąże reguła importu (`binds_as_order_number`).
- **QC CV i akademia.** Rola bez daty końca dalej niż na 1. pozycji = staż nieznany
  (QC: sprawdzenie ręczne, nie blokada; Luna w akademii: „bez dat”, chyba że cytat
  mówi „obecnie”).
- **Praktykant.** Status programu `completed` (awans) = zakończony. Oddzwonienie
  najpóźniej w ostatnim dniu programu; przy awansie przypinane są też niezrealizowane
  oddzwonienia. Nowe minimum stawki bez odpowiedzi o zgodzie czyści zgodę; „później” =
  dostępność nie wcześniej niż +91 dni.
- **Poczta i M365.** Klauzula używana z negacją (`~`) nie może dać NULL — porównanie
  z polem JSON przez `->>` owijaj w `coalesce` (`dismissed_unprocessed_clause`).
  Prywatność spotkania rozstrzyga pochodzenie wiersza (założone w NEXUSIE =
  `operational_owner_id`), nie typ; starsze niż rok czyści jednorazowy przebieg po id
  (`m365_old_private_scrub:<conn>`). Callback M365 przy koncie z `azure_oid` porównuje
  też `oid`.
- **Portale i prep.** Worker portali po wysyłce porównuje `options` i `approved_hash`
  z chwili wysyłki — zmiana w trakcie zostawia `update`; pewna odmowa publikacji po
  wcześniejszej próbie kolejkuje zamknięcie po externalId. Ocena prepu nie liczy pytań
  `legacy_import` przypiętych bez człowieka (prep-kit je pokazuje).

### Runda 5 (26.09.2026, po PR #1844)

Raport: `docs/audits/2026-09-25/runda-5.md` (raporty wszystkich rund są w repo —
zacznij od `docs/audits/2026-09-25/README.md`, zanim zrobisz kolejny audyt).

- **Limit ciała żądania i strażnik NUL czytają jedną stałą `REQUEST_BODY_METHODS`**
  (`core/body_size_limit.py`, z DELETE). Metoda buforowana przez strażnika bez limitu
  to anonimowe wyczerpanie pamięci jedynego procesu uvicorna.
- **HTML otwierany w nowej karcie pod originem aplikacji** (blob albo `document.write`)
  składa `core/printable_html.printable_document` (CSP w `<meta>`; `autoprint=False` =
  bez skryptu). Test AST odrzuca trasę z własnym `window.print`.
- **PATCH daty końca umowy w przód albo na „bezterminowo”** odwołuje zaplanowane
  „Wejdź za konsultanta” jak aneks przedłużenia; nocne wejście anuluje zastępstwo
  z dniem wejścia nie później niż ostatni dzień odchodzącego
  (`entry_not_after_departure`).
- **Czat `/cv-i/{token}/chat` respektuje `max_views`** bez zużywania wyświetleń; po
  ostatnim wyświetleniu przyjmuje pytania jeszcze 2 h (`CHAT_AFTER_LAST_VIEW`).
- **Formuła faktury Nordei:** OCR nigdy w otwartej transakcji ani pod blokadą;
  `fill_missing` zapisuje warunkowo (`invoice_lines IS NULL`, ta sama `file_path`
  i `file_uploaded_at`), `save_line` czyta PDF przed `FOR UPDATE`.
- **Dzień tygodnia** w powiadomieniach i przeglądach liczony w `BUSINESS_TZ`;
  `.weekday()` na UTC tylko z komentarzem „Dzień UTC celowo”, gdy godzina też jest UTC.
- `?tab=portals` otwiera okno zlecenia z rozwiniętą sekcją „Portale ogłoszeniowe”
  (`wintab=portals`).

### Runda 6 (26.09.2026, po PR #1849)

Raport: `docs/audits/2026-09-25/runda-6.md` (19 agentów audytu, 15 naprawczych).

- **Kolumna JSONB czytana przez `is_(None)` ma `none_as_null=True`** (albo predykat
  `jsonb_typeof(...) = 'null'`) — domyślnie `None` zapisuje JSON `null`, którego
  `IS NULL` nie widzi (formuła Nordei nie wracała do pętli).
- **Podpis Outlooka** (`m365/signature_cache.py`): pierwszy znacznik podpisu,
  ucięcie na pierwszym znaczniku cytatu, podpis z cudzym adresem e-mail = brak
  podpisu. Brak podpisu jest bezpieczniejszy niż cytat innej rozmowy w mailu do
  kandydata.
- **Usunięcie kandydata** zostawia nagrobek `purged_candidates` (źródło + HMAC
  `external_id`, bez danych osobowych; klucz `CANDIDATE_IDENTITY_FINGERPRINT_KEY`),
  który import Traffita czyta przed upsertem i adopcją po mailu — usunięta osoba
  nie wraca z nocnym syncem. Kasuje powiadomienia o osobie (także linki
  `/candidates/{id}` innych typów), odwołuje jej przyszłe prepy/follow-upy w Teams
  po commicie i anonimizuje jej wydarzenia kalendarza
  (`services/candidate_erasure_leftovers.py`, `followup_meetings.erase_candidate_meetings`).
  Scalanie nagrobka NIE stawia. **CV (pliki, wygenerowane, zgłoszenia) zostają
  zawsze** — decyzja Artura 26.09.2026, patrz „Integralność i uprawnienia”.
- **Pamięć nocnego przeglądu bazy** żyje we wpisie „Praca w tle”
  `auto_full_review_finished` (`run_created_at`, `fingerprint`), bo retencja
  kasuje przegląd po 2 dniach. Przegląd `failed` albo bez wektora zapytania nie
  zamyka zdarzenia. Automaty (nocny przegląd, propozycje z nowych CV, „Moi
  ludzie”) biorą tylko `request_work_state.IN_WORK_STATES`.
- **Backfill odrzuceń z Traffita** łączy `activity_date` jako czas warszawski
  (i stary odczyt UTC dla wierszy sprzed #1730). Po zmianie parsera czasu grep
  każdego SQL-a łączącego po tym znaczniku.
- **Plik z Traffita zdejmuje „główne CV” wyłącznie z innych kopii z Traffita.**
- **Walidacja w PATCH po zmianie WARTOŚCI, nie po kluczu żądania** (`update_job`:
  DL, TAC, klient; unieważnienie rankingu) — okna edycji odsyłają komplet pól.
- **Logi:** `httpx`/`httpcore` na WARNING; redakcja adresów Slacka, iCal, `%40`
  i wartości `email`/`phone`/`q…`/nazwisk w query; nazwy plików i klucze
  magazynu przez `core/log_safety` (strażnik AST `test_log_pii_filenames_keys.py`).
  Workflowy nie drukują wyników z produkcji z nazwiskami ani kluczy CV; joby
  przeciw produkcji nie wgrywają raportu Playwright.
- **CPU po tysiącach wierszy w `async def` idzie do `asyncio.to_thread` z
  single-flight** (ranking praktykantów, „Podobne rekrutacje”).
- **Przełożenie rozmowy u klienta wskazuje DL** (decyzja Artura 26.09.2026): okno
  potwierdzenia terminu pyta „To przełożenie rozmowy z DD.MM?” (lista z
  `GET /api/interview-cycle/slots/{id}/replaceable`), a odwołana zostaje tylko
  wskazana rozmowa (`supersedes_event_id`). Bez wskazania nic nie jest
  odwoływane — klient bywa, że umawia kilka rund naraz.
- **Zapytania DL w Insights liczą się od `COALESCE(opened_at, created_at)`** —
  `created_at` rekrutacji z Traffita to data importu.

### Runda 7 (26.09.2026, po PR #1860)

Raport: `docs/audits/2026-09-25/runda-7.md`.

- **Redakcja logów (`core/logging_config.py`) ma czas liniowy:** wzorce bez
  lookaheadu po zachłannym kwantyfikatorze, kwantyfikatory zaborcze, tekst
  ucinany do 32 KB przed redakcją (początek + koniec + znacznik), redakcja
  idempotentna. Nowy wzorzec = test w `test_log_redaction_linear_time.py`
  (złośliwe napisy 16–64 KB < 50 ms). Access log idzie synchronicznie na pętli
  jedynego procesu — kwadratowy regex to DoS jednym anonimowym żądaniem.
- **Paragony migracji w publicznym logu:** `scripts/show_migration_receipts.py`
  drukuje przez białą listę typów (liczby, daty ISO, ID; napis = długość, kwota
  = znacznik). Paragon 0304 zapisuje szczegóły pod
  `repair_details_0304_contract_order_sync_repair` (`load_repair_details` czyta
  też stary paragon). „Coolify set env” czyta wartość z pliku zdarzenia i maskuje
  ją przed użyciem; klucze wyglądające na sekret tylko przez `value_from_secret`.
- **Usunięty albo scalony klient nie przyjmuje zapisów:**
  `client_access.assert_client_assignable` (422 `client_deleted`/`client_merged`
  z nazwą rekordu głównego) w rekrutacjach (POST, PATCH przy zmianie klienta,
  ponowne otwarcie zamkniętej — PATCH i `/publish`, runda 9), kontraktach,
  kontaktach, hiring managerze „nowa osoba”, regułach CV (zapis), przypisaniu
  DL-a (`/team-structure/dl-clients`), odczycie maila klienta, stawkach,
  konfliktach i generatorze CV „bez procesu”. Rejestr NIP poczty zamówień
  i writer pomijają `deleted_at`. `merge-into` z żywymi kontraktami/rekrutacjami/
  ID w env = 409 z listą; od rundy 9 scalenie PRZENOSI na cel kontakty, wiedzę,
  one-pagery, warunki umowy i kartę klienta (`_move_client_materials_on_merge`;
  warunki/karta po obu stronach = 409 `duplicate_singletons`), a duplikaty
  scalone wcześniej w źródło wskazują wprost na cel (bez łańcucha). Usunięcie
  klienta z historią zamyka jego puste opublikowane rekrutacje (bez `closed_at`).
- **DELETE rekrutacji:** zamknięta, z Traffita albo ze spotkaniem w kalendarzu =
  409 (`job_is_closed`, `job_from_traffit`, `job_has_calendar_events`) — dla
  każdej roli; całość w `audited_deletion`.
- **Auto-DL wymaga roli `delivery_lead`** (w `role` albo `roles`) i schodzi,
  gdy przestaje być głównym DL-em klienta (zdjęcie heada, usunięcie
  przypisania, zmiana klienta rekrutacji); DL wpisany ręcznie zostaje.
- **Automatyczny ruch karty (`pipeline_auto_move.auto_advance`)** nie przesuwa
  osoby z ostrzeżeniem (czarna lista, weto HM) — `Activity auto_advance_skipped`;
  po ruchu te same skutki co `/move` (przepięcia w transakcji, powiadomienia
  i ryzyko po commicie przez `run_after_commit`).
- **„Interview” w KPI i Insights = `client_interview`** (decyzja Artura) —
  `kpi_panel`, `kpi_team`, kafel Aktywność; liczniki etapów pulpitu idą regułą
  kolumn Tablicy (`board_column_for` po nazwie etapu).
- **Nagrobek usuniętego kandydata ma też wiersz `external_source='email'`**
  (HMAC znormalizowanego maila, bez migracji); import Traffita i Talent Radar
  pomijają go tylko, gdy nie ma żywego kandydata z tym mailem. Strażnik
  `NOT EXISTS` siedzi w samym `_UPSERT_CANDIDATE` (INSERT … SELECT).
- **Zgoda RODO:** wymóg zgody jest zamrażany na kopii etapu
  (`branded_render_metadata["consent_required"]`) — usunięcie wygenerowanego CV
  go nie zdejmuje. Druk i PDF przy wymogu zgody = zawsze 409 (wydruk nie niesie
  zrzutu). Przegląd DL i kolejka Cpro pobierają CV ETAPU (`lib/stage-cv-file.ts`),
  nie surowy DOCX generatora.
- **Dzierżawy zadań (`services/lease_renewal.renew_lease`)** ponawiają odnowienie
  po wyjątku do upływu dzierżawy; auto-CV podpina szkic w procesie, który
  wykonał zadanie (`cv_auto_generate.after_job_finished`).
- **Korpus składany (flaga OFF):** zakres cv/title/skills potwierdza pole
  `to_tsvector('simple', candidate_keyword_fold(...))`; w trakcie przeliczania
  wpis wersji ma `in_progress_version` bez `version`, a
  `app_settings['keyword_fold_fts_process']` kasuje pozycję po procesie z inną
  `FOLD_VERSION`.
- **M365:** 502/504 z wysyłki app-only = wynik niepewny (bez ponowienia);
  odroczeni odbiorcy raportu KPI czekają w `kpi_email_report_pending:*`;
  prywatne spotkanie z Outlooka traci `candidate_id`; publiczny POST
  potwierdzenia rozmowy usunięty.
- **Import rejestru z Excela:** arkusz „Bez działalności” stawia
  `needs_business_data_annex` także na umowie z NEXUSA (tylko to pole). Od rundy 8
  import zdejmuje flagę, którą SAM postawił, gdy arkusz mówi „zrobione” albo osoby
  już w nim nie ma (migawka w przebiegu — cofnięcie przebiegu przywraca flagę).

### Runda 8 (27.09.2026, po PR #1864)

Raport: `docs/audits/2026-09-25/runda-8.md`.

- **Dzień zakończenia umowy = `end_date` → `terminated_at` → dziś** (archiwum,
  LTV, analiza odejść, rok do roku Rady, kreator metryk, kampanie). Wypowiedzenie
  trwa tylko przy `end_date <= terminated_at`; samo przeżyte `terminated_at` po
  aneksie przedłużenia już nic nie znaczy.
- **Kontraktu usuniętego ALBO scalonego klienta nie da się wznowić** żadną drogą
  (`contract_lifecycle.assert_contract_client_not_deleted` w `reopen_contract`,
  PATCH, aneks, `/bulk-extend` → `skipped_client_deleted`, „Cofnij zakończenie”,
  „Powrót po przerwie”, `confirm-fully-signed`): 422 `client_deleted` /
  `client_merged`.
- **Zamówienia MD:** druga zaplanowana zamiana tej samej osoby = 409; nieudane
  nocne przeniesienie anuluje zastępstwo (`transfer_failed`); usunięcie osoby
  z zaplanowanym zastępstwem = 409; „Przywróć anulowane” nie wskrzesza linii
  z umową zakończoną/unieważnioną; linia natychmiastowego przejęcia ma puste pola
  MD do przeniesienia (bez chwilowego zamknięcia zamówienia).
- **Import MD, klient kosztowy:** numer z samych cyfr (≥ 7) w KSZTAŁCIE zamówień
  tego klienta (długość + 2 pierwsze cyfry) wiąże wiersz także, gdy takiego
  zamówienia nie ma — „Brak pasującego zamówienia”, nie zejście po nazwisku.
- **Liga Mistrzów: punkty za rozmowę liczy `client_interview`** (decyzja Artura
  27.09.2026, od razu także w bieżącym kwartale); etap QC CV (kod `interview`)
  punktów nie daje. `_rank_recruiters_by_points` jest jedyną funkcją liczącą Ligę
  (ekran, zamrożenie, wykluczenie lidera z wyścigów miesięcznych); klucz
  `league_points_interview` i migawka kwartału bez zmian.
- **„Interview” = `client_interview` także w KPI Rady** (`insights_board`
  `kpis.interview`, CSV „Rozmowy u klienta”), wykresie rocznym, lejku i tabeli
  zespołu; etap `interview` to QC CV.
- **Przydział requestów:** prowadzący wpisany przez automat wraca po powrocie
  requestu do puli jako wiersz `auto` (planer zwolni go za urlop) — chyba że
  automat go już zdjął (powód z `AUTO_RELEASE_REASONS`), wtedy prowadzącego wpisał
  człowiek i wraca jako `owner`. Tryb `off` zwalnia przypisania spoza puli, martwe
  konta i propozycje (powód `mode_off`). Prowadzący z nieaktywnym kontem = brak.
- **QC CV i Cpro:** plik „…B2B…” wybiera JEDNA reguła (`dz_review.pick_document_cv`:
  nazwa klienta → najnowszy) dla QC i kolejki Cpro; wymóg „do Cpro wysyła osoba od
  Cpro” działa także przy wyłączonym QC; zgoda RODO w QC = obraz na kopii etapu;
  ponowne „Biorę” nie przedłuża własnej blokady (409), blokada nieaktywnego konta
  nikogo nie wiąże.
- **Kalendarz:** usunięcie/przesunięcie blokady rozmowy u klienta w Outlooku nie
  kasuje ani nie przesuwa rozmowy z NEXUSA (kopia zostaje odpięta); przełożenie na
  przyszły termin zeruje `reminder_sent_at`; ocena prepu sprawdza tylko pytania,
  które pokazuje prep-kit, a popsuta odpowiedź modelu i transkrypt > 200 tys.
  znaków = `unavailable`, nigdy „słaby”.
- **Indeks:** ścieżki inline zawsze zostawiają intencję naprawy po nieudanym
  embedzie; status oferty w payloadzie Qdranta aktualizuje tani `set_payload` przy
  zmianie statusu (bez `embedding_id` jako bramki — punkt, którego nie ma, jest
  pomijany); reconciler wznawia kandydata z intencją `dead` bez `done` RAZ
  (dokładnie jedna `dead`), nie w każdym przebiegu.
- **Alerty zapisanych wyszukiwań:** każdy zapis we własnej sesji; sufit 1000 stron;
  dziennik pisany i czytany paczkami po 5000 (limit argumentów asyncpg to 32 767).
- **Jarvis:** czat i potwierdzenie oddają połączenie do puli przed turą; karta
  akcji pokazuje wszystko, co zapisze „Zrób to” (czas w Europe/Warsaw, czas bez
  strefy odrzucany); akcja nie wisi w `confirmed` (po 5 min „nie wiadomo”);
  blokady tur zdejmowane przy starcie procesu.
- **Logi i M365:** nazwy plików i ścieżki w logach tylko przez `safe_filename`;
  wyszukiwanie e-maila (CV, podpis Outlooka) w czasie liniowym; stary prywatny
  wpis z Outlooka traci `candidate_id` (faza `repair-m365-private-event-candidate`);
  „odwołane” follow-upu zapisuje się dopiero po udanym odwołaniu w Teams.
- **Sekcja wyłączona przełącznikiem `show` znika z danych publicznych**
  (decyzja Artura 27.09.2026): `public_job_payload` (domyślnie `respect_show=True`)
  zwraca puste must/nice i zerowe parametry (poza stałym `contract`) — tak dostają
  je `/r/<slug>`, grafika OG, meta, lista `/p/<slug>` (`visible_params`), podgląd
  w edytorze i portale. Pełną projekcję (`respect_show=False`) czytają wyłącznie
  kontrola treści i migawka zatwierdzenia. Portal przy ukrytych wymaganiach = 422
  `listing_invalid`.
- **Strona kariery i portale:** kontrola publikacji sprawdza także sekcje
  wyłączone przełącznikiem; slug linku rekrutacji bez nazwy klienta i nazwisk
  (nieczysty dostaje nowy adres przy zatwierdzeniu); zmiana klienta po
  zatwierdzeniu = szkic; wycofanie w trakcie dzierżawy nie zeruje
  `next_attempt_at`; dwa równoległe „Publikuj” = 409.
- **Migracje 0381/0383/0388:** downgrade przy istniejących danych kończy się
  wyjątkiem zamiast je kasować.
- **Rozmowa u klienta ma dwie rundy naraz** (decyzja Artura 27.09.2026):
  zaległy debrief rundy odbytej (`pick_current_round`) i prepy do następnej
  (`pick_prep_round`, `PairSnapshot.for_preps()`) przypominają się równolegle.
  „Runda zamknięta” liczy JEDNA funkcja `debrief_gate.debrief_closes_round`
  (bramka, ekran, plakietka, kolejka prepów i przypomnienia 45 min / 2 h po
  rozmowie) — sam feedback bez pytań klienta rundy nie zamyka.

### Runda 9 (27.09.2026, po PR #1870)

Raport: `docs/audits/2026-09-25/runda-9.md`.

- **`get_db` commituje PRZED wysłaniem odpowiedzi** (sesja na stosie
  „function” FastAPI, nie „request”). Od FastAPI 0.141 zależność z `yield`
  kończyła się po odpowiedzi i po `BackgroundTasks`: 2xx mimo nieudanego
  commitu, połączenie „idle in transaction” przez zadanie w tle. Generator
  `StreamingResponse` i zadanie w tle otwierają WŁASNĄ sesję — sesja żądania
  jest już zamknięta. Flagę niezatwierdzonych zapisów czyści wyłącznie koniec
  transakcji najwyższego poziomu (wycofanie SAVEPOINT-u jej nie kasuje).
- **Nocne ścieżki nie rzucają nowych odmów** — wznowienie kontraktu ze skanu
  idzie przez `sync_contract_to_live_order_nightly` (savepoint, pominięcie
  przy 422), auto-aktywacja szkicu i podpis B2B pomijają kontrakt klienta
  usuniętego/scalonego (`contract_client_is_gone`).
- **Scalony klient nie przyjmuje zapisów zamówień** (`_assert_client(...,
  for_write=True)` → 422 `client_merged`); odczyty i sprzątanie (zakończenie,
  usunięcie, anulowanie) zostają.
- **Scalanie kandydatów nigdy nie kasuje CV** — konflikt dwóch głównych CV
  albo tej samej treści zdejmuje `is_primary`/odcisk, wiersz zostaje. Pola
  blokujące (czarna lista, „tylko etat”, zgody) rozstrzyga reguła „bardziej
  restrykcyjne wygrywa”.
- **Usunięcie kandydata przenosi CV z bazy (BYTEA) do magazynu** i zapisuje
  klucze w `retained_candidate_files` (0390, pseudonim zamiast id); magazyn
  niedostępny przy CV w bazie = 409, nic się nie zmienia.
- **Liga DL, cel DL, raport DL i Insights DL (decyzja Artura 27.09.2026):** DL
  rekrutacji to AKTYWNE konto z rolą Delivery Leada; inaczej rekrutacja idzie
  do głównego DL-a klienta (`job_delivery_lead_fill._HEADS`,
  `reports._resolve_dl_id`, `insights_dl_scope.DL_HEAD_CTE`).
- **Autofreeze nadrabia pominięte okresy** (3 miesiące, 2 kwartały wstecz) —
  ale tylko kończące się ≥ `CATCH_UP_FROM` (30.09.2026, decyzja Artura).
  Liga DL Q1 2026 i wyścig rekomendacji 07.2026 zostają dla admina.
- **SSO z AAD RBAC nie reaktywuje konta, które admin jawnie wyłączył**
  (`services/admin_active_decision.py`). E-mail użytkownika porównywany
  i zapisywany małymi literami (`services/user_email.py`). Stan SSO niesie
  `browser_nonce` (sessionStorage karty) — kod wymiany z cudzej przeglądarki
  daje 410.
- **Off-limits klienta usunięte w całości** (decyzja Artura 27.09.2026) —
  karta, przegląd, warunki umowy i API ich nie niosą; kolumny zostają.
- **Mail odrzucenia wychodzi ze skrzynki osoby, która odrzuca** (bez
  połączenia M365 = `rejection_email_status: no_mailbox`, nic nie wychodzi).
  Dostępność maila liczy jedna reguła po obu stronach
  (`previous_is_client_visible` ↔ `lib/rejection-email.ts`).
- **`/move` i `/bulk-move` dla osoby spoza rekrutacji** przyjmują wyłącznie
  kolumny „Nowi”/„Screening” (422 w innych) z twardą bramką czarnej listy
  i weta. Weto HM, przepięcia i „Klient milczy” liczą się z KOLUMNY docelowej.
- **Odczyt PDF (CV, formularz kariery, poczta zamówień) w osobnym procesie**
  z limitem pamięci 1,5 GB i czasu 150 s (`cv_text_extractor`).
- **Pytania z archiwum rozmów (bez autora) edytuje tylko admin albo HoR**;
  pytań `legacy_import`/`client_debrief` nie da się przenieść do innego klienta.
- **Admin/DL czytają cudzy mail wyłącznie powiązany z kandydatem**
  (`_can_access_email`).

### Runda 10 (27.09.2026, po PR #1871)

Raport: `docs/audits/2026-09-25/runda-10.md`; testy manualne UI Codexa (F01–F27) i lekcje:
`docs/audits/2026-09-25/manual-ui-codex-2026-09-26.md`.

- **Automat ruchu karty nie przeskakuje bramki CV** (F09): terminy od klienta
  przesuwają kartę na „Rozmowę u klienta” tylko z kolumny „CV wysłane” albo
  dalszej; inaczej `auto_advance_skipped` z `cv_not_sent` i komunikat dla DL.
  Nowa bramka = sprawdź WSZYSTKIE ścieżki zmiany etapu (ręczny, zbiorczy,
  automat, import).
- **Koniec współpracy przed startem kontraktu = 422** `end_date_before_start_date`
  (`/terminate`, `bulk-mark-ended`, podpis dokumentu rozwiązania, PATCH i POST
  dat). **Przedłużenie zamówienia okresowego nie nakłada się** na inne
  zamówienie tego kontraktu (409 `overlapping_order`). Bieżące + przyszłe
  nienakładające się zamówienie przy „Zatrudniony” to kontynuacja, nie duplikat.
- **Faktury:** kwota NUMERIC(14,2) z groszami (0394), numer obowiązkowy,
  kwota > 0 (F01/F13).
- **Braki w Finansach:** jedno zamówienie może mieć kilka braków (po jednym na
  datę końca, 0392 `ux_order_gaps_order_ended`), `episode` w kluczu odhaczenia;
  z Braków ukrywany jest tylko brak OTWARTY z intencją zakończenia —
  „uzupełnione z opóźnieniem” zostaje w historii miesiąca.
- **Import MD:** wiersz bez numeru nie trafia na aktywną linię innego klienta
  ani imiennika (`prefer_active_line` tylko ta sama osoba i klient); nieczytelna
  faktura nie wyrzuca MD (`invoice_unreadable`), numer wyczerpanego zamówienia
  kosztowego = `order_exhausted` (0393).
- **Aneks stawki potwierdza admin, Finanse i DL portfela** (decyzja Artura,
  `effects.can_confirm_rate_annex`). Porozumienie o rozwiązaniu kończy projekt
  ostatnim dniem usług, umowę — datą rozwiązania.
- **Import Traffita nie nadpisuje poprawek z NEXUSA**: znaczniki ręczne w
  `_nexus_identity` (email/phone/linkedin/profile_about/status), kontakty
  (decydent, nazwa, klient tylko dopełniane) i pule z nagrobkami, notatki
  usunięte w NEXUSIE (`deleted_note_sources`, 0395). Niezmieniony rekord
  (`traffit_payload_sha`) nie jest przepisywany — delta plików/CV bierze też
  kandydatów z oknem źródła (`traffit_source_updated_at`), żeby ponowienie po
  błędzie działało.
- **Słowa kluczowe i porównanie czytają `verified_tech`** (F17/F18) —
  dołożenie kolumny do korpusu = podbicie `CORPUS_SOURCES_VERSION` i zapytanie
  przeliczające w `keyword_corpus.py` (bez zmiany `FOLD_VERSION`).
- **Szablony maili autora mają limit wyniku przed operacją** (`+ ~ % join
  replace` itd.) i przerwanie przy przyroście pamięci procesu.
- **Alembic przy starcie ma `lock_timeout` 10 s i `statement_timeout` 20 min**
  (`startup_locks.apply_migration_session_limits`). Daty i szkic umowy ramowej
  z manifestu portfela (`client_excel`) są nieedytowalne (409), bo psuły
  `/api/health/deep`.
- **Eksport XLSX:** `safe_cell` usuwa znaki niedozwolone w XLSX przed
  sprawdzeniem prefiksu formuły.
- **Metryki pulpitu per osoba liczą z jednej migawki firmy** (60 s, single-flight)
  — nie woła się `VERIFIER_ANCHORED_CTE` per kafel.
- Stawka kandydata w propozycjach jawna dla wszystkich; stawka do klienta
  bez zmian (tylko admin/DL zapisują, rekruter nie widzi).

### Runda 11 (27.09.2026, po PR #1874)

Raport: `docs/audits/2026-09-25/runda-11.md` (domknięcie pozycji z rundy 10).

- **`/bulk-move` i `/move` otwierają świeżą parę tą samą funkcją**
  (`_fresh_pair_entry_kwargs`: `entry_source` + blokada 12 h, integracja =
  `auto_match` bez blokady). Nowa ścieżka zakładająca proces = ta funkcja.
- **Korpus słów kluczowych ma trzecie źródło: `screening_notes.verified_skills`**
  (tylko `confirmed`, sama nazwa), przeliczane triggerem na `screening_notes`
  (migracja 0396). Nie zapisuj screeningu do `verified_tech` — to pole czyta
  scoring. Zmiana źródeł = podbicie `CORPUS_SOURCES_VERSION` (dziś 3).
- **OAuth łączenia skrzynki M365: `state` niesie tylko nonce**, verifier PKCE
  = HMAC klucza podpisu, nonce zużywany raz (`consume_state`,
  `app_settings['m365_oauth_consumed_states']`). Nie wkładaj sekretów do `state`.
- **Każdy render Jinja z treścią od użytkownika przez `_render_bounded`**
  (`user_email_templates`): szablony maili, szablony umów, szkic kontraktu,
  podgląd generatora B2B. Surowy `SandboxedEnvironment().render()` = OOM.
- **Potwierdzenia we froncie przez `useConfirmV2()`** (`components/v2/modals/ConfirmV2.tsx`)
  albo istniejące przyciski potwierdzane w wierszu — natywne `confirm()`
  odrzuca strażnik `src/__tests__/native-confirm-guard.test.ts`.
- **CV firmowe etapu jest per wiersz etapu**; GET dla etapu bez własnego CV
  niesie `pair_source_stage_id`/`pair_source_status` — ekrany czytają CV pary
  stamtąd. Plików CV nie kopiujemy ani nie przenosimy.

### Runda 12 (28.09.2026, po PR #1877)

Raport: `docs/audits/2026-09-25/runda-12.md`.

- **Zmiana hasła nie wylogowuje bieżącej sesji:** `POST /api/auth/change-password`
  zwraca 200 z nową parą tokenów (bez `fpc`), a unieważnia wszystkie
  wcześniejsze (podłoga `tokens_valid_after` z zegara aplikacji). Front
  zapisuje nowy token (`lib/password-change-session.ts`).
  Token klienta OAuth dostaje 403 — trasa wydająca tokeny użytkownika nie
  może przyjmować tokenu integracji.
- **Status requestu „champion” tylko przy „Szukamy”** — `request_status_expr`
  = `request_stage_expr` = `visible_state`. „Mamy championa” kliknięte na
  innym stanie zapisuje się, ale widać je po przestawieniu na „Szukamy”
  (decyzja Artura 28.09.2026).
- **CV firmowe pary czytają wszystkie ekrany przez `useStageBrandedCv`**
  (`pairSourceStageId`): karta „CV do klienta”, warsztat wysyłki (link klienta
  i odwołanie linków idą na wiersz pary), zakładka „Rekrutacje” profilu.
- **Umiejętności ze screeningu (`confirmed`) liczą się w zakresie „Umiejętności”,
  filtrze umiejętności v2 i wycinkach** — jedno źródło
  `keyword_corpus._screening_skills_from`. v1 wyszukiwania bez zmian.
- **Natywne `alert()` i `confirm()` odrzuca strażnik**
  `src/__tests__/native-confirm-guard.test.ts` — komunikaty przez `useToast`,
  potwierdzenia przez `useConfirmV2()`.
- **Responsywność:** przewijany kontener tabeli z `sr-only` w nagłówku musi mieć
  `relative`; pole `flex-1` w wierszu dostaje `w-0` (minimum z `size=20`
  zależy od fontu systemu). Nocny `preview-chromium` biegnie w jobie `stack`
  tylko z harmonogramu — w kolejce merge'ów jest pomijany.

### Runda 13 (28.09.2026, po PR #1884)

Raport: `docs/audits/2026-09-25/runda-13.md`.

- **Tokeny mają `iat` z mikrosekundami** (`security._issued_at`), a
  `token_is_revoked` porównuje je dokładnie; tokeny z całkowitym `iat` (sprzed
  28.09.2026) — po pełnych sekundach. Każde ustawienie `tokens_valid_after`
  bierze czas z zegara aplikacji (`datetime.now(timezone.utc)`), nigdy
  `func.now()` — to początek transakcji, więc token wybity równolegle przeżyłby
  unieważnienie. Nowa ścieżka wydająca token = `create_access_token`/`create_refresh_token`.
  Całkowite `iat` wybite po 28.09.2026 14:30 UTC (`_LEGACY_INT_IAT_UNTIL`) przy
  ustawionej podłodze = unieważnione; testy wybijają `iat` z ułamkiem (runda 14).
- **Zapisane wyszukiwanie z filtrem umiejętności** dostaje przy migracji v1 → v2
  kod `screening_skills` (`saved_search_payload.RULE_SCREENING_SKILLS`).
- **Powiadomienia: `showError` tylko dla błędów**, informacja — `showInfo`
  (`components/Toast.tsx`, rola `status`).
- **Pole `flex-1` w wierszu ma jawną szerokość (`w-0`), przewijany kontener
  z `absolute`/`sr-only` w środku ma `relative`** — pilnują strażniki
  w `responsive-guards.test.ts`.
