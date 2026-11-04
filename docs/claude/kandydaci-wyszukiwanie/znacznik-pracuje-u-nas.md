# Znacznik „Pracuje u nas” — jedna reguła na każdym ekranie (12.10.2026)

<!-- indeks: pracuje / kończy / zaczyna u nas, „Potwierdź zatrudnienie”, dzwonek do DL -->

Zgłoszenie Artura: osobę, która u nas pracuje (umowa + zamówienie), dało się
wyszukać i dodać do rekrutacji, a po drodze nigdzie nie było widać, że pracuje
— dopiero na profilu. Dane były w API (`employment`), ale czytał je tylko
profil, szybki podgląd i kolumna „W procesie” listy. Makiety i decyzje D1–D5:
https://claude.ai/artifact/QekWy3zx3pXNEKDKQmikf6, raport:
`docs/employment-marker-completion-report.md`.

## Reguła

- **Tylko umowa (decyzja Artura 17.10.2026).** Znacznik, stare pole
  `employment`, filtry `at_client` / `available` i lista „Nasi konsultanci
  u tego klienta” czytają wyłącznie żywą umowę w Kontraktach (B2B, umowa
  o pracę, zlecenie). Etap „Zatrudniony” bez umowy i ręczny konflikt
  `current_employment` („Oznacz jako zatrudnionego”) nie są już źródłem —
  szczegóły w sekcji „Tylko umowa” na końcu. Nie przywracaj ich jako sygnału.
- **Jedno źródło: `services/employment_marker.py`.** Czysta `build_markers`
  rozstrzyga fazę, źródło i klientów; każdy ekran czyta jej wynik jako pole
  `employment_marker`. Nowy ekran z osobą = to pole, nie własne wyliczenie
  z umów.
- **Fazy:** „pracuje” = żywa umowa (`active` / `ending`) ze startem nie później
  niż dziś albo bez daty (`current_employment.is_live_contract`); „zaczyna” =
  żywa umowa ze startem w przyszłości; „kończy” = do końca łańcucha zamówień
  bez kontynuacji zostało najwyżej 30 dni. Podpis w Generatorze aktywuje
  umowę od razu i przesuwa kartę na „Zatrudniony” — przy starcie w
  przyszłości znacznik mówi „zaczyna”, nie „pracuje”.
- **Stare pole `employment` zostaje.** `employed_at_client` znaczy „ma u nas
  żywą umowę albo sygnał zatrudnienia”, także przed dniem startu — filtr listy
  „Otwarci” nie może łapać osoby z podpisaną umową. Niezmiennik w teście:
  `employed_at_client` ⇔ znacznik istnieje. `contractor_identity.is_current_contract`
  (sama data startu) to reguła kwot i zostaje osobno.
- **Data w znaczniku to koniec zamówień, nie umowy** (umowa B2B jest
  bezterminowa): koniec łańcucha bez kontynuacji wg `order_continuation` — to
  samo, co pokazuje lista kontraktorów. Zamówienie do końca miesiąca
  z przedłużeniem nie daje „do końca miesiąca”. Bez daty: zamówienie
  bezterminowe, brak zamówień, aktywna linia MD z budżetem. Wyjątki od
  14.10.2026 — sekcja „Po audycie 13.10.2026” niżej.
- **„Kończy” idzie za regułą alertów Delivery**, nie za zakładką „Kończące się
  30d”: linie zamówień MD „kończą się” tylko u klientów
  z `EXTENDED_ORDER_ALERT_CLIENT_IDS`. Zakładka liczy grupy MD na froncie
  u każdego klienta — ten rozjazd istniał wcześniej.
- **Znacznik niczego nie blokuje** (jak konflikty z klientem od 17.09.2026)
  i nie niesie kwot, więc widzi go każda rola operacyjna. „Kontrakt ›” w ramce
  tylko z dostępem do sekcji Delivery.
- **Rekruter widzi przez znacznik klienta, koniec zamówienia i Delivery Leada**
  także bez dostępu do zamówień w Delivery, a filtr „Kończy u nas w ciągu 60
  dni” daje mu taką listę dla całej bazy. To cel znacznika (makiety 1–4 i 6
  zatwierdzone przez Artura), nie przeciek. Znacznik nie niesie i nie może
  zacząć nieść stawek, numerów ani treści zamówień — nowe pole z zamówienia
  w znaczniku to zmiana dostępu, do decyzji Artura.
