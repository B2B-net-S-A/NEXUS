# Mapa decyzyjna: status kontaktu z Outlooka — decyzje Artura 10.11.2026
<!-- indeks: automat statusu kontaktu osoby z mapy, mail od nas → „w toku”, mail od osoby i odbyte spotkanie → „pierwszy kontakt”, „stały dialog” tylko ręcznie, status się nie cofa, sprzeciw, ręczna zmiana ma pierwszeństwo (contact_edited_at), auto-odpowiedzi, korespondencja z kandydatem się nie liczy, przebieg po synchronizacji skrzynki, skrypt uzupełnienia wstecz, adres z mapy do pustego kontaktu -->

Status kontaktu na mapie decyzyjnej zmieniał tylko człowiek w oknie osoby i od
24.10.2026 nikt go nie ruszył, więc lista kont i kolejka Fabryk IT
(`fabryki-it-lista-kont-i-kolejka.md`) pokazywały „bez kontaktu” przy osobach,
z którymi handlowiec już pisał. Rekomendacja B4 z makiet:
https://claude.ai/artifact/PEfTGijHaxrPDZS2mkxKty. Bez migracji; na ekranach dochodzi
tylko kropka „Nowości” przy kolumnie „Mapa po kontakcie”.

Kod: `backend/app/services/sales/decision_map_outlook.py`, wywołanie w
`services/m365/sync.py` (`_sync_sales_decision_maps`), skrypt
`backend/scripts/sales_decision_map_outlook.py`.

## Które zdarzenie daje który status

- **Nasz mail do osoby → „w toku”. Mail, którego nadawcą jest osoba, albo odbyte,
  nieodwołane spotkanie → „pierwszy kontakt”. „Stały dialog” ustawia tylko człowiek,**
  bo automat nie ocenia jakości relacji. Artur wybrał ten wariant z trzech; odrzucone:
  status dopiero po odpowiedzi osoby oraz samoczynny „stały dialog”.
- **Osoba schodzi z kolejki po naszym pierwszym mailu,** bo „w toku” liczy się jako
  „po kontakcie” (`CONTACTED_STATUSES`).
- **Mail przychodzący, w którym osoba jest tylko w kopii albo nie da się ustalić
  nadawcy, daje „w toku”.** Historia z importu Atlasa ma sam kontakt, bez adresów,
  więc nie wiadomo, czy to ta osoba napisała.
- **Auto-odpowiedź, odpowiedź na zaproszenie i zwrotka nie są kontaktem**
  (`my_day.is_auto_subject`, ta sama lista co w „Mój dzień”). Na kopii z 10.11 to 193
  z 2514 maili przychodzących w Sprzedaży; bez tej reguły włączona nieobecność
  dawałaby „pierwszy kontakt”.
- **„Ostatni kontakt”** dostaje dzień najpóźniejszego zdarzenia w kalendarzu firmy
  (`business_date`), także wtedy, gdy status się nie zmienia.

## Czego automat nie rusza

- **Status nigdy się nie cofa, data idzie tylko w przód.**
- **Osoba ze sprzeciwem** (flaga na wpisie mapy albo `do_not_contact_at` kontaktu)
  zostaje nietknięta: odpowiedź „proszę nie pisać” nie może dać „pierwszego kontaktu”.
- **Ręczna zmiana ma pierwszeństwo.** Poprawka osoby, która zmienia status albo datę
  kontaktu, zapisuje na wpisie `contact_edited_at`, a automat pomija zdarzenia sprzed
  tej chwili. Handlowiec, który cofnął status, nie zobaczy go znowu po kolejnej
  synchronizacji; podniesie go dopiero nowy mail albo spotkanie. Poprawka innych pól
  (notatka, telefon) znacznika nie ustawia.
- **Szansa zamknięta albo w archiwum** i wpis bez nazwiska.
- **Korespondencja z kandydatem** (decyzja Artura 10.11.2026: „Zostaw”). Mail
  z `candidate_id` i spotkanie z kandydatem nie trafiają do Sprzedaży (reguła z 28.10,
  `outlook-handlowcow-w-sprzedazy.md`), więc statusu też nie przesuwają. Na kopii
  z 10.11 dotyczy to 7 osób z poziomu 4. Czytanie na potrzeby mapy poczty albo
  kalendarza z kandydatem to nowy przepływ danych z rekrutacji do Sprzedaży i wymaga
  oceny IOD.
