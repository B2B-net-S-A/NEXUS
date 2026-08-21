# Eksperymenty rankingowe 4a/4b — rozszerzone aliasy i strojenie wag (17.08.2026)

Kontynuacja programu wyszukiwarki po dekompozycji v1.1
(`champion-signals-decomposition-2026-08-17.md`). Oba eksperymenty za flagami /
zmianą stałych, oba zmierzone wg kryterium zarejestrowanego z góry
(R@20n bez regresu + ≥1 metryka rankingowa w górę), oba **GO i wdrożone**.

## 4a — rozszerzone rodziny aliasów umiejętności ([#1181](https://github.com/artur-t-96/Nexus/pull/1181))

**Luka zmierzona na prodzie:** bazowa taksonomia (196 kanonicznych + 458
aliasów) nie znała narzędzi-podstaw z tysiącami kandydatów — git (14,8k),
jira (11,9k), confluence (3,9k), excel, active directory, maven, servicenow,
bpmn, uml… **Mechanizm wpływu:** regex z ALIAS_MAP to źródło derived-must dla
~88% ofert (`_extract_skills_from_champion`) — termin spoza taksonomii jest
w implicit-must niewidzialny.

~60 rodzin (tech-only, bez soft-skills i 2-literowców) + mostki wariantów
(k8s→kubernetes, postgres→postgresql, rest apis→rest api). Merge w loaderze za
`SKILL_ALIAS_EXTENDED_ENABLED` (baza wygrywa na kolizjach); taksonomia
boldowania CV celowo nietknięta.

**A/B na zamrożonych 50:** P@5 0.228→0.232 (+2%) · R@20n 0.187→0.186 (szum)
· MRR 0.422→0.428 (+1%) · nDCG 0.155→0.157 (+2%) → **GO** (małe, spójne zyski
przy zerowym koszcie; flip = dane, odwracalny env-em).

## 4b — strojenie wag: 35/30/12/8/5 → **45/25/10/8/2** ([#1182](https://github.com/artur-t-96/Nexus/pull/1182))

**Metodologia (dwustopniowa, out-of-sample):**
1. **Trening** — 7 profili wag JEDNYM biegiem harnessu (nowe powtarzalne
   `--weights`; wspólny retrieval = porównanie czystych wag) na 50 ofertach
   champion-era **rozłącznych** z zamrożonym eval (`--exclude-job-ids`).
   Wynik: 45/25/10/8/2 dominuje na wszystkich metrykach (P@5 +46%, R@20n +49%,
   MRR +39% vs default), gradient 45 > 50 > 35 → okolice optimum.
   **Semantyka wygrywa** — spójne z całym programem (retrieval i embeddingi
   były głównym frontem napraw).
2. **Walidacja** — zwycięzca vs default na zamrożonych 50:

| metryka | default 35/30/12/8/5 | **45/25/10/8/2** |
|---|---|---|
| P@5 | 0.228 | **0.240 (+5%)** |
| R@20n | 0.187 | **0.189 (+1%)** |
| MRR | 0.422 | **0.442 (+5%)** |
| nDCG@10 | 0.155 | **0.160 (+4%)** |

Zysk przeniósł się na dane, których trening nie widział → **GO**.
Caveat: eval zeruje champion_fit w obu ramionach (leakage guard); prod trzyma
champion 10 — przeważenie pozostałej piątki przenosi się strukturalnie.

**Dlaczego flip przez STAŁE, nie wiersz w `scoring_weight_profiles`:**
powierzchnie uzasadnień (Dopasowanie) i część ścieżek siedzą na wbudowanym
DEFAULT — globalny wiersz w bazie rozjechałby pierścień kanbanu od zakładki.

**Dwa wzmocnienia przy okazji (oba złapane w trakcie):**
- `SKILLS_MUST/NICE_MAX` to teraz **pochodne** z `SKILLS_MAX` (2:1) — jako
  osobne literały rozjechały się z budżetem przy strojeniu (20/10 przy 25);
  wykryły to testy asertujące budżet warstwy.
- **Wagi domyślne weszły do digestu `scoring_algorithm_version`** — zmiana
  stałych w kodzie zmienia score'y pod tym samym `profile_id=0`, więc bez
  wpisu stary cache mieszałby dwie skale punktowe. Edycje profili z bazy
  zostają poza digestem (`mark_stale_for_profile` działa punktowo).

## Skumulowany efekt programu na zamrożonym zbiorze (50 ofert z Championami)

| krok | P@5 | R@20n | MRR | nDCG@10 |
|---|---|---|---|---|
| przed sygnałami v1 (15.08 rano) | 0.108 | 0.081 | ~0.30 | — |
| v1 finanse+lokalizacja (15.08) | 0.196 | 0.148 | 0.350 | 0.113 |
| + kara seniority (17.08) | 0.228 | 0.187 | 0.422 | 0.155 |
| + aliasy + wagi 45/25/10/8/2 (17.08) | **~0.24+** | **~0.19** | **~0.44+** | **~0.16** |

(Ostatni wiersz: 4a i 4b mierzone niezależnie od tej samej bazy — efekt
łączny do potwierdzenia następnym pomiarem; interakcja drugiego rzędu, bo
aliasy zasilają warstwę skills, którą wagi lekko odchudzają.)

## Co dalej (świadomie POZA tym wdrożeniem)

- **Learning-to-rank właściwy** (model na surowych warstwach zamiast ręcznej
  siatki profili) — dopiero po osadzeniu tych wag; wymaga zrzutu per-warstwa
  z harnessu i dyscypliny train/eval jak wyżej.
- Pomiar efektu ŁĄCZNEGO 4a+4b na świeżym zbiorze (po przyroście danych
  z pętli świeżości notatek i nocnego parse'u CV).
- Sufit puli (49,6% na ofertach championowych) — wciąż górna granica; kolejne
  zyski rankingowe będą maleć, dopóki retrieval nie podniesie sufitu.