- **`elsewhere`** jest liczone tylko, gdy znany jest klient rekrutacji: `true`
  = któryś klient znacznika jest spoza rodziny klienta tej rekrutacji, `false`
  = to klient tej rekrutacji. Przy `false` pigułka mówi „Pracuje u tego
  klienta” i zastępuje plakietkę `client_current_employment` (bez dubla —
  `markerCoversEligibility`).

## Gdzie i jak

- **Koszt.** Lista kandydatów składa wiersze z relacji już wczytanych
  (`rows_from_candidate`), więc nie dokłada zapytań o źródła; zamówienia
  i Delivery Leadzi dochodzą tylko, gdy na stronie jest ktoś z sygnałem.
  Pozostałe ekrany: jedno zapytanie o źródła na stronę
  (`load_employment_markers`). Pulpit „Moje następne kroki” składa do 25
  tablic w pętli i znacznika nie niesie (`with_employment=False`).
- **Front:** treść w `lib/employment-marker.ts`, pigułka
  `ds/EmploymentPill`, ramka `v2/employment/EmploymentNotice`. Pigułka stoi
  OBOK nazwiska, nigdy w przycisku nazwiska ani w linii faktów — ich treść
  jest nazwą dostępną i tekstem, po którym szukają testy. `lib/employment-marker.ts`
  nie importuje wartości z `@/lib/api` (testy okien mockują tamte moduły wąsko).
- **Panel osoby:** krótka pigułka w rzędzie odznak, ramka w dymku. Stała
  ramka zabrałaby treści panelu wysokość — test `e2e/responsive-preview.spec.ts`
  wymaga 350 px przy 1280 × 650.
- **Lista:** znacznik stoi pod nazwiskiem (kolumna „Kandydat” jest wymagana,
  „W procesie” da się ukryć), a „W procesie” liczy rekrutacje w toku. Filtr
  w pigułce „Dostępność”: `employment=at_client` („Pracuje u nas”)
  i `employment=ending_soon` („Kończy u nas w ciągu 60 dni”); jedna lista
  wartości `EMPLOYMENT_FILTER_VALUES`. Filtr działa dla jednej wartości
  i zostaje „tylko lista” (drugi silnik go nie ma).
- **Okno „Dodaj do rekrutacji”** dostaje osoby pracujące propsem `employed`
  od ekranu, który je otwiera — bez osobnej trasy. Zaznaczenie odtworzone
  z adresu dla osób spoza wczytanych stron nie ma danych do ramki.
- **Tablica rysuje ostrzeżenia pary**, które serwer wysyłał w `warnings`
  (NDA, czarna lista klienta, konkurent…) — jedna mapa etykiet
  `lib/eligibility-reason-labels.ts`, na karcie i w wierszu tabeli.
- **Weryfikacja Profilu Championa → „Rozmowa z naszym konsultantem”**
  (14.10.2026): lista „Nasi konsultanci u tego klienta”
  (`GET /api/jobs/{id}/champion-profile/consultant-suggestions`) liczy tą samą
  regułą — od 17.10.2026 wyłącznie żywe umowy (także `ending`) — u klienta
  rekrutacji ze scalonymi rekordami (`job_client_family`), bez limitu,
  alfabetycznie.
  Wcześniej własne wyliczenie (30 osób na źródło, umowy w przypadkowej
  kolejności, same `active`, każdy dawny „Zatrudniony”) zasłoniło Delivery
  Leadowi konsultanta, z którym rozmawiał. Okno (`champion/ConsultantPicker`)
  szuka też w całej bazie i zapisuje osobę spoza NEXUSA z wpisanego imienia
  i nazwiska — serwer przyjmuje dowolnego kandydata, lista to podpowiedź.
- **„Moi ludzie”:** osobę z grupy „Pracują” można dodać do rekrutacji (D5);
  grupa i pigułka idą z jednego wyniku. Automat dopasowań i narzędzia Jarvisa
  dalej pomijają pracujących.

## Zatrudnienie i dzwonek (D3, D4)

