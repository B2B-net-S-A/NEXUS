# Rozliczenia: kilka Time Sheetów na różne prace, raport BIK w Wordzie, stopka RODO (próba VI–VIII 2026)

<!-- indeks: merge_projects, Time Sheet z 2 plików, dwa PDF-y dwa zamówienia, Polkomtel dwa projekty, poprawiona wersja Time Sheetu, Czas (godz.), Czas- (godz.), BIK DOCX, raport BIK w Wordzie, osoba z nazwy pliku BIK, Act MD z jednostką, 17,5MD, Vendor's file, stopka RODO, 2016/679, Akceptacja za inny miesiąc kwiecień 2016 -->

Od 25.11.2026. Powtórka próby rozliczeń na VI–VIII 2026 (klon kopii produkcji, poczta
01.06–15.10) pokazała cztery luki odczytu. Prawda to suma pozycji faktur Finansów
z nazwiskiem osoby, bo faktura bywa podzielona na zamówienia i tylko jedna ma powiązanie.

## Kilka Time Sheetów jednej osoby w miesiącu (`timesheet.merge_projects`)

Konsultant Polkomtelu pracuje na dwóch zamówieniach i co miesiąc przysyła dwa PDF-y
„Time Sheet”, każdy z innym opisem prac. W VI: 152 h i 128 h (te same dni po 8 h i 4 h),
Finanse fakturowały 35 MD na dwa zamówienia. NEXUS czytał jeden plik.

- Plik dochodzi do arkusza, gdy jest tej samej osoby, za ten sam miesiąc i opisuje inne prace:
  projekt z wiersza albo nagłówka, a bez nich opis prac. Zbiory muszą być rozłączne.
- Plik z pracą, która już jest (poprawiona wersja, kopia), nie dochodzi: liczy się najnowszy,
  jak przed zmianą.
- Wiersze bez projektu dostają projekt pliku (najczęstszy opis), więc „Projekty: …”
  pokazuje godziny osobno. Informacja „Time Sheet z N plików” mówi, że godziny są zsumowane.
- Podziału na zamówienia z dwóch plików nie robimy: stawki linii sprawdza dalej
  `order.line_rate`, a podział od klienta daje `order_split`.

## Raport BIK: „Czas (godz.)”, Word, osoba z nazwy pliku (`timesheet_bik`)

- Nagłówek godzin „Czas (godz.)” albo „Czas- (godz.)” i kolumna „Zadanie” w XLSX.
- Ten sam szablon w DOCX: akapity „Za miesiąc …”, „Imię i nazwisko: …” nad tabelą
  „Zadanie · Data · Czas (godz.)” i wiersz „Suma”. Czytamy go jak tekst PDF (`text_rows`).
  W `service._read_file` DOCX bez protokołu Orlenu próbuje czytnika BIK.
- Arkusz bez pola „Imię i nazwisko” bierze osobę z nazwy pliku, jak Time Sheet VeloBanku
  (`rozliczenia-time-sheet-osoba-z-nazwy-pliku.md`).

## Zestawienie BNP CIB: „Act MD” z jednostką (`vendor_file`)

„17,5MD” i „140 h” w komórce to liczby; wcześniej plik dawał „bez godzin”.

## Miesiąc akceptacji: daty sprzed lat to nie miesiąc (`mail_text.read_acceptance`)

Stopka RODO w mailu („rozporządzenia (UE) 2016/679 z dnia 27 kwietnia 2016 roku”) dawała
„Akceptacja za inny miesiąc: kwiecień 2016”. Miesiące z rokiem różnym od roku rozliczenia
o więcej niż 1 pomijamy.

## Co zostaje u ludzi

- Deklaracja w czasie przyszłym („w dniach 27–31 będę niedostępna”) dalej nie jest
  deklaracją (`mail_declaration`, decyzja z 23.11.2026); MD wpisują Finanse.
- Skan PDF bez tekstu i arkusz z datami z innego roku (Orlen) — bez MD.
