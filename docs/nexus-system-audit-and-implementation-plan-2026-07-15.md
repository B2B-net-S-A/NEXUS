# NEXUS — pełny audyt systemu, rekomendacje i plan implementacji

> Data dokumentu: 2026-07-15
>
> Data zebrania dowodów produkcyjnych: 2026-07-14
>
> Status dokumentu: plan naprawczy do realizacji przez Opus w Claude Code;
> implementacja nie została rozpoczęta w ramach tego dokumentu
>
> Tryb audytu: read-only, bez lokalnego Dockera, bez zmian danych produkcyjnych
>
> Baseline końcowej weryfikacji produkcji:
> `31ae7caecac88941ae8fc3c4ec7c62fa9ff85cf5`

## 1. Cel dokumentu

Ten dokument jest kompletnym handoffem implementacyjnym. Ma pozwolić Opusowi:

1. odtworzyć podstawę każdego findingu,
2. wdrażać naprawy w prawidłowej kolejności,
3. nie połączyć niezależnych ryzyk w jeden monolityczny PR,
4. zbudować testy regresji i kryteria akceptacji,
5. przeprowadzić każdy krytyczny fix przez CI, merge, deploy i produkcyjną
   weryfikację,
6. zachować istniejący lokalny WIP i nie używać brudnego checkoutu jako
   baseline'u.

Dokument nie jest zgodą na destrukcyjne operacje. Zgodnie z kontraktem repo,
wyłączenie publicznej usługi, rotacja sekretów, usunięcie danych, destrukcyjna
migracja lub force-push wymagają odrębnej, jawnej decyzji właściciela.

## 2. Executive summary

NEXUS działa na produkcji i końcowo zweryfikowana rewizja była zgodna z
`origin/main`. Nie powinien jednak być traktowany jako w pełni bezpieczny ani
operacyjnie zdrowy.

Audyt wykazał:

- 3 problemy P0 wymagające natychmiastowego containmentu,
- ponad 20 problemów P1 obejmujących integralność danych, auth, migracje,
  integracje, CI/CD, backup i schedulery,
- rozległy backlog P2 w frontendzie, obserwowalności, uprawnieniach i jakości
  danych,
- false-green health: globalne `status=healthy` przy jednoczesnym
  `cloudtalk=unhealthy` i `traffit=degraded`,
- prawdopodobny drift schematu: produkcyjny snapshot wskazywał head `0152`,
  podczas gdy audit baseline repo miał head `0164`,
- realną awarię produkcyjnych Insights niewidoczną w globalnym healthchecku.

### Najważniejsza rekomendacja

Nie wdrażać wszystkich zmian jednym PR-em i nie zaczynać od kosmetyki UI.
Kolejność musi być następująca:

1. containment administratora, podpisów i destrukcyjnych endpointów,
2. read-only inventory produkcyjnego schematu,
3. naprawa migracji, readiness i Analytics,
4. fail-closed release gate,
5. revocable sessions, auth i privacy,
6. integralność procesów biznesowych i integracji,
7. dedykowany worker i idempotency,
8. poprawność frontendu,
9. backup, restore, observability i pełne CI.

## 3. Zakres i źródła dowodów

Audyt obejmował:

- snapshot `origin/main` zamiast lokalnego, brudnego WIP,
- publiczne `GET /api/health`,
- chronione `GET /api/admin/snapshot`,
- stan background tasks i Alembic raportowany przez produkcję,
- rzeczywiste ekrany produkcyjne w zalogowanym Chrome:
  - Dashboard,
  - Insights,
  - Settings i integracje,
  - Users,
  - Contracts,
  - Candidates,
  - Jobs,
  - Cortex,
- backend FastAPI, modele, migracje, entrypoint, auth, RBAC, signing,
  integracje i schedulery,
- frontend Next.js, middleware, klient API, cache, formularze i surfaces
  administracyjne,
- workflowy CI, deploy, E2E, uptime i backup drill,
- aktualne i draftowe PR-y związane z bezpieczeństwem i release hardening.

### Ograniczenia

- Nie wykonano bezpośrednich zapytań SQL do produkcyjnej bazy.
- Nie było bezpośredniego dostępu do pełnych logów Coolify, Loki, Sentry ani
  ustawień Cloudflare.
- Stan obiektów 0153–0164 musi zostać potwierdzony read-only inventory.
- Dokładna przyczyna timeoutu Insights musi zostać skorelowana z logami i
  planami zapytań.
- Nie uruchamiano lokalnego Dockera.
- Pełny lokalny pytest nie był miarodajny przy hostowym Pythonie innym niż
  wymagany Python 3.12; hosted CI pozostaje źródłem prawdy.

## 4. Zweryfikowany stan produkcji

Końcowa odpowiedź healthchecku wskazywała:

```json
{
  "status": "healthy",
  "version": "31ae7caecac88941ae8fc3c4ec7c62fa9ff85cf5",
  "deployedAt": "2026-07-14T21:18:02Z",
  "checks": {
    "database": "healthy",
    "m365": "healthy",
    "m365_encryption": "healthy",
    "cloudtalk": "unhealthy",
    "autenti": "unconfigured",
    "traffit": "degraded",
    "anthropic": "configured"
  }
}
```

Chroniony snapshot pokazał:

- expected background tasks: 23,
- running: 17,
- disabled: 5,
- completed: 1,
- crashed: 0,
- `slack_sla_alerts` w stanie `completed`,
- `signing_sweeper` jako running,
- `cloudtalk_sync` jako running,
- `traffit_sync` jako running,
- Alembic head `0152_cv_generated_async_status`.

W audit baseline repo graf migracji był scalony do
`0164_analytics_v1_kpi_defaults`. Projektowy kontrakt nadal wymaga używania
`alembic ... heads`, ponieważ w historii i na poszczególnych środowiskach
występowało wiele headów.

### Produkcyjne obserwacje UI

