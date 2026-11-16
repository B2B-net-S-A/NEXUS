# Zajętość wolumenu kopii w `/api/health` zapisuje cron na hoście
<!-- indeks: /etc/cron.d/nexus-backup-volume co 15 min, `backup-volume.json` w /var/lib/nexus-status, `backupVolumePercent` null od 23.09 do 16.11, PROD-01 z audytu 22.09, `/var/backups` symlink na sdb, disk-alert.yml próg 80%, retencja KEEP_PG=30 -->

Audyt 22.09.2026 (PROD-01) dodał do `/api/health` pola `backupVolumePercent`
i `backupVolumeCheckedAt` (`backend/app/services/host_status.py`) oraz montowanie
`/var/lib/nexus-status:/run/nexus-host-status:ro` w `docker-compose.yml`. Cron, który
miał zapisywać plik, nigdy nie trafił na host: katalog był pusty od 23.09, health
dawał `null`, a `disk-alert.yml` pomijał kontrolę z ostrzeżeniem. Zainstalowany
16.11.2026 za zgodą Artura.

Źródło w repo: `scripts/host/nexus-backup-volume-status.sh` (na hoście
`/usr/local/sbin/nexus-backup-volume-status.sh`) i `scripts/host/nexus-backup-volume.cron`
(na hoście `/etc/cron.d/nexus-backup-volume`). Błędy skryptu: `/var/log/nexus-backup-volume.log`
(pusty, gdy wszystko działa). Repo nie wdraża tych plików samo, więc po zmianie w repo
trzeba je skopiować ręcznie; zmiana na hoście to praca za zgodą Artura.

## Co robi skrypt

- Co 15 min `df -P -k` na celu symlinku `/var/backups` (wolumen `sdb`, `/mnt/HC_Volume_…`).
- Zapisuje atomowo (plik tymczasowy w tym samym katalogu + `mv`, prawa 0644, bo backend
  czyta jako `appuser`) `/var/lib/nexus-status/backup-volume.json`:
  `{"used_percent": 73, "avail_gb": 52.0, "checked_at": "…Z", "mount": "/mnt/HC_Volume_…"}`.
  `used_percent` to kolumna `Use%` z `df`, `avail_gb` w GiB jak w `df -h`.
- Gdy `/var/backups` wypada na `/` (wolumen odpięty) albo `df` jest nieczytelny, nie zapisuje
  nic i kończy się błędem. Plik się starzeje, po 2 h health daje `null`. Procent dysku
  systemowego nie udaje wtedy zajętości kopii.
- Nic nie kasuje i nie rusza Dockera.

Test na atrapie `df`: `backend/tests/test_host_backup_volume_script.py`.

## Kto to czyta

- `/api/health` → `backupVolumePercent` (liczba albo `null`, gdy plik jest starszy niż 2 h),
  `backupVolumeCheckedAt`.
- `disk-alert.yml`, job `backup-volume`: alarm (issue „NEXUS backup volume high”) od 80%.

## Stan 16.11.2026 i tempo wzrostu

Wolumen 197 GB (187 GiB dla `df` po rezerwie), 73%, 52 GiB wolne. Zawartość
`/var/backups/nexus`: 30 zrzutów Postgresa 132 GB, 28 snapshotów Qdranta 10,7 GB (4 przebiegi
po 7 kolekcji), zrzuty `coolify_db` 2,7 GB, `coolify_config` 25 MB.

Retencja w `/root/nexus-backup.sh` liczy pliki, nie bajty: `KEEP_PG=30` (komentarz zakłada
~265 MB na zrzut, dziś to ok. 6 GB), Qdrant `KEEP_QDRANT*4` plików, do tego `-mtime +30`.
Zrzut rósł z 1,7 GB (18.10) przez 4,8 GB (01.11) do 6,0 GB (16.11). Każdej nocy nowy zrzut
~6 GB wypiera najstarszy, a najstarsze są małe, więc wolumen przybywa o kilka GB na dobę.
Symulacja na tych rozmiarach (wzrost zrzutu 0,04–0,08 GB/dobę): 80% ok. 21–22.11,
90% ok. 28–29.11, 100% ok. 6–7.12. Nawet bez wzrostu zrzutu 30 × 6 GB + reszta to ok. 96%.

Pełny wolumen = nieudany `pg_dump`, częściowy plik kasowany, a przy liczeniu `KEEP_PG`
nic nie zwalnia miejsca, więc kolejne noce też bez zrzutu. Kopii poza serwerem nie ma
(`/root/nexus-offsite-backup.sh` kończy się co noc „konto off-site nie zostało założone”),
więc lokalne zrzuty to jedyna historia. Zmiana retencji jest decyzją Artura.

## Odczyt i cofnięcie

```bash
ssh <host z prod-readonly.conf> 'cat /var/lib/nexus-status/backup-volume.json; df -h /var/backups/; cat /var/log/nexus-backup-volume.log'
curl -s https://api.nexus.b2bnetwork.pl/api/health | jq '{backupVolumePercent, backupVolumeCheckedAt}'
```

Cofnięcie: `rm /etc/cron.d/nexus-backup-volume` (health wróci do `null` po 2 h).
