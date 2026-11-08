# Backup bazy o 06:30 UTC, częściowy plik kasowany, jedno ponowienie
<!-- indeks: cron `/root/nexus-backup.sh` na hoście poza repo, 06:30 UTC zamiast 02:30, kolizja z oknem Deploy, ponowienie po 20 min, kontener Postgresa szukany od nowa -->

Decyzja Artura z 08.11.2026 (audyt rutyn). Skrypt i cron leżą na hoście, poza
repo: `/root/nexus-backup.sh`, crontab roota, log `/var/log/nexus-backup.log`
(odczyt: `scripts/prod_readonly.py backup-log 200`). Zmiana skryptu albo godziny
to praca na hoście za zgodą Artura, nie PR.

## Dlaczego nie 02:30 UTC

Wdrożenie restartuje Postgresa i zabija działający `pg_dump`. Dwie noce z rzędu
nie było zrzutu: 06.11 (Deploy 02:22–02:32 UTC) i 07.11 (02:32–02:41 UTC). Częściowy
plik liczył się do `KEEP_PG` i wypychał najstarszy dobry zrzut.

## Co robi skrypt od 08.11.2026

- Start `30 6 * * *`. Host ma strefę UTC, więc to 07:30 w Warszawie zimą
  i 08:30 latem.
- Po nieudanym `pg_dump` kasuje częściowy plik.
- Czeka 20 minut (`PG_RETRY_PAUSE=1200`) i ponawia raz. Każda próba szuka kontenera
  od nowa, bo wdrożenie tworzy Postgresa pod nową nazwą. Brak kontenera to też
  nieudana próba, a nie koniec skryptu: Qdrant i Coolify idą dalej.
- Ponowienie dotyczy tylko Postgresa. Qdranta da się odtworzyć z bazy.

## Okno wdrożeń a 06:30 UTC

Okno kończy się o 08:00 Warszawy, czyli zimą o 07:00 UTC, a latem o 06:00 UTC.
**Zimą 06:30 UTC leży więc w oknie** i Deploy po scaleniu może się nałożyć; latem nie.
W zimowym czasie nie ma tu slotów budzika ani crona Deploy (ostatni, 04:23 UTC, bywa
opóźniony), a nałożyć się może tylko Deploy po nocnym scaleniu. Ponowienie po 20 min
przeczekuje restart, bo Deploy trwa ok. 10 min.

Pomiar z 08.11 (1000 biegów Deploy z 07.10–08.11, bieg dłuższy niż 4 min, 15 min od
startu backupu): przy 02:30 UTC 5 nałożeń, przy 06:30 UTC 3, wszystkie z 07.10 i 14.10,
przed wprowadzeniem okna wdrożeń. Od zmiany czasu 25.10 przy 06:30 UTC zero.

## Kopie przed zmianą

Na hoście zostały `/root/nexus-backup.sh.bak-20261108` i
`/root/scripts/crontab.backup-20261108-backup`.

Procedura odtworzenia i kopia poza serwerem: `docs/disaster-recovery.md`.
