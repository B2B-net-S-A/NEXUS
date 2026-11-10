# Fabryki IT: lista kont mierzona kontaktem i kolejka osób — decyzje Artura 10.11.2026
<!-- indeks: lejek atlas-it-factories, lista domyślnym widokiem, „Mapa po kontakcie”, podpowiedź rozjazdu etapu z mapą, kolejka do pierwszego kontaktu (poziom 1 i 2), cudza kolejka tylko z „Sprzedaż: edycja”, liczniki „Znamy teraz” i „Kiedyś” jednym skanem, „Kto ich zna”, bez celu i rankingu -->

Etap konta w lejku „Fabryki IT” opisuje research („Mapa decyzyjna gotowa”), a nie
kontakt. Na kopii z 10.11.2026 na mapach było 122 osób, 89 bez kontaktu, a część
kont stała na etapie „Pierwszy kontakt” bez nikogo po kontakcie na mapie. Lista kont
pokazuje więc kontakt obok etapu. Rekomendacje B2 i B3 z makiet:
https://claude.ai/artifact/PEfTGijHaxrPDZS2mkxKty. To pierwszy PR pakietu „Centra IT”:
sam odczyt, bez migracji.

Kod: `backend/app/services/sales/factories.py`, `services/sales/known_counts.py`,
trasy `backend/app/api/sales_factories.py` (`/api/sales/it-factories`), front
`frontend/src/components/sales/factories/`, klient API `lib/api/sales-factories.ts`.

## Lista kont

- **Fabryki IT startują od listy, pozostałe lejki od tablicy.** Tablica zostaje pod
  przełącznikiem „Widok” (`?view=board`), bo etapy dalej się na niej przesuwa. Wybór
  inny niż domyślny dla lejka idzie do adresu, domyślny go czyści.
- **Wiersze daje `GET /api/sales/opportunities`**, więc działają wszystkie filtry
  zakładki (opiekun, szukanie, archiwum, „bez kroku”). `GET …/it-factories/accounts`
  dokłada tylko liczniki mapy po id szansy. Nie buduj drugiej listy szans.
- **„Po kontakcie”** to osoba z nazwiskiem i statusem „w toku”, „pierwszy kontakt”
  albo „stały dialog” (`CONTACTED_STATUSES`). „Bez kontaktu” i brak statusu to osoba,
  do której nikt nie dotarł. Jedna definicja dla listy, kolejki i sumy nad tabelą.
- **Podpowiedź, nie blokada.** Otwarty etap „Pierwszy kontakt” albo dalszy, przy
  zerze osób po kontakcie (także przy pustej mapie), dostaje dopisek przy etapie
  (`stage_mismatch`). `/move` niczego nie sprawdza: handlowiec poprawia status osoby
  albo etap, jak uzna. Twarde bramki etapów Artur odrzucił.
- **Klient NEXUSA** ma plakietkę i „Uzgodnij z DL: …” zamiast kroku, z tej samej
  reguły co leady i spotkania (`client_gate.match_companies`). Nasza spółka nie jest
  klientem do przekazania.
- **„Ostatni ruch” i krok** biorą się z `touch.py` i `next_step.py` przez listę szans.
  Front niczego nie liczy sam.
- Awaria liczników map zostawia wiersze z kreskami i komunikat z ponowieniem. Zero
  na liście znaczy zero, nie „nie udało się policzyć”.

## Kolejka do pierwszego kontaktu

- **Zakres:** osoby bez kontaktu z map otwartych, niezarchiwizowanych kont, których
  opiekunem jest zalogowana osoba. Poziom 1 i 2 (zarząd, dyrektorzy) to kolejka.
  Poziom 3 i 4 oraz osoby bez poziomu wracają osobno i ekran pokazuje je zwinięte;
  nic nie jest kasowane ani ukrywane na stałe.
- **Kto nie trafia do kolejki:** osoba ze sprzeciwem (flaga na wpisie mapy albo
  `do_not_contact_at` kontaktu), osoby z firmy „Nie kontaktować”, konta przegrane
  i w archiwum.
