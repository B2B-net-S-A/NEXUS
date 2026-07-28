# NEXUS — globalna koordynacja pierwszego kontaktu z kandydatem

- Data handoffu: 2026-07-28
- Status: gotowe do review na draft PR; bez merge, deployu i zmian produkcyjnych
- Branch: `codex/candidate-contact-queue`
- Bazowy `origin/main`: `7c7c2a5bab28fd29ef64f6bfafdea3aa29d02441`
- Commit backendu: `4550ac09`
- Commit frontendu: `2a747ed4`
- Commit poprawki po pełnym CI: `10160870`
- Draft PR: <https://github.com/artur-t-96/Nexus/pull/984>
- Hosted CI kodu: zielone na `10160870`

## 1. Decyzja wdrożeniowa

Kod jest przygotowany do review, ale nie jest upoważniony do wdrożenia.

Codex wykonał wyłącznie pracę w izolowanym worktree, testy host-native,
commity na branchu oraz przygotowanie draft PR. Nie wykonano:

- merge do `main`;
- deployu;
- migracji produkcyjnej;
- zmiany flag lub konfiguracji Coolify;
- rejestracji webhooka;
- zapisu do produkcyjnego NEXUS ani Traffit;
- żadnego zapisu NEXUS → Traffit.

Claude powinien najpierw wykonać review kodu i niniejszego handoffu. Decyzja o
merge i uruchomieniu kolejnych etapów wymaga osobnego GO.

## 2. Cel i najważniejsze niezmienniki

Zmiana oddziela obecność kandydata w pipeline/shortliście od realnego
zobowiązania do wykonania telefonu.

Najważniejsze niezmienniki:

1. Jeden kandydat ma najwyżej jeden globalny `candidate_contact_case`.
2. Ten sam case może mieć wiele otwartych ofert, po jednej unikalnej
   opportunity dla pary kandydat–rekrutacja.
3. Dodanie kolejnej oferty nie odbiera kandydata aktualnemu opiekunowi.
4. Slot 1–20 oznacza wyłącznie faktycznie oczekujący telefon:
   `queued` albo `callback_due`.
5. Udana rozmowa zwalnia slot, ale opiekun może pozostać właścicielem relacji
   w `handoff_pending`.
6. `do_not_contact` jest trwałym stanem `suppressed` i blokuje automatyczne
   ponowne otwarcie.
7. Traffit pozostaje źródłem danych rekrutacyjnych. NEXUS jest źródłem prawdy
   tylko dla koordynacji kontaktu.
8. Wszystkie automatyzacje są domyślnie wyłączone.
9. Historyczne rekordy sprzed `CANDIDATE_CONTACT_ACTIVATION_AT` nie tworzą
   procesów i w UI pozostają neutralne: „Brak danych sprzed uruchomienia”.

## 3. Zakres implementacji

### 3.1. Migracja `0200_candidate_contact_coordination`

Dodano:

- `candidate_contact_cases`;
- `candidate_contact_opportunities`;
- `candidate_contact_events`;
- `candidate_contact_traffit_cursors`;
- `candidate_contact_traffit_ledger`;
- powiązanie `calls.contact_case_id`;
- biznesowy wynik telefonu, źródło, callback, hash requestu i klucz
  idempotencji w `calls`.

Statusy i wyniki są przechowywane jako `VARCHAR`; migracja nie dodaje enumów
PostgreSQL.

Ochrona pojemności:

- `queue_slot` ma zakres `1..20`;
- częściowy unikalny indeks na `(owner_user_id, queue_slot)`;
- constraint wymaga slotu dla `queued`/`callback_due`;
- pozostałe stany nie mogą zajmować slotu.

Audyt:

- eventy przechowują zdenormalizowane identyfikatory potrzebne po zamknięciu
  lub usunięciu rekrutacji;
- trigger bazy odrzuca `UPDATE` i `DELETE` na
  `candidate_contact_events`;
- opportunity zachowuje tombstone rekrutacji i nie jest kasowana kaskadowo
  razem z `Job`.

CI wykonuje:

1. upgrade do head;
2. powtórny upgrade do head;
3. downgrade `0200` → `0199_candidate_stage_removals`;
4. upgrade `0199` → `0200`;
5. ponowny upgrade do wszystkich headów.

