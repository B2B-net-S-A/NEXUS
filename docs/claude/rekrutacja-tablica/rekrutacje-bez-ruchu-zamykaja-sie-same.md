# Rekrutacje bez ruchu: przypomnienie DL po 14 dniach, HoR po 21, zamknięcie po 28 (28.10.2026)

<!-- indeks: `services/job_idle.py`, `no_activity` = przegrana, „Jeszcze trwa”, pętla `job_idle`, `job_idle_reminder` -->

Prośba Artura z 28.10.2026: ponad 100 otwartych requestów, część martwa. Kopia
produkcji z 22.10: 204 otwarte, 90 bez ruchu od 14+ dni, 66 od 21+, 39 od 28+.
„Porządek w requestach” (24.09) niczego nie wymuszał: 194 w „Szukamy”,
1 w „Klient milczy”. Artur odrzucił wersję z osobną listą „Do decyzji” i oknem
z powodami („za dużo”) i wybrał jedną regułę z dwoma przyciskami. Makiety:
https://claude.ai/artifact/VKCXNX7A4Tqw5q5FTbP3kz (wersja 2).

## Reguła

- **Ruch Delivery Leada** = CV wysłane do klienta albo karta przesunięta po
  odpowiedzi klienta (rozmowa, akceptacja, umowa, zatrudnienie, odrzucenie
  osoby, która była u klienta). Screening, notatki, odrzucenia na wcześniejszych
  etapach i aplikacje z ogłoszeń nie są ruchem: w 12 z 36 martwych rekrutacji
  rekruter ruszał karty w ostatnich 14 dniach.
- Licznik liczy dni kalendarza firmy od późniejszego z: ostatniego ruchu,
  otwarcia rekrutacji, „Jeszcze trwa” (`jobs.idle_snoozed_at`) i startu reguły
  minus 14 dni (`app_settings['job_idle:started_at']`, zapisuje go pierwszy
  przebieg). Zaległe dostają więc przypomnienie w dniu włączenia, a —
  decyzja Artura z 29.10.2026, bo na kopii stagingu byłoby to 113 z ok. 200
  otwartych — HoR po 21 dniach i zamknięcie po 28 (`BACKLOG_EXTRA_DAYS`).
- **14 dni** → dzwonek i mail obowiązkowy do Delivery Leada (bez aktywnego DL:
  Head of Recruitment). **21 dni** → to samo i do Head of Recruitment, z liczbą
  rekrutacji na DL. **28 dni** → NEXUS zamyka (`close_job_core`, autor pusty)
  powodem `no_activity` z notatką; DL i HoR dostają informację.
- Zamknięcie najwcześniej 7 dni (kalendarz firmy) po przypomnieniu do HoR w tym
  samym cyklu — przestój pętli nie zamknie niczego bez ostrzeżenia.
- **Decyzja Artura: `no_activity` liczy się jak przegrana**
  (`HIT_RATIO_LOST_CLOSE_REASONS`, lustro `SYSTEM_CLOSE_REASON_GROUPS`
  w `lib/job-close-reasons.ts`). Człowiek go nie wybierze (422
  `close_reason_system_only`), ale może go zmienić „Zmień powód zamknięcia”,
  a rekrutację otworzyć ponownie.
- Automat nie pisze do rekruterów osób w toku (reguła zamykania w
  `zamkniecie-rekrutacji-osoby-w-toku.md`); pasek zamkniętej Tablicy pokazuje
  im ich osoby.

## Gdzie to siedzi

- Reguła i przebieg: `backend/app/services/job_idle.py` (czyste `idle_state`,
  `stage_for`, `notice_text` + `run_idle_sweep`). Pętla `job_idle`
  (`app/tasks/job_idle.py`): co godzinę, działa w dzień roboczy 8–17 (Warszawa);
  na stagingu zablokowana. Kill-switch `JOB_IDLE_ENABLED`.
- Jeden wpis `job_idle_reminder` dziennie na osobę (dedup dobowy `emit`),
  mail obowiązkowy `job_idle`. Znaczniki etapów: `Activity` `idle_notice`
  z `stage`, `since` i dniem przebiegu (`on`); nowy cykl = nowe `since`.
- Trasy (`app/api/job_idle.py`, ta sama bramka co `POST /close`):
  `GET /api/jobs/{id}/idle`, `POST /api/jobs/{id}/idle/snooze` („Jeszcze
  trwa”, wpis `idle_snoozed` w historii; HoR widzi liczbę odłożeń).
- Front: `JobIdleBanner` nad Tablicą dla tych, którzy mogą zamknąć rekrutację;
  „Zamknij…” otwiera dzisiejsze okno zamykania (przy zatrudnieniu z
  „Wygraliśmy”), „Jeszcze trwa” liczy od nowa. Migracja 0617, lustro
  w `entrypoint.sh`.
- Istniejący poranny skrót `request_review_needed` („Szukamy” bez pracy od
  30 dni) został bez zmian.
