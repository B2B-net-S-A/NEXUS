# „Cofnij zakończenie" i „Powrót po przerwie" (0368, 23.09.2026)

Zakończony kontrakt ma dwie osobne akcje (Admin, Finanse, TCM — bez DL;
bramka `ContractTerminationRecoveryUser` + wyjątek sekcji w
`section_access._is_contract_termination_recovery`). Zwykła zmiana statusu
„Zakończony → Aktywny" w rejestrze NIE przenosi się na zamówienia (zgłoszenie:
linia MD została w „Zakończonych" z decyzją o puli) — front ją przechwytuje.

- **Migawka stanu sprzed zakończenia** (`contract_termination_snapshots`,
  jeden OTWARTY wiersz na kontrakt) zapisuje `apply_contract_order_offboarding`
  — JEDYNE miejsce, które zmienia zamówienia przy zakończeniu. Stan kontraktu
  „przed" podaje wołający (`ContractStateBefore.of(contract)` PRZED mutacją);
  każda nowa ścieżka kończąca kontrakt musi go przekazać. Kolejne wywołania
  w epizodzie dopisują zamówienia i aktualizują stan „po", nigdy „przed".
  `reopen_contract` (przedłużenie/aneks) zamyka migawkę jako `superseded`;
  zmiana statusu z rejestru — nie (`supersede_termination_snapshot=False`).
- **Cofnięcie** (`services/contract_termination_reversal.py`): plan liczy ta
  sama funkcja dla podglądu i wykonania. Zamówienie zmienione po zakończeniu
  (stan ≠ „po") jest pomijane z powodem. Decyzja `remove`/`transfer` o puli MD
  = blokada 409 ze wskazaniem zamówienia. Nierozstrzygnięta sprawa
  offboardingu jest USUWANA (zostawiona blokowałaby nową sprawę przy
  ponownym zakończeniu z tą datą), jej alerty zamykane jako `resolved`.
  Zakończenia sprzed 0368: data końca z `order_change_events` („stara →
  data zakończenia"), a bez wpisu — data końca grupy; zamówienie okresowe bez
  śladu jest pomijane. Import MD: wiersze `unmatched` z tym nazwiskiem, wgrane
  po zakończeniu, za miesiące po dacie zakończenia — tą samą ścieżką co
  `assign_row` (`md_consumption.reapply_rows_for_restored_line`).
- **Powrót po przerwie** (`services/contract_return_after_break.py`): nowy
  kontrakt Draft z `returned_from_contract_id`; w otwartym zamówieniu MD/
  kosztowym szkic linii (`status=draft` w AKTYWNEJ grupie — karta pokazuje go
  w obsadzie jako „Draft — uzupełnij"; `update_line` aktywuje go, gdy ma
  stawkę przychodową i budżet), przy okresowym — szkic zamówienia.
- **Generator B2B idzie razem z kontraktem (0367):** cofnięcie woła
  `contract_termination_sync.undo_contract_termination` (umowa w Generatorze
  i dane rozwiązania umowy wracają), powrót po przerwie —
  `on_contract_returned_after_break` (nowa umowa dla nowego kontraktu).
- Korekta zgłoszenia: `contract_termination_reversal_repair.py` (trójka ID,
  blok `repair-termination-reversal` w entrypoincie, marker w `app_settings`).
