# Audyt NEXUS 25.09.2026 — runda 2

> **Baza:** `8d9755da2` · **Status:** naprawione w PR #1836 (merge 9d85252d8, na produkcji 25.09.2026).
> Oryginalny raport (prywatny artefakt): https://claude.ai/artifact/Hcs6cYoiaJ187RmuFMZspY
> Reguły wynikające z naprawy: `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie”.

NEXUS · commit 8d9755da (po PR #1833) · 25.09.2026

# Audyt, runda 2: co zostało po naprawie

7 agentów przejrzało kod po wdrożeniu PR #1833. Sprawdzały dwie rzeczy: czy poprawki są poprawne i kompletne, oraz czy są nowe błędy poza zakresem pierwszej rundy. Wszystko to tylko odczyt, nic nie zostało zmienione. Każde znalezisko poniżej sprawdziłem sam w kodzie. Poprzedni raport: [runda 1](https://claude.ai/artifact/BtnT7zb5kwPk5gNLvg56x6).   **1** krytyczne: regresja z #1833 zatrzymuje skrzynkę zamówień **5** wysokie **10** średnie **3** niskie

## W skrócie

Większość z ~45 poprawek działa. Bezpieczeństwo jest czyste, migracje zgodne, a frontend przechodzi testy (61/61) i type-check. Problemy mają dwa źródła. Pierwsze: poprawki działają tylko w części ścieżek, bo ta sama reguła żyje w bliźniaczym miejscu, którego poprawka nie objęła. Tak jest z pickerami, `/bulk-move`, domyślnym rekruterem, trzema fazami Traffita i dwoma endpointami z `create_task`. Drugie: poprawki dotknęły nowego stanu, którego wcześniej nie było, i wywołały regresję. Tak jest z drugim wpisem „Nieudane” tej samej wiadomości i z „Aktywnym” z minioną datą. 15 z 19 pozycji dotyczy kodu z #1833, 4 są nowe.

## Czeka na decyzję (stan w chwili raportu)

- **Czy naprawiam?** Proponuję jeden PR z wszystkimi 19 pozycjami. Każda dostanie test, który najpierw pada, a potem przechodzi. Najpilniejsza jest pozycja krytyczna: dziś wystarczy jeden mail z dwoma pustymi załącznikami, żeby skrzynka zamówień stanęła na stałe.
- **Praktykant i „tylko umowa o pracę”.** Proponuję odmowę (409) przy przekazaniu takiej osoby rekruterowi i schowanie przycisku. Mówię o tym osobno, bo to zmienia działanie ekranu praktykanta.

## Krytyczne

### Mail z dwoma pustymi załącznikami zatrzymuje skrzynkę zamówień na stałe `[Poczta zamówień]` `[poprawka #1833]` `[potwierdzone]`

`order_mail_ingest.py` `_hold_or_record_failed` · indeks `uq_order_mail_documents_message_no_attachment` (`models/order_mail.py:94`)

Indeks UNIQUE pozwala na jeden wpis bez `attachment_sha256` na wiadomość. Nowa ścieżka zapisuje wpis „Nieudane” bez sha **dla każdego załącznika**, a `_message_logged` sprawdza wiadomość razem z nazwą pliku. Mail starszy niż doba z dwoma PDF-ami bez `contentBytes` daje przy drugim załączniku `IntegrityError`. Nic go nie łapie, więc bieg kończy się błędem, a znacznik stoi. Każdy następny bieg pada tak samo i żaden późniejszy mail nie jest już czytany. Przed #1833 takiego wpisu nie było.

## Wysokie

### „Cofnij zakończenie” może dać „Aktywny” z minioną datą, a nocny cron kończy umowę ponownie `[Kontrakty]` `[poprawka #1833]` `[potwierdzone]`

`contract_termination_reversal.py:~660` (cel `ending` z minioną datą → `active`) · `:495` (`fallback = end_date` dla umów zlecenie i UoP)

Umowa „Kończący się” z datą 31.08, zakończona przez cron 1.09. Cofnięcie daje 200 i status „Aktywny” z datą 31.08. Następnej nocy `_promote_statuses` kończy ją ponownie: zamyka przywrócone zamówienia, zakłada sprawy offboardingu MD, wysyła alerty DL i przestawia Generator. Ten sam efekt ma ścieżka bez migawki dla umowy zlecenie zakończonej przed 0368 (`end_date == terminated_on`). Test przepuszcza ten przypadek, bo nie sprawdza statusu po cronie.

### PATCH samej notatki na zakończonej umowie uruchamia pełną reaktywację `[Kontrakty]` `[poprawka #1833]` `[potwierdzone]`

`contracts.py:~3962` (gałąź `reopen_contract` w `update_contract`)

Warunek nie sprawdza, czy żądanie zmieniało `end_date`. Na umowie `ended` z pustą albo przyszłą datą każdy PATCH bez statusu, np. `{"notes": "x"}`, woła `undo_contract_termination`. To czyści podpisane rozwiązanie, przywraca wiersz Generatora i zamyka migawkę. Przy pustej dacie nie łapie tego też nowa gałąź dla umów z rozwiązaniem.

### Ponownie przysłany PDF bywa oznaczony jako duplikat duplikatu i nie zostaje przeczytany `[Poczta zamówień]` `[poprawka #1833]` `[potwierdzone]`

`order_mail_ingest.py:628` `_first_with_sha` · `order_mail_recheck._retry_failed_one`

Filtr wyklucza tylko `failed`. Wiersz `duplicate_attachment` też ma sha, więc może zostać „oryginałem”. Dane sprzed PR: F (`failed`) i D (duplikat F). Ponowienie bierze F, widzi D jako oryginał i zamienia F w duplikat D. Powstaje cykl F↔D, a PDF nie jest czytany nigdy. Wpis znika przy tym z „Nieudanych”. To dokładnie przypadek, który poprawka opisuje w docstringu.

### Traffit: po zerwaniu połączenia z bazą przepada cała reszta fazy `[Integracje]` `[poprawka #1833]` `[potwierdzone]`

`traffit/importer.py` CV (`~3285`), pliki (`~3885`), aktywności (`~4673`)

Savepointy wierszy zastąpiły `rollback()`, ale w trzech fazach nie ma `needs_session_rollback(e, past_savepoint=False)`. Bliźniacze fazy go mają (`:1567, 1644, 1818, 2810, 2893, 4941`). Po restarcie Postgresa w trakcie nocnego syncu każde kolejne `begin_nested()` rzuca `PendingRollbackError`. Każdy następny wiersz staje się błędem przypisanym, nic się nie commituje, a na końcu faza się wywraca. Kwarantanna dostaje przy tym fałszywe liczniki.

### Praktykant może przekazać rekruterowi osobę „tylko umowa o pracę” `[Praktykant]` `[nowy]` `[potwierdzone]`

`trainee_program.py:734` `_ensure_handover_allowed` · `TraineeCallCard.tsx:215`

Sprawdzane są tylko `outcome == "call"` i data, a `b2b_willingness` już nie. Karta z wynikiem „Rozmowa” pokazuje przycisk „Przekaż rekruterowi” także dla `employment_only`. Powstaje propozycja `source="trainee"` dla osoby, którą każda inna powierzchnia dopasowań ukrywa.

## Średnie

### Trzy pickery na liście kandydatów i picker klientów w Kontraktach nadal pokazują „Brak …” przy błędzie `[Frontend]` `[poprawka #1833]` `[potwierdzone]`

`RecruitmentMultiSelect.tsx:37`, `AddedByMultiSelect.tsx:45`, `TalentPoolMultiSelect.tsx:34`, `ContractsClientPicker.tsx:81`

#1833 dodał `PickerQueryState` tylko w trzech z sześciu pickerów w `v2/filters`. Pozostałe trzy są na głównym ekranie `/candidates`. `ContractsClientPicker` opiera się na `isLoading`, który w react-query v5 po błędzie ma wartość `false`, więc awaria wygląda jak „Brak wyników”.

### Kandydat, którego nie ma na tablicy, omija QC CV i osobę od Cpro (`/move`, `/bulk-move`) `[Rekrutacja]` `[poprawka #1833]` `[potwierdzone]`

`pipeline_move_rules.py:85` (`(None, None)`) · `pipeline.py:581` (`if current is None: return`)

Docstring obiecuje „start od Nowych”, ale para bez wierszy wychodzi z bramki od razu. Żądanie API przesuwające świeżego kandydata wprost na „CV wysłane” albo Cpro u Nordei dostaje 200 bez QC. Z interfejsu tej drogi nie widać, luka jest w API.

### `/bulk-move` nadal robi `db.rollback()` po commicie `[Rekrutacja]` `[poprawka #1833]` `[potwierdzone]`

`pipeline.py:3336-3378`

`_post_commit_effect` objął tylko pojedynczy `/move`. W paczce błąd przeliczenia ryzyka wygasza `current_user`, więc dodawanie reszty osób do pul pada po cichu (`MissingGreenlet` łapany w `except`). Błąd dodania jednej osoby cofa też wcześniej dodane.

### Domyślny rekruter wniosku o terminy może być nieaktywnym kontem `[Kalendarz]` `[poprawka #1833]` `[potwierdzone]`

`interview_cycle.py:567` · `interview_slots.py:94-124`

Walidacja działa tylko dla jawnego `recruiter_id`. Wartość domyślna (właściciel procesu → pierwszy weryfikator → `job.recruiter_id`) nie sprawdza `is_active`. Konta z Traffita bywają nieaktywne, a wtedy przypomnienie „Telefon ≤30 min” idzie do nikogo.

### Samodzielne zamówienie z budżetem MD po #1833 „kończy się datą”, ale nic go nie domyka `[Zamówienia]` `[poprawka #1833]` `[potwierdzone]`

`order_facts.py:103`, `order_gaps.py:164` · `dl_portal_expiry_scanner.py:233` (`periodic_due` wymaga `md_total IS NULL`)

Dotyczy starych zamówień bez typu z `md_total`. Finanse widzą takie zamówienie w Brakach i Zejściach, a jego status zostaje `active` na zawsze. Nocna synchronizacja kosztu dalej nadpisuje mu stawkę.

### Zakładka „Nieudane” obiecuje ponowienia, które nie nastąpią, i nie pozwala niczego zamknąć `[Poczta zamówień]` `[poprawka #1833]` `[potwierdzone]`

`OrderMailQueue.tsx` `failedRetryNote` · `order_mail_queue.py:344` `_DISMISSABLE_OUTCOMES`

Notka „System ponawia je sam” pojawia się też przy wpisach bez pliku (każdy z `_hold_or_record_failed`) i starszych niż 7 dni, a tych ponowienie nie bierze. Obsłużonego ręcznie wpisu nie da się odrzucić, więc wisi w zakładce bez końca.

### Zakładka „Nieudane” pokazuje DL i Finansom surowe `repr(exc)` `[Poczta zamówień]` `[poprawka #1833]` `[potwierdzone]`

`order_mail_ingest.py:1572` · `order_mail_queue.py:327` (redakcja tylko dla TCM)

Treść błędu niesie ścieżki z dysku i SQL (`IntegrityError … [SQL: INSERT …]`). Do 25.09 żadna zakładka tego nie pokazywała, a CLAUDE.md wymaga „klasy wyjątku, nie repr”.

### Odwrócony zakres stawki albo stażu: lista odpowiada 200, wyszukiwarka 422 `[Wyszukiwanie]` `[nowy]` `[potwierdzone]`

`candidates.py:282` (`CandidateFilterSpec` bez walidatora) · por. `schemas/candidate_search.py:159`

`min_rate=200&max_rate=100` na liście zwraca tylko osoby bez stawki. To przypadek UAT B28, naprawiony wyłącznie w wyszukiwarce. Dotyczy też eksportu „z filtra” i alertów zapisanych wyszukiwań. Łamie regułę „v2 w obu silnikach daje to samo”.

### Wyszukiwarka w trybie `literal` z jednoznakowym `q` zwraca całą bazę `[Wyszukiwanie]` `[nowy]` `[od agenta]`

`search.py:671` · `candidate_search_predicates.py:790`

`literal_text_clause` zwraca `None` dla frazy krótszej niż 2 znaki, a handler nie dodaje wtedy żadnego warunku. Lista ma `min_length=2`, wyszukiwarka nie.

### Portale: szybkie wycofanie nowej publikacji zostawia opłacone ogłoszenie bez zamknięcia `[Integracje]` `[poprawka #1833]` `[od agenta]`

`job_portals/service.py:259, 332, 381`

`_cancel_stale_cleanup` kasuje zaległe zamknięcie starej próby w nadziei, że nowa publikacja przejmie ogłoszenie. Wycofanie nowej, zanim ruszy worker, daje `removed` bez zamknięcia. Flagi portali są dziś wyłączone.

## Niskie

**3 pozycje**

- **Dwa endpointy wciąż wołają goły `create_task`:** `admin_talent_pools.py:60` i `admin_notes_insights.py:46`. Test `spawn` sprawdza tylko 5 wymienionych modułów, zamiast przeszukać całe `app/api`.
- **`gate_stage_row` robi osobne zapytanie na każdy zamknięty wiersz historii pary** (`pipeline_move_rules.py:59`). W `/bulk-move` to mnoży się razy 100. Ten sam PR w `candidate_followups` rozwiązał to wcześniej załadowanym katalogiem.
- **Nabór Akademii liczy `since` od północy UTC** (`academy.py:111`), więc zgłoszenie z 00:30 czasu polskiego pierwszego dnia nie wpada.

Poniżej progu: `cv_parsed_after` w UTC (brak kontrolki w UI), poniedziałek w UTC w `request_allocation_notices.py:178`, `{"min_fits": Infinity}` daje 500 (tylko admin/HoR). Rejestracja nadal zdradza istnienie konta czasem odpowiedzi (`SELF_REGISTRATION_ENABLED` wyłączone).

## Sprawdzone i czyste

- **Bezpieczeństwo:** brak blokujących. `safe_cell` nie da się obejść wyjątkiem dla liczb. Otwieranie dokumentów w przeglądarce, logi Slacka i `hide_parameters` działają. Nowe powierzchnie (praktykant, Akademia, OAuth portali, Jarvis) mają poprawne bramki. W repo nie ma sekretów.
- **Baza:** jedna głowa `0384`, lustra w `entrypoint.sh` zgodne, indeks częściowy `cv_sent` pasuje do zapytania, modele i migracje 0370–0384 bez rozjazdów.
- **Pieniądze:** `_assert_job_of_client`, `_missing_activation_fields`, `current_contract_clause` (SQL = Python), `margin_revenue` z redakcją, `old_currency`, blokady grup MD i przejęć.

- **Poczta:** `titles_collide` dla BIK, PFRON, SAP i CP; znacznik z limitem 24 h, poza wymienionym wyjątkiem; sonda; zakres widoczności kolejki dla DL i TCM.
- **Rekrutacja:** `_post_commit_effect` w `/move`, bramki przy powrocie z „Zamkniętych”, osoba zapasowa Cpro, debrief przez DL, 409 w „Porządku w requestach”, daty 1900–2100, warianty `.js`/`.net`.
- **Integracje:** `DELIVERY_UNCERTAIN`, `to_thread` bez sesji w wątku, `carried_errors`, backoff outboxu, `TurnClaim` w Jarvisie.

**Niepotwierdzone:** nie uruchamiałem testów z bazą, bo lokalnie nie ma Postgresa i Dockera. Wszystkie znaleziska pochodzą z czytania kodu. Zachowania parsera tsvector dla `.js` nie sprawdziłem na żywej bazie, pilnuje go test w CI.


---

## Notatki weryfikacyjne koordynatora

Surowe notatki z weryfikacji (plik:linia sprawdzone w kodzie). „POTWIERDZONE” = sprawdzone przez koordynatora, bez oznaczenia = zgłoszone przez agenta.

### Audyt runda 2 — potwierdzone
#### Frontend
- R2-F1 POTWIERDZONE [POPRAWKA niekompletna]: RecruitmentMultiSelect:37/78, AddedByMultiSelect:45/107, TalentPoolMultiSelect:34/90 — useQuery bez isPending/isError, CommandEmpty "Brak …" przy błędzie; ekran /candidates. ContractsClientPicker:81 isLoading (v5) → błąd jako "Brak wyników" (/contracts).
- tsc: 0 błędów w kodzie PR (13 środowiskowych); vitest 61/61.
#### Pieniądze
- R2-M1 POTWIERDZONE [POPRAWKA]: contract_termination_reversal.py:660 cel active przy end_date<dziś (migawka ending z minioną datą) i :495 fallback=end_date dla UZ/UoP bez aneksu → "Aktywny" z minioną datą; cron _promote_statuses kończy ponownie (offboarding, alerty, Generator).
- R2-M3 POTWIERDZONE [NOWY z #1833]: contracts.py ~3962 reopen odpala przy każdym PATCH bez statusu na ended z pustą/przyszłą datą (nie sprawdza "end_date" in fields_set) → np. PATCH notatki czyści rozwiązanie.
- R2-M2 POTWIERDZONE [POPRAWKA]: dl_portal_expiry_scanner.py:233 periodic_due wymaga md_total IS NULL → samodzielne zamówienie z md_total nigdy nie domykane datą, a order_facts/order_gaps (po #1833) traktują je jako kończące się datą → Braki/Zejścia przy statusie active na zawsze; cost sync nadpisuje stawkę.
#### Poczta
- R2-P1 POTWIERDZONE [POPRAWKA/regres]: uq_order_mail_documents_message_no_attachment (internet_message_id WHERE sha IS NULL) + _hold_or_record_failed zapisuje drugi failed bez sha dla tej samej wiadomości (2 załączniki bez contentBytes) → IntegrityError bez try → bieg error, znacznik stoi na zawsze.
- R2-P2 POTWIERDZONE [POPRAWKA]: _first_with_sha (ingest.py:635) wyklucza tylko failed; duplicate może być "oryginałem" → cykl F↔D, PDF nigdy nie czytany.
- R2-P3 POTWIERDZONE [POPRAWKA]: _DISMISSABLE_OUTCOMES (queue.py:344) bez failed; notka "system ponawia" także dla wpisów bez pliku/starszych niż 7 dni.
- R2-P4 średnia: repr(exc) w error widoczny dla DL/Finansów w zakładce Nieudane (redakcja tylko TCM).
#### Integracje
- R2-I1 POTWIERDZONE [POPRAWKA]: traffit importer CV (~3285), pliki (~3885), aktywności (~4673) — except bez needs_session_rollback (bliźniacze fazy mają: 1567,1644,1818,2810,2893,4941) → po zerwaniu połączenia każdy kolejny wiersz = błąd, reszta fazy przepada.
- R2-I2 średnio-wysoka [POPRAWKA]: job_portals _cancel_stale_cleanup + szybkie wycofanie nowej publikacji → brak close dla ogłoszenia z próby A (flagi portali OFF).
- R2-I3 POTWIERDZONE: admin_talent_pools.py:60, admin_notes_insights.py:46 goły create_task; test spawn sprawdza tylko 5 modułów.
#### Baza
- R2-D1 POTWIERDZONE (wydajność, niska-średnia): pipeline_move_rules.gate_stage_row:59 ładuje wszystkie wiersze pary i woła stage_column (SELECT) per wiersz "closed"; zwykle 2 zapytania, więcej tylko przy historii zamknięć; w bulk-move ×100.
- Migracje: jedna głowa 0384, lustra OK, indeks częściowy pasuje.
#### Bezpieczeństwo: brak blokujących; poprawki kompletne.
