# Blokady płatności kontraktorów: zajęcia wierzytelności, spór, biała lista w dniu paczki (23.11.2026)

Decyzja Artura z 23.11.2026: rejestr i blokady płatności kontraktorów
w NEXUSIE zamiast Excela „Kontraktorzy” i maili do głównej księgowej.
Uzupełnia „Przelewy i zapłaty (E3)” w `ksiegowosc-koszty-i-kontrahenci.md`
— tamte reguły obowiązują dalej. Migracja `0765_contractor_payment_blocks`
(`contractor_payment_blocks_schema.py`, lustro przez `hr_schema_bundle`),
reguły bez bazy `finance_ledger/garnishment_rules.py`, zapis i odczyt
`finance_ledger/contractor_blocks.py`, plan i paczka `finance_ledger/payments.py`,
trasy w `api/finance_payments.py`, ekran Finanse → Przelewy → „Zajęcia i spory”
(`ContractorBlocks.tsx`).

## Zajęcie wierzytelności (komornik, e-Urząd Skarbowy, inny organ)

- **Rejestr leży na kontrakcie** (`contractor_garnishments`): organ, sygnatura,
  data doręczenia, należność główna, koszty, odsetki, rachunek organu, uwaga,
  uchylenie (data, kto, uwaga). Dopisuje się je z wiersza faktury kontraktora
  w „Do zapłaty” (przycisk „Zajęcie”), zmienia i uchyla w „Zajęcia i spory”.
  Uchylonego nie zmieniasz; nie kasujemy żadnego (ślad).
- **Działa na wierzytelność osoby, nie jedną fakturę**: faktury przypięte do
  kontraktu (`nip_state` `known`/`confirmed`) i każda inna faktura kosztowa od
  sprzedawcy z NIP-em, który ma przypięte faktury tego kontraktu (ta sama firma
  u innego klienta, dokument wydatku). Faktury osób zespołu nie — płacą je Płace.
- **Od doręczenia do dnia uchylenia** (w dniu uchylenia już bez przelewu do
  organu); dzień liczy data wykonania paczki.
- **Podział przy paczce**: do organu idzie należność na dzień przelewu (koszty
  + odsetki + należność główna − to, co już poszło do organu z paczek, które
  nie zostały zdjęte), najwyżej cała płatność; reszta do kontraktora. Zajęcie
  większe niż płatność = całość do organu, przelewu do kontraktora nie ma
  (rachunku kontraktora wtedy nie sprawdzamy w wykazie). Kilka zajęć naraz —
  od najwcześniej doręczonego. W jednym planie kolejne faktury tego kontraktora
  liczą zajęcie po przelewach poprzednich (organ nie dostanie dwa razy tej samej
  kwoty); paczka liczy podział dla zaznaczonych faktur.
- **Odsetki**: brak / kwota z pisma (nie rośnie) / stopa roczna od dnia (odsetki
  proste, dni kalendarzowe, rok 365, od należności głównej) / nieustalone.
  Wpłata do organu zalicza się najpierw na koszty, potem odsetki, na końcu na
  należność (art. 451 KC). Przelew z paczki na późniejszy dzień odejmujemy po
  kwocie, bez odsetek.
- **Kwoty nie da się policzyć = blokada do decyzji księgowej** (`garnishment`,
  zdanie z sygnaturą i powodem): odsetki nieustalone, brak stopy albo dnia,
  brak albo zły rachunek organu, faktura nie w złotych, MPP (także podpowiedź
  MPP od 15 000 zł — księgowa oznacza „NIE MPP” albo płaci poza paczką),
  „Zapłata na konto US”, sygnatura za długa na tytuł. Nie zgadujemy kwoty.
- **Paczka**: pozycja ma `amount` = cała zapłata faktury i `garnishments`
  (przelewy do organów z rachunkiem, tytułem i sygnaturą z chwili paczki).
  Plik ma osobny przelew do każdego organu (Elixir: zwykły, CSV: „Rachunek z”
  = „zajęcie”) i przelew do kontraktora na resztę. Tytuł do organu:
  „Sygn. …”, „Zajęcie wierzytelności”, NIP dłużnika, numer faktury (NIP odpada
  pierwszy, gdy się nie mieści). Odhaczenie „część płatności idzie do organu”
  jest obowiązkowe.
