# Rozliczenia Nordei — N2: e-faktury Peppol BIS Billing 3

Stan na 13.11.2026. Etap N2 planu Nordei (`docs/rozliczenia-nordea-plan.md`,
PR z N1). Po scaleniu planu sekcja N2 tam odsyła tutaj.

Repo jest publiczne: bez nazwisk, stawek i numerów osób. Próbki testowe są
zanonimizowane (`backend/tests/data/peppol`), zrzuty z kopii produkcji leżą
tylko w prywatnym artefakcie.

## Po co

Nordea przyjmuje e-faktury w Peppol BIS 3, OIO UBL albo EHF. Faktura z KSeF do
niej nie trafia, więc Finanse przepisują ok. 300 faktur miesięcznie (jedna na
konsultanta) ręcznie w Vismie Nordei. Integracja EBI24 z Vismą była za droga.
Decyzja Artura z 13.11.2026: NEXUS przygotowuje e-fakturę, a doręcza ją dostawca
Peppol z API, bez własnego punktu dostępu.

## Przepływ

1. Finanse wystawiają fakturę jak dziś w EBI24, faktura trafia do KSeF.
2. Pętla faktur sprzedażowych (co godzinę) pobiera ją z KSeF do
   `client_sales_invoices`. Gdy nabywca jest odbiorcą Peppol, ten sam pobrany XML
   FA(3) zapisuje się w `client_sales_invoice_einvoices.fa_xml`, bez dodatkowego
   zapytania. Faktury zapisane wcześniej doczytuje się z resztki budżetu tej
   pętli: najwyżej 10 na przebieg i tylko przy włączonym module rozliczeń.
   Limit Płac (8 zapytań i 40 pobrań na godzinę) zostaje nietknięty. Skrót pliku
   musi się zgadzać ze skrótem zapisanym przy pobraniu faktury.
3. Konwersja FA(3) → UBL (`services/peppol/ubl.py`) i walidacja regułami
   EN16931 i Peppol (Schematron, wydanie 3.0.21). Błąd = „Błąd walidacji”
   z powodem na ekranie, faktura nie wychodzi.
4. „Wyślij” (pojedynczo albo zaznaczone) albo automat po włączeniu przez
   Finanse: UBL z PDF-em, ponowna walidacja, wysyłka przez dostawcę, potem stan
   doręczenia.

## Mapowanie FA(3) → UBL

| FA(3) | UBL BIS 3 |
|---|---|
| `P_9A` cena, `P_10` rabat, `P_11` netto | `Price/AllowanceCharge` (cena przed rabatem w `BaseAmount`, rabat na jednostkę w `Amount`, `PriceAmount` = netto ÷ ilość). Gdy cena po rabacie nie wychodzi z 4 miejscami, rabat idzie jako `AllowanceCharge` pozycji |
| `P_12` „np II”, „oo” | kategoria `AE`, 0%, `VATEX-EU-AE` (VAT rozlicza nabywca) |
| `P_12` 23, 8, 5… | kategoria `S` ze stawką; przy walucie innej niż PLN drugi `TaxTotal` w PLN z `P_14_*W` |
| `P_12` „np I” | kategoria `O`, `VATEX-EU-O`, bez numerów VAT stron (BR-O-02) |
| `P_12` zw, 0% | odrzucone z powodem (nie występują u Nordei) |
| `NIDS:…` w opisie pozycji | `AccountingCost` pozycji |
| „Contact: …” w opisie pozycji | `BuyerReference` (Peppol wymaga referencji nabywcy albo zamówienia) |
| `KodWaluty` | `DocumentCurrencyCode` (PLN, EUR) |
| `DodatkowyOpis` | `Note` (jedna, łączona) |
| `RachunekBankowy` | `PaymentMeans` 30 z IBAN-em i SWIFT-em |
| korekta, suma ujemna | `CreditNote` 381 z `BillingReference` do faktury korygowanej |
| korekta, suma dodatnia | `Invoice` 380 z `BillingReference` |
| korekta bez zmiany kwot (np. data sprzedaży) | bez e-faktury („Bez e-faktury”) |
| PDF | wizualizacja z XML-a FA (WeasyPrint) w `AdditionalDocumentReference` |

Kontrole: suma pozycji = netto faktury (`P_13_*`), VAT i brutto = kwoty z KSeF.
Różnica oznacza, że e-faktura nie wyjdzie.

## Odbiorcy (katalog Peppol, 13.11.2026)