- Insights → „Lejek rekrutacyjny” kończył się błędem ładowania.
- Insights → „Źródła kandydatów” kończyły się błędem ładowania.
- CloudTalk zwracał błąd autoryzacji 401/403.
- Fireflies pokazywał błąd połączenia, brak udanego syncu oraz surowe fragmenty
  escaped HTML.
- System Admin raportował „Healthy” mimo awarii integracji.
- Lista Users renderowała 231 kont bez paginacji, wraz z kontami testowymi,
  duplikatami i placeholderami.
- Contracts zawierały liczne rekordy bez powiązanego joba.
- Candidates zawierało 53 783 rekordy.
- Jobs zawierało 4 028 rekordów, tylko 14 otwartych, wiele Draft i braków
  ownership/TAC.
- Cortex miał fakty dla 30 143 kandydatów, około 56% bazy.
- `/admin` zwracało 404 oraz błąd hydracji React #418.
- `/docs` i `/openapi.json` były publiczne.

## 5. Model priorytetów

| Priorytet | Znaczenie |
|---|---|
| P0 | Możliwe przejęcie administracyjne, błędne skutki prawne, nieodwracalna utrata danych lub aktywna ścieżka o krytycznym blast radius. Containment przed innymi zmianami. |
| P1 | Wysokie ryzyko bezpieczeństwa, integralności danych, niedostępności, błędnego wdrożenia lub prywatności. Naprawa przed dalszą rozbudową produktu. |
| P2 | Ważna poprawność, wydajność, UX, obserwowalność lub dług techniczny, ale bez natychmiastowego krytycznego blast radius. |
| DATA | Sygnał jakości danych wymagający raportu i decyzji biznesowej; nie wolno automatycznie kasować lub scalać danych. |

## 6. Findings P0

### NEXUS-P0-01 — produkcyjny bootstrap stałego administratora

#### Dowód

- [`backend/scripts/ensure_claude_admin.py`](../backend/scripts/ensure_claude_admin.py)
  tworzy lub aktualizuje stałe konto administratora.
- Skrypt posiada jawny fallback sekretu. Sekret nie jest cytowany w tym
  dokumencie i musi być traktowany jako ujawniony.
- Skrypt wymusza rolę administratora, aktywność konta oraz reset hasła.
- [`backend/entrypoint.sh`](../backend/entrypoint.sh) uruchamia go podczas
  startupu.
- [`.gitleaks.toml`](../.gitleaks.toml) szeroko allowlistuje ścieżki, w których
  znajduje się bootstrap.
- Konto zostało zaobserwowane jako aktywne w produkcyjnym UI.

#### Ryzyko

- trwały administracyjny backdoor odtwarzany po restarcie,
- znany lub przewidywalny sekret produkcyjny,
- zwykła zmiana hasła jest cofana podczas następnego startupu,
- secret scanning nie chroni tej powierzchni.

#### Docelowe rozwiązanie

1. Usunąć automatyczne wywołanie bootstrapu z entrypointu.
2. Usunąć skrypt albo zastąpić go ręcznym, jednorazowym poleceniem
   break-glass, którego nigdy nie uruchamia startup.
3. Usunąć szerokie allowlisty gitleaks.
4. Dodać kontrolny test secret-scanning dla `backend/scripts` i entrypointu.
5. Po wdrożeniu kodu:
   - zdezaktywować lub usunąć konto,
   - unieważnić jego sesje i tokeny,
   - przeanalizować logowania, eksporty, pobrania i zmiany ról,
   - wykonać decyzję o rotacji `SECRET_KEY` na podstawie możliwości
     unieważnienia aktualnych JWT i wyników audytu.

Operacje na koncie i rotacja sekretów wymagają jawnej decyzji właściciela.

#### Kryteria akceptacji

- Dwa kolejne restarty nie tworzą i nie modyfikują konta.
- Konto nie może wykonać uwierzytelnionego requestu.
- Kontrolny sekret w dawniej allowlistowanej ścieżce łamie CI.
- Obraz i entrypoint nie zawierają fallback hasła.
- Incident log zawiera zakres audytu i decyzję dotyczącą tokenów.

### NEXUS-P0-02 — podpis może zostać zaakceptowany bez wiarygodnego QES

#### Dowód

- [`backend/app/services/signing/pades.py`](../backend/app/services/signing/pades.py)
  zwraca dla lokalnej walidacji `is_qes=false` i stan typu
  `PRE_CHECK_ONLY`.
- [`backend/app/services/signing/sender.py`](../backend/app/services/signing/sender.py)
  nie wymusza fail-closed QES we wszystkich konfiguracjach DSS.
- Brak bezwarunkowego wymagania dla `valid`, `intact` i `trusted`.
- Liczba podpisów nie jest równoznaczna z liczbą unikalnych, autoryzowanych
  tożsamości.
- Zakończenie procesu może zapisać dokument, zmienić status i przesunąć
  kandydata w pipeline.
- Produkcyjny `signing_sweeper` był aktywny.

#### Ryzyko

- dokument może zostać uznany za prawidłowo podpisany mimo braku kwalifikowanej
  i zaufanej walidacji,
- ta sama osoba lub nieautoryzowany certyfikat może spełnić licznik podpisów,
- retry lub concurrency może wykonać submit więcej niż raz,
- wycofane albo zregenerowane linki mogą pozostać aktywne.

#### Containment

Po jawnej zgodzie właściciela:

1. zablokować `POST /api/public/sign/*/submit` na edge,
2. ustawić `SIGNING_ENABLED=false`,
3. dodać kill-switch do wszystkich publicznych metod signing,
4. nie włączać ponownie przed testami stagingowymi i akceptacją prawną.

Sama zmienna środowiskowa nie jest wystarczająca, dopóki endpointy publiczne
nie sprawdzają jej jawnie.

#### Docelowe rozwiązanie

- jednoznaczny model verdictu DSS,
- fail-closed dla: braku DSS, timeoutu, 4xx/5xx, malformed response,
  `TOTAL_FAILED`, braku `TOTAL_PASSED`, naruszenia integralności i nieufnego
  certyfikatu,
