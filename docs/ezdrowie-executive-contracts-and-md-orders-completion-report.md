# Centrum e-Zdrowia — umowy wykonawcze i zamówienia MD (raport ukończenia, 16.09.2026)

Zakres: dwa tickety — „Struktura umów wykonawczych" (profil klienta 115) oraz
„Dane startowe zamówień MD" (3 umowy wykonawcze). Drugi odwoływał się do ticketu
funkcjonalnego, którego w repo nie było; jego zakres (zakres podstawowy/opcjonalny,
historia miesięczna ze statusem, tag „Zastąpiony") zrealizowano jako Fazę B.
Dane ze zgłoszeń (nazwiska, stawki) nie trafiają do repo — manifest importu jest
plikiem poza repozytorium. Poniżej przykłady ze zmyślonymi osobami.

## Faza A — struktura umów (tylko klient 115)

- Schemat (0312): `client_framework_contracts.project_part`, nowa tabela
  `client_executive_contracts`, `executive_contract_id` na `client_orders`
  i `client_order_groups`; zasiew 5 części i 3 umów wykonawczych z jednego
  źródła SQL (`app/services/ezdrowie_structure.py`), idempotentny, lustro
  w `entrypoint.sh`, sonda w `/api/health/deep`.
- API: `GET /api/clients/{id}/contract-structure`, `POST/PATCH …/executive-contracts`,
  `GET …/executive-contracts/review`, `POST …/executive-contracts/assignments`.
  Zamówienia (Flow A/B/PATCH) i karty MD przyjmują `executive_contract_id`;
  część umowy jest pochodna z umowy ramowej (`resolve_ezdrowie_assignment`).
- UI: sekcja „Struktura umów" na profilu (lista części, chipy umów, „Dodaj umowę
  wykonawczą" bez opuszczania profilu — nowa umowa ma status Aktywna), panel
  „Przypisania do przeglądu" (ręczne przypisanie każdego obecnego i planowanego
  konsultanta, brak preselekcji), filtr konsultantów po umowach wykonawczych
  pogrupowanych pod częściami (części bez umów widoczne, nieklikalne), tag z numerem
  umowy w tabeli, select umowy wykonawczej w czterech dialogach zamówień.

## Faza B — zamówienia MD (wszyscy klienci)

- `md_optional_total` (zakres opcjonalny) obok `md_total` (podstawowy);
  `md_remaining` liczy całość, zużycie wypełnia najpierw podstawę.
- Wpisy miesięczne per osoba ze statusem „Protokół"/„Zaakceptowany" i notatką:
  `GET/PUT/DELETE …/lines/{id}/consumptions[/{RRRR-MM}]`, dialog „Rozliczenia miesięczne".
- Zastępstwo: `replaces_order_id` ustawia `predecessor_order_id`; poprzednik pokazuje
  „Zastąpiony → następca". Sumy karty: reguła pozycji (zastąpiony wnosi zużycie,
  nie budżet); „Wykorzystano wartości umowy" z kwotami tylko dla ról z finansami.
- Eksport XLSX: kolumny zakresów i wykorzystania.

## Faza C — import danych startowych

`POST /api/admin/clients/{id}/ezdrowie-md-orders/import?dry_run=true|false`
z manifestem JSON (schemat `app/schemas/ezdrowie_md_seed.py`). Dry-run przechodzi
pełną ścieżką i kończy rollbackiem; raport pokazuje dopasowania osób
(`resolved | created | ambiguous | missing`), zużycie per linia, sumy grupy
i blokery. Apply z blokerem = 409 bez zapisu. Paragon w `app_settings` niesie
tylko liczniki i identyfikatory.

Przykładowy fragment manifestu (osoby zmyślone):

```json
{
  "client_id": 115,
  "supersede_order_ids": [1001, 1002],
  "groups": [{
    "executive_contract_number": "CeZ/242/2025",
    "order_number": "CeZ/242/2025",
    "start_date": "2025-12-01",
    "lines": [
      {"key": "a", "person": {"name": "Anna Testowa", "contract_id": 1},
       "base_md": 190, "optional_md": 170, "rate_cost": 700, "rate_revenue": 800,
       "start_date": "2025-12-01",
       "history": [{"month": "2025-12", "md": 20, "status": "protocol"}]},
      {"key": "p", "person": {"name": "Piotr Poprzedni", "create_if_missing": true,
       "contract": {"start_date": "2025-12-01", "end_date": "2025-12-31", "status": "ended"}},
       "base_md": 190, "optional_md": 170, "rate_cost": 500, "rate_revenue": 600,
       "start_date": "2025-12-01", "end_date": "2025-12-31", "line_status": "completed",
       "history": [{"month": "2025-12", "md": 4, "status": "protocol"}]},
      {"key": "n", "person": {"name": "Natalia Następczyni"}, "replaces_key": "p",
       "base_md": 190, "optional_md": 170, "rate_cost": 500, "rate_revenue": 600,
       "start_date": "2026-01-01", "history": []}
    ]
  }]
}
```

## Wykonanie na produkcji (Faza D — poza tym PR-em)

1. Deploy; `/api/health/deep` z sondą `client_executive_contracts`.
2. Profil klienta 115 → „Przypisania do przeglądu": ręczne przypisanie każdego
   obecnego konsultanta (w tym osoby spoza ticketu danych startowych).
3. Dry-run importu z manifestu (poza repo) → rozstrzygnięcie osób `ambiguous`
   (wskazanie `candidate_id`) → apply → zrzuty zakładki Zamówienia i Profilu.

## Testy

- Backend: `test_ezdrowie_structure_migration.py`, `test_ezdrowie_executive_contracts.py`,
  `test_ezdrowie_project_part.py`, `test_md_optional_scope.py`,
  `test_line_consumptions_api.py`, `test_ezdrowie_md_seed.py` + regresja
  zamówień MD (273 testy w zestawie szerokim).
- Frontend: nowe testy sekcji struktury, panelu przeglądu, filtra, dialogów,
  `MdScopeBars`, `LineMonthlyHistoryDialog`; pełny zestaw 1668 testów zielony;
  `type-check` czysty.

## Znane ograniczenia

- Kolumna „Zużycie zamówienia" w istniejącym eksporcie zamówień liczy
  `md_total + korekta − md_remaining`, więc dla linii z opcją zaniża o zakres
  opcjonalny — poprawna jest nowa kolumna „Wykorzystano (MD)"; do uporządkowania
  w `order_excel_export.py`.
- Wymóg umowy wykonawczej u klienta 115 obejmuje każdy typ karty (także kosztową).
- Przepięcie istniejącej karty MD pod inną umowę wykonawczą nie jest obsługiwane
  (tylko przy tworzeniu).
- Archiwum konsultantów nie pokazuje tagu umowy wykonawczej (jak dotąd części).
