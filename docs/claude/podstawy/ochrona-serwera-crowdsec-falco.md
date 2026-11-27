# Ochrona serwera produkcji: CrowdSec, Falco, Traefik, SSH (od 27.11.2026)

Stan po utwardzeniu nexus-prod 27.11.2026 (decyzje Artura z tego dnia). Konfiguracje
(bez kluczy i adresów IP) leżą w `serwer-ochrona/`; na serwerze kopie, raporty i skrypty
są w `/root/security-hardening/`. Usługi ochrony stoją poza Coolify, jako osobne projekty
compose, żeby wdrożenie NEXUSA ich nie odtwarzało.

## Co działa i gdzie

| Element | Na serwerze | Uwagi |
|---|---|---|
| CrowdSec 1.8.2 | `/opt/crowdsec` (kontener `crowdsec`, sieć `coolify`) | LAPI tylko `127.0.0.1:8180`; AppSec `crowdsec:7422` tylko w sieci Dockera |
| Bouncer w Traefiku | wtyczka `maxlerebourg/crowdsec-bouncer-traefik-plugin` v1.8.2 jako **lokalna** (`/data/coolify/proxy/plugins-local/`, commit b0431e2) | middleware `crowdsec@file` z `/data/coolify/proxy/dynamic/crowdsec.yaml` (600, klucz LAPI), podpięty do wejścia `https` |
| Bouncer firewalla | pakiet `crowdsec-firewall-bouncer-nftables` 0.0.38 (repo packagecloud CrowdSec) | tylko hook `input` (SSH i usługi hosta), tabele `crowdsec`/`crowdsec6`, nie `DOCKER-USER` |
| Falco 0.45.2 + Falcosidekick 2.35.1 | `/opt/falco` | modern eBPF bez `--privileged` (capabilities BPF, PERFMON, SYS_RESOURCE, SYS_PTRACE), reguły `rules.d/nexus-rules.yaml` |
| Log dostępu Traefika | `/var/log/traefik/access.log` (JSON, nagłówki poza User-Agent wycięte) | logrotate 14 dni (`/etc/logrotate.d/traefik-access`), bo zawiera adresy IP |
| SSH | `/etc/ssh/sshd_config.d/60-nexus-hardening.conf` | LogLevel VERBOSE, bez agent/TCP forwardingu, ClientAliveCountMax 2; tylko klucze było już wcześniej |
| Jądro | `/etc/sysctl.d/60-nexus-hardening.conf` | wartości sprzed zmiany w `backups/sysctl-przed-20261127.txt` |
| fail2ban | było przed zmianą, jail `sshd` | zostaje; dubluje się z CrowdSec tylko dla SSH |
| TLS | `/data/coolify/proxy/dynamic/tls-options.yaml` | TLS ≥ 1.2, w TLS 1.2 tylko szyfry AEAD, `sniStrict` (bez SNI, np. `https://<IP>`, brak połączenia); testssl 3.2 po zmianie: CBC „not offered”, LUCKY13 OK |
| HSTS panelu | middleware `coolify-panel-hsts` w `coolify-panel-allowlist.yaml` | 365 dni, includeSubDomains; API ma własny HSTS z aplikacji |

Wtyczka jest lokalna, bo zdalna (`experimental.plugins`) pobiera się z plugins.traefik.io przy
każdym starcie Traefika. Gdy pobranie się nie uda, middleware podpięty do wejścia `https` nie
istnieje i **wszystkie** hosty przestają działać. Nowa wersja = `git clone --depth 1 --branch <tag>`
do katalogu wtyczki, sprawdzenie commita tagu w API GitHuba, odtworzenie proxy (niżej, z sieciami).

Bouncer w Traefiku zawsze przepuszcza ruch, gdy CrowdSec nie odpowiada (`updateMaxFailure: -1`,
`streamStartupBlock: false`, `crowdsecAppsec*Block: false`): awaria ochrony nie może położyć NEXUSA,
także przy restarcie serwera, gdy Traefik wstanie przed CrowdSec.

## Tryb tylko-loguj i włączenie banów

Od 27.11 ok. 21:00 do przeglądu w ndz. 29.11 21:00 (zadanie z harmonogramu
`nexus-crowdsec-bany-2026-11-29`, decyzja Artura „sam po przeglądzie”):
- `cscli simulation enable --global` — decyzje scenariuszy są symulowane (`simulated=true`),
  bouncery ich nie dostają;