### 3.2. Model domenowy i worker

Stany procesu:

- `unassigned`;
- `awaiting_capacity`;
- `queued`;
- `callback_due`;
- `cooldown`;
- `handoff_pending`;
- `blocked_no_phone`;
- `suppressed`;
- `completed`;
- `cancelled`.

Wyniki telefonu:

- `connected`;
- `no_answer`;
- `callback_requested`;
- `wrong_number`;
- `do_not_contact`.

Wyniki oferty podczas rozmowy:

- `interested`;
- `maybe`;
- `not_interested`;
- `not_presented`.

`maybe`, `not_presented` i `callback_requested` wymagają przyszłego
`callback_at`. Przy rozmowie wymagany jest dokładnie jeden wynik dla każdej
otwartej opportunity.

Jeden serwis domenowy atomowo zapisuje:

- `Call`;
- wyniki wszystkich ofert;
- zmianę case i slotu;
- eventy audytowe;
- `Candidate.last_contacted_at`.

Ponowienie z tym samym `Idempotency-Key` i tym samym payloadem zwraca poprzedni
wynik. Ponowne użycie klucza z innym payloadem kończy się konfliktem.
`expected_version` chroni przed utratą aktualizacji i daje HTTP `409`.

Worker:

- używa `FOR UPDATE SKIP LOCKED`;
- alokuje slot pod blokadą wiersza użytkownika;
- nadrabia restarty;
- wykonuje EOD turnover idempotentnie przez zmianę stanu/terminu;
- rotuje trwałe retry, aby pierwsze stale zablokowane rekordy nie głodziły
  dalszych;
- waliduje aktywność, rolę i dostęp aktualnego opiekuna;
- zachowuje opiekuna, gdy nowa oferta pojawi się po rozmowie;
- przy `20/20` czeka na slot tego samego opiekuna i nie przepisuje kandydata
  na zapas;
- zmienia opiekuna dopiero po utracie eligibility albo w audytowanym wyjątku.

### 3.3. Terminy

Wszystkie terminy wylicza backend w `Europe/Warsaw`.

- dodanie do 16:00 włącznie w dzień roboczy → termin 18:00 tego dnia;
- dodanie po 16:00 albo w weekend → 10:00 następnego dnia roboczego;
- brak próby do turnoveru 18:00 → audytowane przepisanie;
- pierwszy `no_answer` → 10:00 następnego dnia roboczego;
- drugi `no_answer` → zwolnienie ownera i slotu, 72 godziny cooldownu,
  następnie wybór innej osoby;
- callback obiecany po 18:00 nie jest przepisywany natychmiast tego samego
  wieczoru;
- v1 obsługuje poniedziałek–piątek. Polskie święta są świadomie poza zakresem.

Testy obejmują granice 16:00/18:00/10:00, piątek/weekend, DST Warszawy,
restart po weekendzie i spóźniony intake.

### 3.4. Owner i handoff

Pierwszy owner:

1. właściciel rekrutacji o najwyższym priorytecie;
2. przy remisie najstarsza opportunity;
3. jeśli preferowana osoba jest nieaktywna, bez dostępu albo pełna —
   najmniej obciążona aktywna osoba operacyjna z dostępem do co najmniej jednej
   otwartej oferty;
4. brak osoby daje jawny stan nieprzydzielenia/braku pojemności.

Po rozmowie owner pozostaje odpowiedzialny do chwili, gdy:

- wszystkie przedstawione oferty są odrzucone; albo
- każda zainteresowana oferta ma aktywne spotkanie `screening`/`interview`.

Istniejące spotkanie jest adoptowane także wtedy, gdy zostało utworzone przed
case/opportunity. Anulowanie ostatniego kwalifikującego spotkania przywraca
`handoff_pending`. Kolejne spotkanie dla tej samej pary nie jest ukrywane przez
anulowanie innego.

### 3.5. Triggery NEXUS

Opportunity jest tworzona lub rozszerzana przez:

- utworzenie aktywnego `CandidateStage`;
- promocję shortlisty do pipeline;
- ustawienie shortlisty na `outreach_status=do_kontaktu`;
- istniejące ścieżki automatyzacji, które tworzą aktywny etap;
- import Traffit po aktywacji flag.

