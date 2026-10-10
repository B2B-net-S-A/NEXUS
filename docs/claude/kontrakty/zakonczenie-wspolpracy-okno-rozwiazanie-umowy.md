# Zakończenie współpracy = okno + rozwiązanie umowy + Generator (0367, 23.09.2026)

Ticket „Zakończenie współpracy — obowiązkowy formularz” (kontrakt #674:
lista statusu kończyła kontrakt bez powodu i daty). Serwis
`app/services/contract_termination_sync.py`, okno
`components/contracts/ContractTerminationDialog.tsx` (jedno dla karty
kontraktu, formularza edycji, „Zakończ wcześniej” w aneksach, karty
kontraktora na profilu klienta, listy kontraktorów i zbiorczego „Oznacz
zakończone”), logika `lib/contract-termination.ts`.

- **„Zakończony” wyłącznie przez `/terminate` albo `/bulk-mark-ended`.**
  `PATCH /status` i `PATCH /{id}` z `ended` na istniejącej umowie = 409
  `termination_required`; wyjątek `allow_direct_end` ma tylko POST (wpis
  umowy zakończonej przed założeniem rekordu). `/terminate` ma role
  `ContractStatusWriteUser` (admin, DL, TCM) — te same co lista statusu.
- **Status liczy DATA ZAKOŃCZENIA PROJEKTU** (`_status_after_termination`):
  data ≥ dziś → „Kończący się”, < dziś → „Zakończony” od razu, nocny
  `_promote_statuses` przestawia dzień po dacie i zapisuje `Activity`
  `status_auto_changed`. Ostatni dzień UMOWY statusu nie wydłuża — nie ma
  statusu „W wypowiedzeniu”.
- **Rozwiązanie umowy** = `contracts.agreement_termination_*` +
  `agreement_last_day` (komplet albo nic, CHECK). Odznaczone pole w oknie
  CZYŚCI zapisane wcześniej dane. `notice_period_months` (edycja kontraktu)
  podpowiada ostatni dzień przy wypowiedzeniu; brak = puste pole. Załącznik
  idzie DRUGIM żądaniem do dokumentów kontraktu (`termination_notice` /
  `termination_agreement`) — padnięty upload nie cofa zakończenia.
- **Generator zmienia się w chwili „Zakończony”**, nie przy zapisie okna:
  rozwiązanie → `closed`, `closure_date` = ostatni dzień umowy,
  `project_end_date` = koniec projektu, `termination_mode`; bez rozwiązania →
  `suspended` („Umowy bez projektu”), chyba że osoba ma inny trwający
  kontrakt (`active`/`ending`) — wtedy umowa bez zmian. Wiersz szukany po
  `contract_id`, zapasowo po kandydacie (bez linku albo z linkiem do
  kontraktu `ended`/`void`, nigdy do innego żywego). Powód projektu mapuje
  `_CLOSURE_REASON` na katalog Generatora. Idempotentne po
  `termination_restore` (migawka stanu sprzed zmiany + `contract_id`).
- **„Cofnij zakończenie” = `reopen_contract`** (lista statusu na „Aktywny”,
  aneks przedłużenia, `/bulk-extend`): odtwarza wiersz z migawki, czyści dane
  rozwiązania na kontrakcie, załącznik zostaje. `reopen_contract(...,
  after_break=True)` woła wyłącznie `sync_contract_to_live_order` (nowe
  zamówienie wskrzesza kontrakt = powrót po przerwie): przy ROZWIĄZANEJ
  umowie zakłada nową umowę `in_progress` z `previous_generated_contract_id`
  (numer z `_next_seq`), poprzednia zostaje w „Zakończonych”. Lista statusu
  przy powrocie na „Aktywny” zeruje datę końca umowy B2B (lustro PATCH-a) —
  inaczej cron kończyłby ją ponownie w nocy.
- Historia umowy: `b2b_generated_contract_status_events.details` (źródło,
  kontrakt, daty, tryb, strona); „Zakończone umowy” mają kolumny „Data
  zakończenia zamówienia”, „Tryb” i filtr `?termination_mode=`.
