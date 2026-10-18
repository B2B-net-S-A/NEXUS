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

## 1. Wieczór A — kartoteka i urlopy (fala 1, 24.10.2026)

Stan przed wieczorem A (18.10.2026, tryb cienia): `HR_PROGRAM_ENABLED=true`,
wszystkie moduły HR wyłączone (ekrany widzi tylko admin), `HR_LOOPS_ENABLED=false`,
`HR_M365_MODE=off`; kartoteki, wnioski i raporty godzin z Compassa już wgrane.
Kartoteki prowadzi od 18.10 NEXUS (przełożonych ustawił Artur) — ponowny import
`profiles` nadpisałby przełożonych, więc wieczorem A importujemy tylko `leave`
(i `time` jako archiwum). Opieka, sprawy administracja@ (skrzynka jest na home.pl,
NEXUS czyta tylko M365) i sprzęt przechodzą osobno, każde ze swoim modułem.

1. **Compass przestaje pisać:** `HR_MOVED_TO_NEXUS=people,leave`
   (baner archiwum, odmowa zapisu w akcjach, crony pomijają pracę, w tym
   `oof-reconcile`). Od tej chwili wnioski z ręcznie ustawionej autoodpowiedzi
   w Outlooku zakłada NEXUS (krok 4 uzgadniania M365, `leave_outlook.py`) —
   dwa systemy robiące to samo założyłyby dwa wnioski. `HR_EXPORTS_OFF` zostaje PUSTE — eksporty dostępności
   i dni roboczych mają oddawać zamrożone dane, dopóki NEXUS nie przełączy źródła.
2. **Eksport paczki** (Compass, `scripts/export-nexus-bundle.mjs`, opis
   w `docs/nexus-bundle-v1.md` Compassa): plik poza repo, katalog `chmod 700`,
   na wyjściu tylko liczby wierszy i SHA-256.
3. **Import na sucho:** Ustawienia → „Import z Compassa” (`/settings/hr-import`,
   Kadry albo admin) albo `scripts/hr_compass_import.py --bundle … --module …`.
   Raport (same liczby: nowe / zmienione / bez zmian / do wyjaśnienia) idzie do
   Artura. Lista „bez konta” = osoby z Compassa bez użytkownika NEXUSA —
   decyzja per osoba (założyć konto, pominąć).
4. **Zapis po OK Artura** (tylko admin): ta sama partia (`bundle_sha256`),
   kolejność `profiles → leave → time → payroll → lifecycle → cases → care`.
   Drugi zapis tej samej paczki = same „bez zmian”. Po zapisie skasować plik
   paczki z dysku.
5. **M365 na jednej skrzynce:** `HR_M365_MODE=simulate` → panel M365
   w Ustawieniach → Kadry pokazuje żądania dla testowego urlopu → `live`
   z jedną skrzynką w `HR_M365_MAILBOX_ALLOWLIST` → sprawdzić w Outlooku
   autoodpowiedź i wydarzenie „Poza biurem” → wyczyścić listę (pusta lista
   w `live` = wszystkie skrzynki, opis zmiennej w `config.py`). Uzgadnianie
   07:00 przejmuje znacznik
   `compass-managed-oof-v1` i reguły `COMPASS · zastępstwo · {uuid}`.
6. **Źródło dostępności `local`:** Ustawienia → Kadry → „Źródło dostępności”
   (`PUT /api/hr/admin/availability-source`, tylko admin), potem
   `COMPASS_AVAILABILITY_ENABLED=false`, `COMPASS_WORKDAYS_ENABLED=false`.
   Health `workforce_availability` ma zostać zielone. Dopiero teraz w Compassie
   `HR_EXPORTS_OFF=people,leave`.
7. **Włączenie modułów:** Ustawienia → Kadry → moduły `people, leave, care,
   cases, equipment`. `ADMIN_CASES_MAIL_INGEST_ENABLED=true` (sonda
   `admin_cases_mail` → healthy po pierwszym przebiegu). Ustawienia →
   Powiadomienia → Maile: włączyć „Czas i ludzie” (domyślnie wyłączone jak każdy
   rodzaj; bez tego wnioski, L4 i zadania recepcji widać tylko w dymku
   i licznikach zakładek).
8. **Sprzęt:** import plików recepcji przez arkusz kontrolny (ekran „Sprzęt” →
   Import), pozycje „do wyjaśnienia” przegląda recepcja.
9. **ATLAS:** przepięcie na `/api/care/atlas/sales-signals` — tylko za zgodą
   Artura; potem w Compassie `HR_EXPORTS_OFF` += `care`.

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
