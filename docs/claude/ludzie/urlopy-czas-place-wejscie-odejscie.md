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

### Forma współpracy: słowa i zgłoszenie zamiast wniosku (etap 2, D1, D4–D9, 17.10.2026)

Prawie cała firma jest na B2B albo zleceniu, umowa o pracę pojedynczo. Od
08.07.2026 PIP sam stwierdza stosunek pracy, a „wniosek urlopowy” akceptowany
przez „przełożonego” to sygnał podporządkowania — dlatego forma z kartoteki
decyduje o słowach i o przebiegu nieobecności.

- **Jeden słownik** (D4): `app/services/hr/employment_terms.py`
  (`EMPLOYMENT_TERMS` + zdania tylko backendu w `BACKEND_TERMS`) i lustro słowo
  w słowo `frontend/src/lib/hr-employment-terms.ts` (strażnik
  `tests/test_hr_employment_terms_mirror.py`). UoP: urlop, wniosek, przełożony,
  ewidencja czasu pracy, lista płac; B2B: przerwa w świadczeniu usług,
  zgłoszenie, koordynator, raport godzin, faktura; zlecenie: nieobecność,
  zgłoszenie, koordynator, potwierdzenie godzin (art. 8b), rachunek. Brak formy
  = jak UoP. Nie pisz „urlop”, „wniosek”, „przełożony” na sztywno w tekstach,
  które widzi osoba na B2B albo zleceniu — bierz słowo ze słownika (ekrany,
  powiadomienia urlopów i raportu godzin, PDF raportu, przypomnienie 1.–5.).
  Rodzaj „vacation” osoby na B2B/zleceniu ma etykietę „Przerwa w świadczeniu
  usług” / „Nieobecność” (`leave_policy.type_label`). Autoodpowiedź M365 i
  wydarzenie w kalendarzu mówią „poza biurem” — słowa „urlop” tam nie ma.
- **Przełożony / koordynator = jedna funkcja** `recipients.supervisor_of`
  (urlop, czas, zadania; 17.10.2026): przełożony z kartoteki z aktywnym kontem
  i statusem innym niż `exited` → head pionu → Kadry (bez adminów). Head pionu
  akceptuje wnioski, timesheety i wpisy za osoby swojego pionu bez żywego
  przełożonego. Etykieta „akceptuje” w podglądzie wniosku i w „Moim miesiącu”
  liczy się tą samą regułą — nie dopisuj drugiej.
- **Kto odszedł, nie ma podwładnych** (17.10.2026): kartoteka `exited` albo
  wyłączone konto = brak zespołu w każdym zakresie („Mój zespół”, akceptacje,
  kolejki, pełna kartoteka — `people.can_supervise` w `direct_report_ids`), a
  jako nowy przełożony taka osoba to 422.
- **Zgłoszenie zamiast wniosku** (D5, Artur 17.10): na B2B i zleceniu własna
  nieobecność jest od razu `approved` bez decydującego (`decided_by` NULL),
  M365 i godziny od razu. Informacja (`hr_absence_reported`, bez rodzaju) idzie
  do koordynatora: przełożony z kartoteki → head pionu
  (`app_settings['hr_divisions']`) → Kadry; zastępca nieobecnego przełożonego
  do wiadomości. Zgłoszenia nie trafiają do kolejki wniosków ani do licznika
  „Akceptacji”; w „Akceptacjach” są w sekcji „do wiadomości”
  (`reported` w `GET /approvals/pending`) z „Zgłoś kolizję”.
- Zgłoszenie na dzień z miesiąca, którego raport godzin jest wysłany albo
  przyjęty = 409 (podgląd: `blocking_reason`), bo wchodzi bez niczyjej decyzji
  — najpierw koordynator cofa raport do szkicu (17.10.2026; UoP bez zmian).
- Akceptuj/odrzuć zgłoszenie = 409 (`REPORT_NOT_DECIDED`); czekający wniosek
  osoby, której forma zmieniła się z UoP po złożeniu, dalej można rozstrzygnąć.
  Anulowanie zgłoszenia przez koordynatora = 403 (to odrzucenie pod inną
  nazwą) — anuluje sama osoba (przed pierwszym dniem) albo Kadry/admin.
- **Kolizja**: `POST /api/hr/leave/{id}/conflict` (`{note}` 3–1000 znaków,
  bramka akceptujących + head pionu osoby bez przełożonego) → typ
  `hr_leave_conflict` do osoby (link `/my-time?tab=leave`), ślad
  `leave_conflict_reported` z notatką; zgłoszenie zostaje zatwierdzone. Wiersz
  wniosku niesie ostatnią kolizję (`conflict`), osoba widzi ją przy terminie.
  Mail ma zdanie typu, bez notatki (wolny tekst). Kolizja tylko dla
  trwających i przyszłych zgłoszeń B2B/zlecenia (UoP, minione, zamknięte = 409).