- AppSec z konfiguracją `custom/appsec-logonly` (reguły `vpatch-*` i `generic-*` poza pasmem:
  alert bez 403);
- bez listy społeczności (`DISABLE_ONLINE_API` w compose), bo jej decyzji symulacja nie obejmuje.

Włączenie: AppSec `custom/appsec-ban` (vpatch w paśmie), usunięcie `DISABLE_ONLINE_API`,
`cscli simulation disable --global`, restart `crowdsec`. Cofnięcie jedną komendą:
`docker exec crowdsec cscli simulation enable --global && docker restart crowdsec`.
Ręczna decyzja (`cscli decisions add`) działa też w symulacji: 27.11 doszła do nftables w ≤ 20 s.

Bany trwają 4 h (`profiles.yaml`). Kto dostał 403 albo nie może wejść po SSH:
`docker exec crowdsec cscli decisions list`, zdjęcie: `cscli decisions delete --ip <adres>`.

## Allowlista i fałszywe alarmy

`/opt/crowdsec/config/parsers/s02-enrich/nexus-whitelist.yaml` (adresy tylko na serwerze, repo jest publiczne):
- laptop Artura, sam serwer i serwer bezpieczeństwa z managerem Wazuha (decyzja Artura 27.11: ban zerwałby
  agenta, a skany z tego serwera nie mają banować); sieci Dockera i prywatne zakresy pomija już `crowdsecurity/whitelists`;
- GitHub Actions nie ma na liście adresów (to tysiące zakresów Azure). Pomijane są udane wywołania
  `/api/v1/` panelu Coolify (`coolify-nexus.dynaminds.pl`), a seria 401/403 nadal się liczy;
- `/api/health` (sondy dostępności).
IP laptopa się zmienia: przy blokadzie dopisz nowy adres tutaj i w allowliście panelu
(`coolify-panel-allowlist.yaml`), potem `docker restart crowdsec`.

Cloudflare: bouncer bierze `CF-Connecting-IP` wyłącznie od brzegów Cloudflare (lista jak w
`backend/app/core/cloudflare_ips.py`; zmiana listy = poprawka w obu miejscach), od innych peerów
adres połączenia. Brzegi Cloudflare whitelistuje `crowdsecurity/cdn-whitelist`. Przed włączeniem proxy
Cloudflare dla API (`cloudflare-przed-api.md`) Traefik musi dostać `forwardedHeaders.trustedIPs` na
wejściu `https`, inaczej log dostępu (`ClientHost`) i scenariusze HTTP zobaczą adres brzegu.

## Alerty bez banów

Scenariusze `nexus/*` (`serwer-ochrona/crowdsec/config/scenarios/nexus-alerts.yaml`) nie mają
`remediation`, więc tylko alarmują (`cscli alerts list`), nigdy nie banują:
- `nexus/http-401-403-series` — ponad 40 odpowiedzi 401/403 dla jednego adresu w krótkim czasie;
- `nexus/sso-denied` — 3 odmowy SSO z adresu (`/login?error=<kod odmowy>` po callbacku Microsoftu);
- `nexus/large-export` — odpowiedź eksportu CSV/XLSX z API ponad 20 MB.
Te same progi są regułami Loki w `alloy/loki-rules-bezpieczenstwo.yaml`. Alloy czyta log Traefika
(kody i tokeny w adresach maskowane przed wysyłką), ale ruszy dopiero, gdy Artur da token Grafana Cloud
i `COMPOSE_PROFILES` z `observability` przez workflow „Coolify set env” (27.11 zmienne `GRAFANA_LOKI_*`
w aplikacji były puste). Wtedy adresy IP i ścieżki trafiają do Grafana Cloud.

## Falco

