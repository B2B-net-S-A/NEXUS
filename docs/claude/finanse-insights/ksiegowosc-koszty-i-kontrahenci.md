# Księgowość w Finansach: Koszty i Kontrahenci (E0, E1, 0695, 13.11.2026)

Firma wymienia eBI24 (obieg faktur) na NEXUS. Ten etap to kartoteka
kontrahentów z kontami Symfonii (E0) i jedna kolejka faktur kosztowych ze
statusami księgowymi (E1). Makiety M1, M2 i M7:
https://claude.ai/artifact/6fcZ8LYRRevuX5rJNAZ9W3. Dekret i eksport do
Symfonii (E2) ma sekcję na końcu; przelewy E3, wystawianie faktur E4 — nie dopisuj ich tu
„przy okazji”.

## Moduł „Księgowość”

- Przełącznik `app_settings['finance_accounting']` (`services/finance_ledger/settings.py`),
  domyślnie wyłączony, włącza admin (`PUT /api/finance/costs/module` albo przycisk
  na zakładce „Koszty”, który admin widzi przy wyłączonym module). Wyłączony moduł
  = 404 dla Finansów, admin widzi zawsze; wyłączony program „Ludzi w NEXUSIE”
  zamyka moduł dla wszystkich (faktury przychodzą z pętli KSeF tego programu).
- Trasy `/api/finance/costs` i `/api/finance/counterparties` (`api/finance_ledger.py`):
  sekcja Finanse, `FinanceModuleUser`, wyłącznik programu. Wzorzec bramek:
  `tests/data/authz_golden/finance_ledger.json`.
- **Moduł „Zgody” zostaje ukryty** (decyzja z 21.10.2026,
  `ludzie/zgody-wydatki-i-premie-poza-umowa.md`). Włączona „Księgowość” sprawia,
  że pobieranie z KSeF zapisuje faktury dostawców jako dokumenty wydatków także
  przy wyłączonych „Zgodach”, ale wtedy **bez dopasowania do zgód i stałych
  kosztów** (`cost_invoices.store(match=False)`): dokument zostaje `unmatched`
  z pustym `match_reason`. Przy włączonych „Zgodach” zachowanie jak dotąd.

## Kolejka kosztów (E1)

- Trzy źródła zostają, jakie są: faktury osób zespołu (`payroll_invoices`, Płace),
  faktury kontraktorów klientów (`client_contractor_invoices`, rozliczenia klientów)
  i dokumenty wydatków (`approval_documents`). Kolejka dokłada wpis
  `finance_cost_entries` z kluczem źródła (`source_type` + `source_id`, unikalne).
  Danych faktury nie kopiujemy: numer, sprzedawcę i kwoty czytamy ze źródła przy
  każdym odczycie (`costs._sources`, `UNION ALL`). Zapisujemy tylko to, co się nie
  zmienia (NIP sprzedawcy, chwila wpływu, czy z KSeF) i warstwę księgową.
- **Wpis powstaje** przy zapisie faktury w pobieraniu z KSeF (`sync._ledger_entry`
  po zapisie u Płac, kontraktora i dokumentu wydatku), na końcu każdego przebiegu
  (`_ledger_catch_up` — dołapuje też PDF-y wgrane ręcznie) i przy starcie
  (`DATA_DDL` w `finance_ledger_schema.py`, ten sam SQL co backfill migracji).
  Awaria wpisu nie cofa zapisu faktury. Wstawiamy tylko faktury bez wpisu
  (`WHERE NOT EXISTS`, żeby cogodzinny przebieg nie zjadał wartości sekwencji
  `SERIAL` na każdym wierszu źródeł); `ON CONFLICT DO NOTHING` zostaje jako
  zabezpieczenie przed wyścigiem. Istniejący wpis się nie zmienia.
