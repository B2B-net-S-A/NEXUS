# Ustawienia → Bezpieczeństwo: znaleziska, zdarzenia, rutyny (27.11.2026)
<!-- indeks: /settings?item=security, /api/security/*, webhook security:ingest (CrowdSec, Falco, Wazuh, CI, Grafana), DefectDojo, security-weekly z GitHub API, wyjątek z terminem, rutyny i dzwonek security_routine_overdue, migracja 0800, źródło grafana 0802, źródło defender 0807 (Microsoft Graph, incydenty, Secure Score, dzwonek security_defender_incident) -->

Decyzja Artura z 27.11.2026 (research „Tarcza NEXUSA”, „zbuduj wszystko
z raportu”). Jeden ekran admina zbiera skany CI, zdarzenia z serwera,
logowania, znaleziska do reakcji i terminy rutyn bezpieczeństwa, bo
wcześniej każde źródło było w innym miejscu albo w niczyjej pamięci.

## Ekran

- Pozycja `security` w obszarze System, grupa „Nadzór”, tylko admin.
  Zakładki `?zakladka=przeglad|rutyny` (jak w Importach).
- **Przegląd:** kafelki (skany CI, czeka na reakcję, blokady ruchu 24 h,
  logowania 24 h), lista „Czeka na reakcję” po wadze, wyjątki z terminem,
  trzy ostatnio zamknięte, zdarzenia na żywo, tabela źródeł. Źródło, którego
  jeszcze nie ma, to „nieskonfigurowane”, nie błąd.
- **Panel znaleziska** (`Sheet` z boku): gdzie, dowód, wpływ, właściciel
  (aktywny admin), kroki. „Otwórz sesję naprawy” kopiuje brief do nowej
  sesji Claude Code — NEXUS nie uruchamia sesji sam. „Wyjątek do…” wymaga
  powodu (≥ 10 znaków) i daty po dzisiaj, najwyżej rok. Po terminie
  znalezisko liczy się jako otwarte już przy odczycie
  (`security_screen.effective_status`), a pętla przestawia status i zostawia
  zdarzenie `exception_expired`. „Zamknij jako naprawione” przez `useConfirmV2`.
- **Rutyny:** kalendarz (tydzień/miesiąc) i tabela rytmu. Termin następnego
  przebiegu = wykonanie + rytm. Tygodniowy skan CI odhacza się sam z biegu
  `security-weekly.yml`; resztę odhacza admin („Zrobione”). Po terminie każdy
  aktywny admin dostaje dzwonek `security_routine_overdue` (mail od razu,
  kategoria awarii), raz dziennie (dedup w `emit`).
- Logowanie hasłem z listy awaryjnej (0803): zdarzenie `break_glass_login`
  (waga `high`, opis tylko „konto id (rola)”) i dzwonek
  `break_glass_password_login` z mailem do każdego admina — szczegóły
  w `podstawy/dostepy-onboarding-offboarding.md`.
- „Uruchom pełny skan” otwiera workflow w GitHub Actions (tam „Run workflow”).
  Świadomie bez tokenu z prawem uruchamiania workflowów na serwerze.

## Dane i prywatność

Tabele `security_findings`, `security_events`, `security_routines`,
`security_source_states` (0800, DDL: `app/services/security_schema.py`, lustro
w `entrypoint.sh`, sondy w `/api/health/deep`). Repo i logi Actions są publiczne,
a zdarzenia z serwera niosą adresy atakujących i loginy, więc
`security_ingest.scrub` zamienia w każdym tekście adresy IPv4/IPv6 na
`[adres IP]` i e-maile na `[e-mail]`. Z Falco i Wazuha zapisujemy tylko regułę
i kontener/agenta — nigdy `output`, `full_log`, `data`. Logowanie zostawia
wyłącznie wynik i kod błędu, bez osoby.

## Kontrakt dla źródeł

Wejście: klucz konta serwisowego ze scope'em `security:ingest` w nagłówku
`X-API-Key` (Ustawienia → Klucze API, jedno konto na źródło), limit
`SECURITY_INGEST_RATE_LIMIT` (120/min na konto). JWT admina nie działa (401),
klucz nie czyta ekranu. Źródło należy do konta, które pierwsze do niego
napisało (`security_source_states.owner_service_account_id`): inny klucz dostaje
403 `source_owned_by_other_account`, bo klucz Falco leży w pliku na serwerze
NEXUSA i bez tego mógłby zamknąć znaleziska DefectDojo pustym pełnym skanem.
Wyłączenie albo usunięcie konta zwalnia źródło; rotacja kluczy w tym samym
koncie go nie zwalnia.

- `POST /api/security/ingest` — format ogólny:
  `{source, scanner?, run_id?, complete?, events: [{occurred_at (ze strefą), kind,
  severity, summary ≤ 300, count, ref?}], findings: [{fingerprint, severity,
  title, location?, evidence?, impact?, steps?, detected_at?}]}`. Najwyżej 500
  zdarzeń i 200 znalezisk, nieznane pole = 422. Ten sam `(source, ref)` drugi
  raz jest pomijany. `complete: true` (wymaga `scanner`) zamyka jako naprawione
  otwarte znaleziska tego scannera, których nie ma w liście. Pełny skan w kilku
  paczkach: każda paczka niesie ten sam `run_id`, `complete` tylko ostatnia —
  zamyka się to, czego nie przyniosła żadna paczka biegu. Znalezisko
  naprawione, które wraca, otwiera się ponownie. Status ustawiony w NEXUSIE
  (wyjątek, właściciel) zostaje przy ponownym imporcie.
- `POST /api/security/ingest/falco` — zdarzenie Falcosidekicka (webhook,
  `customheaders: X-API-Key:…`), waga z `priority`.
- `POST /api/security/ingest/wazuh` — alert z integracji; waga z `rule.level`
  (≤3 info, 4–6 low, 7–9 medium, 10–12 high, ≥13 critical).
- `POST /api/security/ingest/grafana` (0802, zlecenie Artura 28.11.2026) —
  webhook kontaktu Grafany Cloud (unified alerting). W Grafanie: kontakt typu
  Webhook, URL `https://api.nexus.dynaminds.pl/api/security/ingest/grafana`,
  metoda POST, w „Extra headers” nagłówek `X-API-Key` z kluczem konta
  `grafana-nexus` (tylko scope `security:ingest`). Nie w „Authorization header”:
  `Authorization: Bearer` to w NEXUSIE miejsce na JWT, a klucz API jedzie
  wyłącznie w `X-API-Key` (`app/api/deps.py`, sekcja kont serwisowych).
  Każdy alert z `alerts[]`:
  - `firing` → znalezisko „czeka na reakcję”, klucz = `fingerprint` Grafany
    (powtórka co kilka minut aktualizuje ten sam wiersz), plus zdarzenie
    `alert_firing`;
  - `resolved` → zdarzenie `alert_resolved` i zamknięcie znaleziska jako
    naprawione (także z wyjątkiem); ten sam alert znów `firing` otwiera je
    ponownie.
  Waga z `labels.severity`: `critical`/`high` → wysoka, `warning` → średnia,
  reszta i brak → niska. Z alertu bierzemy tylko `labels.alertname` (tytuł),
  `labels.grafana_folder` (gdzie: „folder …”) i `annotations.summary` (dowód, po `scrub`).
  Pozostałych etykiet, `description`, `values`, `valueString` ani adresów
  (`generatorURL`, `silenceURL`) nie zapisujemy — bywa w nich instancja,
  adres albo login. Ref zdarzenia `grafana:<fingerprint>:<startsAt>:<status>`,
  więc ponowienie webhooka nie dubluje strumienia. Najwyżej 200 alertów
  w paczce (więcej = 422; w Grafanie zostaw domyślne grupowanie). Przykład:
  `tests/data/security/grafana_webhook_example.json`.
- Kafelek „Ruch z internetu” sumuje `count` zdarzeń CrowdSec `ban`
  i `appsec_block` z 24 h.

- **DefectDojo** (Semgrep, audyty zależności, zizmor, Trivy obrazów z CI) stoi
  za WireGuardem (decyzja Artura 27.11.2026), więc NEXUS go nie czyta: timer
  na serwerze bezpieczeństwa co 30 min wypycha aktywne znaleziska
  (`source: "defectdojo"`, `scanner: "defectdojo"`, `run_id`, paczki po 200).
  Każda paczka, także pusta, odświeża stan źródła (`security_source_states`).
  CI wysyła do DefectDojo raporty po zapadkach (bez przejrzanych wyjątków
  z repo, od 28.11.2026), więc „czeka na reakcję” z DefectDojo to nowe
  znaleziska i wyjątki po terminie. Fałszywy alarm wycisza się w pliku
  zapadki (`skanery-bezpieczenstwa.md`), nie wyjątkiem na ekranie: wyjątek
  na ekranie jest dla realnego problemu, który świadomie czeka.

- **Microsoft Defender** (0807, zlecenie Artura 28.11.2026): incydent High
  wisiał tydzień nieprzypisany w portalu, do którego nikt nie zagląda. NEXUS
  czyta go sam — patrz niżej.

## Źródło „Microsoft Defender” (NEXUS czyta sam)

Pętla `security_defender` (`tasks/security_defender.py`, reguły
`services/security_defender.py`) co 15 min (`DEFENDER_SYNC_INTERVAL_SECONDS`)
pyta Microsoft Graph v1.0:

- `GET /security/incidents?$expand=alerts&$top=50` cztery razy: `status eq`
  `active`, `inProgress`, `awaitingAction` oraz `lastUpdateDateTime ge` (30 dni);
  wynik łączony po id, strony po `@odata.nextLink` (tylko do
  `graph.microsoft.com`, najwyżej 20 stron na zapytanie);
- `GET /security/secureScores?$top=1` — Secure Score w procentach na kafelek.
  Błąd samego Secure Score zostawia ostatni pomiar, incydenty idą dalej.

Kontrakt jak pozostałe źródła (`source`/`scanner` = `defender`):
- incydent otwarty (każdy stan poza `resolved` i `redirected`) → znalezisko
  „czeka na reakcję”, klucz = id incydentu, waga z `severity`
  (`informational` → informacja, nieznana → średnia), zdarzenie
  `incident_open` (ref `defender:<id>:open`);
- `resolved`/`redirected` (scalony) → znalezisko zamknięte jako naprawione,
  także z wyjątkiem (notatka „Incydent zamknięty w Defenderze”), zdarzenie
  `incident_resolved`; incydent znów otwarty otwiera znalezisko ponownie;
- odczyt pełny (bez limitu stron) zamyka też otwarte znaleziska, których
  Defender już nie zwraca; błąd odczytu niczego nie zamyka;
- nowy, wznowiony albo podniesiony do High/Critical incydent → dzwonek
  `security_defender_incident` każdemu aktywnemu adminowi, mail od razu
  (kategoria awarii), dedup dzienny w `emit`.

Prywatność: tytuł to `displayName` po `scrub` (bez e-maili, więc bez UPN-ów,
i bez adresów IP). Dowód: kategorie alertów po polsku, liczba alertów, liczba
zasobów według typu („zasoby: 3 (adres IP 2, konto 1)”) i „przypisany /
nieprzypisany”. Wartości dowodów (konto, urządzenie, adres, temat maila),
`description`, `assignedTo` i `incidentWebUrl` (niesie id tenanta) nie są
zapisywane. Link „Otwórz w Defenderze” w panelu znaleziska i w zdarzeniach
składamy sami: `https://security.microsoft.com/incidents/<id>`.

Ekran: kafelek „Microsoft Defender” (otwarte incydenty, ile wysokich,
Secure Score) i wiersz w tabeli źródeł: bez rejestracji „nieskonfigurowane”,
przed pierwszym odczytem „czeka na pierwszy odczyt”, błąd → „błąd odczytu”
z kodem (np. `HTTP 403`, `token: invalid_client`), odczyt w ostatniej godzinie
→ „na żywo”. Na stagingu pętla zatrzymana (`app/core/staging.py`): kopia
produkcji nie dzwoni adminom incydentami z prawdziwego tenanta.

### Rejestracja aplikacji w Entra (klika Artur)

Osobna aplikacja, bo ta z `Mail.Send` przy wycieku sekretu pozwala wysyłać
maile; ta pozwala tylko czytać incydenty.

1. entra.microsoft.com → Aplikacje → Rejestracje aplikacji → Nowa
   rejestracja: nazwa „NEXUS Defender (odczyt)”, konta tylko w tej
   organizacji, bez adresu przekierowania.
2. Uprawnienia interfejsu API → Dodaj → Microsoft Graph → **Uprawnienia
   aplikacji**: `SecurityIncident.Read.All` i `SecurityEvents.Read.All`.
   Usuń domyślne delegowane `User.Read`. Potem „Udziel zgody administratora”.
3. Certyfikaty i wpisy tajne → Nowy klucz tajny klienta, ważny 12 miesięcy
   (wpisz termin w kalendarz rutyn — po wygaśnięciu źródło pokaże
   `token: invalid_client`). Wartość skopiuj od razu, potem jej nie widać.
4. GitHub → Settings → Secrets and variables → Actions → New repository
   secret `DEFENDER_CLIENT_SECRET` z wartością klucza. Sekretu nie wklejaj
   do pola `value` workflowu — `inputs` widać na stałe w podsumowaniu biegu.
5. Actions → „Coolify set env” (z gałęzi `main`), `redeploy=false`:
   - `key=DEFENDER_CLIENT_ID`, `value=<Identyfikator aplikacji (klienta)>`;
   - `key=DEFENDER_CLIENT_SECRET`, `value_from_secret=DEFENDER_CLIENT_SECRET`;
   - `DEFENDER_TENANT_ID` tylko wtedy, gdy tenant ma być inny niż
     `M365_MAIL_TENANT_ID` (domyślnie ten sam tenant co poczta).
   Na końcu jeden bieg „Deploy” (w dzień roboczy po 18:00).
6. Po wdrożeniu: Ustawienia → Bezpieczeństwo, w ciągu ok. 20 min od startu
   wiersz „Microsoft Defender” = „na żywo”, kafelek pokazuje otwarte
   incydenty i Secure Score. `HTTP 403` = brak zgody administratora albo
   uprawnienie delegowane zamiast aplikacyjnego.

NEXUS czyta sam GitHub Actions (pętla `security_sync`, co 30 min, na
stagingu zatrzymana): biegi `SECURITY_GITHUB_WORKFLOW` z `SECURITY_GITHUB_REPO`
i wyniki jobów ostatniego biegu (token `SECURITY_GITHUB_TOKEN` opcjonalny,
tylko dla limitu). Env na produkcji ustawia wyłącznie workflow „Coolify set env”.

Pilnują: `tests/test_security_screen_unit.py`, `tests/test_security_screen_api.py`,
`tests/test_security_defender_unit.py`, `tests/test_security_defender_api.py`
(przykład Graph: `tests/data/security/defender_*_example.json`),
wzorce `tests/data/authz_golden/security*.json`,
`frontend/src/components/settings/security/*.test.ts(x)`.