- walidacja każdego podpisu osobno,
- fingerprint certyfikatu, tożsamość i przypisana rola podpisującego,
- dwie strony oznaczają dwie różne autoryzowane tożsamości,
- atomowy submit:

```sql
UPDATE signing_links
SET used_at = now(), status = 'processing'
WHERE id = :id
  AND used_at IS NULL
  AND revoked_at IS NULL
RETURNING id;
```

- withdraw/regenerate unieważnia wszystkie stare linki,
- idempotency key i unikalność finalnego dokumentu,
- brak zmiany DB, pliku i pipeline przy niejednoznacznym wyniku.

#### Kryteria akceptacji

- DSS unset, timeout, 500, malformed JSON, `TOTAL_FAILED` i tampered document
  nie modyfikują DB, storage ani pipeline.
- Dwa równoległe requesty dają dokładnie jeden sukces.
- Stary link po withdraw/regenerate zwraca 410.
- Jedna tożsamość nie może podpisać obu stron.
- Produkcyjny smoke test potwierdza disabled state do czasu formalnego go-live.

### NEXUS-P0-03 — masowa nieodwracalna anonimizacja ma zbyt szerokie RBAC

#### Dowód

- [`backend/app/api/candidates_bulk.py`](../backend/app/api/candidates_bulk.py)
  przyjmuje do 500 ID i wykonuje nieodwracalne zmiany PII.
- Poza pasywnym viewerem endpoint jest dostępny dla szerokiego zestawu ról
  operacyjnych.
- Pojedyncze destrukcyjne operacje w innych częściach aplikacji mają wyższy
  próg uprawnień.
- Obecna „anonimizacja RODO” nie obejmuje jednoznacznie wszystkich klas danych:
  CV, `raw_cv_text`, plików, wiadomości, notatek, obiektów storage i wektorów.

#### Docelowe rozwiązanie

- osobne capability `candidate:erase` wyłącznie dla DPO/Admin,
- step-up authentication,
- obowiązkowy powód, ticket i podstawa prawna,
- dry-run pokazujący wszystkie dotknięte rekordy i pliki,
- asynchroniczny job z durable stanem,
- immutable audit before/after,
- jawna mapa retencji dla DB, storage, Qdrant, analityki i backupów,
- rozdzielenie anonimizacji operacyjnej od prawnego usunięcia.

#### Kryteria akceptacji

- recruiter, sourcer, TAC, DL i HoR dostają 403.
- Dry-run nie wykonuje żadnego zapisu.
- Każda operacja ma actor, effective user, powód, zakres i wynik.
- Test obejmuje wszystkie klasy PII.
- Błąd częściowy pozostawia resumowalny, audytowalny stan.

## 7. Findings P1 — platforma, schemat i integralność danych

### NEXUS-P1-01 — drift schematu i fail-open migracje

#### Problem

Produkcja raportowała head `0152`, podczas gdy audit baseline repo był na
`0164`. [`backend/entrypoint.sh`](../backend/entrypoint.sh) toleruje błąd
`alembic upgrade heads`, po czym wykonuje safety-net i `create_all`.
Aplikacja może zatem wystartować na częściowo zmigrowanym schemacie.

#### Rekomendacja

1. Wykonać read-only inventory:

```sql
SELECT version_num FROM alembic_version;

SELECT
  to_regclass('public.analytics_first_candidate_milestones'),
  to_regclass('public.analytics_candidate_first_sources'),
  to_regclass('public.analytics_latest_candidate_stages');

SELECT indexname
FROM pg_indexes
WHERE indexname LIKE 'ix_analytics_%';
```

2. Zinwentaryzować wszystkie tabele, kolumny, constraints, indeksy i widoki
   wprowadzane przez migracje 0153–0164.
3. Nie wykonywać `alembic stamp` bez obiektowego dowodu równoważności.
4. Odtworzyć produkcyjny backup na stagingu i przetestować migracje.
5. Docelowo przenieść DDL do jednorazowego migration joba z advisory lockiem.
6. Runtime DB user nie powinien mieć DDL.
7. Readiness musi wymagać dokładnego oczekiwanego zestawu headów i obiektów.

Do momentu wdrożenia nowego migration joba każdy nowy obiekt schematu nadal
musi przestrzegać aktualnego kontraktu repo i zostać odzwierciedlony
idempotentnie w `_COLUMN_STATEMENTS`. Usunięcie safety-netu następuje dopiero
po uzgodnionym cutoverze.

### NEXUS-P1-02 — produkcyjne Insights nie działają

#### Problem

Funnel i sources kończyły się po długim oczekiwaniu błędem widocznym dla
użytkownika. Globalny health tego nie wykrywał.

#### Rekomendacja

- pobrać correlation ID i logi endpointów,
- potwierdzić obecność analytics views i indeksów,
- na staging clone wykonać `EXPLAIN (ANALYZE, BUFFERS)`,
- na produkcji rozpocząć od `EXPLAIN` lub `pg_stat_statements`,
- zweryfikować semantykę okresu i strefy czasowej,
- wykorzystać PR #699 wyłącznie jako ograniczony hotfix po review,
- oddzielnie naprawić schemat, migracje i readiness.

#### Kryteria akceptacji

- funnel i sources zwracają 200 z poprawnym kontraktem,
- cold p95 < 5 s,
- warm p95 < 2 s,
- liczby zgadzają się z kontrolnym SQL,
- brak wymaganych obiektów powoduje readiness failure.

### NEXUS-P1-03 — publiczna aplikacja mutuje istniejącego kandydata

[`backend/app/api/public_share.py`](../backend/app/api/public_share.py) może po
podaniu znanego e-maila zmienić kanoniczne dane istniejącego kandydata, ownera,
CV i tekst CV.