| Podmiot z faktury | VAT | Adres produkcyjny | Adres testowy |
|---|---|---|---|
| Nordea Bank Abp | FI28583949 | 0088:7332545014840 | 0088:7332545042126 |
| Nordea Rahoitus Suomi Oy | FI01123053 | 0088:7332545014857 | 0088:7332545042126 |
| Nordea Bank Abp S.A. Oddział w Polsce | PL1050003082 | brak w katalogu — faktury czekają | 0088:7332545042126 |

Drugi adres testowy Nordei to 0088:7332545042089 („Nordea Bank Abp (test)”).
Który z nich ma iść, rozstrzyga odpowiedź Nordei. Adresy zmienia się w ustawieniach ekranu.

**Ważne:** testowe adresy Nordei są w produkcyjnej sieci Peppol
(directory.peppol.eu); w katalogu sieci testowej ich nie ma. Piaskownica
dostawcy podłączona do testowej sieci Peppol do nich nie sięga. Wysyłka testowa
wymaga konta produkcyjnego u dostawcy (koszt ok. jednego dokumentu za próbę).

## Dostawca

Adapter `services/peppol/providers.py`: `simulate` (staging, testy) i Recommand
(REST, surowy UBL, stan doręczenia `pending` / `delivered` / `failed`). Porównanie
z 13.11.2026 (z dokumentacji i cenników, bez testu w praktyce):

| Dostawca | Surowy UBL przez REST | Koszt przy ok. 300/mies. | Uwagi |
|---|---|---|---|
| Recommand (BE) | tak | ok. €49 (200 za €29 + €0,20/szt.) | darmowy playground, Polska „partial support”, 9945:PL+NIP |
| Qvalia (SE) | tak | ok. €68 | ISO 27001, Invoice Response, piaskownica do sieci testowej niepotwierdzona |
| Storecove (NL) | tak | ok. €300 (licencja od €3 300/rok) | ISO 27001, KSeF w tym samym API |
| eConnect (NL) | tak | wycena, umowa 3 lata | — |

Decyzja Artura z 13.11.2026: najpierw odpowiedź Nordei, bo kanał może być
bezpłatny. Do tego czasu na produkcji `PEPPOL_PROVIDER=off` (ekran pokazuje
stany i plik UBL do pobrania, przycisk wysyłki jest wyłączony).

## Ekran

Finanse → Rozliczenia → klient → „E-faktury (Peppol)”. Zakładka jest widoczna
przy kliencie, który ma faktury do odbiorcy Peppol. Liczniki stanów działają
jako filtr. Wiersze z błędem i do wysłania są na górze. „Wyślij” jest
pojedynczo i dla zaznaczonych, „UBL” pobiera plik (z PDF-em), „Ustawienia”
mają tryb, automat i adresy odbiorców. Tryb testowy jest domyślny. Produkcja
i automat wymagają potwierdzenia. Faktura wysłana testowo wraca w trybie
produkcyjnym do „Do wysłania” z dopiskiem „Test doręczony”.

## Kolejne kroki

- **Faktury per projekt zamiast per konsultant** (prośba Nordei, Artur odłożył
  13.11.2026): jedna faktura na NIDS ze wszystkimi osobami projektu. Bez kodu
  w N2. To zmiana wystawiania w EBI24 (albo N4.2), konwerter jej nie wymaga,
  bo już przenosi wiele pozycji z NIDS w `AccountingCost`.
- Odpowiedź Nordei (format, adres testowy, kontakt techniczny, bezpłatny
  kanał) → wybór dostawcy → konto → `PEPPOL_*` przez „Coolify set env” → test na
  adres testowy → potwierdzenie Finansów z Vismy → tryb produkcyjny.
- Invoice Response (akceptacja albo odrzucenie przez Nordeę) — gdy dostawca
  ją przekaże.

## Stan

| Część | Stan | Dowód |
|---|---|---|
| Konwersja FA(3) → UBL | gotowe | `tests/test_peppol_ubl.py` (rabat + AE, EUR, korekta −/+, korekta bez kwot, 23%, rabat pozycji) |
| Walidacja EN16931 + Peppol | gotowe | 5 próbek bez uwag; ten sam wynik dla 59 faktur do Nordei z listopada na kopii produkcji z 13.11 (FA odtworzone z pozycji, bo lokalnie nie ma KSeF); dodatkowo XSD UBL 2.1 lokalnie |
| Zapis XML z KSeF, doczytanie | gotowe | `tests/test_peppol_service_db.py` |
| Wysyłka | gotowe z `simulate` | staging: 4 faktury „Doręczona” na 0088:7332545042126, PDF w załączniku |
| Wysyłka przez dostawcę do Nordei | czeka | brak konta u dostawcy (decyzja Artura po odpowiedzi Nordei) |
