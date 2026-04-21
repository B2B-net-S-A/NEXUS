# Branch Protection — `main`

Ustawienia do skonfigurowania ręcznie w GitHub UI dla repozytorium
`artur-t-96/Nexus`. Nie da się tego ustawić z repo — wymaga dostępu admina
do Settings → Branches.

## Krok po kroku

1. **Settings → Branches → Add branch protection rule**
2. **Branch name pattern**: `main`

### Required status checks

Zaznaczyć: `Require status checks to pass before merging`
oraz `Require branches to be up to date before merging`.

Dodać następujące status checks (po pierwszym uruchomieniu nowego CI
pojawią się na liście — może być konieczne odświeżenie po pierwszym PR):

- `Gitleaks secret scan`
- `Backend (ruff + pytest)`
- `Frontend (typecheck + build)`

### Pull request rules

- [x] **Require a pull request before merging**
- [x] Require approvals: **1**
- [x] Dismiss stale pull request approvals when new commits are pushed
- [x] Require review from Code Owners *(gdy powstanie `.github/CODEOWNERS`)*
- [x] **Require conversation resolution before merging**

### History & force-push

- [x] **Require linear history**
- [ ] ~~Allow force pushes~~ — zostawić WYŁĄCZONE
- [ ] ~~Allow deletions~~ — zostawić WYŁĄCZONE

### Admin enforcement

- [x] **Do not allow bypassing the above settings** — włączyć (obejmuje też adminów)

## Codecov token

Po dodaniu coverage do CI trzeba skonfigurować token Codecov:

1. Zaloguj się na [codecov.io](https://codecov.io) przez GitHub OAuth
2. Dodaj repo `artur-t-96/Nexus`
3. Skopiuj `CODECOV_TOKEN` ze strony settings repo w Codecov
4. GitHub → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`
   - Name: `CODECOV_TOKEN`
   - Value: *(wklejony token)*

Codecov upload jest skonfigurowany z `fail_ci_if_error: false` więc brak
tokenu nie blokuje CI — tylko coverage nie zostanie zaraportowany.

## Weryfikacja

Po skonfigurowaniu:

1. Otwórz testowy PR z drobną zmianą (np. edycja README)
2. Sprawdź że w sekcji "Checks" widać wszystkie 3 status checks
3. Sprawdź że "Merge" jest zablokowany dopóki checks nie zielone + brak review
4. Po merge — otwórz kolejny PR, sprawdź że bot Codecov komentuje coverage diff

## Rollback

Usunięcie branch protection — ta sama ścieżka w UI, przycisk "Delete"
przy regule. Settings są retroaktywne (historia commitów zostaje
nietknięta).
