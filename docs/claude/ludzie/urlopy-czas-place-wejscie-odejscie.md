# Urlopy i M365, „Mój miesiąc”, płace, wejście i odejście (16.10.2026)

## Urlopy (`app/services/hr/leave_*.py`)

- Reguły liczą czyste funkcje `leave_policy.py`; zapis, powiadomienia i kolejka
  M365 — `leave_service.py`. Każda decyzja to warunkowy `UPDATE … WHERE status`:
  drugi akceptujący dostaje 409, nie drugą decyzję.
- Dzień urlopu to wiersz `leave_request_days` z `UNIQUE (user_id, day) WHERE active`
  — baza nie pozwala na dwa nakładające się wnioski.
- Pula liczona per rok kalendarzowy DNIA (urlop 29.12–02.01 zjada pulę dwóch lat);
  B2B zużywa pulę dniami płatnymi; urlop na żądanie 4 dni i opieka nad dzieckiem
  2 dni w roku; dzień jest niepodzielny, pół dnia mieści się w połówce puli.
- **Nikt nie decyduje o własnym wniosku, także admin** (reguła + CHECK
  `decided_by <> user_id`).
- Zgodę na przekierowanie poczty do zastępcy daje tylko osoba składająca wniosek.
  Przekierowanie tylko do zastępcy z adresem w domenie z `SSO_ALLOWED_DOMAINS`:
  422 przy wniosku albo zgodzie, wykonawca M365 odmawia (`substitute_outside_company`).
- Akceptacja urlopu usuwa godziny z dni urlopu w „Moim miesiącu” i przelicza
  sumę kontrolną (`time_hooks.on_leave_approved` / `on_leave_cancelled`).
- Powiadomienia (dymek) i mail zastępcy nie zdradzają rodzaju ani notatki (D6);
  mail „Czas i ludzie” nie niesie rodzaju nikomu, także przełożonemu i Kadrom
  (`services/hr/hr_mail.py`, reguła w `modul-ludzie-dostep-schemat-i-przelaczenie.md`).
  Trwałe miejsce spraw do decyzji to „Ludzie → Akceptacje” z licznikiem.

### Zastępca nieobecnego przełożonego (17.10.2026, `leave_substitute.py`)

- Przełożony na **zatwierdzonym** urlopie obejmującym **cały** dzisiejszy dzień
  (kalendarz firmy; pół dnia i wniosek oczekujący się nie liczą) wskazał we
  wniosku zastępcę. Do końca tego urlopu zastępca widzi w „Akceptacjach”
  wnioski podwładnych tego przełożonego, akceptuje i odrzuca je (bez anulowania
  i wpisu za pracownika) i akceptuje ich timesheety. Zakres kończy się sam —
  nie ma nic do sprzątania.
- Zakres to tylko podwładni nieobecnego przełożonego: nie on sam, nie cudzy
  zespół (404 jak u przełożonego cudzego zespołu), nie własny wniosek (403).
- D6: zastępca nie należy do kręgu. Rodzaj widzi tylko przy planowych
  (`SUBSTITUTE_VISIBLE_TYPES`); L4, urlop opiekuńczy, siła wyższa,
  macierzyński i oddanie krwi to dla niego „Nieobecność” do wiadomości (403
  przy decyzji) — taki wniosek dostają też Kadry, żeby nie czekał do powrotu.
  Notatki wniosku zastępca nie widzi nigdy. W timesheecie dni urlopu bez rodzaju.
- Nowy wniosek: powiadomienie do przełożonego i do zastępcy („w zastępstwie
  za …”); L4 — zastępca dostaje „do wiadomości” bez rodzaju.
- Ślad decyzji: `details.as_substitute_for` = „w zastępstwie za …” (+ id).
- Plakietka przy osobie poza „Ludźmi” (lista „@”, kolumna „Rekruter” na
  `/jobs`) bierze `GET /api/hr/leave/absence` raz na listę i tylko przy
  otwartym module urlopów; awaria = brak plakietki, nie błąd ekranu. Po
  oznaczeniu nieobecnej osoby z zastępcą pole podpowiada „Oznaczyć też
  zastępcę?”.

