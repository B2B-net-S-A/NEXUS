# Faktury do klientów z KSeF (E8 cz. 1, 18.10.2026)

- Faktury wystawia się tam, gdzie dziś (decyzja E8: wystawianie z NEXUSA do KSeF to osobny krok).
  NEXUS liczy „do faktury” przy odczycie z zamówień: zużycie MD × `md_rate_revenue`, okresowe jako
  stawka × `billing_hours_per_month` / dni / miesiąc; część miesiąca po dniach roboczych. **Nic
  z tego nie zapisuje.** Osoba bez zużycia MD daje kwotę nieznaną, nie zaniżoną.
- Wspólna pula MD tylko według `shared_md_orders.uses_shared_md_pool`, nie według surowej
  flagi `is_md_budget_based` (0246 ustawiła ją też zwykłym zamówieniom MD z `md_budget_mode IS
  NULL`; ich zużycie leży na liniach, więc liczymy je per osoba).
- **Zamówienie kosztowe rozlicza fakturę, nie MD** — linie nie mają `md_total`, import MD ich nie
  dotyka, więc „do faktury” NEXUS dla nich nie liczy („zamówienie kosztowe — kwotę faktury
  ustalają Finanse”). Wiersz pokazuje budżet i resztę przed fakturami za ten miesiąc: kwota +
  korekta − faktury z wcześniejszych miesięcy rozliczone przez `cost_orders.settle_group`
  (arkusz Finansów). Faktura z KSeF wiąże się z kosztowym tylko numerem (kwota nie ma z czym się
  równać); jest zgodna, gdy mieści się w tej reszcie, nadwyżka to różnica do sprawdzenia przez
  Finanse (`check_basis: "budget"`). Przy wierszu liczy się suma faktur — dwie faktury mogą
  zmieścić się osobno, a razem nie.
- Faktury sprzedażowe z KSeF jako `Subject1` (migracja `0471_client_sales_invoices`). Klient
  i `KSEF_*` wspólne z rozliczeniami ludzi (etap 4), znacznik HWM osobny
  (`app_settings['client_sales_ksef_sync']`), pętla `sales_ksef_fetch`. Budżet przebiegu: 6 zapytań
  o metadane i 20 pobrań; blokada 429 z którejkolwiek ścieżki wstrzymuje obie (limit tokenu spółki).
- Dopasowanie: NIP nabywcy → klient kanoniczny. Numer zamówienia w fakturze wiąże z zamówieniem,
  różnicę kwoty sprawdzają Finanse. Bez numeru wiąże kwota równa co do grosza jednemu
  zamówieniu albo jednej osobie, a potem osoba i stawka z pozycji faktury (decyzja Artura z 02.11.2026,
  niżej); reszta czeka na Finanse z powodem. Korekta idzie za fakturą
  pierwotną. Ręcznego przypisania automat nie nadpisuje. Brak `P_6` = okres z daty wystawienia.
- Faktura z KSeF NIE schodzi z budżetów zamówień kosztowych (`client_order_invoice_consumptions`
  — import z arkusza Finansów zostaje jako zapas „wg arkusza Finansów”). Zmiana = decyzja Artura.
- Uznania z wyciągu (import wyciągów Płac) idą osobną ścieżką od obciążeń (SAVEPOINT); uznanie bez
  numeru faktury w tytule to tylko podpowiedź. Wyciąg wgrany przez Płace dopasowuje uznania do
  faktur klientów tylko, gdy importujący ma moduł Finanse (`match_credits`, sprawdzane na trasie);
  bez niego uznania są tylko policzone (`restricted: true`, bez liczników dopasowań — nie zdradzają,
  czy numer faktury istnieje) i czekają na ten sam plik wgrany przez Finanse.
- Uznanie MPP z NIP-em w `/IDC/`, którym nie zaczyna się numer KSeF żadnej naszej faktury, to nie
  wpłata klienta, tylko noga VAT naszej zapłaty dla dostawcy (Santander: „UZNANIE VAT (SP)” z rachunku
  VAT na główny) — E8 je pomija (`_foreign_seller`). 12.11.2026 takie uznania opłacały faktury
  sprzedaży o tym samym numerze („1/11/2026”). Numer zawarty w dłuższym numerze z tytułu
  („2/10/2026” w „2/10/2026/UE”) ustępuje dłuższemu.
- Kwoty widzą Finanse i Delivery Lead u swojego klienta (`can_read_client_finance`); rekruter nie.
  Moduł `app_settings['client_invoicing']` domyślnie wyłączony; zakładka „Faktury” u klienta
  i „Faktury do klientów” w Finansach.

## Po pierwszej próbie na prawdziwych danych KSeF (02.11.2026)

- Token spółki działa tylko na produkcji MF (`test` i `demo` odrzucają go kodem 450), ma wyłącznie
  `InvoiceRead`. Wystawianie faktur z NEXUSA wymaga osobnego tokenu z `InvoiceWrite`.
- Parser FA przeszedł 40 z 40 prawdziwych faktur FA(3), kwoty XML zgadzają się z metadanymi.
- **Kolejka nie wygasa z powodu budżetu.** Sprzedaż ma ok. 600 faktur miesięcznie, pierwszy przebieg
  od 3 miesięcy wstecz to ok. 1800 faktur przy 20 pobraniach na godzinę, czyli ok. 4 dni. `_defer`
  z powodem `budget` nie nalicza próby: inaczej po 24 przebiegach faktury wypadały z kolejki
  (`pending_expired`), a znacznik był już za nimi. Budżet przekazujemy do `_Run` jawnie, bo domyślna
  wartość pola dataclass zapisuje się przy definicji i `monkeypatch` stałej jej nie zmienia.
