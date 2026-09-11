# A/B scorera: legacy vs kanoniczny (11.09.2026)

[← wróć do raportu P0–P1](codex-remediation-p0-p1-completion-report.md)

Decyzja z 10.09: nowy ranking z #1428 (kanoniczny fit, ta sama liczba co na
ekranach C2) **zostaje**, a w tym tygodniu przechodzi A/B wobec starego scorera.
To jest ten pomiar.

## Ustawienie

| | |
|---|---|
| Kanał | `coolify-ops.yml` → `action=eval-ab-scorer` (po #1492 — krótka komenda `scripts.eval_ab_run`) |
| Zbiory | zamrożony **A** (50 ofert z Championami, era 08.2026) i holdout **B** (`scripts/eval_frozen_set.py`) |
| Pula | wektorowa (semantic only), 2000 kandydatów na ofertę, `--min-gt 3` |
| Ramię OFF (kontrola) | `--scorer legacy` — `rank_candidates_for_job` |
| Ramię ON | `--scorer canonical` — `canonical_fit.score_candidates` |
| Wspólne | ta sama pula, te same dane, jeden bieg; `HYBRID_POOL_ENABLED=false`, `RERANKER_ENABLED=false` |
| Biegi | A: [34587611822](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34587611822) · B: [34588917307](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34588917307) |

Canonical domyślnie maskuje dowody wymagań zweryfikowane przez rekruterów —
istnieją głównie dla kandydatów, z którymi zespół już pracował, czyli dla
pozytywów ground-truth, więc zdradzałyby etykietę (jak `champion_fit`).

## Wyniki

### Zbiór A

| scorer | P@5 | R@20 | R@20 norm | MRR | nDCG@10 | HistHit@10 |
|---|---:|---:|---:|---:|---:|---:|
| legacy (kontrola) | 0.240 | 0.075 | 0.192 | 0.451 | 0.151 | 0.312 |
| canonical | **0.256** | 0.073 | 0.193 | **0.474** | **0.163** | 0.298 |
| Δ | +0.016 | −0.002 | +0.001 | +0.023 | +0.012 | −0.014 |

### Holdout B

| scorer | P@5 | R@20 | R@20 norm | MRR | nDCG@10 | HistHit@10 |
|---|---:|---:|---:|---:|---:|---:|
| legacy (kontrola) | 0.124 | 0.103 | 0.113 | 0.273 | 0.096 | 0.300 |
| canonical | 0.124 | 0.097 | 0.107 | 0.275 | 0.095 | 0.284 |
| Δ | 0.000 | −0.006 | −0.006 | +0.002 | −0.001 | −0.016 |

`R@20 norm` dzieli Recall@20 przez maksimum osiągalne dla wielkości
ground-truth danej oferty — to jest liczba do porównań, nie surowe R@20.

## Werdykt

Kryterium GO z rundy 18.08 ([matching-improvements-r2](matching-improvements-r2-2026-08-18.md)):
R@20n bez regresu (≥ kontrola − 0.002) **i** ≥1 metryka rankingowa > kontrola
+ 0.002, **z potwierdzeniem kierunku na holdoucie B**.

- **A: GO.** R@20n bez zmian (+0.001), P@5 +0.016, MRR +0.023, nDCG +0.012.
- **B: kierunek niepotwierdzony.** R@20n −0.006 (poza tolerancją 0.002),
  P@5 bez zmian, MRR +0.002 (na granicy), nDCG −0.001.

**Wniosek: kanoniczny scorer nie jest gorszy od starego w sposób, który
uzasadniałby cofnięcie — na głównym zbiorze wyraźnie lepiej ustawia górę
listy, na holdoucie wychodzi remis z lekkim spadkiem recall.** Formalnie, jako
„nowa zmiana do włączenia”, nie przeszedłby GO (brak potwierdzenia na B).
Ponieważ jest już produktem (ta sama liczba na ekranach C2, w kolumnie
wyszukiwarki ręcznej i w pierścieniu „Dopasowanie”), rekomendacja: **zostaje**,
zgodnie z decyzją z 10.09, pod obserwacją `weekly_eval` (od P1 mierzy canonical
i porównuje tylko biegi tego samego scorera).

## Uwagi do odczytu

- **Spójny spadek HistHit@10** (−0.014 na A, −0.016 na B). Canonical nie ma
  warstwy Championa ani historycznego boostu — to jego definicja (bazowy fit
  bez kar i bez historii). Jeśli ma to znaczenie produktowe, kolejny krok to
  osobny eksperyment z sygnałem historycznym, a nie strojenie wag.
- **Kontrola odtworzyła baseline 18.08 z dryfem** — legacy na A: P@5 0.240
  vs 0.248, R@20n 0.192 vs 0.199. Od 18.08 zmieniły się dane (60 110
  kandydatów w bazie, reindeks z 09.09) i bramka must-have z P0 (ukrywa
  znane braki technologii). Porównanie OFF/ON jest ważne, bo oba ramiona
  liczone są w tym samym biegu, na tej samej puli i danych; porównań z
  liczbami sprzed 11.09 nie należy robić bez nowego baseline'u.
- **50 ofert to mała próba** — jedno trafienie w top 5 jednej oferty to 0.004
  w P@5. Delty z B mieszczą się w kilku trafieniach.
- `bm25=0` w obu ramionach jest poprawne: pula wektorowa, noga BM25 nieużyta.

## Jak powtórzyć

```bash
gh workflow run coolify-ops.yml --repo B2B-net-S-A/NEXUS --ref main \
  -f action=eval-ab-scorer -f eval_set=A -f eval_jobs=50 -f eval_pool=2000
```

Potem `eval_set=B`. Wynik jest w logu biegu (sekcje `===NEXUS-EVAL-OFF/ON===`).
Zadanie Coolify sprząta się samo; gdyby zostało, `action=eval-stop`.
