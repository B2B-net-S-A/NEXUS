[← Powrót do README](../README.md)

# Candidates list — więcej miejsca na kandydata (mniej „naćkania")

**Data:** 2026-06-22
**Zakres:** frontend / widok listy kandydatów (`/candidates`)

## Problem

Na liście kandydatów (widok `list`, gęstość `cozy`) komórka **„Kandydat"** przy
aktywnym wyszukiwaniu renderuje 3 linie — nazwisko + email + snippet `AI: …`
(a przy notatce nawet 4). Blok zajmuje ~57 px, a wiersz miał tylko 72 px, więc
nazwisko niemal dotykało linii podziału — „za dużo tekstu w jednym miejscu",
wizualnie zatłoczone.

## Zmiana

Podniesiona wysokość wiersza wirtualizera w
[`CandidatesListV2.tsx`](../frontend/src/components/v2/pages/CandidatesListV2.tsx):

| Gęstość  | Było  | Jest  |
|----------|-------|-------|
| `cozy`   | 72 px | 92 px |
| `compact`| 52 px | 64 px |

Dzięki temu 3-liniowy blok „Kandydat" ma ~17 px oddechu góra/dół (zamiast ~7 px),
a wiersze przestają być zatłoczone. Bez zmiany liczby kolumn, treści ani layoutu —
czysto wertykalny oddech. Komentarz odwołujący się do starych wartości (52/72)
zaktualizowany.

## Weryfikacja

- Podgląd nowej wysokości wstrzyknięty na żywo do prod (DOM override) i potwierdzony
  screenshotem (Chrome MCP) — blok „Kandydat" wyśrodkowany z marginesem, brak
  dotykania linii podziału.
- Brak testów/snapshotów zależnych od 52/72 (sprawdzone grepem — trafienia `52`
  to współrzędne geo, nieistotne).

## Znane ograniczenia / poza zakresem

- Poziome ucinanie długich nazwisk (`Cyryl Khrystsenk…`) to szerokość kolumny,
  osobny temat — nie ruszane.
- Duplikacja emaila (w komórce „Kandydat" i w kolumnie „Email") — świadomie
  zostawiona, użytkownik prosił o *więcej miejsca*, nie o usuwanie treści.
