# Serwer bezpieczeństwa `nexus-security` — Wazuh (SIEM) i DefectDojo (rejestr znalezisk), dostęp tylko przez WireGuard

Od 27.11.2026, po researchu bezpieczeństwa (decyzje Artura z 27.11). Osobny serwer, bo Wazuh
(OpenSearch) nie mieści się obok produkcji, a jego awaria nie może dotknąć NEXUSA.
Sekretów, adresów IP i list dostępu tu nie ma: repo i logi Actions są publiczne.

## Co gdzie stoi

| Element | Gdzie | Uwagi |
|---|---|---|
| Serwer | Hetzner Cloud, projekt NEXUS, `nexus-security`, CPX32 (4 vCPU, 8 GB, 160 GB), Nuremberg, Ubuntu 24.04 | Kopie Hetznera włączone (dzienne, 7 slotów). Adres IP w konsoli Hetznera. |
| Wazuh 4.14.11 single-node | `/opt/wazuh-docker/single-node` (Docker, upstream `wazuh-docker` tag `v4.14.11`) | Zmiany tylko w `docker-compose.override.yml` i `config/`, plik upstream bez zmian. |
| DefectDojo 3.5.300 | `/opt/django-DefectDojo` (Docker, tag `3.5.300`, obrazy z Docker Hub) | Obrazy przypięte w `.env` (`DJANGO_VERSION`, `NGINX_VERSION`). |
| Pliki NEXUSA dla Wazuha | `/opt/nexus-security/wazuh/` | Reguły lokalne, integracja `custom-nexus`, hasło rejestracji agentów, klucz ingestu. |
| Sekrety | `/root/nexus-security-secrets/` (700, pliki 600) + menedżer haseł Artura | Hasła Wazuha i DefectDojo, tokeny API, konfiguracje WireGuarda. |
| Agent Wazuha | nexus-prod, pakiet `wazuh-agent=4.14.11-1` z `packages.wazuh.com`, `apt-mark hold` | Wersja agenta nie może być wyższa niż managera: podbijaj razem. |

Koszt: 35,49 € + 0,50 € (IPv4) + 7,10 € (kopie) = 43,09 € netto/mies., ok. 53 € brutto.
CX43 (16 GB, 16,49 €) był wybrany, ale 27.11 był niedostępny we wszystkich lokalizacjach UE.
Gdy zabraknie pamięci: przeskalowanie CPX32 → CPX42 w konsoli (restart, bez reinstalacji).
Z mniejszego dysku na większy można; z powrotem już nie.

## Sieć: z internetu tylko SSH i WireGuard

- UFW: wejście tylko 22/tcp (wyłącznie klucze, `PasswordAuthentication no`) i 51820/udp (WireGuard).
- Porty Dockera omijają UFW, więc filtr jest w `DOCKER-USER` (`/usr/local/sbin/nexus-security-docker-user.sh`,
  jednostka `nexus-security-docker-user.service`, tak jak na nexus-prod). Z `eth0` do kontenerów dochodzą
  tylko 1514/1515 (agent Wazuha) z adresu nexus-prod. IPv6 z `eth0` do kontenerów: DROP.
- Tunel `wg0` 10.66.0.0/24: serwer `.1`, laptop Artura `.2`, joby CI `.10`–`.13`
  (`ci-semgrep`, `ci-deps`, `ci-zizmor`, `ci-trivy`). Peery CI widzą wyłącznie DefectDojo
  (`DOCKER-USER` + `ufw deny in on wg0 from 10.66.0.8/29`), nie widzą Wazuha ani SSH.
- Adresy w tunelu: dashboard Wazuha `https://10.66.0.1` (certyfikat z własnego CA, przeglądarka ostrzega),
  API Wazuha `https://10.66.0.1:55000`, DefectDojo `http://10.66.0.1:8080` (HTTP w szyfrowanym tunelu).
  Indeksator (9200) nie jest publikowany wcale.
- Sprawdzenie z zewnątrz: skan z laptopa bez tunelu ma dawać otwarte tylko 22.
  Nie wystarczy przeczytać reguł UFW (patrz `coolify-panel` w pamięci: Docker je omija).

## Wazuh: co zbiera i kiedy alarmuje

- Konfiguracja agentów jest centralna: `/var/ossec/etc/shared/default/agent.conf` w kontenerze managera.
  Agent pobiera ją sam i restartuje się. Sprawdzenie: `verify-agent-conf`.
  - FIM w czasie rzeczywistym: `/etc/ssh`, `/root/.ssh`, `/data/coolify/proxy`. Co 12 h: `/etc`, `/root`
    (bez zrzutów `.dump/.sql/.jsonl/.log/.gz`). `report_changes` wyłączone, bo diffy zawierałyby sekrety.
  - Logi: `/var/log/auth.log`, Falco `/var/log/falco/events.json`, Traefik `/var/log/traefik/access.log`
    (JSON), Docker i containerd z journald. Wodle `docker-listener` odpada, bo na hoście nie ma modułu
    python `docker` w apt.
  - Podatności pakietów: wbudowany `vulnerability-detection` z inwentarzem syscollectora.
