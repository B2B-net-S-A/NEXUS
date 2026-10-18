# Runbook przełączenia z Compassa na „Ludzi w NEXUSIE” (17.10.2026)

Moduły wchodzą na produkcję „ciemne” (`app_settings['hr_modules']` puste, M365
`off`, pętle bez pracy) i są włączane bez kolejnych wdrożeń. Kolejność kroków
ma znaczenie: **najpierw Compass przestaje pisać, potem NEXUS zaczyna**. Dwa
systemy piszące naraz w te same skrzynki albo tę samą kartotekę to jedyny
scenariusz, którego nie da się łatwo odkręcić.

Zmienne środowiskowe NEXUSA zmienia wyłącznie workflow „Coolify set env”
(nazwy niżej, wartości nigdy w repo ani w logach). Zmienne Compassa — vault
Coolify Compassa + restart (nie wdrożenie).

## Warunek wstępny: dane, potem włączenie programu (Artur 18.10.2026)

Cały program stoi za `HR_PROGRAM_ENABLED=false` — nikt, także admin, go nie
widzi. Nie włączamy pustych modułów: najpierw dopracowane integracje i próba
generalna importu na kopii danych (kartoteki, urlopy, timesheety, płace, karty
technologiczne, sprawy, sprzęt z arkuszem kontrolnym recepcji, wzory umów od
Kadr), porównanie z Compassem i OK Artura. Dopiero potem `HR_PROGRAM_ENABLED=true`
przez „Coolify set env” — moduły dalej są wyłączone przełącznikami, admin widzi
ekrany do importu, a kroki niżej włączają je po kolei. Krok z kontem serwisowym
dla Compassa (`people_roster:read`) wymaga już włączonego programu — wcześniej
tego zakresu nie ma w pickerze.

## 0. Przed pierwszym wieczorem (nie blokuje wdrożenia)

| Kto | Co |
|---|---|
| Admin Azure | **Zrobione 18.10.2026.** Aplikacja „NEXUS Kadry” ma w Entra wyłącznie `User.Read.All` (odświeżanie profili). Poczta i kalendarz (`MailboxSettings.ReadWrite`, `Calendars.ReadWrite`, `Mail.Read`, `Mail.Send`) idą WYŁĄCZNIE przez Exchange RBAC for Applications, zawężony zakresem „NEXUS Kadry - zakres” do grupy „NEXUS Kadry - skrzynki” (`nexus-kadry-skrzynki@b2bnetwork.pl`). Nie dodawać tych uprawnień w Entra — działałyby na całą firmę. Kolejne skrzynki = `Add-DistributionGroupMember` do tej grupy (wieczór przełączenia). Intune: `DeviceManagementManagedDevices.Read.All` — osobno, za zgodą. |
| Admin NEXUSA | **Zrobione 18.10.2026** przez „Coolify set env”: `HR_M365_CLIENT_ID`, `HR_M365_CLIENT_SECRET` (`value_from_secret`), `HR_M365_CLIENT_SECRET_EXPIRES_ON` (data RRRR-MM-DD — przy każdej rotacji; nazwa zawiera „SECRET”, więc też przez sekret repo o tej samej nazwie), `HR_M365_MAILBOX_ALLOWLIST` (jedna skrzynka testowa — pusta lista = WSZYSTKIE skrzynki, nie czyścić), `ADMIN_CASES_MAILBOX`, `HR_M365_MODE=off`, `HR_PROGRAM_ENABLED=false`, `ADMIN_CASES_MAIL_INGEST_ENABLED=false`. Zmienne wchodzą do kontenera dopiero przy wdrożeniu (zwykłe „Deploy”, nie `redeploy=true`). |
| Admin NEXUSA | Konto serwisowe dla Compassa z zakresem `people_roster:read` (Ustawienia → konta serwisowe); klucz trafia do vaulta Compassa jako `NEXUS_ROSTER_API_KEY`, adres `/api/integrations/compass/roster` jako `NEXUS_ROSTER_URL`. Dla ATLASA klucz z `sales_signals:read` (+ `:write` do zwrotu statusów). |
| Recepcja | Usunąć klucz BitLocker i kody PUK z plików recepcji; przejrzeć arkusz kontrolny importu sprzętu. |
| Kadry | Dni wolne firmy na 2026–2027, zasada przeniesienia urlopu, kto ma obowiązek timesheetu. |
| Delivery | „Sprzęt od nas / od klienta” u klientów z konsultantami (`clients.equipment_provider`). |

