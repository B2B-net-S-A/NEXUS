# Runbook przełączenia z Compassa na „Ludzi w NEXUSIE” (17.10.2026)

Moduły wchodzą na produkcję „ciemne” (`app_settings['hr_modules']` puste, M365
`off`, pętle bez pracy) i są włączane bez kolejnych wdrożeń. Kolejność kroków
ma znaczenie: **najpierw Compass przestaje pisać, potem NEXUS zaczyna**. Dwa
systemy piszące naraz w te same skrzynki albo tę samą kartotekę to jedyny
scenariusz, którego nie da się łatwo odkręcić.

Zmienne środowiskowe NEXUSA zmienia wyłącznie workflow „Coolify set env”
(nazwy niżej, wartości nigdy w repo ani w logach). Zmienne Compassa — vault
Coolify Compassa + restart (nie wdrożenie).

## 0. Przed pierwszym wieczorem (nie blokuje wdrożenia)

| Kto | Co |
|---|---|
| Admin Azure | Rejestracja aplikacji „NEXUS Kadry”: `MailboxSettings.ReadWrite`, `Calendars.ReadWrite`, `Mail.Send`, `User.Read.All` (odświeżanie profili), dostęp do skrzynki administracja@ (RBAC for Applications zawężony do skrzynek z listy). Intune: `DeviceManagementManagedDevices.Read.All` — osobno, za zgodą. |
| Admin NEXUSA | `HR_M365_CLIENT_ID`, `HR_M365_CLIENT_SECRET`, data wygaśnięcia sekretu, `HR_M365_MAILBOX_ALLOWLIST` (jedna skrzynka testowa), `ADMIN_CASES_MAILBOX` przez „Coolify set env”. `HR_M365_MODE` zostaje `off`. |
| Admin NEXUSA | Konto serwisowe dla Compassa z zakresem `people_roster:read` (Ustawienia → konta serwisowe); klucz trafia do vaulta Compassa jako `NEXUS_ROSTER_API_KEY`, adres `/api/integrations/compass/roster` jako `NEXUS_ROSTER_URL`. Dla ATLASA klucz z `sales_signals:read` (+ `:write` do zwrotu statusów). |
| Recepcja | Usunąć klucz BitLocker i kody PUK z plików recepcji; przejrzeć arkusz kontrolny importu sprzętu. |
| Kadry | Dni wolne firmy na 2026–2027, zasada przeniesienia urlopu, kto ma obowiązek timesheetu. |
| Delivery | „Sprzęt od nas / od klienta” u klientów z konsultantami (`clients.equipment_provider`). |

Sprawdzenie po wdrożeniu PR-a: `/api/health` → `version` = SHA z maina; deep
health zna nowe tabele; sondy `hr_m365`, `admin_cases_mail`, `hr_jobs`,
`equipment_intune` = `disabled`.

## 1. Wieczór A — kartoteka, urlopy, opieka, sprawy, sprzęt

1. **Compass przestaje pisać:** `HR_MOVED_TO_NEXUS=people,leave,care,cases`
   (baner archiwum, odmowa zapisu w akcjach, crony pomijają pracę, w tym
   `oof-reconcile`). `HR_EXPORTS_OFF` zostaje PUSTE — eksporty dostępności
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
   `admin_cases_mail` → healthy po pierwszym przebiegu).
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
