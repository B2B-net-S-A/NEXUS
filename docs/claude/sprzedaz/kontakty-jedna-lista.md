# Kontakty jako jedna lista — decyzje Artura 13.11.2026
<!-- indeks: osoby od bota Kontakty i z Cognism w zakładce Kontakty, sales_contacts z bota, bez dubli po e-mailu i nazwisku, nowsze stanowisko nadpisuje także ręczne, starsze źródło nie, źródło bez daty nic nie nadpisuje, „nie pracuje” = sales_company_contacts.is_current false, lista left w raporcie people, Cognism active, Cognism nie przywraca osoby, nawias w polu nazwiska, historia karty rodzaj contacts, contact_sync, active na mapie liczone z kontaktu, kolejka Fabryk IT bez osób, które odeszły, „Pracuje tutaj” w oknie kontaktu -->

Do 13.11.2026 osoby firmy leżały w trzech miejscach: zakładka Kontakty
(`sales_contacts`), mapa konta w lejku Fabryki IT (`decision_map` szansy) i mapa
Cognism (`sales_companies.custom_fields.bot_decision_map`). Mapy nie zakładały
kontaktów (`decision_map.fill_contact` tylko uzupełnia istniejący), więc na kopii
produkcji z 13.11 mapa pokazywała dawnego prezesa jako „Aktywna rola”, a kontakt
miał stare stanowisko albo stanowisko w polu nazwiska. Makiety: raport
https://claude.ai/artifact/2Hxqi6uLTSE4AYp1GPqtpV, sekcja „Kontakty: jedna lista”.

Kod: `backend/app/services/sales/contact_sync.py`, wywołania w
`bot_tasks/people.py` (`_sync_contacts` w biegu bota Kontakty, `_cognism_seen`
w rutynie Cognism), historia w `services/sales/bot_card_history.py`
(`contact_lines`), front `components/sales/ContactsSection.tsx`,
`ContactEditDialog.tsx`, `SalesMotionPanel.tsx`. Bez migracji.

## Reguły

- **Każda osoba, którą bot Kontakty albo rutyna Cognism zapisuje dla firmy, trafia
  do Kontaktów tej karty.** Nowy kontakt dostaje imię i nazwisko, stanowisko,
  e-mail i telefon tylko te, które przeszły filtr źródła (bot: z własnym linkiem;
  Cognism: służbowy e-mail i numer bez flagi „Do Not Call”), LinkedIn i
  `source` (`bot-kontakty` albo `cognism`). Link do źródła i data są w historii
  karty, na ekranie Kontaktów nie ma żadnych oznaczeń pochodzenia.
- **Bez dubli:** ten sam e-mail albo to samo imię i nazwisko bez względu na
  kolejność wyrazów i stanowisko w nawiasie (`contact_sync.marks`, jak
  `person_marks`). Kontakt w archiwum zostaje nietknięty i nie wraca.
- **Pola ludzi bot nadpisuje nowszą wartością** (decyzja Artura: także stanowisko
  wpisane ręcznie przez handlowca, jeśli źródło jest nowsze). „Nowsze” to data
  źródła (bot: `published`, Cognism: dzień odczytu `observed_at`) późniejsza niż
  data obecnego stanowiska: najpóźniejsza z dnia ręcznej zmiany kontaktu
  (`updated_at` w kalendarzu firmy, gdy zmiana przyszła po ostatnim zapisie
  automatu, inaczej dzień zapamiętany przy tym zapisie, `changes[].human`) i dat
  źródeł wcześniejszych zapisów automatu (`contact_sync.title_state`). Ten sam
  dzień to nie nowsze. **Źródło bez daty niczego nie nadpisuje.** Puste
  stanowisko dostaje wartość bez porównywania dat.
- Nowe stanowisko trafia do kontaktu (pole kontaktu, gdy to jego firma główna,
  i powiązanie z tą firmą) oraz do wpisu tej osoby na mapie konta w lejku
  Fabryki IT (`role_in_company`, wiersz historii szansy bez użytkownika). Mapa
  Cognism ma własną regułę: nowszy odczyt zastępuje starszy
  (`merge_cognism_people`). Stare stanowisko idzie do historii karty.
