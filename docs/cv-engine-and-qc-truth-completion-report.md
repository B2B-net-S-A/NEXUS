# Silnik CV bez wypełniacza i QC, które mówi prawdę — raport

13.10.2026. Plan czterech PR-ów po weryfikacji generatora CV i QC CV:
1. silnik CV;
2. QC mówi prawdę;
3. „To nieprawda” i „Jakość QC”;
4. CV w procesie.

Makiety i decyzje D1–D6: https://claude.ai/artifact/BZZRshjBDC4CMEGGP6m4Wr.
Artur: „tak na wszystkie D1–D6, rób PR-y po kolei”.

Reguły:
- `docs/claude/generator-cv/silnik-cv-bez-wypelniacza.md`;
- `docs/claude/rekrutacja-tablica/qc-mowi-prawde.md`.

Wszystkie liczby pochodzą z produkcji, odczytane tylko do odczytu za zgodą Artura. W repo są wyłącznie liczby, bez osób i treści.

## Skąd ta zmiana

Zespół mówił, że generator „wpisuje głupoty”, a QC „proponuje głupoty”. Ludzie
wklejali oryginał, notatki i Championa do ChatGPT.

| Co (pomiar 13.10.2026) | Liczba |
|---|---|
| CV wygenerowane w 30 dni | 759 |
| Punkt „Posiada kluczowe technologie…” w CV „Pod rekrutację” | 376 z 565 |
| Branża zgadnięta przez model albo wpisana przez kod („IT”) | 471 CV |
| Lata zepsute przez kod („4.4 years” z „4,5 roku”) | 22 CV |
| Kontrola AI z uwagami / z ukrytymi prawdziwymi zastrzeżeniami | 79% / 86 CV |
| QC: uwagi na CV (121 par z 3 dni) | 8,13 |
| QC: tytuł niezgodny, bo oczekiwany z kodami klienta | 97 ze 121 |

## PR 1 — silnik CV (B2B-net-S-A/NEXUS#2192, `b2d971122`)

- Prompt `legacy_v7`:
  - bez punktu wyliczającego wymagania;
  - rzeczowy ton;
  - technologie roli tylko z tej roli albo z odpowiedzi, która nazywa firmę (D3);
  - branża tylko ze źródła (D1).
- Nagłówek to nazwa roli od klienta bez kodów i lokalizacji, bez tłumaczenia (D2, `cv_role_title`).
- Lata: ułamek dopasowany w całości, daty nie są latami, „N lat jako X” tylko z ról X.
- Strażnik „fakt tylko z pytania”: technologia z pytania rekrutera albo z wymagań, której nie ma w CV ani w odpowiedziach, znika z uwagą WERYFIKUJ. Inny zapis tej samej technologii się liczy.
- Notatki dla modelu:
  - bez transkryptów i prepów;
  - bez pieniędzy i dostępności kandydata.
- Kontrola AI nie chowa zastrzeżeń.
- Przegląd python-reviewer znalazł 7 problemów, w tym 3 blokujące. Wszystkie poprawione przed merge'em, z testami.

## PR 2 — QC mówi prawdę (gałąź `fix/qc-truth`)

- Źródła QC:
  - odpowiedzi ze screeningu, bez pytań i zdań przeczących;
  - notatki bez automatów.
- `dz_review.found_in`: zapis, tłumaczenia, odmiana. Blokada „spoza oryginału” tylko ostrym trybem.
- Nagłówek CV nie jest twierdzeniem.
- Tytuł porównywany z `cv_role_title` i ze słownikiem słów ról.
- Pogrubienia: tylko to, co pogrubiłby generator, i tylko w CV, które pogrubia.
- Zdanie w roli wymagane tylko przy opisie roli w oryginale, także dla krytycznych. Reszta trafia do „Informacji”.
- „Szukałem w: …” przy pozycji i stały klucz pozycji (pod PR 3).
- Propozycje AI:
  - cytat z tej roli albo ze zdania z rozmowy, które nazywa firmę;
  - bez przeczeń i niższych wersji.
- Po wdrożeniu przeliczają się nieudane pary starszej wersji (zaliczonych nie: nowy wiersz zerowałby czas oczekiwania w kolejce DL).

Pomiar tym samym skryptem (`backend/scripts/qc_truth_audit.py`) na tych samych 121 parach. Kod PR 2 był wczytany jako nakładka, bez wdrożenia:

| Co | Przed | Po |
|---|---|---|
| Uwagi na CV | 8,13 | 3,19 |
| Pary zaliczone | 61 | 74 |
| Pozycje blokujące | 115 | 79 |
| Tytuł | 97 | 12 |
| Pogrubienia must / nice | 146 / 52 | 10 / 4 |
| Pogrubienia bez pokrycia | 145 | 9 |
| Zdanie w roli (must) | 111 | 14 (95 jako informacja) |
| Krytyczne | 38 | 13 (23 jako informacja) |
| Must-have nie w CV | 294 | 234 (27 jako informacja) |
| Spoza oryginału | 59 | 48 |

Przegląd python-reviewer znalazł 5 problemów blokujących. Wszystkie poprawione z testami:
- luźny rdzeń przepuszczał krytyczną „Spring” przy „sprint planning”;
- przeliczenie zaliczonych par zerowało czas oczekiwania w kolejce Delivery Leada;
- kropka rozcinała „.NET 8” w odpowiedziach, a odpowiedź w kilku liniach była ucięta;
- cytat notatki w oknie QC niósł stawkę z karty;
- cytat z linii o innej firmie przechodził jako dowód.

Liczby w tabeli są już po tych poprawkach. Braków must-have jest więcej niż w pierwszym pomiarze (187 → 234), bo przestały przechodzić fałszywe trafienia z prefiksu.

Okno QC z nowymi polami przeklikane na harnessie `/preview/cv-qc?state=truth` w 1280×720:
- „Szukałem w” mieści się w jednym wierszu;
- „Informacje — bez poprawki” widać w zaliczonym sprawdzeniu;
- okno ma 32–1248 px, nic nie wychodzi w poziomie.

Pozostałe uwagi przejrzane ręcznie:
- tytuł: model zmienił rolę od klienta albo plik z dysku jest o innej roli;
- spoza oryginału: tej rzeczy nie ma w żadnym źródle;
- must-have nie w CV: w 188 ze 226 przypadków nie ma ich ani w CV, ani w oryginale, ani w rozmowie (pytanie do kandydata).