- **Nabywca z UE ma VAT UE zamiast NIP-u** (`KodUE` + `NrVatUE`, kolumna `buyer_foreign_id`, 0630):
  to ok. 48% faktur sprzedażowych. Klucz rejestru `clients.nip_registry` to 10 cyfr albo prefiks
  kraju z cyframi, porównanie w postaci `normalize_registry_id`.
- **Osoba i stawka wiążą bez numeru zamówienia** (metoda `person`, decyzja Artura z 02.11.2026, uzupełnia
  regułę kwoty z E8). Faktura godzinowa ma rzeczywiste godziny, a NEXUS szacunkowe, więc kwota nie będzie
  równa: w próbie 20 faktur Nordei nazwisko wskazywało jedną osobę 20/20, cena była równa 20/20, godziny
  różne 18/20. Warunek: pełne imię i nazwisko prowadzi do jednej pozycji zamówień miesiąca i cena równa
  co do grosza; inaczej faktura czeka na Finanse. Numer zamówienia i równa kwota mają pierwszeństwo.
  Nazwisko porównujemy bez polskich znaków (`Łukasz` = `Lukasz`): pomiar 06.11.2026 na nocnej kopii
  produkcji dał 736 z 821 faktur Nordei przez `person`, a 5 z 75 `amount_differs` miało tylko tę różnicę.
  Pozostałe 70 to dane, nie reguła: 50 osób bez pozycji zamówienia w miesiącu usługi z faktury (24 mają ją
  w kolejnym miesiącu, 5 o miesiąc wcześniej albo dwa później, 21 nie mają w ±2 miesiącach), 11 osób
  z dwiema pozycjami w miesiącu (celowo czeka) i 9 z inną ceną.
- **Faktura z numerem zamówienia, którego NEXUS nie zna, czeka na Finanse** (`unknown_order_number`, decyzja Artura z 08.11.2026): nie wiąże
  jej kwota ani osoba, bo przy dwóch fakturach na tę samą kwotę druga rozliczałaby to samo zamówienie i ekran pokazałby obie jako zgodne. Numer
  rozpoznajemy tylko po etykiecie (`PO`, `PO number`, `purchase order`, `zamówienie`, także `numer zamówienia: SAP …`) albo gdy cały wpis to co
  najmniej 5 cyfr (`named_order_numbers`). Pole to wolny tekst, więc cyfry z nazw projektów, adresów i numery umów nie blokują. Patrzymy w `order_refs` i w nazwy pozycji (`invoice_texts`), bez
  pozycji sprzed korekty. Powód jest w `RETRY_REASONS` (numer może dojść do zamówienia) i w `GAP_REASONS` (alert DL). Pomiar z nocnej kopii 08.11.2026: zmienia
  wynik 60 z 1450 faktur z klientem, w tym 10 wiązań (6 kwotą, 4 osobą); pozostałe 50 i tak czekało, zmienia się im powód.
- **Numer nabywcy idzie do klienta przy ręcznym przypisaniu.** Pomiar z 02.11.2026 na fakturach z października:
  173 ze 188 NIP-ów nabywców nie ma klienta w NEXUSIE, ok. 197 faktur miesięcznie; numer w profilu ma 18 ze 169
  klientów. Okno „Przypisz” pozwala wskazać klienta, a przycisk „Przypisz i dopisz NIP” (`save_buyer_number`) zapisuje
  numer u klienta kanonicznego i od razu dopasowuje pozostałe faktury tego nabywcy. Nie czekamy na `rematch_pending`,
  bo idzie po kolejce paczkami (niżej). Numeru nie zapisujemy, gdy klient albo jego scalony duplikat ma inny numer
  (także tekst w tym polu), ani gdy numer ma inny klient: dopisanie zrobiłoby `ambiguous_buyer` i zatrzymało faktury
  obu klientów. Faktura przypisuje się wtedy normalnie. Zapis trafia do Historii zdarzeń
  (`client.registry_number_added`). Dopisanie jest z potwierdzeniem (decyzja Artura z 02.11.2026): obok głównego
  przycisku jest „Tylko przypisz”, bo faktura spółki zależnej bywa rozliczana z zamówienia spółki matki (od 25.11.2026
  numer z dowodem dopisuje automat, sekcja „Nieznani nabywcy” niżej). Klient bez
  zamówień w miesiącu faktury dostaje „Dopisz NIP bez przypisywania” (`POST /{id}/buyer-number`); odmowa zapisu to tam 409.
  Klucz obcy ma co najmniej 5 cyfr: faktury zapisane przed pełnym numerem (niżej) mają VAT z literą ucięty do jednej
  cyfry (`FR1`, `IE9`), a taki klucz mają różne firmy, więc ani go nie zapisujemy, ani nie wiążemy nim faktur.
- **VAT UE zapisujemy w całości, z literami** (`normalize_buyer_number`): `FR1A123456789`, `IE9S99999L`, `ATU12345678`,
  `NL123456789B01`. Tą samą funkcją idą `buyer_foreign_id`, klucz `nip_registry`, numer dopisywany do klienta i numer
  w eksporcie, bo klucz musi być taki sam po obu stronach. `normalize_registry_id` zostaje bez zmian dla poczty zamówień:
  ucina takie numery, ale skan tekstu znajduje tylko polskie i fińskie, więc ucięty klucz nigdy tam nie trafia.
  Faktura nie trzyma XML-a (tylko `xml_sha256`), więc numeru uciętego przed tą zmianą nie da się poprawić z bazy; trzeba
  pobrać fakturę z KSeF ponownie po `ksef_number`. Pomiar z 02.11.2026: na produkcji 0 faktur przy wyłączonym module,
  więc modułu włączonego po wdrożeniu tej zmiany to nie dotyczy i skryptu naprawczego nie ma.
