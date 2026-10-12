# Rekruter przy rekrutacji: widoczny i trwały niezależnie od miejsca dodania — raport z wdrożenia

12.10.2026. Reguły: `docs/claude/rekrutacja-tablica/role-przy-rekrutacji-delivery-lead-rekruter.md`
(punkt „Dopisanie osoby = trwały wpis w zespole”) i
`docs/claude/rekrutacja-tablica/rekrutacja-v3-lista-jobs-i-wiecej-w-pasku-bocznym.md` (kolumna „Rekruter”).

## Po co

Head of Recruitment zgłosił: przy rekrutacji jest kilka osób, a po filtrze
„Rekruter” widać tylko jedną, tę główną; na pulpicie osoba ma kilka requestów,
na liście jeden.

## Co pokazał pomiar na produkcji (tylko odczyt, przed zmianą)

- Filtr „Rekruter” i pulpit „Requesty i obłożenie” zwracały te same rekrutacje
  u wszystkich 15 osób z requestami — reguła odczytu (`services/job_team.py`)
  była poprawna i zostaje bez zmian.
- Kolumna „Rekruter” listy pokazywała pierwszą osobę i „+N”. W 28 wierszach
  osoba, po której się filtruje, była schowana za „+N” — w wierszu stało
  nazwisko prowadzącego. To był objaw z ekranu.
- Dopisanie osoby miało dwie drogi o różnych skutkach: pulpit (dzwonek, ale
  osoba znikała po wyjściu requestu z „Szukamy”, bo automat zwalnia
  przypisania) i panel „Zespół” / okno edycji (bez dzwonka, osoba zostawała).
- 18 „kolejnych osób” istniało wyłącznie jako aktywne ręczne przypisanie
  z pulpitu (15 miało wiersz kategorii `auto_cc`, 3 żadnego).

## Co weszło

- **Lista `/jobs`** — `JobRecruiterCell` pokazuje dwie osoby z nazwiska (jedna
  pod drugą) i „+N”; pierwsze stoją osoby z filtra „Rekruter” i zalogowana
  osoba (`pinRecruiters` w `lib/job-team.ts`, `maxNames` w `RecruiterChips`).
  Szerokość kolumny bez zmian. Kształt `recruitersSummary` bez zmian (czytają
  go trzy inne ekrany).
- **Jedna trwała ścieżka dopisania** — `job_team.add_manual_member`: osoba,
  która nie jest prowadzącym, dostaje wiersz `job_collaborators`
  (`source = 'manual'`, z awansem wiersza `auto_cc`). Wołają ją `manual_add`
  (pulpit, zamiana propozycji), `accept_proposal`,
  `restore_after_champion_removed` i `POST /api/jobs/{id}/collaborators`.
  Przypisań automatu nie utrwalamy.
- **Dzwonek z panelu** — `POST …/collaborators` wysyła „Nowy request do pracy”
  (nie dla siebie, nie dla osoby już pracującej, nie przy zamkniętej
  rekrutacji). Przy okazji zniknął wyścig select→insert (upsert).
- **Zmiana prowadzącego** — zastąpiona osoba traci też ręczny wiersz
  współpracownika, więc „Zmień” nadal zastępuje, a nie dokłada. Okno edycji
  dopisuje ją ponownie, gdy po zmianie pierwszego rekrutera nadal stoi w polu
  „Kolejne osoby” (znalezione w przeglądzie kodu: znikałaby po cichu).
- **Zdjęcie z okna edycji** — `DELETE …/collaborators/{user_id}` dla osoby
  z aktywnym przypisaniem woła `remove_recruiter` i wymaga roli przydzielającej
  (admin, Delivery Lead w swoim zakresie, Head of Recruitment); pozostali
  redaktorzy dostają 409 z komunikatem. Uprawnień nie poszerzono.
- **Uzupełnienie danych** — migracja `0429_recruiter_member_backfill` z lustrem
  w `entrypoint.sh` (jednorazowo, znacznik w `app_settings`): aktywne ręczne
  przypisania osób niebędących prowadzącym dostają wiersz `manual`.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Front: komórka, przypinanie, lista, okno edycji | zielone | `npx vitest run` — 75 plików, 1160 testów (lista, harnessy, inwentarz, pulpit, panel „Zespół”) i 5 plików, 46 testów okna edycji; `npm run type-check` bez błędów |
| Przegląd kodu (tylko blokery) | bez blokerów | niezależny przegląd diffu; jedna uwaga poniżej progu (okno edycji) poprawiona |
| Harness `/preview/jobs-list-v3` przy 1280 × 720 | przeklikane | bez filtra: oglądający (trzeci w zespole) i pierwsza osoba z nazwiska, „+1”; z `?who=71`: osoba z filtra pierwsza; brak poziomego przewijania (1280/1280), wiersz z dwiema osobami 69 px — tyle co istniejący wiersz z propozycją (71 px) |
| Backend: lint i składnia | zielone | `ruff check`, `ruff format --check`, `py_compile` na zmienionych plikach |
| Backend: testy z bazą | w CI | `tests/test_recruiter_role_persists.py`, `test_jobs_ownership.py`, `test_job_team.py`, `test_recruiter_member_backfill.py` — lokalnie nie ma Postgresa |
| Zakres uzupełnienia na produkcji | policzone przed wdrożeniem | sam `SELECT` migracji: 18 wierszy (3 nowe, 15 awansów z `auto_cc`), znacznika jeszcze nie ma |
| Produkcja po wdrożeniu | po wdrożeniu | `/api/health` z SHA z maina; odczyt: wiersze z uzupełnienia i ponowne porównanie pulpitu z filtrem |

## Skutki uboczne, zamierzone

- Osoby z uzupełnienia zaczynają dostawać alerty terminu i dzwonki zmian
  Championa swoich rekrutacji (czytają ręcznych współpracowników).
- Dopisanie z panelu wysyła też mail „request przypisany”, tak jak dopisanie
  z pulpitu.
- Osoby dodane z pulpitu są widoczne w polu „Kolejne osoby” okna edycji.

## Poza zakresem

- Rekrutacje bez rekrutera po migracji z Traffita — obsada ręczna z pulpitu
  (decyzja: Traffita już nie czytamy).
- Treść porannego „Zwolnione: …” — osoba schodzi z obłożenia, ale zostaje przy
  rekrutacji.
- Osoba zdjęta w czasie „Mamy championa” wraca po cofnięciu championa
  (zachowanie sprzed zmiany).
- Komentarz w `frontend/src/lib/job-collaborators.ts` i jedno zdanie w regule
  listy nadal wspominają pole „Kolejne osoby” na `/jobs/new`, którego nie ma od
  02.10.2026.