- **„Potwierdź zatrudnienie”** pyta „Co z obecną współpracą?”, gdy karta
  niesie znacznik z `elsewhere=true`. Odpowiedź
  (`StageMove.hired_current_engagement`) jest opcjonalna na serwerze, wymagana
  w oknie; serwer zapisuje ją tylko, gdy osoba faktycznie ma zatrudnienie
  u innego klienta. Trafia do historii ruchu i na oś czasu profilu (trzy akcje
  `candidate_hired_engagement_*` — oś nie czyta `details`).
- **Okno niczego nie zmienia w umowach i zamówieniach.** Zakończenie
  współpracy dalej zaczyna się w oknie zakończenia (`/terminate`).
- **Dzwonek `consultant_in_other_recruitment`** (0431,
  `services/consultant_elsewhere_notifications.py`): do Delivery Leadów
  klienta, u którego osoba pracuje, gdy karta wchodzi na „CV wysłane”
  w rekrutacji u innego klienta (raz na parę osoba–rekrutacja) albo gdy osoba
  zostaje tam zatrudniona. Samo dodanie do rekrutacji nie dzwoni.
- **Jedno wpięcie:** `stage_notification_emitter.notify_stage_change` — przez
  nie idzie ruch pojedynczy, zbiorczy, automat i podpis w Generatorze. Po
  commicie ruchu; błąd dzwonka nie cofa ruchu. Cały dzwonek stoi
  w savepoincie, bo jest wołany przed regułami etapów w tej samej sesji —
  nieudane zapytanie bez savepointu zabrałoby zwykłe dzwonki tego ruchu.
- **Odbiorcy:** `bell_recipients` (admini tylko jako zapas); autora ruchu
  odsiewamy PO wyznaczeniu odbiorców — odsianie przed dałoby zapas na adminów
  zawsze, gdy kartę rusza jedyny Delivery Lead klienta.
- „CV wysłane” rozpoznajemy po kolumnie Tablicy, nie po kodzie etapu (etapy
  z szablonów Traffita mają inne kody); ruch wstecz nie dzwoni.

## Po audycie 13.10.2026 (14.10.2026)

Audyt pokazał, że były konsultant z dawnym etapem „Zatrudniony” zostawał
„Pracuje u nas” na zawsze (dzwonek szedł do Delivery Leada byłego klienta,
okno zatrudnienia pytało o nieistniejącą współpracę), a wypowiedziana umowa
z linią MD i umowa po końcu ostatniego zamówienia mówiły „Zamówienie bez daty
końca”. Teraz obowiązuje:

- ~~Etap „Zatrudniony” zamykany umową (`hire_closed_by_contract`)~~ — od
  17.10.2026 etap w ogóle nie jest sygnałem (sekcja „Tylko umowa”).
- **Data końca = wcześniejsza z dwóch:** koniec łańcucha zamówień i data końca
  umowy (`contracts.end_date`; umowa B2B ma ją tylko po ręcznym zakończeniu).
  Wypowiedziana umowa z linią MD z budżetem kończy się w swojej dacie.
- **Łańcuch, którego wszystkie zamówienia już się skończyły** (zamknięte albo
  z datą końca w przeszłości; porzucony pusty szkic się nie liczy, zaplanowany
  szkic z datą albo stawką — tak), daje ostatni dzień ostatniego zamówienia,
  także przeszły: znacznik mówi „Kończy u nas <data>”, a nie „Pracuje · bez
  daty końca”.
- **Filtr „Kończy u nas w ciągu 60 dni”** łapie osobę tylko, gdy KAŻDA jej
  trwająca umowa kończy się najpóźniej za 60 dni — także ta, której
  zamówienia już się skończyły (ta sama data co w znaczniku, `_work_end_sql`).
  Druga umowa bez końca = osoba zostaje u nas.
- **Dzwonek o zatrudnieniu też raz na parę** osoba–rekrutacja (cofnięcie
  z „Zatrudniony” i ponowne zatrudnienie nie dzwoni drugi raz). Liczy się tylko
  wcześniejszy dzwonek o zatrudnieniu — dzwonek o „CV wysłane” go nie zastępuje.
- ~~„Zatrudniony” bez umowy liczony 12 miesięcy (`STALE_HIRE_DAYS`)~~ —
  zastąpione 17.10.2026 regułą „tylko umowa”.

## Dostępność i stawka z umowy (15.10.2026)

