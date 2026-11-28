# Reguły rozliczeń i faktur per klient: propozycja do zatwierdzenia (28.11.2026)

Cel Artura: NEXUS sam rozlicza miesiąc i wystawia faktury do klientów, a człowiek tylko wyjaśnia
rozbieżności. Ten dokument to **propozycja**. Na produkcji nic nie zostało zapisane. Reguły klikają
Artur albo Finanse w UI (ścieżka na końcu).

Źródła:
- katalog reguł: `backend/app/services/client_settlements/rules_catalog.py`;
- wymagania faktur w kodzie: `backend/app/services/client_invoicing/requirements.py`;
- opis wymagań: `docs/claude/zamowienia/wymagania-klientow-do-faktury-sprzedazy.md`;
- reguły rozliczeń: `docs/claude/finanse-insights/rozliczenia-*.md`;
- dane: faktury z KSeF za X (`client_sales_invoices`, okres 2026-10), zamówienia (`client_orders`),
  zestawy reguł (`client_settlement_rule_sets`);
- przegląd skrzynek Finansów z 23.11 i historia rozliczeń z 22.11 (pliki robocze poza repo, bez nazwisk).

Nazwisk konsultantów, stawek ani kwot osób tu nie ma. Adresy e-mail to tylko skrzynki funkcyjne klientów.

## Stan wyjściowy

- 28 klientów, każdy ma jedną wersję reguł `effective_from = 2026-11`. Produkcja i kopia z 28.11 są
  zgodne: 28 wersji, 1374 klucze, ostatni zapis 25.11 19:13 UTC.
  To samo zapytanie na obu bazach: `select count(*), max(updated_at), sum((select count(*) from jsonb_object_keys(rules))) from client_settlement_rule_sets`.
- 14 klientów ma stary zestaw: 42 z 58 kluczy. Brakujące klucze biorą wartość domyślną katalogu
  (`rules_catalog.effective`, `rules_catalog.py:640-662`). Wszystkie 16 brakujących ma domyślnie
  `off`, więc działają jak wyłączone. Pierwszy zapis z ekranu i tak zapisze komplet 58 kluczy.
- `order.charge_on_accept = off` u wszystkich. To świadomy wybór na czas testów
  (`docs/claude/ludzie/portal-konsultanta.md:127-128`). Propozycja tego nie zmienia.
- Za X w „Wystaw za miesiąc” są wiersze 25 klientów. Bank Pekao SA i Energa mają tylko zamówienia
  w szkicu (po 2), VIP Solution nie ma zamówienia. Energa nie ma też NIP-u w kartotece.
- Ustawienia wystawiania (`app_settings['client_invoice_issue']`) na produkcji nie mają listy
  nabywców u żadnego klienta.

## Jak sprawdzono wpływ na szkice (krok 2)

Uruchomienie na kopii `nexus_staging_nightly_20261128`, obraz `nexus-staging-backend:latest`
(`6d256cce7a`, bez różnic w `client_invoicing` i `client_settlements` względem `main`).
Skrypt zaczyna od `install_egress_guard(())`. Każdy scenariusz idzie w SAVEPOINT, a cała sesja kończy
się `ROLLBACK`. Po wycofaniu na kopii jest 0 wersji `2026-10`.

Dla każdego wiersza „Wystaw za miesiąc” skrypt liczy osobno trzy blokady z `issue.to_issue`:
`_row_block` (brak kwoty albo pozycje czekają na rozliczenie), `_signature_block`
(`cl.after_signed_document` z dokumentem z `cl.client_document`) i `_bzone_block` (`cl.bzone_order`).
`to_issue` pokazuje tylko pierwszą z nich. Do tego doszła kontrola przy wysyłce: `requirements.line_problems`
(`cl.item_must_contain`) na pozycjach ze szkicu (`issue._lines_for`).

| Scenariusz | Wiersze X | Zablokowane | w tym bez faktury w KSeF | Wysyłka wstrzymana | Ostrzeżenie przy wysyłce |
|---|---:|---:|---:|---:|---:|
| S0: dziś (za X nie ma wersji reguł) | 501 | 370 | 36 | 0 | 0 |
| S1: obecne zestawy z XI przeniesione na X | 501 | 370 | 36 | 0 | 0 |
| **S2: propozycja jako wersja 2026-10** | 501 | **370** | 36 | 5 (BIK) | 29 (PKO) |
| S3: S2, dokumenty klienta wymagane już za X, Alior w wariancie B | 501 | 378 | 36 | 5 | 29 |