Sprawdzenie po wdrożeniu PR-a: `/api/health` → `version` = SHA z maina; deep
health zna nowe tabele; sondy `hr_m365`, `admin_cases_mail`, `hr_jobs`,
`equipment_intune` = `disabled`.

### Testy przed przełączeniem (18.10.2026)

- **Symulacja M365** (lokalnie, fikcyjny urlop B2B z zastępcą): autoodpowiedź
  i wydarzenie dzień przed urlopem, przekierowanie dopiero od pierwszego dnia,
  czas ściany `Europe/Warsaw` (koniec wyłączny — dzień po ostatnim), ponowienie
  przebiegu bez nowych operacji. Ponowne zaplanowanie tego samego wniosku
  dokłada operację przekierowania z nową rewizją — w skrzynce aktualizuje tę
  samą regułę (potwierdzone na żywo).
- **Test na żywo na jednej skrzynce** (bez wniosku w bazie, te same
  budowniczowie żądań co wykonawca kolejki): autoodpowiedź z harmonogramem
  i znacznikiem, wydarzenie „Poza biurem” (drugi POST z tym samym
  `transactionId` nie tworzy duplikatu), reguła przekierowania z wyjątkiem
  nadawców z domeny firmy (ponowienie = PATCH tej samej reguły); po teście stan
  skrzynki identyczny jak przed.
- **Próba generalna importu** (paczka Compassa z 18.10 na lokalnej kopii bazy
  NEXUSA: struktura z produkcji, dane kont/klientów/kontraktów, id kandydatów;
  wynik w raporcie sesji): przebieg na sucho = zapis, drugi zapis tej samej
  paczki = same „bez zmian” (0 zapisów). Zgodne ze źródłem: 45 kartotek, 212
  wniosków (te same statusy), 28 676,75 h w 0 rozbieżnych miesiącach, 104
  stawki, 246 premii, 611 spraw, 0 duplikatów. Do decyzji Kadr przed
  importem na produkcji:
  - suma dni urlopu w NEXUSIE jest większa, bo NEXUS zapisuje każdy dzień
    nieobecności (opieka, odbiór dnia, bezpłatny), a Compass liczył w polach
    dni tylko pulę; 10 wniosków urlopowych ma w Compassie puste pola dni —
    u dwóch osób na UoP saldo „pozostało” w NEXUSIE jest niższe (o 14 i o 8
    dni) — Kadry potwierdzają, które jest prawdziwe;
  - jedna osoba z Compassa nie ma konta w NEXUSIE (dwóch konsultantów
    zostaje w Akademii — tak ma być);
  - mapa technologiczna: 166 kart trafia bez powiązania z kontraktem
    (kontraktorzy Compassa nie są połączeni z NEXUSEM), 135 technologii spoza
    słownika do przejrzenia.

## 1. Fala 1 — kartoteka i urlopy (sobota 24.10.2026, rezerwa wt 27.10 po 19:00)

Stan przed falą (18.10.2026, tryb cienia): `HR_PROGRAM_ENABLED=true`, moduły HR
wyłączone poza `equipment`, `HR_LOOPS_ENABLED=false`, `HR_M365_MODE=off`, lista
skrzynek = jedna testowa, kolejka `hr_m365_operations` pusta, źródło dostępności
`compass` przy `COMPASS_AVAILABILITY_ENABLED` nieustawionym (zastępstwa nie widzą dziś
żadnych urlopów), `COMPASS_WORKDAYS_ENABLED=true`, 0 dni wolnych firmy. Kartoteki,
wnioski i raporty godzin z Compassa wgrane 18.10. Kartoteki prowadzi od 18.10 NEXUS
(przełożonych ustawił Artur) — import `profiles` nadpisałby przełożonych, więc fala 1
importuje tylko `leave` (i `time` jako archiwum; czas pracy zostaje w Compassie do 1.11).
Opieka, sprawy administracja@ (skrzynka jest na home.pl, NEXUS czyta tylko M365) i płace
to osobne fale.

