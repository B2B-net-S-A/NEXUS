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


### Standalone approval ownership and artifact preservation

Migration 0294 permits an approval to belong either to a pipeline CV or directly
to a generation (exclusive ownership check). A separate cascading owner reference
preserves pipeline approvals when their generation is deleted while removing
standalone approvals with their owner. Standalone approval is authorized, locks the
generation, validates the archived DOCX hash and generation factual-review hash,
and freezes client-safe HTML plus those exact DOCX bytes. Repeated approval reuses
version 1. The share modal can now approve and select an unedited standalone upload.
Version lookup/listing accepts both owners with generation/context filtering.

Host evidence: 14 Python cases, two React interaction cases, TypeScript and Ruff
passed. Tests use mock persistence; hosted migration/relational evidence is pending.
Previous pushed head dd288a5d completed all CI shards and frontend build in run
34405938149. This is not evidence for changes after that head.

Remaining: standalone manual editing/new drafts and approved-only API enforcement,
plus full real-model/visual acceptance and other open CV-01..20 requirements. No
production completion is claimed.


### Relational approval verification prepared

Added four hosted database cases: standalone deletion cascade, pipeline approval
retention after generation deletion, rejection of ownerless approvals, and the HTTP
approve/retry/list/share/public-view roundtrip with blind identity and chat exclusion.
They are collected successfully and Ruff passes; execution against PostgreSQL is
pending hosted CI. The roundtrip uses synthetic archived bytes and a synthetic
verification receipt, so it does not prove rendering quality or model accuracy.

Approval refreshes the locked generation from the database (`populate_existing`)
before validating it, and approved-version resolution explicitly checks the standalone
owner ID as well as the source generation ID. Fourteen focused local unit cases
still pass. CI run 34407704731 for pushed head 96d9ff50 was verified in progress;
these additional checks are not part of that head yet.


### Standalone manual-edit backend

Migration 0295 adds a durable generated draft with revision, version, HTML and
frozen template/consent assets. Authorized editor endpoints now support load/save,
new draft, DOCX preview and finalization. Finalization uses the same HTML sanitizer,
DOCX renderer and source-review service as the pipeline, then stores an immutable
CvDocumentVersion. Failed review does not advance status/revision. The unchanged
approval shortcut refuses to bypass an existing editable draft.

Eighteen focused unit cases pass; Alembic has single head 0295 and Ruff passes.
Renderer/reviewer are mocked in the new transition tests, so these are lifecycle
proof only. Frontend adapter, print/download endpoints and real edited-CV acceptance
remain unfinished. The shared review service is still synchronous and needs the
previously recorded durable/cache treatment. No production completion is claimed.


### Shared editor connected to standalone panel

The generated-history row now opens the same editor component through a standalone
API adapter. Query/session identity includes the resource kind; switching between
resources remounts local state. The adapter covers save, finalize, new draft,
DOCX preview, print and exact approved-version download. Standalone state explicitly
has no candidate-stage ID. Template/language replacement remains disabled for
selected generated documents in both entry paths.

Two editor interaction cases pass (pipeline and standalone): an immediate finalize
includes the last edit before autosave, and download/preview use the correct resource
endpoint. The two sharing interaction cases passed earlier. TypeScript, Ruff and
18 backend unit cases pass. Tiptap/backend transport are mocked in these UI tests;
production browser verification and PostgreSQL integration remain pending.
CI 34407704731 for 96d9ff50 has a successful frontend build and four backend shards
still running at this checkpoint. This UI/editor package is newer than that head.


### Edited artifact regression and bounded model responses

A host test now uses the actual DOCX renderer on submitted editor HTML and inspects
paragraph text and bold runs: negation and explicit emphasis survive, and original
narrative is absent. Five editor tests pass. The hosted HTTP/database roundtrip was
extended with a new draft, stale-revision refusal, second approval, unchanged first
public link and separate downloads of versions 1/2. It is collected, not yet executed;
the reviewer is mocked, so this does not prove real-model acceptance.

Review feedback identified two additional unbounded response parsers. Final factual
verification and responsibility shortening now reject responses over one million
characters before Pydantic parsing. Oversized replies do not approve or partially
rewrite the document. Thirty-four focused verifier/editorial tests pass, including
parser-not-called assertions. These are runtime robustness checks, not CV quality
scores. Full real-model corpus, DL acceptance and production verification remain open.


### Pipeline selection of an approved generated revision

The handoff workbench now offers the original generation or a specific approved
revision when importing a generation into the recruitment draft. The request carries
the explicit version ID. Backend resolves it with generation/candidate/job ownership
and artifact integrity checks, copies its sanitized HTML, and records the source
version/content/DOCX hashes. Existing pipeline approval is archived before replacement.
This imports text as a new draft; it does not silently transfer approval or reuse the
original generation review for manually changed text.

