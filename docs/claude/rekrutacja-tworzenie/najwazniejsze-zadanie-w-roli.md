# „Najważniejsze zadanie w tej roli” — pole Delivery Leada (23.11.2026)

Decyzja Artura po warsztatach nowego CV (23.11.2026). Delivery Lead wpisuje
w Profilu Championa jedno zdanie słowami klienta: co ta osoba musi dowieźć
w pierwszej kolejności. Do tego zaznacza **jedno** z pytań screeningowych jako
pytanie, które to zadanie sprawdza. Zadanie i odpowiedź kandydata na to pytanie
są wkładem do zdania 3 „Dlaczego nasz kandydat” w nowym CV (`generator-cv/`).

## Kształt danych

- `champion_profile.project.key_task: str`: puste znaczy, że profil powstał
  przed 23.11.2026.
- `champion_profile.screening_questions[].key_task: bool`: najwyżej jedno
  pytanie ma `true`. `ChampionProfile._one_key_task_question` zostawia pierwsze
  zaznaczone, a edytory zaznaczają radiem (`flagKeyTaskQuestion`).
- Odczyt: `champion_view.key_task(source)` → `(zadanie, pytanie | None)`.
  Na froncie `keyTaskOf` z `lib/champion-key-task.ts`.
- Profil żyje w JSONB, więc pole nie wymaga migracji.

## Bramka przekazania

- Kod braku `key_task`: zdanie `MSG_KEY_TASK` w `job_readiness.py` i lustro
  w `frontend/src/lib/__fixtures__/job-readiness-blockers.json`.
- Brak występuje, gdy nie ma zadania albo żadne wypełnione pytanie nie jest
  zaznaczone.
- Działa jak odpowiedź dyskwalifikująca: tylko przy **pierwszym** przekazaniu.
  Rekrutacje w pracy sprzed tej daty nie są blokowane. Ponowne otwarcie
  i ochrona zapisu (`include_open=True`) liczą brak.
- Brak odsłonięty przez dopisanie pytań nie jest „nowym” brakiem
  (`_REVEALED_BY["key_task"] = "questions"`).
- Obowiązuje wszędzie, także w API v1 (`POST /api/v1/recruitments`). Decyzja
  Artura 23.11.2026: „Wszędzie, API też”. Ciało ma `key_task`
  i `screening_questions[].key_task`. Odczyt requestu zawsze zgłasza
  `key_task` w `missing`, bo zadania od klienta AI nie zgaduje.

## Gdzie to widać

- `/jobs/new`: pole w sekcji „O projekcie” i radio przy pytaniach.
- Edytor Profilu Championa: pole w „O projekcie” i radio przy pytaniu.
- Brief Championa: karta „Najważniejsze zadanie w tej roli” ze znacznikiem
  „trafia do CV” i plakietka przy pytaniu.
- Arkusz screeningu rekrutera (`ScreeningFormFields`): przy zaznaczonym
  pytaniu stoi informacja, że odpowiedź trafia do CV.
