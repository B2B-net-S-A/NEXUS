# Kalendarz = „Rozmowy u klienta” (0338, 22.09.2026)

`/calendar` był kopią Outlooka trzech osób: 10 wydarzeń założonych w NEXUSIE
w całej historii, 0 w ostatnich 90 dniach, 0 feedbacków. Zespół nie umawia
w NEXUSIE screeningów ani rozmów. Planuje prep i drugi prep oraz musi znać
termin rozmowy kandydata U KLIENTA, żeby zadzwonić ≤30 min po niej. Ekran
prowadzi teraz jeden cykl per para (kandydat, rekrutacja):
`Terminy od klienta (DL) → Wybór terminu (rekruter) → Prep → Prep 2 →
Rozmowa u klienta → Telefon ≤30 min → Debrief`. Raport:
`docs/calendar-client-interview-cycle-completion-report.md`.

- **Dwa widoki: Tablica (domyślna) i Tydzień** (`?view=week`; zakładki
  „Agenda” nie ma od 24.09.2026 — decyzja Artura). Tablica: 7 kolumn w trzech
  grupach faz, puste kroki zwinięte, na karcie najpilniejsze zadanie pary
  spoza jej kolumny; klik w nazwisko (albo `?cycle=c-j` z dzwonka) otwiera
  panel kandydata (`CycleCandidatePanel`: zadania, 7 kroków, prepy z Teams,
  ocena prepu, terminy od klienta, pytania klienta, linki do rekrutacji
  i profilu). `?view=agenda` z zapisanych powiadomień prowadzi na Tablicę
  (`parseView`) — nie usuwaj aliasu. Tydzień (`WeekCalendar.tsx`, `?event=`/
  `action=feedback` bez zmian) domyślnie chowa zwykłe spotkania z Outlooka/iCal
  bez kandydata i rekrutacji (`isOtherOutlookMeeting`, przełącznik w tej
  przeglądarce). Zakres `?scope=mine|jobs|all` (lista „Pokaż”): DL/TAC
  domyślnie `jobs`, reszta `mine`, `all` tylko admin/HoR (403). **`jobs`
  zawiera też pary z `mine`** (`_scope_pairs.in_scope`, 02.10.2026): osoba
  z rolą TAC dostała dzwonek „Terminy rozmowy od klienta” jako rekruter
  kandydata w rekrutacji, w której nie jest w zespole — „Moje rekrutacje” były
  puste, a link z dzwonka mówił „nie ma w Twoim zakresie”. Domyślny widok nie
  może chować zadania przypisanego osobie imiennie; nie zawężaj `jobs` z powrotem.
- **Odznaka rozmowy na Tablicy rekrutacji stoi w KAŻDEJ kolumnie** i niesie
  `steps` (7 kresek) + `interview_event_id` (`interview_badges_for_job`) —
  osoba przesunięta dalej z zaległym telefonem wyglądała na załatwioną. Karta
  pokazuje samą plakietkę (od 04.10.2026 bez paska 7 kresek), kroki rysuje dok
  osoby w sekcji „Rozmowa u klienta” (`DockInterviewCycle`), a ścieżka
  i „Najbliższy krok” liczą `call_due` (`summarizeBoard.callDue`).
- **Kroki i zadania liczy SERWER** (`services/interview_cycle.py`, czyste
  `compute_steps`/`compute_todos` + hurtowe `load_overview`, stała liczba
  zapytań). Front (`lib/interview-cycle.ts`) tylko prezentuje. Para jest „w cyklu”,
  gdy ma otwarty wniosek o terminy, prep/rozmowę u klienta w oknie −14/+30 dni
  albo najnowszy etap „Rozmowa z klientem” z ostatnich 30 dni.
- **Terminy od klienta = `client_interview_slot_requests`** (`services/interview_slots.py`):
  `awaiting_recruiter → awaiting_dl → confirmed | cancelled`, przejścia pod
  `FOR UPDATE`, jeden OTWARTY wniosek na parę (częściowy UNIQUE → 409). Dodaje
  i potwierdza WYŁĄCZNIE admin/HoR/DL/TAC z członkostwem w rekrutacji; wybiera
  rekruter wniosku (domyślnie: właściciel procesu → pierwszy weryfikator →
  `job.recruiter_id`) albo członek zespołu. Potwierdzenie zakłada wydarzenie
  `EventType.client_interview` z `operational_owner_id` = rekruter i opcjonalnie
  blokadę w JEGO Outlooku bez uczestników (kandydata zaprasza klient; awaria
  Grapha nie blokuje potwierdzenia: `outlook="failed"`).
- **Telefon po rozmowie = istniejące wyzwalacze `post_interview_*`**, poszerzone
  o `client_interview` (`_POST_INTERVIEW_EVENT_TYPES`). Dla rozmowy u klienta:
  strona KANDYDATA (dzwoni rekruter, nie zbiera feedbacku klienta), odbiorca =
  właściciel wydarzenia, link `/calendar?cycle=c-j&debrief=<id>` (ekran otwiera
  okno debriefu). `calendar_auto_complete` też kończy `client_interview`.
  Okno na agendzie: `POST_INTERVIEW_CALL_WINDOW_MINUTES` (30).
- **Debrief = `InterviewFeedback(candidate_side)` pod wydarzeniem rozmowy**
  (`PUT /api/interview-cycle/events/{id}/debrief`, upsert): jak poszło
  (`overall_impression` 5/3/1), komentarz (`concerns`), pytania klienta
  (`client_questions` + bank `InterviewQuestion(source=client_debrief, client_id)`
  + pin `JobQuestion`), `offer_acceptance` (yes/likely/no/unknown) i
  `acceptance_condition` (nowe kolumny). Pytanie bez klienta NIE trafia do
  banku — globalny bank wyciekłby do prepów innych klientów.
- **Prep-kit ma warstwę `client_debrief`** (zaraz po przypiętych, filtrowana
  `_fits_job`) — pytania tego klienta z poprzednich rozmów. Prep z ekranu to
  `ScheduleInterviewModal` z `defaultEventType="prep_call"`; `prep_call`
  domyślnie dostaje Teams (lustro `_TEAMS_DEFAULT_EVENT_TYPES` ↔ `TEAMS_DEFAULT_FOR`).
- **„Oba kierunki” z Outlookiem:** PATCH terminu/tytułu/miejsca/opisu wydarzenia
  z Outlooka idzie NAJPIERW do Grapha organizatora (`update_graph_event`,
  czas w `BUSINESS_TZ` bez przesunięcia — `_graph_datetime`), dopiero potem do
  bazy. Brak połączenia twórcy / 400/403/404 = 409 i ZERO zmian lokalnie
  (zapis tylko w NEXUSIE sync by cofnął). Uczestnicy, cały dzień i link Teams
  zostają Outlookowi. Synchronizacja działa tylko dla osób z połączonym M365.
- Harness `/preview/calendar-cycle` (`?as=dl`) — dane fikcyjne, zero zapytań
  (dane agendy przez `dataOverride`, reszta zasiana w cache).