- Import z Compassa: oczekujący wniosek osoby na B2B/zleceniu wchodzi jako
  przyjęte zgłoszenie (`decided_at` = data złożenia), raport liczy je w
  `extra.contractor_pending_reported`.
- **Pula** (D6): na zleceniu nie ma puli płatnych dni — `PUT …/entitlements`
  z dniami > 0 dla zlecenia = 422; B2B tylko gdy umowa ją ma. Wiersz puli
  z czasu innej formy (UoP → zlecenie) zostaje jako historia, ale plan dni,
  podgląd, saldo, most do godzin i import liczą zlecenie jak bez puli
  (`leave_policy.pool_applies`). **Staż** (D9):
  `leave_seniority_years` + `zus_certificate_received_on` w kartotece (tylko
  UoP); `suggested_entitlement_days` (20 / 26 od 10 lat) w kartotece i w
  odpowiedzi zapisu puli — tylko podpowiedź, pulę zatwierdzają Kadry.
- **Uczeń/student na zleceniu** (D8): `student_contribution_exempt` +
  `contribution_exempt_until` (CHECK: data tylko przy znaczniku; znacznik tylko
  na zleceniu — serwis, zmiana formy go zdejmuje). Bez daty urodzenia: Kadry
  wpisują wcześniejszą z dat (koniec statusu albo dzień przed 26. urodzinami).
  `student_reminders.student_contribution_reminders` (z pętli `hr_lifecycle`,
  od 8:00) od 30 dni przed datą do niej włącznie: `hr_lifecycle_task` do Płac
  i Kadr, raz na osobę i datę (`hr_job_runs` `hr_student_contribution_reminder`,
  `u<id>:<data>`). Plakietka „składki od MM.RRRR” w Strukturze i „Moim zespole”.

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
- **Odczyt bez zapisu** (17.10.2026): `GET` „Mojego miesiąca” niczego nie
  zapisuje. Bez timesheetu widok pokazuje szkic wirtualny (z auto-wpisami
  płatnego urlopu), a wiersz `timesheets` zakłada pierwszy zapis
  (`time_entries.open_draft`: wpis, „Wypełnij miesiąc”, wysyłka). Wysyłka
  w zamkniętym miesiącu bez timesheetu = 409.
- **Potwierdzenie godzin na zleceniu** (D7, art. 8b/8c): przyjęty raport osoby
  na zleceniu po terminie wypłaty (koniec miesiąca następnego) zostaje bez zmian
  3 lata (`time_retention.py`): cofnięcie przyjęcia i usunięcie wpisu = 409,
  zgłoszona później nieobecność nie zdejmuje godzin (miesiąc jak zamknięty
  w płacach — ostrzeżenie osobie, powiadomienie Płacom). Przed terminem
  wypłaty to zwykła korekta. Decyduje forma zapisana przy akceptacji
  (`timesheets.employment_type`), nie obecna; stare wiersze bez niej — obecna.
  Wiersza `timesheets` nie kasuje żadna ścieżka (`user_id ON DELETE RESTRICT`,
  odejście i wyłączenie konta nie ruszają godzin).
- PDF: tytuł z formy — „Ewidencja czasu pracy”, „Raport godzin”, „Potwierdzenie
  liczby godzin” z dopiskiem o art. 8b; role „Pracownik/Wykonawca/Zleceniobiorca”.

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
  Termin premii z placementu = start kontraktu + 21 dni roboczych firmy (święta
  ustawowe i dni wolne firmy — ten sam kalendarz co urlop, decyzja 17.10.2026);
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
  wejścia samych podwładnych (`case.manager_user_id`) przekazanie nie przepina.
- **Przejmujący = obecny przełożony** (17.10.2026): zmiana przełożonego w
  kartotece (edycja, „Struktura”, przekazanie podwładnych) przechodzi na żywą
  sprawę odejścia, gdy sprawa szła za kartoteką, a domyślny przejmujący idzie za
  nim (`lifecycle_service.follow_profile_manager`); przełożony i przejmujący
  wskazani w sprawie ręcznie zostają, zdjęcie przełożonego zostawia przełożonego
  sprawy.
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

### Ścieżki i wejście konsultanta (etap 3, O1, O4–O6, O11, 17.10.2026)

- **Ścieżki zamiast list** (O1): szablon ma odbiorców (`audience`: `team` —
  zespół wewnętrzny z kontem, `consultant` — konsultant u klienta bez konta)
  i wersję. Pozycja: termin w dniach roboczych, wykonawca (rola: przełożony,
  Kadry, recepcja, IT, osoba, opiekun kontraktu `care_owner`, DL klienta
  `delivery_lead`, administracja `administration` = uprawnienie „Sprawy”),
  opis, „wymagane”, „z plikiem”, warunki (`employment_types`, `equipment`
  `ours`/`client` z `clients.equipment_provider`, `student`) i stały klucz
  (`key`). Warunek zamiast osobnej ścieżki: pozycja pojawia się tylko tam,
  gdzie pasuje. Sprzęt nieznany (klient bez ustawienia) = bez pozycji sprzętu
  (jak hak Sprzętu); student nieznany (konsultant nie ma kartoteki) = pozycja
  zostaje z dopiskiem „jeśli nie jest studentem, pomiń”.