- **`last_activity_at` i aktywności.** Dotyk szansy (`touch.py`) wynika z samego maila
  albo spotkania, nie ze zmiany statusu.

## Jak osoba łączy się ze zdarzeniem

- **Liczą się tylko aktywności `msgraph-mail` i `msgraph-event`** z `sales_activities`:
  synchronizacja NEXUSA i historia Outlooka z importu Atlasa. Automat nie dopasowuje
  poczty do firm sam. Mail, który nie trafił na oś firmy, statusu nie zmieni.
- **Osobę z kontaktem łączy `motion.match_contacts`,** ta sama reguła co karta szansy.
  Zdarzenie dotyczy osoby, gdy aktywność ma jej kontakt (także przy innej karcie firmy,
  bo kontakt znaleziony po id z Atlasa bywa tam) albo gdy adres z mapy lub kontaktu
  jest wśród adresów maila czy uczestników spotkania.
- **Adresy bierze z `emails` (po `internetMessageId`) i `calendar_events`
  (po `iCalUId`),** bo aktywność trzyma jeden kontakt na firmę, a mail ma często kilku
  odbiorców. `calendar_events` nie trzyma organizatora, więc spotkanie zorganizowane
  przez osobę z mapy liczy się tylko przez kontakt aktywności.

## Przebieg i zapis

- **`sync_live` biegnie po każdym przebiegu skrzynki z dostępem do Sprzedaży,**
  w osobnej, krótkiej transakcji, żeby blokada wiersza szansy nie czekała na Graph.
  Awaria idzie do logu i nie przerywa synchronizacji skrzynki.
- **Pierwszy przebieg po wdrożeniu tylko zapamiętuje chwilę startu** (`app_settings`,
  klucz `sales_decision_map_outlook_since`). Wdrożenie samo nie przepisuje map według
  historii; robi to skrypt po zgodzie Artura. Przebieg patrzy najwyżej 30 dni wstecz
  (`LIVE_LOOKBACK`), żeby zapytanie nie rosło z historią.
- **Bez kursora:** wynik zależy tylko od zdarzeń i stanu mapy, więc powtórka nic nie
  zmienia. Na kopii z 10.11 przebieg przy 31 mapach trwa 19–29 ms.
- **Zapis jak poprawka w oknie osoby:** blokada wiersza szansy, zmiana liczona od nowa
  na zablokowanej treści, `decision_map.with_entries`, jeden wiersz historii na osobę
  (`field = 'decision_map'`, bez użytkownika, z dopiskiem „z Outlooka: mail od nas”,
  „mail od osoby”, „mail przychodzący” albo „spotkanie”). Do historii idzie sam rodzaj
  zdarzenia, bez tematu i treści. Klucz osoby się zmienia, więc otwarte okno poprawki
  dostaje 409.
- **Na stagingu pętle w tle stoją,** więc krok uruchamia się ręcznie
  (`sync_mod._sync_sales_decision_maps`).

## Uzupełnienie wstecz i adresy z mapy

- **`scripts/sales_decision_map_outlook.py`** przechodzi całą historię tymi samymi
  regułami. Domyślnie na sucho (`READ ONLY`). `--apply` wymaga `--expect-people`
  i `--expect-emails` z biegu na sucho, a na produkcji dopiero po „tak” Artura.
  Raport to liczby i identyfikatory.
- **Adres wpisany tylko na mapie trafia do pustego pola kontaktu** (decyzja Artura
  10.11.2026), regułą okna osoby z 02.11 (`decision_map.fill_contact`): nie nadpisuje,
  nie zakłada kontaktów, kontakt w archiwum zostaje. Synchronizacja rozpoznaje pocztę
  po adresie kontaktu albo domenie firmy, a na kopii z 10.11 adres w kartotece miały
  23 ze 122 osób z map i 2 z 31 kont miały domenę. Uzupełnienie działa na pocztę od
  teraz; starych maili nie zapisuje ponownie.
- **Bieg na sucho na kopii z 10.11.2026:** 31 map, 122 osoby, 109 z kontaktem,
  1 zdarzenie z Outlooka przy tych firmach, 0 osób do zmiany, 38 adresów do dopisania
  (39 wpisów, jedna osoba jest na dwóch mapach).

Testy: `backend/tests/test_sales_decision_map_outlook.py`.
