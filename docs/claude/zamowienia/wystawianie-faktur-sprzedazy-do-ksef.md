# Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4, 13.11.2026)

NEXUS zastępuje eBI24 przy fakturach do klientów (~450 faktur miesięcznie, ~29 klientów, osobna pozycja na
konsultanta). Ten etap: szkice z „Do faktury”, numeracja, XML FA(3), wysyłka do KSeF 2.0, PDF, korekta
i zaliczkowa. Kod: `services/client_invoicing/{issue,fa3_build,numbering,ksef_send,issue_settings,invoice_pdf}.py`,
trasy `api/client_issued_invoices.py` (`/api/finance/issued-invoices`), migracja `0696_sales_invoice_issue`
(SQL w `services/client_invoice_issue_schema.py`, lustro w entrypoincie przez `hr_schema_bundle`).

## Kto i gdzie

- Wyłącznie „Moduł Finanse” (`FinanceModuleUser`) i sekcja Finanse na każdej trasie; moduł
  `app_settings['client_invoicing']` wyłączony = 404 (admin widzi). Delivery Lead i rekruter — 403.
- Finanse → Faktury do klientów: „Wystaw za miesiąc”, „Szkice”, „Wysłane”, „Ustawienia wystawiania”.
  Karta faktury: `/finance/faktury/{id}` (kroki Szkic → Wyślij do KSeF → Przyjęta → UPO → Zapłacona).

## Ustawienia (nie w kodzie)

- `app_settings['client_invoice_issue']`: dane sprzedawcy (nazwa, NIP, adres, miejsce wystawienia), rachunki
  per waluta (PLN, EUR, USD), termin płatności (domyślnie 14 dni), nazwa usługi w pozycji, wzory serii,
  stawka VAT domyślna, nadpisanie stawki i terminu przy kliencie, podstawa zwolnienia (dla „zw.”).
  Bez nazwy, NIP-u i adresu sprzedawcy oraz rachunku w walucie faktury wysyłka czeka z komunikatem.
- NIP sprzedawcy musi być równy `KSEF_CONTEXT_NIP` — inaczej KSeF odrzuciłby fakturę.
- **Adres i termin z historii klienta** (decyzja Artura 28.11.2026, `client_invoicing/client_defaults.py`).
  Pomiar na kopii produkcji 28.11: 24 z 28 klientów z kontraktem nie miało adresu na karcie, więc XML
  FA(3) ich szkiców nie powstawał („Uzupełnij nazwę i adres nabywcy”). Termin 14 dni różnił się od faktur
  Finansów za X u 19 z 27 klientów (21, 30, 35, 60). Szkic z karty klienta bierze więc:
  - adres: karta klienta → kartoteka kontrahentów eBI24 (`finance_counterparties`) → adres nabywcy
    z ostatniej faktury w KSeF pod NIP-em klienta;
  - termin: nadpisanie przy kliencie w ustawieniach → najczęstszy termin z jego faktur w KSeF
    z 12 miesięcy (bez korekt, remis = nowsza) → `payment_days`.
  Tylko pod NIP-em klienta: drugi nabywca (Bosch GmbH, Nordea per kontrakt) ma własny adres i termin
  z listy nabywców. Szkice VII–IX na kopii: z tym adresem XML zgodny ze schematem MF w 710/718.
- Nabywca z UE (VAT UE w `clients.nip`, np. `FI12345678`) dostaje serię UE i stawkę `np II` (odwrotne
  obciążenie, `P_13_9`, `P_18`=1), chyba że klient ma nadpisanie.

## Numeracja

- Serie: `PL` `{n}/{mm}/{yyyy}`, `UE` `{n}/{mm}/{yyyy}/UE`, `ZAL` `ZAL/{n}/{mm}/{yyyy}`, `KOR` `KOR/{n}/{mm}/{yyyy}`
  (wzory edytowalne; `{n}` bez zer wiodących jak w eBI24). Miesiąc numeru = miesiąc daty wystawienia.
- **Szkic nie ma numeru** (w eBI24 szkic zjadał numer i robił dziury). Numer nadaje się w transakcji tuż przed
  wysyłką do KSeF, pod blokadą wiersza `client_invoice_series` (`SELECT … FOR UPDATE`); unikalny indeks
  `uq_client_issued_invoices_number` to druga zapora. Numer i XML są zapisane (commit) przed rozmową z KSeF.