## Microsoft 365 (`app/services/hr/m365/*`)

- Własna rejestracja aplikacji HR (D3), RBAC for Applications po stronie Exchange.
  Tryby `HR_M365_MODE`: `off` (operacje czekają w kolejce), `simulate` (te same
  żądania lądują w `hr_m365_operations.simulated_request` — lokalnie i do
  przeglądu w Kadrach → „Microsoft 365”), `live` (tylko skrzynki z
  `HR_M365_MAILBOX_ALLOWLIST`, pusta lista = wszystkie).
- Kolejka `hr_m365_operations` z `dedupe_key`, rezerwacja `FOR UPDATE SKIP LOCKED`,
  odroczenia 5 min → 30 min → 2 h → 6 h, po 6 próbach `failed`. W `last_error`
  kategoria błędu, nigdy treść odpowiedzi Graph. Każda operacja przed zapisem
  w skrzynce czyta wniosek — anulowany urlop nie dostanie autoodpowiedzi.
- Autoodpowiedź „nasza” niesie znacznik NEXUSA albo Compassa
  (`compass-managed-oof-v1`) — po przełączeniu NEXUS przejmuje te z Compassa.
  Własna autoodpowiedź osoby (bez znacznika) jest nietykalna. Okno liczone
  w datach warszawskich.
- Reguła przekierowania: nazwa `NEXUS · zastępstwo · {uuid}` (rozpoznajemy też
  `COMPASS · zastępstwo · {uuid}` — import zachowuje UUID), otwarcie pierwszego
  dnia urlopu, zamknięcie po ostatnim, `forwardTo` (kopia), domeny firmy z
  `SSO_ALLOWED_DOMAINS`. Reguła Outlooka nie ma warunków czasowych — sprzątanie
  sierot w uzgadnianiu 07:00 jest obowiązkowe.
- Wydarzenie w kalendarzu: prywatne „Poza biurem”, bez rodzaju nieobecności.
- **Uprawnienia rejestracji „NEXUS Kadry”**: APPLICATION `MailboxSettings.ReadWrite`,
  `Calendars.ReadWrite`, `Mail.Send` zawężone RBAC for Applications do skrzynek
  zespołu, plus `User.Read.All` (odczyt profili niżej). `User.Read.All` to
  uprawnienie katalogu Entra ID, nie Exchange — RBAC for Applications go nie
  zawęża; daje stanowiska, działy i telefony całego tenanta, bez poczty.

### Kartoteka z katalogu M365 (`m365/profile_sync.py`, `m365/directory.py`)

- Raz dziennie od 6:00 (pętla `hr_m365_daily`, rezerwacja `hr_job_runs`
  `hr_m365_profile_sync` per dzień), tylko przy włączonym module `people`.
  `GET /users/{upn}?$select=jobTitle,department,mobilePhone,businessPhones,accountEnabled`
  dla kartotek `onboarding/active/offboarding` z aktywnym kontem.
- Przepisujemy tylko pola, które kartoteka ma: `job_title`, `department`, `phone`
  (komórka, a bez niej pierwszy numer biurowy — kolejność Compassa, inaczej
  pierwsza synchronizacja przestawiłaby telefony). `officeLocation` nie
  przenosimy: kartoteka ma tylko biuro/zdalnie, a to ustalają Kadry.
  `accountEnabled = false` przy aktywnej kartotece tylko liczymy.
- **Kadry przed katalogiem.** Pole zmienione ręcznie w NEXUSIE
  (`profile_created`/`profile_updated` w `hr_audit_events`, także kreator
  wejścia) po ostatnim zapisie tego pola z M365 jest przypięte — katalog go nie
  nadpisuje. Kadry odpinają pole, czyszcząc je (puste pole zawsze wypełnia
  katalog). Pusty atrybut w katalogu niczego nie kasuje. Wartości z importu
  Compassa nie są ręczne, więc pierwsza synchronizacja je odświeża. (Compass
  nadpisywał ręczne zmiany co tydzień — błąd naprawiony.)
