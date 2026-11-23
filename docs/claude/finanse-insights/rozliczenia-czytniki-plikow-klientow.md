# Rozliczenia: czytniki MD z plików klientów spoza RCP BNP

<!-- indeks: czytniki plików, Time Sheet PDF, polski Time Sheet, Imię Nazwisko, Łączna liczba godzin, Okres od, BIK PDF, Rozliczenie czasu pracy, ERGO Monthly confirmation, NN Ilość MD, rozliczeniakontraktorow, Orlen protokół, Roboczodni, Sugerowane wynagrodzenie, declared, _other_files, inny plik miesiąca, proof.month bez MD, Sprawdzanie -->

Od 23.11.2026. W próbie rozliczeń IX–X 2026 (kopia produkcji z 23.11, reguły klientów
z produkcji) 60 przypadków poza Nordeą stało w „Sprawdzaniu” bez MD, choć plik był w poczcie.
Czytniki z `client_settlements/` rozpoznawały tylko RCP BNP, KCP/Redmine, PKO, Time Sheet
w XLSX, raport BIK i KEŚU. Cel Artura: od grudnia NEXUS rozlicza z poczty bez panelu.

## Wzory

| Wzór | Moduł | Skąd MD |
|---|---|---|
| Nasz „Time Sheet” w PDF (Bosch, Polkomtel, ERSTE, Cardif) | `timesheet.text_rows` | godziny z wierszy dat / `fields.md_hours`; „-” to pusta komórka |
| PDF „<osoba> Okres od: · Projekt: … Okres do: · Data Dzień Opis Godziny Rozliczalne” (Bosch) | `timesheet.text_rows` | jak wyżej; pusta kolumna „Rozliczalne” znika z tekstu, więc wystarcza jedna liczba |
| Polski „Time Sheet” XLSX: „Imię Nazwisko · Data · Opis zadań · Liczba godzin · Uwagi” (Bosch, ERSTE) | `timesheet.parse_rows` | tylko w arkuszu z tytułem „Time Sheet”, bo ta sama tabela jest w raporcie BIK |
| BIK PDF bez linii siatki: „Za miesiąc wrzesien 2026 · Zadanie Data Czas (godz.) · Suma 24 h” albo „Miesiąc 01.09.2026 · dni 1-09 · Razem 160” | `timesheet_bik.text_rows` | wiersze, a przy rozbieżności „Suma” z ostrzeżeniem |
| ERGO „Monthly confirmation of hours worked” | `confirmation_ergo` | „Total 168,00” / `fields.md_hours` |
| NN: mail „Rozliczenie pracownika … za okres 09-2026” z „Ilość MD” | `mail_nn` | MD wprost (akceptacja klienta), bez przeliczania |
| Orlen: protokół DOCX/PDF „OKRES ROZLICZENIOWY” | `protocol_orlen` | „Sugerowane wynagrodzenie”: „132 h x 150 PLN” → godziny / `fields.md_hours`, „22 x 1200 PLN” → 22 MD |

Orlen: faktury Finansów liczą MD z godzin, więc „22 MD - po 6h” to 132 h = 16,5 MD, nie 22.
Gdy przy kwocie nie stoi „h” ani „MD”, rozstrzyga stawka z protokołu: „(150zł x8h = 1200zł MD)”,
„175 pln x 8= 1400 PLN/MD”, „90 PLN/h”. Kilka różnych kwot (kilka osób) nie daje MD.

ERGO, NN i Orlen mają wspólne kontrole w `declared.evaluate` (miesiąc, nazwisko, limit MD).

## Plik za inny miesiąc

Plik, którego miesiąc jest inny niż rozliczany (szablon z rokiem 2025, Time Sheet za
październik w paczce wrześniowej), nie daje MD. Przy włączonej `proof.month` to kontrola
z jej poziomem, przy wyłączonej informacja „… za inny miesiąc” (`declared.month_mismatch`),
żeby przypadek nie stał w „Sprawdzaniu” bez powodu. Dotyczy Time Sheet, BIK, ERGO, NN i Orlenu.
Time Sheet i raport BIK bez dat zachowują się jak dotąd (MD i kontrola `proof.month`);
ERGO, NN i Orlen bez miesiąca nie dają MD.

## Inny plik miesiąca

`_pick_report` bierze najnowszy PDF/XLSX miesiąca, a często jest nim faktura albo oferta.
Gdy wybranego pliku nie zna żaden czytnik, `service._other_files` próbuje pozostałych plików
miesiąca (PDF, XLSX, XLSM, DOCX, EML, MSG) i bierze pierwszy z MD. Ten plik staje się wtedy
dowodem rozliczenia (`report_document_id`). Szablon RCP BNP bez MD też oddaje plik innym
czytnikom (raport BIK w PDF wyglądał dla `rcp_bnp` jak RCP).

Plik zapisany przez czytnik poczty jako `invoice`, a nie `report` (np. potwierdzenie ERGO
za IX), do rozliczenia nie trafia: to sprawa klasyfikacji w czytniku poczty, nie czytników.

## Skala (próba IX–X, kopia 23.11)

Przypadki IX–X poza Nordeą w „Sprawdzaniu”: 60 → 32. MD dostaje 28 przypadków u 6 klientów
(Orlen 11, Bosch 6, NN 3, BIK 3, ERGO 3, Polkomtel 2). Tam, gdzie jest faktura Finansów, MD
zgadza się z nią w 20 z 22. Jeden przypadek Bosch za X: 22 MD, do faktury idzie 5,5 (reszta puli zamówienia,
tak jak u Finansów). Drugi Bosch za X: wiersze 132 h, suma w pliku 126 h, więc kontrola
`fields.md_hours`. W żadnym przypadku, który miał już MD, MD się nie zmieniło.

Poza zakresem: EY (eksport tygodni ST), zdjęcia JPG, MS Enter Price „Report on Tasks”,
Cardif „SUMA: 176h 22MD”, RITS „Rejestr czasu”, Orlen „Ewidencja Czasu Pracy”.