- Wpisy powstają **niezależnie od przełącznika** — po włączeniu modułu kolejka ma
  pełną historię. Żeby nie zalać Finansów starymi fakturami, ekran ma filtr
  „Miesiąc wpływu”; backfill nie udaje „Zaksięgowanych” (to robi E2).
- **Etapy** jak w eBI24: `received` (Z KSeF do przyjęcia: Przyjmij / Odrzuć z
  powodem) → `new` (Do opisu) → `verified` → `ready` (Gotowe do księgowania) →
  `booked` (Zaksięgowane, ustawia E2). Odrzucić można w poczekalni i w „Do opisu”;
  „Cofnij” idzie o jeden krok, z „Odrzuconych” wraca do poczekalni (KSeF) albo do
  „Do opisu” (PDF). Dokument spoza KSeF zaczyna od „Do opisu” — poczekalnia jest
  tylko na KSeF. Zaksięgowanej nie ruszamy (etap, flagi, kategoria, termin).
- **Nikt nie zmienia etapu ani opisu własnej faktury** (faktura osoby zespołu
  z jego kontem) — 403, także zbiorczo (reszta zaznaczonych przechodzi, odmowy
  wracają w `refused`). Wszystkie odmówione = 4xx z powodem pierwszej.
- Flagi zastępują etykiety procesowe eBI24: MPP, NIE MPP (wykluczają się — CHECK
  i serwis), Wstrzymać płatność, Zapłata na konto US, Duplikat. Kategoria:
  Kontraktorzy, Zespół, Biuro, Benefity, Proforma, Inne (z KSeF: osoba zespołu =
  Zespół, kontraktor = Kontraktorzy, dokument wydatku = Biuro; Finanse zmieniają).
- Historia (`finance_cost_entry_events`): każda zmiana etapu, flag, kategorii,
  terminu i notatki z osobą i chwilą; powód odrzucenia w `detail`.
- **„Kogo dotyczy”** pokazuje to, co źródło już ustaliło, nic nie liczy od nowa:
  osoba i rozliczenie miesiąca z Płac, kontrakt i miesiąc kontraktora, zgoda na
  wydatek. Termin płatności: z rozliczenia osoby (`payroll_settlements.due_on`)
  albo wpisany ręcznie; metadane KSeF nie niosą terminu (XML kosztów nie
  pobieramy — budżet pobrań zostaje dla Płac).
- **Faktury osób zespołu widzą tylko Płace i admin** (D2,
  `ludzie/urlopy-czas-place-wejscie-odejscie.md`; ta sama bramka `is_payroll` co
  lista faktur w `api/hr_ksef.py`). Konto z samym „Modułem Finanse” nie widzi ich
  w kolejce ani w licznikach, karta i PATCH dają 404, akcja zbiorcza zwraca je
  w `refused` jako 404 (`costs._payroll_scope`). Kategoria tych faktur to
  „Zespół” (decyzja Artura z 13.11.2026).
- Start kolejki: bez daty startu — stare faktury odsiewa filtr „Miesiąc wpływu”
  (decyzja Artura z 13.11.2026).

## Kartoteka kontrahentów (E0)

- `finance_counterparties`: identyfikator (NIP, PESEL, VAT UE, inny) po
  normalizacji, unikalny razem z typem; wiersz bez identyfikatora musi mieć ID
  partnera Symfonii (też unikalne). NIP i PESEL z sumą kontrolną; „PL” + NIP
  i VAT UE z prefiksem PL to ten sam NIP (`finance_ledger/identifiers.py`).
- **Rola nie jest zapisana**, liczy się przy odczycie: klient (numer prowadzi do
  klienta przez `client_invoicing.clients.nip_registry`), osoba zespołu
  (`employee_billing_details`), kontraktor (kontrakt aktywny albo zakończony do
  92 dni — `contractor_invoices.load_index`), inaczej dostawca.
