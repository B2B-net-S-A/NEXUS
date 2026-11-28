# Skanery bezpieczeństwa w CI: Semgrep i audyt zależności (zapadka)

Od 13.11.2026. Artur pytał, jak regularnie sprawdzać bezpieczeństwo NEXUSA.
Wcześniej CI miało tylko gitleaks, Trivy przy zmianie Dockerfile'a albo
zależności i Dependabota. Nie było analizy kodu pod SQLi, XSS, SSRF i path
traversal ani audytu znanych podatności zależności na PR-ze.

## Co biegnie i kiedy

| Skaner | Kiedy | Gdzie |
|---|---|---|
| Semgrep (`p/python`, `p/fastapi`, `p/typescript`, `p/react` + własne `.semgrep/nexus-sql.yml`) | każdy PR, tylko zmienione pliki `backend/**/*.py` i `frontend/**/*.{ts,tsx,js,jsx,mjs,cjs}` | `ci.yml` → `semgrep-pr` |
| pip-audit (`backend/requirements.txt`) | PR, który zmienia `backend/requirements*.txt` | `ci.yml` → `deps-audit-pr` |
| npm audit (`frontend/`, `--omit=dev`, waga high+) | PR, który zmienia `frontend/package.json` albo `package-lock.json` | `ci.yml` → `deps-audit-pr` |
| zizmor (linter bezpieczeństwa GitHub Actions) | PR, który zmienia `.github/workflows/**`, `dependabot.yml` albo zapadkę | `ci.yml` → `zizmor-pr` |
| całość: Semgrep na całym repo, oba audyty, zizmor, Trivy obrazów produkcji, import do DefectDojo | poniedziałek 05:30 UTC (po Dependabocie) i ręcznie | `security-weekly.yml` |

- Wynik jobów PR-owych (Semgrep, audyt, zizmor) wlicza się do wymaganego kontekstu
  **„Backend (pytest)”** (job `backend-pytest-gate`), tak jak „Strażnicy repo”.
  Osobny kontekst nie jest wymagany w rulesecie, więc sama czerwień joba nie
  zatrzymałaby kolejki merge'ów.
- W kolejce merge'ów skanów nie ma. Grupa w kolejce zawiera tylko pliki, które
  Semgrep widział już na PR-ach, a minuty Actions są płatne (`ci-gotchas.md`).
  To, czego PR nie widzi (nowe reguły rejestru w starym kodzie, nowe CVE przy
  tych samych wersjach), łapie bieg tygodniowy.
- Czerwony bieg tygodniowy otwiera issue „NEXUS tygodniowy skan bezpieczeństwa
  czerwony”, a zielony je zamyka (`alert_issue.sh`).
- `p/secrets` świadomie poza listą, bo sekrety łapie gitleaks (wymagany kontekst).

## Zapadka: co przechodzi, co blokuje

- **Semgrep:** `.semgrep-baseline.json` w korzeniu repo. Wpis = reguła +
  ścieżka + odcisk (`fingerprint`) dopasowanego fragmentu kodu (bez numeru linii, więc kod nad
  nim może się przesuwać). Każda zmiana samego dopasowania, np. nowy `{parametr}`
  w f-stringu SQL, daje nowy odcisk i czerwień. Pole nie nazywa się `key`, bo gitleaks bierze
  16 znaków heksa po słowie „key” za klucz API. Wpis ma `status`
  (`zweryfikowane` albo `do-przegladu`) i `reason`; pusty powód albo inny status
  czerwieni job „Backend (lint + migrations)” (`test_security_ratchets.py`).
- **Zależności:** `.github/dependency-audit-baseline.json`, osobno `python` i
  `npm`. Wpis pasuje po identyfikatorze albo aliasie (PYSEC/GHSA/CVE), ma
  `reason` i `expires`. Po terminie wyjątek znów czerwieni, tak jak `exp:`
  w `.trivyignore`.
- Nowe znalezisko: najpierw popraw kod albo podbij wersję. Wyjątek dopisuj
  tylko świadomie, z uzasadnieniem, które da się sprawdzić w kodzie (skąd
  pochodzi wartość, gdzie jest bind albo escapowanie):

  ```bash
  pip install semgrep==1.136.0 setuptools==75.8.0   # wersja jak „semgrep” w baseline
  semgrep scan --metrics=off --config p/python --config p/fastapi \
    --config p/typescript --config p/react --config .semgrep/nexus-sql.yml \
    --json --output semgrep.json backend frontend
  python3 .github/scripts/semgrep_ratchet.py update --results semgrep.json \
    --status zweryfikowane --reason "Nazwa tabeli ze stałej listy, wartości przez bind."
  ```

  `update` po pełnym skanie usuwa też wpisy, których już nie ma. Wynik skanu
  części plików nie kasuje wpisów z innych plików.
