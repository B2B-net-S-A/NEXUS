# Rutyny nocne — Dyżurny, Strażnik Nowości, Tester, Domykacz, Poranny raport
<!-- indeks: zadania Claude'a na laptopie 00:00–07:30, PR-y rutyn same po zielonym CI, odczyt produkcji przez SSH, backup poza rutynami, `scripts/staging/refresh_code.sh`, nocna kopia z launchd, status aplikacji nie jest sygnałem -->

Decyzja Artura z 02.11.2026. Automaty, które już mieliśmy, tylko zgłaszały
problemy: nocny E2E czerwienił się 5 nocy, a raporty kolejki leżały otwarte
tygodniami. Rutyny mają te zgłoszenia podnosić i coś z nimi robić, a Artur
ma rano otwierać jedną sesję zamiast wielu raportów.

| Godzina (Warszawa) | Rutyna | Co robi |
|---|---|---|
| 00:11, codziennie | Nocna kopia stagingu (launchd, bez modelu) | `nightly_sync.py` z kopii w `~/.claude/nexus-rutyny/bin/kopia/`: flagi z produkcji, nowa kopia bazy, dosłanie plików CV, Qdrant, strażnik rankingu (`staging-na-laptopie.md`) |
| 01:05, pon. i czw. | Strażnik Nowości | PR-y ze zmianą ekranu a `novelties.json`, także tytuły `fix` |
| 02:00, codziennie | Dyżurny | Alarmy na GitHubie i wiszące PR-y |
| 03:17, pon.–pt. | Odświeżenie stagingu | `scripts/staging/refresh_code.sh`: kod z `origin/main` tuż przed Testerem, baza bez zmian |
| 03:30, pon.–pt. | Tester | PR-y od poprzedniego biegu na stagingu, każdą dotkniętą rolą przy 1280 × 720, najwyżej 10 |
| 06:30 | Domykacz wdrożeń | `/api/health` względem maina i listy „po wdrożeniu” |
| 07:30, pon.–pt. | Poranny raport | Jedna sesja z pytaniami do Artura |
| 08:30, codziennie | Zegarek (launchd, bez modelu) | Oczekiwane biegi kontra ślady `.ok`: brak śladu to czerwień, powiadomienie na laptopie i ping poza laptop |

- **Działają na laptopie jako zadania w aplikacji Claude**, bo potrzebują
  stagingu, `gh` i klucza SSH. Zamknięta aplikacja = bieg przy następnym
  uruchomieniu. Crona GitHuba nie używamy: spóźnia się do 7 godzin, a jego logi
  są publiczne.
- **Godziny wynikają z audytu z 08.11.2026.** Aplikacja dodaje kilka minut opóźnienia.
  PR Strażnika o 02:30 kończył wdrożenie 3–4 min przed backupem produkcji i 06.11
  zabrał zrzut, a odświeżenie o 01:00 omijało PR-y scalone przed Testerem. Odśmiecacz
  jest usunięty: pracy było na 1–2 noce, a CI nie odróżnia złego skasowania.
- **Status biegu w aplikacji jest zawsze „succeeded”**, także po kodzie 1, 3, 4
  i odmowie trybu auto. Wynik rutyny czytaj ze śladu `<rutyna>.ok`: jedna linia JSON
  (`stan`: `ok`, `degraded`, `failed`, `skipped`) zapisana przez `bin/slad.py`.
  Zegarek (`~/.claude/nexus-rutyny/zegarek.py`) liczy brak śladu jako awarię.
- **PR-y rutyn wchodzą same po zielonym CI** (`gh pr merge --squash --auto`,
  decyzja Artura). Najwyżej jeden PR na rutynę na noc, bez migracji. Dlatego
  rutyna zmieniająca kod musi przed PR-em uruchomić lokalne testy zmienionych plików.
- **Odczyt produkcji przez SSH jest dozwolony dla rutyn, tylko do odczytu**
  (`default_transaction_read_only`), wąskimi zapytaniami: id, liczby, daty.
  Bez treści notatek. Odmowa uprawnień = wpis w raporcie, bez obchodzenia.
