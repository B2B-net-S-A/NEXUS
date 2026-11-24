# Rozliczenia: zestawienie dostawcy BNP Paribas CIB („Vendor's file”) daje MD osoby

<!-- indeks: BNP Paribas CIB, Vendor's file, worksheet.xlsx, RRRRMM_B2B.net S.A._worksheet, Resource Name, Act MD, Act Hours, Zestawienie godzin, Potwierdzam zestawienie, vendor_file, Czeka na liczbę MD, Wysłane, #3755 -->

Od 24.11.2026, po powtórce 7s próby rozliczeń IX–X 2026 (z odtworzonymi Wysłanymi,
#3755). U BNP Paribas CIB koordynatorka wysyła klientowi plik
„RRRRMM_<firma>_worksheet.xlsx” z prośbą o akceptację czasu pracy. Klient odpisuje
„Potwierdzam zestawienie”. Czytnik poczty zapisuje plik z Wysłanych i odpowiedź
klienta jako dokumenty osoby, ale pliku nikt nie czytał. Rozliczenie stało w
„Czeka na liczbę MD”, a Finanse fakturowały MD z pliku (IX 11,5, X 21,5).

## Reguła

`client_settlements/vendor_file.py` czyta arkusz z nagłówkiem „No. · ID · Service ·
Year · Month · Resource Name (without Polish letters) · Resource Type · Act MD ·
Act Hours” (wiersz na osobę). `service._read_file` pyta go przed Time Sheet
w godzinach.

- **Osoba**: wiersze z imieniem i nazwiskiem z kontraktu, w dowolnej kolejności,
  bez polskich liter. Plik bez tej osoby nic nie daje. U tego klienta kontrola
  nazwiska jest wyłączona, więc plik innej osoby dałby jej MD bez żadnej uwagi.
- **Miesiąc**: z kolumn „Year” i „Month” (nazwa angielska, polska albo numer).
  Kilka wierszy osoby z różnych miesięcy daje plik bez liczby.
- **MD**: „Act MD”, kilka wierszy osoby za jeden miesiąc sumujemy. „Act Hours”
  inne niż MD × `fields.md_hours` (tolerancja 0,01 h) daje plik bez liczby.
  Nie zgadujemy, który zapis jest dobry, więc MD wpisują Finanse.

Kontrole są jak przy dokumencie z deklarowaną sumą (`declared.evaluate`): miesiąc,
osoba, limit MD. Do tego `proof.accept_has_hours` z godzinami z pliku. „Potwierdzam
zestawienie” bez liczby wystarcza, bo godziny są w pliku za ten miesiąc (decyzja
z 23.11.2026, `mail_text.judge`).

## Uwaga do reguł klienta

Na kopii produkcji z 24.11.2026 BNP Paribas CIB ma włączone tylko `ci.ksef`
i `ci.buyer_nip`. Kontrole dowodu pracy (`proof.*`) są wyłączone, więc MD z pliku
przechodzą bez sprawdzenia akceptacji klienta w mailu. Plik pochodzi z naszych
Wysłanych. Żeby NEXUS wymagał odpowiedzi klienta, Finanse włączają
`proof.accept_has_hours` w regułach klienta.

## Pomiar (klon `nexus_staging_klodko_v7s`, transakcja z ROLLBACK, 24.11.2026)

`service.recompute_and_store` 371 rozliczeń IX–X na kodzie z `main` i z gałęzi.
Zmieniły się dwa rozliczenia, oba u tej osoby:

- IX: z „Sprawdzania” bez MD na „ok” z 11,5 MD, równo z fakturą;
- X: z „Sprawdzania” bez MD na „ok” z 21,5 MD, równo z fakturą.

Pozostałe 369 rozliczeń jest bez zmian.

Pliki pokrewne: `rozliczenia-czytniki-plikow-klientow.md`,
`rozliczenia-odpowiedz-klienta-na-nasz-wyslany-mail.md`.
