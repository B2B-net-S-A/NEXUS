# Usuwanie klienta z profilu + Historia zdarzeń (migracja 0307)

Przycisk **„Usuń klienta"** w profilu klienta (dowolny status) i ogólnosystemowa
sekcja **Ustawienia → Historia zdarzeń**. Kod: `api/client_deletion.py`,
`services/client_deletion.py`, `services/critical_events.py`,
`api/event_history.py`; front: `components/client-profile/DeleteClientDialog.tsx`,
`components/settings/EventHistoryTab.tsx`. Pełny opis:
`docs/client-deletion-event-history-completion-report.md`.

- **Uprawnienie jest IMIENNE, nie rolowe:** `users.can_delete_clients`
  (domyślnie `false` dla wszystkich). Macierz akcji RBAC daje administratorowi
  każdą akcję automatycznie, więc nie da się nią wyrazić „tylko te cztery
  osoby" z ticketu — dlatego osobna flaga, której **admin też nie ma**, dopóki
  ktoś jej nie zaznaczy w edycji użytkownika („Może usuwać klientów").
  Nadanie i odebranie trafia do Historii zdarzeń. Osoby z ticketu NIE są
  zaszyte w kodzie ani migracji (repo jest publiczne) — flagę nadaje admin
  w Ustawieniach → Administracja. W trybie „podgląd jako" usuwanie jest
  zablokowane (403), a przycisk ukryty.
- **Nadane uprawnienie działa od następnego załadowania aplikacji, nie od
  ponownego logowania** (16.09.2026). Profil siedzi w `nexus_user`
  w localStorage i do tej daty odświeżał go WYŁĄCZNIE login: cztery osoby
  z ticketu dostały flagę i nadal nie widziały przycisku. `AppShellV2` raz na
  załadowanie dociąga `GET /api/auth/me` i wpisuje go przez `syncUser`
  (`store/auth.ts`) — bez tokena (strony publiczne) i w trybie podglądu nie
  strzela, przy identycznym profilu nie zapisuje (nowa referencja
  przerenderowałaby cały shell), a innego `user.id` niż zapamiętany nie
  przyjmuje. Dotyczy tak samo roli i `allowed_sections`, w obie strony:
  odebrane uprawnienie też znika bez wylogowania.
- **Router bez bramki ZAPISU Delivery** (`DELIVERY_SECTION_DEPENDENCIES`),
  tylko odczyt Delivery: flagę może dostać np. osoba z Finansów, a Finanse
  mają Delivery do odczytu. Stary `DELETE /api/clients/{id}` z `clients.py`
  (admin, jedno żądanie, kaskada, bez nagrobka) usunięty — trasa żyje teraz
  w `client_deletion.py` i wymaga `?confirmation=0`.
- **Blokada twarda patrzy na FAKTY, nie na `clients.status`:** otwarte
  zamówienia okresowe (`draft`/`active`/`paused`, także przez kontrakt
  klienta), otwarte zamówienia MD/kosztowe (`draft`/`active`/`scheduled`),
  żywe kontrakty (`active`/`ending`/`ready_for_signature`) i kandydaci
  w niezamkniętych rekrutacjach. Szkic kontraktu bez zamówienia NIE blokuje
  (to nie pracujący kontraktor). **Linie zamówień MD/kosztowych są sprawdzane
  SAME, niezależnie od statusu grupy** — zamknięcie z datą w przyszłości daje
  grupę `completed` z liniami nadal `active`, wyczerpanie puli przestawia
  wyłącznie grupę, a osoba obsadzona z bazy ma kontrakt-szkic, więc blokada
  kontraktorów by jej nie złapała. Kliknięcie „Usuń klienta" to już próba —
  zablokowana trafia do Historii zdarzeń; wykonanie liczy ocenę od nowa pod
  `FOR UPDATE` na wierszu klienta i przy blokadzie zwraca 409 jako
  `JSONResponse` (NIE `HTTPException` — wyjątek wycofałby sesję razem z wpisem).
- **Pusty vs z historią = ta sama ocena co czyszczenie 0303**
  (`evaluate_candidates` + `load_client_candidates` — dowolna zakładka, zakres
  portfela w KAŻDEJ kategorii to wpis katalogu). Werdykt `delete` → trwale,
  przez `purge_client(run=None)` z nagrobkiem (`purged_clients.run_id` jest od
  0307 NULL-owalne), znacznikiem w manifeście portfela i wszystkimi pułapkami
  z 0303. Każdy inny → **usunięcie z zachowaniem historii**: `deleted_at` +
  `archived_at`, wiersz zostaje (kontrakty, zamówienia, umowy nadal na niego
  wskazują). `visible_client_predicates` dostało `deleted_at IS NULL`, bo import
  portfela potrafi cofnąć `archived_at`. Zakresów portfela NIE archiwizujemy —
  inwariant manifestu liczy żywe zakresy.
- **`critical_events` nie ma żadnego FK** — wpis przeżywa usunięcie obiektu
  i konta (nazwy zdenormalizowane), a zapis zablokowanej próby z OSOBNEJ sesji
  (`record_blocked`) nigdy nie czeka na blokady trzymane przez odmawiające
  żądanie. Wykonane operacje idą do sesji operacji (`record_executed`, wspólny
  commit). `audited_deletion` owija istniejące DELETE-y: 403/409/422/423
  z wnętrza bloku = zablokowana próba, 404/5xx = nic.
- **Wpisy NIE niosą imion i nazwisk kontraktorów/kandydatów** — przeżywają
  usunięcie osoby (art. 17 RODO), a API nie pozwala ich edytować. Etykiety to
  numery: `Kontrakt #id`, `Zamówienie #id`, `Konsultant (linia #id) —
  zamówienie X`, `Umowa B2B {numer}`; zablokowana próba usunięcia klienta
  zapisuje rodzaj i liczbę blokad bez pozycji (okno pokazuje nazwiska na żywo).
  Nazwy firm i kont pracowników zostają.
- **Usunięty klient nie ma profilu ani zapisów:** `get_client`/`profile`,
  `_assert_client` w zamówieniach, grupach i umowach ramowych oraz lista
  Pomoc → Klienci odrzucają `deleted_at` — obok list filtrowanych predykatem.
  Odmowy „brak uprawnienia" są zapisywane raz na 10 min na osobę i klienta.
- **Na start w Historii:** usunięcie klienta, kandydata/kontraktora
  (`DELETE /api/candidates/{id}` — BEZ imienia i nazwiska, tylko `Kandydat #id`
  + pseudonim `subject_ref`, bo to usunięcie z art. 17), konsultanta
  z zamówienia MD/kosztowego, kontraktu (także wymuszone przy podpisanej B2B),
  umowy ramowej, wygenerowanej umowy B2B, zamówienia okresowego (anulowanie =
  wpis z opisem) i zamówienia MD/kosztowego, plus zmiany uprawnienia do
  usuwania. Nowa krytyczna operacja = `audited_deletion` / `record_executed` +
  etykieta w `EVENT_TYPE_LABELS`.
- **Odczyt:** `GET /api/settings/event-history` (`FinanceModuleUser` = Admin
  + Finanse), filtry obiekt/wynik/tekst/daty, stronicowanie. Brak API do
  edycji i kasowania wpisów — świadomie.