Powody blokady w S0, S1 i S2 są te same:
- 363 wiersze: „czeka na przyjęte rozliczenie (RCP)”;
- 7 wierszy: brak kwoty pozycji, czyli brak zużycia MD albo stawki.

363 wynika z tego, że za X w NEXUSIE jest po jednym rozliczeniu u Nordei, PKO, Aliora, Orlenu, ERSTE
i BIK. Klient z choćby jednym rozliczeniem czeka na RCP każdej osoby (`settled_lines.py`, docstring).
To stan danych, nie skutek reguł.

**Wniosek: propozycja nie dodaje żadnej blokady w „Wystaw za miesiąc” za X.** Zmiany działają przy wysyłce:
- BIK: wszystkie 5 wierszy czeka na numery JIRA (decyzja 3);
- PKO: 29 ostrzeżeń „brak SSGW”, wysyłka możliwa.

S3 pokazuje, co dają reguły dokumentów, gdy obejmują już X:
- PKO: 29 wierszy bez podpisanego protokołu (te same wiersze, które i tak czekają na RCP);
- VeloBank: 8 wierszy bez podpisanych arkuszy;
- Alior w wariancie B: 10 z 10 wierszy bez podpisanego arkusza (decyzja 1).

Kontrola na XI (podmiana wersji 2026-11 w SAVEPOINT): 509 wierszy, 435 zablokowanych przed zmianą
i po niej, z tymi samymi powodami:

| Powód | Wiersze XI |
|---|---:|
| Czeka na RCP | 322 |
| Brak kwoty | 69 |
| Brak podpisanego protokołu PKO | 35 |
| Brak podpisanych arkuszy VeloBank | 8 |
| Brak zlecenia B-ZONE (ERSTE) | 1 |

XI nie jest jeszcze zamknięty. Po zmianie dochodzi wstrzymana wysyłka BIK (6) i 35 ostrzeżeń SSGW u PKO.

## Propozycja per klient

Kolumna „Klucze” podaje tylko zmiany wobec obecnej wersji 2026-11. Pozostałe klucze zostają bez zmian.
„Wpływ na X” podaje liczbę zablokowanych wierszy przed zmianą i po niej (S0 → S2) oraz skutek przy wysyłce.

