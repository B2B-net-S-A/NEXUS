# Przedłużenie zamówienia wskrzesza zakończony kontrakt

`POST /clients/{id}/orders` to TRZECIA ścieżka przedłużania współpracy i do
sierpnia 2026 jedyna, która nie dotykała statusu kontraktu (aneks
i `/bulk-extend` wołają `reopen_contract`). Skutek: przedłużenie dodane
kontraktorowi z zakładki „Zakończeni” zostawiało go tam, bo pigułki czytają
`contract_status` — i razem z pigułką milczały MRR, rejestr umów i skaner
wygasania.

Reguła żyje w `contract_lifecycle.sync_contract_to_live_order` i zależy
WYŁĄCZNIE od dat, nie od zakładki: zamówienie obejmujące dziś (`start <= dziś`
i `end IS NULL OR end >= dziś`) wskrzesza kontrakt, przyszłe nie zmienia nic,
`draft`/`cancelled` nie liczą się wcale. **Wskrzeszony kontrakt jest
BEZTERMINOWY** (od 09.2026; do tego czasu dostawał datę końca zamówienia,
a gdy jej okres mijał, cron kończył umowę ponownie — patrz sekcja o zakładce
„Zakończeni"). Nocny `_promote_statuses` pomija `end_date IS NULL`, więc nie
demotuje go „tej samej nocy". Data z zamówienia ma swoje miejsce w „Końcu
zamówienia u klienta" (`client_order_end_date` — od 09.2026 okres zamówienia zawsze z najnowszego uzupełnionego zamówienia, patrz „Synchronizacja kontrakt ↔ zamówienia"). Historię
leczy migracja `0243` (reguła ogólna, zero ID w SQL-u).

**Każdy writer aktywnego zamówienia musi wołać tę samą regułę.** Po 0243
zostały pominięte: PATCH uzupełniający draft, import CSV Nordea oraz aktywne
linie grupowe (create/add/swap i materializacja `scheduled`). Skutek wrócił dla
Contract 327/order 285493 i Contract 165/order 285623. Runtime obsługuje teraz
wszystkie te ścieżki; migracja `0250` koryguje dwa jawnie wskazane rekordy po
pełnych kluczach biznesowych i zapisuje read-only audyt analogicznych przypadków
innych klientów w `app_settings['0250_live_order_contract_repair']`.