- **Import** pliku z eBI24 („Partnerzy → Pobierz”, XLSX albo CSV;
  `counterparty_import.py`): nagłówki po aliasach (bez wielkości liter, polskich
  znaków i spacji; konta i Symfonia także w środku nagłówka, wygrywa najdłuższy
  alias), wiersz nagłówka w pierwszych 10 wierszach. Najpierw podgląd (nowe,
  zmienione, bez zmian, błędy z numerem wiersza), „Zapisz” to ten sam przebieg
  z zapisem. Pusta komórka niczego nie kasuje (ręczna poprawka konta zostaje
  po ponownym imporcie pliku bez tej kolumny). Duplikat identyfikatora albo ID
  Symfonii w pliku to błąd drugiego wiersza; ID Symfonii u innego kontrahenta —
  błąd wiersza. Zły e-mail jest pomijany bez błędu.
- Po zapisie wpisy kolejki bez kontrahenta dostają go po NIP-ie sprzedawcy
  (`LINK_COUNTERPARTIES`); to samo robi przebieg KSeF i start.
- Ręcznie: ID Symfonii, konto kosztowe, konto przychodowe, e-mail
  (`PATCH /api/finance/counterparties/{id}`). Nowych kontrahentów ręcznie nie
  zakładamy (konto nadaje Symfonia, przychodzą importem).

## Ekrany

- Finanse → zakładki „Koszty” i „Kontrahenci” (przy otwartym module);
  karta faktury `/finance/costs/[id]`, okruszek „Koszty”
  (`/finance/costs` przekierowuje do zakładki).
- Podgląd jako inna osoba jest tylko do odczytu (bez zaznaczania i przycisków).

## Dekret i eksport (E2, 0698)

Finanse opisywały w eBI24 każdą fakturę dekretem do Symfonii FK i eksportowały
plikiem. Wzorce z pomiaru 13.11.2026 (1 442 dokumenty): koszt kontraktora
`402-203`, VAT naliczony `221`, rozrachunek = konto kontrahenta z kartoteki.
Makiety M2 (sekcja dekretu) i M3 (eksport): ten sam artefakt co wyżej.

- **Plan kont** (`finance_accounts`, Finanse → „Plan kont”): numer, nazwa,
  rodzaj (koszt, VAT, rozrachunek, przychód), aktywne. Zasiew tylko kontami
  wzorcowymi z pomiaru (bez kont analitycznych kontrahentów — te są
  w kartotece) i nazwami roboczymi do poprawy przez Finanse. Kont się nie
  kasuje ani nie przenumerowuje, tylko wyłącza (zasiew przy starcie dokłada
  brakujące po numerze). Konta z aktywnej reguły nie wyłączysz (409).
- **Reguły dekretu** (`finance_posting_rules`): kategoria wpisu i opcjonalnie
  kontrahent → konto kosztu, konto VAT, odliczenie (100% / brak), rejestr
  (Zakup / Sprzedaż), typ dokumentu (`FVZ`), usługa i wzór opisu (`{usługa}
  {MM}/{RRRR}`, też `{numer}`, `{kontrahent}`; inne pola = 422). Reguła
  kontrahenta wygrywa z ogólną tej samej kategorii; liczą się tylko aktywne.
  Domyślna: Kontraktorzy → 402-203, VAT 221, Zakup, FVZ, „Usługi IT”. Reguł się
  nie kasuje (wyłącza się), z tego samego powodu co kont. Konta reguły muszą
  być w planie, aktywne i właściwego rodzaju. Inne kategorie nie mają reguły
  z zasiewu — bez reguły dekret nie powstaje.
- **Dekret na wpisie** (`finance_cost_entries.decree`, JSONB, kwoty w
  groszach): Wn koszt = netto (odliczenie 100%) albo brutto (brak), Wn VAT =
  VAT (tylko przy 100% i VAT ≠ 0), Ma rozrachunek = brutto; korekta (brutto
  < 0) odwraca strony. Źródła nie niosą rozbicia na stawki — jedna pozycja na
  fakturę, stawka wyliczona z netto/VAT, gdy pasuje do 23/8/5/0. Opis bierze
  miesiąc usługi ze źródła (rozliczenie osoby, `period_month` kontraktora),
  inaczej z daty wystawienia.