- **`rematch_pending` idzie po całej kolejce** paczkami po 200 w kolejności `id`, kursor w
  `app_settings['client_sales_rematch_cursor']`. Wcześniej brał 200 najnowszych, więc przy ponad 200 czekających
  starsze faktury nie dostawały kolejnej próby (kolejka rośnie o ok. 197 faktur `unknown_buyer` miesięcznie).
  Przebieg jest co godzinę, więc faktura wraca najpóźniej po `kolejka / 200` godzinach. Limitu nie zwiększamy, bo
  `billing_rows` liczy się na każdą fakturę z klientem. Kursor zapisujemy przed próbami: wycofany przebieg nie wraca na
  tę samą paczkę, więc jedna wadliwa faktura nie zatrzymuje reszty.
- **Numer trafia w kilka zamówień: faktura na jedną osobę wiąże się z tą osobą** (08.11.2026), jak przy jednym trafionym zamówieniu.
  Kolejność przy kilku trafionych: suma wszystkich równa netto (wiąże wszystkie), potem jeden cały wiersz równy netto, a dopiero gdy
  takiego wiersza nie ma, pozycja osoby w zamówieniu MD z kwotą równą co do grosza. Jedna taka pozycja wiąże z metodą `order_number`,
  dwie lub więcej (dwie osoby z tą samą stawką) zostają `several_orders`, bo kwota nie mówi, o kogo chodzi (od 25.11.2026 rozstrzygają wtedy
  osoby z pozycji faktury, niżej). Wspólna pula bez podziału
  na osoby nie ma pozycji z `order_id`, więc nie wiąże. `several_orders` jest w `RETRY_REASONS`: faktura wraca po poprawce reguły albo
  po imporcie zużycia MD, który wypełni pozycje. Miesiąc puli z importu bez ręcznego `breakdown` dostaje podział z wierszy importu
  (`shared_md_month_people`, ta sama reguła co panel zamówienia), o ile składają się w sumę zejścia (09.11.2026). Bez tego rozliczenie
  widziało jedną pozycję puli, choć ekran pokazywał osoby, i faktury na osoby czekały u Finansów.
- **Faktura zbiorcza: reguła klienta `cl.collective_invoice`** (24.11.2026, decyzja Artura). VeloBank fakturuje całe zamówienie jedną
  pozycją („Prace programistyczne za miesiąc … w ramach zamówienia nr …”), a w NEXUSIE każda osoba ma własne zamówienie okresowe
  z tym numerem w tytule. Grupy nie ma, a API nie założy jej nad istniejącymi zamówieniami (tworzy nowe linie).
  - Działanie: u klienta z włączoną regułą numer z faktury wiąże wszystkie jego zamówienia z tym numerem w miesiącu faktury
    (`_whole_order`), także te z tytułem „Zamówienie nr …”, bez względu na kwotę. Różnicę kwoty widzą Finanse.
  - Wiąże też zamówienie z tym numerem, którego osoba w miesiącu nie pracowała. O zestawie decydują daty zamówień.
  - Bez reguły faktura czeka jako `several_orders`, chyba że jej pozycje nazywają osoby z tych zamówień (osoby z pozycji, niżej).
  - Odrzucone: wiązanie po samej kwocie. Przegląd 24.11 pokazał, że kwota nie odróżni faktury bez jednej osoby (przy 8 osobach to
    12,5%) od miesiąca z urlopami. Faktura jednej osoby bez nazwiska wiązała też małe zamówienie drugiej. A zaostrzony warunek nie wiązał
    już samego VeloBanku za IX.
  - Pomiar na kopii produkcji z 24.11 z regułą tylko u VeloBanku: z 24 faktur `several_orders` wiąże 4 (VeloBank VII–X), u innych
    klientów nic.
  - Faktury VeloBanku VII–X przypisano ręcznie 24.11 (`manual`, automat ich nie przepina). Zamówień osób, których kontrakty
    skończyły się 30.06, nie przypisano: tych osób nie ma w arkuszach zbiorczych.
- **Tytuł „Zamówienie nr X” to numer X** (24.11.2026). Numer zamówienia bez grupy to jego tytuł (`order_refs`), a faktura podaje
  sam numer („nr zamówienia: 9001/2026”). Faktura czekała wtedy jako `unknown_order_number`, choć zamówienie było w NEXUSIE.
  - `OrderRef.variants` daje też numer bez przedrostka, gdy reszta tytułu to jeden wyraz z cyfrą, jak `number_from_title`
    w rozliczeniach. Tytuł opisowy („Zamówienie Polkomtel — osoba”, „Zamówienie z dnia …”) numeru nie daje.
  - To samo dotyczy numeru grupy zapisanego z przedrostkiem (BNP: „ZAMÓWIENIE 1078”).
  - Przedrostek zdejmuje jeden wzorzec, `billing.TITLE_PREFIX`. Ten sam bierze `_number_key` faktury zbiorczej.
  - Bez reguły `cl.collective_invoice` tytuł z przedrostkiem i bez to ten sam numer. Suma wszystkich zamówień z numerem
    równa netto co do grosza wiąże wszystkie (reguła sumy z 08.11), inaczej faktura czeka jako `several_orders`. Wcześniej
    numer trafiał tylko tytuły bez przedrostka, więc faktura na kilka osób wiązała część zamówień.
  - Pomiar `decide()` na kopii produkcji z 23.11 (`nexus_staging_klodko_v6`, 2858 faktur z decyzją): zmienia wynik 44.
    Automat (`rematch_pending`) zmieni 34 z nich:
    - 31 faktur czekających jako `unknown_order_number` wiąże numer z jedynym zamówieniem z tym numerem w miesiącu
      (PKO VI–IX: 28, BNP IV–VI: 3);
    - 3 faktury PKO dalej czekają, ale jako `several_orders`: dwie osoby mają jeden numer, a kwota nie wskazuje żadnej.
  - Pozostałych 10 automat nie rusza (`matched`, `amount_ambiguous` poza `RETRY_REASONS`):
    - 5 związanych dziś kwotą albo osobą wskazuje to samo zamówienie albo jego jedyną linię;
    - 3 faktury PKO za VII–IX związane numerem z jednym z czterech zamówień z tym numerem dostałyby `several_orders`.
      To faktury na cztery osoby, a tylko tytuł jednego zamówienia nie miał przedrostka.
  - Po zmianie w `decide()` zostaje 134 `unknown_order_number` (PKO 38, przed zmianą 72). To numery, których NEXUS nie ma
    w miesiącu faktury.