| Klient (id) | Klucze i poziomy (zmiana) | Uzasadnienie i dowód | Wpływ na X |
|---|---|---|---|
| ALIOR BANK (39) | bez zmian (`cl.after_signed_document` = block zostaje); **bez** `cl.client_document` | KEŚU wstrzymuje fakturę tylko w Rozliczeniach (`service.waits_for_signature`, `service.py:3630-3640`). „Wystaw za miesiąc” stanu KEŚU nie widzi: `settled_lines.AWAITING` ma tylko `waiting` i `awaiting_t4t` (`settled_lines.py:39-42`). `cl.client_document` z „podpisujący” każe `_signature_block` czekać na arkusz z `signoffs`, którego KEŚU nie zapisuje (`issue.py:541-572`, `signoffs.py:412-414`), więc S3 blokuje 10/10. Decyzja 1 | 10 → 10 (RCP); S3: 10/10 także „brak podpisu arkusza” |
| BIK (18) | `proof.month` block; `cl.item_name` warn, wzór „Usługi informatyczne, Konsultant: {osoba}, nr zamówienia: {zamowienie}”; `cl.item_must_contain` block, tekst „IABIS-” | Wymagania: rola i numery JIRA w pozycji, korekta z 23.11 za IX (`wymagania-…-sprzedazy.md:19-20`). `{rola}` = tytuł zamówienia, a u BIK 16/16 tytułów to „Zamówienie N — osoba”. Zapytanie: `select count(*) filter (where title ~* '^zamówienie') from client_orders where client_id=18 and status in ('active','completed')`. Za X 0/8 faktur ma JIRA w opisie. Decyzja 3. `cl.invoice_mail` (PDF obok KSeF) dopiero, gdy Finanse podadzą adres | 1 → 1 (brak kwoty); wysyłka wstrzymana 5/5 do wpisania numerów |
| BNP Paribas (12) | `cl.orders_together` wł.; `cl.ksef_contract` wł., numer 108051/2021, z dnia 2021-12-16; `cl.invoice_mail` wł., adres fakturyelektroniczne@bnpparibas.pl, temat `{ksef}`, załącz „RCP (TS) nazwane numerem KSeF, faktury kosztów w tym samym mailu” | Wymagania BNP (`wymagania-…-sprzedazy.md:15,17,21`). Za X 46/48 faktur wskazuje umowę 108051/2021, w tym zapis z datą 16.12.2021. 2/48 to grupy MD 1127_2026 i 1273_2026 „na podstawie Umowy 1980.2015”, co miesiąc od V. Zapytanie: `order_refs` faktur `client_id=12`. Za X 0/48 ma ZAM_ w `NrZamowienia`, a 41/48 tylko w opisie. Decyzja 2 | 1 → 1 (brak kwoty) |
| BNP Paribas CIB (58) | komplet 58 kluczy; `proof.month` block; `proof.excel_with_mail` warn, domena bnpparibas.pl; `travel.extra_costs_confirm` warn | Miesięczne zestawienie godzin od klienta, zwrot dojazdu na decyzję B2B (historia rozliczeń, 22.11) | 0 → 0 |
| Bank Pekao SA (3) | `cl.client_document` warn, rodzaj „Protokół odbioru”, na „cały miesiąc”, od 2026-11; `cl.after_signed_document` block | Faktura po protokole podpisanym obustronnie (`wymagania-…-sprzedazy.md:22`); przy fakturze 316/10/2026 księgowość banku prosiła o protokół. Klient ma 2 zamówienia, oba w szkicu, więc dziś bez skutku. Niepotwierdzone: czy czytnik `signoffs.kind_of` rozpozna protokół projektu Pekao (szuka „Okres rozliczeniowy: od”) | brak wierszy |
| Bank Pocztowy (16) | `cl.client_acceptance` warn, adres bodyleasing_kontakt@pocztowy.pl, temat „KCP B2Bnetwork {miesiac} {rok}”; `cl.after_signed_document` block; `cl.item_name` warn, wzór „Prace informatyczne zgodnie z zamówieniem {zamowienie} {osoba}” | Paczka KCP i odpowiedź banku (`rules_catalog.py:452-465`). Adres akceptacji to ten, z którego bank odpowiada (przekierowanie założone 25.11). Opis „zawsze” w tej formie, tak jak 9/10 faktur za X. Akceptacja wstrzyma fakturę tylko w Rozliczeniach (`client_acceptance.waiting`, `client_acceptance.py:145-152`). W „Wystaw za miesiąc” stan `awaiting_client` nie blokuje, bo nie ma go w `settled_lines.AWAITING`: XI 12/12 wierszy niezablokowanych mimo reguły. Decyzja 1 | 0 → 0 |
| Bosch (19) | `cl.invoice_mail` wł., adres eInvoice_8650865H@de.bosch.com, temat „Faktura VAT Nr: {numer}_ B2B.NET S.A._{mm}_{rrrr}”, adres UE einvoice_42004201@de.bosch.com, temat UE „attachment; Faktura UE VAT Nr: {numer}_ B2B.NET S.A._{mm}_{rrrr}”, załącz „PDF faktury”. **Ustawienia wystawiania:** nabywcy b1 i b2 (niżej) | Dwa adresy e-invoice z tematem per seria (`wymagania-…-sprzedazy.md:21`), ten sam wzór tematu w XI (5 PL i 3 UE). Za X 3 z 7 faktur poszły do Robert Bosch GmbH (254, 287, 288/11/2026/UE, „np II”): grupy PO 87020279 (kontrakt 627) i 87020188 (kontrakt 626), trzecia bez powiązania. Bez listy nabywców NEXUS wystawi PL/23 na Sp. z o.o. Decyzja 6 | 2 → 2 (brak kwoty) |
| CARDIF (38335) | komplet 58 kluczy; `proof.month` block | Szablonowy TS klienta za miesiąc. `cl.attachment_name` warn już jest | 0 → 0 |
| Credit Agricole (116) | komplet 58 kluczy; `proof.month` block; `cl.ksef_fields` wł., klucz OSOBA, wartość zasoby_out@credit-agricole.pl | Pole OSOBA od XI (`wymagania-…-sprzedazy.md:18`). 3/3 faktury za X mają w `DodatkowyOpis` ten adres i nazwisko koordynatora, różne na każdej fakturze. Decyzja 4 | 0 → 0 |
| Cyfrowy Polsat (38339) | komplet 58 kluczy; `proof.month` block; `proof.excel_with_mail` warn, domena plus.pl | TS z potwierdzeniem jak w Polkomtelu; domena plus.pl wspólna dla grupy (`rozliczenia-czytniki-plikow-klientow.md`, sekcja Polkomtel i Polsat) | 1 → 1 (brak kwoty) |
| ERGO Technology (13) | `proof.month` block; `proof.name_match` warn | „Bez uwag” jest włączony bez żadnej kontroli dowodu (zestaw: tylko `ci.*`, `order.pool`, automat). Czytnik Monthly Confirmation daje miesiąc i nazwisko (`rozliczenia-czytniki-plikow-klientow.md:48,80-87`). Decyzja 5 | 0 → 0 |
| ERSTE (103) | `proof.month` block; `cl.item_name` warn, wzór „Usługi informatyczne - {osoba}” (`cl.bzone_order` zostaje) | 4/4 faktury za X mają ten opis, numer zlecenia idzie w `NrZamowienia` | 5 → 5 (RCP); XI 1 wiersz bez zlecenia B-ZONE |
| EY (14) | komplet 58 kluczy; `proof.month` block | TS potwierdzany przez klienta | 0 → 0 |
| Energa (41) | komplet 58 kluczy, wszystko wyłączone | Brak korespondencji rozliczeniowej, brak NIP-u, zamówienia w szkicu | brak wierszy |
| KIR (32) | komplet 58 kluczy; `proof.month` block | Wykaz godzin z akceptacją managera | 0 → 0 |
| MS Enter Price (61) | komplet 58 kluczy; `proof.month` block | TS z akceptacją | 0 → 0 |
| Nationale Nederlanden (106) | `proof.month` block; `proof.name_match` warn | Jak ERGO: automat bez kontroli dowodu; mail „Rozliczenie pracownika … za okres MM-RRRR” ma miesiąc. Decyzja 5 | 0 → 0 |
| Nordea (11) | komplet 58 kluczy; `cl.contractor_person_id` wł. | 294/298 faktur za X ma w pozycji „ID:” z kodem osoby. Reguła tylko ostrzega (`rules_catalog.py:590-600`), wysyłka z podanym powodem. `report.time_for_teams` warn zostaje | 310 → 310 (RCP) |
| Orlen (35) | `proof.month` block; `proof.name_match` warn | Jak ERGO; ewidencja i protokół Orlenu mają miesiąc i osobę. `cl.protocol_amount` warn zostaje. Decyzja 5 | 9 → 9 (RCP) |
| PFRON (122) | komplet 58 kluczy; `proof.month` block; `cl.orders_together` wł.; `cl.ksef_contract` wł., numer 2026/000008/PZP, z dnia 2026-04-22 | Za X jedna faktura z 15 pozycjami na 18 wierszy, z numerem tej umowy | 0 → 0 |
| PKO BP (26) | `cl.item_must_contain` warn, tekst „SSGW” | 24/24 faktury za X mają „Numer SSGW” w pozycji. Numer jest per zamówienie i nie ma go w NEXUSIE, więc ostrzeżenie przypomina o wpisaniu go | 29 → 29 (RCP); 29 ostrzeżeń przy wysyłce |
| Polkomtel (15) | `proof.month` block; `cl.item_name` warn, wzór „Usługi informatyczne za {miesiac}, {osoba}, zamówienie: {zamowienie}” | Ten wzór ma 1 z 5 faktur za X, pozostałe są w trzech innych pisowniach; prośba klienta z XI o osobę i zamówienie w pozycji. `{miesiac}` daje miesiąc słownie („październik 2026”) | 2 → 2 (brak kwoty) |
| RITS (38340) | komplet 58 kluczy, bez nowych | Dokument nieustalony | 0 → 0 |
| VIP Solution (62) | komplet 58 kluczy, bez nowych | Brak zamówienia | brak wierszy |
| VeloBank (37) | `cl.item_name` warn, wzór „Prace programistyczne za miesiąc {miesiac} w ramach zamówienia nr {zamowienie}” | Opis jak na fakturze za X; arkusze od 2026-11 i faktura zbiorcza zostają | 0 → 0; S3: 8/8 bez arkuszy |
| Wedel (155) | komplet 58 kluczy, bez nowych | Zamówienia kwotowe, reguły MD nie pasują | 0 → 0 |
| eZdrowie (115) | bez zmian (`cl.client_protocol` i `cl.copyright_statement` zostają) | Umowa wykonawcza różna per faktura, więc stały `NrUmowy` nie pasuje | 0 → 0 |
| mLeasing (23) | `proof.month` block | Raport godzin od klienta za miesiąc | 0 → 0 |

