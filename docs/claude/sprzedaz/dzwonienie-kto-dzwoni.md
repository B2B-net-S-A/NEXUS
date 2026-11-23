# Dzwonienie: kto dzwoni? Szukanie po numerze — decyzje Artura 23.11.2026
<!-- indeks: Kto dzwoni, who-calls, calling_lookup.py, ostatnie 9 cyfr, phone_tail, numer ze spacjami +48, kontakty firm telefon i komórka, sprzeciw w wynikach, wyszukiwanie Tabeli po cyfrach, SEARCH_PHONE_DIGITS -->

Zgłoszenie osób dzwoniących (23.11.2026): klient oddzwania na numer, pod który się nie
dodzwoniliśmy, a telefon pokazuje sam numer. Pole „Firma, osoba, numer” w Tabeli
porównywało tekst: na kopii produkcji z 23.11 562 z 4953 numerów list (11%) zapisano ze
spacjami („+48 500 058 777”), więc wpisane 500058777 dawało „Nikt nie pasuje”. Pole
szukało też tylko w listach, a w kontaktach firm jest ok. 11 tys. osób z numerem.
Makiety: prywatny artefakt https://claude.ai/artifact/Gxjj6erDvtVBijP4S73g6p (punkt 3).

Kod: `backend/app/services/sales/calling_lookup.py`, trasa
`GET /api/sales/calling/who-calls?phone=` w `api/sales_calling.py` (bramka „Sprzedaż:
podgląd”), warunek cyfr w `calling.list_records`, front `calling/WhoIsCalling.tsx`
w `CallingActions`. Bez migracji.

## Zasady

- **Porównujemy ostatnie 9 cyfr** (`phone_tail`, w SQL `regexp_replace` + `right`):
  +48, 0048, spacje i myślniki nie mają znaczenia. Krótszy numer to 422, a pole mówi
  „Wpisz cały numer”.
- **Gdzie szukamy:** rekordy list dzwonienia wszystkich osób (z osobą, która dzwoni,
  stanem, ostatnią rozmową, powrotem i kampanią) i kontakty firm (telefon i komórka,
  bez archiwum). Kontakt, który ma już rekord, nie stoi drugi raz.
- **Odpowiedź nie oddaje żadnego numeru**: numer zna osoba, która go wpisała.
  Rekord albo kontakt ze sprzeciwem jest na liście z plakietką „Nie kontaktować”:
  oddzwaniający klient ma wyjść jako znany, nie jako „brak”. W Tabeli sprzeciwu dalej
  nie ma (`dzwonienie-kampanie-i-import-listy.md`).
- **Pole widzi każdy z „Sprzedaż: podgląd”**; kampanie i import zostają dla edycji.
  Wynik prowadzi do karty firmy („Na liście dzwonienia”, „Zaloguj rozmowę”).
- **Tabela** szuka też po samych cyfrach, gdy wpis ma co najmniej 6 cyfr
  (`SEARCH_PHONE_DIGITS`).
- Bez indeksu: kilka tysięcy rekordów i kilkanaście tysięcy kontaktów. Gdy kontaktów
  będzie rząd więcej, dołóż kolumnę z cyframi i indeks zamiast liczenia przy zapytaniu.

Testy: `backend/tests/test_sales_calling_lookup.py`, w
`frontend/src/components/sales/__tests__/sales-calling.test.tsx` „Kto dzwoni?”.
