# 08 — Audyty Codexa (13–14.09.2026): weryfikacja i plan napraw

> Wejście: handoff z audytu ręcznego UI (53 pozycje B01–B53, katalog `outputs/manual-audit-2026-09-13/`,
> poza gitem) oraz pięć audytów tematycznych w `docs/`: integracje/monitoring/wdrożenia,
> procesy/uprawnienia/integralność, pokrycie testami i QA, statystyki, Traffit/ATLAS/COMPASS.
> Audyty pisano na rewizjach sprzed UAT P2 (#1508) i P3 (#1510). Każdą pozycję zweryfikowano
> w kodzie `origin/main` `86731771` (plik:linia). Pełna weryfikacja z dowodami i danymi
> produkcyjnymi: `wyniki/codex-2026-09-14/weryfikacja.md` (poza gitem).

## Wynik weryfikacji

| Źródło | Razem | Naprawione wcześniej | Do naprawy w kodzie | Poza kodem / decyzja |
|---|---:|---:|---:|---:|
| Handoff B01–B53 | 53 | 19 | 33 | 1 (B44 częściowo: próg = decyzja) |
| Integracje, monitoring, wdrożenia | 12 | 2 | 7 | 3 |
| Procesy, uprawnienia, integralność | 8 (+`docs/RBAC.md`) | 1 | 6 | 2 |
| QA | 12 | 0 | 3 | 9 |
| Statystyki | 9 | 0 | 8 | 1 (CloudTalk uśpiony) |
| Traffit / ATLAS / COMPASS | 10 | 0 | 2 | 8 (inne repozytoria) |

Naprawione przed tym planem (potwierdzone w kodzie, do retestu na produkcji):
B01, B02, B04, B05, B08, B09, B10, B11, B12, B15, B17, B18, B20, B30, B31, B32, B33, B36, B49
(UAT P1–P3: #1506, #1508, #1510), MON-03 (sonda M365, #1508), MON-06 (telemetria błędów
frontendu), nieaktualny `docs/RBAC.md` (#1345).

## Plan: trzy PR-y

Zasady jak w Fali 3 (`06-fala-3-poprawki-i-regresja.md`): gałąź od `origin/main`, agenci równolegle
na rozłącznych plikach, test do każdej poprawki (padający bez niej), przegląd adwersarialny przed PR,
retest na produkcji po wdrożeniu — audyt wymaga, żeby nie zamykać pozycji na podstawie lektury kodu.

### PR 1 — P1: integralność danych, uprawnienia, statystyki

| ID | Problem | Kierunek naprawy |
|---|---|---|
| B16 | Log aktywności admina generuje daty i identyfikatory losowo | odczyt istniejącego `GET /api/activities/feed` |
| F01 | Feedback z rozmowy może wskazać cudze spotkanie i innego kandydata | autoryzacja do wydarzenia + zgodność rekrutacji/kandydata przed zapisem |
| F02 | Router feedbacku nie egzekwuje polityki sekcji | `PIPELINE_SECTION_DEPENDENCIES` jak w sąsiednich routerach |
| F03 | Równoległe zmiany kontraktu mogą cofnąć stan `void` | `FOR UPDATE` w trzech handlerach zmiany statusu |
| F04 | Usuwanie kandydata kasuje pliki przed commitem, rollback ich nie przywraca | trwały rejestr kasowań (`cv_source_cleanup`) w tej samej transakcji |
| INT-01 | Kursor M365 przesuwa się mimo błędów importu; status `idle` mimo błędów | kursor tylko po czystej stronie, status `error` przy błędach |
| A01 | Raport uzgodnienia placementów mnoży wiersze przy wielu próbach, nie łączy par bez rekrutacji | dedup prób, `IS NOT DISTINCT FROM`, totale liczone niezależnie |
| A02 | Raport DL zalicza powtórny `hired` jako pierwszy placement | filtr po `first_reached_at` z widoku pierwszych milestone'ów |
| A03 | Wolne wakaty i fill rate klienta liczą surowe wiersze etapów | `count(distinct candidate_id)` |
| A04 | Kontrakt bez stawki kosztowej nie obniża jakości sumy finansowej | jakość `partial` + licznik brakujących nóg; ranking oznacza klienta jako niepełnego |
| A05 | Źródła kandydatów z Traffita nie trafiają do raportu źródeł | zdarzenie źródła emitowane przy imporcie, idempotentnie |
| MON-01 | Dzienny monitor Sentry kończy się sukcesem bez odczytu | brak tokenu / błąd API = czerwony bieg |
| DEP-02 | Wdrożenie nie sprawdza zgodności rewizji Alembica | krok smoke na `/api/health/alembic` |

### PR 2 — pozostałe pozycje handoffu (UI i drobny backend), sześć obszarów

| Obszar | ID |
|---|---|
| Shell i Ustawienia | B13, B14, B37, B38, B42, B43, B45, B51 |
| Kandydaci | B21, B22, B27, B28, B29, B35 |
| Rekrutacje, Champion, kalendarz | B07, B19, B34, B39, B40, B44 (tooltip), B47, B48 |
| Klienci i zamówienia | B03, B24, B26 (etykieta), B46, B50, etykieta kafla wartości zamówień po B30 |
| Kontrakty i finanse | B06, B23, B25, B41, B52, B53 |
| Statystyki i procesy P2 | A07, A08, A09, F05, F06 |

### PR 3 — monitoring i CI

MON-04/INT-10 (sonda świeżości cyklu życia COMPASS), INT-09 (świeżość per faza Traffit),
INT-02 (klucz replay webhooka M365), DEP-03 (wersja frontendu w smoke), DEP-01 (tylko log
target vs faktyczny SHA — koalescencja burstów zostaje), QA-01 (artefakty coverage per shard
i scalenie), QA-06 (burn-down 12 plików testów z listy `_FAILING`), QA-07 (macierz flag CV).

## Poza kodem NEXUS

- **Sekrety GitHub (blockery startu produkcyjnego, te same co w README):** klucz i dostęp S3 do
  kopii off-site + `BACKUP_MONITORING_ENABLED` (OPS-01, F08, QA-04); `SENTRY_AUTH_TOKEN` (MON-01);
  konto `E2E_USER_*` (MON-02, F07, QA-02 — test loginu oczekuje hasła, a produkcja ma tylko SSO:
  decyzja o koncie hasłowym wyłącznie dla E2E albo o stagingu); `CODECOV_TOKEN` (QA-01);
  triaż 7 znalezisk Trivy (QA-05).
- **Decyzje produktowe:** B44 próg wyścigu rekomendacji per osoba czy kalendarzowy; B26 „udział”
  względem lidera czy sumy; A06 CloudTalk pozostaje wyłączony (decyzja z 28.07); DEP-01 zostaje.
- **Inne repozytoria (audyt Traffit/ATLAS/COMPASS):** ATLAS INT-01, INT-03, INT-05, INT-08;
  COMPASS INT-02, INT-04, INT-06, INT-07 — osobne sesje w tamtych repozytoriach.
- **Dane na produkcji:** ponowne wgranie CV dla dwóch kandydatów testowych (B12).

## Stan

| PR | Gałąź | Stan |
|---|---|---|
| 1 | `fix/audit-p1` | scalony 14.09 (#1512, prod `75a1b8b3`) |
| 2 | `fix/audit-ui-p2-p3` | PR otwarty 14.09 |
| 3 | `chore/audit-ops` | po PR 2 |

Poprawki z przeglądu adwersarialnego PR 2 poza tabelą: redakcja kwot także dla
„Planowanych" na profilu; jedna reguła „obecnego" kontraktu na czterech
powierzchniach (profil, Analityka, Rada, admin); reset przeniesionego numeru
zamówienia na ścieżce z kolejki maila; `?event=` zdejmowany po nieudanym linku.
Poza PR 2 (osobny krok): front nie wysyła jeszcze `expected_state_version`
w ruchu pipeline'u (F05 działa po stronie serwera, kompatybilnie wstecz).

Retesty na produkcji: `wyniki/codex-2026-09-14/retest-<sha>.md` (poza gitem).
