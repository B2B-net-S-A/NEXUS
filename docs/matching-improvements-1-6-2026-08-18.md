# Ulepszenia wyszukiwarki 1–6 — raport wykonania (2026-08-18)

> Kontynuacja programu jakości matchingu po punktach 1–4 z 17.08
> (`docs/matching-experiments-4a-4b-2026-08-17.md`). Sześć ulepszeń
> zatwierdzonych en bloc; dyscyplina measure-first bez zmian: każda zmiana
> scoringu za flagą, pomiar A/B na zamrożonych 50 ofertach, flip tylko
> zwycięzców. PR-y: #1188 (konsolidacja 3-6 + narzędzia), #1189 (flip wag).

## Werdykty pomiarowe

Zamrożony zbiór 50 ofert z Championami (`scripts/eval_frozen_set.py`),
pula 2000, `--min-gt 3`. Kryterium GO: R@20n bez regresu (≥ baseline − 0.002)
ORAZ ≥1 metryka rankingowa > baseline + 0.002.

| eksperyment | P@5 | R@20n | MRR | nDCG@10 | werdykt |
|---|---|---|---|---|---|
| baseline po 4a+4b (pula 1000) | 0.244 | 0.192 | 0.438 | 0.162 | — |
| **pula 2000** (`MATCH_POOL_SIZE`) | **0.252** | 0.192 | 0.438 | **0.168** | **GO — żywe na prodzie** |
| hybryda ×2 (ponowny pomiar przy 2000) | 0.252 | 0.192 | 0.438 | 0.168 | NO-GO (zero delty; OFF na stałe) |
| dostępność v2 (kara za twardą kolizję dat) | 0.252 | **0.184** | 0.452 | 0.166 | **NO-GO** (R −0.008; flaga OFF na stałe) |
| **wagi 60/10/15/5/0** (LTR-lite) | **0.256** | **0.200** | **0.463** | 0.167 | **GO — flip #1189** |

Skumulowany postęp programu od baseline'u 2026-08-10 (P@5 0.085 / R@20n 0.061 /
MRR 0.209): **P@5 ×3.0, R@20n ×3.3, MRR ×2.2**.

## Co weszło (per ulepszenie)

**1. Sufit retrievalu.** Outbox indeksu osuszony (0 pending — sufit 49,6%
realny, nie papierowy). `MATCH_POOL_SIZE=2000` zmierzone GO i ustawione
w Coolify. Pasaże pozostają odłożone: kolekcja zamrożona od 12.08
(`embed_candidate` jej nie utrzymuje), a mechanizm porażki z A/B 12.08
nietknięty — re-pomiar wymagałby pełnego odświeżenia bez przesłanki, że
wynik będzie inny.

**2. Pomiar łączny 4a+4b.** Efekt skumulowany aliasów GO + wag 45/25/10/8/2
potwierdzony na zamrożonym zbiorze — brak interakcji ujemnej.

**3. Strażnik cotygodniowy** (`app/tasks/weekly_eval.py`). Harness jako
subproces raz w tygodniu (niedziela 05:00 UTC) na zamrożonych 50; wynik
w `traffit_sync_state.weekly_eval` (widoczny w `/api/admin/traffit/sync/status`);
spadek P@5 albo R@20n >15% t/t → `logger.error` (Sentry) +
`last_status='regression'`. Awaria (timeout/harness_failed/parse_failed)
NIE przesuwa watermarka — czkawka w niedzielę nie wycisza strażnika na
tydzień. Env: `WEEKLY_EVAL_ENABLED=true` (aktywowane 18.08).

**4. Dostępność v2** (`CHAMPION_AVAILABILITY_CONFLICT_ENABLED`). Kara −10%
wyłącznie za twardą kolizję JAWNYCH dat (deadline vs availability_date lub
data z notatek; wyprowadzenia nigdy nie karzą; 30 dni łaski). Zbudowane
poprawnie, zmierzone uczciwie: NO-GO (R@20n −0.008 — próg twardy). Flaga
zostaje OFF; rodzina sygnałów dostępności po trzech pomiarach
(fallback −24%, konflikt −0.8 p.p.) uznana za wyczerpaną — spójnie z
`availability=0` w nowych wagach.

