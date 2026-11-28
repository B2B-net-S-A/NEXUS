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
| `cl.collective_invoice` | Dopasowanie faktury z KSeF (`matching.decide`, `collective`): numer z faktury wiąże wszystkie zamówienia klienta z tym numerem w miesiącu faktury, także z tytułem „Zamówienie nr …”, bez względu na kwotę; bez reguły faktura z numerem kilku zamówień czeka (`several_orders`). Opis: `faktury-do-klientow-z-ksef.md` | VeloBank: jedna pozycja na całe zamówienie, w NEXUSIE zamówienie na osobę (24.11.2026) |
| `cl.ksef_contract` | `WarunkiTransakcji/Umowy` (`NrUmowy`, opcjonalnie `DataUmowy`) w każdej fakturze z NEXUSA; „inna umowa dla zamówień” (`by_order`) daje zamówieniu albo grupie MD własną umowę, Finanse mogą poprawić numer w szkicu (sekcja niżej) | BNP |
| `cl.ksef_fields` | do dwóch par `DodatkowyOpis` (klucz, wartość; `{zamowienie}` = numery zamówień faktury) po „Uwagi” ze szkicu | Credit Agricole: `OSOBA` = adres koordynatora (od XI 2026) |
| `cl.item_name` | wzór opisu pozycji, wspólny z „Do faktury” w rozliczeniach: `{zamowienie}`, `{osoba}`, `{rola}` (tytuł pozycji zamówienia), `{usluga}`, `{miesiac}`; pole bez wartości znika z separatorem | BIK: rola z zamówienia w opisie |
| `cl.item_must_contain` | każda pozycja szkicu ma zawierać tekst; poziom „blokuje” wstrzymuje wysyłkę, „ostrzega” tylko pokazuje uwagę | BIK: numery JIRA (wpisuje je osoba w opisie pozycji) |
| `cl.invoice_mail` | karta podaje adres, gotowy temat (`{numer}`, `{ksef}`, `{m}`, `{mm}`, `{rrrr}`, `{zamowienie}`) i co załączyć; seria UE/KORUE bierze adres i temat UE, gdy są | Bosch: dwa adresy e-invoice (PL i UE) z tematem per seria; BNP: TS z numerem KSeF w temacie; BIK: PDF obok KSeF |
| `cl.after_signed_document` (istniała) | od teraz także „Wystaw za miesiąc”: wiersz zamówienia z osobą bez kompletu podpisów dokumentu z `cl.client_document` za ten miesiąc jest zablokowany z nazwiskiem, szkic = 409 | Pekao: faktura po protokole podpisanym obustronnie |

- **Maila NEXUS nie wysyła** (wysyłka faktur mailem to następny etap). `{ksef}` przed przyjęciem daje
  „(numer KSeF po przyjęciu)”, `{numer}` przed wysyłką — „(numer faktury po wysyłce)”.
- **Blok ESP-MANAGER (Bosch)** już jest: `cl.cost_mail_block` przy dokumencie na projekt w rozliczeniach.
- Identyfikatory RFP/PR/ORD (Pekao) to numery zamówienia — idą `NrZamowienia` i `{zamowienie}` w temacie maila.

## Numer umowy per zamówienie albo grupa (28.11.2026)

Decyzja Artura z 28.11.2026. Za X 46 z 48 faktur BNP ma jedną umowę, a dwie grupy MD co miesiąc od V idą
„na podstawie” innej umowy (widać to w `client_sales_invoices.order_refs`). Jeden numer na klienta dawał tym
grupom zły `NrUmowy`, a w szkicu nie dało się go zmienić. Kod: `requirements.with_contract`,
`rules_catalog.parse_contract_map`, `issue.invoice_requirements` / `resolve_contract` / `set_contract`.

