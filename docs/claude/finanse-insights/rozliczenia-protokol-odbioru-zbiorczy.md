# Rozliczenia: protokół odbioru zbiorczy (Centrum e-Zdrowia, PFRON)

<!-- indeks: protokół odbioru, protocol_collective, CeZ, umowa wykonawcza, PFRON, Specjalisty, Liczba Roboczogodzin, Suma końcowa, raport zbiorczy kilku osób, brak raportu w poczcie rozliczeń, Przebieg miesiąca, _store_client_reports -->

Od 23.11.2026. W powtórce IX–X 2026 (kopia `nexus_staging_klodko_v5`) „Przebieg
miesiąca” pokazywał za X PFRON 16 z 18 osób i Centrum e-Zdrowia 10 z 10 osób jako
„brak raportu w poczcie rozliczeń”. Ci klienci nie przysyłają RCP osoby. Rozliczają
się podpisanym protokołem odbioru dla całej umowy, a PM albo koordynatorka rozliczeń
przekazuje go na rozliczenia@. Protokoły leżały w `cp_documents` jako raporty bez
kontraktu, czyli jako karty do ręcznego przypisania.

## Dwa wzory (`client_settlements/protocol_collective.py`)

- **CeZ:** „Protokół odbioru · Nr umowy (Wykonawczej) CeZ/…”, okres „w okresie od
  DD.MM.RRRR do DD.MM.RRRR”, w tabeli „Zestawienie” wiersz osoby „Imię Nazwisko
  Suma 176”, pod nią „Suma końcowa”. Tabela szczegółów pod „Podsumowaniem projektu”
  się nie liczy. Protokół jest jeden na umowę wykonawczą, więc osoba bywa tylko
  w jednym z kilku protokołów miesiąca.
- **CeZ, jedna osoba:** imię i nazwisko w komórce bywa rozbite na dwie linie i nie ma
  wiersza „… Suma”. Wtedy osobą jest tekst tabeli, a godzinami „Suma końcowa”.
  Tabela przestawna („Suma z Godziny”) ma wiersz osoby z sumą w tabeli szczegółów:
  od 24.11.2026 osoby są z niego, gdy suma osób to „Suma końcowa”.
- **PFRON:** „Protokół odbioru na usługi outsourcingu specjalistów IT”, blok na osobę
  „Specjalisty: Imię Nazwisko Rola” i „Liczba Roboczogodzin …: 196,5”. Miesiąca
  w treści nie ma, więc bierzemy okres z nazwy pliku albo tematu maila
  („Protokół odbioru październik 2026”). Okres zgadnięty z daty maila nie wystarcza:
  plik idzie wtedy zwykłą ścieżką.
- **MD = godziny / `fields.md_hours`** (`declared.evaluate`). Pomiar IX–X: 40 z 40
  osobo-miesięcy ma te same godziny co faktury sprzedaży Finansów w KSeF (PFRON IX:
  kwota brutto protokołu = faktura zbiorcza).

## Kiedy protokół nie daje MD

- Suma wierszy osób różna od „Suma końcowa” albo okres przez dwa miesiące: to nie
  wzór, plik czeka na człowieka.
- Okres inny niż rozliczany: kontrola `proof.month` bez MD, jak w innych czytnikach.
- Imię z protokołu inne niż w kontrakcie (IX–X: jeden protokół CeZ/177): osoba nic
  nie dostaje, chyba że wskazuje ją numer umowy, na której w miesiącu pracuje tylko
  ona (od 24.11.2026, `rozliczenia-czytniki-plikow-klientow.md`). Nie dopasowujemy po
  samym nazwisku.

## Komu trafia protokół

Ta sama ścieżka co raport zbiorczy Credit Agricole
(`rozliczenia-zip-i-raport-credit-agricole.md`): `mailbox._store_client_reports`
zapisuje ten sam plik jako raport miesiąca każdej osoby z protokołu, gdy wszystkie
znalezione osoby są u jednego klienta, a nadawca pisze z adresu firmy albo z domeny
tego klienta. Rozliczenie osoby bierze z pliku tylko jej wiersz.

**Nadawca protokołu (24.11.2026).** Protokół z adresu firmy dostaje w `cp_documents.sender_email` adres
klienta z wątku (adresat albo cytat „Od:”), gdy taki jest. Z tego korzysta ostrzeżenie faktury
`cl.client_protocol` (`zamowienia/wymagania-klientow-do-faktury-sprzedazy.md`). Protokół niesie też numer
umowy z treści (`Protocol.contract`).

## Mail koordynatora z zaakceptowanymi godzinami (`client_settlements/hours_summary.py`)

Decyzja Artura z 23.11.2026. Za CeZ/242 X podpisanego protokołu nie ma w żadnej
skrzynce (rozliczenia@, koordynatorka rozliczeń; sprawdzone 23.11). Finanse
wystawiły fakturę z maila koordynatorki do rozliczenia@ z 10.11: „Zaakceptowane
godziny przez cez: Umowa nr … - Październik 2026”, wiersz „Imię Nazwisko: 176 h”
na osobę. 6 z 6 osób i 952 h zgadzają się z fakturą. Taki mail jest dowodem godzin.

- Rozpoznanie: „zaakceptowane godziny” albo „akceptacja godzin” w temacie albo
  pierwszej linii treści i co najmniej jeden wiersz „Imię Nazwisko: N h”
  („…:176h”, punktor w osobnej linii też). Czytamy treść tylko do stopki
  („Pozdrawiam”) i cytatu („Od:”, „From:”), bo cytat ma starsze liczby.
- „czekamy”, „BRAK CZEKAMY” albo liczba w innej jednostce: osoba nie dostaje
  dokumentu i zostaje „bez raportu”, dopóki kolejny mail nie poda godzin.
- Tylko mail bez pliku z adresu firmy z tematem rozliczenia; osoby jak przy
  protokole (jeden klient, `mailbox._store_hours_summary`). Ten sam `.eml` u każdej
  osoby z liczbą godzin.
- Miesiąc z tematu („Październik 2026”), bez roku („AKCEPTACJA GODZIN CEZ WRZESIEŃ”)
  z poczty; okres zgadnięty z daty maila = mail idzie zwykłą ścieżką.
- Kilka maili za miesiąc (05.11, 09.11, 10.11): rozliczenie czyta najnowszy plik
  miesiąca, a podpisany protokół PDF wygrywa z mailem.
- Pomiar na archiwum rozliczeń@ IX–XI (2175 maili): rozpoznane dokładnie 6 maili
  koordynatorki CeZ, IX i X równe fakturom.

## Czego czytnik nie zastąpi

Protokół ani zestawienie, które nie przyszły na rozliczenia@, dalej dają „brak raportu”.
