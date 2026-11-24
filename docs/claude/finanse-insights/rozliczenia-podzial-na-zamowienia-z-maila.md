# Rozliczenia: podział miesiąca osoby na zamówienia według maila klienta

<!-- indeks: podział na zamówienia, kilka zamówień w miesiącu, order_split, split_orders, engine.SplitPart, Result.orders, charged_orders, FIN-MD-01, _refuse_split_month, zamówienie zakończone, bez puli, faktura na zamówienie, Do faktury, potwierdzenie usług, tabela przestawna, Etykiety wierszy, numer SAP, BIK, Polkomtel, _store_split_table, resolve_split_row, split_client -->

Od 24.11.2026. Klient czasem prosi o fakturę osobno na każde zamówienie i sam pisze, ile MD
albo godzin osoby idzie na które. Do tej pory rozliczenie osoby za miesiąc miało jedno
zamówienie (`service._order_for`), więc „Do faktury” nie zgadzało się z fakturami Finansów.
W próbie IX–X 2026 były dwa wzory:

- **linie w treści (BIK, X)**: odpowiedź klienta na naszą prośbę o akceptację, „Akceptuję.
  Prośba o rozliczenie października według zamówień:” i linie „<numer>: 40h  <kwota> PLN”;
- **tabela przestawna (Polkomtel, IX)**: koordynatorka klienta wkleja tabelę „Etykiety
  wierszy” × numery SAP, wiersz to osoba („Nazwisko Imię”), w komórkach MD.

## Reguła

Czytnik: `app/services/client_settlements/order_split.py` (bez bazy). Tabelę czyta tylko z HTML,
bo tekst maila gubi puste komórki i liczby trafiają do złych kolumn. Linie bierze z pierwszej
wiadomości wątku, która je ma, bo cytaty niżej mają nieaktualne liczby.

Rozliczenie (`service._recompute`) bierze podział z maili miesiąca osoby, najnowszy pierwszy:

- **Autor z domeny klienta** (`acceptance_senders`), także przy wyłączonych regułach
  akceptacji, i nie sam konsultant ze skrzynką u klienta (`_without_consultant`, #3884).
  Zamówienia wskazuje klient, więc ten sam tekst napisany u nas nie dzieli rozliczenia.
- **Osoba**: przy liniach osoba dokumentu, przy tabeli wiersz z jej imieniem i nazwiskiem
  w dowolnej kolejności.
- **Zamówienie** po numerze z maila wśród linii zamówień kontraktu (bez anulowanych), także
  zakończonych i spoza miesiąca. Porównujemy bez przedrostka spółki, więc „SAP 4500…” i „4500…”
  to ten sam numer (`timesheet_plus.order_key`). Numer, którego osoba nie ma w NEXUS-ie, albo
  dwa numery na jednej linii dają uwagę „Podział z maila klienta nie wszedł”, a MD idą na jedno
  zamówienie jak dotąd.
- **Jednostka**: godziny (h, godz.) dzielimy przez `fields.md_hours`. Tabela bez jednostki to MD,
  chyba że dopiero suma wiersza podzielona przez godziny w MD daje MD rozliczenia. Bez MD
  rozliczenia jednostkę wybieramy raz dla całej tabeli (wiersz ponad 31 = godziny).
- **Zaokrąglenie**: reszta z zaokrąglenia części do 0,001 MD idzie na zamówienie rozliczenia,
  więc suma części, zejście i koszt są jak na jednym zamówieniu.
- **Suma podziału = MD rozliczenia** i same dni zwykłe. Inna suma albo praca dodatkowa czy
  MD wdrożeniowe w miesiącu dają uwagę i jedno zamówienie, bo nie wiadomo, które zamówienie
  dostaje nadgodziny. Taki miesiąc Finanse dzielą ręcznie.
- **MD z samego podziału**, gdy żaden plik miesiąca nie dał liczby (BIK X: jedynym dokumentem
  była odpowiedź klienta). Kontrole są jak przy dokumencie z deklarowaną sumą (`declared`):
  miesiąc, osoba z wiersza albo z tematu wątku, limit MD, `proof.accept_has_hours`.
  Gdy jest Time Sheet albo RCP, MD idą z nich, a podział tylko rozkłada je na zamówienia.

Każde zamówienie ma własną linię rozliczenia, stawkę z dnia miesiąca (`priced_one`), pulę
i zejście (`engine._with_split`). Zamówieniem rozliczenia (`ClientSettlement.order_id`) jest
to z największą częścią MD. Podział zapisujemy w danych przy kontrolach (`ORDERS`,
`service.split_orders`), bez migracji.

### Zamówienie zakończone albo bez puli: jak w mailu, z uwagą

Decyzja Artura z 24.11.2026. Linie, koszt, zejście i faktura idą tak, jak napisał klient.
Zamówienie zakończone w NEXUS-ie (status albo koniec przed miesiącem) i pula za mała dostają
uwagę „uzupełnij zamówienie w NEXUS-ie”, ale przyjęcia to nie blokuje, także przy
`order.no_md_holds_invoice` na poziomie „Blokuje”. Pula może zejść poniżej zera.

Powód: klient sam wskazał zamówienie, a pule w NEXUS-ie bywają nieaktualne. W przypadku BIK
za X jedno zamówienie było „zakończone” z zerową pulą, a drugiemu zostawał 1 MD, mimo że
Finanse wystawiły obie faktury jak w mailu. Odrzucone warianty: „nadwyżka czeka na Finanse”
(dzisiejsza zasada z 10.11 dla jednego zamówienia) i „bez podziału na zakończone”.
Decyzja dotyczy każdego zamówienia nazwanego w mailu klienta, także gdy mail nazywa tylko
jedno (wiersz tabeli z jedną komórką, jedna linia „<numer>: 176h”): mail wskazuje zamówienie,
a NEXUS bierze je zamiast tego z `_order_for`. Rozliczenia bez podziału z maila ta decyzja
nie zmienia: ponad pulę dalej czeka.

## Zejście MD przy przyjęciu (FIN-MD-01)

`service.accept` zdejmuje MD z każdej linii podziału osobno (`_charge`, nadpisanie miesiąca).
Odmowa FIN-MD-01 zostaje: wpis za ten miesiąc na innej linii osoby z importu albo ręczny
blokuje przyjęcie, bo MD policzyłyby się dwa razy. Wyjątek dotyczy tylko własnego podziału:
wpis `settlement` na linii, z której zdjęło MD wcześniejsze przyjęcie tego rozliczenia
z podziałem (`CHARGED_ORDERS`). Gdy klient zmieni podział, taki wpis się zeruje.
Przy jednym zamówieniu `CHARGED_ORDERS` się czyści i działa dawna odmowa.

Przy okazji: zejście dostaje linię z sesji, a nie `PricedOrder`. `PricedOrder` jest tylko do
odczytu, a `upsert_consumption` zapisuje na linii `md_remaining`.

## Faktura do klienta i potwierdzenie usług

- **„Do faktury”** (`client_invoice._split_rows`): osoba ma wiersz na każde zamówienie,
  z pozycją MD tej części, stawką i walutą tej linii oraz nazwą z historii faktur tego
  zamówienia. Stan „Wystawiona” liczymy osobno dla każdego zamówienia. Dodatki, korekta planu
  i koszty integracji idą na wiersz zamówienia rozliczenia. Wiersz ma `order_id`, a front
  używa go w kluczu (`ClientInvoiceView`).
- **Lista miesiąca**: numery wszystkich zamówień z podziału („A, B”). „Wystawiona” pojawia się
  dopiero, gdy każde zamówienie ma fakturę za miesiąc.
- **Karta osoby**: pula i zejście każdego zamówienia są w kontrolach, a blok „Zamówienie: …”
  przy podziale się nie pokazuje.
- **Potwierdzenie usług, blok kosztów** (`service_confirmation._person_cost`): MD i netto
  osoby to suma pozycji zamówień. Dwie waluty w podziale dają blok niegotowy.

## Poczta: tabela z forwardu trafia do każdej osoby

Mail z tabelą przyszedł bez pliku, przekazany z adresu firmy, i do tej pory nie trafiał do
nikogo. Teraz `mailbox._store_split_table` (w ścieżce `_store_hours_summary`: adres firmy
i temat rozliczenia) zapisuje go jako raport `.eml` każdej osoby z tabeli. Warunki:

- klient to ten, do którego należą numery zamówień z nagłówka (`identity.split_client`);
  numery u dwóch klientów albo nieznane w NEXUS-ie nie wskazują nikogo;
- tabelę napisał ktoś z domeny tego klienta (nadawca z cytatu nad tabelą);
- osobę z wiersza szukamy tylko wśród kontraktów tego klienta, po wszystkich słowach imienia
  i nazwiska (`identity.resolve_split_row`); osoba z dwoma kontraktami u klienta dostaje ten
  z linią zamówienia o numerze z tabeli;
- okres pochodzi z tematu albo tabeli; zgadnięty z daty maila nie wystarcza.

Linie BIK przychodzą od klienta wprost i trafiają jak dotąd: osoba z tematu
(`_store_client_acceptance`).

## Czego to nie robi

- Tabeli wysłanej przez klienta wprost na rozliczenia@, nie z adresu firmy, nie rozsyłamy do
  osób. W próbie nie było takiego maila.
- Nie dzieli pracy dodatkowej ani MD wdrożeniowych.
- Nie czyta numerów zamówień z innych wzorów, np. z tabeli NN „Numer zamówienia”.
- Dokumenty dla klienta liczone z jednego zamówienia (`client_documents`: protokół PKO,
  arkusze Velo) i ekran estymacji biorą zamówienie rozliczenia (`order_id`). U tych klientów
  podziału z maila w próbie nie było.

## Pomiar (kopia `nexus_staging_klodko_v6`, transakcja z ROLLBACK, 24.11.2026)

Porównaliśmy przeliczenie kodem z `main` i z gałęzi na 353 rozliczeniach IX–X. Wyszły
3 zmiany, innych zmian nie było:

- BIK X: MD z odpowiedzi klienta, linie 5 + 17 MD jak dwie faktury Finansów;
- Polkomtel IX: 3 linie (7 / 1,75 / 13,25 MD, jedna linia z inną stawką) równe trzem fakturom.
  Przychód różni się od liczonego na jednym zamówieniu.
- Polkomtel IX, druga osoba z tabeli: nowe rozliczenie, 21 MD jak faktura.

Polkomtel X został na jednym zamówieniu, bo tabela za październik nie przyszła na rozliczenia@
(archiwum do 20.11). Finanse podzieliły go z innego źródła. Gdy tabela przyjdzie na
rozliczenia@, podział zadziała tak samo.