- Dekret liczy się przy „Zweryfikuj”, na „Przelicz” i przy zmianie kategorii
  w „Do opisu”/„Zweryfikowane”; „Gotowa do księgowania” liczy dekret wyliczany
  od nowa, a ręczny zostawia. **Niekompletny dekret blokuje „Gotowa”** (409
  z powodem): brak reguły, sprzedawca spoza kartoteki, kontrahent bez konta
  rozrachunkowego, brak kwot, konto spoza planu, bilans Wn ≠ Ma, brak kursu NBP,
  kwoty źródła zmienione po dekrecie.
- **Waluta obca** (decyzja Artura 13.11.2026, ta sama zasada co w E4): dekret
  w PLN po kursie NBP z **dokładnie ostatniego dnia roboczego przed datą
  wystawienia** (`posting.rate_day`, kalendarz `core/scheduling.is_business_day`,
  kurs z tabeli `fx_rates`, bez wywołań sieci i bez szukania starszego kursu).
  Brutto i VAT × kurs (w groszach), netto jako różnica — dekret się bilansuje.
  Brak kursu z tego dnia = wada „Brak kursu NBP {waluta} z dnia DD.MM.RRRR”
  (blokuje „Gotowa”); brak daty wystawienia — też wada. Dekret pamięta walutę,
  kurs i dzień kursu (`fx_rate`, `fx_date`), karta je pokazuje; ręczna korekta
  je zachowuje.
- **Kwoty źródła zmienione po dekrecie**: źródło potrafi zmienić kwoty już po
  dekrecie (PDF dostaje bliźniaka z KSeF, `hr/ksef/sync._bind_twin`). Suma
  pozycji rozrachunku ≠ `abs(brutto)` źródła (dla waluty × kurs z dekretu) =
  wada „Kwoty faktury zmieniły się po dekrecie — Cofnij i przelicz”
  (`posting.amount_issue`): w „Gotowa”, na karcie, na liście miesiąca (wpis poza
  paczką) i przy „Oznacz jako zaksięgowane” — paczka z takim wpisem dostaje 409
  (plik jest nieaktualny: anuluj paczkę, Cofnij, przelicz). Ręczny dekret waluty
  obcej bez kursu nie ma z czym porównać — przechodzi.
- **Kategorii nie zmienia się po „Gotowa” ani w paczce** (409 „najpierw Cofnij
  / anuluj paczkę”, lista na karcie zablokowana): kategoria wybiera regułę,
  a po „Gotowa” dekret się już nie przelicza — zostałby stary.
- Ręczna korekta (`PUT …/entries/{id}/decree`) tylko w „Do opisu”
  i „Zweryfikowane”; Wn ≠ Ma albo konto kosztu/VAT spoza planu = 422. Po
  „Gotowa” dekret zmienia się po „Cofnij”, po zaksięgowaniu wcale. Historia
  wpisu: `decree`, `export`, `unexport`, `book`.
- **Eksport miesiąca** (Finanse → „Księgowanie”, `posting_export.py`): miesiąc
  wpływu (jak filtr kolejki), wpisy „Gotowe” spoza paczek per rejestr z sumami
  Wn/Ma i kontrolą (sumy rejestru liczą tylko faktury bez wady). „Pobierz plik”
  zakłada **paczkę** (`finance_posting_batches`: numer `RRRR-MM/n`, kto i kiedy,
  lista wpisów, bajty pliku i SHA-256) — ponowne pobranie paczki oddaje zapisane
  bajty, więc ten sam plik. **Faktury z wadą dekretu paczka pomija** (decyzja
  Artura 13.11.2026): zostają „Gotowe”, ekran „Księgowanie” pokazuje je z
  powodami („Pominięte w paczce”, też w odpowiedzi `POST /batches` jako
  `skipped`), po poprawce wchodzą do następnej paczki. Same wadliwe = paczka nie
  powstaje (409). Lista pominiętych trzyma D2 (osoba bez Płac nie widzi faktur
  zespołu). Miesiąc eksportu zostaje miesiącem wpływu (decyzja Artura 13.11.2026).
  Wpisu w paczce nie cofa się (najpierw
  „Anuluj paczkę”, wpisy wracają na listę jako „Gotowe”). „Oznacz jako
  zaksięgowane” przestawia wpisy paczki na `booked`.
