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
- **Numer nabywcy idzie do klienta przy ręcznym przypisaniu.** Pomiar z 02.11.2026 na fakturach z października:
  173 ze 188 NIP-ów nabywców nie ma klienta w NEXUSIE, ok. 197 faktur miesięcznie; numer w profilu ma 18 ze 169
  klientów. Okno „Przypisz” pozwala wskazać klienta, a przycisk „Przypisz i dopisz NIP” (`save_buyer_number`) zapisuje
  numer u klienta kanonicznego i od razu dopasowuje pozostałe faktury tego nabywcy. Nie czekamy na `rematch_pending`,
  bo idzie po kolejce paczkami (niżej). Numeru nie zapisujemy, gdy klient albo jego scalony duplikat ma inny numer
  (także tekst w tym polu), ani gdy numer ma inny klient: dopisanie zrobiłoby `ambiguous_buyer` i zatrzymało faktury
  obu klientów. Faktura przypisuje się wtedy normalnie. Zapis trafia do Historii zdarzeń
  (`client.registry_number_added`). Dopisanie jest z potwierdzeniem (decyzja Artura z 02.11.2026): obok głównego
  przycisku jest „Tylko przypisz”, bo faktura spółki zależnej bywa rozliczana z zamówienia spółki matki. Klient bez
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

## Nieznani nabywcy i NIP w formularzu (audyt C5, 08.11.2026)

- **Finanse → Faktury do klientów → „Nieznani nabywcy”** to kolejka faktur `unmatched/unknown_buyer` ze wszystkich miesięcy, po numerze
  nabywcy (`views.unknown_buyers`). „Przypisz” dopisuje numer do klienta tym samym `save_buyer_number` co okno pojedynczej faktury, więc
  odmowy (`differs`, `taken`) i wpis w Historii zdarzeń działają tak samo; „Pomiń” pomija wszystkie czekające faktury nabywcy, z powodem.
  Wiersz bez numeru i z numerem uciętym (`FR1`) nie ma akcji: tych faktur nie da się skleić po numerze.
- **Podpowiedź klienta jest tylko jednoznaczna**: nazwa z faktury równa `legal_name`, `display_name` albo `name` dokładnie jednego
  klienta (bez nieaktywnych), bez wielkości liter. Dwóch klientów o tej samej nazwie to brak podpowiedzi, a klient z innym numerem nie
  dostaje „Przypisz” jednym kliknięciem. Pomiar z 06.11: 13 nabywców z podpowiedzią.
- Suma kolejki znika bez uprawnienia „Wyniki firmy”, tak jak suma miesiąca (decyzja z 02.11).
- **Formularz klienta ma NIP i „Nazwa prawna”** tam, gdzie konto widzi dane prawne. NIP przechodzi sumę kontrolną
  (`client_registry_number`); zagraniczny numer idzie z prefiksem kraju. Zapisujemy postać rejestru (bez kresek i `PL`). Numer innego
  klienta to 409, bo dwa takie wiersze zatrzymałyby faktury obu. Zapis wysyła pole tylko po zmianie: stary tekst w polu NIP nie blokuje
  edycji reszty formularza. Zmiana numeru od razu dopasowuje czekające faktury, także przy zakładaniu klienta.
- **Alert DL o fakturze bez pozycji** (`invoice_without_order_line`, `services/client_invoicing/line_gaps.py`): faktura czeka na Finanse
  z powodem `no_orders`, `amount_differs` albo `expected_unknown`, a pozycja nazywa pełnym imieniem i nazwiskiem osobę z kontraktem
  u tego klienta, która w miesiącu usługi nie ma pozycji zamówienia. Nazwisko spoza kontraktów zostaje Finansom. Faktury starsze niż
  3 miesiące nie alarmują, karta zamyka się sama po przypisaniu faktury albo dopisaniu pozycji.
