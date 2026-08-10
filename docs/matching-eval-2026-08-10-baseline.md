# Baseline wyszukiwarki talentów — pomiar 2026-08-10

**Werdykt: NO-GO.** Silnik na samym opisie oferty nie nadaje się jeszcze do wystawienia
rekruterom jako wstępna wyszukiwarka talentów.

To pierwszy pomiar tego systemu wykonany na **pełnym indeksie** i na **prawdziwych
danych** — poprzedni (2026-05-10) mierzył w większości oferty demo i był nieporównywalny.
Liczby niżej są niskie, ale są prawdziwe; wcześniejsze nie były ani jednym, ani drugim.

## Warunki pomiaru

| | |
|---|---|
| Commit produkcyjny | `9e340c4` → `5725956` (deploy w trakcie, bez wpływu na silnik) |
| Kandydaci | 56 783, **pokrycie indeksu 100%** (0 bez wektora) |
| Oferty | 4 117, **pokrycie indeksu 100%** (0 bez wektora) |
| Model embeddingu | `voyage-3`, 1024 wymiary, spójny po obu stronach (patrz niżej) |
| Próbka | 40 ofert, `--exclude-seed-jobs`, `--min-gt 3` |
| Dostępny materiał | 3 413 ofert z GT ≥ 3 (próg wiarygodności z planu: 25) |
| `champion_fit` | **wyłączony** — czyta odpowiedzi screeningowe istniejące tylko dla pozytywów z GT (wyciek etykiet) |

Backfill wykonany bezpośrednio przed pomiarem: **10 619 kandydatów + 278 ofert**, zero
błędów. Qdrant 48 096 → 58 715 punktów kandydatów, 3 862 → 4 140 punktów ofert.

### Kontrola spójności modelu — omal nie zatruliśmy kolekcji

Skrypt backfillu zaraportował `model=voyage-3`, podczas gdy plan i `.env.example`
zakładały `voyage-3-large`. Dopisanie 10 619 wektorów innym modelem do istniejącej
kolekcji rozjechałoby przestrzeń zapytań z przestrzenią dokumentów — **a kontrola wymiaru
by tego nie wykryła**, bo oba modele dają 1024.

Sprawdzone empirycznie zamiast na podstawie konfiguracji: przeliczenie kandydata bieżącym
modelem i porównanie z zapisanym wektorem dało **cosinus 0,9939**. Prod jest spójny na
`voyage-3`; wzmianka o `voyage-3-large` to dryf dokumentacji, nie awaria produkcji.

## Wyniki — A/B na identycznym zbiorze 40 ofert

| Wariant | P@5 | R@20 | **R@20n** | MRR | nDCG@10 | HistHit@10 |
|---|---:|---:|---:|---:|---:|---:|
| A — bez boostu (domyślny harness) | 0,030 | 0,027 | **0,033** | 0,080 | 0,014 | 0,045 |
| B — z boostem historycznym | 0,085 | 0,045 | **0,061** | 0,209 | 0,058 | 0,287 |

**Czytaj B.** Produkcja stosuje boost zawsze, harness domyślnie nie. Domyślny przebieg
zaniża obraz prawie trzykrotnie (P@5 0,030 vs 0,085) — bez tej pary łatwo ogłosić awarię
tam, gdzie jest tylko źle dobrana konfiguracja pomiaru.

Czytaj `R@20n`, nie `R@20`: dwadzieścia miejsc nie pomieści sześćdziesięciu osób, więc
surowa wartość nie jest porównywalna między ofertami. Wszystkie 40 ofert miało **pełne
pokrycie GT w indeksie** (`GT indexed = GT size`), więc to nie jest artefakt dziury
w indeksie — mierzymy silnik, nie brak danych.

## Główne ustalenie: wąskim gardłem jest RETRIEVAL, nie ranking

Rozłożenie sufitu recall na rozmiar puli pobieranej z Qdranta (ta sama definicja GT co
w harnessie, 960 pozytywów na 40 ofertach):

