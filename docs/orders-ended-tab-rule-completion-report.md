# Reguła zakładki „Zakończeni" — raport ukończenia

Data: 2026-09-03 · jeden PR na ticket · poprzedza go #1355 (zamówienia z maila co godzinę).

## Zgłoszenie

Osoby z zakończonym okresem zamówienia trafiały do „Zakończonych" niekonsekwentnie;
Piotr Klimczak (VeloBank, Contract 469) wylądował tam mimo aktywnej współpracy
i czekającego przedłużenia.

## Co było naprawdę (dane z produkcji, 03.09)

U VeloBanku 11 osób miało to samo zamówienie `3/07/2026/BL` (01.07 → 31.08).
Do „Zakończonych" trafiły dokładnie 4 (464, 465, 469, 470) — te, którym umowa
miała wpisaną datę końca 30.06 (u 469 wpis z 26.06, bez wypowiedzenia, brak
`terminated_at`). Pozostałe 7 miało umowę bezterminową i zostało w „Aktywnych".
Mechanizm: nocny `_promote_statuses` kończy umowę po `end_date`, a `end_date`
bywał przepisany z pierwszego okresu zamówienia; do tego wskrzeszenie kontraktu
żywym zamówieniem przepisywało do umowy datę końca ZAMÓWIENIA, więc po jej
upływie osoba wracała do „Zakończonych". W całej bazie klasa „zakończona bez
wypowiedzenia, a zamówienie trwało po dacie końca umowy" liczy 3 wiersze — wszystkie
VeloBank (465, 469, 470); na nowym zamówieniu `3/09/2026/BL` jest tylko Klimczak.

## Zmiany

- **Front (`lib/client-order-list.ts`)**: `contractClosed` (status końcowy ORAZ data
  końca umowy < dziś) i `lacksCurrentOrder`; `contractorMatchesPill` jest jedynym
  źródłem pigułek dla obu rejestrów (`OrdersAndContractsTab` deleguje). Karta
  kontraktora pokazuje „Brak aktywnego zamówienia".
- **Backend**: `update_contract` synchronizuje otwarte zamówienia do zmienionej daty
  końca umowy (`_sync_client_orders_to_contract_end`, wyłącznie skracanie, audyt
  `orders_synced_to_end_date`); `sync_contract_to_live_order` wskrzesza kontrakt jako
  bezterminowy (data z zamówienia idzie do `client_order_end_date`, gdy śledzony).
- **Dane**: migracja `0271_ended_tab_contract_repair` + lustro w `entrypoint.sh`
  (SQL w `services/contract_ended_tab_repair.py`): Contract 469 → `active`,
  `end_date NULL`, wpis `contract_reopened`; audyt klasy w
  `app_settings['0271_ended_tab_contract_repair']`.
- Instrukcja zamówień (moduł Pomoc) opisuje regułę; CLAUDE.md ma nową sekcję.

## Poza zakresem (świadomie)

- Baczewski (465) i Więckiewicz (470) zostają w „Zakończonych" — nie ma ich na nowym
  zamówieniu; wskrzeszenie wciągnęłoby ich do MRR i alertów. Administracja może
  zakończyć/odtworzyć ich umowy w Kontraktach.
- Contract 444 (Anna Gąsowska, klient 26): `ended` z `terminated_at` 30.09 w przyszłości
  i `end_date` 31.08 — niespójność sprzed tej zmiany, do przeglądu przez administrację.

## Weryfikacja

Backend: testy cyklu życia kontraktu i zamówień + nowe `test_contract_end_date_rule.py`
i `test_ended_tab_contract_repair_0271.py` (w tym wykonanie bloku SQL na bazie).
Front: `client-order-list.test.ts`, `OrdersAndContractsTab.test.tsx`, tsc, eslint.
