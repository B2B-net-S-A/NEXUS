# Ochrona serwera nexus-prod — konfiguracje

Kopie plików wdrożonych 27.11.2026 poza Coolify (opis, tryby i cofnięcie:
`docs/claude/podstawy/ochrona-serwera-crowdsec-falco.md`). Bez sekretów i adresów IP:
klucz LAPI w `traefik/crowdsec.yaml` to `__LAPI_KEY__`, adresy allowlisty są tylko na serwerze.

| Plik w repo | Na serwerze |
|---|---|
| `crowdsec/docker-compose.yml` | `/opt/crowdsec/docker-compose.yml` |
| `crowdsec/config/**` | `/opt/crowdsec/config/**` |
| `falco/docker-compose.yml`, `config.d/`, `rules.d/` | `/opt/falco/` |
| `falco/sidekick.env.example` | `/opt/falco/sidekick.env` (600, klucz `X-API-Key` wpisuje Artur) |
| `traefik/crowdsec.yaml` | `/data/coolify/proxy/dynamic/crowdsec.yaml` (600) |
| `traefik/tls-options.yaml` | `/data/coolify/proxy/dynamic/tls-options.yaml` |
| `traefik/coolify-proxy-docker-compose.yml` | `/data/coolify/proxy/docker-compose.yml` + `servers.proxy` w bazie Coolify |

Zmiana na serwerze = ta sama zmiana tutaj w PR-ze.