Docelowo publiczna aplikacja tworzy immutable `CandidateApplication` albo
`InboundCandidate`. Dopasowany e-mail jest wyłącznie sugestią duplikatu.
Scalenie wymaga review lub OTP właściciela e-maila. CV jest wersjonowane z
provenance.

Kryterium: publiczny request nigdy bezpośrednio nie aktualizuje istniejącego
`Candidate`.

### NEXUS-P1-04 — endpoint GET może wykonywać zapis

Wspólny model sesji DB commitujący po requestach pozwala części tras GET
tworzyć draft, generować dokument lub modyfikować stan.

Naprawa:

- osobne read/write dependencies,
- GET/HEAD w read-only transaction,
- guard `before_flush` dla safe methods,
- inicjalizatory i generatory zmieniające stan jako POST,
- audit zawiera actor i effective user przy impersonacji.

### NEXUS-P1-05 — publiczne uploady bez kwarantanny

Walidacja opiera się głównie na rozszerzeniu/deklarowanym MIME. Brakuje magic
bytes, AV, kwarantanny i ograniczeń archiwów.

Naprawa:

- losowa nazwa storage,
- `basename` i containment check,
- extension + MIME + magic muszą być zgodne,
- kwarantanna i skan,
- ochrona przed ZIP bomb,
- publikacja dopiero po pozytywnym wyniku.

## 8. Findings P1 — auth, prywatność i RBAC

### NEXUS-P1-06 — refresh token w URL i brak revocable sessions

[`backend/app/api/auth.py`](../backend/app/api/auth.py) przyjmuje refresh token
w query parameter. Frontend przechowuje JWT w `localStorage`. Sesje nie mają
pełnej rotacji, family/reuse detection ani revocation po zmianie hasła.

Docelowo:

- HttpOnly, Secure, SameSite cookies,
- krótki access token,
- server-side session store,
- `jti`, session family, rotation i reuse detection,
- `token_version` użytkownika,
- revocation po password reset/change/deactivation,
- CSRF i walidacja `Origin`,
- backendowy `force_password_change`,
- nonce-based CSP.

### NEXUS-P1-07 — race condition Microsoft SSO exchange

SELECT i późniejszy UPDATE pozwalają dwóm równoległym requestom wykorzystać ten
sam exchange code.

Naprawa: atomowy `UPDATE ... WHERE consumed_at IS NULL RETURNING` albo blokada
rekordu. Test concurrency: jeden request 200, drugi 410.

### NEXUS-P1-08 — Outlook privacy opt-out nie jest retroaktywny

Po oznaczeniu e-maila jako prywatny mogą pozostać match, body i załączniki.

Naprawa:

- privacy check przed zachowaniem istniejącego matchu,
- unmatch,
- scrub body,
- usunięcie załączników,
- fail-closed direct fetch,
- test zmiany kategorii po wcześniejszym syncu.

### NEXUS-P1-09 — Fireflies ma globalny zapis przez GET

Sync jest stanową operacją GET dostępną szerokiemu `CurrentUser`. Notatki są
globalnie czytelne, a status ładuje rekordy zamiast użyć `COUNT(*)`.

Naprawa:

- POST,
- Admin/capability,
- distributed lock,
- scope kandydata/zespołu,
- SQL count,
- bezpieczne renderowanie treści.

### NEXUS-P1-10 — CloudTalk mapping ma zbyt szerokie uprawnienia

Lista agentów, sync i mapowanie użytkowników wymagają tylko aktywnego
użytkownika.

Naprawa:

- capability/AdminUser,
- UI gating,
- immutable before/after audit,
- naprawa konfiguracji 401/403,
- pozostawienie integracji disabled do czasu poprawnego provisioning.

### NEXUS-P1-11 — stawka klienta może zostać zmieniona bez financial access

Endpoint modyfikujący client rate ma słabszą ochronę niż odczyt wartości.

Naprawa:

- `require_financial_access`,
- scope/ownership,
- `Decimal`,
- optimistic lock,
- Activity z old/new value.

### NEXUS-P1-12 — WebSocket presence omija ACL zasobu

Aktywny użytkownik może subskrybować arbitralny candidate/job ID, a payload
ujawnia m.in. e-mail i rolę.

Naprawa:

- wspólny principal z HTTP,
- ACL konkretnego zasobu na subscribe/edit,
- resource existence check,
- usunięcie e-maila z broadcastu,
- limity subskrypcji,
- macierz testów rola × zasób.

### NEXUS-P1-13 — middleware frontendowy jest default-allow

Nieznane trasy mogą przejść bez auth, a force-password-change dotyczy tylko
ręcznie wybranych ścieżek.

Naprawa:

- jawna allowlista publiczna,
- wszystko inne protected,
- segment-aware matching,
- generowany route inventory w CI,
- test każdej nowej trasy.

### NEXUS-P1-14 — sekrety i tokeny mogą trafiać do logów

Powierzchnie:

- CloudTalk secret w URL,
- publiczne tokeny signing/share,
- JWT WebSocket w query,
- raw path/query w access logu,
- scrubber skupiony głównie na e-mailu i telefonie.

Naprawa:

- logowanie route template zamiast raw URL,
- redakcja `token`, `code`, `state`, `secret`, `authorization`,
- HMAC-only CloudTalk webhook,
- cookie/subprotocol dla WebSocket,
- test markera, który nie może pojawić się w stdout, Coolify, Loki ani Sentry,
- po wdrożeniu kontrolowana rotacja tokenów na podstawie decyzji właściciela.

## 9. Findings P1 — integracje i praca asynchroniczna

### NEXUS-P1-15 — Traffit może przesunąć watermark mimo błędów

Ryzyka:

- rollback batcha może wycofać wcześniejsze poprawne rekordy,
- liczniki mogą pozostać zawyżone,
- malformed JSON może zostać pominięty,
- błędna strona `/sources` może zostać pominięta,
- watermark może zostać przesunięty mimo częściowego niepowodzenia.

Naprawa:

- savepoint lub commit per batch,
- liczniki dopiero po commit,
- typowane wyjątki,
- durable failed page/ID queue,
- watermark fazy tylko po pełnym sukcesie,
- dependency gating faz,
- reconciliation report.

Nie wykonywać produkcyjnego replay przed naprawą. Wznowienie od ostatniego
udowodnionego dobrego punktu wymaga osobnego planu operacyjnego.

### NEXUS-P1-16 — schedulery uruchamiają się w każdej replice API

[`backend/app/main.py`](../backend/app/main.py) uruchamia wiele pętli w lifespan.
Rolling deploy lub skalowanie może dublować vendor calls, e-maile i joby.

Naprawa:

- osobny worker,
- PostgreSQL advisory lease,
- fencing token,
- heartbeat,
- durable inbox/outbox,
- idempotent manual triggers,
- idempotent webhook processing.

### NEXUS-P1-17 — CloudTalk legacy secret-in-URL i webhook race

Naprawa:

- usunąć legacy secret URL,
- pozostawić HMAC signature,
- zweryfikować timestamp/replay window,
- `INSERT ... ON CONFLICT DO UPDATE` po `cloudtalk_call_id`,
- przejrzeć logi i zdecydować o rotacji webhook secret.

### NEXUS-P1-18 — UI potwierdza e-mail, którego backend nie wysłał

[`backend/app/api/emails.py`](../backend/app/api/emails.py) ma ścieżkę
symulującą wysłanie i zapisującą `email_sent`. Frontend zawsze pokazuje
„Email wysłany”.

Naprawa:

- użyć M365 sendera,
- zapisywać event dopiero po potwierdzeniu providera,
- zachować `provider_message_id`,
- brak połączenia = 412,
- failure nie tworzy „sent”,
- outbox i idempotency.

## 10. Findings P1 — CI/CD, backup i observability

### NEXUS-P1-19 — deploy może wystartować przed wynikiem CI

CI i deploy reagują niezależnie na push do `main`.

Naprawa:

- deploy przez `workflow_run` albo reusable release workflow,
- dokładny SHA,
- aggregate required check,
- GitHub Production Environment,
- branch protection,
- wspólny smoke helper z:

```text
User-Agent: dynaminds-smoke-test/1.0
```

- weryfikacja `version`, nie tylko HTTP 200.

### NEXUS-P1-20 — gitleaks ma szerokie blind spots

Naprawa:

- wyjątki tylko dla precyzyjnych fingerprintów,
- owner i data wygaśnięcia wyjątku,
- skan working tree i historii,
- pinowana wersja i checksum narzędzia,
- fake-secret regression test.

### NEXUS-P1-21 — CI obejmuje tylko część testów i ma nieblokujące skanery

Zaobserwowane ryzyka:

- selektywny backend pytest pomija znaczną część suite,
- Hadolint `continue-on-error`,
- Trivy z nieblokującym exit code,
- Codecov bez twardego progu,
- Next build może ignorować TS/ESLint.

Naprawa:

- pełne `pytest tests -m "not live"` w shardach,
- wymagany aggregate gate,
- blokujące skanery,
- usunięcie `ignoreBuildErrors`,
- changed-lines coverage,
- późniejsze stopniowe podnoszenie globalnego coverage.

### NEXUS-P1-22 — nightly E2E może mutować produkcję

Naprawa:

- osobny staging tenant,
- produkcja wyłącznie read-only smoke za jawną flagą,
- cleanup failure = failure,
- końcowa kontrola braku osieroconych rekordów,
- usunięcie lub zaplanowanie wszystkich `fixme`.

### NEXUS-P1-23 — brak kompletnego backupu uploadów

Naprawa:

- szyfrowany offsite backup `uploads_data`,
- manifest i checksumy,
- retencja i freshness alert,
- docelowo object storage z versioningiem,
- restore test: DB + plik + authenticated download.

### NEXUS-P1-24 — backup drill może być fałszywie zielony

Naprawa:

- brak sekretu/config = failure,
- restricted account i pinned SSH fingerprint,
- strict `pg_restore`,
- freshness/checksum/Alembic/constraints/relational checks,
- izolowany recovery runner,
- Qdrant i uploady w tym samym drill.

### NEXUS-P1-25 — Alloy może mieszać logi innych aplikacji

Naprawa:

- dokładny filtr projektu i usług,
- osobny tenant/credentials Loki,
- obraz przypięty digestem,
- socket proxy z minimalnym API,
- test negatywny dla obcego kontenera.

### NEXUS-P1-26 — health jest false-green

Naprawa:

- `/livez`: tylko proces,
- `/readyz`: DB, schema heads/objects, Qdrant, worker lease i required
  integrations,
- `/api/health`: stabilny publiczny kontrakt,
- snapshot używa tego samego health service,
- vendor checks cache'owane,
- jawna konfiguracja required/optional dependency.

### NEXUS-P1-27 — Audit Log pokazuje wygenerowane dane

Frontendowy Audit Log generuje część danych przez `Math.random()` i prezentuje
je jak prawdziwe zdarzenia.

Naprawa:

- natychmiast ukryć albo oznaczyć jako demo,
- append-only audit events,
- actor/effective user,
- request ID,
- before/after,
- filtry i paginacja.

## 11. Backlog P2

Poniższe pozycje należy rozpisać jako osobne tickety po domknięciu P0/P1:

1. Case-sensitive porównania e-maili w auth.
2. Możliwe 500 dla kont SSO z `password_hash=None`.
3. Timing enumeration w części ścieżek auth.
4. Synchroniczny SMTP w async requestach.
5. Bezpośrednie porównania `.role` mimo modelu wielu ról.
6. Stawki zapisane lub renderowane jako `int` zamiast `Decimal`.
7. `useQuery` wywoływany wewnątrz `map`.
8. Niespójne query keys i brak invalidacji po create/import/move.
9. Kanban optimistic move bez rollbacku.
10. Daty biznesowe przez `toISOString().slice(0, 10)`, ryzyko off-by-one w
    Europe/Warsaw.
