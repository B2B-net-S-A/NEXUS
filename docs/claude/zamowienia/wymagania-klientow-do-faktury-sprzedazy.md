# Wymagania klientów do faktury sprzedaży z NEXUSA — reguły `cl.*` (23.11.2026)

Decyzja Artura z 23.11.2026: faktury sprzedaży wystawia NEXUS, nie eBI24 (po eBI cały KSeF przechodzi do NEXUSA,
Symfonia nie ma KSeF). W eBI24 osoba z Finansów pamiętała wymagania klientów sama; przegląd skrzynek Finansów
z 23.11 zebrał je per klient. W NEXUSIE są **konfiguracją klienta**, nie warunkiem na nazwę klienta w kodzie:
reguły w „Reguły klienta” (Finanse → Rozliczenia, sekcja „Faktura do klienta”, wersje od miesiąca,
`client_settlements/rules_catalog.py`) i lista nabywców w ustawieniach wystawiania. Kod:
`services/client_invoicing/requirements.py` (odczyt reguł), `issue.py` (szkice, wysyłka, karta), `fa3_build.py` (FA(3)).
Reguły obowiązują wg **miesiąca usługi** faktury, nie daty wysyłki.

## Reguły (etap „F2”)

| Reguła | Co robi | Przykład z korespondencji |
|---|---|---|
| `cl.orders_together` | „Wystaw za miesiąc”: zaznaczone zamówienia klienta w tej samej walucie i z tym samym nabywcą idą jedną fakturą, osoba = pozycja z numerem swojego zamówienia, każdy numer w `WarunkiTransakcji/Zamowienia/NrZamowienia` (do 100) | BNP: faktura z kilku ZAM_, waluta jak w zamówieniu |
| `cl.ksef_contract` | `WarunkiTransakcji/Umowy` (`NrUmowy`, opcjonalnie `DataUmowy`) w każdej fakturze z NEXUSA | BNP |
| `cl.ksef_fields` | do dwóch par `DodatkowyOpis` (klucz, wartość; `{zamowienie}` = numery zamówień faktury) po „Uwagi” ze szkicu | Credit Agricole: `OSOBA` = adres koordynatora (od XI 2026) |
| `cl.item_name` | wzór opisu pozycji, wspólny z „Do faktury” w rozliczeniach: `{zamowienie}`, `{osoba}`, `{rola}` (tytuł pozycji zamówienia), `{usluga}`, `{miesiac}`; pole bez wartości znika z separatorem | BIK: rola z zamówienia w opisie |
| `cl.item_must_contain` | każda pozycja szkicu ma zawierać tekst; poziom „blokuje” wstrzymuje wysyłkę, „ostrzega” tylko pokazuje uwagę | BIK: numery JIRA (wpisuje je osoba w opisie pozycji) |
| `cl.invoice_mail` | karta podaje adres, gotowy temat (`{numer}`, `{ksef}`, `{m}`, `{mm}`, `{rrrr}`, `{zamowienie}`) i co załączyć; seria UE/KORUE bierze adres i temat UE, gdy są | Bosch: dwa adresy e-invoice (PL i UE) z tematem per seria; BNP: TS z numerem KSeF w temacie; BIK: PDF obok KSeF |
| `cl.after_signed_document` (istniała) | od teraz także „Wystaw za miesiąc”: wiersz zamówienia z osobą bez kompletu podpisów dokumentu z `cl.client_document` za ten miesiąc jest zablokowany z nazwiskiem, szkic = 409 | Pekao: faktura po protokole podpisanym obustronnie |

- **Maila NEXUS nie wysyła** (wysyłka faktur mailem to następny etap). `{ksef}` przed przyjęciem daje
  „(numer KSeF po przyjęciu)”, `{numer}` przed wysyłką — „(numer faktury po wysyłce)”.
- **Blok ESP-MANAGER (Bosch)** już jest: `cl.cost_mail_block` przy dokumencie na projekt w rozliczeniach.
- Identyfikatory RFP/PR/ORD (Pekao) to numery zamówienia — idą `NrZamowienia` i `{zamowienie}` w temacie maila.

## Faktura z kilku zamówień

- Nie ma własnego `order_group_id`/`order_id`; zamówienia niesie każda pozycja (`order_key` `g12`/`o34`,
  `order_number`). Te pola zapisuje „Do faktury”, front odsyła je przy edycji bez zmian (`clean_line`
  przepuszcza tylko poprawny `order_key`). Bez migracji: wszystko w JSON-ie `lines`.
- „Wystaw za miesiąc” widzi fakturę przy każdym jej zamówieniu (`issue.order_keys`), więc drugi szkic któregokolwiek
  z nich to 409. Przyjęta faktura wiąże się metodą `issued` ze wszystkimi zamówieniami (`link_sales_invoice`).
- `client_order_number` takiej faktury to numery po przecinku (karta i PDF); do KSeF idą numery z pozycji
  (`issue.order_numbers`), pole na karcie jest wtedy tylko do odczytu.
- Faktura na osobę (`split=person`) nigdy nie łączy zamówień.

## Nabywca per kontrakt (Nordea)

- Ustawienia wystawiania → klient → „Nabywcy per kontrakt”: do 10 nabywców (nazwa, NIP albo VAT UE, adres, kraj,
  opcjonalnie adres doręczenia → FA(3) `Podmiot2/AdresKoresp`, np. nabywca w FI, poczta w SE). Kod `b1`, `b2`…
  nadaje zapis; pusta lista = nabywcą jest klient z kartoteki.
- Kontrakt przypisuje się raz: wybór nabywcy w szkicu (`PUT … {"buyer_code"}`) zapisuje `contract_buyers`
  dla kontraktów pozycji (`contract_id` z zamówienia osoby). Następne szkice biorą nabywcę same i dzielą
  zamówienie na faktury nabywców. Seria (PL/UE) i stawka VAT pozycji idą za nabywcą jak przy tworzeniu szkicu.
- Faktura z zamówienia klienta z listą nabywców bez nabywcy z listy **nie wychodzi** („wybierz nabywcę z listy”).
  Powód: we wrześniu dwie korekty Nordei poszły na złego nabywcę.
- Rabat Nordei (2,5% na wierszu) to istniejący rabat od obrotu (`rabat-roczny-od-obrotu-korekta-zbiorcza.md`),
  rachunek EUR klienta — `clients[id].accounts`.

## Sprawdzenie

- XSD FA(3) **jest w repo**: `backend/tests/data/fa3_schema/schemat.xsd` (z typami MF). Nowe pola przechodzą go
  w `tests/test_client_invoice_fa3.py::test_client_requirement_fields_pass_the_fa3_schema`; zapis w opisie
  `wystawianie-faktur-sprzedazy-do-ksef.md` („XSD nie ma w repo”) jest nieaktualny.
- Reguły bez bazy: `tests/test_client_invoice_requirements.py`; ścieżka z bazą (szkic z dwóch zamówień, `NrUmowy`,
  `OSOBA`, nabywca per kontrakt z `AdresKoresp`, tekst wymagany w pozycji, blokada bez protokołu):
  `tests/test_client_invoice_issue_api.py`.
