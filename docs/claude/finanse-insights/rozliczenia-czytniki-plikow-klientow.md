# Rozliczenia: czytniki MD z plików klientów spoza RCP BNP

<!-- indeks: czytniki plików, Time Sheet PDF, polski Time Sheet, Imię Nazwisko, Łączna liczba godzin, Okres od, BIK PDF, Rozliczenie czasu pracy, ERGO Monthly confirmation, NN Ilość MD, rozliczeniakontraktorow, Orlen protokół, Roboczodni, Sugerowane wynagrodzenie, Ewidencja czasu pracy, SAP Fieldglass, timeSheet.worker.list, EY, rok w szablonie, declared, _other_files, inny plik miesiąca, proof.month bez MD, Sprawdzanie, kind_of_file, invoice zamiast report, kolejność plików, remis created_at, ten sam czas zapisu, _month_reports, graph_message_id, załączniki jednego maila, Polkomtel -B2B, KEŚU źródło, kesu_flow._source, akceptacja z Jiry bez opiekuna, przekazanie konsultanta, faktura konsultanta w paczce, faktury kosztów z maila z Jiry -->

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

Pliki „.xls” grupy Polkomtel / Cyfrowy Polsat (od 23.11.2026):

| Wzór | Moduł | Skąd MD |
|---|---|---|
| Polkomtel: „Project timesheet Report” z Jiry, tabela HTML z rozszerzeniem `.xls` | `timesheet_plus` | „Suma godzin” = suma dni / `fields.md_hours`; rozbieżność = bez MD |
| Cyfrowy Polsat: „B2B_RRRR_MM.xls”, XML Spreadsheet 2003 z BOM, wiersz = osoba × zamówienie | `timesheet_plus` | kolumna miesiąca = suma dni (osoby z kontraktu) / `fields.md_hours`; rozbieżność = bez MD |

Od 23.11.2026 (powtórka IX–X na `nexus_staging_klodko_v5`) dochodzą:

| Wzór | Moduł | Skąd MD |
|---|---|---|
| EY: eksport SAP Fieldglass „timeSheet.worker.list….xlsx”, wiersz = tydzień sob.–pt. z „ST” (bywa CSV w jednej kolumnie) | `timesheet_fieldglass` | tydzień w miesiącu w całości; tydzień na przełomie tylko pełny (ST = `fields.md_hours` × dni robocze) → `fields.md_hours` × jego dni robocze w miesiącu |
| Orlen: PDF „Ewidencja czasu pracy” (BL/B2B), wiersz = dzień z „Ilość godzin” | `ewidencja_orlen` | suma godzin dni / `fields.md_hours`; inna „Suma końcowa” albo urlop/nadgodziny z godzinami = bez MD |

Fieldglass: niepełny tydzień na przełomie, tydzień „Rejected”/„Draft” = bez MD, bo nie wiadomo,
ile godzin przypada na miesiąc. Kilka rewizji jednego ID: najwyższa. „Pending Approval” to
informacja (Finanse fakturują też tygodnie czekające na akceptację). Eksport nie ma nazwiska
konsultanta, tylko przełożonego: `proof.name_match` według poziomu reguły. Ewidencja Orlenu:
przełożonego od osoby nie da się oddzielić, więc kontrola nazwiska sprawdza, czy osoba
z kontraktu jest w odcinku „Przełożony · NAZWISKO I IMIĘ”; dwie różne osoby w wierszach = `None`.

ERGO, NN, Orlen, Polkomtel i Polsat mają wspólne kontrole w `declared.evaluate` (miesiąc, nazwisko, limit MD).

## Polkomtel i Cyfrowy Polsat: kontrakt wybiera plik

Konsultanci grupy mają kontrakt w każdej spółce, z tą samą datą startu (Polkomtel 471 /
Cyfrowy Polsat 633, 577 / 634, wcześniej 472 / 631, 473 / 632). To celowy podział: kontrakty
Polsatu powstały z jego PDF-ów „Zlecenie Wykonawcze”, każda spółka ma swoje zamówienia.
Artur 23.11.2026: dane zostają. Nadawca (skrzynka firmowa konsultanta, `plus.pl` wspólne dla
grupy) nie wskazuje więc kontraktu, a plik tak (`identity.resolve_from_sheet`):

- numer zamówienia z wiersza („Z250725003”, „Nr zlecenia”) → kontrakt z nieanulowaną linią
  tego zamówienia; przedrostek „CP”/„SAP” i spacje się nie liczą (`timesheet_plus.order_key`);
- raport Polkomtelu bez numeru albo z numerem spoza NEXUSA → kontrakt osoby u Polkomtelu
  (decyzja Artura z 23.11.2026; „Nr zlecenia” pusty w 81 z 82 raportów w archiwum);
- arkusz Polsatu z numerem spoza NEXUSA, dwie osoby w pliku albo dwa kontrakty w trafieniu → nikt.