Zgłoszenie pracownika: profil mówił „Pracuje u nas do 30.11.2026” i jednocześnie
„Dostępność od 1.09.2026” — data i „Stawka od” pochodziły z notatek ze
screeningu sprzed zatrudnienia. Pomiar produkcji 15.10.2026: 483 osoby
z żywą umową, 308 z minioną datą „Dostępny od” (Tablica pisała „od razu”), 135
ze statusem „Szuka aktywnie”, 99 ze „Stawką od” niższą o ponad 5 zł/h niż
stawka z umowy. Makiety i decyzje D1–D6 (Artur zatwierdził wszystkie, D4 = B):
https://claude.ai/artifact/1oJ9qiLdPFKTsEXTwdLpSN.

### Termin dostępności (D1, D2)

- **Reguła:** dopóki osoba ma żywą umowę (`active`/`ending`), termin =
  późniejsza z dat: dzień po końcu pracy u nas i `availability_date` z profilu.
  Wcześniejsza data z profilu to dawny screening; późniejsza znaczy, że
  kandydat sam podał dalszy termin. Odejście przed końcem zamówienia ustala
  Delivery — notatka rekrutera go nie przyspiesza.
- **Jedno źródło: znacznik.** `EmploymentMarker.free_from` i `free_from_basis`
  liczy `employment_marker.contract_free_from` z WSZYSTKICH umów osoby, przed
  wyborem jednej umowy na klienta (ten woli trwającą i gubi kolejną umowę
  u tego samego klienta). Podstawy: `work_end` (dzień po najpóźniejszym końcu
  pracy, także minionym), `no_end_date` (umowa bez końca pracy albo kolejna
  umowa po bieżącej), `starting` (żadna umowa jeszcze się nie zaczęła).
  Koniec pracy = ta sama data co w ramce „Pracuje u nas” (`order_end_date`).
- **Bez umowy w NEXUSIE** (sam konflikt albo etap „Zatrudniony”) i po końcu
  umowy — bez zmian: data z profilu.
- **Front:** `lib/contract-availability.ts` (`contractAvailability`, tekst,
  dymek, `hidesAvailabilityStatus`). Każde miejsce, które składa tekst
  dostępności z `availability_date`, najpierw pyta ten moduł: karta „Do
  propozycji”, panel osoby, tabela Tablicy (`person-rows`), lista
  (`candidate-row-format`), propozycje i filtr „dostępny teraz”
  (`proposals-merge`), podgląd, przegląd DL, ekran przed rozmową, porównanie.
  Nowy ekran z osobą = ten moduł, nie własne liczenie.
- **Serwer bez znacznika:** `services/contract_availability.py` —
  `load_contract_free` (jedno zapytanie na stronę, lustro daty znacznika przez
  `employment_marker.work_end_sql`; zgodność z `load_employment_markers`
  pilnuje `test_contract_availability_db.py`), `contract_free_by_clause` dla
  filtra `availability_date_before` (`structured_candidate_search`) i
  `attach_contract_free` przed oceną dopasowania.
- **Ocena dopasowania:** `_score_availability` i kara za kolizję ze startem
  Championa czytają `candidate._contract_free`; bez daty końca i przed startem
  umowy = 0 pkt. Ścieżki wsadowe dołączają raz na pulę (`rank_candidates_for_job`,
  `canonical_fit`, worker wyszukiwania, `match_score_cache`, marketplace,
  rekomendacje), `score_candidate_job` ma zapas na pojedynczą parę. Klucz
  `availability_contract` w `scoring_algorithm_version`. Ocena nie unieważnia
  się przy samym przedłużeniu zamówienia (5/100 pkt może chwilę odstawać).
- **Też z umowy:** pole „Start” w przeglądzie DL, kolejka Cpro, podpowiedź
  daty startu w Generatorze umów B2B, fakty dla promptu uzasadnienia
  dopasowania (dołączane przed hashem promptu — bez tego hash zależałby od
  kolejności wywołań). Bramka ruchu (`move_requirements`, „dostępność znana”)
  zostaje przy profilu: pyta, czy rekruter ustalił termin z kandydatem.

### Pigułka i okno edycji (D3, D6)