- **Format pliku**: formatu importu Symfonii FK nie znamy (czekamy na próbkę od
  Finansów). Są dwa neutralne (`export_formats.py`): XLSX i CSV (średnik, BOM,
  przecinek dziesiętny), wiersz na pozycję dekretu: rejestr, typ, numer
  faktury, numer KSeF, daty wystawienia i wpływu, kontrahent, NIP, ID Symfonii,
  konto, Wn, Ma, opis, stawka, odliczenie. Format Symfonii = jedna klasa
  z `key`, `label`, `extension`, `media_type`, `render(rows)` i wpis
  w `FORMATS`. Tekst idzie przez `safe_cell`.
- **D2 także tu**: osoba bez Płac nie widzi faktur osób zespołu w dekrecie,
  liście miesiąca ani paczce (paczka z taką fakturą: `has_payroll`, dla niej
  404 i brak na liście). Paczka założona przez nią ich nie zawiera — zostają
  dla Płac.
- Trasy `/api/finance/posting/*` (`api/finance_posting.py`): sekcja Finanse,
  `FinanceModuleUser`, moduł „Księgowość”, wyłącznik programu; plan kont
  i reguły zmienia „Moduł Finanse”. Wzorzec: `tests/data/authz_golden/finance_posting.json`.
- Ekrany: sekcja „Dekret do Symfonii FK” na karcie faktury, zakładki
  „Księgowanie” i „Plan kont” (przy otwartym module). Bez `data-help`
  (przewodnik „finance” ma komplet kotwic).

## Przelewy i zapłaty (E3, 0699)

Zastępuje w eBI24 eksport przelewów faktur kosztowych do banku i „Importuj →
Wyciągi bankowe → Oznacz faktury jako zapłacone”. Makieta M6 (ten sam artefakt).
Serwis `services/finance_ledger/payments.py`, reguły bez bazy
`payment_rules.py`, stan w kolejce `payment_state.py`; trasy
`/api/finance/payments` (`api/finance_payments.py`) z tymi samymi bramkami co
„Koszty” (sekcja Finanse, `FinanceModuleUser`, moduł „Księgowość”; wzorzec
`tests/data/authz_golden/finance_payments.json`). Zakładka Finanse → „Przelewy”.

- **Warstwa płatności leży obok kolejki**, nie w niej: `finance_cost_payments`
  (1:1 z wpisem, powstaje przy pierwszej zmianie; brak wiersza = „Do zapłaty”),
  `finance_counterparty_accounts`, `finance_payment_batches`,
  `finance_payment_batch_items`, `finance_cost_payment_records`. Stany:
  `unpaid / in_batch / paid / partially_paid`; źródło zapłaty: wyciąg, ręcznie,
  inna ścieżka NEXUSA (Płace). Kolejka ma kolumnę i filtr „Zapłata”, karta —
  panel „Płatność”.
