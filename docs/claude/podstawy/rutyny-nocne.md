# Rutyny nocne — Dyżurny, Strażnik Nowości, Tester, Domykacz, Poranny raport, Odśmiecacz
<!-- indeks: zadania Claude'a na laptopie 01:00–07:30, PR-y rutyn same po zielonym CI, odczyt produkcji przez SSH, backup poza rutynami, `scripts/staging/refresh_code.sh` -->

Decyzja Artura z 02.11.2026. Automaty, które już mieliśmy, tylko zgłaszały
problemy: nocny E2E czerwienił się 5 nocy, a raporty kolejki leżały otwarte
tygodniami. Rutyny mają te zgłoszenia podnosić i coś z nimi robić, a Artur
ma rano otwierać jedną sesję zamiast wielu raportów.

| Godzina (Warszawa) | Rutyna | Co robi |
|---|---|---|
| 01:00 | Odświeżenie stagingu | `scripts/staging/refresh_code.sh`: kod z `origin/main`, baza bez zmian |
| 02:00 | Dyżurny | Alarmy na GitHubie i wiszące PR-y |
| 02:30 | Strażnik Nowości | PR-y ze zmianą ekranu a `novelties.json`, także tytuły `fix` |
| 03:00 | Odśmiecacz (od 09.11) | Martwy kod, najwyżej 10 plików na noc |
| 03:30 | Tester | Plany testów z PR-ów na stagingu, każdą dotkniętą rolą przy 1280 × 720 |
| 06:30 | Domykacz wdrożeń | `/api/health` względem maina i listy „po wdrożeniu” |
| 07:30 | Poranny raport | Jedna sesja z pytaniami do Artura |

- **Działają na laptopie jako zadania w aplikacji Claude**, bo potrzebują
  stagingu, `gh` i klucza SSH. Zamknięta aplikacja = bieg przy następnym
  uruchomieniu. Crona GitHuba nie używamy: spóźnia się do 7 godzin, a jego logi
  są publiczne.
- **PR-y rutyn wchodzą same po zielonym CI** (`gh pr merge --squash --auto`,
  decyzja Artura). Najwyżej jeden PR na rutynę na noc, bez migracji. Dlatego
  rutyna zmieniająca kod musi przed PR-em uruchomić lokalne testy zmienionych plików.
- **Odczyt produkcji przez SSH jest dozwolony dla rutyn, tylko do odczytu**
  (`default_transaction_read_only`), wąskimi zapytaniami: id, liczby, daty.
  Bez treści notatek. Odmowa uprawnień = wpis w raporcie, bez obchodzenia.
- **Nic nie idzie do ludzi.** Rutyna pisze szkic „daj znać”, wysyła Artur.
- **Backup jest poza rutynami:** robi go admin osobno, więc `#1247`
  i `backup-drill.yml` nie są sprawą Dyżurnego.
- **Treść rutyn nie leży w repo**, bo repo jest publiczne: zadania są
  w `~/.claude/scheduled-tasks/`, zasady i raporty w `~/.claude/nexus-rutyny/`.
  Tam też trafiają nazwiska i zrzuty; do PR-ów i komentarzy na GitHubie nie.
- **Rutyna, która przez miesiąc nic nie znalazła, jest do usunięcia.**
