# Dekompozycja sygnałów Championa v1.1 — pomiar 3-ramienny i flip (17.08.2026)

Kontynuacja: v1 (finanse+lokalizacja) włączona 15.08 (P@5 +67%); bundle v1.1
(kara seniority + fallback dostępności) zmierzony 15.08 jako **NO-GO**
(R@20n −21% przy MRR +12%) — dwa sygnały pod jedną flagą były w pomiarze
nierozróżnialne. [#1170](https://github.com/artur-t-96/Nexus/pull/1170)
rozdzielił je na `CHAMPION_SENIORITY_PENALTY_ENABLED` i
`CHAMPION_AVAILABILITY_FALLBACK_ENABLED`; ten dokument to wynik pomiaru
po dekompozycji.

## Pomiar

Trzy ramiona na zamrożonych 50 ofertach z Championami (`/root/champ-eval-ids.txt`,
`--jobs 50 --min-gt 3 --pool 1000`), A/B per proces (`docker exec -e`), ten sam
wieczór, ten sam indeks. Kryterium per flaga, zarejestrowane z góry: R@20n bez
regresu ORAZ ≥1 metryka rankingowa w górę.

| metryka | baseline (prod) | +sama kara seniority | +sam fallback dostępności |
|---|---|---|---|
| P@5 | 0.220 | **0.228 (+4%)** | 0.220 (0%) |
| R@20n | 0.186 | **0.187 (+1%)** | 0.142 (**−24%**) |
| MRR | 0.408 | **0.422 (+3%)** | 0.416 (+2%) |
| nDCG@10 | 0.151 | **0.155 (+3%)** | 0.141 (−7%) |

Werdykty: **kara seniority GO → włączona na prodzie 17.08** (env przez Coolify
POST /envs + redeploy force=false; flaga w `_SCORING_CACHE_INPUTS`, więc cache
score'ów unieważnił się leniwie). **Fallback dostępności NO-GO → zostaje OFF.**

Baseline 17.08 (P@5 0.220) jest wyżej niż 15.08 (0.196) — między pomiarami
wjechały ingesty v2 (append skilli z dowodami, supersede must) i reindeksy;
ramiona porównywane wyłącznie wewnątrz jednego wieczoru.

## Dlaczego fallback dostępności psuje recall (mechanizm, nie zgadywanie)

Warstwa dostępności bez danych („brak daty") jest **poza budżetem** przy
renormalizacji kompozytu. Fallback zamienia ją w REALNY wynik dokładnie u tych
kandydatów, o których mamy fakty notatkowe (~14k) — a wyprowadzona data
(„dziś + 1 miesiąc wypowiedzenia") względem startu Championa często wychodzi
spóźniona i zdekejowana. Skutek: **selekcja niekorzystna wobec kandydatów
bogatych w dane** — ground-truth z wypowiedzeniem spada w rankingu pod ludzi
bez żadnego sygnału dostępności, którzy warstwę po prostu omijają.

Ewentualny powrót do tego sygnału wymaga zmiany semantyki (np. kara wyłącznie
za twardą kolizję dat przy wysokiej pewności, nie generyczny decay), z własnym
pomiarem.

## Lekcja metodyczna

Hipoteza sprzed dekompozycji („MRR daje dostępność, recall psuje kara") była
**dokładnie odwrotna** do wyniku. Bundle z rozjazdem metryk → nie zgaduj
składnika: dekompozycja kosztowała jeden PR i ~40 minut pomiaru, a zgadywanie
wyrzuciłoby działający sygnał i zostawiło szkodliwy.

## Stan flag scoringu po 17.08

| flaga | stan | podstawa |
|---|---|---|
| `CHAMPION_MATCH_SIGNALS_ENABLED` | **ON** | 15.08: P@5 +67%, R@20n +87% |
| `CHAMPION_SENIORITY_PENALTY_ENABLED` | **ON** | 17.08: P@5 +4%, R@20n +1%, MRR +3%, nDCG +3% |
| `CHAMPION_AVAILABILITY_FALLBACK_ENABLED` | OFF | 17.08: R@20n −24% |
| `CV_PASSAGES_ENABLED` | OFF | 12.08: −1,8 p.p. |
| `HYBRID_POOL_ENABLED` | OFF | 12.08: +0,4 p.p. (szum) |

Artefakty: `/root/eval-dec-{base,sen,av}.json` na hoście prod +
`eval-decomp.log` (zero błędów, 50/50 ofert w każdym ramieniu).
