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
- Akceptacja urlopu usuwa godziny z dni urlopu w „Moim miesiącu” i przelicza
  sumę kontrolną (`time_hooks.on_leave_approved` / `on_leave_cancelled`).
- Powiadomienia i dzwonek zastępcy nie zdradzają rodzaju ani notatki (D6).

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
- Stawki z historią, obowiązują od 1. dnia miesiąca.
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
  Ponowne otwarcie tylko admin, z powodem.

## Wejście i odejście (`app/services/hr/lifecycle_*.py`, `handover.py`, `deactivation.py`)

- Prowadzą Kadry; przełożony widzi sprawę swojego człowieka; wykonawca odhacza
  swoje zadania. Terminy zadań w dniach roboczych firmy.
- Odejście: przekazanie pracy po 18:00 ostatniego dnia (cztery rodzaje pracy
  przechodzą istniejącymi ścieżkami zapisu — rekrutacje, DL rekrutacji, klienci
  DL, „Moi ludzie”), wyłączenie konta dzień później. Konto wyłącza wyłącznie
  sprawa odejścia (nie brak osoby na liście), raz na sprawę; admina nie wyłącza
  automat; przebieg z więcej niż limitem deaktywacji nie wyłącza nikogo.
- Powód odejścia tylko ze słownika — bez wolnego tekstu (mógłby nieść dane
  o zdrowiu).
- Lista osób dla Compassa: `GET /api/integrations/compass/roster` (zakres
  `people_roster:read`) — bez stawek, premii, nieobecności, powodu odejścia
  i telefonu. Osoby, które odeszły, zostają ze statusem `exited`; pusta lista to
  awaria (503), nie „wszyscy odeszli”. Przy włączonym module `lifecycle` przepływ
  `compass_lifecycle` (NEXUS ciągnął roster Compassa) zwraca
  `superseded_by_hr_lifecycle`.