- **Numer na kilku zamówieniach wiążą osoby z pozycji** (25.11.2026, decyzja Artura). PKO, Alior i Erste dają każdej osobie
  własne zamówienie z tym samym numerem i fakturują rzeczywiste MD: jedną fakturę na numer z pozycją na osobę albo osobną
  fakturę na osobę. NEXUS liczy szacunek (168 h w miesiącu), więc ani suma, ani wiersz, ani pozycja nie jest równa netto
  i faktura czekała jako `several_orders`.
  - Działanie (`matching._named_people`): gdy kwota nie rozstrzyga, każda bieżąca pozycja faktury (bez „przed korektą”) musi
    nazywać pełnym imieniem i nazwiskiem (`person_named_in`) dokładnie jedną osobę z zamówień trafionych numerem. Faktura
    wiąże zamówienia nazwanych osób (w zamówieniu MD linię osoby) metodą `order_number`, a różnicę kwoty widzą Finanse.
  - Nie wiąże: pozycja bez osoby (koszty, rabat), pozycja na dwie osoby, osoba spoza zamówień z tym numerem, osoba z dwoma
    zamówieniami z tym numerem w miesiącu, samo nazwisko. Ceny nie porównujemy: numer już zawęża zamówienia, a faktura
    podaje cenę za MD, zamówienie za godzinę.
  - Kolejność bez zmian: suma wszystkich, jeden cały wiersz, pozycja osoby z równą kwotą. Osoby z pozycji idą dopiero przed
    `several_orders`, a `cl.collective_invoice` ma pierwszeństwo.
  - Odrzucone: `cl.collective_invoice` dla PKO. Na jednym z numerów PKO wystawia osobne faktury na osobę, a reguła zbiorcza
    przypięłaby każdą do zamówień obu osób (pomiar: 11 zmian, 4 złe).
  - Pomiar `decide()` na kopii produkcji z 23.11 (2858 faktur z decyzją): zmienia wynik 21 faktur (PKO 11, Alior 9, Erste 1)
    i żadna nie wiąże zamówienia osoby spoza pozycji. `several_orders` spada z 31 do 10. Zostają pozycje bez nazwisk
    (VeloBank, jeden inny klient) i osoba z dwoma zamówieniami z tym numerem.
  - Automat zwiąże tylko czekające (`several_orders` jest w `RETRY_REASONS`), na produkcji 25.11 to 17 faktur. Faktur już
    związanych nie przelicza: trzy faktury PKO za VII–IX są związane numerem z jednym z czterech zamówień. Faktury
    z powodem `amount_ambiguous` też nie przelicza (jedna PKO za IX). Te cztery przypisują Finanse ręcznie (decyzja Artura z 25.11).
  - Testy: `tests/test_client_invoicing_rules.py` (sekcja „Osoby z pozycji”).

## Nieznani nabywcy i NIP w formularzu (audyt C5, 08.11.2026)

- **Finanse → Faktury do klientów → „Nieznani nabywcy”** to kolejka faktur `unmatched/unknown_buyer` ze wszystkich miesięcy, po numerze
  nabywcy (`views.unknown_buyers`). „Przypisz” dopisuje numer do klienta tym samym `save_buyer_number` co okno pojedynczej faktury, więc
  odmowy (`differs`, `taken`) i wpis w Historii zdarzeń działają tak samo; „Pomiń” pomija wszystkie czekające faktury nabywcy, z powodem.
  Wiersz bez numeru i z numerem uciętym (`FR1`) nie ma akcji: tych faktur nie da się skleić po numerze.
- **Podpowiedź klienta jest tylko jednoznaczna**: nazwa z faktury równa `legal_name`, `display_name` albo `name` dokładnie jednego
  klienta (bez nieaktywnych), bez wielkości liter. Dwóch klientów o tej samej nazwie to brak podpowiedzi, a klient z innym numerem nie
  dostaje „Przypisz” jednym kliknięciem. Pomiar z 06.11: 13 nabywców z podpowiedzią.