- **„Szuka aktywnie / Otwarty na oferty” znika przy żywej umowie** (pasek
  osoby, lista) — zostaje „Pracuje / Kończy / Zaczyna u nas”. Status w bazie
  bez zmian, wraca po końcu umowy. Strażnik
  `CandidateDetailRecruiterUx.test.ts` liczy dokładny zapis
  `<AvailabilityPill status={candidate.availability_status}` i wystąpienia
  `availability_status` w katalogu profilu — warunek nie może go powtarzać.
- **Okno „Dostępność kandydata”** ma ramkę: do kiedy osoba pracuje, kto
  ustala wcześniejsze odejście (Delivery Lead ze znacznika), że późniejsza
  data zastąpi termin z kontraktu. Ołówek zostaje.

### Status „Czy szuka pracy” przy żywej umowie (S1–S5, 15.10.2026)

Zgłoszenie rekrutera: konsultant z umową z Nordeą i zamówieniem do 31.01.2027
miał przy nazwisku „Szuka aktywnie” obok „Pracuje u nas”. Status wpisał
10.10.2026 automat notatek z „ASAP” w screeningu z 15.07.2026, sprzed umowy.
Pomiar 15.10: 132 z 483 osób z żywą umową miało „Szuka aktywnie”, 115 z nich
z automatu notatek, wszystkie 132 siedziały w puli Targu. Makiety i decyzje:
https://claude.ai/artifact/LZLL3SdRAyaK3j7GbF2DMb (Artur: „wdróż”, S5 = A).

- **Reguła:** dopóki osoba ma żywą umowę (`active`/`ending`, także przed
  startem — „Zaczyna u nas”), status z profilu nie jest pokazywany ani
  używany do wybierania ludzi. O tym, czy i od kiedy jest wolna, mówi
  znacznik. Sam konflikt „Obecne zatrudnienie” i etap „Zatrudniony” statusu
  nie chowają — ten sam warunek co pigułka (`hidesAvailabilityStatus`,
  znacznik ze źródłem `contract`).
- **Jedna funkcja i lustro:** `contract_availability.availability_status_hidden`
  (Python, wynik `load_contract_free` / `ATTRIBUTE`) i
  `without_live_contract_clause` (SQL). Zgodność z pigułką pilnuje
  `test_contract_availability_db.py`. Nowe miejsce, które wybiera ludzi po
  statusie, bierze jedną z nich, nie własne `availability_status IN (...)`.
- **Gdzie działa:** pula Targu (`auto_sync_marketplace_membership` nie dodaje,
  a wpis automatyczny osoby z żywą umową schodzi w tym samym biegu; ręczny
  wrzut zostaje), źródło B „Dostępnych kontraktorów” (`seeking_contractors`:
  osoba z żywą umową wchodzi przez status tylko, gdy wg znacznika kończy
  pracę w horyzoncie — `contract_free_by_clause`; źródło A widzi wyłącznie
  `contracts.end_date`, którego umowa B2B przed ręcznym zakończeniem nie ma,
  więc bez tego wyjątku kończący zamówienie wypadliby z ekranu), licznik „N oznaczonych jako dostępni”
  w dzwonku podobnych requestów, plakietka „dostępny” w „Kandydatach
  z podobnych projektów” (przy żywej umowie „nie wiadomo”), wejście modelu
  podsumowania aktywności (termin z umowy zamiast statusu i daty, jak
  uzasadnienie dopasowania). Filtr listy „Czy można go teraz zaproponować?”
  pomijał pracujących już wcześniej. API v1 oddaje surowy status (to dane).
- **Automat notatek (S2):** „od zaraz” zamienia „Nie wiemy” na „Szuka
  aktywnie” tylko u osoby bez żywej umowy i z notatki o dostępności nowszej
  niż start jej ostatniej umowy (żywej, przyszłej albo zakończonej; szkic,
  umowa do podpisu i unieważniona się nie liczą). Bez dnia notatki — nie.
  `ContractHistory.allows_status_from_note`, historia z `load_contract_history`
  (jedno zapytanie na osobę w pętli `notes_insights_sync`). Data dostępności
  i okres wypowiedzenia z notatek idą jak dotąd — ekrany liczą termin z umowy.
- **Statusów w bazie nie przepisujemy (S5 = A).** Wrócą po końcu umowy;
  jednorazowa korekta „Szuka aktywnie” z notatki sprzed umowy (ok. 115 osób)
  to osobna decyzja, gdyby stary status po końcu umów przeszkadzał.
