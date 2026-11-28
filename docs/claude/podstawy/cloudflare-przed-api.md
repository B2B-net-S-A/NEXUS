# Cloudflare a API: stan faktyczny i plan przejścia (27.11.2026)

## Stan na 27.11.2026

Produkcja NEXUSA nie przechodzi przez Cloudflare. Przed aplikacją nie ma WAF-a ani
limitu z Cloudflare; ruch ograniczają `slowapi` (limity per trasa, `app/core/rate_limit.py`)
i limit ciała żądania (`app/core/body_size_limit.py`, 30 MB). Sprawdzone `dig` i `curl -sD -`:

| Host | DNS | Cloudflare | Rola |
|---|---|---|---|
| `nexus.b2bnetwork.pl` | home.pl, A → serwer | nie (`server` bez `cloudflare`) | front, główna domena od 19.10.2026 |
| `api.nexus.b2bnetwork.pl` | home.pl, A → serwer | nie (`server: uvicorn`) | API, z niego korzysta front (`NEXT_PUBLIC_API_URL`, CSP) |
| `api.nexus.dynaminds.pl` | Cloudflare, rekord DNS only | nie (`server: uvicorn`, brak `cf-ray`) | stary host API, nadal w routingu |
| `nexus.dynaminds.pl` | Cloudflare, proxy ON | tak (`cf-ray`) | tylko 307 na `nexus.b2bnetwork.pl` i wtyczka Outlooka |
| `coolify-nexus.dynaminds.pl` | Cloudflare, rekord DNS only | nie | panel Coolify (allowlista IP w Traefiku), `/api/` dla GitHub Actions |

