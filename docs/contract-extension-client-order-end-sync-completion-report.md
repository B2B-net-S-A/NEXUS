[← docs index](./README.md)

# Contract extension — sync „Koniec zamówienia u klienta"

> PR [#636](https://github.com/artur-t-96/Nexus/pull/636) · 2026-07-02

## Problem (zgłoszenie)

W **Kontrakty → Aneksy → „Przedłuż"** po wprowadzeniu nowej daty końca okresu pole
**„Koniec zamówienia u klienta"** nie aktualizowało się. Przykład ze zgłoszenia:
okres przedłużony do `30.09.2026`, a „Koniec zamówienia u klienta" dalej pokazywał
`30.06.2026`.

**Oczekiwane:** po przedłużeniu kontraktu pole „Koniec zamówienia u klienta"
automatycznie ustawia się na nową datę końca okresu.

## Przyczyna

`create_contract_amendment` (typ `extension`) ustawiał tylko `contract.end_date` i
nigdy nie dotykał `contract.client_order_end_date`. To dwa odrębne pola modelu:

- `end_date` → „Okres" (koniec umowy z kontraktorem),
- `client_order_end_date` → „Koniec zamówienia u klienta" (koniec zamówienia PO po
  stronie klienta; z założenia bywa wcześniejszy niż koniec umowy).

Ten sam błąd dotyczył drugiej ścieżki przedłużania — przycisku **„Extend +N mc"** w
profilu klienta (`POST /api/contracts/bulk-extend`).

## Rozwiązanie

Przedłużenie kontraktu = klient odnowił zamówienie, więc „Koniec zamówienia u
klienta" podąża teraz za nową datą końca okresu.

- **Wspólny helper** `_synced_client_order_end(current, new_end_date)` w
  `backend/app/api/contracts.py` — jedna reguła, dwa miejsca użycia.
- Użyty w `create_contract_amendment` (gałąź `extension`) **oraz** w
  `bulk_extend_contracts`.
- **Guard na `None`:** kontrakty bez śledzonego końca zamówienia
  (`client_order_end_date is None`, na profilu „—") zostają nietknięte — nie
  wymyślamy daty tam, gdzie użytkownik świadomie jej nie podał.
- Zmiana odnotowana w **audycie aneksu** (`old_values`/`new_values`) → widoczna w
  karcie „Przed/Po".
- **Bez zmian we froncie** — pole wyprowadzane po stronie serwera; zakładka aneksów
  już inwaliduje `["contract", id]`, więc panel „Informacje o kontrakcie" odświeża
  się automatycznie.

## Zmienione pliki

| Plik | Zmiana |
|---|---|
| `backend/app/api/contracts.py` | helper `_synced_client_order_end` + sync w `extension` i `bulk-extend` + `client_order_end_date` w `old_values` |
| `backend/tests/test_contract_amendments.py` | 2 pure unit testy (reguła + guard `None`) + 2 integracyjne (sync / pozostaje `None`) + import helpera |
| `.github/workflows/ci.yml` | dopisany `tests/test_contract_amendments.py` do listy pytest (żeby pure unit testy realnie się wykonały) |

## Testy

- **Pure unit** (`test_synced_client_order_end_*`) — reguła sync + guard `None`;
  wykonują się w CI (plik dopisany do `ci.yml`).
- **Integracyjne** (in-process, no-op bez seed data): pełny flow aneksu `extension`
  → pole = nowa data + wpis w audycie; oraz przypadek nietkniętego `None`.
- Lokalnie: `ruff check app/` ✅, `ruff format --check app/api/contracts.py` ✅,
  `py_compile` ✅. Backend pytest waliduje CI (brak lokalnego venv w worktree —
  zgodnie z konwencją repo).

## Weryfikacja po merge

Kontrakt → Aneksy → „Przedłuż" → ustaw nową datę zakończenia → panel „Informacje o
kontrakcie": „Okres" i „Koniec zamówienia u klienta" pokazują tę samą, nową datę.

## Znane ograniczenia / świadome decyzje

- `bulk-extend` naprawiony razem z aneksem (ta sama logiczna operacja „przedłuż
  kontrakt") — świadomie w zakresie, żeby błąd nie wracał drugą ścieżką.
- Sync jest literalny (`client_order_end_date = new_end_date`), zgodnie ze
  zgłoszeniem. Kontrakty z celowo rozjechanym końcem zamówienia (mające już
  wypełnioną datę) też zostaną zrównane — to zachowanie oczekiwane przy
  przedłużeniu. Kontrakty bez daty (`None`) pozostają bez zmian.
