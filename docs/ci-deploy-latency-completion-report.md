# Skrócenie ścieżki merge → produkcja

Data: 2026-08-07. Zakres: `.github/workflows/{ci,ci-gate,deploy}.yml` + jeden kontrakt testowy.

## Problem

Nawet zmiana jednej stałej jechała na produkcję ~52 min od otwarcia PR-a, a przy
kolizji z innym merge'em — godzinami.

### Pomiar wyjściowy (PR #1059, commit `b4af6c58`, zmiana jednej liczby)

| Etap | Czas |
|---|---|
| PR otwarty → merge (CI na PR) | 24 min |
| CI na `main` — **te same testy drugi raz** | 24 min 24 s |
| Deploy (Coolify build + smoke + deep health) | 3 min 58 s |
| **Razem** | **~52 min** |

### Rozbicie CI (24 min) — trzy przebiegi na `main`, 2026-08-06

| Job | 31103760726 | 31100489776 | 31096666193 |
|---|---|---|---|
| Gitleaks secret scan | 17 s | 20 s | 14 s |
| Trivy + hadolint | 31 s | 27 s | 27 s |
| Frontend (typecheck + build) | 5 min 11 s | 5 min 36 s | 5 min 01 s |
| **Backend (ruff + pytest)** | **24 min 20 s** | **24 min 00 s** | **23 min 47 s** |

Wewnątrz backendu (run 31103760726): setup + pip + alembic + import smoke
1 min 38 s, codecov 12 s, **pytest 22 min 20 s** (4792 testy, jeden proces).

Czyli 92% czasu joba backendowego to jeden krok, i on sam wyznaczał długość
całego CI — reszta jobów kończyła się w 5 min i czekała.

### Trzy przyczyny, nie jedna

1. **Pytest bez zrównoleglenia.** 4792 testy w jednym procesie, brak
   `pytest-xdist` w zależnościach.
2. **Te same testy dwa razy na każdą zmianę.** Raz na PR, raz po merge'u na
   `main`. Deploy wisiał na `workflow_run: ["CI"]`, więc te drugie 24 minuty
   siedziały w ścieżce krytycznej. Ponieważ `strict: true` gwarantuje aktualność
   gałęzi, drugi przebieg testował praktycznie ten sam kod.
3. **`strict: true` + 24-minutowe CI.** Przy pracy seriami PR robił się `BEHIND`
   zanim zdążył się zmergować → aktualizacja → CI od zera. Ogony w czasach
   merge'u: #1055 = 105 min, #1052 = 98 min, #1054 = 77 min, #1050 = 536 min.

**Coolify nie był winny** — cały Deploy stabilnie ~4 min.

## Zmiany

### 1. Podział na dwa workflow (`ci-gate.yml` + `ci.yml`)

`workflow_run` reaguje na ukończenie **całego** workflow, nie pojedynczego joba —
dlatego samo rozbicie na joby w jednym pliku nic by nie dało. Stąd osobny plik:

| Workflow | Joby | Czas |
|---|---|---|
| **CI Gate** | Gitleaks secret scan · Backend (lint + migrations) | **1 min 28 s** |
| **CI** | Backend (pytest) · Frontend (typecheck + build) · Trivy + hadolint | ~22 min |

W bramce jest to, co tanio i realnie chroni produkcję: sekrety (nieodwracalne),
ruff (1 s), pełna choreografia alembica (migracja, która nie wchodzi, to
najczęstszy tryb awarii tego repo) i import smoke.

### 2. Deploy bramkowany na `CI Gate`, nie na `CI` (`deploy.yml`)

`workflows: ["CI"]` → `workflows: ["CI Gate"]`.

Czego świadomie **nie ma** w bramce:

- **Build frontendu** — Coolify i tak buduje oba obrazy ze źródeł, więc zepsuty
  build = nieudany deployment = czerwony job Deploy = brak wdrożenia. Bramkowanie
  na nim było duplikatem tej samej weryfikacji.
- **Pytest** — przeszedł już na PR na tym samym kodzie i nadal leci na `main`
  równolegle.

### 3. Kontrakt migracji (`test_client_directory_migration_contract.py`)

