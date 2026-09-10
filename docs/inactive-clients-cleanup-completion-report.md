# Klienci → „Nieaktywni klienci" — jednorazowe czyszczenie listy

Ticket: usunąć z zakładki „Nieaktywni klienci" wyłącznie klientów bez żadnego
śladu współpracy; klientów z innymi powiązanymi danymi wstrzymać do decyzji
ręcznej; po operacji udostępnić listę usuniętych (A) i wstrzymanych (B).

## Jak to uruchomić

1. Admin → Klienci → zakładka **Nieaktywni klienci** → **Czyszczenie listy**.
2. Okno pokazuje **podgląd** (nic nie jest zmieniane): „Do trwałego
   usunięcia", „Wstrzymani — do decyzji ręcznej" z opisem powiązań oraz
   zwiniętą listę „Zostają bez zmian" z rozbiciem po źródłach.
3. Zaznaczenie zgody odblokowuje **„Usuń trwale (N)"**.
4. Po wykonaniu to samo okno pokazuje **raport**: Lista A i Lista B. Ponowne
   otwarcie przycisku zawsze pokazuje raport; drugiego uruchomienia nie ma.

## Reguła decyzji

| Werdykt | Warunek | Skutek |
|---|---|---|
| Zostaje | którekolwiek z 8 źródeł niepuste | brak zmian |
| Lista B | 8 źródeł pustych, ale są inne powiązane dane | brak zmian, opis w raporcie |
| Lista A | nic | trwałe usunięcie + nagrobek |

Mapowanie 8 źródeł na dane:

| Źródło z ticketu | Dane |
|---|---|
| Aktywne projekty | `jobs` o statusie ≠ `closed` |
| Zamknięte projekty | `jobs` o statusie `closed` |
| Archiwalni konsultanci | `contracts` o statusie `ended` |
| Zamówienia (wszystkie etapy) | `client_orders`, `client_order_groups`, `client_order_offboarding_cases` |
| Umowy / kontrakty (dowolny status) | `contracts`, `client_framework_contracts`, `b2b_generated_contracts` (+ zdarzenia) |
| Notatki w profilu | `clients.notes` niepuste |
| Materiały sprzedażowe | `client_one_pagers`, `client_contract_terms` |
| Statystyki współpracy | przejścia `candidate_stages` na rekrutacjach klienta, `dr_clients`, `dr_placement_details` |

„Inne powiązane dane" (lista B) to:

- **każdy klucz obcy do `clients.id`** spoza powyższych tabel — czytany
  z `pg_catalog` w chwili uruchomienia (kontakty, przypisania TAC/DL, reguła
  CV, karta klienta, wiedza o kliencie, cenniki, alerty DL, wygenerowane CV,
  procesy rekrutacyjne, scalone duplikaty…), z opisem skutku usunięcia
  (`zostałyby usunięte razem z klientem` / `straciłyby powiązanie` /
  `blokują usunięcie`);
- wpisy **dziennika aktywności** klienta z akcją inną niż techniczna
  (import manifestu, założenie, edycja, przesunięcie między zakładkami) —
  np. „usunięcie one-pagera" dowodzi, że materiały kiedyś istniały;
- **zakres w innej zakładce** (Aktywni/Relacyjni) — usunięcie klienta
  zabrałoby go i stamtąd;
- **NDA podpisane**;
- klient wskazany w **konfiguracji** (`*_CLIENT_IDS` w env Coolify).

Pomijane jako „wpis w katalogu", nie dane o współpracy: zakres portfela,
aliasy nazwy, wiersz audytu manifestu portfela.

## Zabezpieczenia

- **Usuwane jest tylko przecięcie** listy zatwierdzonej w podglądzie
  z klientami, którzy nadal się kwalifikują. Wiersze klientów są blokowane
  (`FOR UPDATE`) przed ponowną oceną, więc równoległe dodanie rekrutacji czy
  kontaktu czeka albo zmienia werdykt. Klient zakwalifikowany dopiero po
  podglądzie → lista B („nie był zatwierdzony").
- **Jednorazowość**: `UNIQUE(client_cleanup_runs.kind)` + blokada doradcza;
  drugie wykonanie i podgląd po wykonaniu → 409.
- **SAVEPOINT na klienta** — nieudane usunięcie jednego trafia na listę B
  („Usunięcie nie powiodło się"), reszta idzie dalej.
- **Nagrobek** (`purged_clients`) — nocny pełny skan Traffita pomija te
  `external_id`, więc usunięty klient nie wraca.
- **Manifest portfela** — przed usunięciem wiersze audytu dostają
  `purged_at`/`purged_client_id`; inwariant zdrowia odejmuje je od liczby
  wymaganych żywych zakresów. `/api/health/deep` zostaje zielony. Rollback
  manifestu odmawia przy oznaczonych wierszach.
- **Dziennik**: każde usunięcie zapisuje `Activity(action="purged_inactive_cleanup")`,
  a `purged_clients.snapshot` trzyma zakresy, aliasy i akcje dziennika z chwili
  usunięcia.

## Pliki

- Backend: `app/services/inactive_client_cleanup.py`,
  `app/services/inactive_client_cleanup_run.py`,
  `app/api/client_inactive_cleanup.py`, `app/schemas/client_cleanup.py`,
  `app/models/client_cleanup.py`; zmiany w `client_portfolio_import.py`
  (inwariant + rollback), `traffit/importer.py` (nagrobek), `main.py`
  (router + sondy deep-health), `models/client_directory.py` (2 kolumny).
- Migracja `0303_inactive_client_cleanup` + lustro DDL w `entrypoint.sh`.
- Frontend: `components/clients/InactiveClientsCleanupDialog.tsx`, przycisk
  w `ClientsListV2.tsx`, API w `lib/api.ts`, harness
  `/preview/inactive-clients-cleanup` (publiczny, zero zapytań).
- Testy: `tests/test_inactive_client_cleanup.py` (7, żywa baza, w tym API,
  jednorazowość, nagrobek Traffita), `tests/test_client_portfolio_apply_once.py`
  (inwariant z oznaczonymi wierszami), vitest dialogu (3).

## Znane ograniczenia

- Lista B zostaje w zakładce do decyzji człowieka — to wymóg ticketu
  (pkt 3), więc po operacji w zakładce mogą być klienci bez śladu
  współpracy, ale z innymi danymi. Raport mówi, czego dotyczą.
- Nowy plik manifestu portfela (nowy digest), który nadal wymienia
  usuniętego klienta, założyłby go ponownie przy first-apply (dopasowanie po
  nazwie nie czyta nagrobków).
- Rekrutacja założona w Traffit dla usuniętego klienta trafi do
  technicznego „klienta-sieroty" (standardowe zachowanie importu).
