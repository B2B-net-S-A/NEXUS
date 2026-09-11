# 06 — Fala 3: poprawki, retest, regresja (≈ tydzień)

> Wejście: `wyniki/INDEX.md` + wszystkie `raport.md` z Fali 1 i 2 + `wyniki/C/raport.md`.
> Wyjście: zero P0/P1, retest zielony, przepływy MUST jako testy Playwright w nocnym biegu.

## 1. Triaż (człowiek + 1 agent, 2 h)

1. Agent zbiera wszystkie zgłoszenia do jednej tabeli `wyniki/F3/triaz.md`:
   `ID | moduł | prio | tytuł | Sentry | odtworzone 2× | duplikat czego | decyzja`.
2. Deduplikacja: ten sam objaw z różnych kart = jedno zgłoszenie (zachowaj oba ID w polu „duplikat”).
3. Reality-check: każde P0/P1 agent odtwarza TRZECI raz na aktualnym SHA. Nie odtwarza się → `false positive` z powodem
   (w sesji 27.05 co dziesiąte było błędem metody).
4. Człowiek decyduje per zgłoszenie: `fix` / `product-decision` / `wontfix` / `defer-after-launch`.
   P0 i P1 mogą być tylko `fix` albo `product-decision` z uzasadnieniem na piśmie.

## 2. Naprawy (agenci, równolegle per moduł)

- **Jeden PR na moduł**, nie na zgłoszenie (rule: `one-big-pr-not-many` + każdy push = pełny rebuild Coolify).
  Wyjątek: P0 bezpieczeństwa → osobny PR natychmiast.
- Gałąź od `origin/main` (nie od lokalnego tipa), nazwa `fix/uat-M07-<krótko>`.
- Każda naprawa ma test: backend `pytest` (plik obok istniejących), frontend Vitest (`__tests__`),
  a dla przepływów MUST — Playwright (§4). Zieleń testów mockujących warstwę, która padła, nie jest dowodem.
- Agent naprawiający czyta CLAUDE.md sekcję modułu PRZED zmianą — wiele „błędów” to opisane decyzje
  (np. redakcja kwot dla HoR, słowo „Oferta” w etapie pipeline'u, brak stawek w Radarze).
- Zmiana logiki zamówień → `python scripts/stamp_orders_procedure.py` (CI wymusza).
- Zmiana schematu → migracja + LUSTRO w `entrypoint.sh` (prod alembic osierocony) + `/api/health/deep`.
- Repo publiczne: w PR i commitach ZERO danych z produkcji (ID klientów OK, nazwy/kwoty NIE).
- PR description: `Zgłoszenia: M07-B01, M07-B03 (UAT 2026-09)`, test plan, `🤖 Generated with Claude Code`.
- Merge: CI zielone (gitleaks + backend + frontend), `scripts/merge-train.sh` przy wielu PR-ach naraz. Bez `--admin`.

## 3. Retest (agenci, po każdym deployu)

1. Po merge → poczekaj na `/api/health.version == nowy SHA` (deploy ~6 min po merge; smoke test w Actions).
2. Agent retestu bierze WYŁĄCZNIE scenariusze FAIL z modułu + scenariusze sąsiednie (te same trasy) →
   raport `wyniki/F3/retest-M07-<sha>.md` w tym samym formacie.
3. Sentry: po 10 min `lastSeen:-10m` dla naprawionych issue → puste = działa.
4. Regresja krzyżowa: karta B (spójność liczb) uruchamiana ponownie w całości po ostatnim PR fali —
   naprawy w zamówieniach/kontraktach psują pary 1–7 najczęściej.

## 4. Przepływy MUST → Playwright (agent e2e, ostatnie 2 dni fali)

Docelowo w `frontend/e2e/` (istniejące: `flow-create-candidate`, `flow-stage-transition`, `flow-write-note-mention`;
28 stubów w `flow-stubs-todo.spec.ts`). Zasady:

- Każdy spec używa `EntityTracker` i prefiksu `[QA-E2E-…]`; `afterAll` sprząta; cleanup FAIL = test FAIL.
- Specy odpowiadające P1–P4 (pełne przepływy lub ich kluczowe szwy):
  - `flow-p1-cv-to-hm-verdict.spec.ts`: kandydat z CV → notatka → dodanie do rekrutacji → 2 ruchy → werdykt HM (bez generacji CV — koszt AI; CV mockowane istniejącym dokumentem testowym lub krok pominięty).
  - `flow-p2-hire-to-active-contract.spec.ts`: `hired` → szkic zamówienia → umowa B2B → 409 conflicts → keep terms → kontrakt `active`, `end_date null` → PATCH zamówienia → `client_order_*` + krok harmonogramu.
  - `flow-p3-md-order-import.spec.ts`: grupa MD 2 linie → import (fixture xlsx w repo — fikcyjne nazwiska) → `md_remaining` → idempotencja → korekta → eksport Excel filtr „dziś”.
  - `flow-p4-terminate.spec.ts`: wypowiedzenie z datą wczoraj → `ended` → zamówienie `completed` → profil „Zakończeni” → MRR bez osoby.
- Wszystkie przez API (`request`) dla zapisu + UI (`page`) dla weryfikacji — kanban D&D w Playwright bywa flaky.
- Uruchomienie: `E2E_USER_PASSWORD=… npx playwright test flow-p*.spec.ts`; potem w `e2e.yml` (nocny; issue przy czerwieni już jest).
- Konto do nocnego biegu: dedykowane `e2e@…` z rolą admin? — **decyzja**: admin jest poza rankingami (placementy testowe nie płacą nagród), ale ma pełne prawa; alternatywa: rekruter + sprzątanie przed północą. Domyślnie admin + sprzątanie w `afterAll`.

## 5. Kryteria wyjścia z Fali 3

- [ ] `triaz.md`: każde zgłoszenie ma decyzję; P0/P1 = `fix` zmergowane i retest PASS (lub `product-decision` na piśmie).
- [ ] Karta B powtórzona na finalnym SHA: wszystkie pary `=` albo z zadeklarowaną różną definicją.
- [ ] Karta A powtórzona dla ról z pilotażu (min. 3 role) na finalnym SHA.
- [ ] 4 specy Playwright zielone lokalnie i w nocnym biegu 3 noce z rzędu.
- [ ] Sentry: brak nowych issue z `release:{{final_sha}}` z `users ≥ 2` przez 48 h.
- [ ] `docs/uat/manifest.yaml` → `final_sha` wpisany; `README.md` → kryteria startu odhaczone.
- [ ] Raport końcowy `docs/uat-completion-report-2026-09.md` (bez danych produkcyjnych; liczby zgłoszeń per moduł/prio, lista `product-decision`, lista `defer-after-launch` z właścicielem).