11. Contractors pobierający wyłącznie pierwsze 50 rekordów.
12. Wyszukiwanie candidates/jobs/clients bez debounce, cancellation i
    `keepPreviousData`.
13. Authenticated file helper mogący wysłać bearer do arbitrary absolute URL.
14. Sortowanie hit-ratio tylko na bieżącej stronie.
15. Brak części semantic tokens i tysiące raw-color utilities.
16. Custom modal bez właściwych dialog semantics i focus trap.
17. Brak skip link.
18. Wystawiony upload XLSX kończący się deterministycznym TODO error.
19. Integracyjne karty Settings montowane dla ról bez uprawnień.
20. Lista Users bez paginacji i server-side search.
21. `/admin`: 404 i hydration mismatch.
22. Publiczne `/docs` i `/openapi.json`.
23. Brak kompletnego backendowego `.dockerignore`.
24. Kod aplikacji zapisywalny dla runtime usera.
25. Sentry token jako build ARG.
26. Wspólny root env dla wielu usług.
27. Mutable image tags.
28. Zbyt szeroki CORS dla rozszerzeń Chrome.
29. Niewystarczająca walidacja `SECRET_KEY`.
30. Fallback klucza stanu M365.
31. Sentry ignorujący wszystkie Axios `Network Error`.
32. Rozjazd komentarza uptime z realnym harmonogramem.
33. `slack_sla_alerts` przechodzący do `completed` zamiast działać albo jawnie
    raportować disabled.

## 12. Sygnały jakości danych

Te pozycje nie upoważniają do automatycznego usuwania ani scalania:

- około 44% kandydatów bez faktów Cortex,
- nierozwiązane duplikaty kandydatów,
- nazwy zawierające `[zatrudniony]`,
- duża liczba starych Draft jobs,
- Draft jobs z kandydatami w pipeline,
- brak ownera/TAC,
- kontrakty bez joba,
- testowe, placeholderowe i zduplikowane konta użytkowników.

### Rekomendowany reconciliation flow

1. Read-only raport CSV/JSON.
2. Dla każdej pozycji: evidence, confidence, proponowana akcja.
3. Review przez właściciela domeny.
4. Dry-run zaakceptowanej operacji.
5. Backup/restore proof.
6. Mały batch canary.
7. Raport before/after.
8. Dopiero potem kolejne batch'e.

## 13. Instrukcja startowa dla Opus

### 13.1. Izolacja pracy

Nie używać istniejącego brudnego checkoutu i nie wykonywać
`reset`/`checkout --`/`stash` na pracy innych zadań.

```bash
cd /Users/arturtwardowski/NEXUS
git fetch origin
git worktree add ../NEXUS-opus-p0 -b fix/p0-containment origin/main
cd ../NEXUS-opus-p0
git log origin/main..HEAD
git status --short
```

Jeśli docelowy katalog worktree już istnieje, wybrać inną, jednoznaczną nazwę.

### 13.2. Reguły wykonania

- Nigdy nie uruchamiać lokalnego Dockera.
- Jeden problem bezpieczeństwa lub jedna spójna warstwa na PR.
- Conventional commits.
- Nie używać `--no-verify`.
- Nie force-pushować `main`.
- Każdy schema PR do czasu cutoveru respektuje `_COLUMN_STATEMENTS`.
- Dla GitHub CLI write używać `codex-gh`; zwykły `git push` korzysta z
  credential helpera.
- Nie kopiować sekretów do PR, issue, logów ani fixture.
- Każdy krytyczny PR musi mieć rollback note.
- Nie kończyć zadania na lokalnych testach: wymagane CI, merge, deploy i
  produkcyjna weryfikacja.

## 14. Plan implementacji fazami

### Faza 0 — containment

#### Operacje wymagające jawnej zgody właściciela

- tymczasowe zablokowanie publicznego submitu podpisów,
- wyłączenie signing,
- wyłączenie CloudTalk,
- rotacja sekretów,
- dezaktywacja/usunięcie konta administratora,
- zatrzymanie mutujących produkcyjnych E2E.

#### PR 1 — `fix/security-remove-admin-bootstrap`

Zakres:

- usunięcie startup bootstrapu,
- usunięcie fallback sekretu,
- zawężenie gitleaks,
- test regresji,
- dokumentowana ręczna procedura break-glass.

Po deployu: incident response dla konta.

#### PR 2 — `fix/signing-emergency-kill-switch`

Zakres:

- gate dla wszystkich publicznych metod,
- brak submit/regenerate przy disabled,
- bezpieczna odpowiedź statusowa,
- focused tests.

#### PR 3 — `fix/signing-fail-closed-validation`

Zakres:

- strict DSS verdict,
- atomic submit,
- link revocation,
- identity binding,
- idempotency,
- concurrency tests.

#### PR 4 — `fix/rbac-destructive-operations`

Zakres:

- bulk erase,
- client rate,
- CloudTalk mapping,
- Fireflies sync,
- negatywna macierz ról,
- immutable audit.

### Faza 1 — schemat, readiness i Analytics

#### Krok operacyjny 1 — read-only schema inventory

Artefakt wyjściowy:

- aktualne `alembic_version`,
- DDL checksum lub znormalizowane definicje 0153–0164,
- lista brakujących/nadmiarowych obiektów,
- plan locków i czas migracji,
- decyzja: migrate, reconcile albo stamp po pełnym dowodzie.

#### Krok operacyjny 2 — staging restore

- restore aktualnego backupu,
- kontrola checksum/freshness,
- wykonanie migracji,
- walidacja danych i constraints,
- zapis czasu i zasobów,
- rollback rehearsal.

#### PR 5 — `fix/release-schema-gate`

Zakres:

- migration job,
- advisory lock,
- brak `|| continue`,
- kontrolowany cutover od runtime DDL,
- exact-head readiness,
- runbook.

