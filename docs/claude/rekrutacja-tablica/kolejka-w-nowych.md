# Kolejka w „Nowych” — zespół na górze, potem system od najwyższego wyniku
<!-- indeks: `lib/new-column-queue.ts`, „Zadzwoń najpierw”, numer na karcie, `_newest_first` zostaje na serwerze, analiza 201 wysłanych CV -->

Decyzja Artura z 02.11.2026, makiety i pomiar:
https://claude.ai/artifact/8x6AxqnTihmecy2uw3Dhoh. Serwer układa kartę od
najmłodszego wejścia (`api/pipeline.py`, `_newest_first`, decyzja z 16.10.2026),
a silnik dopełniania dodaje najlepszych jako pierwszych. W każdej paczce kolejność
wychodziła więc odwrotna: najlepsza osoba stała średnio na 16. miejscu (korelacja
z wynikiem −0,80, ujemna w 151 ze 166 rekrutacji). Z 3 231 kart od systemu ruszono
12%, choć z miejsc 1–5 po wyniku do klienta szło 5,2%, a z miejsc 21+ 1,5%.

## Reguły

- **Kolejność liczy front** (`orderNewColumn`), przed filtrem „Kto dodał”, więc
  miejsce karty nie zależy od filtra, a strzałki panelu chodzą tą samą listą.
  `_newest_first` na serwerze zostaje: inne kolumny i inni czytelnicy z niego
  korzystają.
- **Na górze od najmłodszego:** osoby dodane przez zespół i karty od systemu,
  które ktoś wziął („Dzwonię”, „Biorę”, `decided`, aktywna blokada). Tak zostaje
  decyzja z 16.10: osoba dodana ręcznie nie ląduje w środku kolumny.
- **Pod nimi czekające karty od systemu:** od najwyższego wyniku z migawki
  `entry_autofill.score`; najpierw bez uwag, potem z ostrzeżeniem (`cautions`),
  na końcu z brakiem krytycznej (`criticalGapMap`). Remis rozstrzyga numer osoby.
- **Pierwszych pięć to „Zadzwoń najpierw”** z numerem na karcie
  (`CALL_FIRST_COUNT`). Nagłówki rysują się tylko wtedy, gdy kolejka ma choć
  jedną kartę. Procent na karcie się nie zmienia.
