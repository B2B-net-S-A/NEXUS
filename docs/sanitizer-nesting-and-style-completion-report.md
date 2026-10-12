# Sanitizer HTML CV: ograniczony koszt i zepsuty `style` (12.10.2026)

Błędy `sanitize_cv_html` znalezione w przeglądzie bezpieczeństwa PR-a #2146
(edytor CV na cały ekran). Istniały wcześniej; Artur polecił naprawić je
osobnym PR-em. Reguły: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`.

## Co było źle

| Objaw | Przyczyna |
|---|---|
| Zapis CV z `style="color: red; font-size"` (albo zbłąkanym nawiasem) kończył się błędem 500 | Nasza podklasa sanitizera CSS serializowała listę deklaracji razem z tokenem błędu z tinycss2 |
| Jedno żądanie z głęboko zagnieżdżonym HTML-em blokowało serwer na minuty | html5lib w bleach płaci za każdy znacznik czasem proporcjonalnym do głębokości drzewa, a handlery wołają sanitizer wprost w pętli zdarzeń. Pole `content_html` przyjmuje 500 000 znaków |
| To samo przy tysiącach akapitów z elementem w środku | Walker drzewa przy powrocie do rodzica przeglądał całe jego rodzeństwo |
| To samo przy tysiącach elementów wpisanych wprost w `<table>` | Parser przenosi taką treść przed tabelę, za każdym razem przeglądając rodzeństwo tabeli |
| To samo przy tysiącach atrybutów w jednym znaczniku (10 000 atrybutów, 58 KB) | Tokenizer porównuje każdy atrybut ze wszystkimi wcześniejszymi |
| To samo przy tysiącach `<head>` / `<template>` i znaczników zamykających | Nasz pre-parser przeszukiwał listę ukrytych znaczników przy każdym zamknięciu |
| `style="color:f(f(f(…"` (600 nawiasów, 1,2 KB) kończył zapis błędem 500 | `RecursionError` w tinycss2 |

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| `style` | Token błędu jest pomijany: zła deklaracja znika, reszta stylu zostaje |
| Głębokie drzewo | Limit 80 otwartych elementów liczy sam parser. Po przekroczeniu treść jest składana drugi raz ze spłaszczonego zapisu: najwyżej 32 znaczniki otwarte naraz, kolejne pominięte, tekst zostaje |
| Szerokie drzewo | Walker pamięta pozycję rodzica |
| Treść wprost w tabeli | Ponad 1000 takich elementów tabele są rozbierane na tekst |
| Atrybuty | Znacznik z ponad 64 atrybutami trafia do parsera z pierwszymi 64 |
| Ukryte znaczniki | Licznik i pierwsze otwarcie każdego rodzaju zamiast przeszukiwanej listy; zachowanie bez zmian |
| Zagnieżdżony CSS | Przepełnienie rekurencji usuwa cały styl |
| Zwykła treść | Bez zmian bajt w bajt |

Bez migracji i bez zmian w trasach.

Pierwsza wersja poprawki liczyła zagnieżdżenie w pre-parserze, przed
parserem HTML. Przegląd pokazał, że to nie wystarcza: `<li><h1>` albo
`<b><div></b>` powtarzane w kółko budują drzewo na tysiące poziomów, choć
w tekście nic nie wygląda na zagnieżdżone (100 KB: 27 s, 500 KB: ponad 25
minut). Stąd limit w samym parserze.

## Pomiar (czas procesora, treść ok. 500 KB)

Pomiary „przed” pochodzą z dwóch przeglądów i z własnych prób; komputer był
w tym czasie obciążony innymi sesjami, więc zegar ścienny bywał kilka razy
dłuższy niż czas procesora. Kolumna „po” to czas procesora.

| Treść | Przed | Po |
|---|---|---|
| 100 000 niedomkniętych `<div>` | ok. 270 s | 0,5 s |
| `<li><h1>` × 62 500 | nie skończyło się w 25 min | 1,1 s |
| `<b><div></b>` × 41 600 | 613 s | 0,6 s |
| `<span><div></span>` × 35 700 | 275 s | 0,4 s |
| 33 000 akapitów `<p><b>x</b></p>` | 46 s | 2,8 s |
| 62 000 `<b>x</b>` wprost w `<table>` | 37,5 s | 3,8 s |
| 20 000 atrybutów w jednym `<p>` | ponad 25 s | 0,03 s |
| 50 000 `<head>` i 30 000 znaczników zamykających | ponad 45 s | 0,3 s |
| 1500 stanowisk zwykłego CV (130 KB) | bez zmian | 0,45 s |

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Odtworzenie przed poprawką | potwierdzone | 19 z 26 testów pierwszej wersji czerwonych na kodzie sprzed zmiany (10 dla `style`, 9 dla zagnieżdżenia); pomiary czasu w tabeli wyżej |
| Nowe testy | zielone lokalnie | `tests/test_html_sanitizer_limits.py`: 73 testy, w tym 7 największych przyjmowanych treści poniżej limitu czasu procesora i test żywotności zaczepów w bleach |
| Zwykła treść bez zmian | potwierdzone | 11 wzorców CV równych `bleach.clean`; próba losowa 45 000 dokumentów do 600 znaczników: 0 różnic; pre-parser na 80 000 losowych dokumentów identyczny z wersją z `main`; 12 wzorców ukrytych znaczników zapisanych z kodu sprzed zmiany |
| Wrogie kształty | potwierdzone | 1200 losowych jednostek powtórzonych do 120 KB: najwolniejsza 2,6 s; najwolniejsze skalują się liniowo do 500 KB |
| Pozostałe testy sanitizera | zielone lokalnie | wszystkie pliki testów korzystające z `sanitize_cv_html` (części bez bazy); części z bazą w CI |
| Przegląd bezpieczeństwa | dwa przebiegi, uwagi naniesione | 1. przebieg: licznik w pre-parserze nie ogranicza parsera → limit przeniesiony do parsera. 2. przebieg: walker identyczny ze stockowym na 20 000 drzew i 8 000 dokumentów, brak obejścia limitu, drogi awaryjne trzymają allowlistę (444 sprawdzenia); wskazane trzy starsze ścieżki (atrybuty, ukryte znaczniki, rekurencja CSS) naprawione w tym PR-ze |

## Świadomie poza zakresem

- **Gęsty tekst w jednym węźle** (setki tysięcy zbłąkanych `<` albo encji
  w jednym akapicie): html5lib dokleja tekst kawałek po kawałku i liczy pozycję
  błędu od początku fragmentu. Przegląd zmierzył 7–11 s dla 500 KB na
  obciążonej maszynie; na spokojnej niepotwierdzone. To sekundy, nie minuty,
  i wymaga treści, której edytor nie tworzy.
- Zaczepy korzystają z wnętrza bleach 6.4.0 (wersja przypięta w
  `requirements.txt`, biblioteka nie jest już rozwijana). Przy zmianie wersji
  pilnuje ich `test_parser_hooks_are_alive`.
- Przeniesienie sanitizera z pętli zdarzeń do puli wątków w handlerach —
  maksymalna treść zajmuje teraz 1–4 s procesora zamiast minut, ale nadal
  w pętli.
- Dokument z ponad 80 poziomami zagnieżdżenia (20 tabel układu jedna w drugiej,
  39 cytowanych odpowiedzi z poczty, 40 poziomów listy) albo ponad 1000
  elementów wpisanych wprost w tabelę traci część struktury; tekst zostaje.
  Zwykłe CV ma 7–8 poziomów, wklejone z Worda kilkanaście.

## Po wdrożeniu (12.10.2026)

Próby lokalne i CI biegły na Pythonie 3.12, produkcja na 3.13. Po wdrożeniu
(`/api/health` → `9c58ead1d`, 20:59 UTC) sprawdzone tylko do odczytu w kontenerze
backendu (Python 3.13.14): zachowanie na wzorcach bez zmian, zaczepy w bleach
żywe, wrogie treści 500 KB kosztują 0,02–1,7 s czasu procesora.
