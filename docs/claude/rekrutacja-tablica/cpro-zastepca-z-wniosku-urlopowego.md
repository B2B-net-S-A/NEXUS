# Osoba od Cpro na urlopie: zastępcę wskazuje we własnym wniosku (29.10.2026)
<!-- indeks: „Kto wrzuca do Cpro” we wniosku urlopowym, `cpro_substitute_user_id`, zastępstwo liczone przy odczycie, `firm_sender` vs `effective_sender` -->

Pytanie Artura z 29.10.2026: osoba od Cpro poszła na urlop (zatwierdzony,
bez zastępcy), a ustawienie Cpro dalej wskazywało na nią. Kolejka „Do
wrzucenia do Cpro” i dzwonki po akceptacji DL-a szły więc do nieobecnej, a
reszta zespołu kolejki nie widzi (`board_tasks._sees_cpro`: gdy ktoś jest
ustawiony na firmę, widzi ją tylko on). Zastępca z wniosku
(`substitute_user_id`) dotyczy akceptacji i poczty, nie Cpro. Decyzja Artura:
osoba od Cpro wskazuje we wniosku, kto w tym czasie wrzuca.

- **Pole we wniosku.** `leave_requests.cpro_substitute_user_id` (0619,
  `hr_leave_cpro_schema.py`), osobno od zwykłego zastępcy, bo osoba od Cpro
  bywa w Finansach, a Cpro przejmuje ktoś z rekrutacji. Podgląd wniosku mówi
  `cpro_sender: true` osobie, która dziś jest osobą od Cpro, i wtedy okno
  pokazuje „Kto wrzuca do Cpro”. Lista osób jest ta sama co przy „Zmień” nad
  kolejką (`useCproAssigneeOptions`, serwer: `board_tasks.load_assignee`).
- **Wymagane we własnym wniosku na pełne dni** (422 `CPRO_SUBSTITUTE_REQUIRED`;
  okno blokuje zapis tym samym warunkiem, `cproSubstituteMissing`). Pół dnia
  go nie wymaga, bo osoba od Cpro jest wtedy w pracy. Wpis za pracownika
  (Kadry, L4) może je podać, ale nie musi. Ktoś, kto nie jest osobą od Cpro
  i poda pole, dostaje 422 — pole nie znika po cichu.
- **Zastępstwo liczy się przy odczycie**, jak `until` z „Zmień”:
  `cpro_sender.effective_sender` = ustawienie firmy (`firm_sender`) +
  zatwierdzony urlop tej osoby na cały dzisiejszy dzień z aktywnym zastępcą
  (`leave_cover`, ten sam warunek co `leave_substitute._covering_today`).
  Wynik ma `until` = ostatni dzień urlopu i `fallback_user_id` = osoba od
  Cpro, więc pulpit pokazuje „zastępstwo do …, potem …”. Ustawienie
  w `app_settings` się nie zmienia: anulowany albo skrócony urlop niczego
  nie zostawia i nie ma czego sprzątać.
- **„Zmień” w trakcie urlopu wygrywa** — ustawia inną osobę niż urlopowicz,
  a zastępstwo z daty liczy powrót od ustawienia firmy (`next_state` czyta
  surowy stan), więc po nim wraca osoba od Cpro, nie zastępca z wniosku.
- **Kto jest osobą od Cpro dla wniosku** — `firm_sender`, bez urlopowej
  nakładki. Inaczej osoba od Cpro, która w trakcie urlopu składa kolejny
  wniosek, nie dostałaby pytania.
- **Dzwonek** przy zatwierdzeniu (także zgłoszenia B2B, które wchodzi od
  razu): `cpro_send_assigned` „Wysyłasz kandydatów do Cpro” z terminem i
  imieniem, bez rodzaju nieobecności (D6, `urlopy-czas-place-wejscie-odejscie.md`).
  Anulowanie urlopu nie wysyła osobnego dzwonka zastępcy do Cpro — kolejka
  po prostu przestaje do niego trafiać.
- Moje wnioski (`/my-time?tab=leave`) pokazują w kolumnie zastępcy dopisek
  „Cpro: …” (`cpro_substitute_name`).
- Edycja wniosku (`EditIn`) pola nie zmienia; zmiana zastępcy do Cpro =
  „Zmień” nad kolejką albo nowy wniosek.
- Testy: `backend/tests/test_hr_leave_cpro_substitute.py`,
  `frontend/src/components/hr/leave/__tests__/LeaveRequestDialog.test.tsx`
  (describe „osoba od Cpro”), `leave-format.test.ts` (`cproSubstituteMissing`).
