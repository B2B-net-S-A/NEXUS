# Rozliczenia: karta ewidencji pracy VeloBanku czytana jak Time Sheet

<!-- indeks: karta ewidencji pracy, Karta ewidencji pracy_MM.RRRR, VeloBank, Velo, Tabela miesięczna, NAZWISKO I IMIĘ, Czas pracy, Suma przepracowanych dni, Nie rozpoznano szablonu RCP, timesheet.parse_rows, _CARD_COLUMNS, _clock_hours, arkusz zbiorczy, signed_sheet, 21,625 -->

Od 24.11.2026, po powtórce 7 próby rozliczeń IX–X 2026. Część osób u klienta
z arkuszami zbiorczymi (Velo) przysyła zamiast Time Sheet własną kartę klienta,
„Karta ewidencji pracy_MM.RRRR_<osoba>.xlsx”. Nikt jej nie czytał. Rozliczenie
miało uwagę „Nie rozpoznano szablonu RCP” i status „warnings”, a MD brało z
podpisanego arkusza zbiorczego (#3909), w którym MD są zaokrąglone do setnych:
21,63 zamiast 21,625 MD z faktury Finansów.

## Reguła

`timesheet.parse_rows` czyta kartę jako wariant Time Sheet:

- nagłówek „NAZWISKO I IMIĘ” to osoba (jak „Consultant(s)”);
- tabelę rozpoznajemy tylko w arkuszu z tytułem „Tabela miesięczna”, po kolumnach
  „Dzień” i „Czas pracy”;
- „Czas pracy” to czas w formacie godzin: czas Excela, „8:00” albo `timedelta`;
- pusty „Czas pracy” (weekendy, dni wolne, wiersz z datą z innego miesiąca
  przeniesiony z szablonu) nie jest wpisem;
- liczba zamiast czasu daje plik nierozpoznany, bo nie wiadomo, czy to godziny,
  czy ułamek doby. MD wpisują wtedy Finanse, jak dotąd;
- „Suma przepracowanych dni” kończy tabelę. Jest w dniach (21:37 = 21,625 MD),
  więc nie porównujemy jej z godzinami.

Dalej działa jak każdy Time Sheet (`timesheet.evaluate`): MD = godziny /
`fields.md_hours` (173 h = 21,625 MD), miesiąc z dat, osoba, limit dnia i miesiąca.
`proof.excel_with_mail` spełnia podpis klienta na arkuszu zbiorczym (`signed_sheet`,
tylko `by_client`). Zgodność z arkuszem sprawdza `service._signed_checks`: różnica
21,625 i 21,63 to 0,005 MD i nie daje uwagi.

## Dlaczego czytnik, a nie samo wyciszenie uwagi

Rozważyliśmy prostszy wariant: nie dawać „Nie rozpoznano szablonu RCP”, gdy MD daje
podpisany przez klienta arkusz. Status przeszedłby na „ok” z MD z arkusza, czyli
21,63 zamiast 21,625 za IX, więc z inną kwotą niż faktura. Czytnik daje MD
z godzin dokładnie, a plik, którego nie rozumie, dalej zostawia Finansom.

## Pomiar (klon `nexus_staging_klodko_v7`, transakcja z ROLLBACK, 24.11.2026)

`service.recompute_and_store` 369 rozliczeń IX–X na kodzie z `main` i z gałęzi.
Zmieniły się dwa rozliczenia, oba u tej osoby:

- IX: z „warnings” i 21,63 MD na „ok” i 21,625 MD, równo z fakturą;
- X: z „warnings” i 22 MD na „ok” i 22 MD.

Pozostałe 367 rozliczeń jest bez zmian.

Pliki pokrewne: `rozliczenia-podpisany-arkusz-zbiorczy.md`,
`rozliczenia-czytniki-plikow-klientow.md`.