Wpis „Cloudflare: proxy ON, OWASP CRS PL2, 10 req/min/IP” w `observability.md` był
skopiowany z ogólnego standardu (#111, 08.05.2026) i dla API nigdy nie był prawdą:
20.07.2026 (#824) sprawdzono brak `cf-ray` na `api.nexus.dynaminds.pl`. Nikt nie podjął
decyzji „API poza Cloudflare”; host od początku był „DNS only”, a 19.10.2026 cała
aplikacja przeszła na `b2bnetwork.pl`, którego strefa jest w home.pl, poza Cloudflare.

## Decyzja Artura z 27.11.2026

Zostajemy przy `slowapi` i CrowdSec przed Traefikiem, bez zmian DNS i zapory. Odrzucone
warianty: przeniesienie strefy `b2bnetwork.pl` do Cloudflare (ryzyko dla poczty M365 i
strony firmy) i powrót na `*.dynaminds.pl` (cofa decyzję o marce z 19.10). Plan niżej
zostaje na wypadek powrotu do tematu; nie proponuj go ponownie bez nowego faktu
(np. atak wolumetryczny, wymóg klienta).

## Czego nie ruszać „przy okazji”

- `client_ip_key` bierze prawy wpis `X-Forwarded-For` (dopisany przez Traefika), a gdy ten
  adres jest w zakresach Cloudflare, bierze `CF-Connecting-IP`. Spoza zakresów nagłówek
  jest ignorowany, bo ustawia go klient. Zakresy: `app/core/cloudflare_ips.py`; zmiana listy
  Cloudflare = poprawka tam i w zaporze serwera. Strażnik: `tests/test_rate_limit_key.py`.
- Strefa `dynaminds.pl` ma regułę Managed Challenge na każdej ścieżce `/api/auth/` (stąd
  callback SSO na `/auth/microsoft/callback`, #412). Zapytanie XHR nie przejdzie wyzwania,
  więc API za proxy w tej strefie wymaga zawężenia tej reguły do hosta frontu.

## Co Cloudflare by ucięło (plan Free)

- **Timeout 100 s do pierwszego bajtu odpowiedzi (błąd 524).** Synchroniczne wywołania modelu
  mają w przeglądarce 120 s (`SLOW_ENDPOINT_TIMEOUT_MS`, generator CV, Champion, poczta
  zamówień, formularze klienta 180 s), a backend daje modelowi 90 s × do 3 prób
  (`ANTHROPIC_TIMEOUT_SECONDS`, `ANTHROPIC_MAX_RETRIES`). Zmierzony ogon to 10–31 s, więc 524
  zdarzy się rzadko, ale wtedy backend skończy pracę i zapłaci za model, a człowiek zobaczy błąd.
  Rozkładu `duration_ms` z `http_outcome` z produkcji nie sprawdzono.
- **Ciało żądania do 100 MB.** U nas limit to 30 MB (`MAX_REQUEST_BODY_MB`), więc bez zmian.
  Czas wysyłki pliku nie liczy się do 100 s.
- **SSE Jarvisa** ma heartbeat co 10 s (`_HEARTBEAT_SECONDS`), **WebSocket** `/ws/notifications`
  Cloudflare przepuszcza na każdym planie. Bez zmian.
- **Ruch maszynowy**: webhooki Graph (`/api/microsoft365/webhooks`), Autenti (`/api/autenti/webhook`),
  API integracyjne v1 z kluczami kont serwisowych, GitHub Actions → `coolify-nexus`. Bot Fight
  Mode i wyzwania by je zablokowały, potrzebne reguły „skip” dla tych ścieżek.
- **WAF i limit na planie Free**: tylko Free Managed Ruleset (bez OWASP Core Ruleset, ten od
  planu Pro), jedna reguła rate limit z oknem 10 s liczona po IP. Limit „10/min” z dawnego
  wpisu wymaga planu Pro.

## Plan przejścia (gdy Artur powie „rób”; wdrożenia pon–pt 18:00–08:00 albo w weekend)

1. **Strefa.** Proxy Cloudflare działa tylko dla domen w strefie Cloudflare. Dla
   `b2bnetwork.pl` (home.pl) to przeniesienie serwerów nazw całej strefy: poczta (MX
   `hosting.b2bnetwork.pl`, SPF z `spf.protection.outlook.com`, DKIM/autodiscover M365),
   strona firmy i `kariera` muszą być przepisane rekord w rekord przed zmianą NS. Konfiguracja
   częściowa (CNAME) jest dopiero od planu Business. Alternatywa: powrót NEXUSA na
   `*.dynaminds.pl` (już w Cloudflare), co cofa decyzję o marce z 19.10.
2. **Kod przed proxy.** `client_ip_key` z `CF-Connecting-IP` jest już w kodzie. Gdy proxy obejmie
   front, `frontend/src/app/auth/microsoft/callback/route.ts` musi przekazywać też
   `cf-connecting-ip` (dziś tylko `x-forwarded-for`), inaczej callback SSO wróci do jednego
   kubełka. Audyt IP w `api/auth.py` (`request.client.host`) i dowód IP w podpisie
   (`api/b2b_esign.py::_client_ip`, lewy wpis XFF) liczą adres osobno — do przejścia na ten sam helper.
3. **Traefik i CrowdSec.** Allowlista panelu Coolify i bouncer CrowdSec widzą adres peera; za
   Cloudflare byłby to edge, więc ban albo allowlista objęłyby wszystkich. Przed proxy:
   `forwardedHeaders.trustedIPs` = zakresy Cloudflare na wejściu `https` i bouncer czytający
   `CF-Connecting-IP` tylko od tych zakresów; allowlistę panelu przenieść do reguły WAF
   Cloudflare (host `coolify-nexus`, poza `/api/`).
4. **DNS.** Proxy ON dla hostów API i frontu (i `coolify-nexus`, bo po kroku 6 port 443 jest
   tylko dla Cloudflare). SSL/TLS „Full (strict)”. Certyfikat: Let's Encrypt przez HTTP-01 działa
   za proxy, prostszy jest certyfikat Origin CA Cloudflare w Traefiku.
5. **Reguły Cloudflare.** Free Managed Ruleset; jedna reguła rate limit na `/api/auth/`
   (np. 20 żądań / 10 s / IP, blokada 10 s); skip Bot Fight Mode i wyzwań dla ścieżek z
   punktu „Ruch maszynowy”; reguła z `/api/auth/` zawężona do hosta frontu.
6. **Zapora.** Docker omija UFW, więc reguły tylko w `DOCKER-USER`, na `eth0`, porty po DNAT
   (80/443 Traefika), utrwalone jednostką systemd jak `coolify-panel-block.service`:
   przepuść `ESTABLISHED,RELATED`, przepuść 80/443 ze źródeł z `ips-v4`/`ips-v6` (ipset),
   odrzuć resztę 80/443. SSH 22 bez zmian (idzie przez INPUT/UFW). Opcjonalnie Authenticated
   Origin Pulls (mTLS Cloudflare → Traefik), bo zakresy Cloudflare to też Workers innych kont.
7. **Weryfikacja.** `dig +short api.nexus.b2bnetwork.pl` → adresy Cloudflare;
   `curl -sD - https://api.nexus.b2bnetwork.pl/api/health` → 200 z `cf-ray`;
   `curl --resolve api.nexus.b2bnetwork.pl:443:91.99.199.112 …` z sieci spoza Cloudflare →
   timeout; logowanie SSO; Jarvis (SSE), dzwonki (WS); bieg „Coolify Ops / list” zielony;
   w `http_outcome` różne klucze IP, nie adresy edge'a.

## CAA (rekordy ustalone 28.11.2026, wpisuje Artur)

Do 28.11.2026 żadna strefa nie miała CAA, więc certyfikat dla dowolnej naszej nazwy mógł
wystawić każdy urząd. Rekord na szczycie strefy obejmuje wszystkie subdomeny, a dla
subdomeny z CNAME-em liczy się CAA celu, gdy cel go ma (dziś `e-kursb2bnetwork.elms.pl` nie ma).
Dlatego lista wynika z wystawców każdej nazwy z ostatnich 13 miesięcy (crt.sh, indeks do
początku 10.2026) i z `openssl s_client` na każdym żywym hoście 28.11:

| Wystawca | Nazwy | Strefa |
|---|---|---|
| Let's Encrypt | `api.nexus.*`, `nexus.b2bnetwork.pl`, `kariera`, `coolify-nexus`, `coolify-staging`, strona firmy `b2bnetwork.pl` (+`www`, `webmail`, `admin`), `gitlab`/`qualrix`/`s3`, `vpn`, origin `elevate*` i `reports` za proxy, część `ekurs` | obie |
| Google Trust Services (`pki.goog`) | Universal SSL Cloudflare: `dynaminds.pl`, `www`, `nexus`, `elevate*`, `reports`, `nexus-staging`; `ekurs`/`www.ekurs` (CNAME do platformy na Cloudflare for SaaS) | obie |
| SSL.com | dziś brak certyfikatu, ale Cloudflare wystawia nim Universal SSL i SaaS zamiennie z LE i GTS | obie |
| Sectigo | certyfikaty zapasowe Cloudflare (`*.dynaminds.pl`, 05.2026) | `dynaminds.pl` |

Pominięte, bo nieużywane: GoDaddy (`dynaminds.pl` do 03.2026, strona przed Cloudflare),
cPanel i nazwa.pl (do 2023), home.pl/Certum (`b2bnetwork.pl`, 2022), DigiCert (2019).
`hosting.b2bnetwork.pl` (MX) podaje certyfikat `*.home.pl`, nie naszej nazwy.
`autodiscover` to CNAME do `autodiscover.outlook.com` (certyfikat Microsoftu dla jego nazwy).
Bez `issuewild`: wildcard idzie tą samą listą `issue` (Universal SSL `*.dynaminds.pl`).
Cloudflare przy Universal SSL i tak sam dokłada niewidoczne w panelu rekordy swoich
urzędów (widać je w `dig`), więc wpisy `pki.goog`/`ssl.com`/`sectigo.com` w `dynaminds.pl`
są jawną kopią tego, co i tak obowiązuje.

`dynaminds.pl` — Cloudflare → DNS → Add record → CAA, nazwa `@`:

```
0 issue "letsencrypt.org"
0 issue "pki.goog; cansignhttpexchanges=yes"
0 issue "ssl.com"
0 issue "sectigo.com"
0 iodef "mailto:postmaster@b2bnetwork.pl"
```

`b2bnetwork.pl` — panel home.pl → DNS strefy → CAA, host `@`:

```
0 issue "letsencrypt.org"
0 issue "pki.goog; cansignhttpexchanges=yes"
0 issue "ssl.com"
0 iodef "mailto:postmaster@b2bnetwork.pl"
```

Adres iodef to adres roli, który już odbiera raporty DMARC (decyzja Artura 28.11.2026).
Sprawdzenie po wpisie: `dig +short CAA dynaminds.pl` i `dig +short CAA b2bnetwork.pl`
pokazują powyższe wiersze (w `dynaminds.pl` także dopiski Cloudflare z `issuewild`).
Nowy dostawca, który wystawia certyfikat dla naszej nazwy (hosting strony, platforma
z CNAME-em, inny urząd w Coolify), wymaga dopisania jego urzędu tutaj i w strefie,
inaczej odnowienie certyfikatu się nie uda.