- Pełny lokalny skan trwa ok. 45 s (10 rdzeni). Semgrep 1.136.0 to ostatnia
  wersja dla Pythona 3.9, więc działa też na systemowym Pythonie macOS.

## Pułapki

- **Semgrep 1.136 na Pythonie 3.12 potrzebuje `setuptools`** (`pkg_resources`
  przez opentelemetry); bez niego każdy bieg kończył się `ModuleNotFoundError`
  i czerwienią „nie zakończył skanu” (pierwszy bieg #3398).
- **Jawnie podany plik Semgrep skanuje nawet wtedy, gdy `.semgrepignore` go
  pomija.** Dlatego PR skanuje katalogi `backend frontend` z `--include=/ścieżka`
  dla każdego zmienionego pliku (`semgrep_ratchet.py include-args`).
- **Nawiasy w trasach Next.js** (`[slug]`) to w `--include` klasa znaków: bez
  escapowania wzorzec nic nie łapie i plik przechodzi bez skanu. Skrypt
  escapuje `[`, `]`, `*`, `?`.
- **`.semgrepignore` zastępuje domyślne wykluczenia** Semgrepa, więc stoją w nim
  wszystkie: testy, `frontend/e2e`, migracje Alembica (bez wejścia
  użytkownika), `node_modules`, `.next`.
- Reguły przychodzą z rejestru semgrep.dev przy każdym biegu; krok ponawia
  skan 3 razy. Rejestr może dodać regułę: na PR-ze trafi tylko w zmienione
  pliki, w biegu tygodniowym zaczerwieni całe repo i otworzy issue.
- pip-audit i npm audit kończą się kodem 1 także przy znaleziskach z baseline,
  więc o wyniku decyduje skrypt zapadki. Brak raportu albo błąd npm audit
  (np. `ENOLOCK`) to czerwień, nie cichy pass.

## Stan baseline z 13.11.2026

- Semgrep: 228 wpisów. 58 `zweryfikowane`, m.in. surowe SQL w
  `candidate_merge.py` (nazwy z `information_schema`), `nexus_data_correction.py`
  (`_qualified_identifier`, pola z listy `casts`), `keyword_suggest.py` (stałe
  wyrażenie + bind), fałszywe alarmy „token w logu”, md5/sha1 jako skrót
  tożsamości, `dangerouslySetInnerHTML` po DOMPurify. 170 to `text()` z
  f-stringiem albo zmienną w `backend/app` i `backend/scripts`, wprowadzone
  jako `do-przegladu`.
- Przegląd tych 170 (13.11.2026, PR po #3398): wszystkie `zweryfikowane`,
  żadna wartość wklejana do SQL nie pochodzi z żądania, pliku ani maila.
  Wklejane są stałe modułu (CTE typu `CREDITED_FROM_SNAPSHOT_CTE`), gałęzie
  literałów wybierane boolem, nazwy parametrów `:p{i}` z `enumerate`, białe
  listy (słownik, `Query(pattern=…)`, zbiór pól) i nazwy z katalogu bazy po
  regexie `^[a-z_][a-z0-9_]*$`. Każdy wpis ma własny powód ze źródłem
  wartości i bindami. Doszło AES-CBC w `ksef_send.py` (wymóg API KSeF).
  Baseline: 229 wpisów, 0 `do-przegladu`; nowy wpis od teraz tylko jako
  `zweryfikowane` z konkretnym powodem.
- Zależności: python-jose 3.5.0 (PYSEC-2026-4298) i ecdsa 0.19.2
  (PYSEC-2026-1325) bez wydania z poprawką były wyjątkami do 25.11.2026.
  Tego dnia backend przeszedł na PyJWT, oba wpisy zdjęte i baseline Pythona
  jest pusty. npm (13.11): brak high/critical w zależnościach
  produkcyjnych (6 moderate w `@sentry/*` → `glob`/`minimatch`).

## zizmor, Trivy obrazów i DefectDojo (27.11.2026)

Po researchu bezpieczeństwa z 27.11 (marzec 2026: przejęte tagi
`aquasecurity/trivy-action`, CVE-2026-33634) CI dostało linter workflowów,
skan obrazów, które się nie zmieniają, i wysyłkę wyników do DefectDojo.

### zizmor
- Wersja 1.33.1 z koła PyPI sprawdzanego sumą (`.github/scripts/install_zizmor.sh`;
  przy podbiciu zmień wersję, sumę, URL i pole `zizmor` w baseline). Skan
  całego repo (`run_zizmor.sh`: workflowy + `dependabot.yml`), z audytami
  online tokenem Actions i 3 próbami, bo jeden niedostępny endpoint GitHuba
  kończy bieg błędem „no audit was performed”.
- Pierwszy skan: 68 znalezisk. Poprawione: `persist-credentials: false`
  w 51 checkoutach (token zostawał w `.git/config` dla każdego kroku joba,
  także testów z kodu PR-a; `git fetch` w CI Gate i sicie frontu działa
  anonimowo, bo repo jest publiczne), `permissions: contents: read` na
  poziomie `ci.yml`, `issues: write` w `e2e.yml` tylko w jobach alarmu,
  `strategy.job-index/total` przez `env` zamiast `${{ }}` w `run:`, `cooldown`
  7 dni w `dependabot.yml` (wydanie z dnia publikacji nie wchodzi w poniedziałkowy PR).
- Zapadka: `.github/zizmor-baseline.json`, skrypt `zizmor_ratchet.py`
  (status, powód i porównanie wspólne z Semgrepem). Odcisk = audyt + plik +
  droga w YAML-u bez numerów kroków + dopasowany fragment, więc przesunięcie
  kroku nie czerwieni, a zmiana dopasowanego `run:` wymaga przeglądu. 8 wpisów,
  wszystkie `zweryfikowane`: `workflow_run`/`pull_request_target` w
  `deploy.yml`, `e2e.yml`, `queue-failure-feedback.yml`, `queue-migration-lane.yml`
  (checkout tylko domyślnej gałęzi, bez kodu PR-a), `secrets[...]` w
  `coolify-set-env.yml` (wartość nie może przejść przez `inputs`), losowe hasło
  do `$GITHUB_ENV` w `e2e.yml`, poświadczenia checkoutu w `migration-rechain.yml`
  (push przepięcia). Nowy wyjątek:

  ```bash
  bash .github/scripts/run_zizmor.sh zizmor.json    # lokalnie: zizmor z PyPI (Python ≥ 3.11) albo koło jak w install_zizmor.sh
  python3 .github/scripts/zizmor_ratchet.py update --results zizmor.json \
    --status zweryfikowane --reason "Skąd pochodzi wartość i dlaczego nie da się jej wstrzyknąć."
  ```

### Trivy obrazów produkcji
- Job „Trivy obrazów produkcji” w biegu tygodniowym. Coolify buduje obrazy na
  serwerze bez rejestru, więc backend i front budujemy z wdrożonego SHA
  (`version` z `/api/health`, `sha` z `$FRONTEND_URL/version.json`; bez
  odpowiedzi HEAD maina z ostrzeżeniem). Obrazy zewnętrzne: `image:` z
  `docker-compose.yml` tej wersji (bez `nexus-*`) i `TRAEFIK_IMAGE` w
  workflowie (proxy Coolify; wartość `traefik:v3.7` to domyślna Coolify 4.7.7,
  na serwerze niepotwierdzona — `docker inspect coolify-proxy`).
- Wynik to „co dałby redeploy”, nie zrzut kontenera: `apt`/`npm ci` mogą dać
  nowsze łatki, a pływający tag (`16-alpine`, `latest`) to najnowszy obraz tagu.
- Zapadka: `.trivyignore-images` (format `.trivyignore`, `exp:` obowiązkowy,
  komentarz z powodem nad wpisem, termin najwyżej ~rok). Osobny plik, bo
  wpis w `.trivyignore` ukryłby tę samą podatność w skanie zależności na PR-ach.
- Lokalnie 27.11 (Trivy 0.70.0, amd64): `postgres:16-alpine` 33 HIGH/CRITICAL
  z poprawką (gosu na starym Go, libxml2), `qdrant/qdrant:v1.17.1` 135 (Debian
  13.4, openssl, paczki Node.js z UI), `grafana/alloy:latest` i `traefik:v3.7`
  po 0; obraz stagingu backendu 6 (urllib3, msgpack, setuptools, libzstd),
  frontu 20 (Alpine openssl/musl/zlib, npm wbudowany w obraz Node). Bieg na
  runnerze (46062454294, obrazy z wdrożonego `a613205d0`) dał te same liczby.
- Stan wyjściowy w `.trivyignore-images`: 122 identyfikatory w czterech
  grupach. Własne obrazy mają termin 31.12.2026, bo poprawka to nasz PR
  (wersje w requirements, digest obrazu bazowego, npm poza etapem runner).
  Postgres i Qdrant mają termin 31.01.2027: Postgres czeka na nowy build
  obrazu tagu, Qdrant na świadome podbicie wersji. Identyfikator wspólny
  dla kilku obrazów stoi raz, przy najkrótszym terminie.
- 28.11.2026 (decyzja Artura): własne obrazy bez wyjątków. Backend: świeży
  digest `python:3.15-slim`, `apt-get upgrade` w obrazie (libzstd1) i
  `pip uninstall pip` po instalacji zależności — urllib3, msgpack i setuptools
  z raportu to kopie w `pip/_vendor/vendor.txt`, nie nasze zależności. Front:
  świeży digest `node:24-alpine` i npm/npx/corepack/yarn usunięte z etapu
  `runner`. Trivy lokalnie: 6 → 0 i 20 → 0. Nowy wpis dla własnego obrazu
  w `.trivyignore-images` to ostateczność — najpierw te trzy dźwignie.
- Qdrant 1.17.1 → 1.20.2 po jednej wersji minor na wdrożenie (135 → 99 → 17
  → 2 znalezisk), bo Qdrant gwarantuje zgodność storage tylko o krok. Próba
  na kopii wolumenu stagingu: każda wersja wstaje w kilka sekund, 8 kolekcji
  green, te same liczby punktów i wyniki `query_points`. Postgres sprawdzony
  ponownie: najnowszy `16-alpine` (16.16) ma te same 33.
  Klient `qdrant-client` szedł razem z serwerem (1.17.1 → 1.19.1 → 1.20.0).
  Po kroku 3 w `.trivyignore-images` zostają 2 wpisy Qdranta (libzstd1, zlib1g
  z Debiana obrazu upstream). Staging i E2E od razu na 1.20.2 — skok 1.17.1 →
  1.20.2 sprawdzony na kopii wolumenu stagingu.

### DefectDojo
- Każdy job biegu tygodniowego kończy się krokiem „Import do DefectDojo”
  (`defectdojo_import.sh`, `continue-on-error`): `POST /api/v2/reimport-scan/`,
  produkt „NEXUS”, engagement „CI tygodniowy”, testy „Semgrep”, „pip-audit”,
  „npm audit”, „zizmor” (SARIF), „Trivy <obraz>”. DefectDojo nie ma
  publicznego adresu: krok podnosi tunel WireGuard z sekretu
  `DEFECTDOJO_WG_CONF_{SEMGREP,DEPS,ZIZMOR,TRIVY}` — osobny peer na job, bo
  joby biegną równolegle, a wspólny klucz wypierałby sesje (peer widzi w tunelu tylko DefectDojo,
  `http://10.66.0.1:8080`, nadpisywane zmienną repo `DEFECTDOJO_URL`)
  i zamyka go na końcu. Token `DEFECTDOJO_TOKEN` to konto `ci-import`
  (dostęp tylko do produktu NEXUS przez jego `authorized_users`; DefectDojo 3.x nie ma ról); produkt i engagement zakłada sesja SOC.
  Sekrety ustawia Artur; bez nich krok kończy się notką. Raport idzie
  wprost z joba, bez artefaktu (artefakty publicznego repo pobierze każdy
  zalogowany), a log ma tylko kod HTTP i liczby, bez wyjścia `wg-quick`.
- Serwer stawia sesja SOC (Wazuh + DefectDojo). Znaleziska do ekranu
  Ustawienia → Bezpieczeństwo wypycha serwer bezpieczeństwa co 30 min, a wynik
  jobów `security-weekly.yml` ekran czyta z API GitHuba — nazwy pliku i jobów
  zmieniaj tylko razem z ekranem (`SECURITY_GITHUB_WORKFLOW`, nazwy jobów idą na ekran wprost).

### Do DefectDojo tylko to, co czeka na reakcję (28.11.2026)
- Pierwszy pełny import (28.11, ok. 13:35) wystawił na ekranie Bezpieczeństwo
  287 pozycji „czeka na reakcję”: 237 Semgrep, 36 Trivy, 8 zizmor, 6 npm —
  co do sztuki wyjątki, które zapadki już przepuszczały z powodem. Import brał
  surowe raporty, więc każdy bieg wystawiałby je od nowa.
- Od teraz każdy job wysyła raport PO zapadce, w formacie skanera:
  `semgrep_ratchet.py dojo` (bez wpisów `zweryfikowane`), `zizmor_ratchet.py
  dojo` (SARIF z tego samego biegu, para z JSON-em po regule, pliku i linii;
  brak pary = czerwień), `dependency_audit.py --dojo-output` (bez porad z ważnym
  wyjątkiem i pakietów, które są w raporcie tylko przez nie), Trivy z
  `.trivyignore-images`. `do-przegladu`, nowe znaleziska, wagi pod progiem
  bramki bez wyjątku i wyjątki po terminie idą do DefectDojo jak dawniej.
- `close_old_findings` zamyka w DefectDojo to, czego nowy raport nie ma, a
  sync z `complete: true` zamyka to na ekranie. Na ekranie wygląda to jak
  „naprawione”; powód i termin wyjątku są w pliku zapadki, nie w DefectDojo.
- Przegląd 28.11.2026 (klasyfikacja wszystkich 287): `text()` z wklejaniem
  tylko stałych, białych list i placeholderów (bindy dla wartości); md5/sha1 jako
  skrót tożsamości tekstu i klucz cache; `jwt.decode` bez podpisu tylko do
  wyświetlenia `exp` naszego klucza JJIT; AES-CBC wymagany przez API KSeF; HTML
  w mailu zgód przez `html.escape`; trzy `dangerouslySetInnerHTML` po DOMPurify
  albo JSON-LD z `<` → `\u003c`; „token” w logach to id, kody błędów i liczby;
  zizmor jak w baseline. Trivy i npm: powody nad wpisami w `.trivyignore-images`
  (gosu bez sieci i TLS, libxml2 bez funkcji XML w SQL, libzstd w Qdrancie i we
  freshclamie ClamAV) i `dependency-audit-baseline.json` (glob/minimatch tylko
  we wtyczce budowania Sentry, termin 28.02.2027). Wynik: 0 pozycji do reakcji.

### Własna reguła: `text()` z SQL-em zbudowanym gdzie indziej (28.11.2026)
- Reguła z rejestru `avoid-sqlalchemy-text` działa w trybie taint w obrębie jednej
  funkcji. Źródłem jest dla niej tylko sklejanie na miejscu (f-string, `+`, `%`,
  `.format`), więc nie widziała SQL-a z innej funkcji albo modułu
  (`text(build_sql(...))`, `text(schema.X)`), z `.join(...)` ani przekazanego
  parametrem. 28.11 takich wywołań było 124 (61 w `app/models/`). Przegląd:
  wszystkie bezpieczne — stałe, białe listy, nazwy z katalogu bazy, wartości
  przez bind.
- `.semgrep/nexus-sql.yml` (`nexus-sqlalchemy-text-built-elsewhere`) łapie każdy
  niedosłowny argument `text()` poza tym, co widzi reguła rejestru, bez
  `backend/app/models/` (predykaty indeksów liczone przy imporcie). Baseline:
  131 wpisów `zweryfikowane` z powodem per plik; 71 z nich to te same linie co
  wpis reguły rejestru (pętla po zmiennej zbudowanej f-stringiem w funkcji).
- Identyfikator reguły z pliku zależy od ścieżki (`semgrep.nexus-…`), więc każdy
  skan podaje `--config .semgrep/nexus-sql.yml` względnie od korzenia repo; pilnuje
  tego `test_every_semgrep_scan_uses_the_repo_rules_from_baseline`. Przykłady
  reguły: `.semgrep/nexus-sql.py`, `semgrep --test --config .semgrep/nexus-sql.yml
  .semgrep/nexus-sql.py`. PR zmieniający `.semgrep/` uruchamia test reguł i skan
  całości, bo nowa reguła trafia też w niezmieniony kod.
- Fingerprint wpisu to dopasowane `text(sql)`, nie budujący je kod: zmiana
  w funkcji, która składa SQL, nie wymusi ponownego przeglądu. Reguła pilnuje
  nowych miejsc wywołania, a nie zmian w budowniczych.

### Gitleaks na pełnej historii (jednorazowo, 27.11.2026)
- gitleaks 8.21.2, `.gitleaks.toml`, `--log-opts=--all`, `--redact`: 13 558
  commitów, 46 trafień, drzewo `main` 0. Aktualne sekrety były tylko w
  `bf5cb10f8`/`38bd32fa7` (15.04.2026), już zmienione 24–25.11 albo decyzją
  Artura zostawione; klucz deploy z `bf5cb10f8` ma inny odcisk niż jedyny
  klucz zarejestrowany na GitHubie (zmieniony 16.07.2026). Reszta: domyślne
  hasła dev/test i atrapy w testach.
