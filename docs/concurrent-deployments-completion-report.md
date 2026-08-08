# Wiele PR-ów / deployów naraz bez wzajemnego blokowania — completion report

Data: 2026-08-07 · Branch: `claude/concurrent-deployments-0169d1`

## Problem

Przy próbie wprowadzenia kilku PR-ów naraz wszystko się zacina. Dwie warstwy:

1. **Merge:** branch protection ma `strict=true` („branch must be up to date")
   + CI trwa ~22 min. Każdy merge na main flipuje pozostałe PR-y w `BEHIND`,
   a GitHubowy auto-merge **nigdy sam nie aktualizuje** gałęzi — PR-y czekają
   na ręczne „Update branch" i wzajemnie unieważniają sobie CI (livelock
   z sesji #1030, 2026-08-03/04).
2. **Deploy:** każdy push na main = pełny rebuild Coolify (~10 min). Burst
   merge'y historycznie zapychał kolejkę Coolify (HTTP 429 „queue is full",
   2026-07-15/16; wcześniej churn rebuildów zapchał dysk, 2026-05-22),
   a wyprzedzone deploye czerwieniły się fałszywie w deep healthchecku.

## Rozważone i odrzucone

| Opcja | Dlaczego nie |
|---|---|
| **GitHub merge queue** (natywne rozwiązanie tego problemu) | Niedostępne: działa tylko w repo organizacji (publiczne lub Enterprise Cloud). `artur-t-96/Nexus` to prywatne repo na koncie osobistym. |
| **Zdjęcie `strict` (up-to-date)** | To strażnik przed incydentem 27.07: squash przeterminowanej gałęzi **cicho cofnął 6 merge'y na prodzie** (GitHub raportował `MERGEABLE/CLEAN`). Prawdziwie równoległe lądowanie = instytucjonalizacja tego ryzyka. |
| **Workflow w Actions auto-aktualizujący PR-y** | W sekretach repo nie ma PAT-a, a `update-branch` wykonany `GITHUB_TOKEN`-em nie triggeruje workflowów (suppression GitHuba) → CI na PR-ze nigdy by nie ruszyło i auto-merge by nie odpalił. |

## Wdrożone rozwiązanie

### 1. `scripts/merge-train.sh` — sekwencyjne wprowadzanie PR-ów bez babysittingu

Lokalny skrypt (gh + PAT → update triggeruje CI normalnie):

```bash
scripts/merge-train.sh 1062 1063 1064
```

Dla każdego PR-a w podanej kolejności: uzbraja auto-merge (squash), przy
`BEHIND` robi `gh pr update-branch`, czeka aż CI przejdzie i PR wjedzie, po
czym bierze następny. Aktualizuje **jeden PR na raz** — update wszystkich
naraz kosztuje ~N²/2 przebiegów CI zamiast N, bo każde lądowanie unieważnia
resztę. Konflikty (`DIRTY`), zamknięte PR-y i timeouty (default 90 min/PR) są
pomijane z raportem na końcu (exit 1, lista PR-ów do ręcznej uwagi).

Sufit fizyczny pod `strict=true` bez merge queue: **~1 PR na okno CI
(~25 min)** — ale bez klikania i bez zgubionych PR-ów; 5 PR-ów wjeżdża samo
w ~2 h. Wąskim gardłem taktu jest pełne CI na PR-ze (pytest ~22 min jako
required check); sam merge→prod to po #1063 już tylko ~5,5 min (bramka
„CI Gate"), więc prod nadąża za pociągiem praktycznie na bieżąco.

### 2. `deploy.yml` — koalescencja burstów (skip redundantnego rebuildu)

Nowy krok `Skip if target already live (burst coalescing)` na początku
deploy joba: pyta `/api/health`; jeśli produkcja serwuje już `TARGET_SHA`
**lub jego potomka** (GitHub compare API, status `ahead`/`identical`) —
pomija trigger/rebuild i przechodzi wprost do smoke testu.

Czemu to poprawne: Coolify klonuje **HEAD maina** w momencie budowy, więc
pierwszy build z burstu wdraża także późniejsze commity — kolejne buildy
niczego nie zmieniają, tylko mielą kolejkę. Fail-open: każdy błąd sondy
(health nieosiągalny, brak wersji, `behind`/`diverged`) = normalny deploy.
Ręczny `workflow_dispatch` **nigdy nie skipuje** (escape hatch do świadomego
redeployu np. po zmianie env varów).

### 3. `deploy.yml` — deep healthcheck akceptuje potomka

Pierwszy smoke test od #965 uznawał wyprzedzony deploy za sukces
(pokrewieństwo zamiast równości SHA), ale **deep healthcheck nadal wymagał
dokładnego SHA** → czerwienił te same przebiegi 6 próbami później. Teraz
deep health przechodzi też na potomku `TARGET_SHA` — nasz kod i migracje tam
są, więc to pełnoprawna weryfikacja.

## Zmienione pliki

- `.github/workflows/deploy.yml` — krok precheck + `if:` na 3 krokach deploy
  joba + ancestry w deep healthchecku + nota w komentarzu nagłówkowym
- `scripts/merge-train.sh` — nowy (nowy katalog `scripts/` w root repo)
- `CLAUDE.md` — sekcja „CI gotchas": wpis o merge train i koalescencji
- `docs/concurrent-deployments-completion-report.md` — ten raport

## Jak używać (TL;DR)

1. Przygotuj N PR-ów (zielone CI na własnej gałęzi, rozwiązane wątki review).
2. `scripts/merge-train.sh <pr1> <pr2> ... <prN>` — i idź na kawę.
3. Deploye z burstu koalesują się same; prod kończy na najnowszym SHA,
   wszystkie runy Deploy zielone.

## Ograniczenia / świadome decyzje

- Lądowanie pozostaje **sekwencyjne** (~25 min/PR) — to cena `strict=true`,
  którego nie zdejmujemy po incydencie 27.07. Prawdziwa równoległość wymaga
  przeniesienia repo do organizacji z Enterprise Cloud (merge queue) — nie
  warte kosztu dla solo-deva.
- Skrypt wymaga lokalnego `gh` z PAT-em (repo+workflow) — jest już
  skonfigurowany na tej maszynie.
- Precheck w deploy.yml nie dotyka ścieżki `workflow_dispatch` (rollbacki
  i wymuszone redeploye działają jak dotąd).

## Weryfikacja

- `python3 -c "yaml.safe_load(...)"` na deploy.yml — OK; `bash -n` na
  skrypcie — OK.
- Deploy tego PR-a przejdzie ścieżką **bez** skipu (prod = rodzic targetu →
  `behind` → normalny rebuild) — smoke + deep health potwierdzą nowy SHA.
- Ścieżka skipu uruchomi się przy najbliższym realnym burście merge'y;
  w logu deploy joba pojawi się „pomijam redundantny rebuild".
