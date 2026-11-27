# Incydent bezpieczeństwa — kto, w jakiej kolejności, czym odciąć, co zachować, kogo zawiadomić

Runbook z 27.11.2026, po rotacji sekretów z 24–25.11 (hasło i APP_KEY panelu Coolify
oraz SECRET_KEY NEXUSA z publicznego commita działały do 24.11). Repo jest publiczne:
w tym pliku są role, nie nazwiska; telefony i adresy osób leżą w prywatnej liście
kontaktów firmy, nie w repo ani w logach Actions.

## Kiedy to jest incydent

Każde z poniższych, także „chyba”:

- sekret NEXUSA, Coolify, serwera albo dostawcy widziany tam, gdzie nie powinien
  (commit, log Actions, transkrypt, zrzut, mail);
- logowanie albo token, którego nikt z zespołu nie rozpoznaje (Entra, panel Coolify,
  GitHub, Cloudflare, SSH);
- dzwonek „Logowanie hasłem awaryjnym”, którego nikt z adminów nie rozpoznaje;
- dane kandydatów, klientów albo umów widoczne dla osoby bez uprawnienia, wyeksportowane
  hurtem bez powodu albo zmienione bez śladu w `activities`;
- alert Wazuh, CrowdSec albo Sentry o włamaniu, wykonaniu kodu, skanie zakończonym
  sukcesem;
- zgubiony albo skradziony laptop lub telefon z dostępem do kont operatorów.

Wątpliwość rozstrzyga się na korzyść incydentu: fałszywy alarm kosztuje godzinę,
przeoczone naruszenie kosztuje termin 72 h z RODO.

## Role

| Rola | Kto (funkcja) | Co robi |
|---|---|---|
| Prowadzący | właściciel techniczny NEXUSA (admin, konto 0 Coolify) | decyduje o odcięciu, prowadzi dziennik, zleca rotację |
| Zastępca | drugi operator Coolify (konto 1) | przejmuje, gdy prowadzący jest nieosiągalny 30 min |
| Zarząd | członek zarządu odpowiedzialny za dane | decyzja o zgłoszeniu do UODO i powiadomieniu osób, kontakt z klientami |
| IOD / osoba od RODO | jeśli wyznaczony; inaczej Zarząd | ocena ryzyka dla osób, treść zgłoszenia |
| Claude | sesja Claude Code | odczyt, zbieranie dowodów, przygotowanie poleceń; zmian na kontach i hasłach nie robi |

Claude nie zmienia ustawień bezpieczeństwa kont, haseł, MFA ani polityk Entra. Wyłączenie
konta, odwołanie sesji, usunięcie klucza i rotacja u dostawcy to kliknięcia człowieka
z tej tabeli. Claude przygotowuje dokładne kroki i sprawdza efekt.

## Kolejność

1. **0–15 min: zapisz i nie sprzątaj.** Otwórz dziennik incydentu (plik poza repo,
   np. w notatkach sesji): godzina wykrycia, kto wykrył, co dokładnie widział. Od tej
   godziny liczy się 72 h. Najpierw dowody z sekcji „Dowody”, które giną przy restarcie
   (`docker logs`), potem odcięcie.
2. **15–60 min: odetnij najmniejszym ruchem, który zamyka drogę.** Sekcja „Odcięcie”.
   Wyłączenie całego NEXUSA tylko wtedy, gdy nie da się odciąć konkretnej drogi.
3. **1–24 h: rotacja tego, co mogło wyciec.** Sekcja „Rotacja sekretów”.
4. **Do 72 h od wykrycia: decyzja o zgłoszeniu do UODO** (sekcja „RODO”), nawet jeśli
   dochodzenie trwa — zgłoszenie można uzupełniać.
5. **Po zamknięciu:** opis w `docs/claude/audyty/` (bez nazwisk i sekretów), strażnik
   w CI, jeśli błąd może wrócić, wpis w pamięci z datą.

## Odcięcie

