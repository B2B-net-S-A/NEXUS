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
  osoba, która zweryfikowała kandydata, a bez niej właściciel wydarzenia, link `/calendar?cycle=c-j&debrief=<id>` (ekran otwiera
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
- **Od 20.10.2026 rozmowę zakłada też ruch karty („Kiedy rozmowa?”) i zapis
  pytań bez terminu**, a bramka przed „Umową” obejmuje każdą parę z etapem
  rozmowy — `pytania-z-rozmowy-bez-terminu.md`.
- **Telefon i e-mail kandydata w nagłówku panelu** (wariant C z makiet,
  20.10.2026): `candidate_phone` obok `candidate_email` w `PairInfo`, za tą
  samą bramką odczytu kandydatów; numer = `tel:`, e-mail = `mailto:`,
  „Kopiuj oba”. Bez obu linii nie ma (`CandidateContactLine`).
- **Twórca wydarzenia zostaje jego właścicielem** także wtedy, gdy otwarte
  wydarzenie ma innego `operational_owner_id` (`user_owns_event`). DL zakłada
  rozmowę u klienta z rekruterem jako właścicielem i poprawia termin, gdy
  klient go przesunie; od #1390 do 29.10.2026 edycja kończyła się 404
  „Wydarzenie nie znalezione”, choć lista pokazywała DL-owi ten wpis.
  Zastępca widzi tylko otwarte wydarzenia osoby, którą zastępuje — to bez zmian.
- **Dwa wpisy rozmowy o tej samej godzinie to jedna runda** (zgłoszenie
  03.11.2026): rozmowa wpisana przy ruchu karty, a chwilę później wniosek o ten
  sam termin dawały parze dwa wiersze `client_interview`. Do startu ekran był
  poprawny, a po starcie Prep i Prep 2 świeciły „pominięte”, bo „poprzednia
  runda” kończyła się o tej samej godzinie. Granice rundy liczą
  `interview_cycle.preps_of_round` i `late_preps_of_round` (ekran i API integracji),
  a potwierdzenie wniosku odwołuje wpis o tej samej godzinie
  (`interview_slots._cancel_same_hour_entries`). Spotkania z Outlooka
  z uczestnikami zostają, jak przy przełożeniu (`replaceable_interviews`).
- **„Zmień termin” przy rozmowie** (zgłoszenie 04.11.2026): klient przełożył
  rozmowę na przyszły tydzień, prep dało się przełożyć z panelu, rozmowy nie.
  Edycję miał tylko właściciel, a DL rekrutacji na „Szczegółach” dostawał 404.
  Przycisk stoi w panelu kandydata i w doku osoby
  (`components/calendar/cycle/RescheduleInterview.tsx`), zapis idzie przez
  `POST /api/interview-cycle/events/{id}/reschedule`. Nowy termin dostaje **to
  samo wydarzenie**, więc prepy, telefon i debrief zostają przy tej rundzie.
  Mogą to zrobić ludzie pary: właściciel, DL rekrutacji, rekruter kandydata
  i HoR/admin (`_interview_move_refusal`, `can_reschedule` w odczycie wydarzenia).
  **Nie zamieniaj tego na `_ensure_pair_writer`**: `ensure_job_membership`
  przepuszcza każdego rekrutera, a zmiana idzie do cudzego kalendarza. Cudze
  spotkanie z Outlooka bez wniosku o terminy zostaje u organizatora (409), bo
  mogą w nim być osoby spoza firmy. Przełożyć można tylko rozmowę przed nami.
  Przełożenie zdejmuje „Odpisz klientowi” (także przy PATCH z Tygodnia), bo
  gotowy tekst podawał stary termin; `client_replied_at` zostaje puste.
- **Zamknięcie karty anuluje otwarty wniosek o terminy** (decyzja Artura
  04.11.2026, zastępuje „przywrócona wraca z tym samym wnioskiem” z 23.10.2026).
  Pomiar z 04.11: 7 z 15 otwartych wniosków stało na kartach „Odrzucony”
  i „Wycofany”, karta mówiła „Wybierz termin”, panel osoby miał aktywny przycisk,
  a wniosek miał terminy jeszcze do 5 dni po zamknięciu. Anuluje
  `transition_process` przy etapie `rejected` i `withdrawn`, więc obejmuje ruch
  z Tablicy, ruchy zbiorcze i CPro. Przywrócona karta dostaje nowe terminy nowym
  wnioskiem. Potwierdzony termin zostaje. Od tej samej daty wniosek anuluje też
  ruch dalej niż rozmowa („Akceptacja”, „Negocjacje”, „Onboarding”, „Zatrudniony”).
  Stare wiersze: `scripts/cancel_open_slots_on_closed_cards.py`.
- **Wszystkie terminy minęły = DL dodaje nowe, rekruter nie ma zadania** (decyzja
  Artura 04.11.2026). Wybór takiego terminu kończył się 422, interfejs nie ma
  anulowania, więc „Wybierz termin” i „Potwierdź” wisiały bez końca: 6 z 15 otwartych
  wniosków na kopii z 03.11. Stan liczą `interview_cycle.slots_lapsed` (wniosek
  otwarty, `all_slots_past`, okno klienta żyje do `window_end`) i `needs_new_slots`.
  DL dostaje zadanie `slots_expired`, krok „Terminy” jest po terminie, a odznaka
  mówi „Terminy minęły · czeka na DL”. Zadania nie ma na karcie zamkniętej i po
  rozmowie ani gdy po wniosku rozmowa się odbyła albo jest zaplanowana (termin
  ustalono poza wnioskiem). Taki wniosek nie blokuje nowego
  (`_cancel_lapsed_request`, także dla klienta w panelu) ani follow-upu z kandydatem.
- **Zamknięta rekrutacja gasi otwarty wniosek w odczycie** (decyzja Artura
  04.11.2026): `load_snapshots` go pomija, wiersz zostaje bez zmian. Debrief i prep
  zostają zadaniami, nie ma „Brak terminów” ani „Uzupełnij pytania”.
- **Zamknięta karta z rozmową bez debriefu** ma odznakę „Debrief niezapisany”
  (`debrief_missing`, decyzja Artura 04.11.2026), nie czerwone „Zadzwoń”. Nikt już
  do tej osoby nie dzwoni, a ekran „Rozmowy u klienta” takiej pary nie pokazuje.
  „Zapisz debrief” zostaje w doku, bo pytania klienta mają wartość dla następnych.
- **Telefon po rozmowie należy do osoby, która zweryfikowała kandydata** (decyzja
  Artura 09.11.2026). Rekruterka przypisana do rekrutacji dostawała na ekranie cudzego
  kandydata, a weryfikująca nie miała zadania jako swojego. `PairSnapshot.verifier_id`
  (`stage_verifier.verifier_ids`, tylko aktywne konto), bez niego właściciel rozmowy.
  Zadania `call_now` i `debrief_overdue` widzi telefonujący, właściciel rozmowy i widok
  DL (`jobs`). Rekruter z `jobs.recruiter_id` dostaje parę w „mine” tylko wtedy, gdy
  `default_recruiter_ids` wskazuje właśnie jego. **Nie używaj `default_recruiter_ids` do
  telefonu:** zwraca właściciela procesu, który bywa DL-em.
- **Zamknięta karta nie dostaje przypomnień T+15/T+45** (`_card_closed`).
- **Spotkania przy zamknięciu karty** (decyzja Artura 09.11.2026): okno rezygnacji
  i odrzucenia pokazuje spotkania przed nami, domyślnie do odwołania
  (`RejectionMeetingsField`, `GET …/pairs/{job}/{candidate}/meetings`). Po ruchu front
  woła `POST …/meetings/close`: karta musi być zamknięta, a wołający to osoba, która
  ją zamknęła, albo admin/HoR (`pair_meetings.ensure_can_close`). Odwołuje ta sama
  `cancel_event_effects` co Tydzień, po jednym spotkaniu, więc odmowa Outlooka przy
  jednym nie cofa reszty ani zamknięcia. Klienta NEXUS nie powiadamia i okno mówi to
  wprost. Zaproszenie z Outlooka bez bliźniaka o tej samej godzinie = prośba dzwonkiem
  do prowadzącego (`ask_to_cancel`). Przy kilku osobach naraz listy nie ma.
- **Jedna rozmowa w kilku rekrutacjach klienta = jeden debrief** (zgłoszenie
  12.11.2026). Kandydatka w dwóch requestach Nordei na Scrum Mastera miała
  jedną rozmowę u klienta wpisaną w obu (raz przy ruchu karty, raz przy
  zapisie pytań). Debrief zapisany w jednej rekrutacji zostawiał w drugiej
  „Telefon po rozmowie · po terminie 167 h” i „Zapisz debrief”. Ten sam
  kandydat, ten sam `client_id` i ta sama godzina rozpoczęcia to jedno
  spotkanie: `debrief_gate.shared_meeting_debriefs` daje debrief spod
  bliźniaczego wpisu, a zamyka on rundę w bramce (`missing_debrief`), na
  ekranie (`load_snapshots`) i w API integracji (`closed_debrief_event_ids`).
  Odwołany wpis się nie liczy, inna godzina albo inny klient to osobna
  rozmowa. Debrief nie jest kopiowany; zapis w drugiej rekrutacji zakłada
  własny wiersz pod jej wpisem. Na kopii z 10.11 takie pary były 2.