Fifteen focused version tests and 25 workbench tests pass; TypeScript passed. These
are controlled transport/database tests, not production proof. Rendering assets are
still resolved through the generation asset loader during import; complete immutable
asset transfer across versions remains to be checked. CI 34407704731 for 96d9ff50
completed successfully (all backend shards and frontend build). Subsequent editor
and import changes require a new CI run.


### Immutable rendering assets attached to approvals

Migration 0296 stores template and consent bytes with approved versions. Pipeline
and standalone edited finalization preserve those assets and hashes. Unchanged
standalone approval also captures its assets and rejects a template hash mismatch
against recorded generation provenance. Pipeline import of an approved revision and
reopening a standalone approval use the version's assets directly, never current
storage/template files. Missing historical assets yield an explicit error while
existing approved downloads remain available; no historical bytes are fabricated.

Twenty-nine focused tests pass, including corrupt-asset refusal and reopening while
the live asset loader is forced to fail. Ruff passes and Alembic has single head
0296. PostgreSQL migration and real UI proof are still pending. CI 34409180558 is
running for earlier pushed head 2d5a3c80; CI Gate 34409180592 is successful.
This does not close remaining generation-time source/asset retention, legacy approval,
async review, full quality corpus or production acceptance requirements.


### Exact edited-review reuse

An already approved edited-source review can be reused only when HTML, generation,
frozen-source hash, verifier version, editor projection version, prompt hash and
response schema hash all match the current request. Source loading/validation still
runs. Standalone finalization retains the receipt in draft metadata for subsequent
revisions, as pipeline finalization already does. Any mismatch requires fresh review.

Twenty-four focused tests pass, including nine mismatch cases and a no-quota-call
case for an exact receipt. This avoids repeated paid verification of unchanged text;
it is not durable async review or cross-request deduplication before approval. The
main remediation table/evidence paragraph was refreshed without marking completion.


### New links require an explicit approval

Generated-share API now rejects requests without a selected approved version before
token creation. Existing nullable-version tokens remain readable/revocable with their
legacy interactive behavior. Legacy public/chat tests explicitly seed historical
unpinned tokens; the new approved HTTP roundtrip tests creation and SHA-only token
storage separately. Share responses/history include the pinned version ID and the
panel labels approved vs older generation links.

Eleven local approval tests, two sharing UI tests and TypeScript pass; 24 hosted
legacy/new integration tests collect but still require execution on PostgreSQL.
CI 34409180558 has a successful frontend build and backend shards in progress for
2d5a3c80. Changes after that head remain local. New approved links currently use the
classic approved HTML view; interactive support for edited approvals is not enabled.
No production completion or full CV-01..20 acceptance is claimed.


### Blind identity checks after manual editing

Editor origin metadata now freezes known identity terms for blind CVs (person name,
name components and source employer names). Shared approval checks normalized visible
HTML text against these terms before factual review or receipt reuse. Errors contain
no matched identity. Standard CVs are unaffected. This closes the specific case in
which a manually reintroduced name is true in the source but forbidden in blind CVs.

Thirty-five focused tests pass, including surname-only text, inline formatting,
employer names and no AI admission on refusal. This is an exact known-term guard,
not semantic anonymization proof: unknown identifiers, obfuscation/inflection and
false-positive rates still need real corpus acceptance. Historical metadata without
the guard is not backfilled here. Broader client presentation-rule checks after
editing remain open, as do hosted/production verification.


### Frozen rule configuration carried into editor metadata

New generation payloads now retain the complete dataclass recipe snapshot alongside
its existing editorial-provenance hash. Editor origin metadata deep-copies that
snapshot and marks it verified only when canonical serialization matches the saved
hash. Explicit no-rule and unavailable historical configuration are distinguished.
Public payloads exclude the recipe and private client instructions.

Forty-four focused source-review/editor provenance tests pass, including mutation
isolation, missing/mismatched snapshots and public exclusion. This establishes the
input for post-edit rule validation; it does not yet enforce all limits/sections on
arbitrary edited HTML. No historical snapshot is invented. CI 34409180558 has passed
frontend and backend shards 0/3; shards 1/2 were still running at this checkpoint.


### Client presentation limits checked after edits

Generated HTML now has explicit section/role markers preserved by sanitizer and
Tiptap. Shared approval checks configured role count, bullets per role, bullet length,
summary point count and omitted sections against the frozen recipe. Missing required
structure or exceeded limits blocks approval with an actionable message. Drafts stay
loadable: state reports conflicts instead of throwing. The editor shows conflicts
for the last saved draft and identifies manual review requirements. Free instructions,
dates, translations and highlighting are not falsely certified by these checks.

Forty-two focused backend tests pass, plus four frontend editor/real-Tiptap tests,
TypeScript and Ruff. Initial HTML exporter regression also passed. Structural markers
are not proof of semantic role classification if a caller deliberately relabels
content; real-client usability/visual acceptance and broader policy coverage remain
open. CI 34409180558 completed successfully for 2d5a3c80 (all backend shards and
frontend build). This subsequent asset/privacy/policy package requires new CI.


### Explicit candidate source selection at the API boundary