Zwykłe dodanie do shortlisty do oceny nie rezerwuje telefonu.

Zamknięcie/usunięcie jednej rekrutacji zamyka tylko jej opportunity. Usunięcie
triggera shortlisty nie zamyka opportunity, jeśli najnowszy etap pipeline nadal
jest aktywny, i odwrotnie. Najnowszy etap, a nie dowolny historyczny wpis,
decyduje o aktywności pipeline.

### 3.6. Traffit — wyłącznie odczyt

Nowy poller:

- czyta wyłącznie `/employees/recruitment_history`;
- działa nie rzadziej niż co 5 minut po aktywacji;
- używa ścisłego `X-Request-Filter`;
- nie uruchamia fallbacku do pełnego skanu po odrzuceniu filtra;
- pobiera cały zestaw przed przesunięciem kursora;
- używa trwałego kursora `(created_at, id)`, overlapu i ledgeru;
- porównuje numeryczne ID numerycznie przy tej samej sekundzie;
- nie przesuwa kursora przy odrzuconym filtrze, błędnym payloadzie ani
  konflikcie dwóch różnych payloadów o tym samym external ID;
- deduplikuje identyczne external ID wewnątrz jednego page-setu przed
  jakimkolwiek efektem domenowym;
- zapisuje brakujące lub niejednoznaczne mapowania jako wyjątki;
- retry wyjątku jest fair według najstarszej ostatniej próby.

Strict poller i dzienny importer używają tej samej osi `created_at, id`.
Wspólny watermark domenowy chroni przed ponownym otwarciem przez stare eventy
niezależnie od źródła:

- terminal Traffit bez istniejącej opportunity zapisuje durable watermark, ale
  nie tworzy case ani slotu;
- starszy start z strict pollera lub daily importu jest ignorowany;
- lokalne zamknięcie w NEXUS i `not_interested` zapisują id-less source fence;
- event Traffit starszy lub równy lokalnemu zamknięciu nie otwiera procesu;
- ściśle nowszy event może rozpocząć nowy cykl;
- `do_not_contact` pozostaje bezwzględną blokadą automatycznego reopen.

Nie dodano webhooka, outboxu, przesunięć pipeline ani żadnego klienta zapisu
NEXUS → Traffit.

## 4. API, role i PII

Dodano:

- `GET /api/candidate-contact/status`;
- `GET /api/candidate-contact/queue`;
- `GET /api/candidate-contact/candidates/{candidate_id}`;
- `GET /api/candidate-contact/oversight`;
- `POST /api/candidate-contact/cases/{id}/attempts`;
- `POST /api/candidate-contact/cases/{id}/reassign`.

Role:

- telefon i własna kolejka: `recruiter`, `sourcer`, `tac`;
- oversight i awaryjny reassign: `admin`, `head_of_recruitment`;
- `viewer/user` jest wykluczony.

PII jest widoczne tylko wtedy, gdy użytkownik ma dostęp do co najmniej jednej
powiązanej rekrutacji. Niepowiązany użytkownik nie dostaje case ani PII.

### Jawna decyzja do review: minimalna projekcja cross-job

Globalny opiekun musi przedstawić wszystkie otwarte oferty i zapisać wynik dla
każdej z nich. Dlatego, jeśli ma zwykły dostęp do co najmniej jednej powiązanej
rekrutacji i jest aktualnym ownerem case, endpoint kontaktowy pokazuje mu
minimalną projekcję wszystkich otwartych ofert w tym case:

- ID i tytuł rekrutacji;
- klient;
- właściciel rekrutacji;
- wynik i status spotkania.

Nie daje to dostępu do pełnego endpointu `Job` ani pozostałych danych tych
rekrutacji. Inny, niebędący globalnym ownerem użytkownik widzi wyłącznie oferty
z własnego scope. Manager w oversight widzi wszystkie powiązane oferty.

Claude powinien jawnie zaakceptować lub odrzucić tę wąską capability.

### Jawna decyzja do review: dodatkowe membership checks

Ścieżki shortlisty i kalendarza dostały fail-closed membership checks przed
mutacją. To jest defense-in-depth potrzebne, aby nowy globalny proces nie stał
się bocznym kanałem do cudzej rekrutacji, ale może ujawnić starsze workflow,
które polegało na zbyt szerokim dostępie.