- **Okna edycji (S4):** ramka `availabilityContractNote`
  (`lib/contract-availability.ts`) mówi, że status jest ukryty do końca
  współpracy — w „Dostępności kandydata” na profilu i przy „Dyspozycyjności”
  w „Edytuj dane” (`EditCandidateModal`). Pole zostaje edytowalne.

### Stawka (D4, D5)

- **„Stawka od” = stawka konsultanta z bieżącej umowy**, dopóki umowa trwa
  — szczegóły w `screening-notatki/stawka-od-i-historia-stawek-kandydata.md`
  (sekcja „Żywa umowa”). Profil pisze wtedy „Stawka u nas” z zieloną kropką
  (`rate_from_source = contract` w odpowiedziach).
- **Kto widzi kwotę (D4 = B):** każdy, kto widzi stawkę kandydata — także
  rekruter, Delivery Lead innego klienta i rola „Automatyzacje” w aplikacji.
  Tylko stawka konsultanta z ŻYWEJ umowy: historia stawek (`_paid_rates`)
  i „ostatni kontrakt” w przeglądzie DL pokazują ją każdemu; zakończone umowy,
  stawka do klienta, marża i kwoty zamówień zostają przy dostępie do finansów.
  API kluczy dalej za zakresem kosztów (`profile_rates(show_costs=…)`).
- Znacznik dalej NIE niesie kwot — stawka idzie przez „Stawkę od”.

## Tylko umowa (17.10.2026)

Pytanie rekrutera „jak oznaczyć, że ktoś jest zatrudniony” i decyzja Artura:
zatrudniony to osoba z umową w Kontraktach — z umowy czyta się też stawkę
i termin dostępności, więc nie oznacza się go ręcznie. Makiety:
https://claude.ai/artifact/UGYuAg37XJYhkAipLQyPeW. Pomiar produkcji 17.10:
493 osoby z żywą umową; ok. 23 osoby z kartą „Zatrudniony” z ostatniego roku
bez umowy i 1 ręczny wpis straciły znacznik.

- **Źródło:** wyłącznie żywa umowa (`active` / `ending`; start w przyszłości =
  „Zaczyna u nas”). `build_markers(contracts, …)` i `rows_from_candidate`
  nie mają już sygnałów; `_derive_employment` daje `employed_at_client` tylko
  z umowy (`source` ∈ `contract` / `none`), `_at_client_predicate` to samo
  `EXISTS` po umowach. Usunięte: `SignalRow`, `hire_closed_by_contract*`,
  `current_hired_signal_exists`, `STALE_HIRE_DAYS`.
- **Ręczne „Oznacz jako zatrudnionego” zniknęło** (szybki podgląd, także
  u Delivery Leada i admina; `capabilities.can_mark_employed` usunięte).
  `POST /conflicts` z typem `current_employment` → 422
  `conflict_type_retired`; formularz konfliktów go nie oferuje (stare wiersze
  dalej się wyświetlają). Jedyny aktywny wpis na produkcji zdjęła migracja
  0452 / faza danych entrypointu z powodem (marker
  `manual_employment_conflicts_retired_2026_10`). Kod dopuszczalności dalej
  umie czytać ręczne wiersze — nowych nie da się dodać.
- **Karta „Zatrudniony” bez umowy** (ręczne „Potwierdź zatrudnienie”: B2B
  poza Generatorem, umowa o pracę, zlecenie) niesie `missing_contract` —
  plakietka „Brak umowy w Kontraktach” na karcie i w panelu osoby
  (`services/hire_contract_reminder.missing_contract_ids`; tylko zatrudnienia
  z ostatnich 365 dni, umowa = dowolny wpis poza `void` u klienta rekrutacji
  i jego scalonych rekordów, także szkic). Okno zatrudnienia mówi, że znacznik
  pojawi się po wpisaniu umowy.
- **Dzwonek `hire_missing_contract`** (0452, temat „Rekrutacje” z dymkiem,
  kategoria Kontrakty) do Delivery Leadów klienta rekrutacji, raz na parę
  osoba–rekrutacja; wpięty w `stage_notification_emitter.notify_stage_change`
  obok dzwonka „konsultant w innej rekrutacji”, po commicie, best-effort.
  Podpis w Generatorze tworzy umowę przed ruchem, więc nie dzwoni.