- **Wyjątek: nocna kopia używa klucza z pełnym dostępem przez launchd bez modelu**
  (decyzja Artura z 08.11.2026), więc klasyfikator jej nie sprawdza. Dlatego
  `nightly_sync.py` i `clone_from_hetzner.py` biegną z kopii w
  `~/.claude/nexus-rutyny/bin/kopia/scripts/staging/`, a nie z maina: scalony PR
  nie zmienia sam tego, co działa z kluczem. Po zmianie tych dwóch skryptów:
  `git show origin/main:scripts/staging/<plik> > ~/.claude/nexus-rutyny/bin/kopia/scripts/staging/<plik>`.
  Zadanie: `~/Library/LaunchAgents/pl.dynaminds.nexus-nocna-kopia.plist`,
  skrypt startowy `bin/nocna-kopia.sh`. Build i `sanitize.sql` idą z kodu stagingu
  (`origin/main`), bo nie mają dostępu do klucza.
- **Odtwarzanie kopii ma limit 40 min i strażnika postępu** (decyzja z audytu z 08.11.2026):
  rozmiar bazy, wiersze COPY i start instrukcji bez zmiany przez 5 min przerywają bieg, potem
  jedno ponowienie z tego samego zrzutu. 07.11 strumień stanął po 8 min, a limit 2 h zabrał noc.
- **PR-y dotykające bramki wdrożeń i sond nie wchodzą same.** Zmiana w `deploy.yml`,
  `select_release_sha.py`, `deploy_needed.py`, `alert_issue.sh`, `uptime-probe.yml`
  albo `disk-alert.yml` idzie z etykietą `wstrzymaj` i pytaniem do Artura
  (decyzja z 08.11.2026, #3155 wszedł nocą bez przeglądu).
- **Rutyny czytają produkcję wyłącznie przez `scripts/prod_readonly.py`**
  (decyzja Artura z 06.11.2026), nie surowym `ssh`. W trybie auto klasyfikator
  raz przepuszczał, raz odrzucał tę samą komendę SSH, a reguła zgody na `ssh`
  dałaby rutynie dowolną komendę na produkcji. Skrypt ma stałe podkomendy:
  `sql` (tylko SELECT/WITH, bez poleceń psql; w bazie sesja i transakcja
  READ ONLY zakończona ROLLBACK), `env NAZWA…` (zmienne procesu 1 backendu
  z białej listy, filtr na serwerze, nazwy sekretów odrzucone), `backup-log [N]`
  i `health`. Reguła zgody Claude Code obejmuje tylko kopię skryptu
  w `~/.claude/nexus-rutyny/bin/`, a host i klucz są w
  `~/.claude/nexus-rutyny/prod-readonly.conf`, bo repo jest publiczne.
  Kopia nie podąża za mainem sama: zmiana skryptu wchodzi do rutyn dopiero po
  `install -m 755 scripts/prod_readonly.py ~/.claude/nexus-rutyny/bin/`, więc
  scalony PR rutyny nie poszerza sam, co rutyny mogą na produkcji.
  Bramki pilnuje `backend/tests/test_prod_readonly_script.py`.
- **Nic nie idzie do ludzi.** Rutyna pisze szkic „daj znać”, wysyła Artur.
- **Backup jest poza rutynami:** robi go admin osobno, więc `#1247`
  i `backup-drill.yml` nie są sprawą Dyżurnego.
- **Treść rutyn nie leży w repo**, bo repo jest publiczne: zadania są
  w `~/.claude/scheduled-tasks/`, zasady i raporty w `~/.claude/nexus-rutyny/`.
  Tam też trafiają nazwiska i zrzuty; do PR-ów i komentarzy na GitHubie nie.
- **Rozstrzygnięcia i sprawy przeżywają noc** (audyt z 08.11.2026, wcześniej decyzje czytano
  z dwóch dni, a sprawy znikały z raportów). `decyzje-stale.md` czyta każda rutyna, a `sprawy.jsonl`
  (`bin/sprawy.py`) jest jedynym rejestrem spraw z właścicielem i terminem. Terminy z plików
  pamięci dopisuje Zegarek (`terminarz.py`); kasowania mają właściciela Artura i nikt inny ich nie robi.
- **Rutyna, która przez miesiąc nic nie znalazła, jest do usunięcia.**
