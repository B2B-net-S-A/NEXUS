# Test całej ścieżki na stagingu — zmiana na styku ról przechodzi każdą rolę przed PR-em
<!-- indeks: mapa „kto → co robi → co widzi następny”, „Zaloguj jako” (`scripts.staging_login_as`), backend z gałęzi na 8101, rola, która nie powinna widzieć, raport w artefakcie -->

Decyzja Artura z 25.10.2026. Zmiana, która dotyka co najmniej dwóch ról
(przekazanie, akceptacja, powiadomienie albo kafelek dla innej osoby, kwota
widoczna tylko dla części ról), przechodzi na stagingu
(`staging-na-laptopie.md`) całą ścieżkę: każdą rolą po kolei, na
prawdziwych danych, **zanim powstanie PR**. Bo testy i zrzut z jednego konta
pokazują, że ekran się renderuje, a nie to, że Delivery Lead dostał to, co
rekruter właśnie wysłał. PR od razu dostaje auto-merge, więc test po jego
otwarciu przychodzi za późno.

Zmiana w obrębie jednej roli (jeden ekran, jedna osoba) nie wymaga tego
testu; wystarcza zrzut ze stagingu jak przy makiecie (`ui/makiety-na-stagingu.md`).
Refaktory, testy i dokumentacja — tylko CI.

## 1. Mapa ścieżki, zanim cokolwiek klikniesz

Wypisz kroki jako „kto → co robi → co widzi następna osoba”, np.
rekruter przesuwa kartę na „Zweryfikowany” → Delivery Lead dostaje dzwonek
i kartę w przeglądzie → akceptuje → rekruter widzi „CV wysłane” → Head of
Recruitment widzi to w Insights. Role i przejścia bierzesz z pliku reguł
obszaru (indeks w CLAUDE.md). Dopisz role, które czegoś **nie** powinny
widzieć ani robić (rekruter a stawka do klienta, Delivery Lead a cudzy
klient) — to też są kroki.

## 2. Gałąź na danych stagingu

- **Front z gałęzi** na porcie 3101, jak przy makietach:
  `cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8101 npm run dev -- -p 3101`
  (sam front bez zmian w API: `http://localhost:8100`).
- **Backend z gałęzi** na porcie 8101, na bazie stagingu, z obrazu stagingu
  i kodem z worktree:

  ```bash
  W=~/.codex/worktrees/nexus-staging-data-promotion  # katalog, z którego stoi staging
  docker compose -p nexus-staging --project-directory $W \
    -f docker-compose.staging.yml --env-file $W/.env.staging.local \
    run -d --rm --no-deps --name nexus-staging-backend-branch \
    -p 127.0.0.1:8101:8000 -v "$PWD/backend:/app" \
    -e 'CORS_ORIGINS=["http://localhost:3101"]' backend
  ```

  Po teście `docker stop nexus-staging-backend-branch`. Jeden taki kontener
  naraz — nazwa jest stała celowo, druga sesja dostanie konflikt zamiast
  cichego drugiego backendu na tej samej bazie.
- **Zmiana schematu bazy** nie idzie na wspólną bazę stagingu (entrypoint
  gałęzi wykonałby na niej DDL i migracje). Dotyczy też gałęzi bez własnej
  migracji, gdy main ma migracje nowsze niż kopia stagingu. Najpierw kopia
  bazy, na której stoi staging (nazwa jest w `DATABASE_URL` kontenera
  `nexus-staging-backend-1`, np. `nexus_staging_20261022b`, a nie `nexus`):
  `docker exec nexus-staging-postgres-1 sh -c 'createdb -U nexus nexus_branch && pg_dump -U nexus <baza stagingu> | psql -q -U nexus nexus_branch'`
  (11 GB, kilka minut; `createdb -T` nie zadziała, bo staging trzyma
  połączenia). Potem backend gałęzi z `STAGING_DATABASE_NAME=nexus_branch`
  ustawionym w powłoce przed `docker compose … run` (compose wstawia je do
  `DATABASE_URL` przy czytaniu pliku; `-e` tego nie zmieni). Entrypoint
  migruje kopię, a `/api/health` odpowiada po ok. 2–3 min. Po teście
  `docker stop nexus-staging-backend-branch` i `dropdb -U nexus nexus_branch`
  (przećwiczone 29.10.2026).
- **Front na innym porcie niż 3101** (zajęty przez inną sesję): podaj ten
  port w `CORS_ORIGINS` backendu gałęzi.

## 3. Każdy krok jako prawdziwa osoba w tej roli

Hasła na stagingu są skopiowane z produkcji, a admiński „Podgląd jako”
jest tylko do odczytu (`api/deps.py`), więc do kroków z zapisem służy
„Zaloguj jako” — skrypt działający wyłącznie przy `NEXUS_ENV=staging`:

```bash
docker exec nexus-staging-backend-1 python -m scripts.staging_login_as --role delivery_lead
docker exec nexus-staging-backend-1 python -m scripts.staging_login_as --user-id <id>
```

Pierwsza komenda wypisuje aktywne osoby w roli, druga sam token. W karcie
przeglądarki (3100 albo 3101): `localStorage.clear()`, usuń cookie
`nexus_access`, `localStorage.setItem('access_token', '<token>')`, otwórz
`/login` — strona sprawdza token przez `/api/auth/me` i kończy logowanie.
Zmiana roli = to samo z tokenem następnej osoby. Token nie trafia do repo,
PR-a ani raportu.

- Wybieraj osobę, która ma dane w tym kroku: Delivery Lead na swoim kliencie,
  rekruter na swojej karcie. Id osoby i rekordu zapisuj w raporcie, nazwiska nie.
- Okno 1280 × 720, wbudowana przeglądarka.
- Po każdym kroku zrzut oraz sprawdzenie, co dostała następna osoba:
  dzwonek, kafelek, licznik, mail w Mailpicie (`http://localhost:8125`).
- Rola, która nie powinna czegoś widzieć: brak przycisku na ekranie **i**
  odmowa serwera (403 przez `curl` z jej tokenem) — ukryty przycisk to nie
  uprawnienie.
- Staging jest wspólny dla sesji. Zapisy rób na rekordach potrzebnych do
  ścieżki i napisz w raporcie, co zostało zmienione (id).

## 4. Czego staging nie pokaże

Pętle w tle stoją (`app/core/staging.py`), wyjście na świat blokuje zapora,
dane są z dnia kopii. Krok zależny od pętli uruchom raz ręcznie (funkcja
pętli w `docker exec … python -c`) albo oznacz jako **niepotwierdzone** z
powodem. To samo dla integracji zewnętrznych (M365, CloudTalk, KSeF).

## 5. Raport

Tabela: krok · rola (id konta) · czego się spodziewałem · co wyszło · zrzut.
Zrzuty z prawdziwymi danymi idą do prywatnego artefaktu na claude.ai, jak
makiety. W opisie PR-a słowny skrót tabeli bez danych osobowych. Krok na
czerwono = poprawka i powtórka całej ścieżki przed `gh pr create`.
