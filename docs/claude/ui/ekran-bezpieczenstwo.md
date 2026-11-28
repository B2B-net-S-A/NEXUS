# Ustawienia → Bezpieczeństwo: znaleziska, zdarzenia, rutyny (27.11.2026)
<!-- indeks: /settings?item=security, /api/security/*, webhook security:ingest (CrowdSec, Falco, Wazuh, CI, Grafana), DefectDojo, security-weekly z GitHub API, wyjątek z terminem, rutyny i dzwonek security_routine_overdue, migracja 0800, źródło grafana 0802 -->

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

NEXUS czyta sam tylko GitHub Actions (pętla `security_sync`, co 30 min, na
stagingu zatrzymana): biegi `SECURITY_GITHUB_WORKFLOW` z `SECURITY_GITHUB_REPO`
i wyniki jobów ostatniego biegu (token `SECURITY_GITHUB_TOKEN` opcjonalny,
tylko dla limitu). Env na produkcji ustawia wyłącznie workflow „Coolify set env”.

Pilnują: `tests/test_security_screen_unit.py`, `tests/test_security_screen_api.py`,
wzorce `tests/data/authz_golden/security*.json`,
`frontend/src/components/settings/security/*.test.ts(x)`.