- **Numer nabywcy z dowodem dopisuje automat** (`client_invoicing/buyer_proof.py`, decyzja Artura z 25.11.2026: „uzupełniaj sam
  i zapisz jako regułę”). To rozszerza regułę z 02.11 „Dopisanie jest z potwierdzeniem”: potwierdzenie Finansów zostaje dla wszystkiego
  bez dowodu z osób albo z nazwy prawnej. Przebieg idzie co godzinę w pętli faktur sprzedaży tuż przed `rematch_pending`, więc kolejkę
  sprzed wdrożenia bierze pierwszy przebieg.
  - **Osoby z pozycji** (`auto_persons`, pierwsze źródło). Czekające faktury grupujemy po numerze nabywcy (klucz `save_buyer_number`).
    Bieżąca pozycja (bez „przed korektą”), która nazywa pełnym imieniem i nazwiskiem (`person_named_in`) osobę z kontraktem innym niż
    unieważniony, wskazuje klienta kanonicznego tego kontraktu. Pierwszeństwo ma kontrakt trwający w miesiącu usługi, a gdy takiego nie
    ma, liczą się wszystkie kontrakty osoby. Pozycja z osobami u kilku klientów (np. dwa kontrakty w tym miesiącu) nie głosuje. Numer
    idzie do klienta, gdy wskazują go co najmniej 2 pozycje, a żadna nie wskazuje innego klienta.
  - **Nazwa prawna** (`auto_legal_name`). Najnowsza nazwa nabywcy to `legal_name` dokładnie jednego klienta (bez nieaktywnych, bez
    wielkości liter i zbędnych spacji), a żaden inny klient nie ma jej w żadnym polu nazwy. Czyli podpowiedź jest jednoznaczna i trafia
    nazwą prawną. Sama nazwa wyświetlana albo źródłowa niczego nie dowodzi.
  - **Sprzeczne dowody = nic.** Osoby wskazują innego klienta niż nazwa prawna, nazwa nabywcy jest nazwą prawną innego klienta albo klient
    wskazany przez osoby ma nazwę prawną inną niż nazwa nabywcy. Ostatni przypadek to spółka z grupy z własnym numerem, fakturowana za
    osoby z kontraktem u klienta siostry: pomiar z 25.11 znalazł dwa numery z osobami jednego klienta, z czego jeden należał do spółki siostry.
  - **Zapis tylko w stanie `add`**: klient bez numeru, a numeru nie ma nikt inny. Stany `differs` (spółka zależna z własnym VAT przy
    kliencie matce z numerem), `taken` i `same` zostają Finansom. Tak samo dwa numery z dowodem dla jednego klienta w jednym przebiegu,
    bo inaczej o numerze klienta decydowałaby kolejność.
  - **Dlaczego 2 pozycje.** Jedna wzmianka bywa przypadkiem (imiennik albo osoba na fakturze innego nabywcy), a numer przypina klientowi
    wszystkie faktury nabywcy, także przyszłe. Osoba bez kontraktu nie głosuje, bo nie wiadomo, u kogo pracuje.
  - **Zapis jak ręczne „Przypisz”.** Numer przechodzi przez `save_buyer_number`, więc pozostałe faktury nabywcy wiążą się od razu. Wpis
    `client.registry_number_added` nie ma autora (w Historii zdarzeń widać „System”), a w szczegółach są `source` i `named_positions`.
    Każdy nabywca idzie w osobnym SAVEPOINT. Log INFO na każdy numer zawiera same identyfikatory i liczby.
  - **Pomiar na sucho** na kopii produkcji z 25.11 (226 nabywców w kolejce). 8 numerów do dopisania: 3 z osób, 5 z nazwy prawnej. Klienta
    dostaje 137 faktur, a 36 od razu wiąże się z zamówieniem. 4 numery z osobami zostają Finansom, bo nazwa prawna klienta jest inna.
    Odsiew przed `person_named_in` (`matching.name_key`) dał ten sam wynik co pełne porównanie (1 756 pozycji, 574 osoby). Cały przebieg
    trwał 0,5 s.
  - Testy: `tests/test_client_invoicing_buyer_proof.py` (bez bazy), z bazą w `test_client_invoicing_buyer_number.py`
    i `test_client_invoicing_sync.py`.
- Suma kolejki znika bez uprawnienia „Wyniki firmy”, tak jak suma miesiąca (decyzja z 02.11).
- **Formularz klienta ma NIP i „Nazwa prawna”** tam, gdzie konto widzi dane prawne. NIP przechodzi sumę kontrolną
  (`client_registry_number`); zagraniczny numer idzie z prefiksem kraju. Zapisujemy postać rejestru (bez kresek i `PL`). Numer innego
  klienta to 409, bo dwa takie wiersze zatrzymałyby faktury obu. Zapis wysyła pole tylko po zmianie: stary tekst w polu NIP nie blokuje
  edycji reszty formularza. Zmiana numeru od razu dopasowuje czekające faktury, także przy zakładaniu klienta.
  Ramka „N faktur z KSeF czeka na ten NIP” jest **tylko dla Finansów**: wpisany numer nie jest związany z klientem z adresu, więc Delivery
  Lead odczytałby nim nazwę i kwoty faktur firm spoza portfela.
- **Alert DL o fakturze bez pozycji** (`invoice_without_order_line`, `services/client_invoicing/line_gaps.py`): faktura czeka na Finanse
  z powodem `no_orders`, `amount_differs` albo `expected_unknown`, a pozycja nazywa pełnym imieniem i nazwiskiem osobę z kontraktem
  u tego klienta, która w miesiącu usługi nie ma pozycji zamówienia. Pozycję sprawdzamy po zamówieniach (`member_ids`), nie po tekście linii:
  kosztowe mają nazwiska po przecinku, a wspólna pula „N os.”. Nazwisko spoza kontraktów zostaje Finansom. Faktury starsze niż
  6 miesięcy nie alarmują, karta zamyka się sama po przypisaniu faktury albo dopisaniu pozycji.

## Dodatkowe numery nabywcy — spółki grupy klienta (0781, 25.11.2026)

- **Klient ma jedno `clients.nip`, a spółki jego grupy fakturują się pod własnym numerem** (oddział, spółka leasingowa,
  fundusz emerytalny, oddział zagraniczny). Audyt 25.11.2026: 22 faktury spółek grupy jednego klienta (ok. 452 tys. zł
  i 8 tys. EUR) czekały w „Nieznani nabywcy”, bo dopisanie numeru odmawiało (`differs`). Decyzja Artura z 25.11.2026:
  tabela `client_buyer_numbers` (numer w postaci `normalize_buyer_number`, UNIQUE, `source` `manual`/`auto`, `added_by`),
  nie ukryte duplikaty klienta (zaśmiecałyby wyszukiwanie, liczniki i scalanie).