- „Następny numer” per seria i miesiąc ustawiają Finanse w ustawieniach — przejście z eBI24 w połowie miesiąca
  kontynuuje numerację. Nie da się go ustawić na numer już wydany (409).
- **Odrzucenie przez KSeF (decyzja Artura z 13.11.2026):** faktura odrzucona (`rejected`) albo
  na pewno niewysłana (`failed`) nie istnieje w obrocie, ale **zatrzymuje swój numer** — po poprawce idzie
  ponownie z tym samym numerem, więc w zwykłym przebiegu dziury nie ma. Data wystawienia może się zmienić tylko w tym
  samym miesiącu. Wycofanie takiej faktury: gdy jej numer jest ostatni w serii, wraca do puli (licznik
  w dół, wiersz znika); gdy nie jest ostatni, faktura zostaje jako `cancelled` z opisem „numer
  niewykorzystany” — to jedyne źródło dziury i jest udokumentowane przy numerze.

## Szkice z „Do faktury”

- Wiersze `billing.billing_rows` za miesiąc usługi; domyślnie jedna faktura na zamówienie, opcjonalnie faktura
  na osobę. Pozycja na osobę: „{usługa} — {konsultant} — {miesiąc} (zamówienie {numer})”, ilość × cena z
  „Do faktury” (MD, h, dni, mies.). Okres usługi w `OkresFa`, numer zamówienia klienta w
  `WarunkiTransakcji/Zamowienia/NrZamowienia`.
- Pozycja bez kwoty (brak zużycia MD, brak stawki) **blokuje szkic** z nazwiskiem osoby. Zamówienie kosztowe
  daje pozycję bez ceny (kwotę ustalają Finanse) — wysyłka czeka, aż ją wpiszą.
- **Zamówienie okresowe bierze pozycje z przyjętego rozliczenia** (decyzja Artura 27.11.2026, `client_invoicing/settled_lines.py`). Pomiar IV–X: stawka × 168 h z zamówienia zgadzała się z fakturą Finansów w 93 z 624 faktur za X; z pozycjami z „Do faktury dla klienta” (MD z RCP albo godziny zatwierdzone w T4T, nadgodziny, onboarding, dodatki) na powtórce VI–VIII: VII 62 → 282 zgodnych, VIII 158 → 310. Osoba w rozliczeniach bez przyjętego RCP (albo z godzinami niezatwierdzonymi w T4T) blokuje szkic z nazwiskiem i powodem; osoba spoza rozliczeń klienta albo klient bez żadnego rozliczenia w NEXUSIE za ten miesiąc (miesiące sprzed rozliczeń, klient spoza modułu; zestaw reguł tego nie rozstrzyga, bo trzyma też reguły `cl.*`) — linia z zamówienia jak dotąd. Kolejne pozycje osoby (nadgodziny, dodatek) mają w nazwie dopisek po „ — ”.
- Zamówienie z fakturą za ten miesiąc (szkic albo wysłana, bez wycofanych) nie daje drugiego szkicu (409).
- Szkic edytowalny: daty, okres, termin, nabywca, numer zamówienia, uwagi, waluta, seria (PL/UE), pozycje.
  Usunięcie szkicu nie zostawia śladu w numeracji.

## FA(3) i kwoty

- `fa3_build.py`: `FA (3)` / `1-0E`, kolejność elementów jak w schemacie MF. Wartość pozycji = ilość × cena
  (do grosza), VAT od sumy netto w stawce. Stawki `P_12`: 23, 8, 5, 0 KR, 0 EX, zw, np I, np II.
- Waluta obca: kurs średni NBP z **dokładnie** ostatniego dnia roboczego przed datą dostawy (koniec okresu
  usługi; pon–pt bez świąt ustawowych, `core/scheduling.is_business_day`) z `fx_rates` (`source='NBP'`).
  Brak tabeli z tego dnia (dziura w pobieraniu kursów) to problem „brak kursu NBP z dnia X” i wysyłka czeka —
  kurs z wcześniejszego dnia byłby niezgodny z art. 31a ustawy o VAT (przegląd 13.11.2026). `KursWaluty`
  w pozycji, `P_14_xW` = VAT × kurs w złotych. Korekta bierze kurs faktury korygowanej.