- **„Nie pracuje” to `sales_company_contacts.is_current = false`** (i `ended_at`,
  gdy źródło podaje dzień odejścia) dla tej firmy. To nie archiwum: osoba z
  historią zostaje na liście, nic się nie kasuje. Źródła odejścia: lista `left`
  w raporcie bota Kontakty i `active = false` z Cognism; obie z datą, nowszą niż
  stan „pracuje” (`contact_sync.work_state`): dzień ręcznej zmiany albo data
  opublikowanego źródła bota. **Odczyt Cognism się tu nie liczy**, bo nie dowodzi,
  że osoba dalej pracuje (przykład z kopii 13.11: Cognism z 12.11 pokazuje
  dawnego prezesa jako aktywnego, a artykuł z 7.10 mówi o zmianie od 1.10; wygrywa
  artykuł). Odejście zapowiedziane na przyszłość jeszcze się nie liczy.
- **Osoba, która odeszła, a nie ma kontaktu:** dostaje kontakt „nie pracuje” tylko,
  gdy jest na mapie konta w lejku. Nieznana osoba z listy `left` nie trafia nigdzie.
- **Powrót:** osobę „nie pracuje” przywraca człowiek („Pracuje tutaj” w oknie
  kontaktu) albo bot Kontakty z datą publikacji nowszą niż odejście. **Odczyt
  Cognism nie przywraca**, z tego samego powodu.
- **Stan na mapach liczy się z kontaktu**, nie jest kopiowany: wpis mapy konta
  dostaje przy odczycie `active = false` (`motion._mark_gone`), mapa Cognism tak
  samo (`read_cognism_map`), więc jedna zmiana w Kontaktach zmienia wszystkie
  widoki. Kolejka do pierwszego kontaktu w Fabrykach IT pomija osoby, które
  odeszły (`factories.waits_for_first_contact`). `active = false` od Cognism
  nie ukrywa już osoby na mapie Cognism (do 13.11 znikała).
- **„Imię Nazwisko (Stanowisko)” w polu nazwiska** rozdziela się przy każdym
  zapisie botów dla tej firmy, tylko gdy stanowisko było puste i przed nawiasem
  są co najmniej dwa wyrazy. Zmiana idzie do historii karty.
- **Nie dotykamy:** klienta NEXUSA (karta powiązana albo zgodna z nazwą klienta),
  naszej firmy, firmy „Nie kontaktować”, osoby ze sprzeciwem (kontakt albo zapis
  rozmowy „Nie kontaktować”, po nazwisku, e-mailu i numerze) i osoby z flagą
  Cognism „Do Not Call”. Te same odmowy co mapa i import listy.
- **Do bota dalej idą tylko nazwa i domena firmy.** Dopasowanie osób robi NEXUS.
  Logi i odpowiedź dla bota to liczby (`contact_changes`).

## Historia karty

Jeden wiersz `sales_bot_results` rodzaju `contacts` na bieg i firmę, status
`accepted`, `payload.source` (`bot` albo `cognism`), `payload.changes`: osoba
(`contact_id`, `name`), `change` (`added`, `title`, `left`, `back`, `split`),
`before`, `after`, `source_url`, `as_of`, `human` (dzień ręcznej zmiany sprzed zapisu). Zakładka Aktywności pokazuje je jako
„Kontakty (automat)” albo „Cognism (automat)” tylko kontu z „Sprzedaż: edycja”
(`GET /api/sales/companies/{id}/bot-history`). Wpisy per kontakt służą też do
liczenia dat obecnego stanu (wyżej).

## Ekran Kontakty

- Osoby „nie pracuje” na końcu listy (serwer sortuje je na koniec przy
  `company_id`, ekran też), wyszarzone, z plakietką „nie pracuje”. Bez plakietek
  „bot” i „do weryfikacji”. Każdy wiersz edytowalny jak dotąd.
- Okno kontaktu otwarte z karty firmy ma przycisk „Oznacz: nie pracuje” /
  „Pracuje tutaj” (powiązanie z firmą, `POST /api/sales/contacts/{id}/companies`
  z dotychczasową rolą i stanowiskiem). Zmiana podbija `updated_at` kontaktu,
  więc starsze źródło bota jej nie cofnie.
- Ręczna zmiana stanowiska w oknie zmienia też stanowisko przy firmie głównej
  (lista firmy czyta stanowisko z powiązania).
- Mapa konta w lejku pokazuje przy takiej osobie plakietkę „nie pracuje” zamiast
  stanowiska.

Testy: `backend/tests/test_sales_contact_sync_unit.py`,
`backend/tests/test_sales_contact_sync_api.py`,
`frontend/src/components/sales/__tests__/sales-contacts-one-list.test.tsx`.