- **Nie dublujemy przelewu.** Faktury osób zespołu płacą Płace (rozliczenie
  miesiąca, „Dla Finansów”, paczka Płac — `ludzie/urlopy-czas-place-wejscie-odejscie.md`).
  W planie paczki są tylko dla Płac i admina (D2) i zawsze zablokowane („zapłatę
  prowadzą Płace”); stan w kolejce czytamy z `payroll_settlements` (opłacone
  = „Zapłacona”, w paczce Płac = „W paczce”); „Opłacono” i rachunek na karcie
  takiej faktury = 409. Obciążenia z wyciągu, które rozpoznaje ścieżka Płac
  (`statements.decide`) albo które Płace już zapisały z tego pliku, zostają
  tamtej ścieżce (licznik „zespół (Płace)”). Faktury kontraktorów klientów
  i dokumenty wydatków nie mają w NEXUSIE innej ścieżki zapłaty — płacimy je tu.
  Decyzja Artura z 13.11.2026: faktury osób zespołu nigdy nie wchodzą do paczki
  kosztów, a do planu trafiają tylko faktury z terminem ≤ wybranej daty.
- **Bramka zapłaty z rozliczeń klientów** (`pay.after_client_signature`,
  `client_settlements/service.payment`, decyzja z 13.11.2026): faktura
  kontraktora klienta → rozliczenie osoby za miesiąc faktury (kontrakt +
  `period_month`, rodzaj `actual`) → reguły klienta na ten miesiąc
  (`payments._client_gates`). `can_pay: False` przy poziomie `block` (stan
  `fail`) = wiersz zablokowany z tytułem reguły („Zapłata czeka na podpis
  klienta na KEŚU”), nie wejdzie do paczki; przy poziomie `warn` = ostrzeżenie
  do świadomego odhaczenia (jak biała lista). KEŚU podpisane albo zapłata po
  mailowej akceptacji (`pay_on_mail`) = bez ograniczeń; reguła wyłączona, brak
  KEŚU, kontraktu, miesiąca albo rozliczenia (`payment` zwraca `None`) — też.
- **Rachunek odbiorcy**: wpisany na karcie > z faktury w KSeF (kontraktorzy
  klientów: `Platnosc/RachunekBankowy/NrRB` zapisywane od E3 w `details.accounts`
  przy pobraniu XML-a; dokumenty wydatków XML-a nie mają) > z kartoteki
  (zapamiętany przy ręcznym wpisie, „zapamiętaj w kartotece”). Krajowy = 26
  cyfr NRB z sumą kontrolną, zagraniczny = IBAN z sumą kontrolną. Rachunki
  kontrahentów pokazujemy w całości (Finanse muszą je sprawdzić; firmowe są
  jawne w wykazie VAT) — rachunki osób zespołu nie trafiają tu wcale.
  Rachunek faktury w aktywnej paczce się nie zmienia (409 — anuluj paczkę).
- **Plan paczki** („Do zapłaty z terminem do”): tylko faktury z terminem ≤ daty.
  Bez terminu faktura nie trafia do planu — historia sprzed NEXUSA była płacona
  w eBI24, a KSeF nie niesie terminu (wpisują go Finanse na karcie). Blokady:
  poczekalnia/odrzucona, „Wstrzymać płatność”, „Duplikat”, zapłacona, w innej
  paczce, brak kwoty, brak albo zły rachunek, przelew w złotych na rachunek
  zagraniczny, „Zapłata na konto US” bez ręcznego rachunku, tytuł (niżej).
- **Tryb**: „Zapłata na konto US” = przelew na rachunek urzędu (tylko ręczny
  rachunek, bez białej listy; formatu przelewu podatkowego `/TI/…` nie
  składamy), „MPP” = podzielona płatność, „NIE MPP” = zwykły; bez flag — MPP,
  gdy faktura w złotych ma ≥ 15 000 zł brutto, jako **wskazówka do potwierdzenia**
  (ostrzeżenie do odhaczenia przy paczce). MPP tylko w złotych. Art. 105a: od
  dostawcy w miesiącu wystawienia > 50 000 zł netto, a faktura < 15 000 zł
  brutto bez MPP — podpowiedź „rozważ MPP” (PKWiU nie znamy — XML-a kosztów
  nie pobieramy).
