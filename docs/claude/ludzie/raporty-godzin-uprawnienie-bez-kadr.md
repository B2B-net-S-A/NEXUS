# Uprawnienie „Raporty godzin” — akceptacja timesheetów bez Kadr (28.10.2026)

Decyzja Artura z 28.10.2026. Osoba z back office rozlicza raporty godzin i premie
z automatu. Do tej pory miała rolę Finanse, czyli pełny odczyt i edycję firmy:
rekrutacje, kandydaci, klienci, kontrakty ze stawkami i marżą, zamówienia,
Insights. Samo „Płace” nie wystarczało, bo raporty godzin całej firmy
akceptowały tylko „Kadry” (oraz koordynator, head pionu i admin). „Kadry” dają
jednak e-teczki z potwierdzeniami L4, rodzaj nieobecności i decyzje urlopowe.

Docelowe konto: rola **„Pracownik”** + **„Raporty godzin”** + **„Płace”**.
Ustawia je admin w „Osobach i rolach”.
Makiety i zrzuty: https://claude.ai/artifact/VkHnhBQM4RGSYGYJ4zro4p.

- **Katalog:** `timesheets`, „Raporty godzin: akceptacja całej firmy”, w grupie
  „Ludzie”, ale na końcu `PERMISSIONS` (siatka przy starcie sprawdza ostatni
  zasiewany klucz). Domyślnie ma je tylko admin. Migracja `0613`, CHECK akcji
  w `entrypoint.sh`.
- **Co daje** (`time_access.Actor.timesheets`): `approves_everyone`, czyli
  kolejka, podgląd, akceptacja, zwrot, cofnięcie, poprawka wpisu i
  „Przypomnij” dla raportów całej firmy. Nikt nie akceptuje własnego raportu.
- **Czego nie daje:** nadgodzin (`overtime_allowed` zostaje przy Kadrach),
  domyślnych opisów godzin, paczki ZIP i CSV miesiąca (to Płace albo Kadry),
  kolejki nieobecności, wpisu za osobę ani kartotek z e-teczką.
- **D6:** posiadacz bez Kadr widzi w dniach raportu „Nieobecność”, nie rodzaj,
  tak jak zastępca koordynatora. Wyjątek: własny zespół i osoby pionu, którego
  jest headem (`Actor.sees_leave_type`).
- **„Akceptacje” na froncie:** nieobecności (chipy, skrzynka, „Wpisz nieobecność
  za…”) pokazują się tylko przy `me.leave_approver` z `/api/hr/config`.
  Tę flagę liczy `leave_service.is_leave_approver`, ta sama funkcja co bramka
  tras urlopów. Osoba z samymi „Raportami godzin” nie dostaje bloku 403
  „Brak uprawnień”. Zakres na ekranie: „wszyscy”.
- Nowe miejsce, które akceptuje timesheety „za wszystkich”, czyta
  `Actor.approves_everyone`. Nie wpisuj tam znowu samego `people_admin`.

## Raport osoby, która odeszła (decyzja Artura 05.11.2026)

Osoba po odejściu (`employment_status = exited`, konto wyłączone) sama nie wyśle
raportu, a Płace liczą tylko zatwierdzone. Dlatego akceptujący dopisuje godziny
w podglądzie i klika „Potwierdź za osobę”
(`POST /api/hr/time/timesheets/{id}/confirm-for-person`,
`time_flow.confirm_for_person`).

- Tylko ze szkicu, z co najmniej jednym wpisem, w otwartym miesiącu płac i tylko
  po odejściu. Osobie, która pracuje, ta trasa daje 409: ona wysyła sama.
- Działa także na zleceniu. Artur wybrał to świadomie, wiedząc, że przyjęty raport
  zlecenia to potwierdzenie godzin (art. 8b) i po terminie wypłaty nie da się go
  cofnąć przez 3 lata (`time_retention.py`).
- Bez dzwonka do osoby. Ślad: `timesheet_confirmed_for_person` w `hr_audit_events`.
  Cofnięcie jak przy zwykłej akceptacji.
- Wpis za osobę po odejściu poza jej współpracą (`employed_on`) dostaje 422. Własne
  wpisy i wpisy za osoby w pracy zostają bez tej granicy.
- Na liście akceptacji są tylko osoby z wierszem `timesheets` za ten miesiąc. Kto
  odszedł i nie ma wiersza, nie pojawia się tam. Tego celowo nie zmieniamy, bo
  każdy stary miesiąc dostałby wszystkie osoby po odejściu.
