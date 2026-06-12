# Raport ukończenia — Generator Umów B2B: stawka ułamkowa (422) + reset numeracji

> Data: 2026-06-12 · Commit fixu: `3e675dc` · Zgłoszenie: 2 błędy na `/contracts/b2b-generator`

## Zgłoszenie

1. **422 przy generowaniu** — po uzupełnieniu szablonu i kliknięciu „Pobierz DOCX" /
   „Podgląd" pojawiał się `Request failed with status code 422`. Miało: umowa
   generuje się poprawnie.
2. **Reset numeracji** — w „Wygenerowane umowy" zebrały się testowe numery do
   skasowania; numeracja miała zacząć się od nowa.

## Przyczyna (422)

Pole „Stawka godz. (netto)" to `<input type="number">`, więc dla wartości jak
„135,5" przeglądarka wysyła float `135.5`. Schemat `B2BRenderRequest.rate_candidate`
był `Optional[int]`, a Pydantic v2 odrzuca liczbę z częścią ułamkową → **422**.
Stawki całkowite (np. `150`) przechodziły, każda ułamkowa zawsze padała.

## Zmiany (fix 422)

- `backend/app/schemas/b2b_contract_generator.py` — `B2BRenderRequest.rate_candidate`
  → `Optional[float]` (ścieżka standalone `/render`; `/generate` zostaje `int`, bo
  pisze do kolumny `Integer` na `Contract`).
- `backend/app/services/b2b_contract_generator/formatting.py` — `format_rate()`:
  wyświetlanie po polsku — `150` → „150", `135.5` → „135,50".
- `backend/app/services/b2b_contract_generator/render_context.py` — używa
  `format_rate()` dla kwoty; słownie liczone z wartości liczbowej.
- `backend/app/services/b2b_contract_generator/number_words.py` — `rate_in_words()`
  dolicza grosze, by słownie zgadzało się z kwotą (`135,50` → „sto trzydzieści
  pięć złotych pięćdziesiąt groszy") + deklinacja `grosz/grosze/groszy`.
- `frontend/src/components/v2/pages/B2BContractGeneratorV2.tsx` — defensywna
  normalizacja przecinek→kropka w stawce (payload + walidacja).
- `backend/tests/test_b2b_contract_generator.py` — +4 testy (grosze PL/EN,
  `format_rate`, regresja renderu ułamkowej stawki). Pełny plik: 29 passed.

## Reset numeracji (dane prod, jednorazowo)

Wybór użytkownika: **zostaw realną serię 1433–1436, skasuj testowe**.
`DELETE FROM b2b_generated_contracts WHERE year=2026 AND seq < 1433` → usunięto 7
testowych (1, 2, 3, 4, 9, 10, 11/2026), zachowano 4 realne (1433–1436/2026:
Nordea/BNP). Kolejny sugerowany numer = **1437/2026**.

## Weryfikacja (prod, SHA `3e675dc`)

- `/api/health` → `status: healthy`, `version: 3e675dc…`.
- `POST /api/b2b-generator/render?format=html` (auth, realna sesja):
  - `rate_candidate=135.5` → **200**: „stawki godzinowej w wysokości **135,50**
    PLN (słownie: **sto trzydzieści pięć złotych pięćdziesiąt groszy**) netto + VAT."
  - `rate_candidate=150` → **200**: „150 PLN (słownie: sto pięćdziesiąt złotych)".
- `GET /next-number` → `1437/2026`; `GET /generated` → 4 wiersze (1433–1436).
- UI (Chrome MCP): zakładka „Wygenerowane umowy" pokazuje tylko 1433–1436.

## Znane ograniczenia / out-of-scope

- Ścieżka `/generate` (draft `Contract` z profilu kandydata) nadal przyjmuje
  stawkę całkowitą — kolumna `Contract.rate_candidate` jest `Integer`. Obsługa
  ułamków tam wymagałaby migracji na `Numeric` (nie objęte tym zgłoszeniem;
  zgłoszony błąd dotyczył wyłącznie standalone generatora `/render`).
