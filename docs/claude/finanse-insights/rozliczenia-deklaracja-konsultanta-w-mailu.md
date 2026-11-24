# Rozliczenia: deklaracja konsultanta w treści maila jako raport za miesiąc

<!-- indeks: deklaracja konsultanta, report.consultant_declaration, nie miałam dni wolnych, bez dni wolnych, pełny miesiąc, dni wolne, mail z fakturą bez pliku, Faktura wrzesień, mail_declaration, is_body_only_declaration, declaration_clients, sender_contract_ids, _consultant_mails, mLeasing, dni robocze -->

Od 23.11.2026. Decyzja Artura: „Deklaracja wystarcza”. Część klientów nie ma pliku godzin.
Wtedy raportem jest zdanie konsultanta w mailu z fakturą, np. „Fakturę przesłałam przez KSeF.
We wrześniu nie miałam dni wolnych”. Finanse fakturują wtedy pełny miesiąc (IX 2026: 176 h
= 22 MD). W próbie IX–X 2026 tak rozlicza się mLeasing. Dotąd router zostawiał taki mail
tylko jako sprawę, a silnik czytał z `.eml` wyłącznie akceptację NN, więc NEXUS nie miał
dokumentu.

## Reguła

Reguła klienta nazywa się `report.consultant_declaration` („Deklaracja konsultanta w treści
maila wystarcza jako raport”). Stoi w sekcji „Dowód pracy”, a domyślnie jest wyłączona.
Działa tylko u klienta, który ma ją włączoną w zestawie na dany miesiąc. Zestaw zapisany
przed tą regułą sam jej nie włącza. Poziom („Ostrzega” albo „Blokuje”) nie zmienia odczytu,
liczy się samo włączenie. Reguła nie jest przypięta do nazwy klienta.

Finanse włączają ją w **Finanse → Rozliczenia → wybór klienta → Reguły klienta → Dowód pracy**.
Ustawiają „Ostrzega” i zapisują z miesiącem, od którego reguła ma działać. Na produkcji
23.11.2026 żaden klient nie miał zapisanego zestawu reguł.

## Co daje zdanie (`client_settlements/mail_declaration.py`)

Czytamy tylko własną część maila. Cytowany wątek pod „Od:”/„From:” i linie z „>” pomijamy.
Mail dzielimy na zdania i części zdań między przecinkami. Deklaracja musi stać w jednej
części razem z pełną nazwą miesiąca („wrzesień”, „września”, „wrześniu”). Same rdzenie
nie wystarczają, bo łapały imiona („Marta”, „Maja”). Od 24.11.2026 nazwa od 7 liter
z jedną brakującą literą („wrzeniu”, mLeasing IX 2026) też jest nazwą miesiąca. Krótszych
nazw („maja”, „luty”) nie poprawiamy, bo bez litery dają inne słowa. Nazwa bez roku bierze
rok rozliczanego miesiąca. Poza deklaracją i miesiącem w tej części mogą stać tylko słowa
z białej listy (`_FILLER`: „we”, „za”, „przepracowałam”, „cały”…). Każde inne słowo
(„nie przepracowałam”, „byłam chora”, „będę”, „czy”) oznacza, że MD nie wpisujemy.
Decyzja z recenzji kodu 23.11.2026: przy kwotach lepiej oddać deklarację Finansom niż
wpisać złe MD.

| Zdanie | MD |
|---|---|
| „nie miałam/miałem (żadnych) dni wolnych”, „nie miałam wolnego”, „bez dni wolnych”, „pełny miesiąc”, także z „od pracy” („dni wolnych od pracy”) | dni robocze miesiąca |
| „miałam 2 dni wolnego”, „miałem jeden dzień wolny”, „miałam 3 dni urlopu” (czas przeszły, 1. osoba, liczba całkowita) | dni robocze minus ta liczba |
| bez nazwy miesiąca, „miałam dni wolne” (bez liczby), „0,5 dnia”, „będę miała”, choroba, L4, nieobecność, dni pracy, dwie różne deklaracje | brak, uwaga dla Finansów |
| inny miesiąc albo rok niż rozliczany | brak, kontrola `proof.month` |

Dni robocze to kalendarz firmy: dni od poniedziałku do piątku bez polskich świąt
(`person_workdays.business_days`), tak samo jak w `fields.md_month_limit`. Odczyt działa
też bez polskich znaków („nie mialam dni wolnych”).

## Kto może zadeklarować

Deklaracja liczy się tylko od samego konsultanta kontraktu. Zdanie koordynatora o kimś innym
nie jest deklaracją.

- **Router** (`consultant_portal/mailbox.is_body_only_declaration`): mail bez załącznika
  z adresu firmy, z tematem faktury („Faktura wrzesień”), z adresem rozliczeń w „Do” albo „DW”.
  Wpuszczamy go tylko wtedy, gdy co najmniej jeden klient ma regułę
  (`support_mail_route.declaration_clients`, bieżący i poprzedni miesiąc). `_store_declaration`
  zapisuje `.eml`, gdy nadawca wskazuje kontrakt (`identity.resolve_sender`, bez osoby
  z tematu), a klient tego kontraktu ma regułę. W pozostałych przypadkach mail idzie dalej
  zwykłą ścieżką maili bez pliku. Jak przy `is_body_only_settlement` mail zostaje też sprawą
  („sprawa i dokument”).
- **Silnik** (`service._consultant_mails`): czyta deklarację tylko z `.eml`, którego nadawca
  (`sender_email`) należy do tego kontraktu. Nadawcę rozpoznajemy po adresie z kontraktu,
  adresie z kartoteki albo skrzynce firmowej `imie.nazwisko@` (`identity.sender_contract_ids`).
  Mail wgrany w panelu nie ma nadawcy, więc deklaracji nie daje.

Mail z tematem rozliczenia („Rozliczenie 09.2026”) zapisuje już `is_body_only_settlement`.
Silnik przeczyta z niego deklarację na tych samych zasadach, bo sprawdza nadawcę.

Pliki pokrewne: `rozliczenia-akceptacja-w-tresci-maila.md`, `rozliczenia-czytniki-plikow-klientow.md`,
`ludzie/jedna-skrzynka-wsparcie.md` (sekcja „Router E8”).