- Ślad `profile_m365_synced` tylko przy zmianie, z samymi nazwami pól;
  `m365_synced_at` stempluje każdy udany odczyt.
- Tryby: `off` nic; `simulate` buduje te same żądania, ale nie wysyła ich i nie
  zmienia kartoteki (wynik: liczba kont i wzór żądania, bez adresów); `live`
  czyta tylko konta z `HR_M365_MAILBOX_ALLOWLIST` (pusta = wszystkie).
- 404 = konto spoza tenanta → pomijamy i liczymy (`not_found`). 403 albo brak
  tokenu = przebieg `failed` (sonda `hr_m365`: `degraded: profile_sync_forbidden`),
  ponowienie przy kolejnym obrocie pętli (co godzinę).

### Termin sekretu rejestracji (`m365/secret_expiry.py`)

- Termin podajemy sami: `HR_M365_CLIENT_SECRET_EXPIRES_ON` (RRRR-MM-DD, data
  „Expires” z Entra ID). Pusta albo nieczytelna wartość = „nie znamy”, nigdy
  błąd startu.
- **Rotacja:** nowy sekret w Entra ID (rejestracja „NEXUS Kadry”) →
  workflow „Coolify set env” ustawia RAZEM `HR_M365_CLIENT_SECRET`
  i `HR_M365_CLIENT_SECRET_EXPIRES_ON` → stary sekret usunąć po wdrożeniu
  (okno 19:00–07:00) i sprawdzeniu `/api/health`.
- Sonda `hr_m365`: ≤ 30 dni `degraded: secret_expires_in_<n>d`, w dniu terminu
  i po nim `unhealthy: secret_expired` (uptime-probe otwiera zgłoszenie),
  brak daty przy rejestracji pracującej na żywo (urlopy, Intune albo czytnik
  administracja@) `degraded: secret_expiry_unknown`.
- Alarm `automation_failing` (tylko admini, mail od razu) od 7:00, raz przy
  progu 30, 14, 7, 1 dnia i raz w dniu terminu — klucz rezerwacji (termin,
  próg), więc nowa data po rotacji zaczyna od nowa. Karta „Microsoft 365”
  w Ustawieniach → Kadry pokazuje termin i ostatni odczyt profili, a nad kartą
  ostrzeżenie przy ≤ 30 dniach, po terminie i przy braku daty.

## „Mój miesiąc” — obecność i godziny (`app/services/hr/time_*.py`)

- Jeden ekran: siatka miesiąca z obecnością (tylko wyjątki od domyślnego miejsca
  pracy) i godzinami. Limit 8 h liczony na SUMĘ wpisów dnia pod blokadą wiersza
  timesheetu; ponad 8 h (do 16 h) to nadgodziny — tylko z prawem
  (`can_log_overtime`, Kadry, admin) i z uzasadnieniem. Pełny dzień urlopu
  blokuje wpis, pół dnia zajmuje 4 h; płatny urlop B2B z puli to auto-wpis.
- Przejścia: szkic → wysłany → zaakceptowany; zwrot do szkicu z notatką; cofnięcie
  akceptacji. Nikt nie akceptuje własnego timesheetu (CHECK `approved_by <> user_id`).
- **`pdf_hash` = funkcja Compassa co do bajtu** (`time_hash.py`, sortowanie jak
  w JavaScripcie, `toFixed(2)`). Zmiana algorytmu = każdy zaimportowany PDF zgłosi
  rozbieżność. Wektory w `tests/test_hr_time_hash.py` policzono kodem Compassa.
  Pobranie PDF przy rozjeździe sumy = 409.
- `payroll_locked` (zamknięty miesiąc płac) blokuje każdą zmianę timesheetu,
  także nowo zakładanego (`ensure_timesheet` czyta `payroll_periods.is_closed`).

## Płace i premie (`app/services/hr/payroll_*.py`, `bonus_rules.py`)

