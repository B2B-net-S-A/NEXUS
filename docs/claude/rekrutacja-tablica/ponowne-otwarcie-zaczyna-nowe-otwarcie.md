# Ponowne otwarcie rekrutacji zaczyna nowe otwarcie (05.11.2026)

<!-- indeks: `jobs.cycle_started_at`, `job_opening`, obsada `filled_by_job`, „Sprzed otwarcia” na Tablicy, placement bez zmian (D2) -->

Zgłoszenie Artura z 05.11.2026: po „Otwórz ponownie” osoby z poprzedniego
otwarcia (zaakceptowane, a potem klient się wycofał, albo zatrudnione dawno
temu) liczyły się jak bieżąca praca. Ponowne otwarcie zmieniało tylko status
i nie ruszało kart, a liczniki „na teraz” brały każdą kartę opublikowanej
rekrutacji. Pomiar na kopii produkcji z 04.11.2026:

- otwarcie 76 zamkniętych rekrutacji z kartą w Akceptacji (87 kart, od 2022)
  podnosiło „Akceptacje do domknięcia” z 7 do 92, a prognozę z 6–7 do 82–83
  placementów (zdanie w mailu do Rady też);
- 11 z 95 otwartych ponownie rekrutacji miało 0 wakatów przez zatrudnienie
  sprzed otwarcia i odmowę 422 `close_reason_has_hire` przy zamknięciu jako
  „nie liczy się”;
- placementów nie przybywało (856 przed i po), bo placement to pierwsze
  „Zatrudniony” pary (D2), a nic nie przenosiło kart samo.

## Decyzje Artura (05.11.2026)

- **Nowe otwarcie.** `publish_core` przy ponownym otwarciu zapisuje
  `jobs.cycle_started_at` (`services/job_opening.py`, migracja 0653, lustro
  w `entrypoint.sh`). Lustro w gałęzi PATCH statusu, choć PATCH z „Zamknięta”
  na „Opublikowana” odpowiada dziś 409 `reopen_required`.
- **Przeniesienie z Traffita to nie nowe otwarcie** (`new_opening=False`
  w `traffit_transfer`): ta sama praca, karty są żywe. Uzupełnienie
  z historii (`BACKFILL_SQL`, jednorazowo ze znacznikiem
  `0653_job_opening_backfill`) bierze ostatnie ponowne otwarcie przez
  człowieka i pomija `traffit_transfer`.
- **Od otwarcia liczą się stany „na teraz”**, nic więcej:
  - obsada i wakaty — `job_fill.filled_by_job` (osoby z „Zatrudniony”
    w bieżącym otwarciu, bez wykluczonych placementów): raport DL, Insights
    → Delivery Leadzi, pulpit DL, miejsca Championów (`_hired_ids(since=…)`),
    pauza szukania przy faworycie, podpowiedź „komplet obsady” (jedna na
    otwarcie), bramka `close_reason_has_hire` i „wygrana” w raporcie
    zamknięć;
  - „W drodze”, prognoza z akceptacji, zdanie o zatorze i mail do Rady
    (`insights_in_flight`), „Teraz” w „Lejku po etapach”, ostrzeżenie
    `active_cards_warning`, dzwonek i mail przy zamknięciu oraz pasek
    „Twoje osoby” na zamkniętej Tablicy.
- **Karta liczy się w bieżącym otwarciu, gdy jej najnowszy ruch jest od
  otwarcia.** Osoba z poprzedniego otwarcia, którą rekruter ruszy, wraca do
  liczb bez żadnego okna wyboru.
- **Tablica:** karta sprzed otwarcia zostaje w swojej kolumnie, wyszarzona,
  z etykietą „Sprzed otwarcia DD.MM.RRRR” (`board-card-badges.fromPreviousOpening`,
  `KanbanView.opening_started_at`). Nic nie znika i nic nie jest przenoszone.
- **Placement się nie zmienia.** Osoba zatrudniona w poprzednim otwarciu
  i zatrudniona jeszcze raz w nowym zajmuje wakat, ale drugiego placementu nie
  daje (Liga, KPI, Insights, wyścigi bez zmian). Historia — lejek „Doszło”,
  placementy w oknie, hit ratio w Lidze — liczy się jak dotąd.

## Pułapki

- Nowy licznik „na teraz” na kartach rekrutacji (wakaty, w toku, akceptacje)
  bez `in_opening_sql` / `filled_by_job` = ta sama regresja.
- Nie filtruj wierszy etapów przed wyborem najnowszego: „Prowadzi” i pierwszy
  weryfikujący biorą się z całej historii pary. Filtruj kartę po jej
  najnowszym ruchu (`waiting_cards(since=…)`).
