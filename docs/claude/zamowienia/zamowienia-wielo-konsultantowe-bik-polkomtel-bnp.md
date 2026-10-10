# Zamówienia wielo-konsultantowe (BIK / Polkomtel / BNP) + import zużycia MD

Klienci rozliczani w T&M na MD przysyłają JEDNO zamówienie („nr 445") obejmujące
kilku konsultantów, każdego z własną stawką kosztową, przychodową i budżetem MD,
który topnieje wraz z miesięcznymi raportami z Finansów. Migracja `0227`.

- **Zamówienie wielo-konsultantowe to GRUPA nad istniejącymi `client_orders`, a nie
  „wiele osób w jednym wierszu".** Odruchowe rozwiązanie — zdjąć `NOT NULL`
  z `client_orders.contract_id` i przenieść konsultanta do tabeli linii — psuje
  siedemnaście ścieżek, bo CAŁY system czyta zamówienie przez jego kontrakt:
  `dl_portal_expiry_scanner` robi INNER JOIN po `contract_id` (zamówienie bez kontraktu
  przestaje ostrzegać na 30/14/7 dni, a `_promote_statuses` i tak przestempluje je na
  `completed` — wygasa bez ostrzeżenia), sync terminacji w `contracts.py` domyka zamówienia
  po `contract_id` (osierocone biegłyby po zakończeniu współpracy w nieskończoność),
  zgrupowana lista iteruje po `Contract.client_orders` (osierocone ZNIKA z widoku),
  a `ClientOrderRead.contract_id: int` wywala walidację przy pierwszym odczycie.
  Grupa kosztuje jedną tabelę i zero ryzyka: linia = zwykłe `ClientOrder` ze swoim
  kontraktem, więc wszystkie te ścieżki działają bez zmian. Zamówienia pozostałych
  klientów mają `order_group_id IS NULL` i nie zmienia się dla nich nic.
- **Bramka po `client_id` z ENV, nie po nazwie i nie w bundlu.** `MULTI_CONSULTANT_ORDER_CLIENT_IDS`
  (CSV, Coolify) — dopisanie klienta bez deployu. Nazwa odpada z tego samego powodu co
  przy e-Zdrowiu: Traffit nadpisuje `Client.name`, a „BNP" to RODZINA rekordów.
  **Front NIE trzyma kopii listy** (inaczej niż `lib/ezdrowie.ts`, gdzie jedno stałe ID
  jest zduplikowane po obu stronach) — lista jest zmienną środowiskową, więc kopia
  w bundlu byłaby nieaktualna od pierwszej zmiany w Coolify. Zamiast tego
  `ClientSafeResponse` wystawia wyliczone `multi_consultant_orders_enabled`.
  **Pusta lista = funkcja wyłączona dla wszystkich** (fail-closed).
- **Bramka stoi przy KAŻDEJ operacji, nie tylko przy renderowaniu.** Ukryty przycisk nie jest
  zabezpieczeniem; wywołane wprost API założyłoby zamówienie u klienta, którego zakładka
  nigdy go nie pokaże — dane nie do zobaczenia i nie do poprawienia z interfejsu.
  Wyjątek: **ODCZYT u klienta spoza listy zwraca pustą listę, nie 403** — 403 renderuje się
  jak awaria, a tutaj naprawdę nie ma czego pokazać.
- **Stawki MD mają WŁASNE kolumny** (`md_rate_cost`/`md_rate_revenue`), nie nadpisują
  `rate_client`/`Contract.rate_candidate`. Tamte są interpretowane przez `Contract.rate_unit`
  (h/dzień/mc) i zasilają marżę miesięczną w widokach jednoosobowych — wpisanie tam stawki
  dziennej dałoby cichy, 22-krotny błąd marży u trzech klientów. `_compute_monthly_margin`
  jest CELOWO nietknięte.
- **`md_remaining` jest WYLICZANE** (`md_total − Σ konsumpcji + md_manual_adjustment`),
  przeliczane od zera przy każdej zmianie. To jest mechanizm idempotencji importu, razem
  z UNIQUE `(order_id, period_month)`: powtórka miesiąca NADPISUJE wiersz konsumpcji.
  **Korekta ręczna siedzi w osobnej kolumnie**, nie nadpisuje `md_remaining` — nadpisanie
  przeżyłoby dokładnie do najbliższego importu, który przelicza pozostałość od `md_total`.
- **Pozostałość może zejść poniżej zera** — przekroczony budżet jest faktem handlowym.
  UI sygnalizuje kolorem, nic nie blokuje i nic nie ścina (także przy zamianie kontraktora).
- **Zamiana kontraktora zachowuje wartość w PLN**: `md_nowe × stawka_nowa = md_pozostałe ×
  stawka_stara`, wyłącznie od dnia zamiany w przód. Domknięcie starej linii jest lustrem
  syncu terminacji z `contracts.py`: data zawsze, status `completed` dopiero gdy dzień
  zamiany nadszedł — zamiana zaplanowana na przyszłość NIE może wyłączyć pracującego
  konsultanta. Obie stawki, obie liczby MD i data lądują w `payload` zdarzenia; bez nich
  nie da się rozliczyć faktury za miesiąc zamiany (MD sprzed zamiany idą po stawce poprzednika).
- **Precyzja:** `NUMERIC(16, 6)`. „Bez zaokrąglenia" jest nieosiągalne w typie
  stałoprzecinkowym (`kwota / stawka` bywa ułamkiem nieskończonym); sześć miejsc to cztery
  zapasu ponad prezentację (2 miejsca), więc kolejne importy nie kumulują widocznego błędu.
- **Import MD dopasowuje po imieniu i nazwisku, a numer zamówienia z „Uwag" WIĄŻE**
  (ticket 23.09.2026, BIK: stare zamówienie do 14.08, następca od 15.08, dwa wiersze
  tej samej osoby). Numer wiąże WYŁĄCZNIE względem klientów, u których ta osoba ma
  linie: znany numer zamówienia tego klienta, a u klienta z numerami z samych cyfr
  (BIK, Polkomtel) także ≥ 7 cyfr (`finance_order_matching.explicit_order_hints`,
  `OrderNumberIndex`; u Polkomtela każdy ciąg cyfr). Globalny zbiór numerów
  blokowałby BNP/CeZ („delegacja 445", NIP w uwagach).
  Wiersz z takim numerem idzie WYŁĄCZNIE na linię tej osoby w zamówieniu o tym numerze
  albo nigdzie („Brak pasującego zamówienia" + `status_reason` liczony przy odczycie,
  `_unmatched_reason` — bez kolumny w bazie). Zapis wskazany numerem
  (`apply_md_consumption(explicit_order=True)`) NIE przekierowuje na poprzednika
  i NIE przenosi nadwyżki na następcę; ręczne przypisanie wbrew numerowi = 422.
  Przekierowanie FIN-MD-01 rusza tylko przy wpisie poprzednika z INNEJ paczki — wpis
  z tej samej paczki to osobny wiersz arkusza (do 23.09 był nadpisywany).
  Zapis z numerem cofa wpis następcy za ten miesiąc, jeśli dziennik ma
  `transfer_md` z tego zamówienia, a wpis pochodzi z innej paczki
  (`_revert_earlier_transfer`) — inaczej ponowny import podzielonego miesiąca
  liczyłby MD dwa razy.
  Jedno trafienie → zastosuj; zero → „Brak aktywnego zamówienia"; **więcej niż jedno →
  „Wymaga przypisania" i system NIE zgaduje** — trafienie w złe zamówienie odejmuje MD nie
  temu klientowi i wychodzi dopiero na fakturze. Wiersz importu ŻYJE DALEJ w bazie, bo bez
  trwałego wiersza niejednoznaczność przepadłaby razem z odpowiedzią HTTP.
  Tokeny nazwiska są **zbiorem** (nie listą) — arkusze piszą raz „Jan Kowalski", raz
  „Kowalski Jan". Normalizacja z `candidate_identity_quarantine.normalize_person_name_part`.
- **Import MD po audycie 24.09.2026:** linie BIK/Polkomtela spoza okresu wchodzą do
  puli wiersza wyłącznie, gdy numer z „Uwag” jest numerem ich zamówienia
  (`_md_row_pool`). Przekroczenie puli sprawdza całą rodzinę linii zamówienia
  (następca zamiany, cel przeniesienia) i obowiązuje też w replayu Polkomtela,
  przywróceniu linii i zatwierdzaniu wspólnej puli (tam także FIN-MD-07).
  Statusy wierszy: „Bez zamówienia MD” (szary), „Rozliczono kwotowo”, „Brak
  pasującego zamówienia” tylko dla numeru, którego nie ma; liczniki nagłówka
  liczy `lib/md-import-row-tone.ts`.
- **Parser XLSX szuka nagłówka po synonimach** i przemiata wszystkie arkusze (raporty często
  zaczynają się arkuszem tytułowym). Miesiąc wybiera OPERATOR — nazwy plików kłamią dokładnie
  wtedy, gdy import dotyczy okresu zaległego. Wiersze nieczytelne trafiają do `skipped_rows`,
  nigdy nie znikają po cichu.
- **Uprawnienia — obsadę zamówienia prowadzi DELIVERY, nie tylko admin.** Stawki linii MD
  ustawia admin albo Delivery Lead **przypisany do tego klienta** (`_manages_md_lines`).
  Zakres jest wąski i trzeba go pilnować: dotyczy WYŁĄCZNIE kolumn `md_rate_*` na tej
  powierzchni — legacy `rate_client`/`rate_candidate`/`total_value` w module zamówień
  zostają **admin-only** (`_ORDER_FINANCE_WRITE_FIELDS`), a `head_of_recruitment` jest poza
  (przechodzi `DlAssignedOrAdmin` globalnie, bez przypisania, a repo konsekwentnie trzyma go
  z dala od powierzchni finansowych — patrz `/settings/clients-overview`). Rola `finance`
  też nie: jest odcinana od powierzchni kandydackich, a ta niesie nazwisko konsultanta.
  **Odczyt i zapis są wyliczane z JEDNEJ funkcji** — rozdzielenie ich dałoby rolę, która
  zapisuje stawkę i widzi w jej miejscu „—", czyli formularz bez możliwości sprawdzenia
  własnej pracy. `VIEW_FINANCE` NIE zostało dodane roli DL globalnie: to zmieniłoby eksport
  kontraktów, `/settings/clients-overview` i panel admina. **Profil klienta ORAZ portal DL
  (`/my-clients`, zakładka Analityka) są od 01.09 wyjątkiem zrobionym tą samą metodą,
  nie capability** — patrz „Delivery Lead widzi kwoty własnego portfela
  (profil klienta + Analityka)".
  Liczby MD są **operacyjne**, nie finansowe — pasek zużycia działa bez uprawnień do stawek,
  a same stawki renderują się jako „—" (znikająca kolumna czytałaby się jak brak danych, nie
  jak brak uprawnień). Import: `FinanceManageUser` (admin + Finanse) z wąską projekcją
  wierszy — bez identyfikatorów kandydatów i kontraktów.
- **Picker konsultanta pokazuje DWA źródła w jednej liście** (`ConsultantPicker`,
  `GET …/order-groups/consultant-options`): osoby z kontraktem u tego klienta
  („Rekrutacja u klienta") i pozostałych aktywnych konsultantów z bazy
  („Baza Nexus"). Wcześniej był tu `<select>` wyłącznie z kontraktami u klienta,
  więc konsultanta kończącego projekt u jednego klienta nie dało się wpisać na
  zamówienie u drugiego. Reguły, które trzymają tę listę uczciwą: dedup po
  OSOBIE, nie po kontrakcie (kto jest w źródle A, nie pojawia się w B, a osoba
  z dwoma żywymi kontraktami u tego klienta ma jeden wiersz — ten o najpóźniejszym
  starcie); „aktywny" to `active` + **`ending`** (kontrakt < 30 dni do końca to
  wciąż ktoś, kto pracuje, i najbardziej oczywisty kandydat na obsadę); sortowanie
  i wyszukiwanie idą po kluczu bez diakrytyków **w Pythonie**, bo prod nie ma
  `unaccent`; zapytanie jest AND-em po tokenach dopasowywanych PREFIKSEM, więc
  „Jan Kowalski" zwraca jedną osobę, a nie wszystkich Janów i wszystkich
  Kowalskich (równość byłaby pułapką — „Anna Kowal" w trakcie pisania nie
  zwracałoby nic, a pustka czyta się jak „nie ma jej w bazie" i kończy duplikatem).
  Odpowiedź niesie `total`, bo lista bez licznika przycięta limitem czyta się jako
  komplet. **Nazwa klienta, u którego dana osoba pracuje teraz, NIE wychodzi** —
  odbiorcą listy jest zespół jednego klienta. Harness wizualny (publiczny, same
  mocki): `/preview/order-consultant-picker`.
- **Osoba z bazy Nexus jedzie jako `candidate_id`, a serwer zakłada jej kontrakt
  w statusie `draft`.** `client_orders.contract_id` jest NOT NULL i czyta go
  kilkanaście ścieżek (skaner wygasania, sync terminacji, MRR), więc linia musi
  wisieć na kontrakcie u TEGO klienta — zdjęcie NOT NULL jest wykluczone (patrz
  wyżej). `draft`, nie `active`: aktywacja ma własny walidowany cykl życia
  (`contract_lifecycle.activate_contract`), a formularz obsady o umowie nie pyta,
  więc nie może wpychać ludzi do MRR i alertów wygasania. Kontrakt już istniejący
  jest REUŻYWANY (zero drugich, równoległych kontraktów u tego samego klienta).
  `OrderLineCreate` wymaga DOKŁADNIE JEDNEGO z pól `contract_id`/`candidate_id`:
  przy dwóch trzeba by rozstrzygać, które wygrywa, a każde rozstrzygnięcie po
  cichu wpisuje na zamówienie kogoś innego, niż widział operator. Fakt założenia
  kontraktu ląduje w historii zamówienia (`payload.contract_created`).
  **Zamiana kontraktora (`SwapConsultantModal`) świadomie ZOSTAJE przy starej,
  wąskiej liście** — ticket dotyczył dodawania do zamówienia.
- **Pułapka UI, którą złapał dopiero test w przeglądarce:** gałąź pustego stanu MUSI wisieć na
  `isSuccess`, nie na `!isLoading`. W przerwie między ponowieniami react-query ma
  `isLoading === false`, `isError === false` i puste `data`, więc warunek na `isLoading`
  przepuszczał ten stan do pustego stanu i ekran twierdził „brak zamówień", zanim cokolwiek
  było wiadomo. Dotyczy trzech miejsc: listy zamówień, historii zamówienia i historii importów.
- **Aktywacja na prodzie:** ustaw `MULTI_CONSULTANT_ORDER_CLIENT_IDS` w Coolify (ID z
  `SELECT id, name FROM clients WHERE name ILIKE '%BIK%' OR name ILIKE '%Polkomtel%' OR
  name ILIKE '%BNP%'`). Zakładka „Zamówienia” od 09.2026 renderuje ten sam widok
  (`MultiConsultantOrdersTab`) dla KAŻDEGO klienta — lista steruje już tylko
  interpretacją starych danych, nie tym, co widać (audyt 24.09.2026).
