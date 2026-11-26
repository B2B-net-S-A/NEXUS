# Rozliczenia: wzór dokumentu wskazuje klienta (osoba u dwóch klientów)

<!-- indeks: wzór dokumentu, KCP, karta pracy, Bank Pocztowy, VeloBank, Time Sheet, GridTable, Strumień, Nr strumienia, dwa kontrakty, dwóch klientów, timelogLip, templates.recognize, resolve_by_template, contracts_at_several_clients, parse_velobank, Suma dni przepracowanych, karta Alior, karta ręcznego przypisania, przekazany wątek -->

Od 26.11.2026. Konsultant z kontraktem w Banku Pocztowym i VeloBanku wysyła z adresu
firmy jednym mailem dokumenty obu banków. Adres wskazuje dwa kontrakty, więc karta
KCP i Time Sheet czekały bez osoby. Gdy w mailu był przekazany wątek ze skrzynki
w jednym z banków, cały mail, razem z kartą drugiego banku, szedł do tego
kontraktu (poczta za VII i VIII 2026).

## Reguła

Dotyczy tylko osoby z działającymi kontraktami u co najmniej dwóch klientów. Osoba
to ta z kontraktu wybranego już dla pliku, a bez niego jedyna osoba pod adresem
nadawcy (`identity.contracts_at_several_clients`). Dla raportu (`kind == "report"`)
czytnik sprawdza wzór pliku (`consultant_portal/templates.recognize`) i gdy wzór
należy do klienta, rozstrzyga `identity.resolve_by_template`:

- jedyny kontrakt osoby u tego klienta, który działa w miesiącu dokumentu, dostaje
  plik. Wygrywa to z kontraktem z przekazanego wątku i ze skrzynki u drugiego klienta;
- dwa takie kontrakty, żaden działający albo brak miesiąca: karta do ręcznego
  przypisania. Plik nie idzie wtedy do klienta, którego wzorem nie jest (dotąd
  karta za miesiąc po końcu kontraktu szła do drugiego banku przez
  `resolve_sender_in_month`);
- czytnik działa jak dotąd, gdy osoba nie ma kontraktu u klienta wzoru, w pliku
  stoi inne imię i nazwisko, wybrany kontrakt już jest u tego klienta albo plik
  nie ma wzoru. Faktura nigdy nie ma wzoru.

Miesiąc bierzemy z pliku, a bez niego z nazwy albo tematu. Okres zgadnięty z daty
maila nie rozstrzyga. Dodatkowe słowa w polu osoby nie przeszkadzają (karta banku ma
tam skrót działu).

## Które wzory

Przegląd archiwum rozliczenia@ i administracja@ III–XI 2026 (załączniki z powtórek
poczty na kopii produkcji):

| Wzór | Poznajemy po | Czego nie wystarcza |
| --- | --- | --- |
| KCP Banku Pocztowego | tytuł karty i wypełniony wiersz „Liczba godzin czas podstawowy” (w archiwum mają go wszystkie 74 karty przypisane bankowi, a żadna Aliora ani PKO BP) | sam tytuł: tak samo nazywają się karty Aliora i PKO BP; „Suma dni przepracowanych”: ma ją też wydruk karty Aliora z NEXUS-a (`kesu.render_html`) |
| Time Sheet VeloBanku | kolumna „Strumień” albo „Nr strumienia”, albo „Velo(Bank)” w nazwie projektu | arkusz „GridTable”: to ogólny eksport, ma go co najmniej siedmiu klientów; „velo” stoi też w „Development” |

Rodzaj pliku (raport czy faktura) rozstrzyga osobno `mailbox.kind_of_file`: każda
karta ewidencji w PDF jest raportem bez względu na nazwę pliku (#4029).

## Nowy wzór

Dopisuj w `templates.recognize` tylko cechę, która w archiwum stoi u jednego
klienta, i dodaj test z plikiem innego klienta, który tej cechy nie ma. Klucz
klienta jest z `order_policies/known_clients.KNOWN_REGISTRY_IDS` (NIP).

## Czego ta zmiana nie robi

- Nie przypisuje faktury. Faktura z maila z przekazanym wątkiem nadal dziedziczy
  kontrakt z wątku, jeśli czytnik tak wybrał dotąd.
- Nie działa dla koordynatora, który przesyła cudze pliki: adres nie wskazuje osoby.
- Nie przepina dokumentów zapisanych wcześniej.

Powiązane: `finanse-insights/rozliczenia-nadawca-i-okres-z-poczty.md`,
`finanse-insights/rozliczenia-osoba-z-pliku-skrzynki-i-umowy.md`.