**Aktualizacja 18.10.2026 ok. 19:30 — Artur: „przełączenie teraz”.** Zrobione
o 19:00: K2 (Compass `HR_MOVED_TO_NEXUS=people,leave` + `NEXUS_APP_URL`), K4–K5
(ponowny import `leave`/`time` = 0 zmian), K6 (moduły `people`, `leave`) i mail
„Czas i ludzie” włączony dla firmy. Źródło dostępności przełączone i cofnięte na
`compass`: `availability_loop` startuje tylko przy `COMPASS_AVAILABILITY_ENABLED`
albo `HR_LOOPS_ENABLED`, więc K11 idzie dopiero po K7. Zostały, w tej kolejności:
K7 → K11 → K8 → K9 (→ K10, gdy jest drugi akceptujący) → K12 (≥ 2 h po dopisaniu
skrzynek do grupy) → K13 → K14, a pełne uzgadnianie M365 następnego dnia o 07:00.
Wdrożenia K7, K9 i K12 muszą się zmieścić w oknie (pon 19.10 przed 07:00 albo od
19:00). Przy włączonym mailu „Czas i ludzie” powiadomienia z pętli (zadania sprzętu,
przypomnienia o składkach) idą też mailem — 18.10 żadna pętla nie miała adresata
(0 zadań sprzętu, 0 zwrotów i startów w 14 dni, 0 osób w oknie składek).

Każda zmiana zmiennej NEXUSA wchodzi dopiero z wdrożeniem, a Deploy wdraża cały HEAD
maina — zmienne łączymy w trzy wdrożenia (K7, K9, K12). Compass po zmianie zmiennej
restartuje się sam (`redeploy=true`). Wartości z adresami e-mail nigdy jako jawne `value`
w „Coolify set env” (wejścia runa są publiczne) — tylko `value_from_secret` albo pusta.

**Warunki wejścia (piątek 16:00, decyzja Artura):** odpowiedzi Kadr (salda dwóch osób,
osoba bez konta, dni wolne firmy; „kto składa raport godzin” potrzebne dopiero na 1.11),
Compass z trybem archiwum na produkcji, ogłoszenie dla zespołu wysłane, skrzynki z pliku
fali 1 w grupie „NEXUS Kadry - skrzynki” (Codex, piątek, kontrola po 2 h), zielony
`/api/health/deep`, drugi akceptujący w sobotę (wniosek testowy Artura), brak scaleń do
maina w trakcie przełączenia.