Reguły własne: shell w kontenerze aplikacji (tty albo rodzic = proces aplikacji, healthchecki nie
pasują), odczyt `.env` Coolify, kluczy SSH Coolify, `authorized_keys` roota i plików aplikacji w
`/data/coolify/applications/`, nowy proces nasłuchujący spoza listy znanych. Do tego domyślne reguły
z obrazu (np. „Terminal shell in container”). Przy zgodności kilku reguł Falco zgłasza pierwszą.
Zdarzenia: `docker logs falco` (JSON), plik `/var/log/falco/events.json` (jedna linia JSON na zdarzenie,
logrotate `/etc/logrotate.d/falco-events`, 7 dni; czyta go agent Wazuha) i Falcosidekick. Pole `output`
w pliku zawiera linię poleceń, więc w Wazuhu może trafić sekret z argumentów. Webhook do NEXUSA
(`POST /api/security/ingest/falco`, nagłówek `X-API-Key` konta serwisowego ze scope'em `security:ingest`)
wpisuje się w `/opt/falco/sidekick.env` (600), potem `docker compose up -d` w `/opt/falco`.
Własne `docker exec … sh` w backendzie i czytanie `authorized_keys` przez sesje Claude'a też dają
zdarzenie — to zamierzone (ślad audytowy), nie błąd reguły.

## Pułapka: odtworzenie `coolify-proxy` zrywa ruch

Coolify dopina proxy do sieci aplikacji poleceniem `docker network connect`. Kontener odtworzony
z compose (`docker compose up -d` po zmianie) miał tylko sieć `coolify`, więc 27.11 od 19:58:15 do
ok. 20:00:40 UTC wszystkie hosty dawały 504 albo wisiały (56 błędów w logu dostępu). Naprawa:
`docker network connect ocgkwcbovpve9wvf9smxl0kx coolify-proxy` i to samo dla `nexus-front`.
Od tego dnia obie sieci są w `/data/coolify/proxy/docker-compose.yml`, a ta sama treść w bazie
Coolify (`servers.proxy.last_saved_proxy_configuration`, skrypt
`/root/security-hardening/coolify_db_proxy_sync.py`), żeby „Restart Proxy” w panelu jej nie cofnął.
Po każdej zmianie compose proxy: sprawdź sieci kontenera i `api/health` zaraz po starcie. Nowa
aplikacja w Coolify = nowa sieć do dopisania. Restart (bez odtworzenia) i reboot serwera sieci zachowują.

## Wyniki audytów (tylko odczyt)

- Lynis 3.0.9: hardening index 61 przed, 63 po SSH, 66 po sysctl. Ostrzeżenia, które zostają do 05.12:
  restart serwera (28.11), 10 pakietów z poprawkami (pełna aktualizacja 05.12). „Brak repo security”
  to fałszywy alarm Lynisa (nie czyta formatu deb822 z `ubuntu.sources`). Raporty: `reports/lynis-*.dat`.
- docker-bench-security v1.6.1: 117 testów, wynik −9. Większość to sposób działania Coolify (gniazdo
  Dockera w Traefiku, Sentinelu, Falco; porty 80/443) albo opcje demona (`live-restore`,
  `no-new-privileges`, `userland-proxy`, `icc`), które wymagają restartu dockerd — nie zmieniane.
- Świadomie bez zmian: uprawnienia `/data/coolify/source/.env` (644, katalog 700; kontener `coolify` montuje
  go tylko do odczytu jako swój `.env`), `.env` aplikacji (Coolify przepisuje je przy każdym wdrożeniu),
  `MaxSessions` SSH (Coolify multipleksuje połączenia).
- Coolify aktualizuje się sam co noc (`auto_update_frequency` 00:39): 27.11 o 00:45 wszedł 4.7.9.
  Po aktualizacji sprawdź allowlistę panelu (spoza listy `/login` 403, `/api/health` 200) i
  `coolify-panel-block.service`; 27.11 obie działały.

## Cofnięcie całości

1. Traefik: przywróć `/root/security-hardening/backups/proxy-docker-compose.yml.20261127T195725Z`,
   `docker compose up -d` w `/data/coolify/proxy`, od razu dopnij sieci aplikacji (wyżej), usuń
   `/data/coolify/proxy/dynamic/crowdsec.yaml`; bazę Coolify przywróć z
   `backups/coolify-servers-proxy-id0.20261127T195725Z.json`.
2. `docker compose down` w `/opt/crowdsec` i `/opt/falco`; `systemctl disable --now crowdsec-firewall-bouncer`.
3. Usuń `tls-options.yaml` z katalogu dynamicznego Traefika; HSTS panelu: kopia
   `/root/coolify-panel-allowlist.yaml.bak-20261127T204037Z`.
4. Usuń `60-nexus-hardening.conf` z `/etc/ssh/sshd_config.d/` (`systemctl reload ssh`) i z `/etc/sysctl.d/`.