**Bosch, ustawienia wystawiania** (Finanse → Faktury do klientów → Ustawienia wystawiania → Bosch →
„Nabywcy per kontrakt”):

| Kod | Nabywca | Numer | Adres | Kraj |
|---|---|---|---|---|
| b1 | ROBERT BOSCH SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ | NIP 5261027992 | ul. Jutrzenki 105, 02-231 Warszawa | PL |
| b2 | Robert Bosch GmbH | VAT DE811128135 | PO Box 1403, 39-004 Magdeburg (jak na fakturach za X) | DE |

Lista nabywców zmienia zachowanie szkicu: każdy szkic Boscha wymaga wtedy wyboru nabywcy
(`issue.py:1283-1287`). Pierwszy wybór zapamiętuje nabywcę dla kontraktów od miesiąca usługi. Kontrakty
626 i 627 → b2, kontrakty 623, 624, 625 i 628 → b1. Tak było na fakturach za IX i X.

## Do decyzji Artura

1. **Alior (KEŚU) i Bank Pocztowy (akceptacja KCP) nie wstrzymują „Wystaw za miesiąc”.**
   - Dowód: `settled_lines.py:39-42` nie zna stanów `awaiting_signature` i `awaiting_client`.
     `_signature_block` (`issue.py:541-572`) zna tylko arkusz i protokół z `signoffs`.
     Na kopii za XI Bank Pocztowy ma 12/12 wierszy bez blokady także z propozycją.
     Alior z `cl.client_document` („podpisujący”, S3) ma 10/10 wierszy zablokowanych bez względu na podpis KEŚU.
   - **Rekomendacja:** osobna sesja w kodzie, żeby „Wystaw za miesiąc” blokowało te dwa stany.
     Do tego czasu nie ustawiać `cl.client_document` u Aliora. Szkice obu klientów Finanse sprawdzają przed wysyłką.
   - Alternatywa: ustawić wariant B u Aliora i wystawiać jego faktury poza „Wystaw za miesiąc”.