- **Kto zmienia** (O4): Kadry — `team`, head back office
  (`structure.load_division_heads()['back_office']`) — `consultant`, admin —
  obie; każdy z nich widzi obie (`can_edit` w odpowiedzi). Odbiorców ani
  rodzaju ścieżki nie da się zmienić zapisem (422). Pozycji z kluczem nie da
  się usunąć (422) — czytają ją inne moduły (`welcome_mail` — mail powitalny,
  `equipment_kit`, `equipment_issue`).
- **Wersje** (O5): każdy zapis = wersja + 1, nowa pozycja pamięta
  `added_in_version`, sprawa — `template_version`. Nowe sprawy dostają
  bieżącą wersję, trwające zostają na swojej; „Dociągnij do trwających”
  (`POST /templates/{id}/catch-up`) tylko DOPISUJE brakujące pozycje nowszej
  wersji, które pasują do warunków sprawy. Zmiana daty sprawy przelicza ją do
  bieżącej wersji (jak dotąd: terminy otwartych, nowe pozycje, znikają otwarte
  spoza ścieżki).
- **Wejście konsultanta** (`lifecycle_entry.py`): sprawa `audience =
  'consultant'` przy kontrakcie (`contract_id` bez FK, klucz
  `contract:{id}:entry`), bez konta osoby. Zakłada ją hak startu kontraktu
  i przegląd nadchodzących startów (`contract_hooks`, krok `lifecycle` PRZED
  sprawą administracja@); kontrakt ze startem w przeszłości — tylko ręcznie
  („Załóż listę wejścia”). Lista = ścieżka „Konsultant u klienta” + pakiet
  klienta (`client_pack.pack_tasks`: dokumenty, dostępy, odbiór od klienta;
  awaria pakietu nie blokuje wejścia) + pozycje z warunkiem formy. Zestaw
  i wydanie sprzętu są w ścieżce (warunek „sprzęt od nas”), opis zestawu
  z `load_pack(...).equipment_ours`. Wykonawcy: opiekun jedną regułą opieki
  (`care.access.effective_owners`, bez niego head back office), DL —
  rekrutacji, a bez niego główny DL klienta (bez DL — opiekun); zadania
  „osoby” i „przełożonego” odhacza opiekun (O6). Zmiana daty startu kontraktu
  przelicza terminy otwartych zadań; unieważnienie anuluje wejście, trwałe
  usunięcie je kasuje.
- **Jedna lista zamiast trzech**: sprawa „Wejście konsultanta” w Sprawach
  powstaje dalej, ale `lifecycle_case_id` wskazuje wejście, a checklista to
  zadania „Administracja” (odhaczenie w liście → checklista,
  `admin_cases.hooks.sync_entry_checklist`; w drugą stronę
  `sync_entry_tasks_from_checklist`). Zestaw sprzętu to zadanie recepcji
  `contract:{id}:start` z haka Sprzętu: lista pokazuje jego stan (`mirror`),
  odhacza się je tylko w Sprzęcie (409 na liście), bez dzwonka i bez „Moich
  zadań”. Administracja nie dostaje dzwonka (ma kartę sprawy).
- Stare `contract_onboarding_items`: przy włączonym module tylko do odczytu
  (POST/seed/PATCH/DELETE = 409), widoczne pod listą wejścia; wyłączony moduł
  = jak dotąd (zakładka pokazuje starą listę).
- Zakładka „Wejście” kontraktu: `GET /api/hr/lifecycle/contracts/{id}/entry`
  (sekcja Delivery + podgląd Delivery, DL tylko u swoich klientów), lista,
  kroki (przed startem / dzień startu / 2 tygodnie / do 30 dni), „Z czego to
  powstało”, mail powitalny (G2). Prowadzą (dopisanie pozycji, odhaczanie
  każdego zadania): opiekun, DL klienta, head back office, Kadry, admin.
  `complete_task_by_key(db, contract_id=…, key=…, actor_id=…)` z
  `lifecycle_service` odhacza pozycję z kluczem (mail powitalny).
- **Opieka w przekazaniu** (O11): szósty rodzaj pracy `care` — kontrakty
  odchodzącego opiekuna (bez końca i unieważnienia) i domyślne opieki klientów
  przechodzą na przejmującego (ślad `care.owner_set` /
  `care.default_owner_set` z `previous` i `reason: handover`); domyślnie
  przejmuje head back office, bez niego przełożony. DL przejmie opiekę tylko
  z wszystkimi tymi klientami w portfelu (`receiver_out_of_scope`).
- „Koniec projektu konsultanta” jest zasiany, ale sprawy końca projektu
  jeszcze nie powstają (zwrot sprzętu robi hak końca kontraktu jak dotąd).
