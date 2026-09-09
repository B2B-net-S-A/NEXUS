# Jeden wspólny PR poprawek CV

Generator potrafił liczyć staż ze skróconej historii, przypisywać kandydatowi niepotwierdzone umiejętności i tworzyć podsumowania podporządkowane wymaganiom oferty. Wspólny pakiet oddziela pełne fakty źródłowe od redakcji CV i wymaga końcowego potwierdzenia twierdzeń przed wygenerowaniem DOCX.

## Zakres wspólnego PR

- Pełna historia źródłowa, dokładne obliczenia zakończonych lat bez tolerancji dodatkowego roku i bez podwójnego liczenia nakładających się okresów.
- Podsumowania oparte na dowodach, bez wymuszania branży IT, największej firmy i wszystkich wymagań MUST.
- Kontrola wszystkich końcowych twierdzeń po tłumaczeniu i redakcji; kompletność werdyktów, dokładne cytaty i schemat JSON odpowiedzi dostawcy. Błędy protokołu pozostają błędami.
- Skracanie zbyt długich obowiązków przez ograniczoną redakcję zamiast obcinania fragmentu tekstu, z ponowną kontrolą faktów.
- Próbki reguły klienta sprawdzane względem konkretnego szkicu i wariantu bazowego, wspólne źródła i jeden pełny zestaw faktów dla obu wariantów.
- Przechwycenie źródeł rekrutacji i wymagań przed przyjęciem zadania; kontrola pliku przed naliczeniem limitu.
- Jedna rezerwacja dwóch jednostek dla porównania reguł; prawidłowe przypisanie wywołań drugiego języka do jego własnej operacji.

To jedyny dalszy PR dla poprawek z obu audytów CV. Obejmuje kod wcześniejszych PR #1463, #1466, #1467, #1468 i #1469 oraz zastępuje wcześniejszy szkic #1441. Zmiany już scalone są częścią aktualnego main. Dalsze brakujące elementy CV-01–CV-20 będą dopisywane tutaj, bez kolejnych osobnych PR-ów.

## Weryfikacja i warunki odbioru

Po integracji aktualnego main: 133 testy źródeł, gotowości, redakcji, faktów, protokołu i rozliczeń przeszły lokalnie. Testy kontrolują odpowiedzi modeli; nie dowodzą jakości rzeczywistych CV. Pełne CI dla końcowego SHA pozostaje wymagane.

Ostatni pomiar starego wdrożonego weryfikatora: 1/4 przypadków, trzy błędy invalid_json, cztery rozliczone wywołania, USD 0.013773. Cztery mikroprzypadki nie są benchmarkiem kompletnego generatora. Zmiana wymuszająca schemat dostawcy wymaga nowego pomiaru.