2. **BNP: `NrUmowy` to jedna wartość na klienta.**
   - Dowód: za X 46/48 faktur ma umowę 108051/2021. Dwie grupy MD (1127_2026 i 1273_2026) co miesiąc
     od V wskazują Umowę 1980.2015. Z regułą dostałyby zły numer umowy, a numeru nie da się zmienić
     w szkicu (`issue.py:1474-1475`).
   - **Rekomendacja:** włączyć z 108051/2021 od 2026-11. Osobna sesja: numer umowy per grupa albo
     zamówienie, przed wystawieniem XI. Do tego czasu dwie faktury tych grup idą do wysyłki dopiero po poprawce.
   - Alternatywa: zostawić wyłączone; wtedy żadna faktura BNP nie ma `NrUmowy`.

3. **BIK: rola i JIRA.**
   - Dowód: `{rola}` daje tytuł zamówienia, a u BIK 16/16 tytułów to „Zamówienie N — osoba”.
     Za X 0/8 faktur ma JIRA w opisie, a BIK 23.11 zażądał korekty.
   - **Rekomendacja:** wzór bez `{rola}`. Rolę i numery (epiki IABIS-) dopisuje osoba w szkicu.
     `cl.item_must_contain` „IABIS-” na **block**: wysyłka 5/5 za X czeka na wpis.
   - Alternatywa: poprawić tytuły zamówień BIK na rolę (dane) i dodać `{rola}` do wzoru; JIRA na warn.

4. **Credit Agricole: wartość OSOBA.**
   - Dowód: 3/3 faktury za X mają w `DodatkowyOpis` zasoby_out@credit-agricole.pl i nazwisko
     koordynatora, różne na każdej fakturze. Reguła zna tylko stałą wartość (`requirements.py:180-185`).
   - **Rekomendacja:** OSOBA = zasoby_out@credit-agricole.pl.
   - Alternatywa: adres koordynatora z zamówienia. To wymaga zmiany kodu (pole z zamówienia); do tego
     czasu Finanse wpisują go w „Uwagi” szkicu.

