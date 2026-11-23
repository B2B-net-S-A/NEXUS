# Pula porcji: świeże CV tuż pod progiem wchodzą ponad 150
<!-- indeks: `auto_full_review._fresh_extras`, `FRESH_DAYS`, `FRESH_BELOW_CUT`, `FRESH_POOL_EXTRA`, `fresh_cv` w dowodach puli, `is_fresh_extra`, `job_autofill_pool` -->

Decyzja Artura z 23.11.2026 (wariant A). Raport i pomiar:
https://claude.ai/artifact/F6W8syMoFMNABxqrL5ra2J.

Zgłoszenie: „ręczne wyszukiwanie jest lepsze niż porcja”. Pomiar na kopii z 23.11:
ręcznie wysłani do klienta nie trafiają do puli głównie z wyboru rekrutera, nie przez
błąd oceny. Ich podobieństwo CV jest na 97. centylu wobec 98. czołówki puli, a stoją
o włos za progiem (np. 72,0 przy 72,2). Żadna zmiana wag składowych nie podnosi puli
ponad 49% ręcznie wysłanych, zdjęcie bramki krytycznych pogarsza P@5 (0,155 → 0,150),
a cięcie puli wynikiem z punktami „Znamy tę osobę” spycha ją z 62% do 39% wysłanych.
Wyróżnia ich świeżość: CV z ostatnich 30 dni ma 25% ręcznie wysłanych i 9% czołówki puli.

## Reguła

- **Dodatek do puli, nie premia w wyniku.** Po 150 najlepszych i po „wysłanych wcześniej”
  (`_sent_before_extras`, Z1) przegląd dokłada do `FRESH_POOL_EXTRA` (30) osób ze świeżym
  CV, których wynik jest najwyżej `FRESH_BELOW_CUT` (2) pkt pod ostatnim miejscem puli
  i nie niżej niż `sent_before.MIN_SCORE`. Nikt z 150 nie wypada, procent na karcie
  i `fit_score` się nie zmieniają.
- **Świeże** = `candidates.created_at` albo aktywność `cv_uploaded` / `created_from_cv`
  w ostatnich `FRESH_DAYS` (30) dniach. Nie używaj `cv_parsed_at`: masowe ponowne odczyty
  ustawiły go 59 tys. osób w 30 dni.
- **Pula niepełna** (mniej niż 150 dopuszczonych) nie ma progu, więc dodatku nie liczymy.
- Ten sam filtr co pula: dopuszczony, oceniony, zmierzony, bez innej roli i bez osób
  z rekrutacji. Dowody wiersza mają `fresh_cv: true` (`is_fresh_extra`).
- **Kolejność w puli bez zmian** (wynik + „Znamy tę osobę” + premia porcji). Premia +2 pkt
  także w kolejce nie dawała nic ponad sam dodatek (R@20 i P@5 bez zmian), więc jej nie ma.
  „Nowi w bazie najpierw” (`nowi-w-bazie-najpierw.md`, 14 dni, od progu) czyta pulę,
  więc dopiero ten dodatek daje mu osoby spod progu 150.

## Pomiar (50 ostatnich pełnych przeglądów z 21–22.11, 305 wysłanych od 01.10)

| pula | ręcznie wysłani w puli | wszyscy wysłani w puli | R@20 | P@5 | MRR |
|---|---:|---:|---:|---:|---:|
| 150 + wysłani wcześniej (dziś) | 50,7% | 65,9% | 17,4% | 0,141 | 0,262 |
| + świeże do 2 pkt pod progiem | 54,1% | 68,9% | 17,4% | 0,141 | 0,262 |

Średnia wielkość puli 171 → 185. Do 3 pkt: 55,4% / 69,8%, do 5 pkt: 56,1% / 70,2%.
Kolejka w pomiarze = wynik + „Znamy tę osobę”; świeżość wysłanych liczona do 2 dni przed
dodaniem, żeby nie liczyć CV wgranego przez rekrutera tuż przed dodaniem.

**Do sprawdzenia po tygodniu:** w „Insights → Jakość podpowiedzi systemu” odsetek
ręcznie wysłanych z kategorią „Poniżej puli 150” (`sent_vs_system`); karty z `fresh_cv`
w puli i ich decyzje w porcji.

Testy: `backend/tests/test_auto_full_review.py::test_pool_extras_take_fresh_people_just_below_the_cut`.
