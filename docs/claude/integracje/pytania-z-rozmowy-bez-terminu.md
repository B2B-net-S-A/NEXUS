# Pytania z rozmowy u klienta także bez terminu w NEXUSIE (20.10.2026)
<!-- indeks: „Kiedy rozmowa?”, `questions_missing` po 24 h, debrief bez wydarzenia, bramka przed „Umową” -->

Zgłoszenie Artura 20.10.2026: ludzie nie wiedzą, gdzie wpisać pytania z rozmowy
u klienta, i wpisują je w notatki, a komunikat „uzupełnij pytania” się nie
pokazuje. Stan na produkcji (30 dni): 99 par weszło w etap „Rozmowa z klientem”,
tylko 11 miało wydarzenie `client_interview`; 6 debriefów w 60 dni, ostatnie
pytanie w banku 05.10; przy 25 parach po rozmowie notatka ze słowem „pyta…”.
Przyczyna: cały cykl (telefon ≤30 min, „Debrief zaległy”, bramka przed „Umową”,
przycisk „Zapisz debrief”) liczy się od wydarzenia, a wydarzenie zakładała tylko
ścieżka „Terminy od klienta”, której zespół nie używa. Makiety:
https://claude.ai/artifact/XgFQKNe1npJ6W8zkX66Rdt; Artur przyjął wszystkie
elementy i przeniesienie starych notatek (osobny PR).

- **Termin przy ruchu.** Ruch na „Rozmowę u klienta” (`moveDialogFor` →
  `interview_date`) otwiera `ClientInterviewDateDialog`, chyba że para ma
  zaplanowaną rozmowę albo otwarty wniosek o terminy (`needsInterviewDate`).
  Termin zakłada rozmowę DOPIERO po udanym ruchu
  (`POST /api/interview-cycle/client-interviews`): odmowa ruchu nie może
  zostawić w kalendarzu rozmowy osoby, która nie przeszła. Para z zaplanowaną
  rozmową = 409. Ruch zbiorczy nie pyta. „Nie znam jeszcze terminu” = zwykły ruch.
- **Wydarzenie z NEXUSA, bez Outlooka** (`services/client_interview_entry.py`):
  właściciel = rekruter pary (`interview_slots.default_recruiter_id`, ta sama
  reguła co wniosek o terminy), `external_source = manual`. Kandydata zaprasza
  klient.
- **Pytania bez wydarzenia** — `PUT /api/interview-cycle/pairs/{c}/{j}/debrief`
  (`held_on`, opcjonalnie `held_at`): bieżąca runda bez debriefu
  (`missing_debrief`) dostaje ten debrief; rozmowa dopiero zaplanowana = 422;
  bez rozmowy — zakłada odbytą rozmowę z tą datą (bez godziny 9:00, dziś przed
  9:00 — chwila temu) i zapisuje debrief w tej samej transakcji. Rozmowa z tego
  samego dnia już istnieje = nie druga runda: bez debriefu dostaje ten zapis,
  a Z DEBRIEFEM zapis odmawia 409 `DEBRIEF_EXISTS` (`event_id`, `message`)
  i okno (`DebriefDialog`) przechodzi na ten debrief do poprawy — wczytuje
  ocenę, ofertę i pytania, dopisuje pytania wpisane przed chwilą (decyzja
  Artura 22.10.2026, audyt F27: dotąd okno pary startowało od pustego
  formularza i zapis nadpisywał pytania, ocenę i ofertę zapisane wcześniej
  przez kogoś innego). Dalej wszystko jak przy zwykłym debriefie (bank pytań
  klienta, pin, kroki, bramka).
- **Zadanie `questions_missing`** (`compute_todos`): para w etapie
  „Rozmowa z klientem” od `QUESTIONS_MISSING_AFTER_HOURS` (24 h), bez rozmowy
  w kalendarzu i bez otwartego wniosku o terminy. Adresat = rekruter pary
  (`default_recruiter_ids` w `load_overview`), bez niego Delivery Lead
  (`todo_is_mine`). Okienko „Rozmowy” bierze je z serwera (ikona notatki), akcja
  = okno pytań bez wydarzenia. Gaśnie samo, bo zapis zakłada rozmowę.
- **Bramka przed „Umową” dla każdej pary z etapem rozmowy**
  (`debrief_gate.missing_debrief`): bez wydarzenia, ale z wierszem etapu
  `client_interview` w tej rekrutacji → 409 `DEBRIEF_REQUIRED` z
  `event_id = None` i `needs_interview_date = true`. Front (`debriefRequiredOf`,
  `DebriefRequiredDialog` z `candidateId`) otwiera okno pytań pary. Wyłącznik:
  `DEBRIEF_GATE_WITHOUT_EVENT` (domyślnie włączony). Para, która nigdy nie była
  w etapie rozmowy, nie jest bramkowana.
- **Okno pytań** (`DebriefDialog` z `pair`, `eventId = null`) ma na górze
  „Kiedy była rozmowa?”. Zapytania o wydarzenie są wtedy wyłączone, a `loading`
  nie może wisieć na `isPending` wyłączonego zapytania (TanStack v5 trzyma
  `pending` bez końca).
- **Panel osoby:** `DockClientInterviewQuestions` („Pytania z rozmowy”) dla pary
  na „Rozmowie u klienta” bez rozmowy i bez otwartych terminów; podpowiedź
  `ClientQuestionsNoteHint` po zapisie notatki, która wygląda na pytania klienta
  (`lib/client-question-notes.ts`, bez AI — szkic listy do poprawy w oknie).
  Notatka zostaje notatką. Panel zapisuje pytania przyciskiem „Zapisz pytania”
  (bez ruchu karty).
- Granice słów w regułach notatek: `\b` w JS zna tylko ASCII („rozmową”), więc
  `(?<!\p{L})…(?!\p{L})`.
- Uprawnienia jak zapis debriefu: `RecruitmentAssessmentWriteAccess`, rekruter
  pary albo członek zespołu rekrutacji; para spoza procesu = 404.
- **Powrót na „Rozmowę” nie pyta o termin (audyt 21.10.2026).** „Cofnij
  akceptację klienta” woła `requestMove(…, { skipInterviewDate: true })`,
  a `usePipelineMove` sam pomija „Kiedy rozmowa u klienta?” przy powrocie
  z niezamkniętej kolumny za „Rozmową” (`pipeline-move-dialog.movesBackTo`)
  — karta była już na rozmowie. Ruch naprzód bez terminu pyta jak dotąd,
  także po odbytej rozmowie (kolejna runda), a przywrócenie z „Zamkniętych”
  też pyta.
- **Import pytań ze starych notatek** (`scripts/import_note_client_questions.py`):
  notatka bez `job_id` trafia do pary tylko, gdy kandydat ma w oknie dokładnie
  jedną parę po wejściu w „Rozmowę z klientem” (`split_ambiguous_notes`,
  ta sama reguła w `group_by_pair` dla starszych planów); inaczej idzie do
  „Odrzuconych” z powodem „niejednoznaczna rekrutacja”. Wcześniej te same
  pytania lądowały w debriefach i bankach kilku klientów. `--skip-notes`
  przyjmuje id notatki albo `id_notatki:id_rekrutacji`.
