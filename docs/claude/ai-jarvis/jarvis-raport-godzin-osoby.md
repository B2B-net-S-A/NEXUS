# Jarvis czyta raport godzin innej osoby: `person_month` (07.11.2026)
<!-- indeks: person_month, raport godzin osoby, /api/hr/time/team/{user_id}, Raporty godzin, Kadry, D6 w Jarvisie -->

06.11.2026 Finanse zapytały Jarvisa o raport godzin osoby z kontem pracownika.
Od wyszukiwarki z kategorią `people` (#3145) Jarvis tę osobę znajdował, ale
miał tylko `my_month`, czyli własny miesiąc pytającego, i mógł jedynie zgłosić
brak przez `report_gap`. Ta reguła zastępuje punkt „Czego to nie daje”
z sekcji 07.11 w `jarvis-mowi-czego-brakuje.md`.

- **Narzędzie `person_month`** (`HR_TOOLS` w `services/jarvis/tools.py`, tylko
  odczyt): `user_id` (z `global_search` → `people` albo `who_is_absent`), rok
  i miesiąc (domyślnie bieżący z `business_today()`). Czyta
  `GET /api/hr/time/team/{user_id}/{year}/{month}`, czyli ten sam podgląd co
  ekran „Ludzie → Akceptacje”, z uprawnieniami pytającego.
- **Kto je dostaje:** `hr_module="time"` i `any_permission=("timesheets",
  "people_admin")` — „Raporty godzin”, „Kadry” i admin, czyli konta
  z `Actor.approves_everyone`. Przełożony bez tych uprawnień czyta swój zespół
  na ekranie „Akceptacje”; Jarvis go nie podaje, bo dla osób spoza zespołu
  trasa i tak odpowie 404.
- **Same „Płace” go nie dostają.** Trasa wpuszcza tylko akceptujących
  (`require_hr_time_approver`), a „Płace” raportów nie akceptują
  (`test_payroll_alone_still_does_not_approve`). Godziny osoby czytają z PDF
  i CSV (`Actor.can_read`). Docelowe konto back office ma „Raporty godzin”
  i „Płace” razem, a rola Finanse na produkcji ma „Kadry”, więc obie drogi
  narzędzie obejmuje. Poszerzenie trasy o same „Płace” to osobna decyzja.
- **Kształt wyniku (`_shape_person_month`):** imię i `user_id` osoby, status
  raportu, termin, akceptujący, sumy (godziny, nadgodziny, dni nieobecności
  jako liczba, norma, braki) i dni robocze bez wpisu do dziś. Nie ma w nim
  dni z etykietą nieobecności, opisów wpisów, notatek obecności ani powodu
  zwrotu (`return_note` to notatka akceptującego). Rodzaju nieobecności nie
  ma, nawet gdy trasa go zwraca (Kadry, krąg D6), jak w każdym narzędziu HR.
- Testy: `tests/test_jarvis_hr_tools.py` (widoczność i kształt bez bazy),
  `tests/test_jarvis_person_month_api.py` (trasa z bazą: „Raporty godzin”
  dostają miesiąc z „Nieobecność” zamiast rodzaju, rekruter i same „Płace” 403).