- **Kolejność:** firmy alfabetycznie, klient NEXUSA na końcu (temat prowadzi Delivery
  Lead); w firmie poziom 1 przed 2, potem osoby z kanałem kontaktu, potem nazwisko.
  Bez punktów i bez rankingu.
- **Cudza kolejka: „Sprzedaż: edycja” (więc także admin), istniejącym filtrem
  „Opiekun”.** Konto z samym podglądem widzi tylko własną, a `owner_id` innej osoby
  dostaje 403 z nazwą uprawnienia. Decyzja Artura z 10.11.2026: kolejka to narzędzie
  pracy, nie podgląd cudzej pracy. Nie dokładaj przełącznika osoby, celu dziennego,
  paska postępu ani porównania opiekunów.
- **„Zapisz kontakt”** (konto z „Sprzedaż: edycja”) otwiera `DecisionPersonDialog`
  z kluczem z mapy: to ten sam wpis co na karcie szansy, z `motion.decision_people`.
  Zmiana statusu zdejmuje osobę z kolejki. Status zmienia człowiek; samoczynne
  przesuwanie z Outlooka to osobny krok pakietu (B4).
- **Filtr „Opiekun” zna opiekunów oglądanego lejka** (`useOwnerFilterOptions(pipelineId)`
  dla lejka innego niż domyślny). Wcześniej brał osoby z lejka Sprzedaż, a opiekun kont
  Fabryk IT nie musi mieć tam żadnej szansy, więc nie dało się go wybrać.
- **Kanały są spisem, nie linkami.** Wpis na mapie nie daje prawa do zimnego kontaktu
  (art. 398 PKE), więc kolejka nie ma `tel:` ani `mailto:`. Pierwszy kontakt idzie
  przez osobę, którą znamy, albo w skali pilota 20 firm (decyzja Artura z 10.11.2026).
  Numer i adres są na karcie szansy.

## „Znamy teraz” i „Kiedyś”

- **Jeden skan na całą listę** (`known_counts.count_known_people`, trasa
  `…/it-factories/known-people`, limit 30/min). Panel na karcie liczy jedną firmę ok.
  1 s, więc wołanie go per wiersz dla 34 kont odpada. Prefiltr to ten sam jeden
  `LIKE ANY` (`_company_prefilter`) po nazwach wszystkich kart; 55 nazw na kopii
  z 10.11 to ok. 1,8 s i 3913 osób.
- **Ta sama logika co panel:** nazwy karty, klient (powiązanie ręczne, NIP, nazwa),
  jego nazwy i aliasy, nazwy dołączone na karcie, umowy „przez nas”, flagi zatrudnienia,
  a o relacji osoby decyduje `_match_experience`. `test_sales_factories.py` porównuje
  wynik z licznikami panelu dla tej samej firmy. Zmiana reguły w panelu ma zmieniać
  też listę: nie kopiuj dopasowania do `known_counts.py`.
- **Dwie różnice:** panel ucina prefiltr do 2000 osób na firmę, lista ma wspólny sufit
  20 000 (`truncated` = dolna granica, ekran to mówi). Firma bez nazwy do dopasowania
  i nasza spółka mają zera zamiast błędu.
- **Same liczby.** Lista i kolejka nie pokazują nazwisk kandydatów i nie zapisują
  odczytu w dzienniku. „Kto ich zna” to link do zakładki „Kogo znamy” na karcie firmy,
  z jej zasadami dostępu i dziennikiem. Pokazanie w Sprzedaży czegoś więcej niż
  liczników to zmiana celu przetwarzania danych kandydatów i wymaga oceny IOD.
- Liczniki mają osobne zapytanie i własny klucz pamięci podręcznej (10 minut), żeby
  lista na nie nie czekała, a skan nie ruszał po każdej poprawce osoby na mapie.

Testy: `backend/tests/test_sales_factories.py`,
`frontend/src/components/sales/__tests__/sales-factories.test.tsx`, wzorzec
`tests/data/authz_golden/sales_factories.json`.
