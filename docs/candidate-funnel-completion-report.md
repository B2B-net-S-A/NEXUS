# Ścieżka kandydata: rekruter + Delivery Lead — raport (04.10.2026)

Analiza i makiety: https://claude.ai/artifact/R6yvH1ADUD8U8UZdgpLdbu.
Decyzje Artura z 04.10.2026: D1 bramka „Zweryfikowany” na serwerze, D2 ręczne
zatrudnienie z podaniem, jak podpisano umowę, D3 jedna sprawa zamówienia dla
DL i Finansów, D4 ślad poprawek DL w karcie rekomendacji.

## Stan przed

- Kandydat przechodził lejek przez ~39 okien; kartę dało się przesunąć na
  6 sposobów, z różnymi bramkami — warsztat rozmów nie znał wymogu debriefu,
  kolejka Cpro odsyłała ostrzeżenie na Tablicę.
- Ręczne przekazanie rekrutacji nie dzwoniło do rekrutera; dzwonek „CV do
  przeglądu” otwierał dok, nie przegląd DL.
- Te same dane osoby w trzech panelach (dok, szeroki warsztat, przegląd DL),
  które nakładały się na siebie; fakty o osobie w kilku miejscach.
- „Zweryfikowany” bez arkusza i stawki przechodził; ręczne „Zatrudniony” nie
  mówiło, jak podpisano umowę; po ręcznym zatrudnieniu nikt nie dostawał
  sprawy zamówienia.
- Ruch w rekrutacjach założonych w NEXUSIE (9 dni przed zmianą): 28 dodań,
  6 screeningów, 6 weryfikacji, 4 QC CV, 2 CV wysłane, 1 rozmowa u klienta,
  5 przepuszczeń QC.

## Zmienione

| PR | Co |
|---|---|
| #2010 | Dzwonek przy ręcznym przekazaniu; przegląd DL z wiersza serwera (`GET /api/board-tasks/dl-review-row`) i z linku `?review=1`; warsztat bez drugiej kopii ruchu |
| #2011 | D1: 409 `VERIFIED_REQUIREMENTS_MISSING`; D2: `hired_signed_via` (422 bez niego); okna na froncie |
| #2012 | D3: jedna sprawa „uzupełnij zamówienie” (DL + Finanse), zamyka się dopiero bez braków; D4: „Piotr poprawił: stawka, motywacja” w „Twoje CV w drodze” |
| #2014 | Jedna droga ruchu dla ekranów spoza Tablicy (`usePipelineMoveCore`); karta „kto ma ruch · krok · dni” z ikonami; QC CV w doku na „Zweryfikowanym” |
| #2015 | Jeden panel osoby naraz (ukryty, nie odmontowany); fakty pod nazwiskiem; „Biorę” i „Nie odebrał” w panelu |
| PR 6 | Wybór i potwierdzenie terminu od klienta oraz ocena prepu w panelu; krok „Umowa” (umowa, podpis, zamówienie); Tablica bez kalendarza w nowej karcie; pulpit „Twój ruch / U innych” |

## Świadomie węższy zakres niż w planie

- **Jeden nowy komponent panelu** zamiast doku, warsztatu i przeglądu DL
  (~3,6 tys. linii) — nie zrobiony. PR 5 i 6 rozwiązują problemy z analizy
  (nakładanie, fakty w kilku miejscach, rozmowa i umowa poza panelem) na
  istniejących komponentach.
- **„Oznacz jako podpisaną” w panelu** — panel prowadzi do rejestru
  z wyszukaną umową; okno potwierdzenia (z obsługą różnic warunków) zostaje
  w Generatorze, bo przeniesienie wciąga do Tablicy moduł 6 tys. linii.
- **Liczba uwag QC w `move-requirements`** — dok liczy QC na żądanie.
- **Hook Tablicy wysyła ruch przez `api.post`** — 19 testów rozróżnia ten
  kanał; rozpoznanie odmów jest wspólne.
- **„U innych”** składa się z istniejących list (CV w drodze, wysłane do Cpro);
  oczekiwanie na podpis i decyzję klienta poza „CV wysłane” nie ma osobnych
  wierszy.

## Do sprawdzenia po 2 tygodniach (~18.10.2026)

- Odmowy 409 `VERIFIED_REQUIREMENTS_MISSING` i 422 `HIRED_SIGNED_VIA_REQUIRED`
  w logach — czy rekruterzy uzupełniają arkusz zamiast porzucać ruch.
- Liczba przepuszczeń QC (było 5 na 4 karty w QC) i czas od „QC CV” do
  „CV wysłane”.
- Sprawy „uzupełnij zamówienie” otwarte dłużej niż 7 dni.