- **Mapa w regule, bez migracji.** Parametr „inna umowa dla zamówień” (`by_order`) reguły `cl.ksef_contract`:
  wpisy `zamówienie=umowa` rozdzielone średnikiem albo nową linią, opcjonalnie `zamówienie=umowa z RRRR-MM-DD`
  (data umowy). Numer zamówienia porównujemy bez wielkości liter i spacji. Zamówienie z mapy dostaje swoją
  umowę i swoją datę (bez daty w mapie: bez `DataUmowy`, nie data umowy domyślnej), reszta — numer i datę
  z reguły. Mapa bez numeru domyślnego = reszta faktur bez `NrUmowy`. Nieczytelny wpis zapis reguł odrzuca
  z przykładem formatu. Mapa ma wersje od miesiąca jak cała reguła.
- **Numer z pozycji, nie z pola faktury.** Umowę wybiera numer zamówienia z pozycji z „Do faktury”
  (`order_number`), a bez takich pozycji — „Numer zamówienia klienta” faktury. Poprawka tego pola w szkicu
  grupy nie zmienia jej umowy.
- **`cl.orders_together` nie łączy różnych umów.** Zamówienia klienta łączą się w jedną fakturę tylko przy tej
  samej walucie, nabywcy i umowie. Faktura, w której pozycje mają różne umowy (np. ręczna zmiana pozycji),
  nie wychodzi: „Zamówienia faktury są na różnych umowach (…) — podziel fakturę albo wpisz numer umowy w szkicu”.
- **Numer w szkicu.** Karta szkicu ma pola „Numer umowy (KSeF)” i „Umowa z dnia” (`PUT … {"contract_number",
  "contract_date"}`). Puste pole = umowa z reguł; podpowiedź pod polem pokazuje numer z reguł (`contract_rule`
  w karcie). Wpisany numer wygrywa z regułą, także u klienta bez reguły; data bez numeru = 422. Numer ze
  szkicu leży w JSON-ie `buyer` (`contract_number`, `contract_date`), bo faktura nie ma na niego kolumny:
  `clean_buyer` go nie przepuszcza (szablon z faktury i nabywca z listy go nie przenoszą), a edycja nabywcy
  w szkicu i wybór nabywcy z listy go zachowują (`keep_contract`). Korekta kopiuje nabywcę faktury
  korygowanej razem z numerem.
- Testy: bez bazy `test_client_invoice_requirements.py` (sekcja „Numer umowy per zamówienie…”), z bazą
  `test_client_invoice_issue_api.py` (`NrUmowy` w XML grupy z mapy i grupy domyślnej, podział
  `cl.orders_together` po umowie, numer wpisany w szkicu), front `IssuedInvoiceCardActions.test.tsx`.

## Zlecenie na okres i protokół odbioru (24.11.2026)

Przegląd skrzynek Finansów i kopii dokumentów klientów z 24.11.2026. Decyzje Artura z 24.11: ERSTE — blokada
bez zlecenia, Centrum e-Zdrowia — ostrzeżenie, nie blokada. Kod: `services/client_invoicing/period_checks.py`.
Obie reguły są przełącznikami w „Reguły klienta”, domyślnie wyłączone; włączają je Finanse u klienta
(ERSTE: `cl.bzone_order`, CeZ: `cl.client_protocol`) od miesiąca usługi.

