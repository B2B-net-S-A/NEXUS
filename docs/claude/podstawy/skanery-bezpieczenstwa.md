# Skanery bezpieczeństwa w CI: Semgrep i audyt zależności (zapadka)

Od 13.11.2026. Artur pytał, jak regularnie sprawdzać bezpieczeństwo NEXUSA.
Wcześniej CI miało tylko gitleaks, Trivy przy zmianie Dockerfile'a albo
zależności i Dependabota. Nie było analizy kodu pod SQLi, XSS, SSRF i path
traversal ani audytu znanych podatności zależności na PR-ze.

## Co biegnie i kiedy

| Skaner | Kiedy | Gdzie |
|---|---|---|
| Semgrep (`p/python`, `p/fastapi`, `p/typescript`, `p/react`) | każdy PR, tylko zmienione pliki `backend/**/*.py` i `frontend/**/*.{ts,tsx,js,jsx,mjs,cjs}` | `ci.yml` → `semgrep-pr` |
| pip-audit (`backend/requirements.txt`) | PR, który zmienia `backend/requirements*.txt` | `ci.yml` → `deps-audit-pr` |
| npm audit (`frontend/`, `--omit=dev`, waga high+) | PR, który zmienia `frontend/package.json` albo `package-lock.json` | `ci.yml` → `deps-audit-pr` |
| całość: Semgrep na całym repo + oba audyty | poniedziałek 05:30 UTC (po Dependabocie) i ręcznie | `security-weekly.yml` |

- Wynik obu jobów PR-owych wlicza się do wymaganego kontekstu
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
    --config p/typescript --config p/react --json --output semgrep.json backend frontend
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
  (PYSEC-2026-1325) bez wydania z poprawką; każde `jwt.decode` ma jawne
  `algorithms=`. Termin 15.02.2027. npm: brak high/critical w zależnościach
  produkcyjnych (6 moderate w `@sentry/*` → `glob`/`minimatch`).
