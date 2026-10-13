# Zamknięcie rekrutacji ostrzega o osobach w toku (13.10.2026)

<!-- indeks: 409 `active_cards_warning` z `POST /api/jobs/{id}/close`, potwierdzenie `acknowledge_active_cards`, oba okna zamykania, czego ostrzeżenie nie robi -->

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
- **Sprawdza trasa, nie `close_job_core`.** Automaty (domknięcie starych
  szkiców, scalenie duplikatów, archiwum Traffita) zamykają bez pytania —
  nie ma tam człowieka, który mógłby potwierdzić.
- **Oba okna zamykania** („Zamknij rekrutację z powodem” na stronie rekrutacji
  i „Zamknij jako przegraną” w profilu klienta) pokazują zdanie z serwera,
  liczby per kolumna (`lib/job-close.ts`, wspólne `ActiveCardsNotice`) i zmieniają
  przycisk na „Zamknij mimo to”. Nowe okno wołające tę trasę robi to samo —
  inaczej użytkownik dostanie sam toast z odmową i nie zamknie rekrutacji.
- **Ostrzeżenie niczego nie robi z kartami.** Nie odrzuca osób i nie przenosi
  ich do innej rekrutacji; przeniesienie przy duplikacie requestu to osobne
  narzędzie scalania (`integracje/przeniesienie-rekrutacji-z-traffita-falami.md`).
