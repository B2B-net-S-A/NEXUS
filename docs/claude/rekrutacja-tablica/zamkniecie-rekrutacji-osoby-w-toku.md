# Zamknięcie rekrutacji ostrzega o osobach w toku (13.10.2026)

<!-- indeks: 409 `active_cards_warning`, `acknowledge_active_cards`, powody i hit ratio -->

12.10.2026 Delivery Lead zamknął duplikat requestu z pięcioma kartami, na
których rekruterka pracowała kwadrans wcześniej. Zamknięcie zmienia status
rekrutacji i nie rusza kart, więc osoby zostały w zamkniętej rekrutacji, a okno
zamykania nic o nich nie mówiło. Na produkcji było wtedy 2 150 otwartych
procesów w 58 rekrutacjach zamkniętych w ciągu dwóch tygodni.

- **Ostrzeżenie do potwierdzenia, nie blokada** — jak „Przenieś mimo to” przy
  ruchu karty. `POST /api/jobs/{id}/close` bez `acknowledge_active_cards`
  odpowiada 409 `{code: "active_cards_warning", message, active_cards, columns,
  last_moved_at}`, gdy ktoś jest w toku; z potwierdzeniem zamyka jak dotąd.
- **„W toku”** = bieżąca karta osoby stoi w kolumnie Tablicy innej niż
  „Zamknięci” i „Zatrudniony” (`services/job_active_cards.py`, ta sama reguła
  kolumny co Tablica: `board_stage_badges.board_column_for`). Zatrudnieni
  i odrzuceni nie wywołują ostrzeżenia, więc zwykłe „obsadzone przez nas” po
  uporządkowaniu Tablicy przechodzi jednym kliknięciem.
- **Okno edycji zamyka tak samo, więc tak samo ostrzega.** `PATCH
  /api/jobs/{id}` ze `status: "closed"` (pole „Status” w „Edytuj rekrutację”)
  to lustro `close_job` — bez `?acknowledge_active_cards=true` odpowiada tym
  samym 409. Potwierdzenie jedzie w adresie, bo `JobUpdate` to wyłącznie pola
  rekrutacji (`model_fields_set` decyduje tam o uprawnieniach do pól).
- **Sprawdzają trasy, nie `close_job_core`.** Automaty (domknięcie starych
  szkiców, scalenie duplikatów, archiwum Traffita) zamykają bez pytania —
  nie ma tam człowieka, który mógłby potwierdzić.
- **Trzy okna zamykania** („Zamknij rekrutację z powodem” na stronie
  rekrutacji, „Zamknij jako przegraną” w profilu klienta i „Edytuj
  rekrutację” ze statusem „Zamknięta”) pokazują zdanie z serwera, liczby per
  kolumna (`lib/job-close.ts`, wspólne `ActiveCardsNotice`) i zmieniają
  przycisk na „…mimo to”. Nowe okno, które zamyka rekrutację, robi to samo —
  inaczej użytkownik dostanie sam błąd z odmową i nie zamknie rekrutacji.
- **Ostrzeżenie niczego nie robi z kartami.** Nie odrzuca osób i nie przenosi
  ich do innej rekrutacji; przeniesienie przy duplikacie requestu to osobne
  narzędzie scalania (`integracje/przeniesienie-rekrutacji-z-traffita-falami.md`).

## Hit ratio: przegrana = tylko konkurencja, reszta zamknięć „nie liczy się” (21.10.2026)

Zgłoszenie rekruterki 21.10.2026: zamknięcie zdublowanej rekrutacji obniżało
hit ratio, bo każda zamknięta rekrutacja wchodziła do mianownika. Od 12.10 do
21.10 na produkcji zamknięto 53 rekrutacje: 8 „Obsadzone przez nas”, 25 „Wybrali
konkurencję”, 20 „Inny” (6 z notatką o duplikacie).

### Decyzje Artura (21.10.2026)

