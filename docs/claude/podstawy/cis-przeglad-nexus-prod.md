# Przegląd CIS nexus-prod (Wazuh SCA): co poprawione, co świadomie nie, co czeka na 05.12

28.11.2026, decyzje Artura z tego dnia. Źródło: polityka `cis_ubuntu24-04` agenta Wazuha na nexus-prod
(opis serwera Wazuha: `serwer-bezpieczenstwa.md`). Wynik 53% (127 zaliczonych / 110 niezaliczonych) → **66% (157/80)**
po poprawkach, bez nowych niezaliczonych. Wcześniejsze utwardzenie SSH, sysctl i Lynis: `ochrona-serwera-crowdsec-falco.md`.

Lista niezaliczonych na żywo: API Wazuha w tunelu WireGuard,
`GET https://10.66.0.1:55000/sca/001/checks/cis_ubuntu24-04?result=failed&limit=500`. Ponowny skan:
`systemctl restart wazuh-agent` na nexus-prod (ewaluacja trwa kilka sekund).

## Poprawione 28.11 (skrypt `/root/security-hardening/cis-apply.sh`, cofnięcie `cis-revert.sh`)

Kopie plików i uprawnień sprzed zmiany: `/root/security-hardening/backups/cis-20261128/`.

| Kontrole | Zmiana | Plik |
|---|---|---|
| 35613, 35614 | `secure_redirects=0`, `rp_filter=1` (all, default) | `/etc/sysctl.d/61-nexus-cis.conf` |
| 35604–35607 | moduły `dccp`, `tipc`, `rds`, `sctp` niedostępne | `/etc/modprobe.d/nexus-cis-net.conf` |
| 35543, 35545 | `* hard core 0`, apport wyłączony | `/etc/security/limits.d/60-nexus-cis-core.conf`, `/etc/default/apport` |
| 35547, 35548 | `/etc/issue`, `/etc/issue.net` bez nazwy systemu | — |
| 35640, 35643, 35647, 35652, 35657 | `sshd_config` 600; `AllowUsers root`, `DisableForwarding yes`, `LoginGraceTime 60`, `MaxStartups 10:30:60`, MAC-i tylko SHA-2/umac-128 etm | `/etc/ssh/sshd_config.d/61-nexus-cis.conf` |
| 35594–35601 | `/etc/crontab` 600, katalogi `cron.*` 700, `cron.allow` i `at.allow` = `root` | — |
| 35668 | `su` tylko dla pustej grupy `sugroup` (root ma `pam_rootok` wcześniej) | `/etc/pam.d/su` |
| 35708, 35719, 35588 | limity journald w głównym pliku (1 GB jak w `nexus.conf`), rsyslog `$FileCreateMode 0640`, `NTP=ntp.hetzner.com` w głównym `timesyncd.conf` | — |
| 35722 (częściowo) | logi w `/var/log` bez dostępu dla „innych” | — |
| 35517 | `/dev/shm` hosta `nodev,nosuid,noexec` (kontenery mają własne) | `/etc/fstab` |
| 35585 | bez klienta `telnet` | — |
| 35705 | bezczynna powłoka **interaktywna** wylogowana po 15 min | `/etc/profile.d/60-nexus-tmout.sh` |

Sprawdzone po zmianie: nowe połączenie SSH, `/api/health` 200, Coolify łączy się z hostem swoim kluczem
(`docker exec coolify ssh … root@host.docker.internal`) i ma serwer jako osiągalny, cron roota działa.
Zmiana szła z automatycznym cofnięciem po 10 min (`systemd-run --on-active=600 … cis-revert.sh`), wyłączonym po sprawdzeniu.

## Pułapki

- **Bez `Banner` w sshd.** Baner trafia do wyjścia każdego polecenia SSH, także tych, które wykonuje Coolify i
  parsuje wynik. Dlatego 35644 zostaje niezaliczona; plik `/etc/issue.net` jest poprawny.
- **TMOUT tylko w powłokach interaktywnych** (`case $- in *i*`): w skryptach i `bash -l -c` TMOUT przerywałby też `read`.
  `readonly` z osłoną, bo drugie wczytanie pliku dawałoby błąd „readonly variable”.
- **35509 (moduły systemów plików) nie do zaliczenia:** kontrola wymaga zablokowania m.in. `ext` i `fat`, a na nich
  stoją `/` i `/boot/efi`. Blokada = serwer bez dysku po restarcie.
- **Listy apt na hoście są nieświeże** (`apparmor-utils`, `python3-docker`: brak kandydata). Nie instaluj pakietów
  przed pełną aktualizacją 05.12, bo pojedynczy pakiet mógłby pociągnąć niezaplanowane aktualizacje zależności.
- `rp_filter`: jądro bierze maksimum z `all` i interfejsu, więc istniejące interfejsy z `2` zostają luźne do restartu;
  nowe (kontenery, restart 28.11) dostają `1`.
- 35664 (plik logu sudo) zostaje niezaliczona mimo `Defaults logfile=` w `/etc/sudoers.d/60-nexus-cis`; reguła SCA
  dla katalogu nie łapie pliku. Wpis w `/etc/sudoers` odpuszczony (konflikt `conffile` przy aktualizacji sudo).

## Świadomie nie dotyczy (zostają niezaliczone)

- **Partycje** `/tmp`, `/home`, `/var`, `/var/tmp`, `/var/log`, `/var/log/audit` (35510–35535): serwer w chmurze z
  jednym dyskiem systemowym. `/tmp` jako tmpfs: Artur 28.11 „nie” (pliki skryptów między restartami, `noexec` psuje instalatory).
- **Forwarding IP i zapory** (35608, 35619–35639): Docker wymaga forwardingu; UFW + łańcuchy Dockera + nftables
  bouncera CrowdSec to świadomie kilka narzędzi naraz (`ochrona-serwera-crowdsec-falco.md`).
- **Root przez SSH** (35659): Coolify zarządza serwerem jako root, tylko kluczami.
- **Polityki haseł i PAM** (35671–35698, 35703): logowanie wyłącznie kluczem; wygasanie hasła roota zablokowałoby
  logowanie kluczem (sshd wymusza wtedy zmianę hasła) i zerwało Coolify. `umask` roota zostaje, bo Coolify tworzy pliki jako root.
- **Hasło bootloadera** (35540): konsola tylko przez Hetznera.
- **IPv6 RA** (35618): adresacja Hetznera; zysk zerowy, ryzyko utraty IPv6.
- **rsync** (35573): klient bywa używany przez kopie; usługa nie działa.
- **Zdalne logi, AIDE** (35710, 35720, 35758, 35759): robi to agent Wazuha (logi + FIM).
- **chrony** (35591, 35592): czas z `systemd-timesyncd`.
- **Pliki utmp** w 35722 (`wtmp`, `btmp`, `lastlog` 660 `root:utmp`): tak ma być.

## Czeka na pełną aktualizację 05.12 (decyzje Artura 28.11)

- **auditd z wąskimi regułami** (35723–35726, 35756–35757): tożsamość, sudoers, SSH, czas, moduły jądra; bez
  śledzenia każdego `execve`. Potem `whodata` w FIM Wazuha.
- **AppArmor** (35536, 35537, 35539): `apparmor-utils`, przegląd profili w complain, `apparmor=1 security=apparmor`
  w GRUB razem z restartem 05.12 (nie przy restarcie bez nadzoru 28.11). AppArmor już działa, Docker używa `docker-default`.