- **Wyciąg**: rachunki organów z aktywnej pozycji są „znane” dla faktury,
  więc numer faktury w tytule albo para rachunek + kwota z paczki dopasowuje
  przelew do organu jako zapłatę częściową faktury. Pozycja z podziałem
  kończy się dopiero, gdy faktura jest zapłacona w całości.
- **Każda zmiana zajęcia (dopisanie, zmiana, uchylenie) zdejmuje faktury tego
  kontraktora z paczek czekających na bank** (`payments.release_entries`, jak
  „Zdejmij z paczki”; pobrany plik jest nieaktualny). Podział liczony przed
  zmianą byłby zły, a doręczone zajęcie nie może przegapić paczki, która już
  czeka. Komunikat po zapisie mówi, z których paczek zdjęto.

## Spór / wstrzymane na rozliczeniu kontraktora

- `contractor_payment_holds` na rozliczeniu (`client_settlements`, rodzaj
  `actual`, kontrakt + miesiąc): powód, kto i kiedy zdecydował; zwolnienie
  (kto, kiedy, uwaga) zostawia wiersz. Jedno aktywne wstrzymanie na rozliczenie.
- Blokuje w planie wszystkie faktury tego kontraktu za ten miesiąc (`dispute`,
  zdanie z powodem i osobą) i zdejmuje je z paczek czekających na bank.
- Faktura bez kontraktu, miesiąca albo rozliczenia w NEXUSIE = 409 z odesłaniem
  do flagi „Wstrzymać płatność” na karcie (ta zostaje do innych przypadków).

## Biała lista VAT w dniu paczki (faktury z dziennika „Kontraktorzy”)

- Plan i „Utwórz paczkę” sprawdzają rachunek w wykazie na dziś (pamięć dnia
  w `white_list`, jak dotąd). Dla faktur z dziennika „Kontraktorzy”
  (`journals.journal_of`) **rachunek spoza wykazu blokuje płatność**
  (`white_list_not_listed`, z identyfikatorem zapytania), niezależnie od kwoty;
  powrót do wykazu zwalnia ją bez niczyjej decyzji przy następnym planie.
- **Błąd wykazu (MF nie odpowiedział, limit) to nie zgoda**: blokada
  `white_list_unchecked` z kodem błędu; ponowienie po awarii idzie do MF jeszcze
  raz (błąd nie zostaje w pamięci dnia).
- Bez zmian: tryb `off`, brak NIP-u, rachunek zagraniczny, rachunek faktora
  (informacyjnie) i faktury spoza „Kontraktorów” (ostrzeżenie do odhaczenia
  powyżej 15 000 zł).

## Dostęp i ślad

- Wszystkie trasy (`/api/finance/payments/garnishments`, `/holds`) mają tę samą
  bramkę co Przelewy: sekcja Finanse + „Moduł Finanse” (`VIEW_FINANCE`, to samo
  uprawnienie, które otwiera kwoty Finansów) + moduł „Księgowość”. Bez niego 403.
- Każdy zapis idzie do Historii zdarzeń (`contract.garnishment_add/_update/_lift`,
  `settlement.payment_hold/_release`) z identyfikatorami i nazwami zmienionych
  pól — **bez kwot, sygnatur i rachunków** (log aplikacji tak samo: same id).
  Repo i logi Actions są publiczne: w testach tylko fikcyjne dane.

## Testy

`tests/test_garnishment_rules.py` (należność, odsetki, kolejność wpłat, kilka
zajęć, uchylenie, tytuł, biała lista, dopasowanie wyciągu),
`tests/test_finance_payments_contractor_blocks_db.py` (podział i wyciąg,
zajęcie większe niż płatność, kilka zajęć, uchylenie w trakcie, kwota nie do
policzenia, spór, biała lista w dniu paczki, 403 i ślad), front:
`contractor-blocks-model.test.ts`, `PaymentsTab.test.tsx`.