- `nip_registry` czyta ją obok `clients.nip` i scalonych duplikatów: dodatkowy numer prowadzi do klienta kanonicznego,
  ten sam numer u innego klienta to nadal `ambiguous_buyer`, więc dopisanie odmawia `taken` jak dotąd, a formularz
  klienta (`number_taken_by`) traktuje cudzy numer dodatkowy jako zajęty.
- Dopisanie jako dodatkowy tylko jawnie: `add_buyer_number(..., extra=True)` / `save_buyer_number(..., extra=True)`.
  Bez `extra` klient z innym numerem dalej daje `differs`; z `extra` u klienta bez numeru numer idzie do `clients.nip`.
  Finanse: „Nieznani nabywcy” → „Dopisz jako dodatkowy” przy podpowiedzi z innym numerem i „Jako dodatkowy numer”
  w „Przypisz do…”; okno faktury przy `differs` ma „Przypisz i dopisz jako dodatkowy” albo „Dopisz jako dodatkowy bez
  przypisywania”. Wpis w Historii zdarzeń jak przy zwykłym numerze (`client.registry_number_added`, `details.extra`).
- **Automat dopisuje sam** (decyzja Artura z 25.11.2026: „Automatically”): reguła NIP-u nabywcy z osób na fakturze, gdy
  wszystkie osoby wskazują klienta z innym numerem, woła `save_buyer_number(..., extra=True, source="auto")`.
- Przegląd i cofnięcie: lista „Dodatkowe numery klientów” pod „Nieznani nabywcy” (`GET/DELETE
  /api/finance/sales-invoices/buyer-numbers`), z rozróżnieniem „dopisany przez Finanse / przez automat”. Usunięcie
  nie odpina faktur już przypisanych; kolejne z tym numerem wracają do „Nieznani nabywcy”
  (`client.registry_number_removed`).
- Poczta zamówień (`order_mail_ingest`) czyta tylko `clients.nip`: dodatkowe numery działają w fakturach z KSeF,
  nie w rozpoznawaniu klienta z PDF-u zamówienia (poza zakresem 0781).
- Testy: `tests/test_client_invoicing_unknown_buyers.py` (sekcja „Dodatkowe numery”), lustro DDL
  `tests/test_client_buyer_numbers.py`.

## Zamówienia MD w obcej walucie (08.11.2026)

- **„Do faktury” idzie w walucie stawki z zamówienia, bez kursu.** `md_rate_revenue` linii jest zawsze w PLN/MD (materializator
  przelicza kursem z dnia startu), a stawkę z zamówienia niesie `rate_client` (`_client_md_rate`). Wiersz MD miał na stałe PLN,
  więc każda faktura w EUR kończyła z `currency_differs`, choć numer zamówienia i kwota się zgadzały.
- Brak `rate_client` w obcej walucie to brak kwoty, nie kwota w złotych. Linie w różnych walutach w jednym zamówieniu zostają
  na PLN/MD (`_group_currency`), bo suma EUR + PLN nie ma sensu. Linia w PLN liczy się jak dotąd z `md_rate_revenue`.
- Faktura w PLN do zamówienia w EUR dalej czeka z `currency_differs`: równowartości w złotych nie porównujemy.
- `currency_differs` jest w `RETRY_REASONS`: po poprawce waluty zamówienia faktura wraca do automatu bez ręcznego przypisania.
- Zamówienie kosztowe zostaje w PLN: kwotę faktury ustalają Finanse, a budżet nie ma pola waluty.

- **Zaległe okna sprzedaży (16.11.2026).** Pierwsze pobranie cofało się o 3 miesiące (`INITIAL_MONTHS_BACK`),
  więc sprzedaż z KSeF zaczynała się 04.08.2026, choć KSeF działa od 02.2026. `_backfill` w
  `client_invoicing/sync.py` idzie po bieżącej pętli i po XML-ach e-faktur (z resztki budżetu, więc nowe faktury
  nie czekają): okna po 99 dni od `BACKFILL_FROM` (2025-01-01) do dnia sprzed pierwszego znacznika (`to` zapisane
  raz w `app_settings['client_sales_ksef_sync'].backfill` per środowisko i NIP), znacznik rośnie okno po oknie,
  po dojściu `done`. Faktura, którą już mamy, nie jest pobierana drugi raz. Decyzja Artura 16.11 („cofnij sprzedaż
  wstecz”); skutek: stare faktury dopasowują się do zamówień, a „Nieznani nabywcy” rośnie o ok. 200/mies.
  Zakupy (koszty) cofa się ręcznie „Pobierz ponownie okres” w Płace → Faktury z KSeF (najwyżej 12 miesięcy).
- **Budżet pobrań przy zaległych oknach (16.11.2026).** Dopóki w stanie nie ma `done` przy `backfill`, przebieg ma
  `MAX_DOWNLOADS + BACKFILL_EXTRA_DOWNLOADS` (20 + 30 = 50) pobrań faktury; limit KSeF na produkcji to 64 na godzinę
  i dzieli go pętla zakupów (do 40, zwykle kilka). Po `done` wraca 20. Przekroczenie limitu daje blokadę 429
  (`blocked_until`), nie utratę danych.
- **`done` to koniec listowania, nie pobrań (19.11.2026).** Okno kosztuje jedno zapytanie o metadane, więc
  znacznik dochodzi do `to` w kilka godzin, a faktury z okien czekają w kolejce (`pending`, powód `budget`).
  Na produkcji 19.11 czekało tak 494 faktury (405 z lipca, 42 z czerwca, 47 bieżących z listopada) po 20 na
  godzinę, a w tabeli nie było ani jednej faktury z lipca. Dlatego dodatkowe 30 pobrań zostaje, dopóki w kolejce
  jest choć jedna faktura z powodem `budget` (`_backfill_pending`), także przy fali bieżących faktur na początku
  miesiąca. Kolejka idzie od najnowszych (`acquired_at` malejąco), żeby bieżące faktury nie czekały za zaległymi.
  Brak faktur z jakiegoś miesiąca przy niepustej kolejce to zwykle czekanie, nie luka: sprawdź `pending` w stanie,
  zanim klikniesz cokolwiek ponownie.
