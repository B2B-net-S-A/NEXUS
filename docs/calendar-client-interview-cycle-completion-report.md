# Kalendarz → „Rozmowy u klienta” — raport z wdrożenia (22.09.2026)

## Dlaczego

Stan produkcji (odczyt 21.09.2026):

| Liczba | Co znaczy |
|---|---|
| 10 | wydarzeń założonych w NEXUSIE w całej historii (0 w ostatnich 90 dniach) |
| 7 204 | kopii spotkań z Outlooka od 3 osób (aktywne połączenie M365 mają 2) |
| 1 759 | ruchów na „Rozmowa”/„Rozmowa z klientem” w 90 dni, bez wydarzeń w kalendarzu |
| 0 | feedbacków po rozmowach |

Zespół (odpowiedzi Artura): nie planuje screeningów ani rozmów; planuje prep
i drugi prep; musi znać termin rozmowy kandydata u klienta, żeby zadzwonić
≤30 min po niej. Termin powstaje w pętli DL ↔ rekruter ↔ klient. Po telefonie
ważne są: jak poszło, jakie były pytania (do analizy i lepszego przygotowania
kolejnych osób) i czy kandydat przyjmie ofertę.

Makiety: https://claude.ai/artifact/JrN6w6FfJb8syMRhGvq4Jq — wdrożone A (agenda,
domyślna) + C (tydzień jako zakładka) + B (tablica dla DL) + okno debriefu.

## Co powstało

**Backend**
- Migracja `0338_client_interview_cycle` (+ lustro w `entrypoint.sh`):
  `eventtype.client_interview`, `interviewquestionsource.client_debrief`,
  4 typy powiadomień, tabela `client_interview_slot_requests`,
  `interview_feedback.offer_acceptance` / `acceptance_condition`.
- `app/api/interview_cycle.py` — `GET /api/interview-cycle`, sloty
  (create/choose/confirm/cancel), debrief (GET/PUT), pytania klienta.
- `app/services/interview_cycle.py` (kroki, zadania, agenda) i
  `app/services/interview_slots.py` (przejścia, wydarzenie `client_interview`,
  blokada w Outlooku rekrutera).
- Wyzwalacze `post_interview_*` + auto-complete obejmują rozmowę u klienta;
  link prowadzi do debriefu.
- Prep-kit: warstwa `client_debrief`.
- Edycja terminu wydarzenia z Outlooka przepychana do Grapha
  (`update_graph_event`), czas lokalny `Europe/Warsaw`.
- Sonda `/api/health/deep`: `client_interview_slot_requests`.

**Frontend**
- `/calendar` = `CalendarCycleScreen`: Agenda / Tydzień / Tablica, zakres,
  okna: terminy od klienta, wybór/potwierdzenie terminu, debrief, prep
  (`ScheduleInterviewModal` z `prep_call`).
- Dawna strona → `components/calendar/WeekCalendar.tsx` (bez zmian zachowania;
  legenda typów tylko w panelu bocznym).
- Okno wydarzenia: termin/tytuł/miejsce/opis wydarzenia z Outlooka edytowalne.
- Dzwonek: ikony nowych typów.
- Harness `/preview/calendar-cycle` (`?as=dl`).

## Testy
- Backend: `test_interview_cycle.py`, `test_calendar_outlook_update.py`
  + dotknięte istniejące (kalendarz, wyzwalacze, prep-kit, sekcje) — zielone.
- Frontend: `lib/__tests__/interview-cycle.test.ts`,
  `components/calendar/cycle/__tests__/CalendarCycleScreen.test.tsx`,
  `WeekCalendar.test.tsx` (przeniesiony) — pełny pakiet 4845 zielony.
- Wizualnie: harness w Playwright (1440 px i 390 px), zero błędów konsoli,
  zero zapytań API.

## Znane ograniczenia
- Synchronizacja z Outlookiem działa tylko dla osób z połączoną skrzynką
  (na produkcji 2 aktywne połączenia) — reszta zespołu musi połączyć M365
  w Ustawieniach, żeby prepy trafiały do Outlooka i zmiany terminów wracały.
- Ruch na „Rozmowa z klientem” nie otwiera okna terminów automatycznie
  (świadomie: „Kanban bez bramek”); DL widzi taką parę jako
  „Brak terminów od klienta”.
- Siatka tygodnia nie rysuje jeszcze wirtualnego wiersza „Telefon po” —
  jest na agendzie.