Public candidate generation now requires a positive `cv_document_id`, matching the
existing panel selection. The captured source must match that ID as well as candidate,
stage, job and client before admission. Internal source-loader defaults used by other
workflows are unchanged. Existing consent/resource tests now supply explicit source
IDs so they continue exercising their intended guards instead of schema rejection.

Seventy-one focused input/readiness/consent/source tests pass. New cases reject a
missing/nonpositive selection and a changed captured file before charging or enqueue.
The CV-08 table entry was refreshed; hosted exact-head and production proof remain
pending. Older open clients must refresh after eventual deployment. No deployment
has occurred for this consolidated PR.
# Ponowienia żądań generowania — walidacja lokalna

Panel wysyła `Idempotency-Key` dla generacji ze wskazanego dokumentu i uploadu.
Klucz niepewnej próby jest zachowywany w sessionStorage według skrótu wejścia
(w tym faktycznych bajtów plików), bez zapisywania treści CV. Odebrany sukces
usuwa klucz, aby kolejne świadome generowanie było nową próbą.
Backend po autoryzacji serializuje ten sam klucz użytkownika blokadą transakcyjną
PostgreSQL. Receipt, dokument, zadanie i naliczenie limitu zatwierdzane są w tej
samej transakcji; ponowienie zwraca poprzedni dokument przed ładowaniem źródeł,
naliczeniem i uruchomieniem zadania. Zmienione wejście daje 409, usunięty wynik
410. Migracja 0297 nie przypisuje kluczy historycznym żądaniom.

Dowody lokalne: 17 testów receipt/enqueue (w tym HTTP replay bez ponownego
naliczenia i zadania), 2 testy frontendowe (odzyskanie po przeładowaniu modułu,
rozróżnienie zawartości plików), Ruff. Testy jednostkowe nie dowodzą zachowania
konkurujących transakcji PostgreSQL ani rzeczywistej awarii sieci na produkcji.
Klienci API bez nagłówka zachowują wcześniejsze zachowanie; preview pozostaje
poza tym mechanizmem. Te ograniczenia wymagają dalszej weryfikacji CV-09.
# Oryginalne zasoby generacji — migracja 0298

Nowe generacje zapisują bajty szablonu użytego przez renderer oraz obraz zgody
użyty do końcowego DOCX. Obraz pobierany jest raz, jego skrót trafia do provenance,
a binarne zasoby do oddzielnych kolumn pomijanych na liście historii. Edytor
używa zapisanych zasobów i sprawdza ich skróty. Legacy bez zapisanych zasobów
nadal wymaga aktualnego pliku lub magazynu; znana zmiana szablonu jest odrzucana.
Nie wykonano historycznego backfillu ani wdrożenia migracji na produkcji.

Walidacja lokalna: 28 testów archiwizacji i zgód, w tym rzeczywisty DOCX z tym
samym obrazem co zapisany załącznik; testy zasobów obejmują niedostępny magazyn
i uszkodzoną kopię zgody. Alembic ma jedną końcową rewizję 0298.
CI Gate dla d2495aa0: 34413855623 success; główne CI 34413855594 jeszcze trwa
i nie obejmuje tej nowej paczki zasobów. Pełna ocena jakości modelowej pozostaje otwarta.
# Hosted receipt concurrency evidence — d2495aa0

CI 34413855594 finished successfully for d2495aa0. Its shard 0 log explicitly
reports both `test_competing_receipt_observes_commit_or_recovers_rollback[True]`
and `[False]` as PASSED: a competing request reuses the committed document or
reserves a fresh receipt after rollback. This is PostgreSQL evidence, not a
mock-only inference. It does not establish production network/restart behavior.

The next pushed revision a0a18ddb has CI 34415126821 in progress, CI Gate
34415126803 queued and review 34415126907 in progress at this checkpoint.
No merge, production deployment or model-quality acceptance is claimed.
# Retry podglądu recepty — migracja 0299

Podgląd reguł korzysta z tego samego mechanizmu kluczy ponowienia co generacja.
Autoryzacja klienta i związku kandydat–rekrutacja poprzedza odczyt receipt.
Pierwsze żądanie zapisuje receipt wraz z zadaniem i obciążeniem dwóch wariantów;
ponowienie zwraca wcześniejszy podgląd przed źródłami i naliczeniem limitu.
Usunięcie podglądu zeruje FK, zachowując receipt; ponowienie daje 410. Panel
usuwa wtedy lokalny klucz, pokazuje błąd i dopiero następne świadome kliknięcie
rozpoczyna nową próbę. Błąd sieci nadal zachowuje klucz; nie ma automatycznej
płatnej regeneracji po 410.

Dowody lokalne: test handlera bez ponownego źródła/kwoty/background task,
test wyboru tabeli preview zamiast generated, test błędu 410 i ponownego kliknięcia,
TypeScript. Test PostgreSQL usunięcia podglądu dodany, ale jeszcze niewykonany
w hosted CI. Jedna końcowa rewizja Alembic: 0299. Brak dowodu produkcyjnego.