5. **„Bez uwag” u ERGO, NN i Orlenu.**
   - Dowód: automat jest włączony, a zestaw nie ma żadnej reguły `proof.*` (zestawy na kopii i produkcji).
     Automat przyjmuje RCP z wynikiem „ok” (`rozliczenia-automat-przyjecia-bez-uwag.md`).
   - **Rekomendacja:** `proof.month` block i `proof.name_match` warn; automat zostaje. Plik za inny
     miesiąc albo na inną osobę nie przejdzie wtedy jako „Bez uwag”.
   - Alternatywa: wyłączyć automat do pierwszego miesiąca przyjętego ręcznie.
   - Skutku na rozliczeniach nie zmierzono: na kopii za X i XI ERGO i NN nie mają rozliczeń, a Orlen ma jedno.

6. **Bosch: dwóch nabywców.**
   - Dowód: za X 3/7 faktur poszły do GmbH (seria UE, „np II”), za IX 2/6. Dziś nabywców nie ma
     u żadnego klienta (produkcja).
   - **Rekomendacja:** dodać b1 i b2 jak wyżej. Przy pierwszym szkicu XI Finanse wybierają b2 dla
     kontraktów 626 i 627.
   - Alternatywa: tylko adres UE w `cl.invoice_mail`, a nabywcę zmieniać ręcznie w każdym szkicu.

## Do uzupełnienia przez Finanse (bez decyzji)

- Adres maila z fakturą dla BIK (PDF obok KSeF, prośba z 13.10) i dla Aliora (KEŚU do faktury).
  To adresy osób u klienta, więc nie ma ich w repo. Bez adresu `cl.invoice_mail` nic nie pokazuje
  (`requirements.py:104-110`).
- Energa: NIP w kartotece klienta. Bez niego nie ma faktury do KSeF.
- VIP Solution: zamówienie. Bez niego klient nie ma wierszy w „Wystaw za miesiąc”.
- `order.charge_on_accept` zostaje „off” u wszystkich do końca testów zespołu.

## Ścieżka klikania w UI

1. **Reguły klienta.** Klient → Reguły rozliczeń (albo Finanse → Rozliczenia → klient → „Reguły klienta”).
   - Wybrać wersję **od 2026-11**. To miesiąc usługi pierwszych faktur z NEXUSA i ta wersja już istnieje,
     więc zapis ją nadpisze.
   - Ustawić klucze z tabeli, przełączniki „włącz”, poziomy i parametry dokładnie jak wyżej, potem zapisać.
     Zapis z ekranu zapisuje komplet 58 kluczy (`save_rules`, `backend/app/api/client_settlements.py:439-458`),
     co uzupełnia 14 starych zestawów.
2. **Bosch, nabywcy.** Finanse → Faktury do klientów → Ustawienia wystawiania → Bosch → „Nabywcy per
   kontrakt”. Dodać b1 i b2 i zapisać. Przypisania kontraktów zapisze pierwszy wybór nabywcy w szkicu XI.
3. **Sprawdzenie po zapisie.** Finanse → Faktury do klientów → „Wystaw za miesiąc” za XI.
   - Liczba zablokowanych wierszy ma się zgadzać z pomiarem: 435 z 509 na kopii z 28.11.
     Wiersze PKO i VeloBank czekają na dokumenty, a ERSTE na zlecenie.
   - Karta szkicu BIK pokazuje „Każda pozycja zawiera: IABIS-”.
   - Karta szkicu Credit Agricole pokazuje „OSOBA (KSeF, pole dodatkowe)”.

## Czego nie sprawdzono

- Ostrzeżeń `cl.contractor_person_id` u Nordei na szkicach. Kontrola działa na szkicu (`issue.problems`),
  a pomiar nie tworzył szkiców. Liczba z kartoteki (40 z 301 kontraktów bez potwierdzonego numeru)
  pochodzi z briefu, nie z tego pomiaru.
- Skutku `proof.month` i `proof.name_match` na wyniku „Bez uwag” (decyzja 5): brak rozliczeń ERGO i NN na kopii.
- Czy czytnik `signoffs` rozpozna protokół projektu Pekao.
- Czy GmbH przyjmuje adres „PO Box 1403, 39-004 Magdeburg”. Wzięty z faktur za X z KSeF, nie z dokumentu klienta.
- Treści maili do klientów: NEXUS ich nie wysyła, karta tylko podaje adres i temat.
