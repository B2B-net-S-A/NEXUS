# Ścieżka na stagingu — każdy PR z ekranem, PDF-em, Wordem albo mailem, każdą rolą, która z tego korzysta
<!-- indeks: skill /sciezka, bramka sciezka-stagingu-gate.js, paragon ~/.nexus-staging/e2e, mapa ról sciezki/mapa-rol.json, compare_flags, „Zaloguj jako” (`scripts.staging_login_as`), backend z gałęzi na 8101, rola, która nie powinna widzieć, kontrola po wdrożeniu -->

Decyzja Artura z 25.10.2026, rozszerzona 25.11.2026: także zmiana jednej roli
(edytor CV wymknął się regule „styku ról”). Każdy PR, który zmienia to, co ktoś
zobaczy albo pobierze (ekran, PDF, Word, CV, mail), przechodzi na stagingu
(`staging-na-laptopie.md`) całą ścieżkę każdą rolą z mapy obszaru
(`sciezki/mapa-rol.json`): od początku do końca (edytuj, pobierz, zatwierdź,
przekaż), na kopii produkcji, z kodem gałęzi i flagami jak na produkcji,
**zanim powstanie PR**. Bo testy i zrzut z jednego konta pokazują, że ekran się
renderuje, a nie to, że Delivery Lead dostał to, co rekruter wysłał — a rano
zgłasza to rekruter, nie CI. PR od razu dostaje auto-merge, więc test po jego
otwarciu przychodzi za późno.

Wykonanie: skill `/sciezka <obszar>` (`.claude/skills/sciezka/`). Bramka: hook
`sciezka-stagingu-gate.js` na `gh pr create` / `gh pr ready` blokuje PR bez
paragonu `~/.nexus-staging/e2e/<gałąź>.md`, paragonu starszego niż ostatni commit
z ekranem, bez wiersza ze zrzutem dla roli z mapy albo z różnicą flagi, której
dotyka diff. Draft przechodzi (bramka wraca przy `gh pr ready`). Wyjście
awaryjne: `SCIEZKA_POMIN="<powód>"` i PR jako draft z etykietą
`czeka-na-sciezke`, powód w opisie PR-a. Same testy, `docs/`, `.github/`,
`scripts/` — tylko CI.

Nowy obszar: pierwsza sesja przechodzi go ręcznie i dopisuje scenariusz
(`.claude/skills/sciezka/scenariusze/`) oraz wpis w mapie ról.

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
    --env-file $W/.env.staging-flags.local \
    run -d --rm --no-deps --name nexus-staging-backend-branch \
    -p 127.0.0.1:8101:8000 -v "$PWD/backend:/app" \
    -e 'CORS_ORIGINS=["http://localhost:3101"]' backend
  ```

  Backend z gałęzi ma rolę `web` (`web-i-worker-osobno.md`), więc pętle w tle zostają
  w głównym workerze. Na własnej bazie dopisz `-e NEXUS_PROCESS_ROLE=all`.

  Baza główna zmienia się co noc (`staging-na-laptopie.md`), a zapisy z testu
  zostają na starej kopii. Po teście `docker stop nexus-staging-backend-branch`. Jeden taki kontener
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

Pierwsza komenda wypisuje aktywne osoby w roli, druga sam token. Front nie
przyjmuje tokenu z JS (od 22.11.2026,
`uprawnienia/sesja-w-ciasteczku-httponly-i-csrf.md`), więc w konsoli karty
(3100 albo 3101, na dowolnej stronie frontu) wymieniasz go na ciasteczko
HttpOnly i otwierasz `/login`, którego sonda kończy logowanie:

```js
localStorage.clear();
const API = "http://localhost:8100", t = "<token>";
await fetch(`${API}/api/auth/session`, { method: "POST", credentials: "include", headers: { Authorization: `Bearer ${t}` } });
const me = await fetch(`${API}/api/auth/me`, { credentials: "include" });
localStorage.setItem("nexus_user", JSON.stringify(await me.json()));
location.href = "/login";
```

Ciasteczka `nexus_access` nie da się skasować z JS — zmiana roli to po prostu
następny token tą samą drogą (`POST /api/auth/session` nadpisuje ciasteczko).
Headless Playwright robi to samo `adoptBrowserSession` z
`frontend/e2e/helpers/session.ts`. Token nie trafia do repo, PR-a ani raportu.

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
powodem. To samo dla integracji zewnętrznych (M365, KSeF).

## 5. Paragon i opis PR-a

Format paragonu jest w skillu (krok 6): tabela flag i tabela kroków
(rola · krok · wynik · zrzut), id osób i rekordów, nie nazwiska. Paragon i
zrzuty zostają w `~/.nexus-staging/e2e/` (prawdziwe dane); do pokazania
Arturowi — prywatny artefakt, jak makiety. W opisie PR-a sekcja „Ścieżka na
stagingu” bez danych osobowych. Krok na czerwono = test, poprawka i powtórka
przed `gh pr create`.

## 6. Kontrola po wdrożeniu

Kroki, których staging nie pokaże (poczta, Teams, KSeF, Traffit, Cpro, pętle w
tle, dzisiejsze dane), paragon i opis PR-a wpisują jako „Nie sprawdzone na
stagingu”. Sesja wieczorna po `/api/health` z SHA zawierającym PR sprawdza je
na produkcji (odczyt, `prod_readonly`, bez wysyłek na zewnątrz) i dopisuje
wynik komentarzem w PR-ze; ✗ = karta sesji do rana.