| Reguła | Co robi | Dlaczego |
|---|---|---|
| `cl.bzone_order` | Każdy dzień roboczy pracy osoby w miesiącu faktury (miesiąc ∩ okres kontraktu, do `terminated_at`) musi leżeć w okresie zamówienia klienta tej osoby z numerem `K/RRRR/<nr>/<inicjały>/<nr>/<kod>`. Liczą się wszystkie aktywne i zakończone zamówienia kontraktu (zlecenie do 15., następne od 16.), bez szkiców i anulowanych; numer samodzielnego zamówienia to tytuł, linii MD — numer grupy. Brak = „Wystaw za miesiąc” blokuje wiersz i szkic (409), a karta szkicu blokuje wysyłkę (sprawdzane też przy wysyłce, gdy reguła weszła po szkicu). Komunikat: „Brak zlecenia B-ZONE na ten okres — poproś KAM o zlecenie: osoba (dni bez zlecenia)”. Pozycja bez kontraktu też czeka. Korekty i zaliczki nie są sprawdzane | Bank przyjmuje fakturę tylko z numerem zlecenia, które obejmuje okres. Zlecenia przychodzą do KAM-a, nie zawsze na rozliczenia@, a osoba potrafi zacząć pracę przed zleceniem |
| `cl.client_protocol` | Karta szkicu ostrzega (`warnings`), gdy wśród raportów miesiąca osoby (`cp_documents`, PDF) nie ma protokołu odbioru od klienta: nadawca z domeny klienta (`identity.client_ids_for_sender`), okres z treści PDF = miesiąc faktury, osoba w protokole (inne imię: numer umowy tylko tej osoby, niżej) i numer umowy z treści = umowa wykonawcza osoby (`client_executive_contracts` z zamówienia, inaczej numer zamówienia pozycji; nieznana umowa = każda). Fakturę można wysłać | Klient przysyła protokół ok. miesiąc po okresie; faktury wychodziły z wewnętrznego zestawienia godzin i jedna wymagała korekty |

- **Okres i umowa z treści PDF, nie z tematu maila.** Tematy protokołów jednej umowy bywają identyczne dla
  kolejnych miesięcy, a w wątku jednej umowy PM odesłał protokół innej. Numer umowy czyta
  `protocol_collective` („Nr umowy (Wykonawczej) CeZ/…” → `Protocol.contract`, porównanie `contract_key`).