Zawsze najpierw konkretna droga, potem szersza.

### Konto osoby (przejęte konto Microsoft, odejście w konflikcie, zgubiony laptop)

1. **Entra** (`entra.microsoft.com` → Użytkownicy → osoba): „Zablokuj logowanie”
   i „Odwołaj sesje”. Zgubione urządzenie: dodatkowo usuń metody MFA z tego urządzenia.
2. **NEXUS** (Ustawienia → Użytkownicy → osoba → nieaktywne). To konieczne: **wyłączenie
   konta w Entra nie wylogowuje z NEXUSA.** NEXUS wydaje własne tokeny (dostęp 8 h,
   odświeżanie 30 dni, `config.py` `ACCESS_TOKEN_EXPIRE_MINUTES`,
   `REFRESH_TOKEN_EXPIRE_DAYS`) i przy odświeżaniu nie pyta Microsoftu. Wyłączenie
   w NEXUSIE podnosi `authorization_version` i `tokens_valid_after`
   (`api/admin.py`, blok `authorization_changed`), więc każdy wcześniejszy token
   przestaje działać przy następnym żądaniu, także websocket (`api/ws.py`).
   Wyłączenie zwalnia też przypisania do rekrutacji
   (`uprawnienia/wylaczenie-konta-zwalnia-przypisania.md`).
3. **Skrzynka w NEXUSIE:** po zablokowaniu w Entra odświeżenie tokenu Graph tej osoby
   pada samo; nic więcej nie trzeba.
4. Jeśli osoba miała dostęp operatorski: sekcja „Dostęp operatorski” niżej.

### Wszystkie sesje NEXUSA naraz

- **Szybko, bez wdrożenia:** podłoga sesji dla wszystkich kont,
  `UPDATE users SET tokens_valid_after = now(), authorization_version = authorization_version + 1;`
  w bazie produkcji (zapis na produkcji — tylko na polecenie prowadzącego). Każdy loguje
  się ponownie przez Microsoft.
- **Gdy wyciekł klucz podpisu:** nowy `SECRET_KEY` (generator → sekret repo
  `SECRET_KEY_VALUE` → „Coolify set env” z `value_from_secret`, `redeploy=false` →
  wdrożenie). Wylogowuje wszystkich (ok. 40 osób). Wartości nie wypisuj nigdzie;
  sprawdzenie tylko `prod_readonly.py secret-check`.
- Wdrożenie w dzień roboczy poza oknem 18:00–08:00 tylko na „wdróż teraz” od prowadzącego.

### Konto awaryjne logowania hasłem

`PASSWORD_LOGIN_BREAK_GLASS_EMAILS` przepuszcza logowanie hasłem mimo trybu SSO-only,
czyli z pominięciem MFA Entra. Przy podejrzeniu, że jego hasło wyciekło: zmień hasło
(Ustawienia → Użytkownicy → reset hasła admina) albo wyłącz to konto; zmiana podnosi
`tokens_valid_after`. Opróżnienie listy wymaga „Coolify set env” i wdrożenia
(`podstawy/konto-e2e-na-produkcji.md` — lista ma też konto E2E).

### Dostęp operatorski

- **Panel Coolify:** allowlista IP w
  `/data/coolify/proxy/dynamic/coolify-panel-allowlist.yaml` (`sourceRange`); zostaw tylko
  bieżący adres prowadzącego, Traefik przeładuje sam. Konto osoby: Coolify → Team →
  usuń członka.
- **Tokeny API Coolify:** usuń konkretny token (Keys & Tokens → API tokens) albo wiersz
  w `personal_access_tokens`. **Nigdy nie zmieniaj hasła konta 0, żeby „wylogować
  wszystkich”:** Coolify kasuje wtedy wszystkie tokeny API tego konta i Deploy,
  set-env oraz Coolify Ops dostają 401 (24.11.2026). Hasło konta 0 zmienia tylko
  `/root/coolify-reset-root-password.sh`, który przywraca tokeny.
