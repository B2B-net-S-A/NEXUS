# Umówiony telefon na screening (03.11.2026)
<!-- indeks: `services/screening_calls.py`, wydarzenie `screening` z miejscem „Telefon”, blokada do terminu + 30 min, Outlook bez zaproszenia, sprzątanie w pętli przypomnień -->

Pomysł rekrutera z czatu i decyzja Artura z 03.11.2026: wariant A, blokada do
godziny rozmowy + 30 min, wpis w Outlooku bez zaproszenia. Makiety:
https://claude.ai/artifact/8GhHfMcbqVmst9qDLWUyKb. Pomiar na kopii produkcji:
36 notatek „oddzwonić / kontakt po 16” w 60 dni, 6 z 23 bez śladu pracy przez
ponad 7 dni, a typ `screening` miał 0 wydarzeń w 120 dni.

## Reguły

- **Termin to zwykłe wydarzenie `screening` z miejscem „Telefon”**
  (`BOOKED_CALL_LOCATION`, `is_booked_call`), bez migracji i nowej wartości
  enuma. Przypomnienie, Tydzień, zastępstwa i anonimizacja przy usunięciu
  kandydata działają jak przy każdym wydarzeniu. Nie zmieniaj tego miejsca
  z formularza: po nim poznajemy telefon.
- **Umawiać można tylko w „Nowych” i „Screeningu”** w otwartym procesie otwartej
  rekrutacji. Jedna para ma najwyżej jeden otwarty termin (409, „Przełóż”).
  Termin najdalej za 60 dni.
- **Termin trzyma osobę do startu + 30 min, najwyżej 7 dni i nigdy krócej niż
  12 h** (`hold_until`). Cudzej aktywnej blokady nie przejmuje: rekruter dostaje
  423, a DL, HoR i admin 409 z prośbą o „Przejmij”, bo tam jest dzwonek do
  poprzedniej osoby. Na osobie od systemu umówienie jest decyzją „Dzwonię”
  (`record_call`). Odwołanie albo zapis screeningu skraca blokadę do 12 h od tej
  chwili (`release_hold`), bo bez terminu nie ma powodu trzymać osoby dłużej.
- **„Biorę” i „Przejmij” zabierają telefon** (`follow_claim`, założenie do
  potwierdzenia przez Artura): nowy prowadzący ma przypomnienie, listę i „Przełóż”.
  Blokada w Outlooku poprzedniej osoby znika, a nowa nie powstaje, bo ta trasa
  nie woła Grapha.
- **Edycja w kalendarzu nie rusza znacznika ani Outlooka** (`update_event`): typ,
  miejsce, kandydat i rekrutacja dają 409, a do Outlooka idzie tylko termin.
  Zmiana terminu przesuwa blokadę osoby.
- **Zapis screeningu kończy termin od razu** (`screening_form.save`). Ruch karty
  i zamknięcie rekrutacji łapie `reconcile` w pętli przypomnień, co minutę:
  karta rusza się kilkunastoma ścieżkami i nie dokładamy haka do każdej.
  `reconcile` to sama baza i biegnie przed skanem przypomnień. `clean_outlook`
  biegnie po nich, z limitem 30 s i 20 wpisów, bo wywołanie Grapha trwa do 120 s.
  Staging ma tę pętlę zatrzymaną, więc tam termin po ruchu karty zostaje otwarty.
- **Outlook jest dodatkiem i idzie po commicie** (`add_to_outlook`,
  `move_in_outlook`), bo `GraphClient` zatwierdza sesję przy odświeżeniu tokenu.
  Termin w NEXUSIE zapisuje się zawsze, a odpowiedź mówi, co z Outlookiem
  (`added`, `updated`, `not_connected`, `failed`). Nie używaj `m365-invite`: dla
  typu `screening` zaprasza kandydata i dodaje Teams.
- **W Outlooku jest tytuł „Telefon: Anna N.” i link do panelu**, bo ten wpis żyje
  poza NEXUSEM. Pełne nazwisko i słowa kandydata zostają w NEXUSIE. Synchronizacja
  nie nadpisuje tego wydarzenia, a usunięta blokada nie odwołuje telefonu
  (`nexus_interview` w `m365/sync.py`). Blokadę zdejmuje `clean_outlook`, tylko
  przyszłą; dotyczy to też usunięcia kandydata (`erase_candidate_meetings`).
- **Follow-up liczy telefon jako kontakt dopiero po zamknięciu**
  (`candidate_followups._last_contacts`). Minięty termin bez wyniku schowałby
  follow-up na 14 dni.
- **Przypomnienie prowadzi do panelu osoby i ma dymek** (`force_toast` w ramce
  gniazda). Reszta tematu „Kalendarz” dalej tylko podbija licznik. Kategoria
  „Rozmowy” jest obowiązkowa, więc nie da się tego wyciszyć.
- **Bez zmian:** KPI i liga, oznaczenie „po terminie” w kolumnie, reguła kolejki
  w „Nowych” i licznik rekrutacji bez ruchu. „Do przedzwonienia”
  (`CANDIDATE_CONTACT_ENABLED`) jest wyłączone i z tego nie korzysta, ale jego
  haki też patrzą na typ `screening`: przy włączeniu sprawdź oba mechanizmy razem.
