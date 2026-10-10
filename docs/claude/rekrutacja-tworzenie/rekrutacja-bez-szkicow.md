# Rekrutacja bez szkiców (0415–0416, 04.10.2026)

Pomiar 04.10.2026 (40 rekrutacji z NEXUSA od 25.09): 14 szkiców nikt nie
przekazał, 5 opublikowano bez przekazania (zmiana statusu w oknie edycji
i `/publish` nie sprawdzały bramki), termin miało 6/40, hiring managera 10/40.
Decyzje Artura 04.10.2026 (makiety https://claude.ai/artifact/9T6tEhBfsnyE1RsuaAxABy):
rekrutacja NIGDY nie jest szkicem — system wymusza komplet; linku
udostępniania dla klienta nie robimy. Raport: `docs/job-no-drafts-completion-report.md`.

- **Rekrutacja ma dwa stany: w pracy (opublikowana i przekazana) albo
  zamknięta.** `POST /api/jobs` jest jedyną drogą tworzenia i robi w JEDNEJ
  transakcji: `allocation_lock` → rdzeń tworzenia → decyzja o hiring
  managerze → Champion → bramka (`job_handoff_blocker_items` +
  `enforce_operation`) → przekazanie → podobne rekrutacje → publikacja →
  commit → efekty po commicie. Brak = 422 `{code:"job_not_ready",
  blockers:[{code,message}]}` i rollback (`get_db`). `JobCreate` nie ma
  `status`. Rdzenie bez `commit` żyją w `services/job_lifecycle.py`
  (`create_job_core`, `save_champion_core`, `handoff_core`, `publish_core`,
  `apply_hiring_manager_decision`, `close_job_core`, `run_post_commit`);
  stare trasy wołają je i robią commit same. Nie dokładaj `db.commit()` do
  rdzenia — zepsuje atomowość tworzenia. Efekty z własną sesją (migawka
  rankingu, outbox, `refresh_job_matching`) idą WYŁĄCZNIE po commicie.
- **Nowe wymagania bramki** (tylko `job_handoff_blockers`, nie bramka briefu
  automatu przydziału): hiring manager albo `jobs.hiring_manager_not_provided`,
  termin albo `jobs.deadline_not_provided` („Klient nie podał” — decyzja, nie
  zgadywanie), kategoria, liczba osób ≥ 1. Ustawienie kontaktu HM albo daty
  zeruje flagę. Kody braków: `job_readiness.BLOCKER_CODES` (lustro
  `lib/__fixtures__/job-readiness-blockers.json`), problemy Championa jako
  `champion:<kod>`.
- **`POST /{id}/publish` = „Otwórz ponownie” / „Dokończ i opublikuj”**
  (zamknięta, stary szkic, opublikowana bez przekazania): ciało z
  przekazaniem (inaczej 422 `handoff_required`), `allocation_lock` → wiersz
  `FOR UPDATE` → ta sama bramka → przekazanie. `PATCH` odmawia `status=draft`
  (`draft_not_allowed`) i publikacji z innego stanu (409 `reopen_required`);
  ten sam status wysłany ponownie przechodzi (okno edycji odsyła wszystkie
  pola). Przekazanie starego szkicu go publikuje.
- **Ponowne otwarcie ZAMKNIĘTEJ rekrutacji nie pyta o rekrutera (decyzja Artura
  09.10.2026).** `POST /{id}/publish` bez ciała albo z `assignment_mode: "keep"`
  (wartość istnieje tylko na `JobPublishRequest` — `/handoff` i `POST /api/jobs`
  jej nie przyjmują) → `job_lifecycle.reopen_keep_team_core`: ta sama bramka
  kompletności, `searching`, migawka dopasowań, `Activity handed_off_to_search`
  z `assignment_mode: "keep"`. Prowadzący i ręczni współpracownicy zostają;
  aktywny prowadzący dostaje wiersz przypisania i dzwonek (nie osoba, która
  otwiera), nieaktywny = brak rekrutera. Bez rekrutera request trafia do
  automatu (tryb ≠ `off`) albo do kolejki Head of Recruitment „Nowe rekrutacje —
  kto prowadzi”. 422 `handoff_required` zostaje wyłącznie dla „Dokończ
  i opublikuj” (stary szkic, opublikowana bez przekazania) — tam okno nadal
  pyta o rekrutera. `JobReopenDialog` w trybie `reopen` pokazuje jedną linię
  („Rekruter: X — bez zmian”), zmiana w zakładce „Zespół i ogłoszenie”.
- **Brak z bramki ma działanie tam, gdzie da się go zamknąć (08.10.2026).**
  Hiring managera i termin (albo „Klient nie podał”) ustawia się wprost w oknie
  „Otwórz ponownie” (`JobReopenDialog`: `HiringManagerPicker`, `DeadlineEditor`)
  — archiwum z Traffita nie ma ich nigdy, więc pyta o nie każde ponowne
  otwarcie. Kategoria i liczba osób prowadzą do zakładki „Zespół i ogłoszenie”
  (akcja `team` w `lib/order-readiness.ts`, także w liście braków
  `MissingBlock`), reszta do Profilu Championa. Do tej daty cztery decyzje
  z 04.10 nie miały klucza na froncie i każdy brak odsyłał do edytora
  Championa, w którym tych pól nie ma. Nowy kod braku = wpis w `ReadinessKey`
  z działaniem. Uwaga Championa „Sprawdź i zatwierdź alternatywy”
  (`review_alternatives`) nie pojawia się przy profilu z wierszami wymagań —
  warianty w wierszu są tą decyzją.
- **Ochrona w trakcie pracy:** zapis Championa, `PATCH /api/jobs` i
  `PUT …/hiring-manager` na rekrutacji opublikowanej odmawiają (422
  `handoff_regression`) tylko przy NOWYM kodzie braku. Porównujemy KODY, nie
  zdania (zdania Championa niosą wartości). Brak „odsłonięty” przez
  uzupełnienie rodzica nie jest nowy (`_REVEALED_BY`: pytania → deal-breaker,
  tryb pracy → dni/miasto, must → krytyczne) — inaczej starej rekrutacji nie
  dałoby się uzupełniać krok po kroku. HM zdjęty przez zmianę klienta też nie
  jest nowym brakiem (nowego HM wskazuje się osobnym zapisem po zmianie —
  kontakt musi należeć już do nowego klienta). Zapisy systemowe
  Championa (import dokumentu, weryfikacja, briefing) są świadomie poza ochroną.
- **Niedokończony formularz to NIE rekrutacja:** `job_intake_forms` (0416,
  `services/job_intake_forms.py`, trasy `/api/job-intake/forms`) na koncie
  autora — tylko autor czyta i zmienia, limit 20 (409 `forms_limit`), 30 dni
  retencji w `queue_retention`, kasowany w transakcji tworzenia
  (`intake_form_id`). `/jobs/new` zapisuje go sam (3 s po zmianie) i wznawia
  z kroku 1 albo `?form=<id>`.
- **Stare szkice:** pulpit „Czeka na Ciebie” → `pending_jobs`
  (`services/pending_job_completion.py`: szkice i opublikowane bez
  przekazania z brakami; DL swoje, HoR i admin wszystkie) + `unfinished_forms`
  autora starsze niż 2 dni. Szkice zamykają się same 7 dni po
  `app_settings['legacy_draft_autoclose:deployed_at']` (`legacy_draft_autoclose.py`,
  pętla `job_deadline_alerts`, `close_reason=other`, paragon
  `legacy_draft_autoclose:receipt` z samymi ID) — nic nie jest kasowane.
- **„Odpada, gdy…” ma skutek:** `move_requirements` dokłada pozycję
  `deal_breaker` (nie blokuje, akcja `reject` z `note`) przy ruchu od
  „Zweryfikowany” wzwyż, gdy arkusz pary ma `deal_breaker_hit`; okno „Przesuń
  dalej” mówi „Przesuń mimo to”. Karta rekomendacji pokazuje warunek i zapisuje
  trafienie (`POST /api/recommendation-cards/deal-breaker`) — tylko przy
  pytaniu, które ma odpowiedź w arkuszu (pole wyboru stoi wyłącznie przy
  `source: "sheet"`); bez arkusza pary 409. Odpowiedzi z notatek nadal NIE
  trafiają do arkusza (reguła 0413). Przegląd zgłoszeń AI (prompt v2) dostaje warunki
  i oznacza `entry_meta.deal_breaker_hit` — plakietka, `decide` bez zmian.
- **Odczyt maila v11:** `deadline`, `deadline_time`, `headcount` tylko
  z dosłownym cytatem; „ASAP” = puste.
- Wzmianki w starszych sekcjach o „Zapisz szkic”, kolejności
  `POST /api/jobs → PUT champion → handoff → publish` albo otwieraniu
  rekrutacji polem Status opisują stan sprzed 04.10.2026.