- Reguły lokalne (`/opt/nexus-security/wazuh/local_rules.xml`):
  - Falco: Warning/Notice → 7, Error → 10, Critical/Alert/Emergency → 12.
  - Traefik: znane ścieżki skanerów → 6, 30 takich prób z jednego adresu w 60 s → 10,
    50 odpowiedzi 401/403 z jednego adresu w 60 s → 10.
  - FIM w `/etc/ssh/`, `/root/.ssh/`, `/data/coolify/proxy/` → 10 (100200).
- Progi: od 7 alert idzie do NEXUSA (ekran Ustawienia → Bezpieczeństwo, `docs/claude/ui/ekran-bezpieczenstwo.md`),
  od 10 mailem do Artura (postfix na hoście jako relay do konta SMTP, maks. 12 maili/h).
- Integracja `custom-nexus` wysyła do `POST /api/security/ingest/wazuh` tylko id, czas, regułę (id, poziom,
  opis, grupy) i nazwę agenta. `full_log`, `data` i `srcip` nie opuszczają serwera. Pusty klucz w
  `nexus_ingest.key` = integracja uśpiona.
- Retencja: polityka ISM `nexus-retencja-90d` usuwa `wazuh-alerts-*` i `wazuh-archives-*` po 90 dniach.
- Test: na nexus-prod `touch /etc/ssh/wazuh-fim-test.txt`, po ok. 10 s alert 100200 w
  `/var/ossec/logs/alerts/alerts.json` managera i mail; potem usuń plik (drugi alert, „usunięty”).

## DefectDojo: produkt i konta

- Produkt `NEXUS` (typ `NEXUS`), engagementy `CI tygodniowy` (CI/CD) i `Pentest` (Interactive).
- Konta bez hasła do logowania, tylko token: `ci-import` (import z `security-weekly.yml`)
  i `defectdojo-sync` (timer do NEXUSA). W DefectDojo 3.x nie ma ról Writer/Reader per produkt:
  dostęp daje lista `authorized_users` produktu (oglądanie, edycja, import; kasowanie tylko staff).
  `Product_Member` z rolą nic nie daje (tak było 27.11: 403 na `reimport-scan`).
- Import z CI przez WireGuard: sekrety Actions `DEFECTDOJO_TOKEN` i `DEFECTDOJO_WG_CONF_{SEMGREP,DEPS,ZIZMOR,TRIVY}`,
  po jednym peerze na job, bo równoległe joby na jednym kluczu wypierają się w WireGuardzie.
  W logu biegu tylko kod HTTP i liczby, bez treści znalezisk.
- Synchronizacja do NEXUSA: `nexus-defectdojo-sync.timer` co 30 min, skrypt `/usr/local/sbin/nexus-defectdojo-sync`,
  env `/etc/nexus-security/ingest.env`. Wysyła aktywne znaleziska w paczkach po 200 z jednym `run_id`,
  `complete: true` w ostatniej. Bez `description` (bywają tam dane). Bez klucza NEXUSA usługa się nie uruchamia.
- Hasło admina: `DD_ADMIN_PASSWORD` w `.env` nie dociera do initializera (compose go nie przekazuje), więc
  initializer wypisuje w logu losowe hasło. Ustawione potem przez `manage.py shell`, kontener initializera
  usunięty razem z logiem. Przy kolejnym `docker compose up` initializer znów wypisze „Admin password”, ale
  nie zmienia istniejącego konta.

## Obsługa

- Wpisanie sekretów, których Claude nie zna: `ssh -t root@<nexus-security> nexus-security-smtp` (konto SMTP do maili)
  i `nexus-security-keys` (klucze kont `wazuh-soc` i `defectdojo-sync` z NEXUSA). Hasła bez echa.
- Pliki montowane do kontenera managera (`local_rules.xml`, `authd.pass`, klucz) edytuj w miejscu.
  Podmiana pliku (`install`, `cp` na nowy inode, edytor z zapisem przez rename) zrywa bind mount:
  kontener widzi starą treść aż do `docker compose up -d --force-recreate wazuh.manager`.
- Rejestracja nowego agenta wymaga hasła z `authd.pass` (`use_password yes`).
- Aktualizacje: Ubuntu sam (unattended-upgrades, restart o 04:30 w razie potrzeby). Wazuh i DefectDojo ręcznie:
  nowy tag w repo upstream, podbicie wersji w `.env`/compose, `docker compose pull && up -d`; Wazuh razem z agentem.
- Instalacja odtworzeniowa: kopia Hetznera serwera (całe dyski z wolumenami Dockera).
