# Polityki odczytu PDF per klient — jeden wzorzec, bramka per klient

Każda polityka jest DETERMINISTYCZNA i stosowana PO odpowiedzi LLM (model
wybiera interpretację, nie stosuje reguł), bramkowana CSV `client_id` z env,
fail-closed:

| Klient | Env | Reguła |
|---|---|---|
| Nordea | `NORDEA_ORDER_NUMBER_CLIENT_IDS` | numer tylko z „Call Off Agreement number”; zawsze netto/h bez ÷1,23; Quantity/MD ignorowane; summary pomijane przed modelem i planem |
| Bank Pocztowy | `BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS` | numer pisma; netto MD ÷ 8 (w górę) |
| Credit Agricole | `CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS` | stawka tylko z „Wynagrodzenie za 1MD (8h)”, MD tylko z „Szacowana ilość MD” |
| BNP | `BNP_ORDER_EXTRACTION_CLIENT_IDS` | dokument JEDNOOSOBOWY; „Cena netto” → stawka za 1 MD, „Szt.” → liczba MD, „MM-RRRR do MM-RRRR” → pierwszy/ostatni dzień miesiąca |
| Erste Bank Polska | `ERSTE_GROSS_RATE_CLIENT_IDS` | brutto ÷ 1,23 → netto (half-up, 2 miejsca) |
| Orlen | `ORLEN_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 35) | wspólna stawka on/off-site tej samej osoby; MD z PDF zawsze pomijane |
| PFRON | `PFRON_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 122) | okres wyłącznie z jawnej daty końca usług; brutto → netto |
| BIK | `BIK_ORDER_CLIENT_IDS` (+ kanoniczne ID 18) | numer/data z „Numer/data zamówienia” (start = data, koniec = bezterminowo); każda „Poz.” = osoba z własnym limitem MD („Ilość zamów.”, SZT) i stawką PLN/MD („Cena jednostk.”); wartości netto tylko do kontroli |
| Polkomtel | `POLKOMTEL_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 15) | „Zlecenie wykonawcze": numer = skrót + numer po „nr" do ukośnika („SAP 4500123456"); start z „zawarte w dniu …", koniec zawsze bezterminowo; reguły działają WYŁĄCZNIE na dokumencie z nagłówkiem „ZLECENIE WYKONAWCZE nr" (inny szablon = odczyt ogólny + uwaga); tabela „Cena netto 1MD po upuście \| Cena total \| Konsultant" czytana jako STRUMIEŃ KOMÓREK (PDF: wiersz w linii, komórka scalona osobno; DOCX: komórka = linia, scalona powtórzona), kolejność kolumn z nagłówka (kotwicą „Cena netto", nagłówek osoby = całe słowo „Konsultant"); dwie kwoty w wierszu = stawka + kwota osoby TYLKO z dowodem (każdy wiersz ma parę, kwota osoby > stawki, suma = „na kwotę"), inaczej wiersz niepewny — nigdy zgadywanie; odczyt modelu jest drugim, niezależnym czytelnikiem (inna stawka tej osoby albo osoba spoza tabeli → do sprawdzenia); stawka zawsze netto za MD; „na kwotę …"/„Cena total" = kwota CAŁEGO zlecenia; MD: kolumna przy osobie albo jedna liczba („pracochłonność … MD"); brak MD w kosztowym = poprawny odczyt; `closes_on_md_exhaustion`; przywracanie stawki sprzed ÷1,23 tylko w „Zleceniu wykonawczym nr” (inny dokument → ogólne rozpoznanie brutto/netto) |
| Cyfrowy Polsat | `CYFROWY_POLSAT_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 38339) | wyłącznie numer tą samą regułą („CP 1234"); okres i stawki — odczyt ogólny (CP ma też zamówienia okresowe) |
| Alior | `ALIOR_ORDER_EXTRACTION_CLIENT_IDS` | tylko 4 pola: „Zamówienie nr:”, nazwisko z kolumny konsultanta, okres z nawiasu pod nazwiskiem (inaczej „Moment wejścia w życie” / „czas oznaczony”), stawka z „Razem stawka dla Banku” za MD; zawsze netto, jawne „brutto” w tabeli → weryfikacja bez ÷1,23; Roboczodni/Stawka bazowa/Marża/Total ignorowane |
| PKO BP | `PKO_BP_ORDER_EXTRACTION_CLIENT_IDS` | numer z „Zamówienie nr”; tabela Wykonawców czytana z POŁOŻENIA słów (`pko_bp_layout`, ticket 12, 01.10.2026): kolumny z nagłówków, wiersze z dat „Początek Zaangażowania”, komórki wielolinijkowe przypisywane DP; `prepare_document_text(..., words=doc.words)` DOPISUJE do tekstu „Wykonawca N \| kolumna: wartość” (surowa tabela zostaje), które czyta reguła, bramka i „Przelicz plan”, a `prepare_parser_text` zdejmuje dopisek — model czyta surową tabelę sam (niezależny czytelnik, #1494; podmiana tabeli gubiła wiersz pominięty przez oba odczyty) (słowa liczy `extract_order_words` tylko przy „SSGW” w tekście); bez słów (DOCX, skan) albo gdy układ daje mniej wierszy niż tekst — stara reguła: profil odcinany słownikiem (granica niepewna = wiersz do sprawdzenia; nazwisko sklejone w odczycie modelu/zapisanym prostowane do tabeli, także słowami kolumny „Profil”, przy „Przelicz plan”, `reapply_on_refresh`); okres z „Początek/Planowany Koniec Zaangażowania”; stawka z „Stawka PLN/MD netto” zawsze netto (bez ÷1,23 i bez pytania brutto/netto; „brutto” łącznej wartości nie ma wpływu), jawne „PLN/MD brutto” w nagłówku → weryfikacja; gwiazdka „stawka negocjowana” pomijana |

- **„Przelicz plan” podaje regule `reapplied=True` tylko wtedy, gdy reguła już
  działała na zapisanym odczycie** (`not policies_pending`) — dokument Nordei
  rozpoznany dopiero przy ponownej weryfikacji nie dostaje trwałego powodu
  „odczyt sprzed zmiany reguły”. Ręczne „Zastosuj” odmawia wiersza ze stawką
  bez jednostki (audyt 24.09.2026).
- **PFRON: jawne „netto” przy stawce wygrywa z regułą brutto** (decyzja Artura
  26.09.2026, runda 6 audytu). `pfron_extract_rows` czyta oznaczenie przy
  stawce (etykieta, nawias, słowo za kwotą — `_pfron_rate_marking`): samo
  „netto” = kwota bez ÷ 1,23; brak oznaczenia albo „brutto” = ÷ 1,23 jak
  dotąd; oba słowa naraz = ÷ 1,23, ale wiersz niepewny („Sprzeczne
  oznaczenie stawki…”), więc dokument idzie do człowieka. `rule_version`
  PFRON = „2026-09-26”.
- **„Brak liczby MD" nie jest zastrzeżeniem ODCZYTU — o wymaganych polach decyduje
  typ zamówienia** (ticket Polkomtel 09.2026). Model czyta PDF bez wiedzy o typie
  i przy zamówieniu kosztowym zgłaszał „brak informacji o liczbie MD". Trzy warstwy:
  prompt v6 („MISSING MAN-DAYS" — brak MD nie jest niepewnością i nie zeruje stawki
  wiersza); `drop_md_absence_reasons` w obu endpointach formularzy (formularz sam wie,
  czy dla typu i wariantu MD czegoś brakuje; `md_scope` = `per_consultant` / `order`
  ustawia „Budżet MD na całe zamówienie"); bramka poczty zdejmuje takie powody tylko
  gdy są nieistotne dla typu, a MD bez liczby w ŻADNYM wariancie oraz wspólna pula
  przy kilku osobach idą do kolejki (automat nie dzieli puli). `is_md_absence_reason`
  NIGDY nie łapie powodu, który mówi też o stawce, kwocie, dacie, numerze, nazwisku
  albo sprzeczności.
- **BIK: tekst z SAP-a jest SKLEJONY** — pdfplumber oddaje
  „ProfilUR-JanKowalski”, „4500012345/20260903”, a etykieta „Numer/data”
  stoi linię nad adresem, nie nad wartością. Nazwisko jest kotwiczone na linii
  „Profil”, z myślnikiem albo bez (`_split_glued` rozcina granice mała→wielka
  litera); istniejąca linia „Profil” jest WIĄŻĄCA — nieczytelna nie przełącza
  na szukanie „dwóch wyrazów z wielkiej litery” gdzie indziej, bo opis pozycji
  („Rozwój Strumienia Detalicznego”) wygląda dokładnie jak imię i nazwisko.
  Niejednoznaczna osoba = puste `consultant_name` + powód z numerem pozycji →
  bramka maila odsyła do kolejki, writer odmawia założenia osoby bez nazwiska.
  „Termin dostawy” jest ignorowany (to po nim model zgadywał datę końca).
  Netto dowodzi nagłówek „Wart.netto”, a iloczyn ilość × cena ≠ wartość netto
  pozycji to powód do weryfikacji, nigdy korekta. Polityka ma trzy flagi
  rejestru: `open_ended_period` (bramka maila nie żąda daty końca, front
  dostaje `open_ended` i czyści pole „do”), `exposes_consultant_rows` (ręczny
  odczyt oddaje tabelę osób z limitem MD) i `closes_on_md_exhaustion`
  (patrz niżej). Kanoniczne ID 18 jest odpinane w testach autouse fixturą
  `_detach_bik_canonical_client` — serial `clients.id` inaczej zamienia
  osiemnastego klienta testowego w BIK.
- **BIK: zamówienie kończy wyczerpanie limitów MD WSZYSTKICH osób**
  (`services/order_md_exhaustion.py`). Linie MD kończyły się same już wcześniej,
  ale grupa zostawała `active` bez ani jednej aktywnej osoby. Teraz
  `recompute_remaining` (jedyny writer `md_remaining`, wołany przez import
  zużycia z Finansów) woła `sync_md_group_exhaustion`: grupa per osoba przechodzi
  na `completed` z `closure_reason` „Wszyscy konsultanci wyczerpali limit MD”
  i bez autora, gdy każda nieanulowana linia ma limit i `md_remaining <= 0`.
  Osoba bez limitu trzyma zamówienie otwarte. Świadomie `completed`, nie
  `exhausted` (ticket: „Zakończone”; `exhausted` = pula WSPÓLNA z własnymi
  alertami). Korekta przywracająca komuś MD wskrzesza grupę automatycznie —
  tylko zakończoną automatycznie; ręczne „Przywróć” takiej grupy daje 409
  z instrukcją. Siatka: dobowy skaner i `GET …/order-groups` (reconcile).
- **Zamówienie zakończone wyczerpaniem ma `closure_date` = dzień przeliczenia**
  (nie koniec miesiąca zejścia) — inaczej `group_settles_in_month` odrzuca
  import za bieżący miesiąc (audyt 24.09.2026). Sprawa offboardingu z pulą 0 MD
  zamyka się sama (`md_pool_used_up`, payload `automatic`) i zamyka swój alert,
  ale NIE w trakcie decyzji człowieka — decyzja DL i przejęcie osłaniają linię
  (`offboarding_decision_in_progress` w `session.info`). Sprawa automatyczna nie
  blokuje „Cofnij zakończenie” — cofnięcie usuwa ją jak nierozstrzygniętą.
- **Nordea i Alior mają tabelę osób jako źródło prawdy** (`table_authoritative`
  w rejestrze): formularze czytają wszystkie osoby tak jak mail (parser
  all-rows, osobę wybiera polityka), a „Przelicz plan” stosuje regułę ponownie
  na zapisanym odczycie. U Aliora wiersz kotwiczy MARŻA (token z „%”), kwoty
  mają spację jako separator tysięcy, a nazwisko to słowa bloku wiersza bez
  słownika kompetencji. Model czyta osoby niezależnie: rozbieżność nazwiska,
  stawki albo okresu z tabelą idzie do weryfikacji — także PUSTA stawka/okres
  w odczycie modelu (prompt każe je zostawić puste, gdy model nie umie ich
  powiązać z osobą, więc brak to nie zgoda).
- **Alior porównuje tabelę z ZAPISANYM odczytem modelu** —
  `OrderExtraction.model_rows`, utrwalane w `order_mail_documents.extraction`
  i odtwarzane przez `restore_extraction`. Powody są budowane od zera przy
  każdym zastosowaniu. Bez tego „Przelicz plan” porównywałby tabelę z własnym
  wynikiem (`consultant_rows` po pierwszym zastosowaniu SĄ wierszami tabeli)
  i każda rozbieżność znikałaby po jednym kliknięciu. Zapis sprzed tej reguły
  nie ma `model_rows`; gdy dokument ma wiersze w starym kształcie
  (`_LEGACY_ROW_RE` — stara reguła mogła podstawić tabelę za odczyt modelu),
  nie potwierdza osób i idzie do człowieka. `model_rows` niesie kwoty, więc
  kolejka redaguje je jak `consultant_rows`.
- **U Aliora żadna pozycja nie znika po cichu**: osoba z odczytu modelu bez
  odczytanego wiersza w tabeli (druga pozycja tej samej osoby, wiersz
  w nietypowym układzie na kolejnej stronie) zostaje w wynikach jako niepewna.
  Pomijane jest wyłącznie powtórzenie z IDENTYCZNĄ stawką i okresem.
  Formularz z osobą (`target_consultant`) wybiera wiersz wspólnym ścisłym
  matcherem `_name_match_score` — nie „wszystkie człony w bloku”, bo
  „Anna Nowak” zawiera się w „Anna Nowak-Kowalska”.
- **Szkic, który niesie już zamówienie, nie jest nadpisywany dokumentem na
  rozłączny okres** (planer: `from_order_mail` z Activity `order_mail_*` albo
  `has_file`): Alior przysyła wrzesień i październik–grudzień osobnymi mailami,
  a szkic nie aktywuje się przed podpisem umowy. Ten sam numer albo nachodzący
  okres (korekta dokumentu) nadal uzupełnia ten sam szkic; szkic linii grupy
  zostaje przy `ACTION_GROUP` (osobne zamówienie obok linii MD rozdwoiłoby
  współpracę). Szkic wypełniony ręcznie bez pliku nadal jest „pusty” — znane
  ograniczenie, instrukcja każe dołączyć PDF.
- **Zmieniasz regułę klienta → PODBIJ `rule_version` w rejestrze.** Dokument
  zapamiętuje wersje reguł, którymi go przeczytano
  (`document_meta["rule_versions"]`) i stempluje je przy każdym przeliczeniu.
  Od 0316 wersja NIE jest już warunkiem przeliczenia — wstrzymany wpis wraca
  w każdym biegu (niżej) — ale stempel zostaje: mówi, którą regułą czytano
  zapisany odczyt. Wersja `None` = reguła bez wersjonowania.
- **Domniemanie netto bez reguły klienta** (`_document_marks_only_net`,
  UAT M07-B04): stawka bez oznaczenia przy kwocie jest netto tylko wtedy, gdy
  „netto” stoi przy etykiecie stawki/kwoty W TEJ SAMEJ LINII („Stawka netto
  za MD”, „kwota … PLN netto”), a dokument nigdzie nie mówi „brutto” ani
  o kwotach „z VAT”. Samo „Wartość netto razem” w podsumowaniu nie wystarcza —
  reguła działa też w bramce automatu poczty, więc luźniejsze dopasowanie
  zapisałoby stawkę z VAT jako pewną.
- **Erste stosuje się OSTATNIA** — przelicza kwotę ustaloną przez polityki
  wyżej. Odwrotna kolejność po cichu nie przeliczyłaby nic.
- **Credit Agricole odmawia zamiast zgadywać**, gdy obie etykiety stoją
  w jednym wierszu (nagłówek tabeli): bez wyrównania kolumn „pierwsza liczba
  za etykietą” trafia w liczbę porządkową. Zła stawka zapisana jako pewna jest
  gorsza niż puste pole — wychodzi dopiero na fakturze.
- **`total_value` NIE jest przeliczane** u Erste (ticket mówi o stawce).
- **BNP omija matcher konsultanta, i to jest cała jego istota.** PDF-y tego
  klienta NIE zawierają imienia ani nazwiska — niosą wyłącznie numer ID
  konsultanta. Generyczny matcher (`apply_consultant_row_match` +
  `enforce_consultant_policy_safety`) jest fail-closed po nazwisku, więc dla
  takiego dokumentu KAŻDY odczyt kończył się wyczyszczeniem stawki i liczby
  MD — to jest zgłoszona awaria, nie błąd modelu. Dla BNP parser dostaje sam
  tekst (bez `consultant_name`), a bramka bezpieczeństwa matchera jest
  pomijana; tożsamość rozstrzyga karta, z której operator uruchomił odczyt.
- **Odczytany numer ID NIE jest nigdzie zapisywany.** Nexus nie przechowuje
  identyfikatorów nadanych przez klienta (`candidates.external_id` to ID
  z Traffita, objęte unikalnością per źródło i nadpisywane przy każdym syncu),
  więc numer jedzie wyłącznie w odpowiedzi odczytu jako `consultant_ref` i
  służy WZROKOWEMU potwierdzeniu. Nie jest kwotą, więc przeżywa redakcję
  finansową — rola bez `VIEW_FINANCE` też musi wiedzieć, czyjego zamówienia
  dotyczy plik.
- **BNP jest klientem WIELO-KONSULTANTOWYM**, więc jego zamówienia obsługuje
  `ConsultantLineModal` / `OrderGroupFormModal` / `ExtendOrderGroupModal`, a nie
  widok jednoosobowy. Pole odczytu dołożone tylko do `EditOrderDialog` byłoby
  dla realnego użytkownika BNP MARTWE (ta sama pułapka co przy „Dwóch widokach
  zamówień” wyżej).
- **Brak etykiety u BNP NIE czyści pola** (inaczej niż w Credit Agricole).
  Tam kasowanie było odpowiedzią na udokumentowaną pomyłkę dwóch sąsiednich
  etykiet; tu takiego incydentu nie ma, a wyczyszczenie zostawiłoby operatora
  z pustym formularzem, czyli z tym, na co się skarży. Wartość modelu zostaje,
  ale zawsze z komunikatem „sprawdź”.
- **Dwie rzeczy w wyrażeniu ilości są obroną, nie kosmetyką**: `[^\S\n]*`
  zamiast `\s*` (zwykłe `\s*` przechodzi przez nową linię, więc kwota
  z wiersza wyżej sklejała się z „Szt.” z wiersza niżej i do liczby MD
  trafiała STAWKA) oraz brak spacji w klasie cyfr (separator tysięcy sklejał
  numer porządkowy z ilością: „1 105 szt.” → 1105 zamiast 105).