Treść pliku wskazuje osobę tylko od skrzynki firmy, od klienta z domeny z rejestru zamówień
(wśród jego kontraktów) albo od tej samej osoby. Obcy adres nie dopisze nikomu godzin plikiem.

Do 23.11 oba pliki przepadały przy zapisie: HTML odrzucało `check_settlement_file`, a arkusza
Polsatu nie poznawało `kesu.is_kesu_file`, bo zaczyna się od BOM UTF-8. Polkomtel 471 IX to
22 MD w trzech fakturach na trzy zamówienia SAP (13,25 + 1,75 + 7), nie 1,75 MD.
Pomiar na kopii `nexus_staging_klodko_v4r2` (rollback): 471 IX 22 MD, 471 X 21 MD, 634 X 27,5 MD,
wszystkie „ok” i równe fakturom Finansów; na main żaden z trzech maili nie zostawiał dokumentu.

## Plik za inny miesiąc

Plik, którego miesiąc jest inny niż rozliczany (szablon z rokiem 2025, Time Sheet za
październik w paczce wrześniowej), nie daje MD. Przy włączonej `proof.month` to kontrola
z jej poziomem, przy wyłączonej informacja „… za inny miesiąc” (`declared.month_mismatch`),
żeby przypadek nie stał w „Sprawdzaniu” bez powodu. Dotyczy Time Sheet, BIK, ERGO, NN i Orlenu.
Wyjątek od 23.11.2026: polski Time Sheet z rokiem z zeszłorocznego szablonu (ERSTE „TS -
Październik” z datami 2025) liczy się za rozliczany miesiąc, gdy ten sam numer miesiąca,
każdy dzień z godzinami jest dniem roboczym rozliczanego miesiąca, a choć jeden nie jest
dniem roboczym w roku z pliku (`timesheet.template_year_fixed`, informacja „Rok w szablonie”).
Plik pasujący do obu kalendarzy zostaje plikiem za inny miesiąc.
Time Sheet i raport BIK bez dat zachowują się jak dotąd (MD i kontrola `proof.month`);
ERGO, NN i Orlen bez miesiąca nie dają MD.

## Inny plik miesiąca

`_pick_report` bierze najnowszy PDF/XLSX miesiąca, a często jest nim faktura albo oferta.
Gdy wybranego pliku nie zna żaden czytnik, `service._other_files` próbuje pozostałych plików
miesiąca (PDF, XLSX, XLSM, DOCX, EML, MSG) i bierze pierwszy z MD. Ten plik staje się wtedy
dowodem rozliczenia (`report_document_id`). Szablon RCP BNP bez MD też oddaje plik innym
czytnikom (raport BIK w PDF wyglądał dla `rcp_bnp` jak RCP).

Plik zapisany przez czytnik poczty jako `invoice`, a nie `report`, do rozliczenia nie trafia
(`_month_reports` bierze tylko `report`). Dlatego `mailbox.kind_of_file` sprawdza treść każdego
pliku, który z nazwy i tematu wyszedłby fakturą (PDF, XLSX/XLSM, DOCX): rozpoznany przez
`rcp_bnp`, `confirmation_ergo`, `protocol_orlen`, `ewidencja_orlen`, `timesheet`, `timesheet_bik`
albo `timesheet_fieldglass` jest raportem.
Nowy czytnik wzoru klienta dopisz też do tej listy. Skan bez warstwy tekstu (zdjęcie Time Sheetu
NN „Wrzesień.pdf”) zostaje fakturą: skany w poczcie to też faktury i zaświadczenia, a nazwa
pliku niczego nie rozstrzyga. Klasyfikacja działa na nowych mailach; pliki już zapisane
nie zmieniają rodzaju same.

## Kolejność plików miesiąca: „najnowszy” przy tym samym czasie zapisu

Od 24.11.2026. Czytnik poczty zapisuje wszystkie pliki jednego przebiegu z tym samym
`created_at` (jedno `now` w `mailbox.run_once`), a `_month_reports` sortował tylko po nim.
Przy remisie kolejność brała się z fizycznego położenia wierszy w Postgresie i zmieniała się
po aktualizacji wierszy, więc to samo przeliczenie na tych samych danych dawało różny wynik.
Na kopii z próby IX–X 2026 od samej kolejności remisu zależały 33 z 354 rozliczeń, pięć w statusie
albo MD: Alior 491 IX („ok” albo „Brak maila z Jiry z akceptacją opiekuna”), Polkomtel 476 X
(8 albo 2,5 MD) i trzy rozliczenia BNP („ok” albo „PDF bez podpisu elektronicznego”).

Reguła `_month_reports`, od najnowszego:

- najpierw `created_at`;
- przy remisie późniejsza wiadomość (`graph_message_id`) pierwsza: czytnik bierze maile od
  najstarszego (`receivedDateTime asc`), więc jej pliki mają wyższe id. BNP i Orlen przysyłają
  podpisaną wersję RCP albo protokołu nowszym mailem;
- pliki jednej wiadomości w kolejności zapisu: załączniki jak w mailu, mail z Jiry (`.eml`)
  przed nimi, treść innego maila (przekazana akceptacja, `_store_mail_body`) po nich. Samo
  „wyższe id pierwsze” odwracało załączniki: Polkomtel 476 X ma w jednym mailu Time Sheet
  z godzinami u klienta (8 MD) i drugi, „-B2B”, z godzinami na projekcie wewnętrznym (2,5 MD).

Pliki bez wiadomości (panel, wgrane ręcznie) przy remisie idą w kolejności zapisu. Karta osoby
(`detail`) pokazuje pliki rosnąco po `created_at` i id.

### KEŚU: akceptacja z Jiry i źródło arkusza (`kesu_flow`)

- Akceptacja to najnowszy mail z Jiry z opiekunem („zaakceptowane przez … w dniu …”). Mail
  z samym tematem z Jiry jej nie zasłania. Konsultant przekazuje czasem powiadomienie
  o zmianie statusu („Timesheet … został zaakceptowany”), w którym opiekuna nie ma.
- Źródło KEŚU to najnowszy arkusz. Ten sam arkusz w kilku plikach bierzemy z maila z akceptacją
  opiekuna (potem z arkusza zapisanego osobno z tej samej wiadomości), a z kilku takich
  z najstarszego, czyli z pierwszej kopii maila z Jiry. Faktury kosztów do paczki to PDF-y
  z maila-źródła, a konsultant przekazuje ten mail dalej z tym samym KEŚU i własną fakturą.
  W próbie (Alior 491 IX i X, 493 IX, 496 IX i X) to jego mail był najnowszy, więc faktura
  konsultanta szłaby do paczki dla klienta. Gdy w starszej kopii brakuje faktury kosztów,
  pokazuje to kontrola „Brak faktury kosztów w mailu z Jiry”.
- Inny (poprawiony) arkusz w nowszym pliku dalej wygrywa, także w przekazaniu konsultanta.
  Wtedy PDF-y tego maila idą do paczki jako faktury kosztów: tego ta zmiana nie rozstrzyga.

Pomiar: kopia `nexus_staging_klodko_v6r2`, IX–X 2026, 354 rozliczenia przeliczone w transakcji
z rollbackiem, kod `main` i kod tej zmiany na tych samych danych. Status zmienia tylko Alior
491 IX: z uwagi na „ok” z akceptacją opiekuna, a z paczki wypada faktura konsultanta. MD
i kwoty bez zmian we wszystkich 354. W 11 rozliczeniach zmienia się tylko plik-dowód: mail
z Jiry zamiast jego arkusza, nowsza podpisana kopia protokołu, pierwszy obraz z maila. W dwóch
z nich zmienia się paczka KEŚU: 496 X bez faktury konsultanta, 620 IX z pięcioma biletami
z maila z Jiry (KEŚU bez kosztów dodatkowych; na `main` zależało to od kolejności).
Polkomtel 476 X (8 MD) i trzy rozliczenia BNP („ok”) zostają jak na `main`, ale już nie
zależą od kolejności. Klon `nexus_staging_klodko_v6r2id` (przebieg poczty z kodem PR #3876)
daje to samo: 15 z 365 zmian, status tylko 491 IX, MD i kwoty bez zmian, a faktura
konsultanta wypada z paczki także w 496 IX.

## Skala (próba IX–X, kopia 23.11)

Przypadki IX–X poza Nordeą w „Sprawdzaniu”: 60 → 32. MD dostaje 28 przypadków u 6 klientów
(Orlen 11, Bosch 6, NN 3, BIK 3, ERGO 3, Polkomtel 2). Tam, gdzie jest faktura Finansów, MD
zgadza się z nią w 20 z 22. Jeden przypadek Bosch za X: 22 MD, do faktury idzie 5,5 (reszta puli zamówienia,
tak jak u Finansów). Drugi Bosch za X: wiersze 132 h, suma w pliku 126 h, więc kontrola
`fields.md_hours`. W żadnym przypadku, który miał już MD, MD się nie zmieniło.

Poza zakresem: zdjęcia JPG, MS Enter Price „Report on Tasks”, Cardif „SUMA: 176h 22MD”,
RITS „Rejestr czasu”.

Powtórka na `nexus_staging_klodko_v5` (23.11, odczyt bez zapisu): z 204 przypadków IX–X
(bez KEŚU) MD zmienia się tylko w czterech: EY X, Orlen X i ERSTE X po 22 MD, równe fakturom
Finansów, oraz ERSTE IX 22 MD (bez faktury w próbie).