- D2: Płace (Finanse z roli, admin) widzą stawki i kwoty u wszystkich; osoba —
  swoje; przełożony — godziny i premie swoich bezpośrednich podwładnych, bez stawek
  i kwot wynagrodzenia. Nikt nie przyznaje premii sobie.
- Stawki z historią, obowiązują od 1. dnia miesiąca. Automat premii (placementy,
  Liga) i zmiana albo usunięcie stawki blokują okres płac współdzielonie przed
  własnymi wierszami (trwające zamknięcie miesiąca czeka albo daje 409).
- Trwałe usunięcie kontraktu anuluje jego propozycje premii automatu
  (`cancel_reason='contract_deleted'`, automat ich nie przywraca); przyznane zostają.
- Premie: `source` manual / contract_placement / league / compass_import,
  `source_key` unikalny (automat nie dubluje), `rule_snapshot` przy naliczeniu.
  Termin premii z placementu = start kontraktu + 21 polskich dni roboczych;
  premia DL = 10% × marża/h × 168 h; rekruter progami marży PLN/h. Progi
  i „dodatkowa premia DL” to ustawienia (`app_settings['hr_bonus_rules']`),
  w kodzie nie ma żadnej osoby.
- Zakończenie kontraktu przed terminem anuluje premię, cofnięcie zakończenia ją
  przywraca (`app/services/hr/contract_hooks.py`).
- Zamknięcie miesiąca: propozycje premii muszą mieć decyzję, ostrzeżenia wymagają
  potwierdzenia, linie zamrożone w `payroll_lines`, timesheety zablokowane.
  Ponowne otwarcie tylko admin, z powodem. Zamknięcie blokuje okres i timesheety
  PRZED liczeniem raportu; akceptacje timesheetów i premii sprawdzają okres pod
  blokadą współdzieloną (kolejność: okres, potem timesheet).
- Urlop zatwierdzony albo anulowany w zamkniętym miesiącu płac: odpowiedź API niesie
  `payroll_locked_months` i `payroll_warning` (front pokazuje je w komunikacie), Płace
  dostają powiadomienie i mail bez rodzaju nieobecności, ślad z `sensitivity="payroll"`.
- Dzień wolny firmy dodany albo usunięty przelicza dni aktywnych wniosków obejmujących
  tę datę (pula wraca), powiadomienie i mail osobie (mail bez słowa „urlop”); okno M365 bez zmian.
- Cofnięcie zakończenia kontraktu przywraca premię z zamkniętego miesiąca jako
  propozycję w pierwszym otwartym miesiącu (`restored_from_closed_period`).
- Import z Compassa: koniec stawki minus jeden dzień (Compass trzyma pierwszy dzień
  następnej stawki); ponowny import nie nadpisuje zmian zrobionych w NEXUSIE po
  poprzednim zapisie (`unchanged` albo `conflict`, nigdy `update`) — także fragmentów
  opisu, domyślnych opisów ról i wpisów timesheetu; timesheet zablokowany płacami
  jest nietykalny.

## „Mój czas” — przegląd, saldo, premie w drodze, rozliczenie (etap 2, 17.10.2026)

- **„Przegląd” jest pierwszą i domyślną zakładką** „Mojego czasu” (`?tab=overview`,
  inne wartości `?tab=` jak dotąd; link z powiadomienia `?tab=bonuses` działa).
  Karty: nieobecności, miesiąc, premie, przełożony, sprzęt, do zrobienia
  (`components/hr/me/MyOverviewTab.tsx`). Karta modułu wyłączonego nie istnieje
  i nie pyta serwera; awaria zapytania to zdanie z „Spróbuj ponownie” w karcie,
  nigdy „0”.
