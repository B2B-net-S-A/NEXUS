# Rozliczenia: przypomnienia o brakującym raporcie godzin (RCP)
<!-- indeks: przypomnij, brak RCP, raport godzin, 3. 5. 7. dzień roboczy, opiekun w kopii, dzwonek opiekuna, bez adresata, client_settlement_reminders, settlement_report_missing, Start rozliczeń, wysyłka do konsultantów -->

Rekomendacja 4 z makiet panelu Finansów (zaakceptowane przez Artura 23.11.2026). W powtórce
października 52 kontrakty nie miały raportu w poczcie rozliczeń, a Finanse nie miały akcji
„przypomnij”. Kod: `backend/app/services/client_settlements/reminders.py`, trasy
`/api/finance/settlements/reminders` (`app/api/settlement_reminders.py`), pętla
`app/tasks/settlement_reminders.py`, przycisk `ReportReminders.tsx` w miesiącu klienta.

## Kto jest na liście

Kontrakt, który trwał w miesiącu (aktywny, kończący się, zakończony), bez rozliczenia
i bez pliku raportu. To ten sam stan co „Brak RCP” w `service.month_view`; przy estymacji
liczą się tylko pliki od pierwszego dnia następnego miesiąca.

**Bez klientów rozliczanych z raportu klienta** (reguła `report.time_for_teams`, Nordea),
jak w „Przebiegu miesiąca”: tam brak RCP konsultanta nie jest brakiem. Powtórka 7 próby
IX–X (24.11.2026) dała bez tego 282–286 „braków” Nordei na miesiąc, czyli dzwonek DL-a
o każdej z tych osób (`client_hours_clients`).

## Do kogo

- **Konsultant** dostaje mail wyłącznie przez `portal_mail.send` i tylko przy panelu `pilot`
  albo `all` z aktywacją kontraktu (`PortalSettings.open_for`). W stanie `internal`
  („Tylko zespół”) i `off` do konsultantów nic nie wychodzi
  (`docs/claude/ludzie/portal-konsultanta.md`). Klient z szablonem `client_report` przysyła
  raport sam, więc jego konsultant też nic nie dostaje.
- **Opiekun**: `contracts.care_owner_user_id`, potem `clients.default_care_owner_user_id`,
  potem Delivery Lead klienta z `delivery_lead_client_assignments` (najpierw `is_head`, jak
  `departure_care`). Liczą się tylko aktywne konta.
- **Bez adresata** (mail do konsultanta niedozwolony, brak opiekuna i DL-a klienta): kontrakt zostaje na liście
  Finansów pod filtrem „Brak RCP” i w liczbie `without_recipient`. Nie znika po cichu.
  Próba z października: 48 z 52 kontraktów bez raportu nie miało opiekuna.

## Kiedy

3., 5. i 7. dzień roboczy miesiąca po rozliczanym (`business_today`, bez weekendów i świąt):

- 3. dzień: mail do konsultanta, gdy wolno;
- 5. dzień: mail do konsultanta z opiekunem w kopii (`ccRecipients` w Graph);
- 7. dzień: dzwonek `settlement_report_missing` do opiekuna (jeden na opiekuna i klienta,
  z listą osób; sekcja Delivery, grupa „Rozliczenia: brak raportu godzin”, bez maila).

Pętla budzi się co godzinę od 9:00. **Automat obejmuje tylko klientów z zapisanymi regułami
rozliczeń** (`automatic_clients`). Na kopii produkcji z 23.11.2026 „Brak RCP” za październik
to 498 kontraktów u 28 klientów, a reguły ma jeden klient (9 braków); bez zawężenia automat
wysłałby dzwonki DL-om o setkach kontraktów, których NEXUS jeszcze nie rozlicza. Przycisk
„Przypomnij (n)” działa dla każdego klienta: konsultant z opiekunem w kopii, gdy mail wolno
wysłać, a w przeciwnym razie dzwonek opiekuna.

## Bez powtórek

Każde przypomnienie to wiersz `client_settlement_reminders` (migracja 0763, lustro przez
`hr_schema_bundle`) z unikatem (kontrakt, miesiąc, kanał, dzień). Wiersz powstaje i jest
zatwierdzany PRZED wysyłką, więc restart, drugi przebieg i klik Finansów po automacie tego
samego dnia niczego nie dublują. Wynik (`sent`, `simulated`, `failed`, `blocked`) dopisuje
się po wysyłce. `GET` zwraca per klient datę ostatniego przypomnienia; z tych samych danych
korzysta widok „Przebieg miesiąca”.

## Przełącznik

`app_settings['client_settlement_reminders']` = `{"enabled": bool}`, domyślnie wyłączony,
zmienia go admin w karcie „Start rozliczeń” (`PUT …/reminders/settings`, wpis w dzienniku
zdarzeń). Wyłączony = ani automat, ani przycisk (409); podgląd działa. **Przed włączeniem
na produkcji trzeba zapytać Artura**, bo to wysyłka do ludzi. Na stagingu pętla jest
zatrzymana (`STAGING_BLOCKED_TASKS`).

## Treść maila

Klient z regułą `report.consultant_declaration` (mLeasing) dostaje inną treść:
„Deklaracja dni pracy za <miesiąc>” z przykładem zdania („We wrześniu nie miałam/em dni
wolnych”), bo raportem jest zdanie w mailu, a nie plik z akceptacją klienta; dzwonek
opiekuna mówi to samo. Pozostali klienci: temat „Raport godzin za <miesiąc>: prosimy o przesłanie”. Co przysłać: RCP z akceptacją
klienta, jako plik (PDF albo Excel), nie zrzut ekranu, z adresu firmowego. Dokąd: pierwszy
adres z `CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES`, a bez niego
`CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` (rozliczenia@b2bnetwork.pl). Bez adresu w konfiguracji
mail nie wychodzi (`no_settlements_address`). W treści nie ma kwot ani stawek.