- **Inne imię w protokole niż w kartotece (24.11.2026).** CeZ pisze w protokole zdrobnienie albo inne imię
  (CeZ/177 za X 2026: to samo nazwisko, inne imię), więc faktura dostawała fałszywe „Brak protokołu odbioru”,
  choć protokół leżał w dokumentach osoby. Gdy imię się nie zgadza, liczy się protokół jednej osoby z numerem
  umowy, na której w miesiącu faktury pracuje tylko osoba z pozycji (`protocol_collective.by_agreement`
  z `client_settlements.service._sole_agreements`: linie zamówień z miesiąca, bez anulowanych). To ta sama
  zasada i ta sama funkcja co w rozliczeniu (#3881), żeby rozliczenie i faktura mówiły to samo. Umowa kilku
  osób w miesiącu (CeZ/242) albo protokół kilku osób = ostrzeżenie zostaje. Klon próby (v6r2id), protokół
  CeZ/177 za X: przed zmianą nie pasował do osoby, po zmianie pasuje. Ostrzeżenie zostaje tam przez nadawcę:
  dokument z 17.11 ma adres firmy (punkt niżej).
- **Protokół od klienta, choć przychodzi od nas.** Na rozliczenia@ protokół CeZ nigdy nie przychodzi z domeny
  klienta: PM podpisuje protokół od CeZ i odsyła go do CeZ z DW rozliczenia@ albo przekazuje dalej
  (kopia v5: wszystkie PDF-y protokołów IX–X od adresu firmy). Decyzja Artura z 24.11.2026: liczy się protokół
  z domeny klienta albo z adresu firmy w wątku z klientem. Czytnik poczty (`mailbox._store_client_reports`)
  zapisuje wtedy jako `cp_documents.sender_email` adres klienta z adresatów albo z cytatu „Od:”/„From:”
  przekazanego maila (`_thread_client_address`); ten sam plik przysłany ponownie w wątku z klientem uzupełnia
  nadawcę. PDF z adresu firmy bez klienta w wątku i mail koordynatorki z godzinami się nie liczą.
  Dokumenty zapisane przed tą zmianą mają nadawcę firmy, więc miesiące do X 2026 dostaną ostrzeżenie.

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
- Wybór nabywcy w szkicu (`PUT … {"buyer_code"}`) zapisuje dla kontraktów pozycji (`contract_id` z zamówienia
  osoby) nabywcę **od miesiąca usługi tej faktury** (`contract_buyers`: historia `[{code, from: RRRR-MM}]`).
  Następne szkice biorą nabywcę obowiązującego w swoim miesiącu i dzielą zamówienie na faktury nabywców.
  Seria (PL/UE) i stawka VAT pozycji idą za nabywcą jak przy tworzeniu szkicu.
- **Nabywca kontraktu się zmienia** (24.11.2026, przegląd skrzynek DL-ów Nordei): zmianę ogłasza portal CPro Nordei
  („Important changes made to contract”), np. kontrakt przeszedł 15.09.2026 z Abp S.A. na Abp Finland, a do rozliczeń
  nikt tego nie przekazał. Dlatego przypisanie ma miesiąc początku: wybór nabywcy w szkicu za wrzesień nie zmienia
  sierpnia (szkic, korekta), a poprawka sierpnia nie rusza września. Zmiana w trakcie miesiąca: cały miesiąc idzie do
  jednego nabywcy (faktura jest miesięczna), rozbicie na dwóch nabywców to ręczna decyzja Finansów. Przypisanie
  zapisane przed tą zmianą (sam kod) obowiązuje od początku.
- **Zmianę z CPro zapisuje NEXUS sam** (24.11.2026): mail „Important changes made to contract N” z „Invoice address
  was updated … to: F206 …” dopisuje nabywcę z tym „Kodem w CPro” od miesiąca maila i dzwoni do Finansów z listą
  faktur do sprawdzenia; faktur nie zmienia. Szczegóły: `integracje/cpro-maile-nordei.md`. Przy nabywcy Nordei
  Finanse wpisują „Kod w CPro” (F206, F218…), dwa nabywcy klienta nie mogą mieć tego samego kodu.
- Faktura z zamówienia klienta z listą nabywców bez nabywcy z listy **nie wychodzi** („wybierz nabywcę z listy”).
  Powód: we wrześniu dwie korekty Nordei poszły na złego nabywcę.
- Rabat Nordei **nie jest** regułą tego etapu ani stałym mnożnikiem stawki: to istniejący rabat od obrotu rocznego
  z progami z umowy (`rabat-roczny-od-obrotu-korekta-zbiorcza.md`, decyzje Artura z 16.11.2026: procent na wierszu
  wg obrotu sprzed miesiąca faktury, wyższa stawka od nadwyżki, korekta za miesiąc przekroczenia). Umowa przewiduje
  notę kredytową do 31.01; sposób rozliczenia rozstrzyga Artur. Rachunek EUR klienta — `clients[id].accounts`.

## Sprawdzenie

- XSD FA(3) **jest w repo**: `backend/tests/data/fa3_schema/schemat.xsd` (z typami MF). Nowe pola przechodzą go
  w `tests/test_client_invoice_fa3.py::test_client_requirement_fields_pass_the_fa3_schema`; zapis w opisie
  `wystawianie-faktur-sprzedazy-do-ksef.md` („XSD nie ma w repo”) jest nieaktualny.
- Zlecenie B-ZONE i protokół odbioru bez bazy: `tests/test_client_invoice_period_checks.py` (zlecenie kwartalne,
  kończące się przed końcem miesiąca, kolejne zlecenie, brak zlecenia, niepełny numer, protokół innej umowy
  i innego miesiąca, inne imię z umową tylko tej osoby, umowa dwóch osób, adres klienta z wątku); z bazą:
  sekcja „Zlecenie B-ZONE…” w `test_client_invoice_issue_api.py` (tam też inne imię w protokole: umowa tylko
  tej osoby bez ostrzeżenia, druga osoba na umowie z ostrzeżeniem) i nadawca protokołu
  w `test_consultant_portal_protocol_mail_db.py`.
- Reguły bez bazy: `tests/test_client_invoice_requirements.py`; ścieżka z bazą (szkic z dwóch zamówień, `NrUmowy`,
  `OSOBA`, nabywca per kontrakt z `AdresKoresp`, tekst wymagany w pozycji, blokada bez protokołu):
  `tests/test_client_invoice_issue_api.py`.