**5. LTR-lite** (`--dump-layers` + `scripts/weight_search.py`). Zrzut
per-para (18,9 MB, zbiór rozłączny) → pełny simpleks 7315 wektorów offline
(sekundy, zero kosztu LLM/DB) → nominacja semantic-heavy → walidacja
prawdziwym biegiem na zamrożonych 50: **60/10/15/5/0 GO** (pierwszy dzisiejszy
zysk recall obok precyzji i MRR). Kontrakt dwustopniowy zapisany w docstringu:
siatka NOMINUJE, werdykt wydaje wyłącznie bieg `--weights` na zamrożonym
zbiorze. Flip przez stałe w `scoring_service` (#1189); digest wersji cache
łapie zmianę automatycznie (`default_weights` z #1182).

**6. Digest dopasowań** (`app/tasks/match_digest.py`). Poniedziałek 06:00 UTC:
dla każdej opublikowanej rekrutacji z przypisanym rekruterem/TAC top-5
ŚWIEŻYCH kandydatów (spoza pipeline'u) ze score ≥55 → powiadomienie
in-app (`NotificationType.match_digest`, migracja 0231 + lustro entrypoint;
zero nazwisk w treści, link do rekrutacji). Score'y liczone przez
`bulk_get_or_compute` — wpisy cache'u komitowane PRZED gałęzią continue
(rollback nie kasuje opłaconej pracy). Env: `MATCH_DIGEST_ENABLED=true`
(aktywowane 18.08).

## Nowe wagi domyślne — proweniencja

35/30/12/8/5 (pre-17.08) → 45/25/10/8/2 (siatka 7 profili, #1182) →
**60/10/15/5/0** (pełny simpleks na zrzucie warstw, walidacja out-of-sample,
#1189). Semantyka dominuje (60), skills spadły do 10 (sygnał już w dużej
mierze skonsumowany przez semantykę i derived-must), salary wzrosło do 15,
dostępność wyzerowana (podwójne NO-GO warstwy). `SKILLS_MUST/NICE_MAX`
pozostają pochodnymi 2:1 od `SKILLS_MAX`.

## Pułapki utrwalone w tej fazie

- `ast.parse` NIE łapie „name assigned before global declaration" (etap
  symtable) — weryfikuj `compile()`, nie samym AST.
- Watchery gh: grep case-insensitive (`grep -ci`), walidacja numeryczna
  wyników, wątki review przez GraphQL (`gh pr view --json reviewThreads`
  nie istnieje).
- Test mechaniki warstwy nie może zależeć od strojonych wag domyślnych —
  przy `AVAILABILITY_MAX=0` trzy testy dostępności redukowały się do
  `0.0 == 0.0`; jawny profil z niezerowym budżetem w testach.
- Subproces w pętli tła: `sys.executable` (nie "python"), reap po kill
  przez `communicate()` w try/except (RuntimeError, ProcessLookupError).

## Stan aktywacji (18.08)

- `MATCH_POOL_SIZE=2000` — żywe (deploy #1188).
- `WEEKLY_EVAL_ENABLED=true`, `MATCH_DIGEST_ENABLED=true` — aktywowane
  deployem #1189; pierwszy bieg obu pętli od razu po starcie (watermark
  pusty → `_is_due` True), zweryfikowany w `/sync/status`.
- Flagi OFF na stałe (zmierzone NO-GO): `HYBRID_SEARCH_ENABLED`,
  `CHAMPION_AVAILABILITY_CONFLICT_ENABLED`, fallback dostępności v1.

## Co dalej (nieobjęte tym programem)

- Odpowiedź supportu Traffita → champion daily sync (1095 profili czeka).
- Przegląd 66 twardych wet + 129 duplikatów osób (decyzje ludzkie).
- Ewentualny LTR właściwy (model rankujący na warstwach) — dopiero gdy
  strażnik potwierdzi stabilność 60/10/15/5/0 przez kilka tygodni.