- **Przegrana** to WYŁĄCZNIE `competitor` — rekrutację wzięła inna firma.
- **Wygrana**: zatrudnienie od nas (`analytics_first_milestones`), zwykle z powodem
  `filled_by_us`. Licznik hit ratio dalej liczy zatrudnienia, nie sam powód.
- **Nie liczy się** (poza mianownikiem każdego hit ratio): `duplicate`,
  `internal_hire`, `budget`, `paused`, `client_ghosted`, `no_match`.
- `other` i brak powodu (NULL) zostają w mianowniku, dopóki ktoś nie przypisze
  powodu. Wyłączenie wymaga uzasadnienia, więc nie dzieje się samo.
- Kontrola: uzasadnienie obowiązkowe przy „Nie liczy się” i lista „Zamknięte poza
  hit ratio” w Insights. Rozliczony kwartał Ligi się nie zmienia.
- „Inny” znika z okna zamykania; stare „Inny” trafiają do przeglądu.

### Gdzie to siedzi

- Grupy: `app/services/metric_definitions.HIT_RATIO_*_CLOSE_REASONS`.
- Filtr: `app/services/hit_ratio_scope.py` — `counts_in_hit_ratio()` (ORM) i
  `counts_in_hit_ratio_sql(alias)` (surowy SQL). Każdy wzór hit ratio korzysta
  z niego: Liga i cel DL (`competitions.dl_portfolio_counts`), Insights → Firma
  (`insights_board`, `insights_board_yoy`), raport klientów (`reports`),
  Insights klienci (`insights_clients`), raport DL (`reports._compute_dl_metrics`),
  „win rate” przetargów (`analytics/metrics.tenders`), portfele DL — kolumna
  `jobs_scoped.in_demand` filtruje tylko requesty i wakaty, NIE zatrudnienia
  (placementy łączą się z tym samym CTE; WHERE w CTE wycinałby je tylko w
  Portfelach, a liga by je liczyła).
- Nowy wzór hit ratio bez tego filtra = regresja. Nowy powód bez grupy pilnuje
  `tests/test_hit_ratio_neutral_closures.py`.
- Migracja 0502: `jobclosereason` + `duplicate`, `no_match`;
  `jobs.duplicate_of_job_id` (rekrutacja, która zostaje). Lustro w `entrypoint.sh`.
- Ponowne otwarcie (`publish_core` i gałąź PATCH statusu, wspólne
  `job_lifecycle.clear_close_choice`) czyści `close_reason`, `close_notes`,
  `duplicate_of_job_id` — powód należy do zamknięcia.

### Okno zamykania i „Zmień powód” (PR 2)

- Jedne pola wyboru (`components/v2/jobs/CloseReasonFields.tsx`) w trzech
  oknach: strona rekrutacji, krok „Umowa” i profil klienta (Projekty →
  „Zamknij”, dawne „Zamknij jako przegraną”). Słownik grup:
  `lib/job-close-reasons.ts` — lustro `metric_definitions`.
- Serwer (`services/job_close_choice.validate_close_choice`, wspólne dla
  zamknięcia i zmiany) odmawia 422 z `code`: `close_notes_required` (neutralny
  bez uzasadnienia), `close_reason_has_hire` (neutralny przy zatrudnieniu od
  nas), `close_reason_other_retired`, `duplicate_of_requires_duplicate`,
  `duplicate_of_self`, `duplicate_of_not_found`.
- `PATCH /api/jobs/{id}/close-reason` — ta sama bramka co zamknięcie, tylko
  zamknięta rekrutacja (409 `job_not_closed`), `closed_at` zostaje, wpis
  `close_reason_changed` z `from`/`to` w historii. W UI: „⋯” → „Zmień powód
  zamknięcia…”; plakietka powodu w nagłówku (`JobCloseReasonBadge`).
- Zamknięcie przez „Edytuj rekrutację” (PATCH `status=closed`) dalej nie ma
  powodu — liczy się jak przegrana i trafia do przeglądu (PR 3).
