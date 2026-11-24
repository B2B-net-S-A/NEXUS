# Wzrost danych na `/` produkcji: `uploads-data` na `sdc`, journal maks. 1 GB
<!-- indeks: dysk root 75 GB, linia bazowa 45% 02.11 → 50–56% 16.11, uploads-data 14 GB 0,135 GB/dzień, bind-mount z fstab jak postgres-data, /mnt/HC_Volume_105623192/uploads-data, _data.old, journald SystemMaxUse=1G, prognoza 70% / 90% -->

Decyzja Artura z 16.11.2026 (dwa pytania z wariantami i liczbami). Uzupełnia
`sprzatanie-cache-buildow-na-hoscie.md`: tamten plik dotyczy skoków dysku przy seriach
wdrożeń, ten dotyczy wolnego wzrostu danych między nimi. Zmiana na hoście to praca za
zgodą Artura. Nigdy `docker container/system/volume prune` (17.07 zabrało to `coolify-db`).

## Pomiar 16.11 (SSH tylko do odczytu, za zgodą Artura)

`/` 75 GB: 40 GB zajęte (56%), z tego 4,4 GB to obrazy do odzyskania, więc dane i obrazy
w użyciu to 35,6 GB (47%).

| Kategoria na `/` | GB 16.11 | Tempo |
|---|---|---|
| `uploads-data` | 14 | ok. 0,95 GB/tydz. = 0,135 GB/dzień (tyg. W39–W46, bez eBI24); archiwum eBI24 +2,5 GB jednorazowo 16.11 |
| ↳ CV w katalogu głównym (pdf/docx) | ok. 5 | 0,3–0,7 GB/tydz. |
| ↳ `microsoft365` (załączniki poczty) | 5,3 | 0,2–0,4 GB/tydz. (3,4 GB w sierpniu to pierwszy import) |
| ↳ `contracts`, `sales_files`, zamówienia, umowy ramowe | ok. 2,3 | razem poniżej 0,1 GB/tydz. |
| containerd (obrazy) | 16 | cyklicznie; Coolify sprząta obrazy dopiero powyżej 60% |
| `qdrant-data` | 2,7 | bez mierzalnego wzrostu (katalog kolekcji bez zmian od 09.10) |
| journal systemd | 1,8 | ok. 0,3 GB/mies.; `journald.conf` był pusty, więc limit domyślny 4 GB |
| `/root` (katalogi badań) | 1,6 | stałe |
| `coolify-db` | 0,4 | stałe |
| anonimowe wolumeny (1577) | 0,36 | ok. 400 nowych/mies., ok. 0,1 GB/mies. |

Tempo z dat modyfikacji plików (`find -printf %T`): liczy tylko pliki, które dalej leżą
na dysku. Postgres (`postgres-data`, 24 GB) i backupy nie leżą na `/`.

## Prognoza bez zmiany (z 16.11)

- Sama warstwa danych (0,15 GB/dzień od 35,6 GB): 70% ok. 9.03.2027, 90% ok. połowy czerwca 2027.
- Z obrazami, których Coolify nie sprząta poniżej 60% (tempo z `disk-alert.yml`,
  0,27–0,32 GB/dzień od 56%): 70% ok. 25.12.2026, 90% ok. połowy lutego 2027.
- Seria wdrożeń dokłada do ok. +20 GB nawet z cronem cache buildów, więc realna granica
  to linia bazowa ok. 65–70%, czyli luty–marzec 2027.

## Co zmieniliśmy

1. **Journal maks. 1 GB:** `/etc/systemd/journald.conf.d/nexus.conf` z `SystemMaxUse=1G`
   (źródło: `scripts/host/journald-nexus.conf`). Po restarcie journald 1,8 → 1,0 GB.
   Cofnięcie: `rm /etc/systemd/journald.conf.d/nexus.conf && systemctl restart systemd-journald`.
