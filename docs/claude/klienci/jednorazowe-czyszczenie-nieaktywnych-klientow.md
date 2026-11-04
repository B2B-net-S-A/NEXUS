# Jednorazowe czyszczenie „Nieaktywnych klientów" (migracja 0303)

Admin w zakładce „Nieaktywni klienci" → **„Czyszczenie listy"**: podgląd
(tylko odczyt) → zgoda → wykonanie → raport. Trasy
`/api/clients/directory/inactive-cleanup` (+ `/preview`, `/execute`),
wszystkie `AdminUser`. Ocena: `services/inactive_client_cleanup.py` (czyta),
wykonanie i raport: `services/inactive_client_cleanup_run.py`. Pełny opis:
`docs/inactive-clients-cleanup-completion-report.md`.

- **Trzy werdykty.** Niepuste którekolwiek z 8 źródeł (rekrutacje aktywne/
  zamknięte, kontrakty `ended`, zamówienia wszystkich etapów + grupy +
  offboarding, kontrakty/umowy ramowe/B2B w dowolnym statusie,
  `clients.notes`, one-pagery + warunki umowy, przejścia pipeline'u i historia
  DynaReportera) → **zostaje bez zmian**. Osiem pustych, ale inne dane →
  **lista B** (wstrzymany, z opisem). Nic → **lista A** (usunięty trwale).
- **„Inne dane" NIE są listą ręczną** — każdy FK do `clients.id` jest czytany
  z `pg_catalog` w chwili uruchomienia, więc tabela dopisana w przyszłości nie
  zostanie cicho skaskadowana. Pomijane są tylko wpisy katalogu: zakres
  portfela, aliasy, wiersz audytu manifestu. Poza FK lista B łapie też:
  dziennik (`activities`) z akcją spoza technicznych (import manifestu,
  założenie, edycja, przesunięcie zakładki), zakres w innej zakładce, NDA,
  wskazanie klienta w env `*_CLIENT_IDS` i w stałych kodu (e-Zdrowie,
  Polkomtel, Wedel, Cyfrowy Polsat, kanoniczne ID polityk PDF), klienta
  zakładanego przy starcie („Ministerstwo Sprawiedliwości") oraz nazwę
  pasującą do wzorca zasiewu karty klienta (usunięcie duplikatu zmieniłoby
  licznik „dokładnie jeden" i następny start założyłby kartę komuś innemu).
  FK zadeklarowane w modelach, a nieobecne w bazie, są liczone mimo to.
- **Ślady PO NAZWIE** (`services/inactive_client_cleanup_signals.py`):
  `dr_clients` (DynaReporter ma WŁASNĄ tabelę klientów — MRR i placementy
  nie wskazują na `clients`), `dr_board_placement_clients`,
  `finance_monthly_results` i `b2b_generated_contracts` z pustym `client_id`
  (umowa wygenerowana bez rekrutacji) zatrzymują klienta; leady/oferty
  sprzedażowe DynaReportera → lista B. Klucz nazwy zdejmuje formy prawne —
  fałszywe trafienie może klienta tylko zatrzymać. Okres umowy przypięty do
  zakresu portfela (`contract_*_override`) liczy się jako umowa.
- **Pusta lista nie wykonuje niczego** (422) — inaczej zapis raportu bez
  usunięć zużyłby jednorazową operację przed rozstrzygnięciem listy B.
- **Usuwane jest wyłącznie przecięcie** listy zatwierdzonej w podglądzie
  z klientami, którzy w chwili wykonania NADAL się kwalifikują (blokada FOR
  UPDATE na wierszach klientów przed ponowną oceną). Kto zakwalifikował się po
  podglądzie, trafia na listę B — nikt go nie widział.
- **Jednorazowe:** UNIQUE(`client_cleanup_runs.kind`) + sprawdzenie pod
  blokadą doradczą → drugie wykonanie i podgląd po wykonaniu = 409. Nic
  w kodzie nie woła tego automatycznie.
- **Nagrobek jest load-bearing.** Faza `clients` syncu Traffita robi pełny
  skan co noc i upsertuje po `external_id`, więc bez `purged_clients` usunięty
  klient wracałby następnej nocy. `import_clients` pomija te id (`skipped`).
  `purged_clients.run_id` ma RESTRICT, nie CASCADE — skasowanie raportu nie
  może zdjąć nagrobków.
- **Manifest portfela:** usunięcie klienta zeruje (SET NULL) jego powiązanie
  w `client_import_rows`, a inwariant `get_client_portfolio_import_health`
  porównuje żywe zakresy z liczbą wierszy audytu. Stąd `purged_at` na wierszu
  (stawiany PRZED usunięciem) i `retained_audit_rows = audit_rows -
  purged_rows`. Bez tego każde usunięcie klienta z manifestu = `/api/health/
  deep` 503. Brak kolumny `purged_at` (lustro DDL przegrało blokadę) liczy
  się jako zero, nie wywraca `--apply-once` pod `set -e`.
- **Rollback zaaplikowanego manifestu jest po czyszczeniu niedostępny —
  świadomie.** Manifest ma wiersz audytu dla KAŻDEGO klienta (arkusz
  „NEXUS-only"), więc po usunięciu choćby jednego run ma wiersze `purged_at`
  i rollback odmawia (`rows_purged_by_inactive_client_cleanup`) zamiast
  przywracać stan klientów, których nie ma. Reconcile Traffita pokaże stały
  rozjazd liczby klientów o liczbę nagrobków (tylko raport).
- **Nowy manifest (nowy digest) odtworzyłby usuniętych klientów**, jeśli
  nadal ich wymienia — first-apply dopasowuje po nazwie i nie czyta nagrobków.
  Świadomie poza zakresem (to decyzja przy przygotowaniu nowego pliku).