- Test „round-trip”: zbudowany XML czyta `hr/ksef/fa.py` i `fa_sales.py` (te same parsery co faktury z KSeF).
  XSD FA(3) MF leży w `backend/tests/data/fa3_schema/` i sprawdzają go testy (korekta zbiorcza, wymagania klientów —
  `wymagania-klientow-do-faktury-sprzedazy.md`); pierwszą wysyłkę i tak zrób w trybie `test`.

## Wysyłka do KSeF

- `KSEF_SALES_ISSUE_MODE=off|test|prod` (domyślnie `off`: „Wyślij do KSeF” nieaktywny z wyjaśnieniem; szkice
  działają). Kontekst `KSEF_CONTEXT_NIP`. Token z `InvoiceWrite`: `KSEF_SALES_ISSUE_TOKEN`, a gdy pusty —
  `KSEF_TOKEN`, który od 16.11.2026 ma pełne prawa (decyzja Artura). Ustawiane wyłącznie workflow „Coolify set env”.
- Sesja interaktywna (`ksef_send.py`): AES-256-CBC, klucz szyfrowany RSA-OAEP kluczem MF
  `SymmetricKeyEncryption`, `POST /sessions/online`, faktura, status (ok. 14 s odpytywania), zamknięcie, UPO.
  Wynik przetwarzania: 200 = `accepted` (numer KSeF), inny kod 4xx/5xx = `rejected` (kod i opis).
- **Do edycji, ponownej wysyłki i zwolnienia numeru wraca tylko faktura, która na pewno nie weszła do KSeF**
  (przegląd 13.11.2026): sesja nie powstała, KSeF jawnie odmówił pliku (4xx z błędem, 429, 401/403) albo
  odrzucił fakturę po weryfikacji. Wtedy `failed`/`rejected`.
- **Wynik nieznany = faktura w drodze.** Po otwarciu sesji zerwane połączenie, timeout, 5xx, nieczytelna
  odpowiedź albo awaria w NEXUSIE dają `sending`/`sent`: bez edycji, bez wycofania, tylko „Sprawdź status”
  (lista faktur sesji → status). Plik faktury idzie jednym `POST` **bez automatycznego ponawiania**
  (`KsefIssueClient._post_once`) — wspólny `_send` ponawia po 5xx i zerwanym połączeniu, a KSeF mógł już
  przyjąć plik. Odczyt z KSeF ponawia jak dotąd.
- **440 „duplikat faktury” = faktura o tym numerze już jest w KSeF** (np. pierwsza wysyłka doszła, odpowiedź
  przepadła). Nie `rejected`: `sent` bez edycji i bez zwalniania numeru; numer KSeF dociągamy zapytaniem
  o metadane po numerze faktury (`find_by_number`) — od razu albo przy „Sprawdź status”.
- **Sesja zapisuje się w bazie zaraz po otwarciu** (callback `on_progress` z `transmit`, commit przed wysłaniem
  pliku; tak samo numer referencyjny pliku). Padnięcie procesu w trakcie zostawia fakturę do „Sprawdź status”.
  Wyjątek przed otwarciem sesji = `failed` (plik nie mógł dotrzeć). `sending` bez sesji starsze niż 5 minut
  (`STALE_UNSENT_AFTER`) — proces padł przed otwarciem sesji — da się wysłać ponownie z tym samym numerem
  albo wycofać. „Sprawdź status” na sesji bez faktury po 5 minutach = `failed` (plik nie dotarł).
- Przyjęta faktura od razu trafia do `client_sales_invoices` z tym samym numerem KSeF (`sync.store_invoice`
  na naszym XML-u), więc pętla `sales_ksef_fetch` jej nie dubluje, i wiąże się z zamówieniem metodą
  **`issued`** — automat jej nie przepina (jak `manual`), Finanse mogą cofnąć. Korekta idzie za pierwotną
  (`correction`). Zapłata na karcie z istniejących zapłat (`client_sales_invoice_payments`).

## PDF

- `invoice_pdf.py`: wizualizacja z numerem KSeF i kodem QR weryfikacji (KOD I:
  `https://qr.ksef.mf.gov.pl/invoice/{NIP}/{DD-MM-RRRR}/{SHA-256 pliku, Base64URL}`, test: `qr-test`).
  Szkic i faktura bez przyjęcia: znak „SZKIC — dokument nie jest fakturą”, bez kodu.

## Korekta i zaliczkowa

- Korekta tylko do faktury VAT przyjętej w KSeF: szkic z „stanem przed” (`StanPrzed`) i „po”, sumy = różnice,
  przyczyna obowiązkowa, `DaneFaKorygowanej` z numerem KSeF pierwotnej.
