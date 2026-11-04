# DL widzi tylko swoich klientów + scalenie E-Zdrowie — raport i przekazanie

Stan na 26.09.2026. Raport dla następnej sesji, która przejmie temat.

## Decyzje Artura (25.09.2026)

- W modułach Delivery Delivery Lead widzi tylko klientów, do których ma
  **dowolne** przypisanie w `delivery_lead_client_assignments` (główne albo
  nie). Chodzi o Klientów, Kontrakty, Zamówienia, skrzynkę zamówień z maila
  i portal „Moi klienci”.
- **Rekrutacje zostają otwarte dla wszystkich.**
- **Generator umów B2B zostaje jak był.** DL widzi wszystkie umowy, a stawki
  i zapis tylko u swoich klientów.
- Klienta E-Zdrowie (37721) scalamy z eZdrowie (115).

## Co zostało zrobione

| Część | Stan | Dowód |
|---|---|---|
| Przypisania DL na produkcji (tabela niżej) | zrobione 26.09 przez API aplikacji, jako admin | SQL: każdy z 5 klientów ma właściwego głównego DL |
| Kod zakresu DL (PR #1843, `9a8a942`) | wdrożone | `/api/health` → `e80bdb0`, `healthy` |
| Zakres na produkcji sprawdzony (tylko GET) | działa | tabela „Weryfikacja” niżej |
| E-Zdrowie: rekrutacje i kontrakt #668 → 115 | zrobione przy starcie backendu | paragon `app_settings['ezdrowie_client_merge_2026_09']`: 28 rekrutacji, kontrakt 668, 0 zablokowanych |
| E-Zdrowie: procesy rekrutacji (545 wierszy) | PR #1851 w kolejce merge'ów | patrz „Do zrobienia” pkt 1 |
| Test kalendarza padający 00:00–01:12 | naprawiony w #1843 | zegar testu przypięty na południe |

Przypisania zmienione na prośbę Artura:

| Klient (id) | Główny DL |
|---|---|
| ALIOR BANK (39) | Rafal Urban (81); Klaudia Uliasz usunięta |
| Bank Pekao SA (3) | Rafal Urban (81) |
| MS Enter Price (61) | Klaudia Uliasz (30) |
| CARDIF – Assurances Risques Divers (38335) | Klaudia Uliasz (30) |
| VIP Solution (62) | Klaudia Uliasz (30) |

Weryfikacja na produkcji 26.09, tokeny DL zmintowane w kontenerze, same GET-y:

| Sprawdzenie | Klaudia | Rafał |
|---|---|---|
| `/api/auth/me` → `delivery_client_scope` | `assigned` | `assigned` |
| `/api/my-clients` (liczba klientów) | 18 | 13 |
| `GET /api/clients/39` (Alior) | 403 | 200 |
| Kontrakty Aliora | 0 | 14 |
| Rekrutacje Aliora (`/api/jobs?client_id=39`) | 102 | 102 |
| `GET /api/clients/39/team` | 200 | 200 |

## Jak to działa (skrót — pełny opis w CLAUDE.md)

- **Resolvery:**
  - `access_scope.resolve_delivery_lead_client_ids` to zakres Delivery,
    czyli klienci z przypisania;
  - `resolve_delivery_lead_org_client_ids` to wszyscy klienci, dla ekranów
    rekrutacji;
  - `client_access.resolve_client_team_client_ids / resolve_client_visible_client_ids
    / resolve_client_access` przyjmują `purpose="delivery"|"org"`; domyślnie
    `delivery`, czyli wariant zawężający.
- **Bramka routera:** `app/api/delivery_client_scope.py`
  (`require_delivery_client_path_scope`) czyta `client_id` z adresu. Siedzi
  na routerach zamówień, grup, importów MD, umów ramowych i wykonawczych,
  aneksów, materiałów i wiedzy.
- **Org-wide zostają:**
  - rekomendacje, prep-kit, szablony maili, akcje shortlisty;
  - reguły i generator CV, zapis karty klienta;
  - `GET /api/clients/{id}/team`, `/api/clients-lookup`;
  - generator B2B (`purpose="org"`);
  - pulpity, KPI i Insights (`resolve_dashboard_scope` bez zmian).
- **Wyjątki:** DL z rolą admin, finance albo talent_community_manager widzi
  wszystkich klientów.
- **Wyłącznik bez deployu:** `DL_CLIENT_SCOPE=all` w Coolify, ustawiany
  workflow „Coolify set env”.
- **Front:** `/api/auth/me` niesie `delivery_client_scope`. Przy `assigned`
  lista klientów nie pokazuje przełącznika „Moi / Wszyscy”, a profil cudzego
  klienta przy 403 pisze „Ten klient jest poza Twoim portfelem”.
- **Traffit:** `_build_client_external_id_map` podąża za
  `merged_into_client_id`. Wiersz 37721 zostaje jako ukryty nagrobek
  z `external_id='150'` — **nie kasować go**, bo to on kieruje Traffita na
  115.
- **Testy:** `backend/tests/test_dl_client_scope.py`,
  `backend/tests/test_ezdrowie_client_merge_repair.py`.

## Do zrobienia

1. **Domknąć PR #1851** (procesy rekrutacji E-Zdrowie).
   - Stan: jest w kolejce merge'ów, auto-merge włączony.
   - Po wdrożeniu (`/api/health` → SHA z maina zawierający #1851) sprawdzić
     SQL-em tylko do odczytu:
     `SELECT count(*) FROM recruitment_processes WHERE client_id=37721` = 0.
   - Paragon: `app_settings['ezdrowie_client_merge_2026_09_processes']`,
     oczekiwane `processes_moved` ≈ 545.
   - Deploye stoją w nocy 0–7 (`DEPLOY_FREEZE_WINDOW`). Poranny cron bywa
     opóźniony o kilka godzin; wtedy wolno odpalić ręcznie „Run workflow”
     na Deploy.
2. **Sprawdzić po nocnym imporcie Traffita**, że nic nowego nie przypięło się
   do 37721:
   `SELECT count(*) FROM jobs WHERE client_id=37721` (i to samo dla
   `contacts`) = 0. Jeśli jest > 0, mapa klientów w imporcie nie podąża za
   scaleniem — zacznij od `traffit/importer.py::_canonical_client_id`.
3. **Zamówienie kontraktu #668 u eZdrowie (115) nie ma umowy wykonawczej.**
   - U CeZ jest to wymagane.
   - Zrobić ma Rafał Urban: profil klienta → „Nieprzypisani”. Albo przekazać
     mu to zadanie.
4. **Dominik Zwierzchowski (konto nieaktywne) nadal jest przypisany do
   Nordei** jako drugi DL. Do usunięcia w Ustawieniach → Zespół i dostęp →
   „Kto prowadzi którego klienta”. Najpierw potwierdzić z Arturem, bo nie było
   w poleceniu.
5. **Klienci bez żadnego DL** widzą ich teraz tylko admin i Finanse.
   Z kontraktami został jedynie „Przetarg” (0 aktywnych). Na liście może być
   więcej klientów bez kontraktów, np. rekordy z Traffita. Zapytanie
   kontrolne:
   `SELECT c.id, c.name FROM clients c WHERE c.deleted_at IS NULL AND c.merged_into_client_id IS NULL AND NOT EXISTS (SELECT 1 FROM delivery_lead_client_assignments a WHERE a.client_id=c.id) AND EXISTS (SELECT 1 FROM contracts k WHERE k.client_id=c.id AND k.status::text <> 'void');`
6. **Znane odstępstwa, świadomie zostawione:**
   - DL z dodatkową rolą TAC nie dostaje w zakresie Delivery klientów
     z `ClientTacAssignment`, bo funkcja TAC jest wyłączona.
   - `GET /api/clients/{id}` dla nieistniejącego id zwraca DL-owi 403,
     a nie 404.
   - 5 procesów rekrutacji ma kopię klienta 157 przy rekrutacji klienta 18.
     To starszy rozjazd, niezwiązany z tą zmianą.
7. **Jeśli ktoś zgłosi, że „DL coś zniknęło”:**
   - Najpierw sprawdzić przypisanie klienta.
   - Potem sprawdzić, czy ekran nie jest rekrutacyjny i nie powinien iść
     przez `purpose="org"` / `resolve_delivery_lead_org_client_ids`.
   - Awaryjnie przełączyć `DL_CLIENT_SCOPE=all`.

## Dostęp dla następnej sesji

- SQL tylko do odczytu na produkcji i tokeny do GET-ów: pamięć
  `nexus-prod-readonly-audit-access`.
  - SSH przez klucz `~/.ssh/nexus_prod_root_ed25519`.
  - Tryb tylko do odczytu wymusza `SET default_transaction_read_only = on`.
- Przypisania DL przez API: `POST/DELETE /api/team-structure/dl-clients`
  (`HeadOfRecruitmentPlus`). Zapis na produkcji wymaga wyraźnej zgody Artura.
