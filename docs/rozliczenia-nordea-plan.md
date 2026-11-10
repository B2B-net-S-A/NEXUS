# Rozliczenia klientów — Nordea (plan N1–N4)

Stan na 10.11.2026. Plan i makiety, bez kodu: kod powstaje dopiero po scaleniu
PR-a z etapami E1–E5 (`docs/rozliczenia-klientow-roadmapa.md` na gałęzi
`claude/nexus-rozliczenia-przejecie-804835`, PR #3288). Decyzja Artura z 10.11.2026.
Ten plik jest osobny, żeby nie dawać konfliktu z roadmapą BNP; po scaleniu #3288
etap E6.4 roadmapy odsyła tutaj.

Repo jest publiczne: w tym pliku nie ma nazwisk, stawek, rabatów z umowy ani
adresów e-mail. Źródła (procedura rozliczeń, prezentacja „Fakturowanie Nordea”,
raport T4T za wrzesień, raport dla Cost Control, próbki faktur) leżą tylko
lokalnie u Artura, makiety z danymi w `~/NEXUS-rozliczenia-makiety/nordea/`.

## Jak dziś wygląda miesiąc Nordei

Nordea to największy klient (293 aktywne kontrakty na kopii produkcji z 10.11,
wszystkie godzinowe), faktury do klienta mają 30 dni terminu.

1. Konsultant wpisuje godziny w Time for Teams (T4T) na numery projektów Nordei
   (NIDS, w raporcie `Investment ID`), co tydzień „Submit”, line manager zatwierdza.
2. Pierwszego dnia roboczego Finanse wysyłają do Cost Control listę osób
   (imię, nazwisko, numer Nordei), Cost Control odsyła Excel z T4T. Pierwsza
   wersja jest robocza, potem przychodzą kolejne (we wrześniu pięć: 01.10, 05.10,
   08.10, 13.10, 18.10), za każdym razem na liście są osoby z rozbieżnością
   i bez faktury.
3. Finanse robią tabelę przestawną (UserId, Name, Investment ID, status × okres)
   i porównują z fakturą kontraktora z KSeF (w EBI24): żółty = zgodne,
   czerwony = różne godziny (obok godziny z faktury, potem „h” i data raportu,
   z którym się zgodziło), pomarańczowy = status 1. Liczą się tylko godziny
   w statusie 2 (Approved); 0 (Not submitted), 1 (Submitted) i 3 (Rejected) nie.
4. „Pisać czy czekać” decyduje osoba według reguł w głowie (tabela niżej):
   piszą do konsultanta, czasem do managera, mailem albo SMS-em.
5. Zgodna faktura kontraktora: MD = godziny / 8 w pliku „Kontraktorzy”, kwota
   w „Wynagrodzeniach”, akceptacja w EBI24 (folder, konta, etykiety: benefity,
   „Nie MPP”, metoda kasowa, zajęcia, wstrzymanie).
6. Klient: ostatniego dnia miesiąca w EBI24 powstają faktury cykliczne (jedna na
   osobę, rabat z umowy ramowej, odwrotne obciążenie), godziny rozpisane na NIDS,
   etykieta „Gotowa”, eksport do Excela i porównanie, wysyłka do KSeF.
7. Raport dla Cost Control w trzech arkuszach (Nordea Bank Abp, Nordea Rahoitus,
   Nordea Bank Abp S.A.): numer faktury, numer projektu, numer Nordei, godziny,
   stawka, stawka po rabacie, osoba. Dwie tury: gdy zostają „niedobitki” i końcowa.
8. Nordea jest zagraniczna, faktura z KSeF do niej nie trafia: każdą fakturę
   przepisuje się ręcznie na szablon Nordei w Visma.

Najwięcej czasu zabierają krok 3 (osoba po osobie, po każdej wersji raportu)
i krok 8 (podwójne wprowadzanie). Cel z prezentacji rozliczeń: system liczy
i przygotowuje, człowiek zatwierdza tylko wyjątki.

## Wrzesień 2026 w liczbach (policzone na plikach, bez nazwisk)

Źródło: pięć arkuszy `Sheet1` raportu T4T i raport dla Cost Control. Godziny
z faktury kontraktora przybliżamy godzinami zafakturowanymi Nordei za wrzesień
(Finanse fakturują klienta tylko przy zgodności), bo faktur kontraktorów
z datami wpływu nie mamy w paczce. Dlatego „Czekamy” w pierwszej wersji
obejmuje też osoby, których faktura jeszcze nie przyszła; NEXUS będzie znał
datę wpływu z numeru KSeF.

- 285 osób w T4T (ostatnia wersja), 291 w raporcie dla Cost Control
  (289 Nordea Bank Abp, 1 Rahoitus, 1 S.A.), 284 wspólne. 7 osób zafakturowanych
  nie ma w T4T, 1 osoba z T4T nie ma faktury do Nordei.
- 38–39 osób raportuje na kilka NIDS (faktura do klienta rozpisana na projekty).
- Wiersze w statusie 1: 447 (3 282 h) w wersji 01.10 → 73 (554 h) w 18.10.
  Statusów 0 i 3 eksport nie zawiera.
- Okresy T4T we wrześniu: 1–6, 7–13, 14–20, 21–24, 25–30. „Ostatni przedział”
  z reguł to 25–30.

Statusy osób według reguł z prezentacji (silnik porównania niżej):

| Wersja raportu | Zgodne | Czekamy | Brak akceptacji | Rozbieżność | Bez faktury | Do ponownego sprawdzenia |
|---|---:|---:|---:|---:|---:|---:|
| 01.10 | 157 | 105 | 13 | 8 | 0 | 126 |
| 05.10 | 174 | 90 | 11 | 8 | 0 | 109 |
| 08.10 | 238 | 30 | 11 | 4 | 1 | 46 |
| 13.10 | 264 | 7 | 11 | 2 | 1 | 21 |
| 18.10 | 267 | 4 | 11 | 2 | 1 | 18 |

- Pierwsza zgodność: 157 osób w 01.10, 17 w 05.10, 65 w 08.10, 26 w 13.10,
  3 w 18.10, 23 nigdy (7 bez T4T i 16 zafakturowanych bez zgodności
  w żadnej wersji z paczki).
- Po pierwszej wersji system kazałby napisać od razu do 21 osób (13 bez
  akceptacji we wcześniejszym przedziale, 8 z rozbieżnością) i poczekać na
  kolejny raport przy 105.
- Reguła „czekamy jedną wersję, przy powtórce piszemy” liczona dosłownie dałaby
  po wersji 05.10 aż 89 wiadomości (osoby bez ostatniego przedziału także
  w 01.10), a już w 08.10 tylko 27, bo 63 z nich same się wyrównały. Czekanie
  trzeba mierzyć dniami od początku miesiąca, a nie liczbą wersji (pytanie R9).
- Między wersjami statusy zmieniają się w obie strony: 1 osoba zgodna w 05.10
  miała w 08.10 inne godziny. Nowa wersja musi więc przeliczać wszystkich
  i pokazywać zmiany u zgodnych, a nie tylko u rozbieżnych.
- 11 osób ma do końca status 1 w przedziale 21–24, a i tak są zafakturowane;
  u 4 kolejnych te same godziny są drugi raz w 25–30 już zatwierdzone
  (konsultant przeniósł je zgodnie z procedurą, stary wpis wisi w statusie 1).
  Pytanie R3 niżej.
- Kartoteka po nazwisku na kopii produkcji: z 292 osób (T4T ∪ raport) 261 ma
  aktywny kontrakt Nordei o tym imieniu i nazwisku (1 z nich dwa), 19 tylko
  zakończony, 12 żadnego (inna pisownia, drugie imię, nazwa firmy). 32 aktywne
  kontrakty nie mają osoby w T4T ani w raporcie.
- Dane kontraktów Nordei na kopii: e-mail osoby 54 z 293, line manager 242
  z 293, NIP z generatora umów 55 z 293 (`candidates.nip` pusty). Numer projektu
  (`project_code`) i numer Nordei nie są nigdzie zapisane.
- Faktury do Nordei za wrzesień w KSeF (`client_sales_invoices`): 303, 365 pozycji,
  360 z „NIDS:…”, 273 różne numery Nordei w opisie pozycji (`ID:M…`), 338 pozycji
  w godzinach; waluty PLN i EUR. To gotowe źródło NIDS i numeru Nordei per osoba.

## Co bierzemy z E1–E5 (PR #3288)

| Z E1–E5 | Dla Nordei |
|---|---|
| `client_settlements` (kontrakt × miesiąc × rodzaj, status, `checks` JSONB, `accepted_by/at`) | Jeden wiersz na osobę i miesiąc; godziny zamiast MD w nowych kolumnach (N1.2) |
| Katalog reguł z poziomami `block`/`warn`/`off` i zestawy per klient od miesiąca (`rules_catalog.py`, `client_settlement_rule_sets`) | Nowa sekcja „Raport klienta (T4T)” i reguły „pisać czy czekać” jako dane, nie `if klient == Nordea` |
| API Finansów `/api/finance/settlements*` z bramką `FinanceModuleUser`, kwoty tylko przy `can_read_client_finance`, wyłącznik modułu | Te same trasy listy i karty; nowe trasy wgrania raportu i eksportów z wpisem w `tests/data/authz_golden/` |
| Ekrany `components/finance/settlements/` (lista miesiąca, karta osoby, reguły, „Do faktury dla klienta”) | Lista miesiąca dostaje widok Nordei: wersja raportu, tygodnie, statusy T4T (makiety) |
| E4: faktury kontraktorów z KSeF z metadanych (`client_contractor_invoices`), podpowiedź NIP-u po imieniu i nazwisku, korekty sumowane po netto | Faktury kontraktorów Nordei; netto ÷ stawka działa na metadanych, godziny z pozycji wymagają XML-a (N1.4) |
| E5: pozycje faktury do klienta z ostatniej faktury za grupę zamówienia, „Kopiuj pozycje” | Pozycje per NIDS z godzinami T4T, opis jak na fakturach z KSeF (NIDS, contact, contractor, numer Nordei) |
| `client_sales_invoices` (faktury do klientów z KSeF, dopasowanie `person` dla Nordei) | Kontrola „faktura do Nordei wystawiona” i źródło XML-a do Peppol (N2) |
| `contract_candidate_rates` / `effective_candidate_rate` | Stawka kosztowa w dniu pracy do netto ÷ stawka |
| Dokumenty i panel konsultanta (E3) | Na start bez panelu: konsultant Nordei nie wysyła dowodu pracy, dowodem jest T4T |

## Co jest nowe dla Nordei

1. **Kartoteka T4T.** Kontrakt ↔ `UserId` z T4T (G…) ↔ numer Nordei (M…, na
   fakturze i w raporcie dla Cost Control) ↔ NIDS z datą od–do. Dwa różne
   identyfikatory, więc oba w kartotece. Pierwsze wypełnienie: numer Nordei
   i NIDS z opisów pozycji faktur do Nordei w KSeF, `UserId` po imieniu
   i nazwisku z pierwszego wgranego raportu (podpowiedź do zatwierdzenia jak
   NIP w E4.0). Do tego flaga „wcześniejszy termin płatności” i kanał kontaktu.
2. **Wersje raportu T4T.** Każdy wgrany Excel to wersja z datą otrzymania;
   wiersze surowe (osoba, NIDS, okres, dzień, godziny, status, charge code)
   zapisane per wersja, żeby karta osoby pokazywała historię i różnice.
   Ten sam plik wgrany drugi raz (SHA-256) nie tworzy nowej wersji.
3. **Godziny z faktury kontraktora.** Pozycja w godzinach (`godz.`, `h`,
   `godzina`, `godziny`) → ilość z pozycji; pozycja ryczałtowa (`1 szt.`, `1`)
   → netto ÷ stawka z kontraktu. Pozycje „Polecenie” i „Refaktura podróży”
   poza porównaniem. Gdy polecenie jest doliczone do godzin (ilość ułamkowa),
   godziny = (netto − kwota polecenia z NEXUS-a) ÷ stawka. Korekta w godzinach
   (np. „+4 godziny”) sumuje się z fakturą pierwotną.
4. **Statusy osoby w miesiącu** (jeden na osobę, przeliczany przy każdej wersji
   i każdej nowej fakturze): „Zgodne” (godziny zatwierdzone = godziny z faktury),
   „Brak akceptacji” (zatwierdzone + złożone = faktura, część w statusie 1),
   „Czekamy” (brak albo status 1 tylko w ostatnim przedziale), „Rozbieżność”
   (różna liczba godzin), do tego „Brak faktury” i „Brak w raporcie”.
   Status 1 zostawiony w starszym przedziale przy zgodnych godzinach
   zatwierdzonych to „Zgodne” z uwagą „wisi status 1”.
5. **Reguły „pisać czy czekać”** (z prezentacji, jako reguły klienta):

   | Sytuacja | Piszemy teraz? | Do kogo |
   |---|---|---|
   | Rozbieżność albo status 1 we wcześniejszym przedziale | Tak | Konsultant |
   | Brak godzin w ostatnim przedziale | Czekamy na kolejny raport, przy powtórce piszemy | Konsultant |
   | Status 1 tylko w ostatnim przedziale | Czekamy, przy powtórce piszemy | Konsultant, manager |
   | Faktura wysłana przed końcem miesiąca, ostatni tydzień nieuzupełniony | Tak | Konsultant |
   | Wcześniejszy termin płatności i dowolny brak (także w ostatnim tygodniu) | Tak, pilnie | Konsultant |
   | Faktura wysłana kilka dni przed raportem | Tak, bez czekania | Konsultant |
   | Brak odpowiedzi po wiadomości i kolejny raport bez zmian | Ponów, potem telefon albo manager | Konsultant, manager |

6. **Szkice wiadomości.** Treść z konkretami (tygodnie, brakujące godziny,
   zakres do akceptacji, numer NIDS), do konsultanta albo zbiorczo do managera
   (lista osób do akceptacji ostatniego przedziału). Wysyłka po zatwierdzeniu
   przez Finanse (Outlook przez Graph z wsparcie@, zgodnie z E8), w historii
   osoby „napisaliśmy · data · kanał”. Automatyczna wysyłka dopiero, gdy reguły
   przejdą miesiąc bez fałszywych alarmów.
7. **Raport dla Cost Control w 3 arkuszach.** Excel generowany z zatwierdzonych
   wierszy: arkusz per podmiot Nordei (podmiot z grupy zamówienia albo nabywcy
   faktury), kolumny jak dziś. Dwie tury: „pierwsza” i „końcowa” z listą
   osób, które doszły.
8. **Peppol BIS Billing 3 do Visma.** Z XML-a faktury sprzedażowej w KSeF
   (FA(3)) budujemy UBL Peppol BIS 3: nabywca z identyfikatorem Peppol
   podmiotu, pozycje per NIDS, rabat jako `AllowanceCharge`, odwrotne
   obciążenie (kategoria VAT `AE`), waluta z faktury. Na start paczka plików
   do masowego wgrania w Visma, sieć Peppol w N4.

## Etapy

### N1. Kartoteka i porównanie (MVP, prezentacja: etap 1)

- N1.1 Kartoteka: tabela `client_external_ids` (kontrakt, klient, rodzaj
  `t4t_user` / `client_person_no` / `project_no`, wartość, `valid_from/to`,
  źródło `ksef_item` / `report_name` / `manual`, `confirmed_by/at`). Wypełnienie
  z faktur do Nordei w KSeF i podpowiedzi po imieniu i nazwisku z raportu.
  Ekran „Kartoteka Nordei” w regułach klienta: bez dopasowania, do zatwierdzenia,
  zakończone kontrakty z godzinami.
- N1.2 Wersje raportu: `client_time_reports` (klient, miesiąc, `received_on`,
  numer wersji, SHA-256, liczby) i `client_time_report_rows`; parser T4T
  (arkusz z kolumnami `Investment ID … TimesheetStatus`, nie po nazwie arkusza).
  W `client_settlements` kolumny godzin: `hours_approved`, `hours_submitted`,
  `hours_invoice`, `hours_source` (`item` / `net_by_rate`), `report_version_id`.
- N1.3 Silnik statusów (czysta funkcja jak `engine.compute`): wejście wiersze
  T4T osoby, godziny z faktury, okresy miesiąca; wyjście status, tygodnie,
  uwagi. Testy brzegowe z liczb września (anonimowe): status 1 w starszym
  przedziale, przeniesione godziny, kilka NIDS, faktura mniejsza niż raport,
  osoba bez T4T.
- N1.4 Godziny z faktury kontraktora: na start netto ÷ stawka z metadanych
  (działa w E4 bez zmian), XML pozycji dla faktur Nordei, gdy limit pobrań
  KSeF pozwala (decyzja przy N1, pytanie A2). Polecenie i refaktura z XML-a.
- N1.5 Ekran Finanse → Rozliczenia → Nordea: panel statusów miesiąca z wersją
  raportu, licznikami i filtrem „zmiany od poprzedniej wersji”, karta osoby
  z tygodniami × statusami i historią wersji (makiety).
- **Meta:** wrzesień 2026 wgrany lokalnie z pięciu wersji daje liczby z tabeli
  wyżej (157/105/13/8 w 01.10, 267/4/11/2 w 18.10) i te same osoby w statusach
  co oznaczenia kolorami w pliku Finansów; testy silnika; zrzuty 1280 × 720 i 390 px.

### N2. Eksport do Visma w Peppol BIS 3 (równolegle z N1, prezentacja: etap 2)

- N2.1 Pobranie XML-a faktury sprzedażowej do Nordei (FA(3)) przy zapisie
  w `client_sales_invoices` (dziś zapisujemy `xml_sha256` i pozycje).
- N2.2 Konwerter FA(3) → UBL Peppol BIS Billing 3 z walidacją reguł Peppol
  (Schematron) przed eksportem; błąd walidacji = plik nie wychodzi, powód na ekranie.
- N2.3 „Eksport do Visma” na liście miesiąca: zip plików UBL wybranych faktur
  (tylko wystawione w KSeF), znacznik „wyeksportowano · data”, ponowny eksport
  korekty.
- **Meta:** 3 prawdziwe faktury do Nordei z września przechodzą walidację
  Peppol lokalnie i Finanse wgrywają je masowo do Visma bez przepisywania
  (potwierdzenie rozliczeń); faktura w EUR i korekta wśród nich.

### N3. Reguły i szkice wiadomości (prezentacja: etap 3)

- N3.1 Reguły „pisać czy czekać” w katalogu (sekcja „Raport klienta”):
  ostatni przedział, czekanie do dnia roboczego miesiąca (R9), wcześniejszy termin płatności,
  faktura przed raportem, kanał.
- N3.2 Szkice: szablon per sytuacja, podstawienia z karty osoby; wysyłka po
  zatwierdzeniu (pojedynczo i „Wyślij zaznaczone”), zbiorcza lista do managera.
- N3.3 Raport dla Cost Control w 3 arkuszach (tura pierwsza i końcowa),
  znacznik „wysłano turę” na miesiącu.
- **Meta:** październik 2026 na stagingu: szkice dla każdej osoby z reguły
  „piszemy teraz”, Finanse zatwierdzają treść bez poprawek u większości;
  raport dla Cost Control zgodny z ręcznym co do wierszy i godzin.

### N4. Pełna integracja (prezentacja: etap 4)

- N4.1 Raport T4T ze skrzynki (wsparcie@ po E8): załącznik od Cost Control
  wgrywa się sam jako nowa wersja.
- N4.2 Faktura do Nordei z NEXUS-a zamiast faktur cyklicznych w EBI24:
  pozycje per NIDS, rabat, termin 30 dni (wymaga decyzji o wystawianiu
  sprzedaży w KSeF z NEXUS-a, dziś tylko pobieramy).
- N4.3 Wysyłka do Nordei przez sieć Peppol (dostawca punktu dostępowego).
- N4.4 Synchronizacja z EBI24, jeśli ma API (etykiety, akceptacja kosztowa).
- **Meta:** listopad albo grudzień 2026 rozliczony bez przepisywania do Visma
  i bez ręcznego wgrywania raportu; czas od pierwszego raportu do końcowej tury
  zmierzony i porównany z wrześniem (pięć wersji raportu od 01.10 do 18.10).

## Pytania

### Do rozliczeń

- R1. Godziny z faktury: czy zawsze bierzecie ilość z pozycji, a przy ryczałcie
  netto ÷ stawka? Co z fakturą z poleceniem doliczonym do godzin (ilość ułamkowa)?
- R2. Kto i kiedy wysyła listę osób do Cost Control przy kolejnych wersjach?
  Czy NEXUS może ją przygotować (osoby bez zgodności + bez faktury)?
- R3. 11 osób we wrześniu ma do końca status 1 w przedziale 21–24 i jest
  zafakturowanych. Czy fakturujecie godziny złożone, ale niezatwierdzone, gdy
  manager potwierdził mailem? Albo czy to przedział, którego T4T nie zamyka?
- R4. 7 osób zafakturowanych nie ma w T4T. Skąd ich godziny (inny system,
  inna firma w `ExternalCompanyName`)?
- R5. Raport dla Cost Control: skąd podmiot Nordei przy osobie (umowa,
  zamówienie, NIDS)? Czy kolumny i kolejność muszą zostać co do znaku?
- R6. Visma: czy Nordea potwierdziła, że przyjmie masowo UBL Peppol BIS 3
  (który identyfikator nabywcy, czy załącznik PDF obowiązkowy)?
- R7. Wcześniejszy termin płatności: gdzie dziś jest ta informacja (plik
  „Wynagrodzenia”, czerwona komórka)? Do kartoteki jako flaga od daty?
- R8. Kontakt z konsultantem: mail czy SMS jako domyślny? Kiedy telefon?
- R9. „Czekamy na kolejny raport”: od którego dnia miesiąca piszecie mimo braku
  w ostatnim przedziale? We wrześniu wersja 05.10 przyszła po 4 dniach i reguła
  liczona wersjami kazałaby napisać do 89 osób, z których 63 wyrównały się do 08.10.

### Do Artura

- A1. Kolejność: N1 i N2 równolegle (jak w prezentacji) czy najpierw N1?
- A2. Godziny z pozycji wymagają XML-a faktur kontraktorów Nordei (do ok. 290
  pobrań miesięcznie poza limitem Płac). Pobieramy czy zostajemy przy
  netto ÷ stawka z metadanych?
- A3. Szkice wiadomości: wysyłka z wsparcie@ (E8) czy z konta osoby z Finansów?
- A4. N4.2 wystawianie faktur do Nordei z NEXUS-a do KSeF to nowa odpowiedzialność
  (dziś EBI24). Planujemy czy N4 kończy się na eksporcie Peppol?
- A5. Kto widzi kwoty i stawki na ekranie Nordei: tylko Finanse czy też DL
  Nordei (`can_read_client_finance`)?

## Makiety

Kod makiety i dane z września tylko lokalnie (`~/NEXUS-rozliczenia-makiety/nordea/`,
zrzuty `shots/nordea-*.png`), dane wstrzykiwane przy zrzucie, w kodzie bez nazwisk.

| Ekran | Etap | Zrzut |
|---|---|---|
| Panel statusów miesiąca z wersją raportu | N1.5 | `nordea-panel-1280.png`, `nordea-panel-390.png` |
| Karta osoby: tygodnie × statusy, faktura, historia wersji | N1.5 | `nordea-karta-1280.png`, `nordea-karta-390.png` |
| Szkic wiadomości | N3.2 | `nordea-szkic-1280.png` |
| Eksport: raport dla Cost Control i Peppol do Visma | N2.3, N3.3 | `nordea-eksport-1280.png` |

## Stan etapów

| Etap | Stan | Dowód |
|---|---|---|
| N1 | plan i makiety (10.11), kod po scaleniu #3288 | liczby września w tym pliku |
| N2 | plan (10.11) | — |
| N3 | plan (10.11) | — |
| N4 | plan (10.11) | — |
