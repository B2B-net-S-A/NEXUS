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
  zasiewany klucz). Domyślnie ma je tylko admin. Migracja `0609`, CHECK akcji
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