2. **`uploads-data` na `sdc`:** katalog `/mnt/HC_Volume_105623192/uploads-data`
   zamontowany bind-mountem z `/etc/fstab` na ścieżkę wolumenu, tak jak `postgres-data`:

   ```
   /mnt/HC_Volume_105623192/uploads-data /var/lib/docker/volumes/ocgkwcbovpve9wvf9smxl0kx_uploads-data/_data none bind 0 0
   ```

   Ścieżka i nazwa wolumenu się nie zmieniają, więc compose, Coolify, backend, worker
   i sidecar backupu (`uploads_data:/data/uploads:ro`) działają bez zmian w kodzie.
   Wolumen Hetznera `sdc` montuje się w fstab z `nofail`; gdyby nie wstał, bind-mount
   się nie powiedzie i backend wystartuje na pustym katalogu na `/`. Objaw: brak plików
   w aplikacji przy zdrowym `/api/health`. Pierwsza rzecz do sprawdzenia: `findmnt` niżej.

   Przełączone 16.11.2026 19:15 UTC, po wdrożeniu z 20:05 (kolejka Coolify pusta).
   Backend, worker i sidecar backupu stały 10 s. Po przełączeniu: 87 383 = 87 383 pliki,
   rozmiar identyczny, suma kontrolna próbki zgodna, zapis z backendu działa,
   `/api/health` healthy na `a47af6994`. `sdc` 26 → 40 GB (41%).

## Jak przełączaliśmy (do powtórzenia przy podobnym ruchu)

1. Kopia na żywo: `rsync -aHAX --numeric-ids <_data>/ /mnt/HC_Volume_105623192/uploads-data/`.
2. W oknie wdrożeń, gdy w Coolify nic nie stoi w kolejce: `docker stop` backendu,
   workera i sidecara backupu (wszystkie z `docker ps --filter volume=…_uploads-data`).
3. Drugi rsync z `--delete` (tylko różnica), `mv _data _data.old`, `mkdir _data`
   z tymi samymi uprawnieniami, wpis w fstab, `mount _data`.
4. `docker start` tych kontenerów. Kontenery trzeba restartować, bo mount zrobiony na
   hoście po starcie kontenera nie jest w nim widoczny.
5. Sprawdzenie: liczba plików i `du` źródła i celu równe, `/api/health` zdrowy, pobranie
   pliku w aplikacji.

## Cofnięcie

Od 24.11.2026 nie ma już kopii do szybkiego cofnięcia: `_data.old` jest skasowana (niżej),
więc uploads leżą tylko na `sdc` i w kopii zapasowej. Powrót na `/` to ten sam ruch
w drugą stronę: kopia na żywo z `sdc` do nowego katalogu na `/`, stop tych samych
kontenerów, drugi rsync, `umount <_data>`, usunięcie linii z `/etc/fstab`, podmiana
katalogu i start kontenerów. Najpierw sprawdź, czy `/` ma miejsce na całe uploads.

## Stara kopia `_data.old` — skasowana 24.11.2026

Skasowana na „tak” Artura. Przed kasowaniem (rutyna 23.11) mount i fstab były zgodne,
a health zdrowy. 20 plików było tylko w starej kopii (dokumenty umów i zamówień
z 27.08–13.11), ale żaden nie miał odwołania w bazie. Po kasowaniu `/` = 26 GB z 75 GB
(36%, `diskPercent` w `/api/health` 34).

Kasowanie z zabezpieczeniem, które nie rusza kopii, gdy `sdc` nie jest zamontowany:
`findmnt -n -o SOURCE <_data> | grep -q sdc && rm -rf <_data.old>`. Komenda SSH
podawana do uruchomienia na laptopie musi mieć `-i` z kluczem produkcji, bo
`~/.ssh/config` nie ma wpisu dla hosta. Pierwsza próba 24.11 bez `-i` niczego nie skasowała.

## Odczyt

```bash
ssh <host z prod-readonly.conf> 'findmnt /var/lib/docker/volumes/ocgkwcbovpve9wvf9smxl0kx_uploads-data/_data; df -h / /mnt/HC_Volume_105623192; journalctl --disk-usage'
```

`sdc` (99 GB) trzyma teraz Postgresa i uploads. Tempo wzrostu Postgresa nie jest
zmierzone (zrzuty `pg_dump` gz: 4,8 GB 02.11 → 6,0 GB 16.11). Wolumen Hetznera da się
powiększyć bez przestoju w konsoli (`resize2fs` po powiększeniu).