- **Forma zatrudnienia decyduje o słowach** (B2B i zlecenie nie mają urlopu
  w rozumieniu Kodeksu pracy; decyzja Artura 17.10): UoP → „Urlop RRRR”
  z „na żądanie X z 4” i „opieka nad dzieckiem X z 2”; B2B (i zlecenie)
  z płatną pulą > 0 → „Płatne dni przerwy (z umowy)” bez limitów Kodeksu;
  bez płatnej puli → „Nieobecności RRRR” bez „zostało”. Karta miesiąca:
  UoP „Ewidencja czasu pracy”, B2B „Raport godzin”, zlecenie „Potwierdzenie
  godzin” ze zdaniem o art. 8b ustawy o minimalnym wynagrodzeniu. Te same
  reguły w saldzie zakładki „Urlopy” (`balanceStats`). Funkcje:
  `components/hr/me/overview-format.ts`.
- **Saldo rozbite** (`GET /api/hr/leave/balance`, `leave_balance.day_split`):
  `used_days` = dni sprzed NEXUSA + zatwierdzone do dziś włącznie (dzień
  nieobecności trwający dziś już się liczy), `planned_days` = zatwierdzone po
  dziś, `pending_days` = czekające. Przy płatnej puli liczą się dni płatne
  i z `remaining_days` sumują się do puli z zaległym; „zostało” dalej odejmuje
  oczekujące. Bez płatnej puli (`has_paid_pool = false`: brak puli, pula 0)
  trzy liczby to wszystkie dni rodzajów puli (bez wynagrodzenia), `remaining_days
  = null`. Dzień liczy się do roku SWOJEJ daty (urlop przez Nowy Rok — dwie
  pule). `approved_days` zostaje (czyta je Jarvis).
- **Premie „w drodze” od podpisania umowy (D2).** Podpisana umowa przed startem
  to kontrakt `active` z przyszłym startem (podpis aktywuje go od razu).
  Automat zakłada propozycję, gdy zna marżę; bez stawki klienta (przychodzi
  z zamówieniem) propozycji nie ma. `GET /api/hr/payroll/me` niesie `forecast`
  (`services/hr/my_settlement.bonus_forecast`): kontrakty `active`/`ending`
  w oknie automatu, przed terminem premii, bez końca przed terminem, bez
  „powrotu po przerwie”, a odbiorcy i kwoty z tej samej czystej funkcji co
  automat (`placement_bonuses.placement_targets`), termin `eligible_date`,
  postęp `business_days_elapsed`. Pozycja, dla której automat ma już wiersz
  premii (w dowolnym stanie), do prognozy nie trafia. Kwota to szacunek („~”);
  bez stawek albo kursu NBP `amount = null` z `amount_missing_reason`. Nic nie
  jest zapisywane.
- `/me` zwraca premie w każdym stanie — **anulowane przez automat zostają**
  z `cancel_reason` (Compass i pierwsza wersja ekranu je chowały), przyznane
  mają `assigned_by_name`, każda `period_closed` (miesiąc zamknięty w płacach =
  rozliczona), propozycja przed terminem — postęp „X z 21 dni” tą samą funkcją
  co widok miesiąca płac (`_add_progress`). Ekran „Premie i stawka” pokazuje
  etapy: umowa → 21 dni → decyzja Płac → wypłata (`BonusStagesTable`).
- **„Moje rozliczenie” (D3)**: `GET /api/hr/payroll/me/settlement?year=`
  (bramka `require_hr_payroll_member`, 403 bez własnej kartoteki — także Płace
  i przełożony bez kartoteki). Miesiąc zamknięty = zamrożone `payroll_lines`
  osoby (`final = true`); otwarty = szacunek regułą raportu płac: stawka z 1.
  dnia miesiąca × suma wpisów timesheetu z „Mojego miesiąca” (zaakceptowanego
  albo w toku — `hours_source` `approved`/`entered`) + premie przyznane
  z okresem w tym miesiącu. Płace przy zamknięciu biorą tylko godziny
  zaakceptowane, więc szacunek zmienia się do zamknięcia. Tylko o sobie.
- **Archiwum timesheetów** w „Moim miesiącu” (`TimesheetArchive`): ostatnie
  12 miesięcy ze statusem, sumą godzin i PDF zaakceptowanego
  (`GET /api/hr/time/me/history`), pobierane dopiero po rozwinięciu.
