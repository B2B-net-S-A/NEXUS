# Sharding pytest w CI: 3 osobne runnery, ~22 min → cel ~10 min — completion report

Data: 2026-08-08 · Branch: `ci/pytest-sharding-3x`

## Cel

Pełny pytest backendu (4792 testy, ~22 min 20 s) to wąskie gardło taktu
merge-traina: pod `strict=true` PR-y lądują ~1 na okno CI. Podział na 3 shardy
ma zbić okno do ~10 min (7-8 min pytest + ~2,5 min setup), czyli ~2× szybszy
takt wprowadzania PR-ów.

## Dlaczego shardy na osobne runnery zadziałają tam, gdzie xdist poległ

xdist (wdrożony i wycofany, PR #1063; gałąź `xdist-per-worker-db-wip`) padł na
dwóch rzeczach: (1) równolegli workerzy piszący do WSPÓLNEJ bazy psuli ~25
plików porównujących globalne agregaty (`COUNT(*)` przed/po), (2) runner ma
4 vCPU dzielone między workery i postgres, więc zysk był ledwie 1,47×.

Sharding nie ma żadnego z tych problemów **z konstrukcji**: każdy shard to
osobna maszyna z własnym postgresem i **sekwencyjnym** pytestem — semantyka
identyczna z dzisiejszym CI, po prostu mniej plików na proces. Nie istnieje
współbieżny writer do tej samej bazy; skalowanie ściany jest ~liniowe, bo
każdy shard dostaje własne 4 vCPU.

## Jak działa podział

`backend/tests/conftest.py::_apply_ci_shard_filter` (wywoływany z istniejącego
`pytest_collection_modifyitems`):

- **Sterowany wyłącznie env** `CI_SHARD_COUNT` / `CI_SHARD_INDEX` (ustawia
  matrix w ci.yml). Bez nich — twardy no-op: lokalny `pytest tests/` działa
  jak dotąd.
- **Dzieli CAŁE pliki** (nie pojedyncze testy) — testy wewnątrz pliku bywają
  zależne od kolejności (historia #952).
- **Round-robin po posortowanej liście plików**: każdy shard liczy identyczną
  listę i bierze pozycje `pos % count == index`. Partycja jest zupełna
  i rozłączna **z konstrukcji** (ta sama lista + modulo), bez koordynacji
  między jobami — nie da się „zgubić" pliku, co było historyczną klasą błędu
  (CI 137/263 plików do #848).
- Pusty shard / zły index → `pytest.UsageError` (jawna czerwień, nie cichy
  sukces). Każdy shard loguje `[ci-shard] shard N/3: X plików, Y testów`.

## Zmiany w ci.yml

- Job `backend-lint-test` dostał `strategy.matrix.shard: [0,1,2]`
  (`fail-fast: false` — padnięty shard nie ubija reszty) i nazwę
  `Backend (pytest, shard N)`.
- **Komenda pytest NIETKNIĘTA** — kontrakt pokrycia
  (`test_ci_coverage_contract.py`) parsuje step po literalnej nazwie
  `Pytest (unit + in-process integration)` i liście `--ignore=`; zweryfikowane
  lokalnie importem parsera: step znaleziony, `pytest tests/` obecne,
  25 ignorów, zero wyenumerowanych ścieżek.
- **Nowy job zbiorczy `backend-pytest-gate` o nazwie `Backend (pytest)`** —
  branch protection wymaga kontekstu o dokładnie tej nazwie; shardy matrixowe
  raportują się inaczej, więc bez fan-ina każdy PR zawisłby na zawsze.
  `if: always()` jest load-bearing: anulowane shardy dają jawną czerwień,
  nie wieczne „oczekiwanie". Zielony ⇔ wszystkie shardy zielone.
- Codecov: upload per shard (`backend-coverage-shard-N`), ta sama flaga
  `backend` — Codecov scala raporty per commit, pokrycie łączne bez zmian.

## Czego się spodziewać / ryzyka

- **Balans czasowy**: round-robin po plikach nie gwarantuje równych czasów.
  Pierwszy przebieg CI na tym PR-ze da realne czasy shardów; jeśli najgorszy
  >12 min, korekta = `shard: [0,1,2,3]` + `CI_SHARD_COUNT: "4"` (2 linie).
- **Rezydualne sprzężenia między plikami**: #952 naprawił znane wzorce
  (globalny ALIAS_MAP, listingi >100 wierszy, sztywne id), ale shard = świeża
  baza z mniejszą liczbą „sąsiadów". Jeśli jakiś test padnie w shardzie,
  a przechodzi w pełnym przebiegu — to realny bug sprzężenia do naprawy wg
  katalogu z #952, nie powód do rollbacku shardingu.
- **Minuty GHA**: +2× setup (~5 min runner-time na przebieg CI) — pomijalne
  wobec 3000 min/mc.

## Weryfikacja

- [x] `yaml.safe_load` na ci.yml
- [x] `py_compile` na conftest.py
- [x] Parser kontraktu pokrycia uruchomiony lokalnie na zmodyfikowanym ci.yml
- [ ] CI tego PR-a: 3 zielone shardy + zielony fan-in "Backend (pytest)",
      sumy `[ci-shard]` = pełna liczba plików, czasy shardów ≤ ~10 min
- [ ] Merge bez zmian w branch protection (fan-in raportuje wymagany kontekst)

## Pliki

- `.github/workflows/ci.yml` — matrix + fan-in + Codecov per shard
- `backend/tests/conftest.py` — `_apply_ci_shard_filter`
- `docs/pytest-sharding-completion-report.md` — ten raport