- **SSH:** usuń klucz z `/root/.ssh/authorized_keys` (kopia pliku przed zmianą do `/root`).
  Lista kluczy: `scripts/przeglad_dostepow.py`.
- **Sieć:** blokada adresu na hoście w łańcuchu `DOCKER-USER`
  (`iptables -I DOCKER-USER 1 -i eth0 -s <ADRES> -j DROP`) — UFW nie filtruje portów
  publikowanych przez Dockera. Jeśli działa CrowdSec: `cscli decisions add --ip <ADRES>
  --duration 24h`. Cloudflare (gdy API jest za proxy): reguła WAF „Block” dla adresu
  albo kraju, w ostateczności tryb „Under Attack”. Zapora Hetznera (Cloud Console →
  Firewalls) działa przed serwerem i przetrwa restart.
- **GitHub:** usuń członka albo współpracownika, usuń klucz wdrożeniowy
  (`gh repo deploy-key delete`), wyłącz workflow, który może być nadużyty
  (`gh workflow disable`), zrotuj sekrety repo.
- **Ostateczność:** zatrzymanie aplikacji NEXUS w Coolify (API: POST stop). Aplikacja
  przestaje działać dla wszystkich — decyzja prowadzącego z Zarządem.

## Dowody

Zbieraj przed restartem i przed sprzątaniem. Pliki trzymaj poza serwerem i poza repo
(zaszyfrowany dysk laptopa), z sumą `sha256sum` w dzienniku. Dane osobowe w dowodach
to też dane osobowe: tylko prowadzący i Zarząd.

| Źródło | Jak | Ile żyje |
|---|---|---|
| Logi backendu i frontu | `docker logs --timestamps <kontener> > plik` na serwerze, potem `scp` | do podmiany kontenera (wdrożenie 18:00) |
| Traefik (`coolify-proxy`) | `docker logs --timestamps coolify-proxy`; pliki dostępu tylko jeśli włączone w konfiguracji proxy | do restartu proxy |
| Tabela `activities` NEXUSA | `prod_readonly.py sql --csv` z zakresem dat | trwale |
| Entra: dzienniki logowania i inspekcji | portal → Dzienniki logowania → Pobierz (CSV/JSON) z filtrem osoby albo aplikacji | 7 dni na planie bez P1, 30 dni z P1 — pobierz od razu |
| GitHub audit log organizacji | Organizacja → Settings → Audit log → Export | 180 dni |
| Coolify | tabele `sessions`, `personal_access_tokens`, `activity_log` z `coolify-db` (odczyt) | trwale |
| SSH i system | `journalctl -u ssh --since …`, `/var/log/auth.log`, `last -F` | rotacja logów |
| CrowdSec | `cscli alerts list -o json`, `cscli decisions list -o json` | baza CrowdSec |
| Wazuh | alerty z managera Wazuh (eksport z dashboardu albo `alerts.json`) | retencja indeksu |
| Cloudflare | Security → Events, eksport | zależnie od planu, krótko |
| Sentry | zdarzenia z okresu (projekty `nexus-be`, `nexus-fe`) | retencja planu |
| Dysk serwera | migawka w Hetzner Cloud Console przed jakąkolwiek naprawą | do usunięcia |

## Rotacja sekretów

Na podstawie 24–25.11.2026. Zasada: nowa wartość nigdy nie trafia na ekran ani do logu.

1. **Lista:** co mogło wyciec (plik, panel, commit). Panel Coolify pokazuje wszystkie
   zmienne aplikacji, więc dostęp do panelu = rotacja wszystkich sekretów NEXUSA.
2. **Wartości u nas** (SECRET_KEY, hasło Postgresa, klucze podpisu stanu OAuth, tokeny
   wewnętrzne): wygeneruj prosto do sekretu repo (`gh secret set NAZWA_VALUE`), potem
   „Coolify set env” z `value_from_secret`, **jeden bieg naraz**, `redeploy=false`, na
   końcu jedno wdrożenie. Inputy workflow są publiczne — nigdy `value=` dla sekretu.
