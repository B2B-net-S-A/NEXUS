# Talent Radar — symulacje rekruterskie na produkcji (2026-08-19)

Pięć pełnych przepływów „jak rekruter" na żywym prodzie, po wdrożeniu twardego
sufitu budżetu (#1207-#1208) i przebudowy formularza radaru (profil na górze,
plik ⊕ treść z pastylką ALBO). Każda symulacja: inny realny profil Championa
z Traffita + inny klient → upload → weryfikacja chipa i prefillu stawki →
wyszukanie → ocena trafności top wyników i liczników.

## Wyniki symulacji

| # | Profil (z pliku) | Klient | Stawka z profilu → budżet | Ukryci poza budżetem | Trafność top wyników |
|---|---|---|---|---|---|
| 1 | Programista Java Senior (PKO BP) | Alior Bank | 122,5 auto | 451 / 1987 | Java devy WWA, `java`+`oracle db` ✓, uczciwe braki (`jest`, `xml`) |
| 2 | Architekt Chmurowy Senior (ZOB-2878) | ATOS | 160 auto | 347 / 1994 | seniorzy cloud/infra, `aws`/`gcp`/`kubernetes` ✓ |
| 3 | Tester Automatyzujący (15 mustów) | AVENGA | 110 auto | 342 / 1990 | czyści testerzy; nr 1 z KOMPLETEM mustów (bdd, cucumber, selenium…) |
| 4 | Mobile Developer Android/Kotlin MP | Allegro | 130 auto | 312 / 1986 | prawdziwi mobile devi (`jetpack compose`, `kotlin`, `junit`), Kraków zgodnie z profilem |
| 5 | Analityk Biznesowy Senior ZOB-2905 (digital assets) | ALLCLOUDS | 122,5 auto | 342 / 1986 | seniorskie BA 19-22 lata IT z Warszawy, `business analysis` ✓ |

Dodatkowo tryb tekstowy (bez pliku): „Senior Java, bankowość" + sufit 150 →
1993 przejrzanych, **„Ukryto 168 poza budżetem"** — licznik zawsze widoczny.

## Trzy bugi znalezione TYLKO przeklikiem (testy FE były zielone — mockują `api`; curl działał — omija axiosa)

1. **Upload profilu nigdy nie działał z przeglądarki** — instancja axios ma
   default `Content-Type: application/json`, którego FormData nie podmienia →
   multipart jechał jako „json" → FastAPI 422 `file Field required` (preflight
   OPTIONS przechodził, co myliło w stronę CORS). Fix wzorcem repo: jawny
   nagłówek multipart (#1209).
2. **Parse ubijany przez timeout klienta** — Haiku parsuje profil 10-31+ s
   (zmierzone curl-em: 31,2 s → HTTP 200), a instancja ma timeout 30 s; serwer
   odpowiadał w próżnię, UI wisiał na „Parsuję…". Fix: per-request 120 s (#1210).
3. **Search na zimnym cache też przekracza 30 s** (profil z 15 mustami) — ta
   sama klasa; fix: per-request 120 s + wspólna stała `SLOW_ENDPOINT_TIMEOUT_MS`
   (#1211).

Lekcja utrwalona w pamięci projektu: każdy nowy endpoint LLM/scoringowy w FE
musi dostać override timeoutu — domyślka instancji jest dla CRUD-ów; a FormData
zawsze z jawnym nagłówkiem multipart.

## Werdykt

Przepływ rekruterski radaru działa end-to-end na produkcji: parse wyciąga rolę,
musty, stawkę i lokalizację; stawka wskakuje w budżet (ręczny wpis nadpisuje,
wyczyszczenie wyłącza sufit); twardy sufit tnie ze zliczeniem ukrytych; wyniki
są trafne per rola także dla ról niszowych; filtr dopuszczalności per klient
odsiewa (1986-1994 → 1984-1987). Ostatni fix (#1211) domknął jedyną wykrytą
usterkę.