- Harness `/preview/hr-my-time`: domyślnie „Przegląd” osoby B2B z umowną pulą,
  `?form=uop`, `?form=zlecenie`; zero żądań pilnuje
  `app/preview/__tests__/hr-my-time-harness.test.tsx`.

## Wejście i odejście (`app/services/hr/lifecycle_*.py`, `handover.py`, `deactivation.py`)

- Prowadzą Kadry; przełożony widzi sprawę swojego człowieka; wykonawca odhacza
  swoje zadania. Terminy zadań w dniach roboczych firmy.
- Odejście: przekazanie pracy po 18:00 ostatniego dnia (pięć rodzajów pracy
  przechodzi istniejącymi ścieżkami zapisu — rekrutacje, DL rekrutacji, klienci
  DL, „Moi ludzie”, podwładni), wyłączenie konta dzień później — ale dopiero po przekazaniu
  całej pracy (inaczej „Wyłącz konto teraz” z jawnym „mimo to”, zapisanym w śladzie).
  Sprawy z nieprzekazaną pracą nie da się zamknąć; przejmujący nie może sam odchodzić
  do dnia przekazania. Konto wyłącza wyłącznie sprawa odejścia (nie brak osoby na
  liście), raz na sprawę; admina nie wyłącza automat; przebieg z więcej niż limitem
  deaktywacji nie wyłącza nikogo — kończy się `failed` (`mass_exit_suspected`, sonda
  `hr_jobs` degraded) i powiadomieniem z mailem do Kadr i adminów raz dziennie.
- **Podwładni (etap 2, D5, 17.10.2026)** — piąty rodzaj (`reports`): osoby
  z kartoteką (status ≠ `exited`), których przełożonym jest odchodzący.
  Domyślnie przejmuje przełożony odchodzącego; bez niego — nikt, a wiersz
  z podwładnymi kończy się `failed` jak inne rodzaje (konto czeka, „Wyłącz konto
  teraz” bez „mimo to” = 409). Wykonanie zmienia `manager_user_id` regułami
  kartoteki (`people.validate_managers`, blokada struktury), ślad
  `profile_updated` per osoba (`source: hr_work_handover`). Bezpośredni
  podwładny wskazany jako przejmujący wchodzi na miejsce szefa — dostaje
  przełożonego odchodzącego; ktoś niżej w drzewie = odmowa
  (`receiver_creates_loop`, byłaby pętla). Wnioski i timesheety w toku idą do
  nowego przełożonego, bo akceptującego liczy się w chwili decyzji. Sprawy
  wejścia/odejścia samych podwładnych (`case.manager_user_id`) przekazanie nie
  przepina.
- „Cofnij odejście” zamyka sprawę administracja@ i anuluje zadanie zwrotu sprzętu;
  unieważnienie szkicu kontraktu zamyka sprawę „Wejście konsultanta” i zadanie
  „Przygotuj zestaw”. Zapis szablonu listy zadań zmienia pozycje w miejscu (id) —
  przeliczenie terminów nie dubluje zadań i nie otwiera zrobionych.
- Powód odejścia tylko ze słownika. Obok jest krótka notatka organizacyjna
  (`exit_note`, do 500 znaków) widoczna Kadrom i przełożonemu, z podpowiedzią
  „Bez informacji o zdrowiu” — wolnego tekstu powodu z Compassa
  (`exit_reason_detail`, ankieta) nie importujemy.
- Lista osób dla Compassa: `GET /api/integrations/compass/roster` (zakres
  `people_roster:read`) — bez stawek, premii, nieobecności, powodu odejścia
  i telefonu. Osoby, które odeszły, zostają ze statusem `exited`; pusta lista to
  awaria (503), nie „wszyscy odeszli”. Przy włączonym module `lifecycle` przepływ
  `compass_lifecycle` (NEXUS ciągnął roster Compassa) zwraca
  `superseded_by_hr_lifecycle`.
