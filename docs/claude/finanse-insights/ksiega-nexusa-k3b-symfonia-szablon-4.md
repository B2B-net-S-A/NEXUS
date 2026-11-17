# Księga NEXUSA K3b: plik „Symfonia FK — import dokumentów (szablon 4)” (17.11.2026)

Trzeci format paczki „Do Symfonii” obok XLSX i CSV (`services/ledger/export_file.py`,
klasa `SymfoniaFkDocuments`, klucz `symfonia_fk_txt4`, plik `.txt`). Powstał z trzech
próbek, które 17.11.2026 przysłała księgowa (eksport z eBI24: faktura krajowa, usługi
dla kontrahenta z UE, korekta zakupu). Próbki leżą u Artura, nie w repo (dane firmy);
testy używają zmyślonych faktur (`tests/test_ledger_symfonia_export.py`).

## Co jest w pliku

- Windows-1250, końce wierszy CRLF, bez BOM-u, wcięcia tabulatorami, pole to `nazwa =wartość`
  (spacja przed `=`, kropka w kwotach, daty `RRRR-MM-DD`). Plik: blok `INFO{…}`
  (`Nazwa programu =Sage Symfonia Finanse i Księgowość`, `Wersja szablonu =4`) i po jednym
  `Dokument{…}` na fakturę.
- Znak spoza Windows-1250 traci akcenty, a gdy to nie wystarcza, zamienia się w `?`
  (np. `Å` → `A`); nowa linia, tabulator i `}` w nazwie nie rozbijają bloku (`_text`).
- Kolejność pól jak w próbkach; różnice między typami: zakup ma `kod_obcy`, `wartoscsp`,
  `data_obcy`, `Dane sprzedawcy` (bez `fk_ident`), `pozycja` w zapisach i `IdDlaRozliczen =1`
  na zapisie rozrachunkowym; sprzedaż ma `kod`, `Dane nabywcy` z `fk_ident` i
  `IdDlaRozliczen =-1`; usługa dla UE dodaje `mppFlags`, `JPK_V7` i w rejestrze `UE`, `usluga`.
- Korekta in minus: kwoty w nagłówku dodatnie, w `Rejestr` i `Zapis` ujemne, strona
  zapisu jak w fakturze pierwotnej (NEXUS trzyma ją odwrotnie z kwotą dodatnią — format
  przelicza).

## Mapowanie na dane NEXUSA

Wiersze (`ExportLine`) niosą dekret, a dane faktury (`ExportInvoice`, tylko dla
dokumentów ze źródeł sprzedaż i koszty) składa `exports._invoices`:

| Pole pliku | Źródło w NEXUSIE |
| --- | --- |
| `KsefNumber` | `ksef_number` dokumentu księgi |
| `KSeFDate` | sprzedaż: data (czasu firmy) pobrania z KSeF; zakup: data wystawienia |
| `kod` / `kod_obcy`, `FK nazwa` | numer faktury |
| `symbol FK`, `seria` (`s` + symbol), `typ_dk` | FVS (krajowa), WDT (nabywca z VAT UE, VAT 0 → rejestr „Świadczenie usług poza krajem”, stawka `-2`), FKZ (faktura kosztowa z typem `FKZ` w regule dekretu); korekta sprzedaży = FKS |
| `data`, `dataWystawienia*` | data wystawienia |
| `datasp`, `dataZakupu`, `dataSprzedazy` | sprzedaż: data sprzedaży (P_6); zakup: data wystawienia (NEXUS nie czyta XML-a kosztów) |
| `datarej`, `datawpl` | sprzedaż: data wystawienia; zakup: data wpływu (`doc.op_date`) |
| `Rejestr.okres` | sprzedaż: data sprzedaży; zakup: data wpływu |
| `fk_ident` | `finance_counterparties.symfonia_partner_id` (to samo, co końcówka konta `200-2-NNN`) |
| `khnazwa`, `khnip`, adres, `khKrajKod` | kartoteka kontrahentów (NIP albo VAT UE z prefiksem) |
| `khKrajNazwa` | tablica nazw w `_COUNTRY_NAMES` (w próbkach tylko Polska i Finlandia) |
| `plattermin`, `Transakcja.termin` | termin płatności; brak = data wystawienia |
| `netto`, `vat`, `walbrutto`, `kwota`, `Rejestr.*` | faktura źródłowa; stawka z `posting.vat_rate` (23, 8, 5, 0) |
| `Zapis` | pozycje dekretu księgi |
| `Transakcja.rachunek` | `payment_account` (zakup); dziś nie podpięty |
| `opis`, `opis FK` | opis dokumentu księgi |

## Czego format nie przyjmie (dokument dostaje 422, paczka nie powstaje)

Komunikat wymienia numery faktur i powody (do ośmiu w jednym zdaniu):

