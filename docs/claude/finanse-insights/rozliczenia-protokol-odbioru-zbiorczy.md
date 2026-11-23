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
  nie dostaje. Nie dopasowujemy po samym nazwisku.

## Komu trafia protokół

Ta sama ścieżka co raport zbiorczy Credit Agricole
(`rozliczenia-zip-i-raport-credit-agricole.md`): `mailbox._store_client_reports`
zapisuje ten sam plik jako raport miesiąca każdej osoby z protokołu, gdy wszystkie
znalezione osoby są u jednego klienta, a nadawca pisze z adresu firmy albo z domeny
tego klienta. Rozliczenie osoby bierze z pliku tylko jej wiersz.

## Czego czytnik nie zastąpi

Protokół, który nie przyszedł na rozliczenia@, dalej daje „brak raportu”. W IX–X
tak było z protokołem CeZ/242 za X (sześć osób). Koordynatorka przysłała na
rozliczenia@ tylko zestawienie „Zaakceptowane godziny przez cez” z „czekamy” przy
części osób, a Finanse wystawiły fakturę 13.11, więc protokół dotarł do kogoś
spoza tej skrzynki. Takiego zestawienia w treści maila nie czytamy jako dowodu.