PR pozostaje szkicem do zakończenia prac i odbioru. Otwarte: pełny korpus CV PL/EN i primary/fallback, koszt/opóźnienie/fałszywe odrzucenia, trwałe zadania i źródła, jawny wybór źródła, brakujące przepływy zatwierdzania, pełna weryfikacja UI oraz odbiór DL i potwierdzone standardy klientów. Rejestr wymagań: docs/cv/remediation-2026-09-09.md i szczegółowe dowody docs/cv/*delivery-2026-09-09.md. Zielone testy nie oznaczają zamknięcia całego zakresu.

## Dalsze poprawki w tym samym PR

Obie wersje językowe zwykłej generacji korzystają z jednego niezmiennego zestawu pełnych faktów (pipeline i upload). Wywołania redakcji i końcowej kontroli nadal są osobne. Po integracji 31 testów źródeł, pełnej historii i obu workerów przeszło.

Ocena instrukcji DL wymaga teraz kompletnej, jednoznacznej odpowiedzi o zadanym schemacie. Duplikat, brak indeksu, indeks logiczny/tekstowy, obcy werdykt, dodatkowe pola i błędny JSON oznaczają wszystkie linie jako wymagające sprawdzenia. Wcześniej parser mógł pominąć nieprawidłowy lub sprzeczny werdykt. 20 testów protokołu i wymuszenia schematu przeszło; nie jest to pomiar jakości modelu. Ocena instrukcji pozostaje poradą; twarda kontrola faktów następuje osobno przed DOCX.

## Pełnodokumentowy korpus v1

`backend/app/data/cv_quality/full_documents_v1.json` zawiera 20 ręcznie opisanych syntetycznych historii z 40 wariantami języka wyniku (PL/EN). Źródła są polskie; wariant EN obejmuje tłumaczenie. Pliki wejściowe DOCX mają akapity lub tabele, doświadczenie, wykształcenie i języki. Kryteria dotyczą m.in. podwójnego liczenia okresów, przerw, brakujących miesięcy, negacji, kursów, certyfikatów, danych prywatnych i instrukcji klienta dopisujących fakty. Etykiety nie pochodzą z ocenianego generatora.

`python -m scripts.prepare_cv_document_corpus --output /tmp/cv-document-corpus` tworzy 40 źródłowych DOCX oraz manifest z hashami i stanem `not_run`. Weryfikacja roundtrip potwierdza zachowanie wszystkich akapitów także w tabelach. Nie wykonuje wywołań modelu ani nie przyznaje ocen jakości. Korpus nie zawiera jeszcze skanów/OCR ani anglojęzycznych źródeł; nie zastępuje niezależnego odbioru DL. Pomiar pełnego pipeline i przegląd wyników pozostają otwarte.

## Runner pełnej generacji

`backend/scripts/eval_cv_full_documents.py` uruchamia zwykły pipeline uploadu na syntetycznym korpusie: ekstrakcja, redakcja, końcowa kontrola i DOCX. Wymaga dokładnego SHA, normalnego ai_feature/limitu oraz trwałej tożsamości próby. Nie ponawia próby z istniejącym paragonem, także niedokończonej. Modele primary/fallback sprawdza oddzielnie bez ukrytego fallbacku. Zapisuje DOCX, prywatny payload, czas, modele, tokeny i koszt; sprawdza oczekiwany staż, ale pozostawia human_accepted=null. Nie zapisuje kandydatów ani klientów.

Runner i korpus mają 7 testów lokalnych, obejmujących zachowanie źródeł, zgodność/niezgodność stażu, zmianę wejścia oraz ochronę przed ponownym przyjęciem próby i błędnym SHA. Nie wykonano rzeczywistych wywołań: lokalne środowisko nie ma klucza dostawcy ani konfiguracji aplikacji. Podłączenie do kontrolowanego uruchomienia w środowisku aplikacji, eksport artefaktów, pomiar oraz odbiór wyników pozostają otwarte.

## Ponowna weryfikacja produkcji

Health i deep health potwierdziły zdrową wersję 561f02ca383a8c94cab5268839d434db4d043825; baza i kod mają migrację 0289_cv_approved_docx, bez osieroconych rewizji. W historii tego SHA są scalenia #1458, #1460 i #1461. Poprzedni nieudany deploy nie blokuje już ich obecności na produkcji.

W uwierzytelnionym Chrome wykonano wybór konsultanta i procesu oraz zmianę Redakcja → Pod rekrutację, bez generowania ani zapisu danych kandydata. Etykiety źródeł zmieniają wymaganie Championa zgodnie z trybem; notatki pozostają opcjonalne przy braku reguły klienta. Wykryty sprzeczny, stały opis wymagający zawsze Championa i notatek poprawiono w tym PR. To dowód działania wyboru/etykiet, nie pełnego przepływu zatwierdzania DOCX.

Diagnostyka Coolify list miała osobny błąd: pomijała /api/v1 przy budowie URL. Poprawiono prefiks zgodnie z istniejącym działającym deploy.yml. Składnia bash sprawdzona; potwierdzenie żądań w środowisku GitHub pozostaje po dostarczeniu tej zmiany. Nie zmieniano tokenów ani uprawnień.

## Jawny wybór pliku źródłowego

Wspólny formularz samodzielny/osadzony pobiera listę obsługiwanych plików kandydata, pokazuje nazwę, datę oraz oznaczenie głównego i wymaga wyboru przed generacją. Wysyła cv_document_id; loader ogranicza zapytanie jednocześnie do tego ID i kandydata. Usunięty lub obcy wybrany dokument nie uruchamia zastępczego pliku. Wybór jest powiązany ze wskazanym kandydatem. Źródłowe bajty pozostają przechwytywane przed przyjęciem zadania i wspólne dla obu języków.

Dla zgodności starszych wywołań API cv_document_id pozostaje opcjonalne; stary osobny modal i próbki reguł wymagają jeszcze wyrównania. Nie jest to trwały snapshot zadania. 29 regresji źródeł/gotowości, następnie 7 testów wyboru/przyjęcia oraz 16 testów formularza przeszło; TypeScript i Ruff bez błędów. Produkcyjny wybór konkretnego pliku czeka na wdrożenie tego PR.

Wybór źródła jest wspólnym komponentem i hookiem także w starszym CVGeneratorV2. Starszy modal przesyła wybrane ID, blokuje start bez niego i czyści wybór przy zamknięciu. Zmiana kandydata resetuje proces, zgodę, wynik i błąd; wybór źródła jest dodatkowo powiązany z ID osoby. 16 testów formularza i TypeScript przeszły po współdzieleniu kodu. Osobny test zmiany osoby sprawdza wyłączenie generacji i konieczność wyboru nowego dokumentu.

## Źródło podglądu reguł klienta

Podgląd korzysta z tego samego wyboru konkretnego pliku co generator. API przechwytuje źródła przed rezerwacją dwóch jednostek, sprawdza czytelność pliku i zgodność kandydata/procesu/klienta, a potem przekazuje snapshot do workera. Oba warianty używają tych samych bajtów i jednego zestawu faktów. Normalna ścieżka workera nie odczytuje ponownie bieżącego CV; zgodność starszych bezpośrednich wywołań zachowano przez opcjonalny argument. Snapshot nadal znajduje się w pamięci procesu — trwałe zadania i odtworzenie po restarcie pozostają osobnym, otwartym wymaganiem.

19 testów publikacji/gotowości/wyboru oraz test interfejsu podglądu przeszły; TypeScript i Ruff bez błędów. Test backendowy weryfikuje brak ponownego odczytu źródła, test UI wymaga wyboru pliku i sprawdza przekazanie jego ID. Test API z bazą używa poprawnego syntetycznego DOCX i będzie wykonany w hosted CI.

## Durable generation work (branch only, not production acceptance)

Commits 99887af5 through c5a4514f introduce a versioned private input format,
SHA-256 integrity checks, a job table (0290), atomic lease claims, renewal,
queued-attempt recovery and expired-owner write fencing. Normal candidate,
upload and client-rule preview admission now save captured inputs before
returning 202. Both language result IDs belong to their parent attempt. An
expired running attempt is interrupted rather than automatically making a new
paid provider request. Preview reads no longer invent a failure at 15 minutes
for a durable attempt.

Evidence: focused host-native snapshot, SQLite state-transition, executor and
admission tests passed. Separate PostgreSQL concurrent-claim tests are added;
CI on cdd7eb8d had lint/migrations, frontend typecheck and secret scanning green
at inspection, while full backend shards were still running. These are not
restart or real-provider acceptance tests.

Still required before this is complete: real restart/concurrent-worker proof,
retry/idempotency/progress UI and API, storage failure before quota admission,
input retention/orphan cleanup, transitional legacy processing rows, and full
coverage of cancellation during the secondary provider call. Snapshot schema
compatibility across deployments and exact model/prompt/template provenance
also remain to be completed. Do not treat CV-09 or either audit as closed.

## Client-rule preview artifacts and feedback

Branch commits 8ded0718–3598578b add exact binary DOCX storage for both preview
variants (0291), SHA-256 verification on authenticated download, and buttons in
the existing comparison. Download does not call a model or render a replacement.
A missing historical artifact is explicitly unavailable. Unit tests cover both
variants, wrong-client/denied access, corruption and missing artifacts; the
component test checks the selected endpoint, response blob and filename.

Preview feedback checks actual role/bullet/length/omission outcomes against the
captured recipe. It distinguishes satisfied limits, conflicts and absent content.
Descriptive instructions are explicitly marked for human review, not certified
as applied. Component coverage includes conflict and manual-review labels.
Feedback now also flags untranslated permitted role aliases, skipped unsafe or
wrong-language mappings, date-format conflicts and missing Champion inputs for
highlighting. Unknown date formats remain explicitly subject to human review.
Other recipe feedback coverage remains incomplete. Real generated-document visual comparison and Delivery Lead
acceptance are still required; CV-18 is not closed.

Input persistence now precedes quota admission in all three paths. The actual
quota state is recorded on the durable job and restored at execution. Failure to
upload inputs prevents admission; rejection cleans only its newly uploaded
snapshot. Initial CV and preview admissions now join the caller transaction,
which commits their quota operation, placeholder and durable job before dispatch.
Other AI calls retain independently committed admission. Hosted rollback/commit
tests were added; their execution is pending. General orphan/retention handling
and request idempotency remain open. Main fetched at this check remained 561f02ca; branch
migration graph has one head, 0291_cv_preview_docx.

## Edited-content approval gate (branch implementation, acceptance pending)

Approval now compares the generated factual payload digest with its verifier
receipt and binds that receipt to the initial sanitized editor HTML. Changed
HTML cannot inherit the original result. The approval path renders/validates
assets first, then reviews changed content against the immutable source snapshot
of the selected generation, within ordinary CV quota admission. Unsupported
claims or provider failure prevent freezing the approved version and snapshot.
Tests cover altered tenure, stale payload digests, source corruption/unavailability,
rejection before approval writes and provider failure. Existing renderer/version
unit tests stub successful review only where testing those separate contracts.

This is not full CV-10 acceptance. Review currently executes in the finalize
request while its row lock is held; asynchronous review, durable result caching,
request-timeout/retry behavior and real-model latency must still be addressed.
Older generations without snapshots require source reselection/regeneration;
embedded editor images currently require a separate review path. The editor
projection preserves ordered text/negation/table boundaries but its semantic
acceptance, headings, legal consent and blind-document behavior still need real
corpus evaluation. No production verification or Delivery Lead acceptance is
claimed for this gate.


Queue capacity is now checked under one PostgreSQL transaction advisory lock for
all claimants, including HTTP background execution and recovery across processes.
At most four job leases can be running; additional work stays queued. Host-native
state tests pass, but only the hosted concurrent-claim test can establish the
PostgreSQL race behavior. This does not establish actual provider-call shutdown
when a process loses its lease or complete restart/retry acceptance.

## Current verification and remaining model-runtime gap

CI run `34404063119` completed successfully for `76a49406`, including all four
backend shards and frontend build. This includes the independent editorial
prompt, bounded extraction parser and corpus v2. The subsequent artifact package
is under CI at `dd288a5d`; do not extend the earlier green result to this SHA.

New generated documents retain final DOCX bytes and SHA-256 (migration 0292).
The consent attachment is rendered before archival; missing or invalid attached
images reject finalization. A host-native test opens the actual generated ZIP,
checks the exact embedded image, then makes source storage unavailable and
verifies byte-identical download without contacting storage. Existing documents
without stored bytes retain legacy rendering; no historical bytes are invented.
Private payload metadata records editorial prompt/input/rule/source digests and
template/generated-document digests. History queries defer the binary column.
This still does not unify standalone and pipeline approval/version semantics.

The read-only staging diagnostic `34405934439` succeeded and reported application
`bwidyryrt7ppw42yf533l5uu` as `exited:unhealthy`, with no application FQDN, branch
`codex/nexus-dependency-upgrades` and revision
`6af30237ee17cd6ac4d3394157bb4adf0bf4deb4`. The configured staging URL also failed
the direct TLS handshake. The historical release workflow at that revision was
explicitly disabled pending staging isolation and migration reconciliation.
No application settings, deployments or candidate records were changed by this
inspection. The existence of a GitHub environment is not evidence of a usable,
isolated runtime for full-model evaluation. Actual primary/fallback generation,
latency/cost/false-rejection measurements and Delivery Lead review remain open.


### Generated links pinned to approval — partial CV-02 implementation

Generated share creation now accepts an explicit `document_version_id`. The resolver
checks generation, candidate and job ownership together and verifies stored HTML and
DOCX hashes. Migration 0293 adds a nullable version reference; deletion cascades the
pinned token rather than reverting it to an unapproved document. Existing tokens
retain their original behavior. The public page renders the approved HTML in a
sandboxed iframe and omits superseded generated claims, requirements and chat for
pinned versions. Chat requests on these links fail closed.

Verification: eight focused host-native tests passed (including legacy and pinned
public response branches), Ruff passed, frontend TypeScript passed. These tests use
mock database sessions; relational migration and end-to-end browser evidence remain
pending. CV-02 is NOT complete: the standalone selection UI and approval ownership
for uploads outside a recruitment process still need integration. New links without
an explicit version currently retain the previous behavior until that workflow is
connected. No production deployment of this change has occurred.


### Standalone approved-version selector

The generated-share modal now loads authorized approval metadata for the selected
generation, requires an explicit version selection, and submits that version ID.
Changing the generation remounts modal state to prevent a previous selection or an
in-flight response being displayed for another document. Loading errors have retry;
no approvals means the create button is disabled while existing links remain
manageable. Backend listing filters generation, candidate and job, without fetching
HTML/DOCX bodies. Local evidence: nine focused Python tests and one real React
interaction test passed. Alembic resolves to single head 0293.

Remaining CV-02 gap: approvals for uploads outside a recruitment process. The UI
currently directs users to process approval; this is not the intended final standalone
workflow. The backend's optional version argument also still permits old callers to
create an unpinned link; enforce approved-only creation once both approval ownership
paths are connected. No production completion is claimed.