- **Adres nabywcy z `Podmiot2/Adres` (0730, 17.11.2026).** Lista „Czeka na Symfonię” i plik dla księgowej potrzebują
  adresu nabywcy, a `clients.address` miał go u 11 ze 170 klientów (staging 17.11: 206 z 208 nabywców bez adresu).
  `client_sales_invoices` ma `buyer_country`, `buyer_address_line1`, `buyer_address_line2` (`KodKraju`, `AdresL1`,
  `AdresL2`) i `buyer_address_read_at`; nowe faktury zapisują je przy pobraniu (`buyer_address.columns`). Faktury
  sprzed 0730 (`buyer_address_read_at IS NULL`) doczytuje ta sama pętla (`buyer_address.py`): najpierw z XML-a, który
  już jest w bazie (`client_issued_invoices.xml`, `client_sales_invoice_einvoices.fa_xml`), potem z KSeF z resztki
  budżetu pobrań, na samym końcu przebiegu — po bieżących fakturach, e-fakturach i zaległych oknach. Plik bierzemy
  tylko ze skrótem równym `xml_sha256`. `buyer_address_read_at` stawiamy też, gdy adresu w pliku nie ma, skrót się nie
  zgadza albo KSeF odmawia na stałe, żeby jedna faktura nie zjadała budżetu co godzinę; `not_ready`/`unavailable`
  przerywa doczytanie do następnego przebiegu, 429 jak wszędzie. Przy ok. 20 wolnych pobraniach na godzinę ponad
  1000 starych faktur to 2–3 doby.

## „Po terminie” to brak danych o zapłacie, nie zaległość (19.11.2026)

19.11.2026 zakładka jednego klienta pokazywała „62 po terminie”, a cała firma 2 741 faktur po terminie — żadna z datą
zapłaty. Zapłatę faktury sprzedaży NEXUS zapisuje tylko z uznań na wyciągach (E8), z ręcznego „opłacono” i z lustra
eBI24, a za 2026 r. żadne z nich nie ma danych: wyciągi w Księgowość → Bank są z jednego dnia (12.11.2026, 8 zapłat),
lustro eBI24 nie ruszyło (`EBI24_MODE` ≠ `prod`; 13.11 konto API na produkcji nie widziało dokumentów) i nic by nie dało, bo w eBI24 zapłat się nie
oznacza (w archiwum z 2026 r. zapłatę ma 8 z 5 117 faktur sprzedaży).

- **Bez dowodu z wyciągów NEXUS nie liczy zaległości** (dowód — sekcja niżej, od 0742). Faktura z terminem za sobą
  i bez pełnej zapłaty ma wtedy `payment_unknown: true` i `overdue_days: 0`: przy fakturze „brak danych o zapłacie” z terminem pod spodem,
  w kroku „Zapłata” paska zakładki klienta i karty „Rozliczenie” w Przeglądzie (kroki miesiąca od 20.11.2026,
  `klienci/profil-klienta-piec-sekcji.md`) „brak danych o zapłacie” albo „N bez danych o zapłacie”,
  w Finansach → „Po terminie” zdanie z liczbą takich faktur, bez licznika „0” na zakładce. Trasy zaległości
  zwracają w zakresie konta `invoices` (tylko faktury z dowodem), `payment_unknown` i `payment_unknown_reasons`.
- Częściowa wpłata z wyciągu zostaje „zapłacono część”: część jest faktem, o reszcie NEXUS nie wie.
- **Nie wracaj do zaległości z samego terminu** ani z samych dni wyciągów. Przegląd z 19.11.2026 pokazał, czego
  potrzeba, żeby „po terminie” było prawdą: wyciągi rachunku, na który płaci dany klient (domyślny rachunek EUR
  z faktur nie jest w Księdze, a na rachunek EUR z Księgi płacą tylko dwaj klienci), ciągłe dla każdego rachunku
  (rachunek EUR nie ma operacji co dzień, więc ciągłość po dniach operacji nie wystarcza — potrzebne saldo otwarcia
  i zamknięcia wyciągu), wgrane po tym, jak faktura była już w NEXUSIE (E8 dopasowuje uznania tylko do istniejących
  faktur), i bez faktur rozliczanych kompensatą (seria „Benefit”, 590 faktur w 2026 r.). Ten etap jest w sekcji niżej.
- Próbka 12.11.2026: wszystkie 102 uznania, których E8 nie przypisało, to nogi VAT zapłat dla dostawców (MPP
  z cudzym NIP-em w `/IDC/`) — wpłat klientów E8 nie przeoczyło.

## „Po terminie” z ciągłych wyciągów rachunku odbioru (0742, 19.11.2026)

Decyzja Artura z 19.11.2026: Finanse wgrywają w Księgowość → Bank wyciągi wstecz od 04.2026, miesięczne, kontem bez
Płac (konto z Płacami puszcza R9, które oznaczyłoby stare wypłaty i wysłało ludziom powiadomienia). Faktura (łańcuch
z korektami) z terminem za sobą i czymś do zapłaty jest „po terminie” tylko z dowodem
(`client_invoicing/payment_proof.py`); inaczej „brak danych o zapłacie” z powodem (`payment_unknown_reason`):

1. `compensation` — seria „Benefit” (wzór serii BEN z ustawień wystawiania i domyślny `{n}/{m}/{yyyy}/Benefit`
   dla faktur z eBI24): rozliczenie kompensatą oznacza się „Opłacono” z powodem.
