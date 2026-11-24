# Rozliczenia: faktura do klienta z T4T tylko z godzin zatwierdzonych

<!-- indeks: Nordea, T4T, Time for Teams, status 2, Approved, Do faktury dla klienta, client_invoice, t4t_invoice, awaiting_t4t, Czeka na T4T, godziny niezatwierdzone, wersja raportu, akceptacja mailowa managera, osoba odeszła z projektu, art. 106i, termin faktury 15. dnia, warn_days, noty kredytowe, korekta okresu -->

Od 23.11.2026. Od września Nordea przyjmuje na fakturze sprzedaży tylko godziny zatwierdzone
w Time for Teams (status 2). Za wrzesień 18 osób miało w ostatniej wersji raportu godziny
niezatwierdzone, a 23 wystawione faktury miały więcej godzin niż zatwierdzone, 11 z nich
dokładnie o 32 h (ostatni tydzień). Nordea zapowiada odrzucanie takich faktur i noty
kredytowe. Pomiar na kopii stagingu `nexus_staging_klodko_v5`.

## Reguła

Klient z regułą `report.time_for_teams` (poziom inny niż „wyłączona”) ma w „Do faktury dla
klienta” pozycje z raportu T4T, nie z RCP (`services/client_settlements/t4t_invoice.py`,
`client_invoice._t4t_month`):

- **Podstawa:** godziny w statusie 2 z **ostatniej** wersji raportu za miesiąc (data
  otrzymania, potem numer wersji). Wersje się nie sumują. Godziny osoby liczą się tylko
  przez potwierdzony numer w kartotece (`client_external_ids`).
- **Pozycja:** linia zamówienia godzinowa w zł daje „godz.” × stawka klienta, tak jak dziś
  faktury Nordei. Inna linia daje MD (godziny ÷ 8) × stawka MD. Nazwa pochodzi z reguły
  `cl.item_name`, a bez niej z pozycji „godz.” ostatniej faktury tej linii albo grupy.
  Faktura za koszty podróży (PKP, hotel w „szt.”) nazwy nie daje. Koszt w marży to godziny
  × stawka kontraktora + zatwierdzone dodatki.
- **Blokada:** godziny w statusie 0 albo 1 w ostatniej wersji dają stan `awaiting_t4t`
  („Czeka na T4T”) z powodem „Godziny niezatwierdzone w T4T (wersja z DD.MM): N h czeka
  na akceptację”. Pozycja pokazuje same godziny zatwierdzone, ale nie trafia do
  „Kopiuj pozycje”. Osoba bez zatwierdzonych godzin nie ma pozycji.
- **Wystawiona faktura ponad zatwierdzone:** gdy faktura za miesiąc (z linii albo grupy) ma
  w pozycjach „godz.” więcej godzin niż zatwierdzone, wiersz dostaje uwagę „klient może ją
  odrzucić, potrzebna korekta”.

## Wyjątek: mailowa akceptacja managera

Line manager klienta zatwierdza godziny mailem z liczbą godzin, gdy osoba odeszła
z projektu i nie poprawi T4T albo gdy okres w T4T zamknął się przed akceptacją („By this
mail, I approve 184 hours … for July”). Cost Control to przyjmuje: 4 maile w VIII–X ze
skrzynki koordynatorki i co najmniej 2 przypadki w X–XI ze skrzynek DL-ów. Akceptacje
w T4T Nordea egzekwuje od 01.07.2026.

`extra.mail_accept` (zgoda na nadgodziny w RCP BNP) i `client_acceptance` (paczka KCP
Banku Pocztowego, stan przy rozliczeniu) do tego nie pasują: Nordea nie ma rozliczeń
z RCP. Wyjątek korzysta z odczytu `proof.accept_has_hours` (`mail_text.read_acceptance`,
z angielskimi godzinami i miesiącami `english=True`). Wszystkie warunki muszą być spełnione:

- mail (`.eml`/`.msg`) leży przy osobie jako dokument rozliczenia za ten miesiąc albo
  następny, nieodrzucony;
- w wątku jest wiadomość z domeny z kontaktów klienta (Nordea: nordea.com). Nasza prośba
  „please approve the 102 hours” sama nie wystarczy;
- jest akceptacja, rozliczany miesiąc i dokładnie jedna liczba godzin.

Wtedy pozycja idzie na godziny z maila z uwagą „Akceptacja mailowa managera: N h za …”.
Warunku „osoba odeszła” nie ma, bo zamknięty okres dotyczy też osób, które dalej pracują.

Znane ograniczenia:
- Akceptacja w CPro (`noreply@onevms.se`, „please just send the invoice, we will
  approve”) nie ma liczby godzin ani domeny klienta, więc nie odblokowuje pozycji. Takie
  przypadki Finanse rozstrzygają same.
- Mail managera musi trafić do NEXUS-a jako dokument przy osobie. Dziś leży w skrzynkach
  osobistych koordynatorki i DL-ów.

## Termin faktury (art. 106i ust. 1 VAT)

Fakturę wystawia się najpóźniej 15. dnia miesiąca po miesiącu usługi. Parametr reguły
„ostrzeżenie” (`warn_days`, domyślnie 5) ustala, ile dni przed tym dniem ekran pokazuje
pasek: ile osób i które nie mają zatwierdzonych godzin (czekają na T4T albo nie mają
godzin), bez osób z już wystawioną fakturą. Po terminie pasek mówi, ile dni minęło.
Na kopii z 10.11 za październik takich osób było 13.

## Czego automat nie robi

- **Godziny przeniesione z poprzedniego miesiąca** nie są osobną pozycją „korekta okresu”.
  Decyzja Artura z 23.11.2026: idą w pozycji miesiąca, w którym je zatwierdzono, tak jak
  liczy je Nordea. Raport ich zresztą nie odróżnia: w wersjach IX–X nie ma wiersza z datą
  pracy z innego miesiąca. Nie proponuj ponownie wyliczania nadwyżki ani pola do wpisania.
  Praktyka wobec kontraktora (zapłata za godziny faktyczne albo korekta faktury) zostaje
  decyzją Finansów (`rozliczenia-praktyka-z-korespondencji.md`, „Do decyzji Finansów”).
- Wystawianie faktur w NEXUSIE (FA(3), `client_invoicing/billing.py`) liczy godziny
  z zamówienia, nie z T4T. Ta reguła go nie zmienia.
- Klient bez reguły T4T ma „Do faktury dla klienta” z RCP jak dotąd.