| Krok | Co | Kontrola | Wycofanie |
|---|---|---|---|
| K0 | Stan wejścia: health, zmienne, moduły, M365 (`mode=off`, lista 1, kolejka 0), Compass `/api/health` | wszystko jak wyżej | — |
| K1 | Dni wolne firmy od Kadr (Ustawienia → Kadry, admin) — **przed** importem, bo import liczy dni wniosków kalendarzem firmy | lista dni na ekranie | usunięcie dnia |
| K2 | Compass: `NEXUS_APP_URL` (bez restartu), potem `HR_MOVED_TO_NEXUS=people,leave` (restart). Baner archiwum, odmowa zapisu, `oof-reconcile` pomija pracę. `HR_EXPORTS_OFF` zostaje puste | baner z linkiem do NEXUSA na urlopach i kartotece, próba wniosku = odmowa | `HR_MOVED_TO_NEXUS=` (pusta) |
| K3 | Eksport paczki z Compassa (`--tables profiles,leave_requests,timesheets,timesheet_entries,attendance_records,timesheet_role_defaults,timesheet_user_templates`) — `profiles` tylko do mapowania osób | liczby wierszy, SHA-256 | skasować plik |
| K4 | Import na sucho: `scripts/hr_compass_import.py --module leave`, potem `--module time` (kontener backendu). **Nigdy `--module profiles`**; na ekranie „Import z Compassa” zaznaczyć wyłącznie `leave` i `time`. Raport do Artura | liczby nowe / zmienione / bez zmian / do wyjaśnienia | nic (sucho cofa się samo) |
| K5 | Zapis po OK Artura (`--apply <batch_id>` leave, potem time), drugi przebieg na sucho = same „bez zmian”, paczka skasowana (kontener, host, dysk). Korekta sald dwóch osób w kartotece wg Kadr | 0 zmian w drugim przebiegu | Compass jest źródłem — poprawka w Compassie i ponowny import |
| K6 | Moduły `people` i `leave` (Ustawienia → Kadry → Moduły; `PUT /api/hr/admin/modules` scala, `equipment` zostaje). Mail „Czas i ludzie” (Ustawienia → Powiadomienia → Maile) wg decyzji Artura | `/api/hr/config` zwykłej osoby: `open_modules.people/leave = true`, saldo 200 | moduły `false` + krok K2 wstecz; wnioski założone w NEXUSIE przenieść ręcznie |
| K7 | `HR_LOOPS_ENABLED=true` + `HR_M365_MODE=simulate` → Deploy | zmienne w kontenerze, sonda `hr_jobs` zdrowa, M365 `simulate`, operacje tylko `simulated` | `HR_LOOPS_ENABLED=false`, `HR_M365_MODE=off` → Deploy |
| K8 | Symulacja: karta M365 pokazuje żądania dla trwających urlopów; żadnej operacji `done` | `GET /api/hr/admin/m365/operations` | jak K7 |
| K9 | `HR_M365_MODE=live` → Deploy (lista dalej = jedna skrzynka) | M365 `live`, lista 1 | `HR_M365_MODE=simulate` albo `off` → Deploy |
| K10 | Wniosek testowy Artura (np. 28–29.12, bez przekierowania), akceptuje druga osoba → w Outlooku autoodpowiedź z harmonogramem i wydarzenie „Poza biurem”; anulowanie wniosku zdejmuje oba | operacje `done`, Outlook przed/po | `HR_M365_MODE=off` → Deploy; ręcznie zdjąć `NEXUS · …` |
| K11 | Źródło dostępności `local` (Ustawienia → Kadry, `PUT /api/hr/admin/availability-source`) | sonda `workforce_availability` zdrowa, zastępstwa widzą trwające urlopy | `{"source":"compass"}` |
| K12 | Plik skrzynek = grupa (ponowny skrypt, różnica 0) → `HR_M365_MAILBOX_ALLOWLIST=` (pusta = wszystkie skrzynki, zakres i tak trzyma grupa) + `COMPASS_WORKDAYS_ENABLED=false` → Deploy; potem „Uzgodnij teraz” | lista 0, błędy skrzynek 0 (403 = brak w grupie), przejęte reguły Compassa, wnioski `outlook_oof` przejrzane | lista z sekretu z jedną skrzynką albo `HR_M365_MODE=off` → Deploy |
| K13 | Compass `HR_EXPORTS_OFF=people,leave` — dopiero po K12, bo eksport dni roboczych należy do `leave` i bez `COMPASS_WORKDAYS_ENABLED=false` synchronizacja dostałaby 410 | sonda `compass_workdays` nie czerwona | `HR_EXPORTS_OFF=` (pusta) |
| K14 | Kontrola końcowa: Chrome jako admin (katalog, Struktura, „Mój czas”, Akceptacje, Ustawienia → Kadry, 1280 × 720), zwykła osoba przez API (token w kontenerze) i zrzut od jednej osoby z zespołu; `/api/health/deep` | zrzuty, kody 200/404 jak w scenariuszu | — |
| N1 | Niedziela 07:30: pierwszy pełny dzienny przebieg uzgadniania (sobotni dzień zajęła symulacja) i odczyt przełożonych z M365 | ostatnie uzgodnienie = 25.10, błędy 0, `failed` 0 | jak K12 |

**Co ruszy po `HR_LOOPS_ENABLED=true` (sprawdzone w kodzie 18.10, moduły `people`,
`leave`, `equipment`):** `hr_workdays` (do K11 nic, potem dni robocze ze źródłem
`nexus` co 6 h), `hr_m365_outbox` i `hr_m365_reconcile` (tylko przy `HR_M365_MODE≠off`;
zapisy w skrzynkach z listy), `hr_m365_daily` (alarm sekretu — termin 2028-10-18, nic;
od 06:00 odczyt przełożonych z M365 do `m365_manager_upn`), `hr_lifecycle` (moduł
wyłączony — tylko sprzątanie wygasłych paczek importu i przypomnienie o końcu zwolnienia
ze składek; 18.10: 0 osób w oknie), `hr_contract_hooks` (zadania sprzętu dla kontraktów
w 14 dni: starty tylko u klientów „sprzęt od nas”, końce tylko z wydanym sprzętem),
`equipment_reminders` (od 07:00 powiadomienie w aplikacji dla „Sprzętu”). Bez efektu
(moduł albo wyłącznik): `hr_timesheet_reminder`, `care_reminders`,
`care_announcements_send`, `hr_bonus_proposals`, `admin_cases_mail_ingest`. Nie
startują: `ksef_fetch`, `sales_ksef_fetch`, `hr_agreements_signing`,
`equipment_intune_sync`. Na zewnątrz nie wychodzi nic poza zapisami w skrzynkach
M365; maile do zespołu tylko przy włączonym rodzaju „Czas i ludzie”.