3. **Klucze u dostawców** (Entra client secret, Anthropic, OpenAI, Voyage, KSeF,
   B2/Object Storage, Slack, Sentry): nowy klucz wydaje człowiek w konsoli dostawcy, wkłada
   go do sekretu repo, dalej jak w kroku 2; stary unieważnia dopiero po teście na
   produkcji. Entra client secret pierwszy, bo od niego zależy logowanie.
4. **Hasło Postgresa:** rola w bazie i zmienna muszą się zmienić razem; 25.11 robił to
   strażnik `/root/rotacja-sekretow-2026-11-25/straznik-postgres.sh`.
5. **Coolify (APP_KEY, Pusher, Redis):** `/root/coolify-rotate.sh check|run`, potem
   `php artisan app-key:reencrypt`, stary klucz usuń z `APP_PREVIOUS_KEYS`
   (`/root/coolify-drop-previous-key.sh`).
6. **Dowód rotacji:** odcisk nowej wartości różny od starego (`fp.sh` w katalogu
   rotacji na serwerze, tylko odciski), `secret-check` = fresh, zielony `/api/health`.

Pułapki z 24–25.11: zmiana hasła konta 0 Coolify kasuje tokeny API; wartość
wielolinijkowa w zmiennej Coolify psuje każde wdrożenie; filtr `sed` bez `-n` wypisał
pełną wartość do transkryptu — filtruj `sed -n …p`; „Coolify set env” nadpisuje całą
wartość (listy typu break-glass: stara wartość + nowa).

## RODO

NEXUS przetwarza dane kandydatów, pracowników i osób kontaktowych klientów.
Dla kandydatów i pracowników firma jest administratorem; przy danych powierzonych przez
klienta — podmiotem przetwarzającym.

- **Rejestr naruszeń (art. 33 ust. 5):** każde naruszenie trafia do wewnętrznego
  rejestru, także niezgłoszone — co się stało, skutki, podjęte działania, uzasadnienie
  decyzji o zgłoszeniu albo jego braku.
- **Zgłoszenie do UODO (art. 33):** bez zbędnej zwłoki, **nie później niż 72 h od
  stwierdzenia naruszenia**, chyba że naruszenie raczej nie powoduje ryzyka dla osób.
  Formularz elektroniczny UODO (uodo.gov.pl → „Zgłoś naruszenie”). Po 72 h zgłoszenie
  zawiera wyjaśnienie opóźnienia. Brak części informacji nie wstrzymuje zgłoszenia —
  uzupełnia się je później.
- **Powiadomienie osób (art. 34):** bez zbędnej zwłoki, gdy ryzyko dla ich praw jest
  wysokie (np. wyciek CV z danymi kontaktowymi i stawkami, dokumentów umów, danych
  z dowodów). Treść: co się stało, kontakt, możliwe skutki, co zrobiliśmy, co osoba może
  zrobić. Wysyłka maili do osób z zewnątrz tylko po decyzji Zarządu.
- **Dane klienta (art. 33 ust. 2):** jako podmiot przetwarzający zawiadamiamy klienta
  bez zbędnej zwłoki; umowy powierzenia często skracają ten czas — sprawdź umowę
  danego klienta.
- **Do zgłoszenia potrzebne:** charakter naruszenia, kategorie i przybliżona liczba osób
  i rekordów (liczby z read-only SQL, bez wypisywania danych), prawdopodobne skutki,
  środki zaradcze, kontakt.

## Po incydencie

- Opis przyczyny i przebiegu w `docs/claude/audyty/` — bez nazwisk, adresów i sekretów.
- Błąd, który może wrócić, dostaje strażnika w CI (test, golden, skaner), nie tylko wpis
  w pamięci.
- Przegląd dostępów (`podstawy/dostepy-onboarding-offboarding.md`) od razu, nie przy
  najbliższym kwartale.