- dokument, który nie jest fakturą (PK, RMK, listy płac, BO) — szablon 4 to import faktur;
- typ bez próbki: FVZ, FKS, WSU, eksport poza UE, import (obsługiwane: **FVS, WDT, FKZ**);
  dopisanie typu = jeden wiersz w `_SYMFONIA_TYPES` po odpowiedzi księgowej;
- faktura w walucie obcej (brak próbki: nie wiadomo, czy `netto`/`vat` idą w PLN, a
  `walnetto`/`walbrutto` w walucie, ani jaki jest `kursdoch`);
- stawka VAT inna niż 23, 8, 5, 0 albo kilka stawek na jednej fakturze (szablon wymaga
  osobnego `Rejestr{}` na stawkę — nie ma próbki);
- kraj kontrahenta spoza tablicy nazw.

Plik tworzy `ledger.exports.create`; błąd formatu zamienia na `LedgerError` 422.

## Pola, których NEXUS nie zna (lista pytań do księgowej — w opisie PR-a)

1. **`kodKH` / `khid`** (nagłówek i blok kontrahenta): w próbkach równe sobie i różne od
   `fk_ident`. Zostają **puste**. Kontrahent w Symfonii powstaje przez synchronizację z
   aplikacją eBI — czy przy pustym `khid` Symfonia dopasuje go po NIP-ie?
2. **`schemat`** (`SP`, `ZK`) i **`Rejestr.Rodzaj`** (`1` sprzedaż, `2000` korekta zakupu)
   dla typów bez próbki (FVZ, FKS). Stąd te typy są zablokowane.
3. **`KSeFDate`** — data nadania numeru w KSeF czy data wystawienia? (w próbkach równa
   dacie wystawienia).
4. **Data sprzedaży zakupu** (`datasp`, `dataZakupu`, `dataSprzedazy`): w próbce korekty
   zakupu 2 dni przed wystawieniem. NEXUS bierze datę wystawienia.
5. **Faktura korygowana w zakupie** (`Dokument korygowany`, `Dokument nadrzędny`,
   `NazwaKor`): NEXUS nie zna numeru; pole zostaje puste. Jakiego numeru oczekuje
   Symfonia (obcy czy własny `kod`)?
6. **Zapisy równoległe** (`pozycja =1`, `ZapisRownolegly`, konta `5xx`/`490`) w próbce
   kosztowej: eBI24 dopisał rozliczenie kosztów na „5”. W NEXUSIE to osobny dokument
   (rozliczenie kosztów). Czy import bez nich przejdzie?
7. **`IdDlaRozliczen`**: sprzedaż `-1` bez znacznika na zapisie, zakup `1` ze znacznikiem
   na zapisie rozrachunkowym — co oznacza `-1`, czy sprzedaż nigdy nie ma rozliczenia?
8. **Płatność** (`plattypi =131`, `forma_platnosci =przelew`, `rejestr_platnosci =BANK`) —
   stałe w próbkach, tak je zapisujemy; czy bywa inaczej (karta, gotówka)?
9. **`mppFlags`, `JPK_V7`, `UE`, `usluga`** tylko przy usłudze dla UE; oznaczeń JPK
   (GTU, procedury) NEXUS nie przekazuje. Czy to wystarcza?
10. **Nazwa rejestru**: próbka ma „Świadczenie usług poza krajem”, model księgowy
    (`DEFREJ`) „…poza kraj” — nazwa ucięta przy eksporcie modelu? Używamy tej z próbki.
11. **WDT czy WSU** dla usług dla UE (oba mają ten sam rejestr; próbka: WDT).
12. **`nazwa`** korekty sprzedaży i **nazwy krajów** (Holandia/Niderlandy, Niemcy…) —
    znamy tylko Polskę i Finlandię.
13. Rachunek sprzedawcy (`Transakcja.rachunek`) NEXUS zna z KSeF dla faktur
    kontraktorów — format go wypisuje, gdy `payment_account` jest ustawione, ale
    `exports.purchase_invoice` go jeszcze nie podaje.

## Decyzje i granice

- Paczka kosztów E2 (Finanse → Księgowanie, `finance_ledger/export_formats.py`) zostaje
  w formatach neutralnych: ma własny wiersz (`ExportRow`) bez kwot netto/VAT i dat
  potrzebnych szablonowi. Podpięcie szablonu 4 pod nią to osobna decyzja po
  odpowiedzi księgowej.
- Domyślne rodzaje paczki K3b się nie zmieniają: FVS i FVZ nadal wymagają świadomego
  zaznaczenia (do czasu wystawiania faktur w NEXUSIE Symfonia dostaje sprzedaż z eBI24).
- Sprawdzenie na próbkach (lokalnie, nie w repo): dane z trzech plików → `ExportLine` →
  `render` dały tekst równy próbce po wyzerowaniu `kodKH`/`khid`; dla dwóch plików
  sprzedaży równy bajt w bajt. Plik kosztowy równy po usunięciu zapisów równoległych
  i wyzerowaniu pól z listy wyżej (4, 5, `rachunek`).
