# Ustawienia → Bezpieczeństwo: znaleziska, zdarzenia, rutyny (27.11.2026)
<!-- indeks: /settings?item=security, /api/security/*, webhook security:ingest (CrowdSec, Falco, Wazuh, CI), DefectDojo, security-weekly z GitHub API, wyjątek z terminem, rutyny i dzwonek security_routine_overdue, migracja 0799 -->

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
`security_source_states` (0799, DDL: `app/services/security_schema.py`, lustro
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
klucz nie czyta ekranu.

- `POST /api/security/ingest` — format ogólny:
  `{source, scanner?, complete?, events: [{occurred_at (ze strefą), kind,
  severity, summary ≤ 300, count, ref?}], findings: [{fingerprint, severity,
  title, location?, evidence?, impact?, steps?, detected_at?}]}`. Najwyżej 500
  zdarzeń i 200 znalezisk, nieznane pole = 422. Ten sam `(source, ref)` drugi
  raz jest pomijany. `complete: true` (wymaga `scanner`) zamyka jako naprawione
  otwarte znaleziska tego scannera, których nie ma w liście; znalezisko
  naprawione, które wraca, otwiera się ponownie. Status ustawiony w NEXUSIE
  (wyjątek, właściciel) zostaje przy ponownym imporcie.
- `POST /api/security/ingest/falco` — zdarzenie Falcosidekicka (webhook,
  `customheaders: X-API-Key:…`), waga z `priority`.
- `POST /api/security/ingest/wazuh` — alert z integracji; waga z `rule.level`
  (≤3 info, 4–6 low, 7–9 medium, 10–12 high, ≥13 critical).
- Kafelek „Ruch z internetu” sumuje `count` zdarzeń CrowdSec `ban`
  i `appsec_block` z 24 h.

NEXUS czyta sam (pętla `security_sync`, co 30 min, na stagingu zatrzymana):
biegi `SECURITY_GITHUB_WORKFLOW` z `SECURITY_GITHUB_REPO` (token
`SECURITY_GITHUB_TOKEN` opcjonalny, tylko dla limitu) oraz aktywne znaleziska
DefectDojo (`DEFECTDOJO_URL` + `DEFECTDOJO_API_TOKEN`; adres `next` musi zostać
na tym serwerze). Env na produkcji ustawia wyłącznie workflow „Coolify set env”.

Pilnują: `tests/test_security_screen_unit.py`, `tests/test_security_screen_api.py`,
wzorce `tests/data/authz_golden/security*.json`,
`frontend/src/components/settings/security/*.test.ts(x)`.