- **Tytuł**: numer faktury i numer KSeF w osobnych liniach (4 × 35 znaków,
  numer KSeF nie jest cięty). Od 1.01.2027 (`business_today()`, data
  wstrzykiwana w testach) faktura z KSeF bez numeru KSeF jest zablokowana; PDF
  spoza KSeF przechodzi. MPP: `/VAT/{vat z przecinkiem}/IDC/{NIP sprzedawcy}/INV/{numer}/TXT/{numer KSeF albo numer faktury}`.
- **Biała lista**: `white_list.check` na dzień paczki dla rachunku krajowego
  z NIP-em; wynik i `requestId` przy wierszu i w pozycji paczki. Tryb `off` =
  „Nie sprawdzono (sprawdzanie wyłączone)”, awaria = „niesprawdzony” — nigdy
  „brak w wykazie”. Faktura > 15 000 zł brutto z rachunkiem innym niż
  „w wykazie” (także niesprawdzonym) = ostrzeżenie blokujące do świadomego
  odhaczenia (kto — `acknowledged_by`).
- **Paczka**: jedna waluta; w złotych Elixir-O (`hr/bank/elixir.py`, pole 15
  klasyfikacji: 51 zwykły, 53 MPP) albo CSV, w walucie obcej tylko CSV (IBAN).
  Elixir wymaga rachunku nadawcy (`app_settings['finance_payments']`, „Rachunek
  nadawcy” na zakładce). **Układ pliku Elixir-O i komunikatu MPP trzeba
  sprawdzić w bankowości firmowej przed pierwszą paczką** (import próbny).
  CSV przez `safe_row` (bez formuł). Dwie równoległe „Utwórz paczkę”: blokada
  doradcza `finance-cost-batch` i indeks częściowy
  `uq_finance_payment_batch_items_active` — druga dostaje 409 „w paczce”.
  Paczka ustawia wpisom `in_batch`; „Anuluj” zwalnia pozycje, które nie są
  jeszcze zapłacone. Plik powstaje z pozycji (rachunek i tytuł z chwili paczki).
- **Wyciąg** (Finanse → Przelewy → „Wgraj wyciąg”, MT940/CAMT.053 przez
  `statements.parse_file`, ta sama blokada pliku co Płace i faktury do
  klientów): tylko obciążenia. Dopasowanie: numer KSeF w tytule; potem numer
  faktury całym słowem albo `/INV/` (numery powtarzają się u dostawców —
  rozstrzyga rachunek odbiorcy, bez niego kwota równa pozostałej); potem
  pozycja aktywnej paczki (ten sam rachunek i kwota). Kwota równa pozostałej =
  zapłacona (MPP: kwota + VAT z `/VAT/` w tytule); mniejsza przy wskazanej
  fakturze = częściowa (po samym numerze faktury tylko z potwierdzonym
  rachunkiem); większa, faktura zapłacona, kilka pasujących = „do sprawdzenia”
  z podpowiedziami („Przypisz” / „Pomiń” z powodem). Ten sam plik drugi raz nic
  nie dopisuje; ta sama operacja z innego pliku = pominięta z powodem.
- **Ręczne „Opłacono”** na karcie: kwota (domyślnie całość pozostałej, nie
  więcej), data nie z przyszłości, powód (np. „karta firmowa” — 135 faktur
  w eBI24 płaconych kartą).
