# „Moi ludzie” — raport z wdrożenia (21.09.2026)

## Po co

Rekruter pracuje na stałej liście „swoich ludzi”: wysyła ich do klientów raz za
razem, aż któryś projekt się zamknie. NEXUS tej listy nie miał. Dało się ją
jedynie wyklikać filtrami listy kandydatów, a nowa rekrutacja nie podpowiadała,
kogo z własnych ludzi polecić.

## Decyzje (Artur, 21.09.2026)

| Pytanie | Decyzja |
|---|---|
| Czyja jest osoba | Pierwszy weryfikator pary (kandydat, rekrutacja), która doszła do „CV Wysłane” |
| Horyzont | Bez limitu, porządek przez ręczne „Uśpij” |
| Powiadomienie | Jeden dzwonek na rekrutację, od razu po publikacji, próg 70 |
| Maskotka | Awatar z licznikiem i zdaniami z szablonów, bez AI (czat to osobny etap) |

## Co powstało

**Backend**
- `app/services/my_people.py` — wyliczenie listy (pierwszy weryfikator; bez weryfikacji właścicielem jest pierwszy wysyłający), agregaty, grupy „Pracują” i „Uśpieni”.
- `app/services/my_people_matching.py` — kanoniczny fit „moi ludzie × rekrutacja” oraz `run_for_job` (dzwonek).
- `app/api/my_people.py` — `GET /api/my-people`, `GET /summary`, `GET /for-job/{job_id}`, `POST/DELETE /{id}/snooze`, `POST/DELETE /{id}/pin`, `POST /matches/seen`.
- `app/tasks/candidate_auto_match.py` — krok `_run_my_people` po `run_job_event`.
- Migracja `0334_my_people` z lustrem w `entrypoint.sh`: tabele `my_people_overrides` i `my_people_job_matches`, indeks `ix_candidate_stages_moved_by_stage`, typ powiadomienia `my_people_match`, sondy w `/api/health/deep`.
- Nowe źródło dodania `my_people` w `proposals_bulk.py` i w telemetrii.
- Ustawienia `MY_PEOPLE_MATCH_*` oraz `MY_PEOPLE_PANEL_POOL`.

**Frontend**
- `components/v2/my-people/`:
  - `MyPeoplePanel` — niemodalny panel z zakładkami „Wszyscy”, „Do tej rekrutacji” i „Gdzie przepiąć”.
  - `MyPeopleViews` — prezentacja.
  - `MyPeopleLauncher` — przycisk w topbarze, postać, obsługa `?people=1`.
- `lib/api/myPeople.ts`, `lib/my-people-summary.ts`, `store/my-people.ts`.
- Skrót `m`, capability `nav.my_people`, ikona w dzwonku, unieważnianie cache z WebSocketu.
- Harness `/preview/my-people`.

## Weryfikacja

- Backend: 263 testy w powiązanych plikach (w tym 21 nowych), na świeżo zmigrowanej bazie.
- Frontend: pełny vitest, 466 plików i 4315 testów. `tsc --noEmit` czysty, eslint czysty.
- Harness obejrzany w przeglądarce: lista, zakładka rekrutacji, stan „wektory niedostępne”, pusty, błąd, postać z dymkiem, menu „Uśpij”.

## Znane ograniczenia

- Dzwonek jedzie na kolejce auto-matcha. Przy `AUTO_MATCH_ENABLED=false` nie ma zdarzeń, więc nie ma też dzwonka.
- Dzwonek liczy dopasowanie profilem wag klienta, a panel profilem osoby, która patrzy. Przy profilach per użytkownik liczby mogą się różnić.
- `owners_by_candidate` czyta całą historię `cv_sent` przy każdej publikacji. Działa w tle, ale przy dużym wzroście bazy warto to zmierzyć.
- „Gdzie przepiąć” używa istniejących rekomendacji dla kandydata (`/api/candidates/{id}/recommendations`), a nie kanonicznego fitu.
- Na produkcji niezweryfikowane: przeklikanie przez Chrome po deployu oraz prawdziwy dzwonek po publikacji rekrutacji.