`test_hosted_ci_runs_fresh_retry_downgrade_and_reupgrade_cycle` czytał `ci.yml`
i sprawdzał choreografię alembica, którą przeniesiono do bramki. Kontrakt
przepisany tak, by sprawdzał **zachowanie** („hostowane CI przechodzi cykl"),
a nie który plik je zawiera: przegląda oba workflow i wymaga, by *któryś*
spełniał komplet warunków. Każdy plik osobno, nie na sklejce — `_normalise_sql`
zwija także znaki nowej linii, więc konkatenacja mogłaby skleić ostatnią komendę
jednego pliku z pierwszą komendą drugiego i sfabrykować dopasowanie.

## Wynik (liczby z PRAWDZIWEGO CI, nie lokalne)

| | Przed | Po |
|---|---|---|
| Gitleaks | 17 s | 21 s |
| Backend — lint + migracje (bramka) | *(w jobie 24 min)* | **1 min 28 s** |
| Frontend | 5 min 11 s | 5 min 24 s |
| Backend — pytest | 22 min 20 s | bez zmian *(patrz niżej)* |
| **Bramka przed deployem** | **24 min** | **1 min 28 s** |
| **merge → produkcja** | **~28 min** | **~5,5 min** |

Cel osiągnięty: **czas wdrożenia przestał zależeć od pytestu**. Bramka to
1,5 min, deploy ~4 min. Pytest wpływa już wyłącznie na czas oczekiwania na PR-ze.

## Zrównoleglenie pytest — wdrożone i WYCOFANE

Pierwotna rekomendacja („22 min → ~6 min przez `pytest-xdist`") **nie
utrzymała się w zderzeniu z rzeczywistością**. Zapis przebiegu, bo wnioski są
warte więcej niż sam wynik:

**Pomiar lokalny obiecywał 4×.** Pełny suite na czystej bazie: 4792 passed,
0 failed, 5 min 35 s wobec 22 min 20 s. Statyczny przegląd wyglądał zachęcająco:
`app_client` seeduje unikatowego admina per test, zero `TRUNCATE`/`drop_all`
w całym `tests/`, globalny stan taksonomii jest per-proces.

**CI pokazało co innego.** Przyspieszenie tylko 1,47× (22 min 20 s → 15 min 12 s)
— i, ważniejsze, **realne wyścigi**, których 8-rdzeniowa maszyna lokalna nie
ujawniała, a 4-vCPU runner owszem:

- `test_engagement_inventory` — liczy `COUNT(*)` z całej tabeli przed i po
  GET-cie, żeby dowieść że endpoint jest read-only. Równoległy worker
  wstawiający własny wiersz jest nieodróżnialny od mutacji → test oskarżał
  endpoint o cudzy zapis.
- `test_contracts_search` — `assert 115 == 116`, porównuje `total` z dwóch
  wywołań API; między nimi cudzy worker zmienia dane.

W grupie ryzyka jest **25 plików** dotykających globalnych agregatów. Łatanie
po jednym osłabia asercje: pierwsza próba (znacznik `MAX(id)`) sprawiła, że
licznik przestał wykrywać INSERT przez endpoint.

**Właściwa naprawa też nie przeszła — z innego powodu.** Izolacja bazy per
worker (`CREATE DATABASE … TEMPLATE` w `conftest.py`) rozwiązuje poprawność
elegancko: zero zmian w testach, żadnego osłabiania asercji, cała klasa znika.
Ale pełny suite wydłużył się do **39 min 46 s** — cztery bazy po ~40 MB
przekraczają domyślne `shared_buffers` postgresa (128 MB), a doszła też
porażka z presji na pulę połączeń (awaria commitu, nie asercji).

**Decyzja: zrównoleglenie zdjęte z tego PR-a.** Praca nad izolacją zachowana na
gałęzi `xdist-per-worker-db-wip`. Uzasadnienie: zysk deployowy jest niezależny
od xdista i już zweryfikowany, a zrównoleglenie 4792 testów mocno związanych
z bazą to osobny problem — wymaga zmierzenia izolacji na natywnym Linuksie
(lokalne 39 min może być artefaktem wolnego I/O Dockera na macOS), rozważenia
mniejszej liczby workerów i strojenia postgresa.

### Lekcja przenośna

**Zielony przebieg lokalny nie jest dowodem zgodności z xdistem dla testów
mierzących stan globalny.** Liczba rdzeni zmienia przeplecenie, więc wyścig
ujawnia się dopiero tam, gdzie rdzeni jest mniej. Do tego dochodzi druga
pułapka: pierwszy przebieg lokalny dał 35 porażek, z których **wszystkie**
okazały się artefaktem środowiska (kontener z zamontowanym tylko `backend/`
i bez bibliotek systemowych), a nie problemem xdista — łatwo było wtedy wyciągnąć
odwrotny, równie fałszywy wniosek.

## Weryfikacja

Środowisko odtwarzające CI: `python:3.12-slim` + `postgres:16-alpine`, ten sam
zestaw zmiennych, ta sama lista `--ignore`.

Co zostało potwierdzone dla tego, co wchodzi:

- **Kroki bramki na świeżym postgresie** — pełna choreografia alembica
  (upgrade → ponowny upgrade → downgrade poniżej 0205 → upgrade heads) przechodzi,
  a `from app.main import app` się importuje.
- **Kontrakt migracji po przepisaniu** — warunki spełnia `ci-gate.yml`, nie
  spełnia `ci.yml`; asercja „któryś workflow przechodzi cykl" trzyma.
- **Gitleaks** — po allowlistowaniu DSN-a CI po WARTOŚCI: „no leaks found",
  exit 0 lokalnie (ta sama wersja 8.21.2 i to samo polecenie co CI),
  potwierdzone w CI (21 s).
- **Dwa pełne przebiegi pod rząd bez resetu bazy** — 4792 passed / 0 failed
  w obu (dowód odtwarzalności, patrz sekcja niżej).

### Pułapka metodyczna warta zapamiętania

Pierwszy przebieg lokalny dał **35 porażek i 4 błędy**. Wszystkie okazały się
artefaktem środowiska, nie kodu: kontener miał zamontowany tylko `backend/`,
więc testy czytające pliki z roota repo (`docker-compose`, `ci.yml`, skrypty)
nie miały do nich dostępu, a `weasyprint` nie miał bibliotek systemowych.
Po przemontowaniu na root repo i doinstalowaniu libów zostało 5 porażek, a po
eksperymencie A/B na czystej bazie (serialnie vs `-n 4`, ten sam zestaw
plików — 21 passed w obu) okazało się, że żadna z nich nie wynikała ze
zrównoleglenia.

Wniosek: **czerwony wynik z niedopieczonego środowiska jest bezwartościowy jako
dowód w którąkolwiek stronę.** Gdyby przyjąć te 35 porażek za wynik, decyzja
byłaby błędna; gdyby przyjąć późniejszy zielony przebieg lokalny za dowód
zgodności z xdistem — również (patrz „Lekcja przenośna" wyżej).

## Odtwarzalność suite'u na trwałej bazie

Osobna klasa problemu, wyszła przy okazji. Suite dawał się uruchomić dokładnie
raz na danej bazie; drugi przebieg padał. W CI maskował to świeży kontener
postgresa per job, więc bolało tylko lokalnie.

Dwie różne przyczyny, mimo że objawiały się razem:

1. **`test_engagement_inventory.py`** — seedował wiersz o stałej parze
   `(year=9999, seq=1/2)` przy UNIQUE na tej parze i nie sprzątał.
   Naprawa: seed jest teraz **idempotentny** — kasuje dokładnie tę jedną parę
   przed wstawieniem (nigdy zakres). `contract_number` celowo nie jest kluczem:
   nie ma na nim UNIQUE, a duplikat numeru jest właśnie tym, co ten test bada.

2. **`test_contract_finance_redaction.py`** — pobierał jedną stronę
   `?page_size=100` i wymagał swojego wiersza na niej, czyli zakładał prawie
   pustą tabelę. Przy nagromadzonych kontraktach wiersz wypadał poza stronę i
   test czerwieniał z powodu niezwiązanego z redakcją danych finansowych, czyli
   z tym, co bada. Podbicie `page_size` tylko przesunęłoby próg (endpoint tnie
   na 200), więc naprawa przechodzi po **wszystkich** stronach — to zdejmuje
   założenie o rozmiarze bazy całkowicie.

**Dowód:** dwa pełne przebiegi pod rząd na tej samej bazie, bez resetu między
nimi — 4792 passed / 0 failed w obu (7 min 44 s i 10 min 14 s; drugi wolniejszy,
bo baza urosła).

## Świadomy kompromis

Produkcja może żyć kilka minut zanim pytest na `main` się skończy. Okno kryje
przypadek dwóch PR-ów zmergowanych blisko siebie, które osobno są zielone,
a razem nie. Sygnałem jest wtedy czerwone „CI" na `main` → rollback
(`deployment-runbook` §2). Deep healthcheck w `deploy.yml` łapie osobną,
częstszą klasę: migrację, która nie weszła na prod.

Rollback samej zmiany: w `deploy.yml` zmień `workflows: ["CI Gate"]` z powrotem
na `workflows: ["CI"]` — deploy znowu poczeka na pytest.

## Branch protection

Nazwy jobów się zmieniły, więc wymagane checki też. Nowa lista:

```
Gitleaks secret scan
Backend (lint + migrations)
Backend (pytest)
Frontend (typecheck + build)
```

Reszta ustawień bez zmian (`strict: true`, `enforce_admins: true`, linear
history, 0 wymaganych approvali).

**Wpływ na otwarte PR-y:** w chwili zmiany otwartych było 16 (głównie
dependabot). Każdy musi raz przebiec, żeby wyprodukować kontekst
`Backend (lint + migrations)`. Nie dokłada to pracy ponad to, czego i tak
wymagał `strict: true` — te PR-y i tak wymagały aktualizacji przed merge'em.
