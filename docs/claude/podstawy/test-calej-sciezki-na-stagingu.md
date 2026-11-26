# Ścieżka na stagingu — każdy PR z ekranem, PDF-em, Wordem albo mailem, każdą rolą, która z tego korzysta
<!-- indeks: skill /sciezka, bramka sciezka-stagingu-gate.js, paragon ~/.nexus-staging/e2e, mapa ról sciezki/mapa-rol.json, compare_flags, „Zaloguj jako” (`scripts.staging_login_as`), backend i front gałęzi na wolnej parze portów 3101–3199 / 8101–8199 (`scripts/staging/free_ports.py`), strażnik w CI, rola, która nie powinna widzieć, kontrola po wdrożeniu -->

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

Mapa wpływu (decyzja Artura z 26.11.2026): przed kodowaniem i przed ścieżką
`python3 scripts/impact_map.py` wypisuje inne ekrany i dokumenty z tą samą
informacją (pola schematów, endpointy, komponenty z diffu), a sesja przy każdym
miejscu decyduje „✓ zmienione”, „— nie: <powód>” albo pyta Artura. Bo zmiana
dodana na jednym ekranie bez drugiego daje dwa ekrany, które mówią co innego, a
ścieżka po ekranie, który zmieniłeś, tego nie złapie. Tabela idzie do paragonu i
do opisu PR-a („Wpływ na inne miejsca”); bramka blokuje paragon bez niej albo z
miejscem bez decyzji. Symbol z ponad 50 miejscami dostaje jeden wiersz
`<symbol> · *` („za ogólne”): decyzja jest jedna dla wszystkich, a gdy nowe pole
ma tę samą informację gdzie indziej, listę daje `git grep -lw <symbol> --
frontend/src backend/app`. Bo nowy typ z polami `text`, `source`, `company`
(PR #4058) dał 2797 wierszy i żaden nie czytał nowej informacji.

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

- **Porty worktree:** `eval "$(python3 scripts/staging/free_ports.py)"` daje
  pierwszą wolną parę `FRONT_PORT` (3101–3199) i `BACKEND_PORT` (8101–8199,
  ten sam numer po 3100/8100). Decyzja Artura z 26.11.2026: zamiast zawsze
  3101/8101, bo w 30 dni było 12 błędów „Port already in use”, a sesje
  nadpisywały sobie front gałęzi. Porty idą do paragonu. Para z bazą
  `nexus_branch_<port>` albo kontenerem `nexus-staging-backend-branch-<port>`
  (także zatrzymanym) jest zajęta, bo sesja ze zmianą schematu kopiuje bazę
  kilka minut, zanim cokolwiek nasłuchuje (26.11.2026 dwie sesje dostały 8104).
  Gdy na wspólnej bazie trwa `pg_dump` cudzej kopii, start backendu gałęzi
  poczekaj: migracja w entrypoincie (ALTER TABLE) stoi wtedy w blokadzie za
  kopią, a kontener wisi w „health: starting”. Sprawdzisz to tak:
  `docker exec nexus-staging-postgres-1 psql -U nexus -d postgres -Atc "select count(*) from pg_stat_activity where application_name='pg_dump'"`.
- **Front z gałęzi:**
  `cd frontend && NEXT_PUBLIC_API_URL=http://localhost:$BACKEND_PORT npm run dev -- -p $FRONT_PORT`.
  Front zawsze z własnym backendem gałęzi, także przy zmianie samego frontu:
  CORS wspólnego stagingu (8100) przyjmuje tylko 3100 i 3101.
- **Backend z gałęzi** na `$BACKEND_PORT`, na bazie stagingu, z obrazu stagingu
  i kodem z worktree:

  ```bash
  W=~/.codex/worktrees/nexus-staging-data-promotion  # katalog, z którego stoi staging
  docker compose -p nexus-staging --project-directory $W \
    -f docker-compose.staging.yml --env-file $W/.env.staging.local \
    --env-file $W/.env.staging-flags.local \
    run -d --rm --no-deps --name nexus-staging-backend-branch-$BACKEND_PORT \
    -p 127.0.0.1:$BACKEND_PORT:8000 -v "$PWD/backend:/app" \
    -e "CORS_ORIGINS=[\"http://localhost:$FRONT_PORT\"]" backend
  ```

  Backend z gałęzi ma rolę `web` (`web-i-worker-osobno.md`), więc pętle w tle zostają
  w głównym workerze. Na własnej bazie dopisz `-e NEXUS_PROCESS_ROLE=all`.
  Rolę `web` daje compose z worktree (`-f docker-compose.staging.yml` względnie do
  katalogu, z którego uruchamiasz komendę). Nie podmieniaj go na
  `$W/docker-compose.staging.yml`: tamten jest starszy i nie ustawia
  `NEXUS_PROCESS_ROLE`, więc backend dostaje rolę `all`, jego pętle stoją w standby
  lidera, `keyword_corpus_backfill` nie włącza korpusu złożonego i lista szuka
  podłańcuchem (26.11.2026: v2 „qa” 5–33 s zamiast 0,3 s).

  Baza główna zmienia się co noc (`staging-na-laptopie.md`), a zapisy z testu
  zostają na starej kopii. Po teście `docker stop nexus-staging-backend-branch-$BACKEND_PORT`.
  Nazwa kontenera ma port, więc kilka worktree może mieć swój backend naraz;
  wszystkie piszą do tej samej bazy stagingu, więc zapisy rób na rekordach
  swojej ścieżki.
- **Zmiana schematu bazy** nie idzie na wspólną bazę stagingu (entrypoint
  gałęzi wykonałby na niej DDL i migracje). Dotyczy też gałęzi bez własnej
  migracji, gdy main ma migracje nowsze niż kopia stagingu. Najpierw kopia
  bazy, na której stoi staging (nazwa jest w `DATABASE_URL` kontenera
  `nexus-staging-backend-1`, np. `nexus_staging_20261022b`, a nie `nexus`):
  `docker exec nexus-staging-postgres-1 sh -c "createdb -U nexus nexus_branch_$BACKEND_PORT && pg_dump -U nexus <baza stagingu> | psql -q -U nexus nexus_branch_$BACKEND_PORT"`
  (11 GB, kilka minut; `createdb -T` nie zadziała, bo staging trzyma
  połączenia). Potem backend gałęzi z `STAGING_DATABASE_NAME=nexus_branch_$BACKEND_PORT`
  ustawionym w powłoce przed `docker compose … run` (compose wstawia je do
  `DATABASE_URL` przy czytaniu pliku; `-e` tego nie zmieni). Entrypoint
  migruje kopię, a `/api/health` odpowiada po ok. 2–3 min. Po teście
  `docker stop nexus-staging-backend-branch-$BACKEND_PORT` i `dropdb -U nexus nexus_branch_$BACKEND_PORT`
  (przećwiczone 29.10.2026).

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
(3100 albo `$FRONT_PORT`, na dowolnej stronie frontu) wymieniasz go na ciasteczko
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
stagingu” bez danych osobowych, z portami i linią `Strażnik: <plik testu> /
nie dotyczy`. Krok na czerwono = test, poprawka i powtórka przed `gh pr create`.
Błąd, który może wrócić w innym miejscu, dostaje strażnika w CI (test w tej
gałęzi), a nie notatkę w pamięci — decyzja Artura z 26.11.2026, bo pamięć czyta
tylko sesja, która na nią trafi, a CI pilnuje każdego PR-a.

## 6. Kontrola po wdrożeniu

Kroki, których staging nie pokaże (poczta, Teams, KSeF, Traffit, Cpro, pętle w
tle, dzisiejsze dane), paragon i opis PR-a wpisują w sekcji
`## Nie sprawdzone na stagingu`, jeden punkt na linię, z tym, co ma być widać
na produkcji.

Sprawdza je rutyna „Kontrola po wdrożeniu” (zadanie w aplikacji Claude,
8:15 oraz 19:15, 21:15 i 23:15, po slotach okna wdrożeń; od 26.11.2026).
„Sesja wieczorna”, na którą liczyła ta reguła, w praktyce się nie odbywała.
Gdy `/api/health` pokazuje nowy SHA, rutyna bierze PR-y z tego wdrożenia,
sprawdza punkty odczytem (`prod_readonly`, bez wysyłek na zewnątrz) i dopisuje
wynik komentarzem w PR-ze (znacznik `<!-- kontrola-po-wdrozeniu -->`, tylko
id i liczby). ✗ = karta sesji do rana. Rano wysyła do sesji Raporty
zestawienie `scripts/gdzie_jest.py` z PR-ów z wczoraj.

`python3 scripts/gdzie_jest.py <nr…>` mówi jednym wierszem, gdzie jest PR:
w kolejce, wypadł z kolejki (z powodem i czerwonym testem z biegu
`merge_group`), pas migracji, scalony i czeka na okno 18:00, wdrożenie w toku
albo na produkcji (backend z `/api/health`, front z `sentry-release` strony
`/login`). Bez numerów: PR-y otwarte i scalone w ostatnich 24 h. Bramka Stop
`~/.claude/hooks/gdzie-jest-gate.js` wymaga tego wiersza w ostatniej
wiadomości sesji z PR-em otwartym albo scalonym w tej sesji.