- **„Stan przed” = stan po ostatniej przyjętej korekcie** (przegląd 13.11.2026): po KOR1 21 → 20 MD kolejna
  korekta 20 → 22 daje +2 MD, nie różnicę od faktury pierwotnej. Druga korekta, gdy poprzednia jest jeszcze
  w toku (szkic, w drodze, odrzucona), dostaje 409.
- **Faktury zaliczkowej NEXUS nie koryguje** (409): jej korekta to `KOR_ZAL`, nie `KOR` — następny etap.
- Zaliczkowa minimalnie: klient, waluta, data otrzymania (`P_6`), wiersze w `Zamowienie`, zaliczka na pełną
  wartość zamówienia. Zaliczka częściowa i faktura rozliczeniowa (`ROZ`) — następny etap.

## Poza tym etapem (następne)

- Noty księgowe, wezwania do zapłaty, faktura rozliczeniowa do zaliczek, korekta zaliczkowej,
  wysyłka faktur mailem do klienta,
  certyfikat zamiast tokenu dla wysyłki, walidacja XSD FA(3) w CI, tryb offline KSeF.

## Zamówienie zafakturowane poza NEXUSEM (14.11.2026)

- „Wystaw za miesiąc” pokazuje przy zamówieniu numery faktur z KSeF wystawionych poza NEXUSEM (np. w eBI24),
  powiązanych z nim za ten miesiąc (`client_sales_invoice_links`, metoda inna niż `issued`), jako „zafakturowane
  w KSeF”, a szkic dla takiego zamówienia to 409 z numerem faktury. Poprawka to korekta albo odpięcie faktury
  w „Do faktury”. Powód: przeklikanie na kopii produkcji 14.11.2026 — za październik 302 z 502 zamówień miało już
  fakturę z eBI24, a lista pokazywała je jako „do wystawienia” (w miesiącu przejściowym druga faktura).

## Faktura z ręki, szablony „co miesiąc” i refaktury benefitów (E6, 15.11.2026)

Decyzja Artura z 15.11.2026 po audycie eBI24: za październik 2026 eBI24 wystawił 212 faktur sprzedaży bez zamówienia
w NEXUSIE — 155 refaktur benefitów do kontraktorów (pakiet sportowy, opieka medyczna) i ok. 57 usług do firm bez
zamówienia (część jednorazowa). Bez tej drogi eBI24 nie da się wyłączyć. Kod: `services/client_invoicing/templates.py`,
trasy w `api/client_issued_invoices.py`, migracja `0709_sales_invoice_templates`
(`services/client_invoice_templates_schema.py`).

- **Faktura z ręki** („Szkice” → „Nowa faktura”): klient z kartoteki albo dowolny nabywca. `client_issued_invoices.client_id`
  może być pusty — nabywcą jest migawka `buyer`, przyjęta faktura trafia do `client_sales_invoices` bez klienta.
  Jednorazowe sprzedaże (sprzęt, samochód) idą tą drogą, nie szablonem.
- **Faktura bez zamówienia nie dopasowuje się automatem** (przegląd 15.11.2026): przyjęta w KSeF faktura z ręki,
  z szablonu, zaliczkowa i korekta takiej trafia do „Faktur z KSeF” jako „pominięta” z powodem „Wystawiona w NEXUSIE
  bez zamówienia” (`matching.keep_issued_without_order`), bez powiązań. Bez tego automat przypinał ją „po kwocie” do
  zamówienia klienta z tą samą kwotą, a „Wystaw za miesiąc” blokował to zamówienie jako „zafakturowane w KSeF”.
  Ręczne przypisanie i pominięcie Finansów zostają; Finanse mogą cofnąć stan i przypisać fakturę ręcznie.
- **Szablon** (`client_invoice_templates`): rodzaj `service` albo `benefit` (z `benefit` = `sport`/`medical`/`other`),
  nabywca, pozycje, waluta, seria PL/UE, ważność od–do, termin, aktywny. Nazwa pozycji ze znacznikami `{okres}`
  („październik 2026”), `{okresu}` („października 2026”), `{mm}`, `{rrrr}`. Zakładka „Szablony”: zaznaczenie →
  szkice za miesiąc; **jeden szkic szablonu na miesiąc** (`uq_client_issued_invoices_template_period`, wycofana faktura
  się nie liczy), szablon wyłączony albo spoza ważności — 409. Szkic idzie dalej zwykłą drogą E4.