**Symulacja zajmuje dzień uzgadniania.** Pierwszy przebieg po K7 (po 07:00) rezerwuje
dzień w trybie `simulate`, a klucze `set_oof` uzgadniania są dzienne — w sobotę żywe
autoodpowiedzi trwających urlopów nie wejdą z uzgadniania (te osoby mają autoodpowiedzi
Compassa, które uzgadnianie przejmuje). Pełny żywy przebieg = niedziela 07:00 (N1).
Wniosek testowy zakładamy dopiero po K9 — operacje z akceptacji wykonane w `simulate`
zostają `simulated` i w `live` nie wracają.

Osobno, po fali 1: konto serwisowe dla Compassa (`people_roster:read`) i moduł
`lifecycle` (§ 4), sprzęt z importu plików recepcji (zrobione 18.10), ATLAS (§ 1 dawny
krok 9 — za zgodą Artura, potem w Compassie `HR_EXPORTS_OFF` += `care`).

## 2. Czas pracy — od 1. dnia następnego miesiąca

Poprzedni miesiąc domyka Compass do 5. dnia. Potem `HR_MOVED_TO_NEXUS` += `time`,
import modułu `time` (sucho → zapis), moduł `time` w NEXUSIE włączony.

## 3. Płace — po miesiącu liczonym równolegle

Pierwszy miesiąc liczony w obu systemach i porównany per osoba (różnice
wyjaśnione na piśmie). Od następnego rozliczenia `HR_MOVED_TO_NEXUS` += `payroll`,
moduł `payroll` w NEXUSIE włączony.

## 4. Wejście i odejście, lista osób dla Compassa

Moduł `lifecycle` włączony → trasa `/api/integrations/compass/roster` zaczyna
oddawać listę (pusta lista = 503, nigdy „wszyscy odeszli”). W Compassie
`HR_MOVED_TO_NEXUS` += `lifecycle` i cron `nexus-roster-sync` (nie wyłącza
admina, nie robi masowego `exited`). W NEXUSIE `COMPASS_LIFECYCLE_ENABLED=false`.

## 5. Compass = Akademia

Po tygodniu bez błędów: crony przeniesionych modułów wyłączone przez
`Coolify Ops cron-disable-task` (nigdy `cron-enable`), wszystkie eksporty
w `HR_EXPORTS_OFF`. Tabel Compassa nie kasujemy (wyzwalacz
`block_employment_reversal_after_exit` zostaje — odmowa liczona w cronie
jako `blocked_by_trigger`).

## 6. Wycofanie

Do kroku 5 Compass ma dane i kod: moduł wraca usunięciem go z
`HR_MOVED_TO_NEXUS` (i `HR_EXPORTS_OFF`), wyłączeniem modułu w NEXUSIE,
`HR_M365_MODE=off`, źródłem dostępności `compass` i ponownym
`COMPASS_*_ENABLED=true`. Zmiany zrobione w NEXUSIE w międzyczasie trzeba
przenieść ręcznie (lista z `hr_audit_events` od chwili włączenia). Compass
nie zna znaczników NEXUSA (`NEXUS · …`) i ich nie sprząta — przed powrotem
M365 do Compassa zostaw NEXUS w `live` do końca bieżących urlopów albo zdejmij
autoodpowiedzi i reguły `NEXUS · …` ręcznie.

## Rozliczenia zespołu (etap 4, osobny PR po wdrożeniu „Ludzi”)

1. Po wdrożeniu: `/api/health` = SHA, sonda `hr_ksef` = `disabled`, moduł `settlements` wyłączony.
2. Biała lista: `WHITE_LIST_MODE=test` → sprawdzenie NIP-u spółki w „Danych do rozliczeń” → `live`.
3. KSeF: najpierw środowisko TEST MF (certyfikat testowy, token z `InvoiceRead`, `KSEF_MODE=test`,
   `KSEF_CONTEXT_NIP`, `KSEF_TOKEN` przez „Coolify set env” z `value_from_secret`), „Pobierz teraz”,
   potem token produkcyjny spółki i `KSEF_MODE=prod`.
4. Płace uzupełniają dane do rozliczeń osób (NIP, rachunek z wykazu, identyfikator w Symfonii),
   ustawienia płatności i słowniki Symfonii; włączenie modułu `settlements`.
5. Pierwszy miesiąc: rozliczenia w NEXUSIE obok dotychczasowego trybu, paczka dla Symfonii
   zaimportowana próbnie przez Płace; paczka przelewów zostaje wyłączona do testu w banku.
