# Dzwonienie: jednorazowe przeniesienie Excela osób dzwoniących — decyzje Artura 11.11.2026
<!-- indeks: Przenieś Excel dzwoniących, arkusz = osoba, kolor wiersza = wynik, odcień czerwony żółty niebieski zielony, komentarz po rozmowie, Ponowny kontakt, wiersz Podsumowanie, sales_call_day_totals, duplikat numeru w późniejszym arkuszu, bieg na sucho, calling_excel.py, RecordOverride -->

Powód: do 11.11.2026 osoby dzwoniące prowadziły arkusz Excela na osobę. Wynik był kolorem
wiersza, komentarz pisano ręcznie, a dzień kończył się ręcznym wierszem „Podsumowanie”. Bez
przeniesienia kolejka dostałaby te osoby jako nowe i ok. 640 „nie zainteresowanych”
dostałoby drugi telefon. Makiety: https://claude.ai/artifact/5yiSa8H1BW5v2iewpKFFHX.

Kod: `backend/app/services/sales/calling_excel.py`, trasy
`POST /api/sales/calling/campaigns/{id}/excel/preview` i `.../excel` („Sprzedaż: edycja”,
limit zapytań), front `frontend/src/components/sales/calling/ExcelTransferDialog.tsx`.
Do okna prowadzi link w oknie „Importuj listę”, a nie stały przycisk, bo to czynność
jednorazowa.

## Jak czytamy plik

- **Arkusz = osoba.** Przypisanie wybiera człowiek w oknie. Podpowiedź bierze imię z nazwy
  arkusza („Bianca” → jedyna osoba z „Sprzedaż: edycja” o tym imieniu). Bez przypisania
  wszystkich arkuszy zapis dostaje 422.
- **Wynik**: najpierw kolor wiersza, i to po odcieniu, bo arkusze mają różne czerwienie
  (`color_state`):
  - czerwony = „Nie zainteresowany” (powrót za pół roku);
  - żółty = „Oferta ogólna wysłana”;
  - niebieski i zielony = „Umówione spotkanie” (rekord zamknięty).

  Bez koloru wynik idzie ze słów komentarza (`comment_state`, literówki bez ogonków).
  Komentarz bez rozpoznanego wyniku to rekord nowy z komentarzem w notatce, liczony
  „do przejrzenia”.
- **Data powrotu** z „Ponowny kontakt” albo z komentarza „zadzwonić 12.11”. Data
  z przeszłości oznacza „dziś”. Bez daty obowiązuje domyślna data wyniku z kolejki.
  Rok brany jest z dnia przeniesienia, a data ponad 60 dni naprzód oznacza rok wcześniej.
- **Wiersz „Podsumowanie”** (z „wykonane telefony”) nie jest osobą. Liczby idą do
  `sales_call_day_totals` (źródło `excel`, jedno na osobę i dzień, ponowny zapis nadpisuje).
  Arkusze miały dwa formaty: „Rozmowy: 19” w jednej komórce albo etykieta i liczba obok.
  Dzień z dwoma podsumowaniami bierze późniejsze, a podgląd pokazuje, ile takich dni było.
- **Ten sam numer w dwóch arkuszach** zostaje w późniejszym arkuszu, bo przekazania robiono
  kopiowaniem wiersza do arkusza następnej osoby.
- **Komentarz i „Uwagi”** idą do notatki rekordu („Z Excela: …”). LinkedIn idzie do kontaktu
  (jak w imporcie).

## Zapis

- Te same bramki co import listy (`calling_import.apply_import` z `overrides`): sprzeciw,
  klient NEXUSA, ktoś inny dzwoni, już w kampanii albo otwarta szansa (spotkania sprzed
  kolejki są już szansami), brak telefonu. Ten sam plik drugi raz niczego nie dubluje.
- Rekord z wynikiem ma `attempts = 1` i datę powrotu. **Nie zakładamy wpisów w dzienniku
  rozmów**, bo „Skuteczność” liczyłaby wtedy setki telefonów z dnia przeniesienia. Historia
  sprzed kolejki to `sales_call_day_totals`.
- Podgląd jest biegiem na sucho i niczego nie zapisuje. Zapis na produkcji klika człowiek
  (decyzja Artura: po jego „tak”).

Testy: `backend/tests/test_sales_calling_excel_transfer.py`, część „przeniesienie Excela”
w `frontend/src/components/sales/__tests__/sales-calling.test.tsx`.