2. `no_account`, `account_outside_ledger` — rachunek odbioru to nadpisanie przy kliencie dla waluty, a bez niego
   domyślny rachunek waluty (`issue_settings.account_for`), porównywany jako 26 cyfr NRB. Musi być w Księgowość →
   Ustawienia → Rachunki w walucie faktury. Domyślnego rachunku EUR z faktur 19.11.2026 tam nie było: dodaje go
   Artur albo Finanse (Claude numerów rachunków nie wpisuje).
3. `statements` — łańcuch sald wyciągów tego rachunku (`ledger/bank_continuity.py`) od wyciągu otwartego **przed**
   dniem wystawienia (przy dacie SWIFT otwarcie z dniem X nie obejmuje operacji z dnia X) do dnia **po** terminie:
   termin w ostatnim dniu ciągłości to jeszcze brak danych. Wyciąg następuje po poprzednim, gdy jego saldo otwarcia
   = saldo zamknięcia poprzedniego i nic między nimi nie brakuje: przy znanych numerach wyciągów banku (`:28C:`,
   `LglSeqNb`) numer jest następny (w nowym roku kończy się na 001; ten sam numer = części jednego wyciągu, tylko
   w tym samym dniu), a bez numerów otwarcie wypada najpóźniej dzień po zamknięciu poprzedniego. Numery
   rozstrzygają także przy stykających się datach: przy dacie SWIFT (otwarcie z dniem poprzedniego wyciągu)
   brakujący wyciąg mieści się między dwoma sąsiednimi dniami (przegląd 19.11.2026: 45 → 47). Santander (eBI24)
   daje wyciąg tylko w dni z operacjami, a `:28C:` to rok i numer wyciągu w roku, więc dni bez wyciągu mostkuje
   numer. Równe saldo nad luką nie wystarcza: brakujący wyciąg mógł mieć wpływ i wypływ tej samej kwoty
   (wpłata w EUR i jej wymiana). Liczą się tylko wyciągi wgrane, gdy cały łańcuch faktury był już
   w NEXUSIE (`created_at`; E8 dopasowuje uznania tylko do istniejących faktur), i takie, których uznania przeszły
   przez E8 (`ledger_bank_statements.credits_matched`: moduł faktur do klientów wyłączony albo błąd E8 w ścieżce
   Płac = wyciąg nie dowodzi).
4. `credit_pending` — wpłata z wyciągu, której E8 nie przypisało, może być jej zapłatą: wpłata do sprawdzenia
   (E8 `unmatched`) i duplikat E8 bez oryginału (oryginał skasowało „Usuń wyciąg”) z numerem faktury albo KSeF
   w tytule albo w tej samej walucie z kwotą równą temu, co zostało do zapłaty (nie sprzed wystawienia), oraz
   operacja Księgi bez konta albo przypisana ręcznie (`ledger_bank_lines.kind` `unmatched`/`manual`) w tej samej
   walucie i kwocie, w dniach od wystawienia do końca ciągłości. E8 nie zapisuje uznania bez numeru, którego
   kwota pasuje do kilku faktur (przegląd 19.11.2026: dwie faktury po tej samej kwocie, wpłata jednego klienta
   bez numeru). Tytułów operacji Księgi nie porównujemy: nogi VAT zapłat dla dostawców niosą numery cudzych
   faktur, takie jak nasze (12.11.2026). Przelew zbiorczy za kilka faktur bez numerów w tytule nie pasuje kwotą
   do żadnej — takie faktury Finanse zamykają „Opłacono”.

- **Dni po terminie liczą się do ostatniego dnia ciągłości** (`statements_until`; przy fakturze „wyciągi do DD.MM”),
  nie do dziś: po nim NEXUS o wpłatach nie wie. Częściowa wpłata z dowodem dla reszty: „po terminie” z „zapłacono
  część · zostało …”.
- Finanse → „Po terminie”: lista z dowodem i zdanie o fakturach bez danych z powodami (`payment_unknown_reasons`:
  powód, końcówka rachunku, liczba faktur). Zakładka klienta i karta „Rozliczenie” w Przeglądzie: krok „Zapłata”
  faktur miesiąca — „N z M po terminie” tylko z dowodem (decyzja Artura z 20.11.2026), bez dowodu „brak danych
  o zapłacie” z powodem w drobnym druku, gdy wszystkie faktury mają ten sam; faktury z dowodem z wcześniejszych
  miesięcy są listą „Po terminie z wcześniejszych miesięcy” pod tabelą.
- **Salda wyciągu** (`opening_balance`, `opening_day`, `closing_balance`, `closing_day`, `first_number`,
  `last_number` w `ledger_bank_statements`) zapisuje import w Księdze z `ParsedStatement.balances` (parser czyta też
  daty sald i numer wyciągu), tylko gdy plik sam jest ciągły: każda część ma oba salda z datami, suma operacji =
  suma zmian sald, a części łączą się jak kolejne pliki. Inaczej pola są puste i plik niczego nie dowodzi (nie jest
  odrzucany). Reguła importu: `docs/claude/finanse-insights/ksiega-nexusa-k4-bank.md`.
- **Wyciąg wgrany przed 0742** nie ma sald: ponowne wgranie tego samego pliku je uzupełnia, bez drugiego importu
  operacji (E3, R9, E8 i linie zostają). `credits_matched` takich wyciągów ustawia raz migracja z dowodu w bazie
  (plik bez uznań albo z zapisem E8; znacznik `ledger_bank_credits_matched_backfill`).
- Testy: `tests/test_ledger_bank_continuity.py` (parser, plik, łańcuch), `tests/test_client_invoicing_payment_proof.py`
  (werdykt bez bazy), API w `tests/test_client_invoicing_api.py`, import w `tests/test_ledger_sources_db.py`.