| Pula | GT w puli | Sufit recall |
|---:|---:|---:|
| 20 | 17/960 | 1,8% |
| 50 | 39/960 | 4,1% |
| **200 (obecny prod)** | **131/960** | **13,6%** |
| 500 | 219/960 | 22,8% |
| 1000 | 313/960 | 32,6% |

**Przy obecnym sufcie 200 warstwa scoringu w ogóle nie widzi 86,4% ground truth.**
W 9 z 40 ofert do puli nie trafia ani jeden kandydat z GT — dla tych ofert żadne
strojenie wag niczego nie zmieni, bo nie ma czego rankować.

Podział strat:
- **Retrieval gubi 86,4%** zanim scoring cokolwiek zobaczy.
- **Scoring gubi kolejne ~67%** tego, co dostał (R@20 4,5% z dostępnych 13,6%).

Obie warstwy są słabe, ale retrieval jest twardszym sufitem. **Podniesienie puli z 200 do
1000 podnosi osiągalny sufit 2,4× (13,6% → 32,6%)** — i to bez dotykania wag. To
najtańsza dostępna dźwignia i potwierdza priorytet z Etapu 6 planu, teraz z liczbą.

## Kontekst jakości danych

- **90% ofert (3 721 z 4 117) nie ma `nice_skills`**, 13% nie ma `must_skills`.
- **40% kandydatów (22 555 z 56 783) ma `skills = null`.**

Warstwa umiejętności ma wagę 30 z 90 punktów budżetu i jest w dużej mierze ślepa. To
ogranicza sufit niezależnie od retrievalu i tłumaczy, dlaczego samo strojenie wag nie
odblokuje wyniku.

## Zastrzeżenia do interpretacji

1. **Ground truth to kandydaci w pipelinie oferty**, czyli osoby, które rekruter wprowadził
   — często pozyskane spoza wyszukiwarki. Oczekiwanie, że silnik trafi je w top-5, jest
   surowe. To jednak jedyny dostępny sygnał, a względne porównania (A/B, sufit puli)
   pozostają ważne niezależnie od tej surowości.
2. **Nie dodano `exclude_in_pipeline`** do harnessu świadomie — wyzerowałoby każdą metrykę,
   bo GT to właśnie osoby z pipeline'u.
3. `champion_fit` wyłączony celowo. Włączenie go zawyżyłoby wynik wyciekiem etykiet.
4. W Qdrancie zostaje **1 932 osieroconych punktów kandydatów** i 23 ofert (58 715 punktów
   na 56 783 kandydatów). Zajmują miejsca w puli, więc realny sufit jest minimalnie wyższy
   niż zmierzony. To osobna sprawa — dotyczy też prawa do bycia zapomnianym.

## Co z tego wynika dla planu

1. **Nie strójmy wag.** Przy 86,4% ground truth poza polem widzenia ablacja mierzyłaby szum.
2. **Priorytet: sufit retrievalu (Etap 6).** Podniesienie puli do 1 000 i prefiltr
   w Qdrancie — najtańsza dźwignia, zmierzone 2,4× na osiągalnym sufcie. Wymaga wpierw
   zbatchowania N+1 w scoringu, bo zimna pula 1 000 to ~2 000 round-tripów.
3. **Równolegle: uzupełnienie `must/nice_skills` i `skills` kandydatów.** Bez tego warstwa
   o wadze 30/90 zostaje ślepa.
4. **Dopiero potem ponowny pomiar** i decyzja go/no-go.

## Artefakty

Surowe raporty harnessu (nie commitowane, na serwerze `/root/`): `eval-baseline.md`,
`eval-baseline.json`, `eval-boost40.md`, `eval-boost40.json`.

Odtworzenie:
```bash
python -m scripts.eval_matching --exclude-seed-jobs --jobs 40 --min-gt 3 --json \
  --output /tmp/eval-baseline.md
# wariant z boostem MUSI dostać --jobs, inaczej domyślne 10 ofert
# zamieni porównanie w dwa niezwiązane pomiary
python -m scripts.eval_matching --job-ids "<id z JSON-a A>" --jobs 40 --min-gt 3 \
  --with-historical-boost --json --output /tmp/eval-boost.md
```
