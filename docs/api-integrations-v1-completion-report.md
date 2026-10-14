# API integracyjne v1 — raport ukończenia (PR 2A, 14.10.2026)

Decyzja Artura 14.10.2026: procesy firmy (na start rozliczanie klientów) podpina
się pod NEXUSA przez stabilne API dla automatyzacji. Dokumentacja dla integratora:
[`docs/api/integracje-v1.md`](api/integracje-v1.md). Reguły dla sesji:
`docs/claude/podstawy/konta-serwisowe-klucze-api-x-api-key.md`.

## Co weszło

| Część | Stan | Dowód |
|---|---|---|
| Fundament: scope'y rozliczeń, `X:write ⇒ X:read`, `/me`, `/openapi.json` (tylko v1), koperta błędu v1, limit per konto | gotowe | `app/api/integrations_v1/common.py`, `meta.py`; `tests/test_integrations_v1_contract.py` |
| Autor zapisu = konto serwisowe (`order_change_events.source='integration'`, `Activity.details.via`, Historia zdarzeń, log `actor`, tag Sentry) | gotowe | `services/integration_actor.py`, `order_change_audit.py`; `TestOrderChangeSource` |
| Idempotencja zapisów (`Idempotency-Key`, paragony 90 dni), `dry_run` | gotowe | `services/integration_receipts.py`; `TestInvoicesWrite`, `test_integrations_v1_transactions.py` |
| Odczyt: klienci, kontrakty (+historia stawek), zamówienia i grupy MD, zużycie MD, importy MD, Finanse (zmiany, PDF-y, ZIP, wyniki), faktury i DSO | gotowe | 25 tras GET; `TestReadScopes` |
| Zapis: import MD (409 na powtórzony plik), przypisanie wiersza, korekta MD za miesiąc, „Zrobione”, import wyników, faktury (create/patch/cancel) | gotowe | 9 tras; `TestMdImport`, `TestFinanceChecks`, `TestInvoicesWrite` |
| Kwoty tylko z `amounts:read` (zamówienia, kontrakty, wiersze importu MD) | gotowe | `TestAmountsScope`, `test_md_import_rows_hide_invoice_amounts_without_amounts_read` |
| Kwoty rozdzielone (PR 3, 14.10): `sales_amounts:read` = to, co płaci klient; koszty, marża, stawki konsultantów, faktury od kontraktorów i aneksy umów tylko z `amounts:read`; `costs_redacted` | gotowe | `test_integrations_v1_contract.py`, `TestAmountsScope` |
| Ekran „Ustawienia → Klucze API” | gotowe | `frontend/src/app/settings/api-keys/`, harness `/preview/api-keys`; vitest 431 passed |
| OAuth: mapa tras zależna od metody (+5 tras scraperów) | gotowe | `services/oauth_route_scopes.py`; `tests/test_oauth_route_scopes_methods.py` |
| Migracja 0443 + lustro `entrypoint.sh` | gotowe | `tests/test_entrypoint_order_change_source_mirror.py` |
| Pełne CI na gałęzi (Postgres) | zielone | runy 38569736633, 38571649108 |

Przeglądy przed PR-em (code review + security review) znalazły i naprawiono:
błąd trasy v1 robił COMMIT zamiast ROLLBACK (paragony `pending`, partie MD po
konflikcie), „Zrobione” zwracało 500, `md:read` pokazywał kwoty faktur z wierszy
importu, brak granic int4 w ciele faktury.

## Świadomie poza v1

- Kandydaci, rekrutacje, notatki (RODO); twarde usuwanie (faktura → `cancel`).
- Zatwierdzanie przekroczeń salda MD i przypisań do wspólnej puli — tylko ekran.
- Historia zamówienia MD (`/order-groups/{id}/history`) — zmiany dla rozliczeń daje
  audyt „Zmiany w zamówieniach”.
- Zapis zamówień i kontraktów — PR 2B (`WritePolicy`).
- Status „Pobrane” PDF-ów należy do ludzi — pobranie kluczem go nie zmienia.
- `PATCH /invoices/{id}` przyjmuje `pdf_document_id` bez sprawdzenia przynależności
  (tak samo jak ekran).

## Po wdrożeniu (19:00–07:00)

1. `/api/health` → `version` = SHA z maina.
2. Admin zakłada w „Klucze API” konto testowe (odczyt + `md:write`, termin 7 dni),
   `GET /api/integrations/v1/me`, `/orders?page_size=5`, `/finance/order-changes`,
   `POST /md/imports?dry_run=true` — potem odwołuje klucz.
3. `OAUTH_ROUTE_SCOPES_ENFORCE=true` workflowem „Coolify set env” dopiero, gdy logi
   `would_deny` z 7 dni są puste.
