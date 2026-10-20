# Kafelek „Kandydaci do zamknięcia” (20.10.2026)

Prośba Olafa (Head of Recruitment): lista osób zaakceptowanych przez klienta
z klientem, stawkami, marżą, Delivery Leadem i rekruterem. Decyzje Artura
20.10.2026: kafelek w katalogu „Dodaj kafelek” (nie lista w „Czeka na
Ciebie”), cała kolumna „Akceptacja i umowa”, zakres i kwoty według roli.
Kod: `services/closing_candidates.py`, `GET /api/board-tasks/closing`
(`api/board_tasks.py`), front `custom/ClosingCandidatesTile.tsx`,
`lib/closing-candidates.ts`.

- **Kto jest na liście:** pary, których NAJNOWSZY wiersz stoi w kolumnie
  Tablicy „Akceptacja i umowa” — ta sama reguła kolumn co Tablica
  (`cv_in_transit._place`). Krok z odznaki etapu: „Zaakceptowany”, „Umowa
  wysłana”, „Podpisana”. Po „Zatrudniony” osoba znika. Najdłużej czekający na
  górze, do 50 wierszy, z liczbą wszystkich.
- **Zakres:** admin, Head of Recruitment i Finanse — wszystkie opublikowane
  rekrutacje; Delivery Lead — jak przegląd DL (`board_flow._dl_job_ids`);
  Rekruter i TCM — rekrutacje, w których są Rekruterem, i te, w których
  prowadzą kandydata. Bez warunku `work_state`: po akceptacji request bywa już
  „Zakończony”, a umowa jeszcze nie.
- **Kwoty:** stawki pary z `recruitment_rates.for_pairs` (do klienta =
  przychód, kandydata = koszt). Stawkę do klienta widzą tylko role z
  `user_can_view_client_rate`; bez niej trasa zwraca `show_client_rate:
  false`, a kafelek nie ma kolumn przychodu i marży. Marżę liczy front
  `computeMargin` (PLN/h, dzień = 8 h) — ta sama reguła co przegląd DL; inna
  waluta albo brak stawki kandydata = napis, nigdy zmyślona liczba.
- **Rekruter pary** z `interview_slots.default_recruiter_ids` (właściciel
  procesu → weryfikujący → Rekruter rekrutacji), DL z `jobs.delivery_lead_id`.
