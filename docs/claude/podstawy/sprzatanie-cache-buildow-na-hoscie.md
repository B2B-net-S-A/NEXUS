# Cache buildów sprząta cron na hoście, bo Coolify pomija go w trakcie kolejki wdrożeń
<!-- indeks: /etc/cron.d/nexus-build-cache co 15 min, powyżej 70% dysku `docker builder prune -af --filter until=1h`, Coolify 4.7.5 „build cache was not pruned because deployment is queued or running”, 16.11 94%, nigdy container/system/volume prune -->

Decyzja Artura z 16.11.2026. Źródło w repo: `scripts/host/nexus-build-cache-prune.sh`
(na hoście `/usr/local/sbin/nexus-build-cache-prune.sh`) i `scripts/host/nexus-build-cache.cron`
(na hoście `/etc/cron.d/nexus-build-cache`). Log: `/var/log/nexus-build-cache.log`, jedna
linia na bieg, który coś robił. Zmiana na hoście to praca za zgodą Artura. Repo nie wdraża
tych plików samo, więc po zmianie w repo trzeba je skopiować ręcznie.

## Dlaczego

- Każdy build Coolify dokłada do cache buildów Dockera ok. 1–2,5 GB. Seria wdrożeń
  z kolejki merge'ów (16.11: 26 wdrożeń w 4 h) dokładała ok. 30 GB na dysk 75 GB.
- Docker Cleanup w Coolify (co godzinę, próg 60%, `server_settings`) **pomija prune cache**,
  dopóki jakiekolwiek wdrożenie jest w kolejce albo trwa. Z `docker_cleanup_executions`:
  01:00 81% → 79% i 02:00 88% → 88%, oba z dopiskiem „Skipped: the build cache was not
  pruned because deployment … is queued or running on this server”, a o 03:00 94% → 52%
  dopiero po opróżnieniu kolejki.
- Alarm `disk-alert.yml` (75%) od 02.11 otwierał się 6 razy i zamykał sam. Awaria 17.07
  przyszła przy 98,8%.

## Co robi skrypt

- Co 15 min sprawdza `/`. Do 70% włącznie nie robi nic.
- Powyżej 70% uruchamia `docker builder prune -af --filter until=1h`. Cache użyty w ostatniej
  godzinie zostaje, więc trwający build nie traci warstw.
- `flock`: dwa biegi naraz się nie nałożą.
- Rusza **tylko cache buildów**. Nigdy `docker container prune`, `system prune` ani
  `volume prune`, bo `container prune` skasował 17.07 zatrzymany `coolify-db`. Obrazów też
  nie rusza: zostają dla rollbacku, a i tak sprząta je Coolify.

## Co jest na `/` (16.11, 52%)

containerd (obrazy i warstwy) 16 GB · `uploads-data` 11,8 GB · `qdrant-data` 2,8 GB ·
journal 1,9 GB · `/root` 1,6 GB · `coolify-db` 0,4 GB · cache buildów 0. Postgres NEXUSA
leży na osobnym dysku (`sdc`, `postgres-data`), backupy na `sdb`. Linia bazowa między
seriami wdrożeń: 45% 02.11, 50% 16.11 (ok. 0,27 GB na dzień).

## Odczyt

```bash
ssh <host z prod-readonly.conf> 'tail -20 /var/log/nexus-build-cache.log; df -h /; docker system df'
```

Cofnięcie: `rm /etc/cron.d/nexus-build-cache`.