- **Szablony z faktur z KSeF** (zamiast eksportu 604 szablonów od dostawcy): faktury VAT z wybranego miesiąca bez
  powiązania z zamówieniem i bez faktury z NEXUSA → propozycje. Refaktura benefitu rozpoznana po nazwie pozycji
  („refaktur…” + sport/medyczne). Miesiąc z nazwy zamienia się na znacznik. Drugi import tej samej faktury albo tego
  samego nabywcy z tymi samymi pozycjami nic nie tworzy.
- **Adres nabywcy**: `client_sales_invoices` nie przechowuje adresu, więc pusty adres w szablonie i szkicu uzupełnia się
  z kartoteki kontrahentów (`finance_counterparties`, import „Partnerzy” z eBI24) po NIP-ie, potem z klienta. Bez importu
  kartoteki szkic refaktury pokaże „Uzupełnij nazwę i adres nabywcy”.
- **Miesiąc przejściowy (przegląd 15.11.2026):** szablon do nabywcy, który ma już za ten miesiąc fakturę z KSeF spoza
  NEXUSA bez zamówienia (eBI24 wystawia z własnych szablonów), ma stan „zafakturowane w KSeF” z numerem i nie daje
  szkicu (409). Porównanie po nabywcy (NIP, bez NIP-u — nazwa), nie po pozycjach, żeby inna nazwa pozycji nie
  przepuściła duplikatu; brakującą fakturę tego nabywcy wystawia się „Nową fakturą”.
- „Zapisz jako szablon” tylko z faktury VAT bez zamówienia (bez korekty i zaliczkowej) — faktura z zamówienia powstaje
  co miesiąc w „Wystaw za miesiąc”, szablon zafakturowałby usługę drugi raz (409).
- **Wysyłka seryjna** („Szkice” → zaznacz → „Wyślij zaznaczone do KSeF”): przeglądarka wysyła szkice po kolei tą samą
  trasą co karta (`POST /{id}/send`), bez nowej ścieżki w backendzie — numer, plik, wynik i UPO jak przy jednej
  fakturze. „Zatrzymaj” albo zamknięcie karty zostawia resztę jako szkice bez numeru; wynik nieznany = „w drodze”
  („Sprawdź status” na karcie). Podsumowanie: przyjęte, w drodze, do poprawy z powodem.

## Serie i rachunki jak w eBI24 (16.11.2026)

Decyzje Artura z 16.11.2026 po odczycie archiwum eBI24 (2026: 1 044 faktur `N/M/RRRR`, 1 666 `N/M/RRRR/UE`,
712 `N/M/RRRR/Benefit`, 107 `N/M/RRRR/KORUE`, 36 `KOR/N/M/RRRR`). Migracja `0718_invoice_series_ebi24`
(`services/client_invoice_series_ext_schema.py` przebudowuje CHECK serii).

- **Miesiąc w numerze bez zera** (`{m}`), jak w eBI24: wzory domyślne `{n}/{m}/{yyyy}`, `/UE`, `/Benefit`,
  `/KORUE`, `KOR/{n}/{m}/{yyyy}`. `{mm}` (z zerem) nadal działa; wzór musi mieć `{n}`, miesiąc i `{yyyy}`.
- **Seria `BEN` — refaktury benefitów**: szkic z szablonu rodzaju „benefit” idzie tą serią. Forma płatności
  „Kompensata” (FA(3): `PlatnoscInna` + `OpisPlatnosci`, bez `FormaPlatnosci` i bez rachunku), bo eBI24 rozlicza je
  potrąceniem (`COMPENSATION`, 561 z 566 w archiwum). Brak rachunku w ustawieniach nie blokuje wysyłki serii `BEN`.
- **Seria `KORUE`** — korekta faktury z serii UE (zwykła korekta zostaje w `KOR`).
- **Rachunek przy kliencie** (`clients[id].accounts[waluta]` w ustawieniach): Nordea płaci w EUR na inny rachunek
  (Santander) niż reszta klientów (BNP). Faktura i PDF biorą rachunek klienta, a bez niego domyślny waluty.
- Przejście z eBI24 w połowie miesiąca: „następny numer” każdej serii (`PUT /series/{kod}`) ustawić na kolejny
  po ostatnim numerze z eBI24, osobno dla PL, UE, BEN, KOR, KORUE.