#### PR 6 — `fix/analytics-period-bounds`

Zakres:

- bounded queries,
- kontrola semantyki okresu,
- indeksy wyłącznie po `EXPLAIN`,
- contract tests,
- performance test na staging clone.

Produkcja:

- oba widgety działają,
- porównanie liczb z SQL,
- screenshot,
- p95 zgodne z wymaganiami.

### Faza 2 — fail-closed release i auth

#### PR 7 — `build/fail-closed-release-gate`

- deploy po dokładnym zielonym SHA,
- aggregate check,
- blokujące security scanners,
- wymagany smoke User-Agent,
- branch protection i production environment.

#### PR 8 — `fix/health-readiness-contract`

- `/livez`,
- `/readyz`,
- DB/schema/Qdrant/worker,
- required integration policy,
- wspólny health service dla API i snapshotu.

#### PR 9 — `fix/auth-revocable-cookie-sessions`

- server-side sessions,
- cookie auth,
- rotation/reuse detection,
- revocation,
- CSRF/Origin,
- SSO atomic exchange,
- force-password-change backend gate,
- middleware default-deny,
- CSP.

### Faza 3 — integralność procesów biznesowych

#### PR 10 — `fix/public-application-isolation`

- immutable application model,
- duplicate hint,
- reviewed merge,
- versioned CV/provenance.

#### PR 11 — `fix/m365-real-email-outbox`

- real provider send,
- provider ID,
- outbox,
- idempotency,
- prawidłowe komunikaty UI.

#### PR 12 — `fix/traffit-transactional-watermarks`

- transaction boundaries,
- durable failures,
- dependency gating,
- reconciliation.

#### PR 13 — `fix/m365-private-retroactive-purge`

- unmatch,
- scrub,
- delete attachments,
- privacy regression tests.

#### PR 14 — `fix/cloudtalk-hmac-idempotent-webhooks`

- HMAC-only,
- replay window,
- upsert,
- secret redaction.

#### PR 15 — `fix/ws-resource-acl`

- resource ACL,
- payload minimization,
- limits,
- role matrix.

#### PR 16 — `fix/public-upload-quarantine`

- magic bytes,
- AV/quarantine,
- safe storage,
- archive limits.

### Faza 4 — dedykowany worker

#### PR 17 — `feat/worker-singleton-runtime`

- osobny worker,
- advisory lease i fencing,
- heartbeat,
- readiness/snapshot visibility,
- graceful shutdown.

#### PR 18 — `feat/durable-inbox-outbox`

- webhook inbox,
- e-mail outbox,
- retries per provider,
- dead-letter queue,
- idempotent manual triggers.

### Faza 5 — poprawność frontendu

Rekomendowana kolejność osobnych PR-ów:

1. retry tylko dla safe methods,
2. typed query-key factory,
3. cache invalidation,
4. Kanban rollback,
5. date-only helper i testy Europe/Warsaw,
6. paginacja Users/Contractors,
7. debounce/cancel wyszukiwań,
8. `useQueries` zamiast hooka w pętli,
9. same-origin authenticated file allowlist,
10. realny Audit Log lub ukrycie atrapy,
11. capability gating Settings,
12. a11y,
13. token-first color cleanup z CI gate.

Przed pracą wizualną Opus musi przeczytać
[`frontend/docs/ds/ADDING-BLOCKS.md`](../frontend/docs/ds/ADDING-BLOCKS.md) i
korzystać z istniejącego DS. Nie używać `npx shadcn add`.

### Faza 6 — DR, observability i pełne CI

- uploads backup/object storage,
- restore drill DB + Qdrant + pliki,
- izolowany recovery runner,
- Alloy filtering i socket proxy,
- pinned image digests,
- per-service env/secrets,
- backend `.dockerignore`,
- read-only runtime filesystem,
- staging E2E,
- read-only production smoke,
- full backend test shards,
- changed-lines coverage,
- stopniowy global coverage gate.

## 15. Zależności między PR-ami

```text
PR 1 admin bootstrap ──> produkcyjny incident response

PR 2 signing kill-switch ──> PR 3 signing validation

schema inventory ──> staging restore ──> PR 5 schema gate
                                      └─> PR 6 analytics

PR 7 release gate ──> bezpieczniejsze wdrażanie wszystkich kolejnych zmian

PR 8 readiness ──> PR 17 worker visibility

PR 9 session model ──> finalne middleware/CSP/WebSocket auth

PR 12 Traffit correctness ──> kontrolowany replay/reconciliation

PR 17 worker ──> PR 18 durable inbox/outbox
```

Nie odwracać kolejności:

- UI Analytics nie może zastąpić schema reconciliation.
- Worker nie rozwiąże sam idempotency webhooków.
- Cookie auth nie powinien zostać połączony z bootstrap incidentem.
- Dependency upgrades nie powinny wejść przed stabilizacją P0/release gate.

## 16. Strategia dla istniejących PR-ów

| PR | Rekomendacja |
|---|---|
| #684 | Odbudować na aktualnym `origin/main` jako mały PR usuwający bootstrap. |
| #685 | Wyciągnąć fail-closed release gate po P0. |
| #688 | Użyć jako materiału do migration job/schema gate, po inventory. |
| #689 | Użyć jako materiału do readiness po ustaleniu wymaganych zależności. |
| #690 | Użyć jako materiału do cookie sessions; nie merge'ować jako część starego stacka. |
| #691 | Nie merge'ować jako monolitu; traktować jako źródło diffów. |
| #692 | Dependency/security upgrades dopiero po fundamentach; review grupami. |
| #693 | Worker po ustabilizowaniu release, dependencies i readiness. |
| #694 | Changed-lines coverage po uruchomieniu pełniejszego suite. |
| #699 | Potencjalny hotfix Analytics po schema inventory i query review. |

Każdy PR musi zostać zrebase'owany albo odtworzony na aktualnym main bez
przenoszenia niepowiązanych commitów.