Claude powinien szczególnie sprawdzić regresje:

- dodanie/edycja/usunięcie/promocja shortlisty przez prawidłowe role;
- tworzenie i aktualizacja eventu z opcjonalnym `job_id`;
- synchronizacja M365 dla eventów kandydata.

## 5. Frontend

Dodano:

- `/candidates/contact-queue`;
- preview `/preview/contact-queue`;
- jeden kandydat jako jeden rekord z listą wszystkich ofert;
- wykorzystanie slotów `N/20`;
- wspólny `ContactOutcomeSheet` na kolejce, quick view i profilu;
- callback z obowiązkową datą;
- jeden request na zatwierdzenie, z `Idempotency-Key`;
- obsługę `409` przez odświeżenie aktualnej wersji case;
- badge na liście, kaflach, quick view, profilu i Kanbanie;
- widget „Moja kolejka” dla rekrutera;
- oversight i wyjątki dla Head of Recruitment;
- licznik handoffów bez opiekuna;
- fail-closed rollout gate — elementy są ukryte, gdy funkcja jest OFF.

Kliknięcie numeru telefonu nie zapisuje próby. Stan zmienia dopiero
zatwierdzenie formularza wyniku.

Middleware dopuszcza stronę operacyjną tylko dla `recruiter`, `sourcer`, `tac`.
Admin i Head of Recruitment używają panelu oversight.

## 6. Flagi i konfiguracja

Wszystkie flagi mają domyślnie `False`:

- `CANDIDATE_CONTACT_ENABLED`;
- `CANDIDATE_CONTACT_ASSIGNMENT_ENABLED`;
- `CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED`.

Wymagany jest jawny:

- `CANDIDATE_CONTACT_ACTIVATION_AT`.

Dodatkowe parametry:

- `CANDIDATE_CONTACT_WORKER_INTERVAL_SECONDS` — domyślnie 60;
- `CANDIDATE_CONTACT_WORKER_BATCH_SIZE` — domyślnie 100;
- `CANDIDATE_CONTACT_TRAFFIT_POLL_INTERVAL_SECONDS` — domyślnie 300;
- `CANDIDATE_CONTACT_TRAFFIT_OVERLAP_MINUTES` — domyślnie 15.

Child flags są efektywne tylko przy włączonym `CANDIDATE_CONTACT_ENABLED`.
Traffit intake bez daty aktywacji nie startuje.

Zmiana flag środowiskowych wymaga restartu procesu aplikacji.

## 7. Wyniki lokalne po rebase

### Backend

- bazowy SHA po rebase:
  `7c7c2a5bab28fd29ef64f6bfafdea3aa29d02441`;
- `ruff check`: PASS;
- `ruff format --check app/`: PASS, 568 plików;
- `python -m compileall`: PASS;
- import `app.main`: PASS;
- `bash -n backend/entrypoint.sh`: PASS;
- `git diff --check`: PASS;
- `alembic heads`: `0200_candidate_contact_coordination (head)`;
- szybkie testy: 171 PASS:
  - 162 testy domeny/czasu/Traffit client/mapper;
  - 9 runtime bez bazy;
- kolekcja testów kontaktu: 59 testów:
  - 45 integracyjnych PostgreSQL;
  - 5 runtime PostgreSQL;
  - 9 runtime bez PostgreSQL.

Lokalny PostgreSQL nie był dostępny, a używanie lokalnego Dockera jest
zabronione przez instrukcje repozytorium. 50 testów wymagających PostgreSQL ma
wykonać hosted CI.

### Frontend

- ESLint: PASS, tylko istniejące ostrzeżenia baseline;
- token guard: PASS, 30 plików;
- TypeScript `tsc --noEmit`: PASS;
- Vitest z coverage i jednym workerem: 75 plików / 796 testów PASS;
- Next production build: PASS;
- route `/candidates/contact-queue`: wygenerowana;
- route `/preview/contact-queue`: wygenerowana.

Manualny browser QA preview wykonano dla 390/768/1440 px:

- brak poziomego overflow;
- jeden kandydat pokazuje wiele ofert;
- callback wymaga terminu;
- układ kolejki i formularza pozostaje używalny.

Podczas QA wykryto i naprawiono błąd granicy Server/Client Component w preview.
Po bezkonfliktowym rebase ponowiono pełne testy i production build.

Dwa lokalne przebiegi coverage z domyślną równoległością miały odpowiednio
1 i 2 timeouty po 5 s w niezmienianych testach baseline. Każdy timeout przeszedł
izolowanie, a pełny przebieg `npm run test:coverage -- --maxWorkers=1` zakończył
się wynikiem 796/796. Nie zmieniano cudzych timeoutów; dokładny równoległy
przebieg w hosted CI również zakończył się wynikiem 796/796.

## 8. Hosted CI

Draft PR: <https://github.com/artur-t-96/Nexus/pull/984>

### Pierwszy przebieg

Run
[30354673961](https://github.com/artur-t-96/Nexus/actions/runs/30354673961)
potwierdził:

- PASS: migracja upgrade/downgrade/re-upgrade;
- PASS: import aplikacji;
- PASS: frontend, w tym równoległy Vitest coverage i build;
- PASS: Gitleaks, Trivy/Hadolint i automatyczny review;
- backend pytest: 3661 PASS, 14 SKIP, 3 FAIL.

Trzy błędy były ograniczone do nowej funkcji i zostały przeanalizowane przed
poprawką:

1. Case z istniejącym spotkaniem pozostawał w `queued`, ponieważ sesja używa
   `autoflush=False`, a agregacja opportunities następowała przed jawnym
   flushowaniem zmiany statusu.
2. Test lifecycle tworzył aktywne spotkania przed rozmową, co po uwzględnieniu
   wymaganego zachowania istniejących spotkań kończyło handoff wcześniej niż
   zakładał sam test.
3. Test overlap Traffit tworzył kandydata bez telefonu, więc domena poprawnie
   zwracała `blocked_no_phone` i `due_at=None`, zamiast testowanego terminu
   kolejki.

Commit `10160870`:

- dodał jawny `await db.flush()` przed agregacją opportunities;
- przesunął utworzenie spotkań w teście lifecycle za udany kontakt;
- dodał telefon i jawne asercje `unassigned`/braku slotu w teście overlap.

Flush pozostaje częścią tej samej transakcji: nie wykonuje commitu, nie zwalnia
blokad i nie osłabia atomowości zapisu.

### Pełny przebieg po poprawce

Run
[30356426647](https://github.com/artur-t-96/Nexus/actions/runs/30356426647)
na `10160870` zakończył się zielono:

- Backend: PASS po 17 min 50 s;
- pytest z PostgreSQL: 3664 PASS, 14 SKIP, 78 warnings, 975.11 s;
- migracja upgrade/downgrade/re-upgrade: PASS;
- import aplikacji: PASS;
- Frontend: PASS po 3 min 24 s, w tym lint, typecheck, równoległy Vitest
  coverage 75 plików / 796 testów i production build;
- Gitleaks: PASS;
- Trivy/Hadolint: PASS;
- automatyczny review
  [30356427334](https://github.com/artur-t-96/Nexus/actions/runs/30356427334):
  PASS;
- automatyczny Vercel PR preview: PASS.

Ten wynik obejmuje ostatni commit zmieniający kod. Końcowy commit handoffu jest
wyłącznie dokumentacyjny i również podlega checkom PR przed przekazaniem.

## 9. Scenariusz aktywacji

Każdy etap wymaga osobnego GO i obserwacji. Flagi są globalne; implementacja
nie zawiera cohortingu per-user.

### Etap 0 — schema/code dark deploy

Ustawienia:

- wszystkie trzy flagi OFF;
- `CANDIDATE_CONTACT_ACTIVATION_AT` jeszcze nieużywana.

Warunki GO:

- review Claude bez nierozwiązanych P0/P1;
- zielone wymagane CI;
- backup przed migracją;
- poprawny deployed SHA;
- `/api/health`, `/api/health/deep`, `/api/health/alembic` bez regresji;
- `0200` jako faktyczny head na środowisku.

Oczekiwany efekt:

- nowe tabele/kolumny są obecne;
- brak case, slotów, workera i requestów Traffit;
- UI pozostaje ukryte.

### Etap 1 — NEXUS-only shadow intake, bez assignmentu

Ustawienia:

- wybrać i zapisać niezmienną granicę
  `CANDIDATE_CONTACT_ACTIVATION_AT`;
- `CANDIDATE_CONTACT_ENABLED=true`;
- `CANDIDATE_CONTACT_ASSIGNMENT_ENABLED=false`;
- `CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED=false`.

Oczekiwany efekt:

- nowe, kwalifikujące mutacje NEXUS tworzą case bez slotów;
- historyczny backlog pozostaje poza zakresem;
- można audytować duplikaty, trigger coverage i projekcje PII;
- brak requestów nowego intake Traffit.

Warunki GO dalej:

- jeden case per kandydat;
- brak historycznego backlogu;
- brak nieuprawnionych PII;
- liczba nowych opportunities zgodna z triggerami;
- brak nieoczekiwanych wyjątków shortlisty/kalendarza.

### Etap 2 — automatyczny assignment i telefony

Ustawienia:

- `CANDIDATE_CONTACT_ASSIGNMENT_ENABLED=true`;
- intake Traffit nadal OFF.

Oczekiwany efekt:

- istniejące shadow case są podnoszone przez worker;
- limit 20 jest egzekwowany;
- rekruterzy używają formularza wyniku;
- EOD/callback/cooldown działają wyłącznie w NEXUS.

Warunki GO dalej:

- brak 21. slotu;
- brak duplikatów Call przy retry;
- stabilny backlog i brak starve;
- poprawne handoffy CalendarEvent;
- zaakceptowany workflow operacyjny Head of Recruitment.

### Etap 3 — ścisły intake Traffit

Ustawienia:

- `CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED=true`;
- pozostałe flagi pozostają ON.

Warunki wejścia:

- potwierdzony read-only token i endpoint;
- filtr `recruitment_history` zaakceptowany przez tenant;
- monitoring lag/status/error/exception ledger;
- potwierdzone exact mappingi kandydatów i ofert;
- jawny NO-GO dla jakiegokolwiek fallbacku do full scan.

Oczekiwany efekt:

- poll maksymalnie co 5 minut;
- brak zapisów do Traffit;
- daily importer nie duplikuje procesu;
- konflikt lub błąd filtra zatrzymuje bezpiecznie kursor.

## 10. Rollback i containment

### Najszybszy rollback runtime

1. `CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED=false`;
2. `CANDIDATE_CONTACT_ASSIGNMENT_ENABLED=false`;
3. `CANDIDATE_CONTACT_ENABLED=false`;
4. restart aplikacji;
5. potwierdzenie braku requestów pollera, przetwarzania workera i widoczności
   UI.

Wyłączenie flag nie usuwa audytu ani danych. To preferowany containment.

### Rollback kodu

- revert/rollback aplikacji do poprzedniego zatwierdzonego SHA;
- pozostawić addytywną migrację `0200` na bazie, jeśli powstały już jakiekolwiek
  rekordy kontaktu;
- starszy kod ignoruje nowe tabele/kolumny.

### Downgrade migracji

Downgrade usuwa tabele koordynacji i kolumny Call, więc kasuje dane i audyt.
Jest dopuszczalny wyłącznie:

- przed aktywacją i przed pierwszym zapisem; albo
- po zatwierdzonym backupie i osobnej, świadomej decyzji destrukcyjnej.

Nie wykonywać automatycznego downgrade na produkcji po rozpoczęciu ruchu.

Nie ma rollbacku Traffit, ponieważ implementacja nie zapisuje nic do Traffit.

## 11. Ryzyka i świadome ograniczenia

1. 50 testów PostgreSQL nie mogło zostać wykonanych lokalnie; hosted CI
   potwierdził pełny backend wynikiem 3664 PASS i 14 SKIP.
2. Flagi są globalne, bez cohortingu per użytkownik.
3. Kalendarz dni roboczych nie uwzględnia polskich świąt.
4. Minimalna projekcja cross-job dla globalnego ownera wymaga jawnej akceptacji
   polityki dostępu.
5. Nowe membership checks shortlisty/kalendarza mogą odsłonić starsze,
   zbyt szerokie workflow.
6. Poller zależy od wsparcia ścisłego filtra przez tenant Traffit; odrzucenie
   filtra celowo zatrzymuje tick.
7. Eventy o rozbieżnym payloadzie i tym samym external ID pozostają wyjątkiem
   do ręcznego wyjaśnienia; nie wybieramy arbitralnie jednego payloadu.
8. Brak lokalnego/produkcyjnego E2E po deployu jest oczekiwany, ponieważ zakres
   kończy się przed wdrożeniem.

## 12. Checklista review dla Claude

### Migracja i dane

- [ ] `0200` ma poprawne `down_revision=0199_candidate_stage_removals`.
- [ ] Upgrade jest idempotentny w warunkach entrypointu.
- [ ] Downgrade/re-upgrade przechodzi w CI.
- [ ] Partial unique index i constraints uniemożliwiają 21. slot.
- [ ] Eventy są append-only na poziomie DB.
- [ ] Usunięcie Job zachowuje zamkniętą opportunity i audit.
- [ ] Brak nowych enumów PostgreSQL.

### Domena i współbieżność

- [ ] Deterministyczny owner odpowiada regule priorytet → najstarsze
  przypisanie → najmniejsze obciążenie.
- [ ] Nowa oferta nie odbiera sticky ownera, także przy `20/20`.
- [ ] `Call`, outcomes, case, audit i `last_contacted_at` są jedną transakcją.
- [ ] Powtórzenie Idempotency-Key nie tworzy drugiej próby.
- [ ] Stara wersja daje `409`.
- [ ] Dwie próby, cooldown 72 h i reassignment działają po restartach.
- [ ] Callback po 18:00 nie jest przepisywany natychmiast.
- [ ] Ownerless handoff nie spamuje audytu i nie głodzi kolejki.
- [ ] `wrong_number` zachowuje ownera, o ile nadal jest eligible i ma slot.
- [ ] Wyczyszczenie numeru zwalnia slot przed terminem.

### Traffit

- [ ] Flagi OFF oznaczają zero requestów.
- [ ] Odrzucony filtr nie uruchamia pełnego skanu ani nie przesuwa kursora.
- [ ] Overlap i daily importer nie tworzą drugiego case/opportunity.
- [ ] Numeric ID rozstrzyga equal-second ordering.
- [ ] Terminal bez opportunity nie tworzy case/slotu.
- [ ] Strict i daily ingress respektują wspólny terminal watermark.
- [ ] Lokalne close/`not_interested` blokują stare eventy Traffit.
- [ ] In-tick duplikat tworzy najwyżej jeden ledger row.
- [ ] Konflikt payloadu jest fail-closed.
- [ ] W diffie nie ma zapisu NEXUS → Traffit.

### ACL i PII

- [ ] Telefon zapisują tylko `recruiter`, `sourcer`, `tac`.
- [ ] Reassign/oversight mają tylko `admin`, `head_of_recruitment`.
- [ ] Viewer jest wykluczony.
- [ ] Niepowiązany użytkownik nie widzi case ani PII.
- [ ] Częściowo powiązany nie-owner widzi tylko własne opportunities.
- [ ] Jawnie zaakceptowano minimalną projekcję wszystkich ofert dla globalnego
  ownera.
- [ ] Przetestowano nowe membership checks shortlisty i kalendarza.

### Frontend

- [ ] Kandydat występuje raz przy wielu ofertach.
- [ ] `N/20` liczy wyłącznie sloty telefonu.
- [ ] Kliknięcie numeru nie zapisuje próby.
- [ ] Formularz wykonuje jeden POST i wymaga callbacku tam, gdzie trzeba.
- [ ] `409` odświeża case zamiast nadpisywać stan.
- [ ] Badge są spójne na wszystkich powierzchniach.
- [ ] Widoki 390/768/1440 nie mają regresji.
- [ ] UI jest ukryte przy feature flag OFF.

### Release gate

- [ ] Wszystkie wymagane checki PR są zielone.
- [ ] Claude nie znalazł nierozwiązanych P0/P1.
- [ ] PR pozostaje draft do świadomej decyzji o merge.
- [ ] Brak merge/deploy/config/prod write w ramach pracy Codex.