- **Paczka czekająca na bank jest zamrożona** (przegląd 13.11.2026). Dopóki
  faktura ma aktywną pozycję paczki: ręczne „Opłacono” (pełne i częściowe),
  „Przypisz” operacji z wyciągu, zmiana rachunku i dodanie albo zdjęcie flagi
  płatności (MPP, NIE MPP, „Wstrzymać płatność”, „Zapłata na konto US”) = 409
  „Faktura jest w paczce czekającej na bank — anuluj paczkę albo zdejmij z niej
  fakturę”. „Zdejmij z paczki” (Przelewy → Paczki → Pozycje) zwalnia jedną
  pozycję i oznacza paczkę jako zmienioną. Zapłata z wyciągu (bank wykonał
  przelew) zamyka pozycję normalnie. Plik zawiera **wyłącznie pozycje
  czekające** (`active`) — zapłaconej ani zdjętej do pliku nie dokładamy;
  przy pobraniu zapisujemy skrót pliku, nazwa pliku niesie jego początek,
  a pobranie po zmianie składu daje `X-Batch-File-Changed: true` i na liście
  „Plik nieaktualny — pobierz ponownie” (stary plik trzeba usunąć z banku).
  „Utwórz paczkę”, „Opłacono”, „Przypisz”, wyciąg, „Zdejmij”, rachunek i flagi
  płatności biorą tę samą blokadę doradczą `finance-cost-batch`.
- **Zaksięgowana faktura**: flagi płatności i termin płatności nie zmieniają
  dekretu — wolno je zmienić także przy `booked` (z wpisem w historii);
  kategoria i „Duplikat” zostają zamknięte. Faktura z „Wstrzymać płatność” nie
  pojawia się w planie (wraca po zdjęciu flagi).
- **Rachunek wpisany ręcznie ma ślad**: zmiana na karcie zapisuje zdarzenie
  `account` w historii wpisu (stary → nowy rachunek, źródło, kto, kiedy;
  CHECK akcji poszerza migracja E3), a „zapamiętaj w kartotece” jest domyślnie
  **wyłączone**; zapamiętanie zapisuje `finance_counterparty_account_events`
  (stara i nowa wartość, kto, kiedy). Plan i karta mówią „Rachunek zmieniony
  ręcznie przez X dnia D”. Rachunek wpisany ręcznie (na karcie albo
  w kartotece) i niepotwierdzony w wykazie VAT wymaga świadomego odhaczenia
  **niezależnie od kwoty** (tryb `off` też — odhaczenie zamiast sprawdzenia).
- **Faktoring**: rachunek faktora z XML-a (`Platnosc/RachunekBankowyFaktora`,
  `details.factor_accounts`) ma pierwszeństwo przed rachunkiem sprzedawcy
  (ręczny wpis dalej wygrywa); źródło `ksef_factor`, w planie „faktor”,
  w pliku nazwa odbiorcy z dopiskiem „(rachunek faktora)” i w CSV kolumna
  „Rachunek z” = „faktor”. Biała lista sprawdza rachunek faktora z NIP-em
  sprzedawcy **informacyjnie** — faktor nie musi być w wykazie dla NIP-u
  sprzedawcy, więc wynik nie wymaga odhaczenia (art. 117ba nie zwalnia wtedy
  z ryzyka — decyzja Finansów przy umowie faktoringu).
- **Korekty**: do zapłaty faktury pierwotnej kontraktora = brutto pierwotnej +
  brutto jej korekt (łańcuch `client_settlements.invoice_chain`: numer KSeF
  faktury korygowanej, a bez niego numer faktury; VAT dla MPP też po
  korektach), z dopiskiem „Pomniejszona o korektę …”. Korekta znanej faktury
  nie jest osobnym wierszem do zapłaty (blokada „rozliczona na fakturze
  pierwotnej”, dzieli z nią stan zapłaty); korekta albo kwota ujemna bez znanej
  pierwotnej = blokada „bez znanej faktury pierwotnej”; łańcuch do zera albo
  poniżej = „nie ma czego płacić”. Dokumenty wydatków nie mają łańcucha —
  kwota ujemna to zawsze „bez znanej pierwotnej”.
- **Czego jeszcze nie ma**: zapłat oznaczonych w eBI24 (wpisy z backfillu są
  „Do zapłaty”, dopóki ktoś ich nie oznaczy — do planu nie wchodzą, bo nie mają
  terminu) i „Bank wykonał” dla całej paczki (zapłatę stwierdza wyciąg albo
  „Opłacono”).