## 17. Minimalna weryfikacja host-native

### Backend

```bash
cd backend
ruff check app/ tests/test_<obszar>.py
ruff format --check app/ tests/test_<obszar>.py
pytest tests/test_<obszar>.py -v
alembic -c alembic/alembic.ini heads
```

Jeżeli PR zmienia migrację, hosted CI musi wykonać `upgrade heads` na świeżej
bazie. Lokalny Docker pozostaje zakazany.

### Frontend

```bash
cd frontend
npm ci --legacy-peer-deps
npm run type-check
npm run lint
npm run test -- <focused-test>
```

`npm run build` wykonywać host-native tylko wtedy, gdy nie działa równolegle
`dev`/`start`. Pełne image/integration gates pozostawić hosted CI.

## 18. Definition of Done każdego PR-a

PR nie jest zakończony, dopóki:

1. scope jest jednoznaczny i nie zawiera sąsiednich refaktorów,
2. istnieją testy regresji i negatywne testy bezpieczeństwa,
3. focused host-native checks są zielone,
4. exact diff został przejrzany,
5. commit jest conventional,
6. branch został wypchnięty,
7. PR ma opis ryzyka, migracji i rollbacku,
8. wszystkie required CI są zielone,
9. PR został squash-merged,
10. deploy zakończył się powodzeniem,
11. produkcyjny `version` odpowiada merged SHA,
12. realny endpoint lub UI flow został zweryfikowany,
13. dla UI istnieje screenshot,
14. dla zmian security sprawdzono brak tokenów/PII w logach,
15. worktree jest czysty.

### Produkcyjny health proof

```bash
curl -fsSL \
  -A 'dynaminds-smoke-test/1.0' \
  https://api.nexus.dynaminds.pl/api/health | jq .
```

Należy sprawdzić:

- `status != "unhealthy"` zgodnie z aktualnym kontraktem,
- `version` zaczyna się od siedmiu znaków merged SHA,
- `checks.database` jest zdrowe,
- feature-specific check/endpoint zachowuje się poprawnie.

## 19. Kryteria rollbacku

Rollback powinien być wykonany, jeżeli po wdrożeniu:

- `version` nie odpowiada merged SHA,
- health lub readiness przechodzi na unhealthy,
- pojawia się wzrost 5xx lub latency powyżej zaakceptowanego progu,
- migracja pozostawia niezgodny head/obiekty,
- security fix nadal dopuszcza negatywny przypadek testowy,
- background worker traci lease albo dubluje joby,
- UI krytycznego flow nie działa w realnym Chrome.

Rollback przez udokumentowaną ścieżkę Coolify nie może zastąpić wyjaśnienia
przyczyny i follow-up PR-a.

## 20. Kolejność operacyjna

### Stop-the-line

- bootstrap administratora,
- signing kill-switch i strict validation,
- bulk anonymization RBAC,
- bezpieczny backup uploadów.

### Następne 24–72 godziny prac implementacyjnych

- schema inventory,
- staging restore,
- Analytics,
- destructive-operation RBAC,
- token/log redaction,
- release gate.

### Następny zestaw

- revocable sessions,
- middleware default-deny,
- SSO race,
- Traffit watermarks,
- health/readiness,
- dedicated worker.

### Po stabilizacji fundamentów

- M365 privacy,
- real email,
- public application isolation,
- CloudTalk/Fireflies,
- DR/Alloy/full CI,
- frontend correctness,
- data reconciliation.

## 21. Elementy, które należy zachować

Audyt potwierdził także poprawne lub wartościowe mechanizmy:

- DB, M365 i M365 encryption były zdrowe,
- health DB ma timeout,
- audit baseline repo miał scalony graf Alembic,
- Ruff, frontend type-check i testy Vitest przechodziły,
- self-registration wymusza viewer i email verification,
- reset token ma atomowe zużycie,
- authenticated CV upload używa bezpiecznego basename,
- HMAC comparison jest constant-time,
- Sentry Replay maskuje tekst i media,
- aktualny design system ma semantic tokens i gotowe komponenty.

Naprawy powinny zachować te mechanizmy i nie wprowadzać równoległych,
konkurencyjnych abstrakcji.

## 22. Finalna checklista programu naprawczego

- [ ] P0-01 bootstrap usunięty i konto obsłużone operacyjnie.
- [ ] P0-02 signing pozostaje disabled do formalnego odbioru.
- [ ] P0-03 destructive RBAC i dry-run wdrożone.
- [ ] Produkcyjny schemat jest obiektowo zgodny z repo.
- [ ] Migracje są fail-closed.
- [ ] Insights działa i spełnia p95.
- [ ] Deploy nie może ominąć CI.
- [ ] Health/readiness nie jest false-green.
- [ ] Refresh/session tokens są odwoływalne.
- [ ] Middleware jest default-deny.
- [ ] SSO exchange jest atomowy.
- [ ] Traffit nie przesuwa watermarku po błędzie.
- [ ] Każdy scheduler ma singleton ownership.
- [ ] E-mail jest raportowany jako wysłany wyłącznie po provider ACK.
- [ ] CloudTalk i Fireflies mają właściwy RBAC i stan health.
- [ ] M365 privacy działa retroaktywnie.
- [ ] WebSocket ma resource ACL.
- [ ] Tokeny nie trafiają do logów.
- [ ] Produkcyjne E2E jest read-only.
- [ ] DB, Qdrant i uploads mają zweryfikowany restore.
- [ ] Alloy nie miesza logów aplikacji.
- [ ] Fake Audit Log został usunięty lub zastąpiony.
- [ ] Frontend ma stabilne cache, retry i date handling.
- [ ] Data-quality cleanup ma zatwierdzony raport i dry-run.

Po zaznaczeniu wszystkich pozycji NEXUS może zostać ponownie poddany pełnemu
audytowi produkcyjnemu. Dopiero taki re-audyt powinien zamknąć program naprawczy.
