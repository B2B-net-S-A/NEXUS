# Moduł 5 — Kontrakty, onboarding, realizacja współpracy, rozliczenia i offboarding

## Audyt, rekomendacja docelowa i szczegółowy plan implementacyjny dla Claude Code

- Data audytu: 2026-07-16
- Repozytorium: NEXUS
- Stan kodu użyty do audytu: origin/main = f3e3516e717a5f95f38f1de4d42e9f0e74fbd948
- Stan produkcji w chwili kontroli: wersja f3e3516e717a5f95f38f1de4d42e9f0e74fbd948, HTTP 200, status healthy
- Charakter pracy: audyt read-only kodu i produkcji; bez zmian danych produkcyjnych
- Adresat planu: Claude Code / Opus realizujący serię małych, odwracalnych PR-ów

---

## 1. Streszczenie zarządcze

Obecny moduł nie jest jeszcze pełnym systemem obsługi współpracy z konsultantem. Jest zbiorem kilku częściowo połączonych funkcji:

- rejestru Contract,
- generatora umów B2B,
- dwóch niezależnych ścieżek podpisywania,
- dokumentów i aneksów,
- ClientOrder,
- prostej checklisty onboardingu,
- ewidencji sprzętu,
- ręcznych faktur,
- alertów terminowych,
- ręcznego placementu DynaReporter,
- raportów marży i retencji.

Każda z tych części ma własny stan i własne writery. Nie istnieje jeden agregat, który odpowiada na pytanie:

> Czy ta konkretna osoba, dla tej konkretnej oferty i klienta, ma prawidłowo zawartą umowę, ważne zamówienie, ukończony onboarding, faktycznie rozpoczęła pracę, ma aktualne stawki, rozliczony czas, kontrolowany sprzęt oraz poprawnie przeprowadzony offboarding?

Najważniejszy wniosek:

> Nie należy dalej rozbudowywać Contract jako połączenia dokumentu prawnego, placementu, assignmentu, harmonogramu stawek, zamówienia klienta i faktury. Trzeba rozdzielić stan prawny umowy od operacyjnego lifecycle współpracy i wprowadzić kanoniczny agregat Engagement.

### 1.1. Najpilniejsze ryzyka

1. Contract może stać się active bez podpisanego dokumentu, ważnego zamówienia klienta i ukończonego onboardingu.
2. Produkcja rzeczywiście zawiera aktywny kontrakt bez dokumentów, bez checklisty onboardingu i bez wpisów timeline.
3. Publiczny link podpisu nie jest atomowo konsumowany i nie jest unieważniany przy withdraw/regenerate.
4. Wewnętrzny flow podpisu akceptuje wynik bez QES, jeżeli walidator DSS nie jest skonfigurowany.
5. Wysłany dokument nie zawsze wskazuje niezmienny snapshot i hash dokładnej wersji.
6. Generic create/PATCH przyjmuje status, a osobne endpointy activate/finalize/create-with-order również ustawiają active.
7. Przyszłe wcześniejsze zakończenie nadal natychmiast ustawia ended na obecnym origin/main i produkcji.
8. Dedykowany terminate nadpisuje planowaną datę końca datą faktyczną, przez co raport nie potrafi wiarygodnie rozpoznać wcześniejszego zakończenia.
9. Contract i dokumenty prawne można fizycznie usuwać wraz z historią zależną.
10. ClientOrder i legacy Contract.client_order_end_date są dwoma źródłami prawdy.
11. Rate jest przechowywany jako cache i jednocześnie w kilku harmonogramach effective-dated.
12. Nie istnieje timesheet ani approval klienta, więc faktura nie ma kontrolowanego źródła ilości.
13. Faktury są mutowalne, usuwalne i nie stanowią bezpiecznej księgi finansowej.
14. Nie istnieje offboarding ani wymuszenie zwrotu sprzętu, odebrania dostępów i finalnego rozliczenia.
15. Alerty są in-process, oparte o exact-date windows i mogą zostać pominięte po restarcie lub zdublowane przez kilka replik.
16. Placement, hired, aktywny Contract, ClientOrder i DynaReporter mogą wzajemnie się nie zgadzać.
17. Produkcyjny profil klienta potwierdza taki rozjazd: aktywny konsultant, ale Placementy (0) i brak powiązanej oferty.

### 1.2. Rekomendowany model

Moduł powinien zostać podzielony na następujące agregaty:

1. Placement — decyzja handlowa/rekrutacyjna utworzona w Module 4.
2. Engagement — operacyjna współpraca wynikająca z placementu.
3. LegalAgreement oraz AgreementVersion — umowa i niezmienne wersje artefaktu prawnego.
4. SignatureEnvelope, ExpectedSigner i SignatureEvidence — proces podpisu konkretnej wersji.
5. ClientOrder oraz ClientOrderVersion — pokrycie zamówieniem klienta.
6. RateTerm — wersjonowane warunki candidate/client/framework.
7. OnboardingPlan i OffboardingPlan — obowiązki, dowody i wyjątki.
8. Asset i AssetAssignment — custody sprzętu.
9. TimesheetPeriod, TimeEntry i TimesheetApproval — potwierdzone źródło ilości.
10. BillingDocument, BillingLine, PaymentEvent i CreditNote — ledger rozliczeń.
11. SuccessCheckIn, AssignmentRisk, SuccessAction i RenewalDecision — delivery success.
12. DomainEvent, OutboxMessage, InboxMessage, Obligation i JobRun — trwała orkiestracja.

### 1.3. Rekomendacja wdrożeniowa

Nie robić big-bang rewrite. Plan ma 41 PR-ów w ośmiu falach:

- Fala A: containment najgroźniejszych błędów obecnej produkcji.
- Fala B: niezmienny dokument prawny i bezpieczny podpis.
- Fala C: Engagement w shadow mode oraz jeden hire/start command.
- Fala D: ClientOrder v2 i kanoniczne RateTerm.
- Fala E: onboarding, success, offboarding i asset custody.
- Fala F: timesheet i bezpieczny billing.
- Fala G: outbox, obligations, integracje, projekcje i observability.
- Fala H: reconciliacja, cutover i wyłączenie legacy writes.

Pierwszym zadaniem Claude nie powinno być tworzenie nowych ekranów. Najpierw należy:

1. uruchomić read-only anomaly scanner,
2. zamknąć dowolne status writes,
3. zabezpieczyć signing links i QES,
4. zatrzymać hard delete dokumentów prawnych,
5. wdrożyć wąską poprawkę przyszłego wcześniejszego zakończenia,
6. naprawić resource scope dokumentów i zamówień,
7. dopiero później budować Engagement.

---

## 2. Zakres i granice modułu

### 2.1. W zakresie

Audyt obejmuje pełny lifecycle po decyzji o zatrudnieniu:

- handoff z zaakceptowanej oferty/placementu,
- utworzenie współpracy,
- przygotowanie i wersjonowanie umowy,
- umowę ramową klienta oraz aneksy,
- podpis wewnętrzny, Autenti i flow offline,
- zamówienia klienta i ich przedłużenia,
- candidate/client/framework rates,
- aktywację i faktyczny start,
- onboarding,
- assignment/delivery success,
- sprzęt i custody,
- rejestr czasu i akceptację klienta,
- fakturowanie, płatności i DSO,
- renewal,
- wypowiedzenie i planowane zakończenie,
- offboarding,
- zakończenie i retencję,
- raportowanie, alerty, integracje i operacje.

### 2.2. Granica z Modułem 4

Moduł 4 powinien kończyć się utworzeniem kanonicznego Placement z zaakceptowanej, wersjonowanej Offer.

Moduł 5 zaczyna się od idempotentnej komendy:

~~~text
CreateEngagementFromPlacement(placement_id, idempotency_key)
~~~

Nie należy:

- ponownie implementować decyzji hired w Contract,
- traktować surowego CandidateStage.hired jako trwałego placementu,
- tworzyć Contract bez wskazania recruitment_process_id/placement_id,
- uznawać podpisu umowy za źródło decyzji rekrutacyjnej,
- pozwalać DynaReporter tworzyć niezależny placement.

### 2.3. Rozróżnienie Placement i Engagement

Placement jest faktem: kandydat został wybrany dla konkretnej rekrutacji na konkretnych zaakceptowanych warunkach.

Engagement jest realizacją tego placementu:

- może być przygotowywany,
- może nie dojść do startu,
- może zostać wstrzymany,
- może mieć wiele kolejnych ClientOrder i AgreementVersion,
- ma onboarding, timesheety, billing, success i offboarding,
- zachowuje datę planowaną, faktyczną i przyczynę zakończenia.

Docelowo:

- jedno Placement ma maksymalnie jedno nieanulowane Engagement,
- ponowne zatrudnienie na inną ofertę tworzy nowe Placement i nowe Engagement,
- przedłużenie nie tworzy nowego Placement; tworzy nową wersję warunków/orderu w tym samym Engagement.

### 2.4. Świadomie poza pierwszym rolloutem

Pierwsze fale nie muszą implementować pełnej księgowości:

- wysyłki do KSeF,
- pełnej księgi głównej,
- automatycznych przelewów,
- payroll,
- zaawansowanego revenue recognition,
- automatycznych kursów FX do rozliczeń prawnych.

Jednocześnie model BillingDocument musi od początku pozwalać na:

- net/VAT/gross,
- line items,
- korekty,
- partial payments,
- external IDs,
- jawne waluty,
- bezpieczny późniejszy adapter KSeF/ERP.

---

## 3. Źródła dowodowe i ograniczenia

### 3.1. Stan repozytorium

Przed finalizacją audytu wykonano git fetch origin.

Kanoniczny kod:

- origin/main: f3e3516e717a5f95f38f1de4d42e9f0e74fbd948,
- commit: feat(pipeline): PR-00 — read-only inventory anomalii lifecycle (plan M4) (#780),
- data commitu: 2026-07-16T14:40:22+02:00.

Głęboki audyt modułu wykonano na czystym eksporcie wcześniejszego origin/main:

~~~text
/tmp/nexus-module5-origin-6472b67
~~~

Przed finalizacją origin/main przesunął się dwukrotnie: z 6472b67 do 9d0a16e, a następnie do f3e3516. Przejrzano pełne diffy oraz ponownie sprawdzono CI i entrypoint. Żaden z audytowanych plików Contract, ClientOrder, B2B generatora, signing, invoices ani ich frontendowych ekranów nie zmienił się. Pierwszy commit dotknął głównie analytics/KPI/matching. Drugi dodał Modułowi 4 endpoint /api/admin/pipeline-inventory, jego testy i rejestrację w main.py. Endpoint zawiera już checki hired_no_contract, multiple_live_contracts i contract_no_hired, więc PR-00 tego planu został poprawiony tak, aby ich nie dublował. Ustalenia modułu pozostają aktualne dla dokładnego f3e3516.

Lokalny checkout użytkownika jest inną prawdą:

- branch: wip/uncommitted-main-snapshot-2026-07-15,
- HEAD: 297c151,
- zawiera wcześniejsze commity ratunkowe i nieśledzone dokumenty,
- nie został potraktowany jako stan produkcji,
- nie został zresetowany, stashowany ani modyfikowany poza dodaniem tego raportu.

### 3.2. Istotny patch ratunkowy istniejący tylko lokalnie

Lokalny branch zawiera poprawkę:

- backend/app/api/contracts.py:2008-2017 używa _status_after_end_date_change dla future-dated early termination,
- backend/tests/test_contract_amendments.py zawiera test test_future_early_termination_keeps_contract_active.

Current origin/main nadal ma:

~~~python
elif data.amendment_type == ContractAmendmentType.early_termination:
    end = data.new_end_date or data.effective_date
    contract.end_date = end
    contract.status = ContractStatus.ended
~~~

Wniosek:

- poprawka nie jest na produkcji,
- Claude powinien najpierw obejrzeć dokładny diff ratunkowy,
- przenieść wyłącznie wąską zmianę i test na świeżą gałąź z origin/main,
- nie cherry-pickować całego 297c151 ani nie wdrażać mieszanego worktree.

### 3.3. Stan produkcji

GET https://api.nexus.dynaminds.pl/api/health z wymaganym User-Agent zwrócił:

~~~json
{
  "status": "healthy",
  "version": "f3e3516e717a5f95f38f1de4d42e9f0e74fbd948",
  "deployedAt": "2026-07-16T12:40:35Z",
  "checks": {
    "database": "healthy",
    "m365": "healthy",
    "m365_encryption": "healthy",
    "cloudtalk": "unhealthy",
    "autenti": "unconfigured",
    "traffit": "degraded",
    "cortex": "healthy",
    "anthropic": "configured"
  }
}
~~~

HTTP status: 200.

W trakcie końcowego deploy najpierw wystąpiło przejściowe 503/502, po czym health wrócił do healthy i dokładnego f3e3516. Stan końcowy powyżej pochodzi z ponownej kontroli po zakończeniu wdrożenia.

Ważne:

- produkcja odpowiada dokładnie origin/main,
- Autenti jest unconfigured, więc obecne ryzyka tego flow są ryzykiem przed aktywacją i podczas przyszłego rollout, nie dowodem aktywnej wysyłki Autenti,
- in-house signing nie jest osobnym twardym gate w głównym health,
- healthy nie oznacza spójności danych biznesowych.

### 3.4. Produkcyjna kontrola UI

Wykonano wyłącznie bezpieczne odczyty w zalogowanej sesji Chrome. Nie klikano operacji zapisujących.

Kontrola UI została wykonana przed końcowymi przesunięciami produkcji z 6472b67 do f3e3516. Późniejsze commity dotyczyły analytics/KPI/matching oraz admin pipeline inventory. Końcowa próba odświeżenia obu otwartych tras zwróciła lokalne ERR_BLOCKED_BY_CLIENT. Porównanie commitów potwierdziło, że żaden opisany niżej ekran Contract/Client nie zmienił kodu między tymi wersjami; aktualny backend health i dokładny SHA zostały potwierdzone osobno.

#### Rejestr kontraktów

Widok /contracts pokazał:

- 481 kontraktów,
- 18 kończących się w ciągu 30 dni,
- surowe etykiety active/draft w tabeli,
- przyszłe kontrakty już oznaczone jako active:
  - start 2026-08-03,
  - start 2026-09-01,
- draft ze start_date 2026-06-12 nadal oczekujący na uzupełnienie.

#### Obsługa kontraktorów

Widok /contractors pokazał:

- 19 draftów do uzupełnienia,
- 415 active,
- 18 ending,
- kilka active z przyszłą datą startu,
- active bez daty końca,
- active bez powiązanej oferty,
- active bez stawek,
- ujemną marżę -1,00 zł na jednym z widocznych rekordów,
- komunikat, że bez stawek, dat, typu i trybu nie można aktywować, mimo że lista zawiera rekordy active niespełniające tej obietnicy.

To dowodzi, że status active nie oznacza obecnie faktycznego startu ani pełnej gotowości.

#### Kontrakt #15

Widok /contracts/15 pokazał:

- status Aktywny,
- start 2026-07-01,
- kontrakt bez daty końca,
- stawkę klienta 18 000 zł, kandydata 14 000 zł i marżę 4 000 zł,
- przycisk Usuń dostępny dla aktywnego kontraktu,
- zakładkę Dokumenty z komunikatem Brak załączonych dokumentów,
- zakładkę Onboarding z komunikatem Brak checklisty,
- zero sprzętu,
- zero faktur,
- zero aneksów,
- Timeline z komunikatem Brak wpisów w historii.

Aktywny kontrakt może więc:

- nie mieć dokumentu,
- nie mieć dowodu podpisu,
- nie mieć checklisty,
- nie mieć audytowalnej historii,
- być nadal fizycznie usuwalny z UI.

#### Profil klienta Bank Pekao SA

Widok /clients/3 pokazał:

- aktywnego konsultanta,
- brak powiązanej oferty,
- Placementy (0),
- 1 aktywny konsultant,
- aktywne MRR opisane jako 4 000 zł miesięcznej marży,
- LTV klienta 0 zł,
- trzy pozycje w sekcji Otwarte rekrutacje, każda oznaczona Lost.

Jeden ekran zawiera więc kilka sprzecznych interpretacji tej samej relacji klient–rekrutacja–placement–kontrakt.

#### Analityka kontraktów

Widok /contracts/analytics pokazał:

- miesięczną marżę 2 184 171 zł,
- miesięczny przychód 10 051 531 zł,
- utilization jako brak danych,
- forecast jako brak danych,
- 415 aktywnych,
- 60 aktywnych w kategorii roli Unknown,
- 368 konsultantów bez hubu i regionu,
- 29 zakończeń, wszystkie z powodem unspecified,
- 100% retencji dla wszystkich pokazanych klientów.

Te liczby nie są wiarygodnym obrazem realnej ekonomiki:

- current active status obejmuje future-start,
- zakończenie nadpisuje planowaną datę,
- wszystkie powody są unspecified,
- brak timesheetów,
- wartości są oparte o cache i domyślne monthly assumptions,
- waluty mogą zostać zsumowane bez FX,
- ending jest w części zapytań pomijane.

### 3.5. Ograniczenia

Audyt nie:

- modyfikował danych,
- wysyłał podpisów,
- pobierał prywatnych dokumentów,
- testował destrukcyjnych endpointów,
- uruchamiał lokalnego Dockera,
- wykonywał pełnego integration suite,
- zakładał, że lokalny WIP jest produkcją.

Wnioski o możliwych race conditions, restart gaps i cascade delete wynikają z analizy kodu i schematu. Wnioski o istniejących rekordach active bez dokumentów/onboardingu wynikają bezpośrednio z produkcyjnego UI.

---

## 4. Obecny przepływ i źródła prawdy

### 4.1. Dzisiejszy happy path nie jest jeden

W systemie występują co najmniej następujące ścieżki:

1. Pipeline przechodzi na legacy hired:
   - automatycznie tworzy draft Contract,
   - automatycznie tworzy draft ClientOrder,
   - ustawia start_date na dzisiaj,
   - nie tworzy kanonicznego Engagement.

2. ClientOrder flow B:
   - tworzy Contract od razu jako active,
   - tworzy ClientOrder od razu jako active,
   - może działać bez placementu, podpisu, dokumentu i onboardingu.

3. B2B Generator:
   - tworzy lub mutuje draft Contract,
   - zapisuje draft_content_html,
   - osobno prowadzi B2BGeneratedContract,
   - frontend może wygenerować kolejne osierocone drafty przy send/mark/upload.

4. Contract /activate:
   - wymaga tylko podstawowych pól,
   - nie wymaga podpisanego AgreementVersion,
   - nie wymaga ClientOrder coverage,
   - nie wymaga onboardingu.

5. Contract /draft/finalize:
   - zapisuje HTML jako document snapshot,
   - ustawia Contract active,
   - emituje notification contract_signed,
   - nie ma prawnego podpisu.

6. In-house signing:
   - tworzy publiczne linki,
   - po dwóch approval przesuwa pipeline na hired,
   - celowo nie aktywuje Contract.

7. Autenti:
   - wymaga, aby Contract był już active/ending przed wysłaniem,
   - po completed nie uruchamia spójnego Engagement start,
   - działa przez background task i kilka commitów.

8. Offline mark sent/upload:
   - operator potwierdza operację,
   - stan podpisu/pipeline może być zmieniony bez provider proof.

9. Traffit import:
   - może odtworzyć hired inną ścieżką,
   - nie musi przejść przez hook tworzący Contract/Order.

10. DynaReporter:
    - może ręcznie utworzyć placement niezależny od powyższych danych.

### 4.2. Dzisiejsze niezależne prawdy

| Pytanie biznesowe | Obecne możliwe źródła | Problem |
|---|---|---|
| Czy kandydat został zatrudniony? | CandidateStage.hired, Placement z Modułu 4, DrPlacementDetail, podpis | Brak jednej prawdy |
| Czy współpraca trwa? | Contract.status, daty Contract, future start, cron | active nie znaczy started |
| Czy umowa jest zawarta? | Contract active, finalize, DocumentSignature, Autenti, offline | Sprzeczne semantyki |
| Jaka wersja obowiązuje? | ContractDocument, draft HTML, B2BGeneratedContract, MSA file | Brak immutable version/hash |
| Czy klient zamówił usługę? | ClientOrder, client_order_end_date, framework | Dwa źródła daty |
| Jaka jest stawka? | cache Contract, 3 schedules, order, framework | Możliwy drift |
| Ile należy zafakturować? | ręczny amount, hours_pool_consumed, order_consumption | Brak approved quantity |
| Czy onboarding ukończono? | free-form item | Brak gate i dowodów |
| Czy offboarding ukończono? | brak encji | Nie można ustalić |
| Czy sprzęt wrócił? | mutable ContractEquipment | Brak custody ledger |
| Czy alert wysłano? | Notification title/link, fire-and-forget | Brak delivery ledger |

### 4.3. Bezpośrednie writery Contract

Current code zapisuje Contract co najmniej z:

- backend/app/api/pipeline.py,
- backend/app/api/contracts.py,
- backend/app/api/client_orders.py,
- backend/app/api/b2b_contract_generator.py,
- backend/app/tasks/contract_alerts.py,
- signing pipeline hook,
- importów/integracji.

Nie ma jednej command service, która:

- sprawdza inwarianty,
- wykonuje optimistic locking,
- emituje domain event,
- tworzy outbox,
- zapisuje audit entry,
- jest idempotentna.

---

## 5. Co już działa i należy zachować

Plan nie powinien kasować dobrych elementów. Należy zachować i przenieść:

1. Effective-dated candidate/client/framework schedules jako kierunek, ale ujednolicić je w RateTerm.
2. Decimal/NUMERIC dla stawek kontraktowych.
3. Rozróżnienie Contract end_date i ClientOrder timeline jako koncepcję; usunąć tylko legacy scalar.
4. Autenti idempotency keys i provider IDs.
5. Autenti snapshot dokumentu przed wysyłką.
6. DocumentSignatureEvent jako zalążek append-only event ledger.
7. Signer contact snapshot jako zalążek ExpectedSigner.
8. Podpisane PDF pobierane do kontrolowanego storage.
9. Basic activation readiness list, rozszerzoną docelowo o agreement/order/onboarding.
10. Contract amendments jako widoczny użytkownikowi koncept, ale zmienić mutable JSON na typed version transition.
11. UI tabs grupujące dokumenty, aneksy, onboarding, sprzęt, faktury, rate history i timeline.
12. Rejestr kontraktorów z rozdzieleniem draft/active/ending, po zmianie źródła na Engagement.
13. Testy Autenti webhook/signing i rate schedules, po rozszerzeniu o concurrency oraz invariants.
14. ClientAccess.can_view_legal_documents użyte już w framework contracts na current origin/main.
15. Health contract i dokładne version SHA.
16. Existing storage service jako adapter, po dodaniu staging/finalize/compensation i content hash.
17. Istniejący helper _status_after_end_date_change jako krótkoterminową naprawę legacy flow.
18. Wdrożony /api/admin/pipeline-inventory: wersjonowany read-only contract, _snapshot_auth, limitowane próbki bez PII, per-check timeout i izolacja błędów; Moduł 5 ma go rozszerzać bez dublowania zapytań.

---

## 6. Ustalenia P0 — bezpieczeństwo, prawo i integralność

### P0.1. Contract może zostać aktywowany bez wykonanej umowy

Dowody:

- ContractCreate i ContractUpdate przyjmują status.
- create_contract wykonuje payload bez centralnej state machine.
- PATCH wykonuje ogólne setattr.
- /activate wymaga tylko start/end/rates/type/work_mode.
- /draft/finalize ustawia active bez podpisu.
- /draft/finalize publikuje semantykę contract_signed przed trwałym potwierdzeniem pełnego lifecycle i bez transactional outbox.
- /contract-with-order tworzy Contract active i ClientOrder active.
- produkcja ma active Contract #15 bez dokumentów.

Skutek:

- active nie dowodzi ani podpisu, ani startu,
- raporty, marża, alerty i profil klienta traktują rekord jako żywą współpracę,
- możliwe jest wystawienie faktury lub KPI na podstawie rekordu prawnie niegotowego.

Naprawa containment:

- usunąć status z generic create/update DTO,
- dopuścić tylko jawne commands,
- tymczasowo blokować activate/finalize/create-with-order bez jawnego override z powodem,
- odróżnić prepared, fully_executed, ready_to_start i started.

Docelowo:

- LegalAgreement.status nie zmienia Engagement.status automatycznie,
- EngagementStarted wymaga wszystkich gate,
- start jest domain event, nie wartość surowego pola.

Testy:

- generic PATCH active zwraca 422,
- active bez signed version zwraca blocked requirements,
- future start przechodzi najwyżej do ready_to_start,
- retry start command jest idempotentny.

### P0.2. Publiczny link podpisu nie jest revocable i single-use nie jest atomowe

Dowody:

- _load_valid_link sprawdza expires_at i used_at, ale nie status procesu ani revoked_at.
- used_at jest ustawiane dopiero po walidacji/generowaniu.
- withdraw zmienia status DocumentSignature, ale nie unieważnia linków.
- regenerate tworzy nowy link bez unieważnienia poprzednich.
- token jest przechowywany w plaintext jako primary key.
- GET dokumentu używa require_unused=false, więc wykorzystany link nadal może ujawniać umowę do końca TTL.
- finalize nie wykonuje atomowego compare-and-set na statusie envelope i linku w jednej transakcji.

Skutek:

- wycofany dokument nadal może zostać podpisany,
- dwa równoległe requesty mogą oba przejść,
- token wyciekający z DB/logów jest bezpośrednim credentialem,
- nie ma jednoznacznego dowodu, który link był skuteczny.

Naprawa:

- przechowywać SHA-256/HMAC tokenu,
- dodać revoked_at, revoked_by, revoke_reason,
- atomowe UPDATE ... WHERE used_at IS NULL AND revoked_at IS NULL,
- wymagać envelope status sent/in_progress,
- revoke all przy withdraw/regenerate/resend,
- partial unique dla aktywnego linku per envelope/signer role,
- logować access attempt bez zapisywania tokenu.

Test krytyczny:

- 20 równoległych submit tym samym tokenem; dokładnie jeden 2xx.
- po withdraw, regenerate, complete i expiry każdy wcześniejszy token zwraca 404,
- błąd walidacji nie konsumuje linku, ale drugi równoległy request nie może wejść w finalize.

### P0.3. QES działa fail-open

Dowody:

- finalize_signed_pdf uruchamia twarde odrzucenie non-QES tylko, gdy DSS_VALIDATION_URL istnieje.
- bez DSS niepusty wynik może zostać zapisany jako completed.
- publiczny UI komunikuje, że wymagany jest QES, ale po HTTP 200 pokazuje Dokument przyjęty.
- fully signed opiera się na liczbie approval, nie na zestawie oczekiwanych ról/tożsamości.
- wynik DSS może oznaczyć is_qes na podstawie poziomu podpisu bez wymuszenia pozytywnego indication.

Skutek:

- system może oznaczyć dokument jako completed bez wymaganego rodzaju podpisu,
- dwie sygnatury nie muszą należeć do dwóch różnych oczekiwanych stron,
- UI tworzy fałszywe zapewnienie prawne.

Naprawa:

- SIGNING_ENABLED wymaga działającego walidatora dla policy QES,
- brak DSS = capability unavailable, nie fallback accept,
- expected signers zapisani przed send,
- walidacja tożsamości, roli, certyfikatu, policy i hash dokumentu,
- fully_executed wyliczane z kompletności wymaganych signer roles,
- health/deployment gate dla wymaganego validatora.

### P0.4. Podpis nie zawsze dotyczy niezmiennej wersji

Dowody:

- in-house prepare_send może użyć latest ContractDocument albo fallback draft_content_html.
- signature row nie zawsze ma obowiązkowe snapshot_document_id/content_hash.
- backend nie porównuje podpisanego PDF z bazowym artefaktem ani dozwoloną incremental revision.
- framework agreement i amendment zapisują target, ale worker może później odczytać już podmieniony live file.
- PDF może zostać wyrenderowany ponownie z mutowalnego HTML.
- ContractDocument można update/delete.
- framework file może zostać podmieniony.
- B2B register przechowuje mutable payload, a ponowne pobranie renderuje z aktualnego kodu/template.

Skutek:

- nie można kryptograficznie wykazać, że podpisano dokładnie treść wysłaną do osoby,
- późniejsza zmiana template/renderera może zmienić pobrany dokument,
- korekta nadpisuje historię zamiast tworzyć nową wersję.

Naprawa:

- immutable AgreementVersion,
- bytes w object storage,
- SHA-256,
- canonical payload,
- template_id i template_version,
- renderer_name/version,
- supersedes_version_id,
- envelope wymaga agreement_version_id i content_hash,
- wysłana wersja nie ma update/delete.

### P0.5. Hard delete może usunąć dowody prawne i finansowe

Dowody:

- aktywny Contract ma przycisk Usuń.
- backend DELETE fizycznie usuwa Contract.
- relacje documents, amendments, equipment, client orders, invoices i signatures używają cascade lub delete-orphan.
- amendments/framework files również mają destrukcyjne delete/replace.
- błąd po usunięciu pliku przed DB commit może pozostawić row bez pliku.

Skutek:

- utrata dokumentów, aneksów, podpisów i historii,
- brak audytowalności sporów,
- brak legal hold/retention,
- możliwy broken reference w storage/DB.

Naprawa:

- natychmiast zabronić delete po pierwszym send/activation/financial event,
- draft delete zastąpić void z reason,
- append-only evidence,
- retention/legal_hold,
- storage state staged/final/void,
- garbage collection tylko dla niepowiązanych staged blobs po TTL.

### P0.6. Resource scope jest niespójny dla dokumentów klienta i zamówień

Stan current origin/main:

- framework contracts używają już resolve_client_access i can_view_legal_documents — to należy zachować,
- client contract amendments list/download nadal używają CurrentUser i tylko sprawdzają client/framework IDs,
- ClientOrder list/get/download używa globalnego TacPlus, nie client resource scope,
- contract/signing reads są globalne dla roli i ujawniają stawki, signer email/phone, błędy i validation report.

Skutek:

- użytkownik może iterować IDs dokumentów/aneksów spoza przypisanego klienta,
- TAC/DL może dostać szerszy dostęp niż wynika z ClientAccess,
- PII i dokumenty prawne nie mają osobnego projection/capability.

Naprawa:

- jedna dependency require_client_capability(client_id, capability),
- capabilities: view_legal, manage_legal, view_orders, manage_orders, view_finance, manage_finance, view_signing_evidence,
- każdy download sprawdza parent resource scope,
- osobne DTO redagujące finance i signer PII,
- test macierzy primary + secondary roles i cross-client IDs.

### P0.7. Przyszłe wcześniejsze zakończenie natychmiast kończy Contract

Current origin/main:

- early_termination ustawia end_date i status ended niezależnie od daty effective.
- dedicated terminate również ustawia ended natychmiast, nawet gdy terminated_at jest w przyszłości.

Skutek:

- konsultant znika z aktywnych przed końcem,
- raport, alerty, klient, DynaReporter i billing dostają przedwczesny stan,
- downstream może rozpocząć offboarding/odebranie dostępów za wcześnie.

Krótkoterminowa naprawa:

- przenieść wąski lokalny patch używający _status_after_end_date_change,
- dopisać analogiczny guard dla dedicated terminate,
- dodać test granicy: future/today/past,
- w dniu zakończenia scheduler materializuje actual end.

Docelowo:

- notice_given_at,
- planned_end_at,
- termination_effective_at,
- actual_end_at,
- status ending/offboarding przed actual end,
- osobna cancellation before start.

### P0.8. Webhook podpisu nie ma monotonicznej state machine

Dowody:

- mapping eventu może przypisać nowy status bez ochrony terminal state.
- późny in_progress może cofnąć completed/rejected.
- completed może zostać zapisane bez skutecznego pobrania signed PDF.
- unknown process jest ignorowany zamiast trafiać do durable inbox/reconciliation.
- pełny payload jest przechowywany bez jawnej polityki PII/retention.

Naprawa:

- durable inbox z provider_event_id unique,
- monotonic transition table,
- ignored_out_of_order jako event audytowy,
- completed_pending_artifact do czasu zapisania i zweryfikowania PDF,
- reconciler provider state,
- issuer/audience/key policy dla webhook JWT,
- wymagane iss, aud, iat, exp i nbf z symetrycznym clock skew; przyszłe iat nie może przejść,
- lookup i unique provider reference muszą używać pary provider + provider_ref,
- encrypted payload lub minimal projection + retention.

### P0.9. Wysyłka podpisu i powiadomień nie jest restart-safe

Dowody:

- Autenti używa BackgroundTasks/asyncio create_task.
- in-house sender wykonuje osobne commity dla draftu i linków.
- Teams notification jest fire-and-forget.
- worker może zginąć między lokalnym commit a provider request.
- status sending nie jest w pełni naprawiany przez sweeper.

Naprawa:

- transactional outbox w tej samej transakcji co command,
- provider idempotency key,
- leased worker,
- heartbeat, retry/backoff, dead-letter,
- reconciliation dla sending/unknown,
- delivery ledger z provider message ID.

### P0.10. HTML umowy i draft nie mają bezpiecznej granicy zaufania

Ryzyka:

- draft_content_html jest zapisywany i zwracany jako treść dokumentu,
- preview/finalize zwraca raw HTML jako same-origin HTMLResponse, więc zapisany script/event handler tworzy stored XSS,
- finalize/print wrapper może włączyć raw HTML i aktywny script,
- template/ops mogą zmieniać render po czasie,
- brak obowiązkowej sanitizacji policy i CSP dla preview,
- Activity może zawierać wrażliwe pola finansowe,
- WeasyPrint renderuje HTML bez deny-all URL fetchera; odwołania http://, file://, CSS url() i @import tworzą ryzyko SSRF/local file read,
- template renderer używa zwykłego Jinja Environment, a nie SandboxedEnvironment lub ścisłej allowlisty AST.

Naprawa:

- canonical structured payload jako źródło dokumentu,
- allowlist sanitizer przed preview,
- preview w sandboxed iframe bez same-origin/scripts,
- renderer server-side,
- deny-all fetcher dla renderera z jawnie dozwolonymi asset IDs/data URI o limicie,
- sandboxed Jinja bez wywołań, atrybutów i Python globals,
- immutable rendered bytes,
- CSP,
- audit redaction i secrets/PII policy.

### P0.11. B2B Generator jest dostępny dla każdego zalogowanego użytkownika

Current origin/main używa CurrentUser dla:

- POST /generate,
- GET contract detail,
- GET contract DOCX,
- standalone render HTML/DOCX,
- list generated contracts,
- download generated DOCX,
- company lookup i UoP check.

Krytyczne problemy:

- generate z przekazanym contract_id pobiera Contract bez sprawdzenia author/client/resource scope,
- następnie mutuje start_date, rate_candidate, currency i cały candidate rate schedule,
- viewer/QC/client może utworzyć lub zmienić draft Contract,
- generated DOCX download nie sprawdza created_by ani client scope,
- lista/re-render ujawnia partner PII, warunki i dane prawne,
- pełny render_payload jest zapisany w JSONB,
- alokacja numeru prawnego jest dostępna dla każdej zalogowanej osoby,
- delete najnowszego wpisu może umożliwić ponowne wykorzystanie numeru.

Skutek:

- horizontal privilege escalation,
- ujawnienie PII i warunków umów,
- nieautoryzowana zmiana stawki/draftu,
- naruszenie ciągłości numeracji dokumentów.

Naprawa containment:

- generate/manage/download wymaga jawnej capability manage_candidate_agreements,
- contract_id zawsze przechodzi require_contract_scope,
- generated row ma owner/client/engagement i read scope,
- download wymaga owner albo scoped legal capability,
- standalone preview nie alokuje numeru,
- numer jest rezerwowany append-only dopiero w final command,
- viewer role ma 403 dla wszystkich writerów i dokumentów prawnych.

### P0.12. Dane finansowe omijają istniejącą politykę finance

backend/app/api/financial_access.py definiuje:

- finance roles = admin i delivery_lead,
- require_financial_access,
- recursive financial field redaction.

Jednocześnie current contracts, exports, invoices, DSO, ClientOrder oraz część analytics używają TacPlus.

Skutek:

- TAC otrzymuje candidate/client rates, margin, revenue, invoice amount i order values,
- endpointy nie stosują tej samej polityki co inne powierzchnie,
- brak client scope dodatkowo poszerza ekspozycję,
- Activity.details może ponownie ujawnić pola po redakcji głównego DTO.

Naprawa:

- jawne finance capabilities,
- require_financial_access przed query/serialization dla legacy endpoints,
- osobne non-financial DTO dla legal/operational users,
- redakcja nested schedules, exports, activities i errors,
- testy dla primary/secondary role oraz cross-client.

### P0.13. Startup toleruje częściowo zastosowany schemat

backend/entrypoint.sh:

- alembic upgrade heads kończy się fallbackiem continue przy błędzie,
- każdy enum/column/data statement łapie wyjątek i kontynuuje,
- Base.metadata.create_all również jest non-fatal,
- safety-net definition document_signatures odpowiada starszej wersji modelu/migracji.

Skutek:

- aplikacja może wystartować na niepełnym lub semantycznie starym schemacie,
- health może być zielony, mimo że rzadziej używany endpoint podpisu/kontraktu zwróci 500,
- DB constrainty mogą różnić się między środowiskami,
- nowy kod może założyć kolumny/unique/check, których produkcja nie ma.

Naprawa:

- migracja preflight sprawdzająca oczekiwany head set i schema fingerprint,
- production fail-closed przed startem aplikacji,
- safety-net ograniczyć do jawnie wersjonowanych, idempotentnych repair steps,
- nie utrzymywać ręcznej starej kopii całej tabeli w entrypoint,
- każdy PR schematu aktualizuje wymagany _COLUMN_STATEMENTS zgodnie z repo contract,
- po migracji uruchomić constraint/invariant verification i dopiero wtedy readiness.

---

## 7. Ustalenia P1 — poważne błędy funkcjonalne

### P1.1. Nie istnieje kanoniczny Engagement

Contractor jest obecnie po prostu kandydatem posiadającym Contract.

Brakuje rekordu wiążącego:

- recruitment_process_id,
- placement_id,
- candidate_id,
- job_id,
- client_id,
- agreement,
- client framework,
- order coverage,
- onboarding,
- start,
- rates,
- timesheets,
- billing,
- success,
- assets,
- offboarding.

To jest główna przyczyna wszystkich rozjazdów.

### P1.2. Pipeline hired tworzy drafty bez kanonicznej decyzji i warunków

backend/app/api/pipeline.py:

- reaguje na legacy enum hired,
- tworzy draft Contract i ClientOrder,
- ustawia start_date na date.today(),
- deduplikuje tylko draft po candidate/client/job,
- nie opiera się o immutable accepted Offer/Placement,
- nie ma globalnego idempotency key.

Skutek:

- start może być wymyślony,
- retry lub alternatywny ingress może stworzyć inny rekord,
- Traffit i signing mogą ominąć ten hook.

### P1.3. ClientOrder ma dwa źródła prawdy

Źródła:

- Contract.client_order_end_date,
- Contract.client_orders 1:N.

Rozjazdy:

- contract alerts czytają legacy scalar,
- DL portal scanner czyta tabelę,
- bulk extension i amendment aktualizują scalar,
- order replace/update nie zawsze synchronizuje scalar,
- ekran może pokazywać inną datę niż alert.

Naprawa:

- ClientOrder jako jedyne źródło,
- backfill i shadow compare,
- nie synchronizować obu bezterminowo,
- usunąć legacy writes przed dropem kolumny.

### P1.4. ClientOrder nie ma wersji i inwariantów

Brakuje:

- jawnego order number/reference,
- immutable document version,
- content hash,
- quantity i unit jako źródła coverage,
- constraint end >= start,
- spójności job/client/contract/framework,
- reguły overlap/continuity,
- optimistic version,
- idempotency key,
- jednego current/effective order per zakres.

Dodatkowo:

- upload zapisuje blob pod order_id=0 przed rekordem,
- replace usuwa stary blob przed commit,
- update może przepiąć job/framework bez pełnej rewalidacji,
- flow B tworzy active bez prawnego gate.

### P1.5. Rate ma kilka sprzecznych reprezentacji

Current state:

- Contract.rate_candidate,
- Contract.rate_client,
- Contract.margin,
- candidate_rate_schedule,
- client_rate_schedule,
- framework_rate_schedule,
- ClientOrder.rate_client,
- target rate i benchmark.

Problemy:

- PATCH może zastąpić cały schedule i usunąć historię,
- brak DB protection przed overlap/same-date ambiguity,
- effective_to nie jest wszędzie respektowane,
- resolver może zwrócić przyszły krok, gdy wszystkie są przyszłe,
- cache aktualizuje się tylko w części writerów,
- analytics/order/contractor czytają różne reprezentacje,
- jedna currency/rate_unit jest współdzielona przez buy i sell side.

Docelowo RateTerm:

- side candidate/client/framework,
- amount Decimal,
- currency,
- unit hourly/daily/monthly,
- billing calendar/hours,
- effective_from/effective_to,
- source agreement/order/amendment,
- approval evidence,
- non-overlap constraint.

### P1.6. Aktualny lifecycle Contract miesza cztery różne pojęcia

ContractStatus ma tylko:

- draft,
- active,
- ending,
- ended.

Nie wiadomo, czy active oznacza:

- dokument gotowy,
- dokument podpisany,
- dokument effective,
- onboarding zakończony,
- zamówienie ważne,
- data startu nadeszła,
- konsultant faktycznie rozpoczął.

Dowód produkcyjny: future-start records są active.

### P1.7. Zakończenie niszczy planowaną datę i historię retencji

Dedicated terminate:

- ustawia terminated_at,
- ustawia ended,
- skraca end_date do terminated_at.

Analytics próbuje potem policzyć early termination przez terminated_at < end_date, ale planowana data została utracona.

Skutek:

- 29/29 zakończeń ma unspecified,
- raport pokazuje 100% retencji,
- nie można wiarygodnie policzyć planned vs early.

### P1.8. Onboarding jest free-form checklistą bez gate

Obecny item ma głównie:

- label,
- notes,
- status pending/done/na,
- assigned_to wskazujący opcjonalnego użytkownika,
- due_date,
- order.

Brakuje:

- template i template revision,
- mandatory,
- dependency,
- owner role i reguł automatycznego assignmentu,
- completed_by/at,
- evidence,
- exception approval,
- SLA,
- generation idempotency,
- audit event.

Item można:

- utworzyć od razu jako done,
- dowolnie edytować,
- fizycznie usunąć.

Produkcja ma active Contract bez checklisty.

### P1.9. Nie istnieje offboarding

Brakuje:

- odebrania dostępów,
- potwierdzenia klienta,
- knowledge transfer,
- final timesheet,
- final billing,
- zwrotu sprzętu i depozytu,
- zamknięcia ryzyk,
- exit reason,
- ponownego udostępnienia kandydata,
- blokady closure przy otwartych obowiązkach.

Terminate i cron zmieniają tylko status.

### P1.10. Equipment nie jest custody ledger

Brakuje:

- globalnego Asset,
- unikalnego serial/asset tag,
- acceptance/handover evidence,
- historycznych assignment events,
- completed_by,
- condition photos/protocol,
- powiązania return due z offboardingiem,
- blokady delete po wydaniu.

Możliwe jest:

- returned bez returned_date,
- delete po wydaniu,
- utrata historii depozytu.

### P1.11. Timesheets nie istnieją

Nie ma modelu dla:

- billing period,
- work days/hours,
- absence/holiday,
- submit,
- reject,
- approve,
- approval evidence,
- correction revision,
- lock po invoice,
- mapping do ClientOrder.

System nie ma kontrolowanej odpowiedzi na pytanie, za ile godzin/dni należy zapłacić i wystawić fakturę.

### P1.12. Invoice nie jest bezpieczną księgą

Problemy:

- amount jest Integer z niejednoznaczną jednostką,
- brak lines, VAT, net/gross,
- brak partial payments,
- brak credit notes,
- brak external/KSeF/ERP IDs,
- status i daty są dowolnie mutowalne,
- fakturę można hard-delete,
- PDF może wskazywać dokument innego Contract,
- brak required approved timesheet/order/rate snapshot,
- numer faktury nie ma twardej unikalności,
- DSO miesza waluty i może uwzględniać cancelled.

### P1.13. B2B Generator może tworzyć osierocone Contract

Frontend w kilku akcjach send/mark/upload ponownie wywołuje generate bez stabilnego contract_id.

Backend przy braku contract_id:

- tworzy nowy draft Contract,
- commituje draft,
- dopiero później prowadzi kolejne operacje.

Skutek:

- jedna sesja użytkownika może utworzyć kilka draftów,
- numery/rejestr i dokumenty nie mają pewnej relacji 1:1,
- cleanup jest niebezpieczny, bo nie wiadomo, który draft jest prawny.

Naprawa:

- wizard session z idempotency key,
- contract/engagement ID tworzony raz,
- wszystkie kolejne commands wymagają aggregate_id + version,
- generate preview bez side-effect,
- finalize dopiero po jawnej komendzie.

### P1.14. Dwa systemy podpisu i offline mają różne semantyki

Rozjazdy:

- in-house dopuszcza draft/active/ending,
- Autenti wymaga active/ending przed send,
- in-house completion przesuwa pipeline, ale nie aktywuje Contract,
- Autenti completion nie uruchamia spójnego startu,
- offline mark sent jest self-attested,
- status sent raz oznacza wygenerowany link, innym razem provider delivery.

Naprawa:

- jeden SignatureEnvelope lifecycle,
- adapter provider,
- delivery_requested/sent/delivered/viewed/signed/validated/completed,
- offline jako provider manual z wymaganym evidence i approval,
- jedna polityka przejść niezależna od providera.

### P1.15. DynaReporter placement jest niezależnym write modelem

DrPlacementDetail:

- nie ma candidate_id,
- nie ma job_id,
- nie ma recruitment_process_id,
- nie ma contract_id/engagement_id,
- może być utworzony ręcznie,
- osobno inkrementuje KPI DL,
- delete nie zapewnia pełnej kompensacji,
- raport może łączyć dr_client i operacyjnego client po tym samym numeric ID bez jawnej mapy tożsamości.

Docelowo:

- DynaReporter jest rebuildable projection z PlacementAccepted/EngagementStarted,
- nie ma ręcznego endpointu create/delete po cutover.

### P1.16. Traffit może ominąć hire/engagement command

Import pipeline:

- ma inną semantykę stage,
- może zaimportować hired,
- nie musi wywołać lokalnego hooka draft Contract/Order,
- nie ma jawnego ownera każdego pola lifecycle.

Potrzebna macierz:

| Pole/fakt | Owner | Kierunek sync | Konflikt |
|---|---|---|---|
| Placement decision | NEXUS | outbound | manual review |
| Agreement/signature | NEXUS | summary outbound | never overwrite |
| ClientOrder | NEXUS | optional outbound | manual review |
| Stage legacy | projection | both during transition | inbox conflict |
| Actual start/end | NEXUS | outbound | legal review |

### P1.17. Raporty nie mają jednej definicji active/placement/margin

Przykłady:

- analytics v1 liczy non-draft z date predicate,
- contract analytics liczy status active,
- niektóre endpointy pomijają ending,
- contractors używa własnych bucketów,
- dashboard używa jeszcze innej definicji,
- placement może znaczyć first hired albo DrPlacementDetail,
- client profile pokazuje active consultant i Placementy 0.

Bez canonical event/projection każda poprawka jednego dashboardu tworzy kolejny rozjazd.

### P1.18. Multi-role i resource scope są stosowane nierówno

Niektóre miejsca używają has_any_role, inne current_user.role.

Skutki:

- secondary DL/TAC/HoR może zobaczyć zbyt mało albo zbyt dużo,
- contractor scope i legal/finance scope nie są identyczne,
- role nie wystarczą do client ownership.

---

## 8. Ustalenia P2/P3 — operacje, UX, wydajność i testy

### P2.1. Alerty używają exact-date windows

contract_alerts:

- szuka dokładnie T-90/T-60/T-30/T-14/T-7,
- po restarcie/downtime może ominąć próg,
- deduplikuje przez title/link Notification,
- po przedłużeniu stary dedupe może blokować nowy alert,
- nie ma leader lock,
- kilka replik może wykonać ten sam job.

Docelowo:

- materializowany Obligation,
- due_at <= now,
- idempotency unique,
- retry/lease,
- JobRun last_success/next_due/backlog.

### P2.2. Auto status transition nie tworzy pełnego audytu

Cron active → ending → ended:

- wykonuje bulk UPDATE,
- nie zapisuje Activity per Contract,
- nie zapisuje reason/source,
- nie uruchamia offboardingu,
- nie zamyka ClientOrder,
- nie sprawdza assets,
- na end_date może pozostawić ending do kolejnego dnia.

### P2.3. Timeline nie jest lifecycle ledger

Produkcja pokazuje Brak wpisów w historii dla active Contract.

Obecny timeline:

- opiera się na wybranych Activity/notes/calls,
- nie obejmuje wszystkich zmian statusu,
- onboarding/equipment CRUD nie zawsze tworzą activity,
- podpisy mają osobny event stream,
- order/framework/invoice mają osobne rekordy.

Docelowo timeline jest projekcją DomainEvent/AuditEntry.

### P2.4. UI pokazuje destrukcyjne akcje i surowe statusy

Problemy:

- Usuń na aktywnym Contract,
- active/draft w surowym angielskim na części ekranów,
- zwykłe button tabs zamiast poprawnego tablist/tab/tabpanel,
- brak gate summary,
- brak odróżnienia dokument prepared/signed/effective,
- brak osobnego planned/started,
- future active wygląda jak rozpoczęty,
- brak czytelnej sekcji exceptions.

### P2.5. UI nie pokazuje spójnego handoff

Na profilu klienta:

- aktywny konsultant,
- brak powiązanej oferty,
- Placementy 0.

Docelowy ekran Engagement powinien zawsze pokazywać breadcrumb:

~~~text
Client → Job → RecruitmentProcess → Offer → Placement → Engagement
~~~

Brak któregokolwiek linku powinien być anomaly, nie pusty tekst.

### P2.6. Analytics tworzy fałszywą precyzję

Miesięczna marża i revenue mają dwa miejsca po przecinku, ale:

- brak approved quantity,
- future-start może być active,
- ending bywa pomijane,
- cached rates mogą być stale,
- partial months nie są uwzględnione,
- waluty mogą być mieszane,
- utilization dzieli active contracts przez wszystkich kandydatów ATS,
- forecast nie ma danych mimo dużej bazy.

UI powinien pokazywać data quality coverage i definicję metryki.

### P2.7. N+1 i nieograniczone odczyty

Ryzyka:

- _to_read per framework liczy amendments osobnym query,
- invoice/client analytics wykonuje per-client/per-row lookups,
- część list serializuje relacje w Pythonie,
- bulk operations nie mają twardych limitów,
- contracts export/list może przenosić wrażliwe finance.

### P2.8. Bulk extend ma błędną semantykę dat

Current logic:

- zwiększa miesiąc,
- ogranicza dzień do 28,
- 31 stycznia może stać się 28 kolejnego miesiąca,
- kolejne przedłużenia kumulują skrócenie,
- nie tworzy prawdziwej wersji order/amendment,
- nie raportuje wszystkich missing/skipped IDs,
- może tworzyć Activity dla nieistniejących IDs.

Naprawa:

- calendar-aware add months,
- jawna end-of-month policy,
- preview per row,
- idempotency,
- typed result success/blocked/not_found/conflict,
- amendment/order command, nie surowy mutation.

### P2.9. Storage nie ma transakcyjnego protokołu

Powtarzający się wzorzec:

- zapisz nowy blob,
- zmień DB,
- usuń stary blob przed lub niezależnie od commit.

Możliwe stany:

- orphan blob,
- row wskazujący missing file,
- utrata starego prawnego dokumentu po rollback.

Docelowo:

- staged blob,
- checksum,
- DB record,
- finalize after commit przez outbox,
- immutable version,
- GC staged/orphan po TTL,
- nigdy delete effective legal artifact.

### P2.10. Observability nie mierzy outcome

Brak metryk:

- active_without_executed_agreement,
- fully_executed_without_engagement,
- active_without_order_coverage,
- future_start_marked_active,
- signature_sending_age,
- completed_without_signed_artifact,
- revoked_link_attempt,
- hired_without_placement,
- placement_without_engagement,
- engagement_without_job,
- rate_term_overlap,
- cache_rate_drift,
- overdue_onboarding,
- ended_with_open_assets,
- ended_without_offboarding,
- invoice_without_timesheet,
- outbox oldest age.

### P2.11. CI nie chroni pełnego krytycznego flow

Repo zawiera testy:

- contracts,
- contracts draft,
- amendments,
- onboarding,
- invoices,
- contract alerts,
- Autenti,
- rate schedules.

Selective CI uruchamia część Autenti, schedules, amendments, expiring/export, ale nie obejmuje wszystkich:

- core contracts,
- contract draft,
- onboarding,
- invoices,
- in-house public signing,
- asset lifecycle,
- end-to-end hired → signed → start → billing → offboarding.

Skutek:

- test istniejący lokalnie nie musi być required gate,
- szczególnie istotny test future early termination jest poza origin i nie chroni CI.

Dodatkowo część test_contract_amendments:

- pobiera pierwszy istniejący Contract,
- wykonuje return, jeśli fixture go nie utworzyła,
- podstawowy conftest seeduje głównie admina, nie Contract,
- test może więc przejść jako no-op bez wykonania asercji biznesowej.

Wyłączony z required CI test_contracts_expansion utrwala obecnie błędne immediate-ended dla future early termination. Przed włączeniem należy naprawić oczekiwanie, a nie tylko dodać plik do listy.

### P2.12. Brak optimistic concurrency

Contract, order, amendment, onboarding i invoice są edytowane bez expected_version.

Skutek:

- dwie zakładki nadpisują się,
- operator może zatwierdzić starą wersję,
- full schedule replacement może usunąć zmiany innej osoby,
- webhook i ręczna akcja mogą ścigać się.

### P2.13. Błąd API jest prezentowany jako pusty zbiór lub zero

Na listach Contract/Contractor, w dokumentach, onboardingu, fakturach, profilach klienta i analytics część zapytań nie ma jawnego isError.

Skutek:

- 403 może wyglądać jak brak danych,
- 500 może wyglądać jak 0 PLN,
- operator nie wie, czy ponowić żądanie,
- dashboard może budować fałszywe wnioski biznesowe.

Naprawa:

- wspólny AsyncState,
- osobne stany 403, 404, 409, 422, 503 i network error,
- zero/pusty stan tylko po skutecznym 2xx,
- telemetry error boundary z query key i correlation ID bez PII.

### P2.14. Cache frontendu nie ma jednego kontraktu invalidacji

Lista używa kluczy contracts-v2, a część mutacji unieważnia contracts. Aneksy, termination, client profile, operations view i analytics mają dalsze osobne klucze.

Skutek:

- poprawna mutacja może pozostawić stary status,
- lista, detail i profil klienta pokazują różne liczby,
- użytkownik ponawia operację, bo nie widzi skutku.

Naprawa:

- centralny contractKeys,
- invalidateEngagementGraph dla contract/engagement/client/analytics/expiring,
- mutation response zawiera nową version,
- testy React Query dla każdej komendy domenowej.

### P2.15. Bulk selection może obejmować niewidoczne rekordy

Selected IDs mogą pozostać po zmianie strony lub filtrów.

Skutek:

- użytkownik kończy albo przedłuża rekord, którego nie widzi,
- nie zna wersji rekordu ani zakresu zaznaczenia.

Naprawa:

- selection związany ze snapshotem filtrów,
- jawna liczba elementów poza widokiem albo automatyczne wyczyszczenie,
- expected_version per ID,
- wynik per rekord: success, blocked, forbidden, not_found, conflict.

### P2.16. Seed onboardingu nie jest atomowy

Frontend wykonuje serię niezależnych create. Podwójne kliknięcie lub błąd w połowie może stworzyć duplikaty i częściowy plan.

Naprawa:

- POST /engagements/{id}/onboarding/seed,
- template_version i unique plan/template_item,
- jedna transakcja lub idempotentny upsert,
- jeden wspólny pending lock w UI.

### P2.17. Upload i replacement plików nie mają pełnego protokołu bezpieczeństwa

Problemy:

- limit bywa sprawdzany dopiero po zapisaniu całego streamu,
- claimed MIME/extension nie dowodzą formatu,
- brak quarantine/AV,
- stary blob bywa usuwany przed commit nowego powiązania,
- download nie ma jednolitego audytu i Cache-Control private, no-store.

Naprawa:

- bounded streaming do staged storage,
- magic-byte detection i ścisła allowlista,
- SHA-256, quarantine i scan state,
- finalize oraz cleanup przez outbox po commit,
- prawny artefakt jest immutable i superseded, nigdy replace-in-place.

### P2.18. Accessibility, mobile i tokeny design systemu są niespójne

Audyt frontendu potwierdził:

- tabs bez tablist/tab/aria-selected i pełnej klawiatury,
- custom dialogs bez focus trap i Escape,
- icon buttons bez nazw dostępnościowych,
- ucięcie tabeli umów na produkcji przy szerokości 390 px,
- hardcoded kolory obok semantic tokens,
- część surowych angielskich statusów.

Naprawa:

- komponenty ds/ui zgodne z repozytoryjnym design systemem,
- responsive card/table projection,
- testy axe i keyboard flow,
- screenshot desktop/mobile w produkcji po wdrożeniu,
- żadnych nowych hardcoded kolorów.

### P2.19. Activity feed może ponownie ujawniać finance i signer PII

Contract update i amendment zapisują surowe stare/nowe wartości, a signing zdarzenia mogą zawierać signer email. Ogólny feed jest szerszy niż finansowa i prawna polityka odczytu.

Naprawa:

- restricted AuditEntry jako pełny ledger,
- ogólny feed tylko z allowlistą typów i bez wartości finansowych/PII,
- redakcja zależna od capabilities,
- test regresyjny, że ukryte pola nie wracają przez details, error ani export.

### P2.20. Eksport CSV/XLSX wymaga ochrony przed formula injection

User-controlled wartości zaczynające się od =, +, -, @, tab lub CR mogą zostać wykonane przez arkusz po otwarciu eksportu.

Naprawa:

- neutralizacja niebezpiecznego prefiksu,
- wspólny safe_cell helper,
- testy round-trip dla Contract i invoice export,
- nigdy nie maskować problemu wyłącznie po stronie UI.

### P3.1. Nazewnictwo miesza dokument i współpracę

Contract raz znaczy:

- umowę z kandydatem,
- współpracę,
- placement,
- wiersz raportowy,
- kontener faktur,
- kontener ClientOrder.

Docelowo nazwy:

- Engagement — współpraca,
- LegalAgreement — relacja prawna,
- AgreementVersion — artefakt,
- ClientOrder — zamówienie,
- BillingDocument — dokument finansowy.

### P3.2. Legacy do usunięcia po parity

- Contract.client_order_end_date,
- cache rate_candidate/rate_client/margin jako source of truth,
- generic status writes,
- mutable draft_content_html jako podpisywany artefakt,
- standalone mutable B2BGeneratedContract,
- ręczny DrPlacementDetail writer,
- hard delete prawnych/finansowych rekordów,
- title/link dedupe alerts,
- fire-and-forget external effects.

---

## 9. Najważniejsze scenariusze awarii

### Scenariusz A — active bez umowy

1. Operator tworzy Contract lub używa flow B ClientOrder.
2. Status staje się active.
3. Nie ma ContractDocument ani SignatureEnvelope.
4. Analytics nalicza revenue/margin.
5. Klient widzi aktywnego konsultanta.
6. W sporze nie istnieje dowód wykonanej wersji umowy.

Stan jest już potwierdzony na produkcyjnym Contract #15.

### Scenariusz B — wycofany link nadal podpisuje

1. Operator wysyła link A.
2. Wycofuje envelope albo generuje link B.
3. Link A pozostaje nieużyty i niewycofany w SignatureLink.
4. Odbiorca używa A.
5. Public submit nie sprawdza envelope withdrawn.
6. Powstaje signed artifact dla procesu, który operator uznał za anulowany.

### Scenariusz C — podwójne użycie jednego linku

1. Dwa requesty równocześnie odczytują used_at = NULL.
2. Oba generują i walidują plik.
3. Oba zapisują completion/effects.
4. Pipeline hook i notifications mogą uruchomić się dwa razy.

### Scenariusz D — treść zmieniona po wysłaniu

1. prepare_send fallbackuje do draft_content_html.
2. Powstaje link bez obowiązkowego immutable document version.
3. Operator edytuje draft.
4. Odbiorca pobiera/renderuje później inną treść.
5. Evidence nie dowodzi pierwotnie wysłanej wersji.

### Scenariusz E — restart podczas wysyłki Autenti

1. DB zapisuje signature status sending.
2. Zewnętrzne wywołanie rozpoczyna się.
3. Proces/replika restartuje się.
4. Provider mógł utworzyć proces, ale local provider ID nie został zapisany.
5. Sweeper nie naprawia kompletnego stanu sending/unknown.
6. Retry może utworzyć duplikat albo rekord pozostaje na zawsze stuck.

### Scenariusz F — future termination kończy współpracę dziś

1. Operator wprowadza aneks ze skutkiem za 30 dni.
2. API zapisuje status ended od razu.
3. Konsultant wypada z active.
4. Raport i alerty uznają współpracę za zakończoną.
5. ClientOrder/sprzęt/offboarding nie są spójnie aktualizowane.

### Scenariusz G — planowana data końca zostaje utracona

1. Contract miał planowany koniec 2026-12-31.
2. Współpraca kończy się 2026-09-30.
3. terminate nadpisuje end_date na 2026-09-30.
4. Analytics porównuje terminated_at z nadpisanym end_date.
5. Zakończenie nie jest rozpoznane jako przedwczesne.

### Scenariusz H — faktura bez podstawy

1. Operator ręcznie wpisuje amount.
2. Nie istnieje approved timesheet.
3. Rate cache może nie zgadzać się z effective schedule/order.
4. Invoice otrzymuje issued/paid ręczną zmianą statusu.
5. Nie można odtworzyć quantity × rate × tax.

### Scenariusz I — zakończenie bez zwrotu aktywów

1. Cron ustawia ended.
2. Nie powstaje OffboardingPlan.
3. Equipment pozostaje assigned albo rekord jest usuwany.
4. Nie ma overdue obligation i eskalacji.
5. Firma nie ma pełnego rejestru custody.

### Scenariusz J — dwa placementy dla jednej współpracy

1. Pipeline zapisuje hired.
2. DynaReporter operator tworzy DrPlacementDetail.
3. Moduł 4 tworzy Placement.
4. Contract istnieje bez job.
5. Profil klienta pokazuje active consultant i Placementy 0, zależnie od źródła.

### Scenariusz K — dowolny viewer mutuje cudzy draft B2B

1. Zalogowany viewer zna lub odgaduje contract_id.
2. Wywołuje B2B /generate z tym contract_id.
3. Backend sprawdza tylko, czy typ to B2B.
4. Nadpisuje start date, candidate rate i harmonogram.
5. Viewer pobiera/re-renderuje dokument.

### Scenariusz L — produkcja startuje na częściowym schemacie

1. Alembic upgrade heads zgłasza błąd.
2. entrypoint loguje continuing.
3. część DDL safety-net również zgłasza błędy, ale pętla kontynuuje.
4. health database SELECT 1 jest healthy.
5. pierwszy request do rzadkiego flow podpisu trafia na brak constraintu/kolumny.

---

## 10. Docelowy lifecycle

### 10.1. LegalAgreement

Proponowane stany umowy:

~~~text
draft
→ prepared
→ internal_review
→ approved
→ dispatch_pending
→ sent
→ partially_signed
→ fully_executed
→ effective
→ superseded / terminated / void
~~~

Semantyka:

- draft — edytowalny payload roboczy, bez numeru prawnego.
- prepared — wyrenderowana immutable AgreementVersion.
- internal_review — wymaga akceptacji prawnej/finansowej.
- approved — wersja zatwierdzona do wysyłki.
- dispatch_pending — outbox czeka na providera.
- sent — provider przyjął i istnieje dowód dispatch.
- partially_signed — część ExpectedSigner spełniona.
- fully_executed — wszystkie wymagane role podpisane i zwalidowane.
- effective — nadeszła effective date i nie ma warunku zawieszającego.
- superseded — zastąpiona nową wersją/umową.
- terminated — zakończona zgodnie z termination event.
- void — formalnie unieważniona z powodem; nigdy fizycznie skasowana.

### 10.2. SignatureEnvelope

~~~text
draft
→ queued
→ dispatching
→ sent
→ delivered
→ viewed
→ partially_signed
→ validation_pending
→ completed
~~~

Stany terminalne:

- declined,
- expired,
- withdrawn,
- failed,
- superseded.

Terminal state jest monotoniczny. Spóźniony webhook nie może go cofnąć.

### 10.3. Engagement

~~~text
planned
→ documents_pending
→ signature_pending
→ fully_executed
→ onboarding
→ ready_to_start
→ active
→ renewal_pending / on_hold / ending
→ offboarding
→ ended
~~~

Stany terminalne alternatywne:

- cancelled — anulowane przed rozpoczęciem,
- failed_start — warunki zawarte, ale osoba nie rozpoczęła,
- void — rekord utworzony błędnie, zachowany w audycie.

### 10.4. Cztery różne daty

Nie wolno już używać jednego end_date/start_date do kilku znaczeń.

Engagement:

- planned_start_at,
- confirmed_start_at,
- actual_started_at,
- planned_end_at,
- notice_given_at,
- termination_effective_at,
- actual_ended_at.

LegalAgreement:

- executed_at,
- effective_from,
- effective_to.

ClientOrder:

- coverage_from,
- coverage_to.

### 10.5. Start gate

Engagement może przejść do ready_to_start, jeżeli:

1. istnieje Placement i accepted Offer snapshot,
2. candidate/client/job są spójne,
3. wymagane LegalAgreement są fully_executed,
4. nadeszła lub jest znana effective date,
5. istnieje ClientOrder coverage albo zatwierdzony wyjątek,
6. istnieją kompletne candidate/client RateTerm,
7. mandatory pre-start onboarding jest completed albo waived przez uprawnioną rolę,
8. wymagany sprzęt/access jest ready,
9. nie ma blocking compliance risk.

Przejście ready_to_start → active wymaga:

- actual start confirmation,
- daty nie wcześniejszej niż allowed start,
- expected_version,
- idempotency key,
- domain event EngagementStarted.

### 10.6. End gate

Komenda ScheduleTermination:

- nie ustawia od razu ended,
- zapisuje notice i effective date,
- tworzy OffboardingPlan i Obligations,
- ustawia ending albo renewal_pending zależnie od scenariusza.

Komenda ConfirmEngagementEnded:

- zapisuje actual_ended_at,
- wymaga zamknięcia obowiązków blocking lub jawnych waivers,
- tworzy immutable reason/outcome snapshot,
- publikuje EngagementEnded.

---

## 11. Docelowe encje

### 11.1. Engagement

Minimalne pola:

- id UUID,
- placement_id FK unique dla live record,
- recruitment_process_id FK,
- candidate_id FK RESTRICT,
- job_id FK RESTRICT,
- client_id FK RESTRICT,
- state,
- planned_start_at,
- confirmed_start_at,
- actual_started_at,
- planned_end_at,
- notice_given_at,
- termination_effective_at,
- actual_ended_at,
- termination_reason_code,
- termination_notes,
- outcome_code,
- owner_user_id,
- delivery_lead_user_id,
- success_manager_user_id,
- version,
- created_at/by,
- updated_at/by,
- voided_at/by/reason.

DB:

- spójność process/candidate/job/client w command service,
- partial unique na placement_id WHERE voided_at IS NULL,
- version NOT NULL,
- CHECK actual_ended_at >= actual_started_at, jeżeli obie istnieją.

### 11.2. LegalAgreement

- id UUID,
- owner_scope candidate_engagement/client_framework/standalone_legacy,
- client_id,
- engagement_id nullable,
- legacy_contract_id nullable wyłącznie w okresie migracji,
- agreement_type candidate_b2b/uop/zlecenie/client_framework/order_addendum/other,
- party configuration,
- state,
- current_version_id,
- effective_from/to,
- executed_at,
- superseded_by_id,
- termination metadata,
- version.

Nie przechowuje mutowalnej treści dokumentu.

Owner invariant:

- candidate agreement po cutover wymaga engagement_id,
- client framework/MSA jest własnością klienta, nie pojedynczego Engagement,
- standalone_legacy musi mieć provenance i trafić do reconciliacji,
- check constraint wymusza dozwoloną kombinację owner_scope oraz FK,
- Engagement/ClientOrder może wskazywać właściwy client framework obowiązujący w danym okresie, ale MSA nie jest childem jednego Engagement.

### 11.3. AgreementVersion

- id UUID,
- agreement_id,
- revision integer,
- canonical_payload JSONB,
- template_id,
- template_revision,
- renderer_name,
- renderer_version,
- storage_key,
- content_type,
- byte_size,
- sha256,
- prepared_at/by,
- approved_at/by,
- supersedes_version_id,
- voided_at/by/reason.

Inwariant:

- po prepared bytes/payload/hash/template/renderer są immutable.

### 11.4. ExpectedSigner

- id,
- envelope_id,
- role candidate/company_representative/client_representative/witness,
- subject_ref optional,
- expected_name,
- expected_email,
- expected_phone,
- required_signature_policy QES/AES/SES/manual_approved,
- signing_order,
- required boolean.

### 11.5. SignatureEnvelope

- id UUID,
- agreement_version_id,
- provider,
- provider_process_id,
- idempotency_key,
- state,
- sent/delivered/viewed/completed timestamps,
- expires_at,
- withdrawn_at/by/reason,
- last_error_code,
- retry_count,
- version.

### 11.6. SignatureEvidence i SignatureEvent

Evidence:

- expected_signer_id,
- signer identity snapshot,
- certificate fingerprint,
- signature policy,
- validation provider/version,
- validation result,
- signed artifact hash,
- signed_at,
- evidence storage key.

Event:

- provider_event_id unique,
- envelope_id,
- received_at,
- event_type,
- normalized_state,
- payload projection/encrypted reference,
- processed_at,
- disposition applied/duplicate/out_of_order/unknown.

### 11.7. ClientFrameworkAgreement

Jest client-scoped wariantem LegalAgreement z agreement_type client_framework. Może obejmować wiele Engagementów i nie może wymagać engagement_id.

Wymagane:

- client_id,
- legal entities/parties,
- scope,
- effective period,
- current executed version,
- terms revision,
- amendment application history,
- jawne applicability/linki z ClientOrder lub Engagement, jeśli zakres nie dotyczy całego klienta.

### 11.8. ClientOrder

- id UUID,
- engagement_id,
- client_id,
- job_id,
- framework_agreement_id,
- order_number,
- state draft/approved/effective/exhausted/expired/cancelled/superseded,
- coverage_from/to,
- quantity,
- quantity_unit hour/day/month/fixed,
- total_value optional,
- currency,
- current_version_id,
- version.

### 11.9. ClientOrderVersion

- order_id,
- revision,
- immutable document storage/hash,
- canonical terms,
- source/provider reference,
- approved_at/by,
- supersedes_version_id.

### 11.10. RateTerm

- id UUID,
- engagement_id,
- side candidate/client/framework,
- amount NUMERIC,
- currency ISO 4217,
- unit,
- billing_hours_per_month/billing_calendar,
- effective_from,
- effective_to,
- source_type/agreement_version_id/order_version_id,
- approved_at/by,
- superseded_by_id,
- created_at/by.

DB:

- no overlapping effective range per engagement + side,
- amount >= 0,
- effective_to >= effective_from,
- required currency/unit.

### 11.11. OnboardingTemplate i OnboardingPlan

Template:

- id, name, client/contract type scope,
- revision,
- active_from/to,
- immutable item definitions.

Plan:

- engagement_id,
- template_revision_id,
- generated_at/by,
- state,
- due_at,
- completed_at,
- exception summary.

### 11.12. ChecklistItemInstance

- plan_id,
- key,
- title/description snapshot,
- phase pre_start/day_1/week_1,
- mandatory,
- blocking,
- assigned_role/user,
- dependency IDs,
- due_at,
- state pending/in_progress/completed/waived/blocked,
- completed_at/by,
- waiver_reason/approved_by,
- evidence references,
- version.

### 11.13. Asset i AssetAssignment

Asset:

- asset_tag unique,
- serial_number normalized unique where not null,
- owner company/client,
- type/model,
- state,
- deposit terms.

Assignment:

- engagement_id,
- asset_id,
- assigned_at/by,
- accepted_at/by/evidence,
- return_due_at,
- returned_at/by/evidence,
- condition_out/in,
- deposit settlement,
- append-only custody events.

### 11.14. SuccessCheckIn, AssignmentRisk i SuccessAction

SuccessCheckIn:

- engagement_id,
- audience consultant/client/internal,
- occurred_at,
- health score,
- structured answers,
- notes with PII policy,
- created_by.

Risk:

- category delivery/commercial/attendance/satisfaction/renewal/compliance,
- severity,
- source,
- opened_at,
- owner,
- due_at,
- state,
- resolved_at/outcome.

Action:

- risk_id,
- owner,
- due_at,
- state,
- evidence/result.

### 11.15. RenewalDecision

- engagement_id,
- decision window,
- proposed terms version,
- client intent,
- consultant intent,
- decision renew/end/unknown,
- approved_at/by,
- resulting order/agreement version IDs.

### 11.16. TimesheetPeriod

- engagement_id,
- period_start/end,
- timezone,
- state open/submitted/rejected/approved/locked/invoiced,
- revision,
- submitted_at/by,
- approved_at/by,
- approval evidence,
- client_order_id/version,
- total billable/nonbillable quantity.

Partial unique:

- one current non-void revision per engagement/period.

### 11.17. TimeEntry

- timesheet_period_id,
- work_date,
- quantity Decimal,
- unit,
- category work/holiday/sick/other,
- project/order allocation,
- description,
- source manual/import,
- created/updated audit.

### 11.18. BillingDocument

- id UUID,
- engagement_id,
- legal seller/buyer snapshots,
- document_type invoice/credit_note/debit_note,
- number,
- currency,
- issue_date,
- service_period,
- due_date,
- state draft/approved/issued/partially_paid/paid/overdue/cancelled/credited,
- net_amount,
- tax_amount,
- gross_amount,
- external_system/id,
- immutable issued artifact hash,
- version.

### 11.19. BillingLine

- billing_document_id,
- timesheet_period_id/revision,
- client_order_version_id,
- rate_term_id,
- description,
- quantity,
- unit,
- unit_rate,
- currency,
- tax_rate,
- net/tax/gross,
- rounding policy snapshot.

### 11.20. PaymentEvent i CreditNote

PaymentEvent:

- billing_document_id,
- external payment reference unique,
- amount/currency,
- occurred_at,
- type payment/refund/reversal,
- source/import metadata.

Status płatności jest projekcją ledgeru, nie dowolnym polem PATCH.

### 11.21. DomainEvent i AuditEntry

DomainEvent:

- aggregate_type/id,
- aggregate_version,
- event_type,
- occurred_at,
- actor,
- correlation_id,
- causation_id,
- payload schema/version.

AuditEntry:

- kto,
- kiedy,
- command,
- before/after redacted,
- reason,
- source IP/device where appropriate,
- resource scope.

### 11.22. OutboxMessage i InboxMessage

Outbox:

- domain_event_id,
- destination,
- idempotency_key unique,
- payload,
- available_at,
- lease owner/until,
- attempts,
- delivered_at,
- dead_letter_at,
- last_error.

Inbox:

- provider/source,
- provider_event_id unique,
- received_at,
- payload reference,
- processed_at,
- disposition.

### 11.23. Obligation i JobRun

Obligation:

- engagement/resource,
- type,
- due_at,
- owner/capability,
- state pending/completed/waived/cancelled,
- unique business key,
- escalation policy.

JobRun:

- job name,
- scheduled_for,
- started/finished,
- lease,
- status,
- scanned/created/completed/failed counts,
- last cursor,
- error summary.

---

## 12. Nienaruszalne inwarianty

1. Jeden Placement ma najwyżej jedno nieanulowane Engagement.
2. Engagement zawsze wskazuje Placement i RecruitmentProcess po cutover.
3. Candidate/job/client muszą zgadzać się z Placement.
4. Contract/Agreement/Order nie mogą wskazywać innego klienta niż Engagement.
5. Generic CRUD nie może zmieniać lifecycle state.
6. Każda komenda wymaga expected_version.
7. Każda mutating komenda ma idempotency_key.
8. Każde udane przejście tworzy DomainEvent i AuditEntry.
9. Każdy efekt zewnętrzny wychodzi przez Outbox.
10. Każdy webhook przechodzi przez deduplikowany Inbox.
11. Wysłana AgreementVersion jest immutable.
12. AgreementVersion ma SHA-256 rzeczywistych bytes.
13. SignatureEnvelope zawsze wskazuje dokładną AgreementVersion.
14. Podpisany artifact hash musi odpowiadać oczekiwanej wersji lub jawnie udokumentowanemu provider envelope.
15. QES działa fail-closed.
16. Fully executed wymaga wszystkich required ExpectedSigner.
17. Dwie wymagane role nie mogą zostać spełnione tym samym evidence, jeśli policy tego zabrania.
18. Terminalnego signature state nie można cofnąć.
19. Public token jest hashowny, revocable, expiring i atomowo single-use.
20. Withdraw/regenerate unieważnia wszystkie stare aktywne linki.
21. Prawnych i finansowych records nie wolno hard-delete.
22. Legal hold blokuje garbage collection.
23. ClientOrder ma immutable wersje.
24. Order coverage musi pokrywać aktywną usługę lub istnieje zatwierdzony wyjątek.
25. Order/client/job/framework muszą być zgodne z Engagement.
26. RateTerm tego samego side nie może się nakładać.
27. RateTerm zawsze ma currency, unit i effective range.
28. Nie wolno sumować różnych walut bez jawnego FX source/date.
29. Future RateTerm nie jest current przed effective_from.
30. effective_to jest respektowane.
31. Engagement nie jest active przed actual start confirmation.
32. Future planned start nie jest active.
33. Start wymaga fully executed agreement.
34. Start wymaga order coverage albo approved exception.
35. Start wymaga mandatory onboarding albo approved waiver.
36. planned_end_at nigdy nie jest nadpisywane actual end.
37. Future termination nie ustawia ended przed effective date.
38. Ending tworzy OffboardingPlan i Obligations dokładnie raz.
39. Ended wymaga actual_ended_at.
40. Closure wymaga zamknięcia blocking offboarding albo jawnych waivers.
41. Asset custody history jest append-only.
42. Returned wymaga returned_at, actor i evidence policy.
43. Issued BillingDocument jest immutable.
44. BillingLine snapshotuje quantity/rate/currency/tax.
45. Invoice issue wymaga approved source quantity albo approved exception.
46. Payment status wynika z PaymentEvent.
47. Credit note nie nadpisuje oryginalnej faktury.
48. DynaReporter jest projekcją, nie writerem placementu.
49. Traffit ma jawnego ownera per pole/fakt.
50. Automatyczna naprawa prawnych/finansowych konfliktów jest zabroniona bez review.

---

## 13. Docelowe komendy i API

### 13.1. Wspólny command envelope

Każda komenda:

~~~json
{
  "idempotency_key": "uuid",
  "expected_version": 7,
  "reason": "business reason where required",
  "payload": {}
}
~~~

Wspólna odpowiedź:

~~~json
{
  "aggregate_id": "uuid",
  "version": 8,
  "state": "ready_to_start",
  "event_id": "uuid",
  "requirements": [],
  "warnings": []
}
~~~

### 13.2. Handoff z placementu

~~~text
POST /api/placements/{placement_id}/engagement
~~~

Zachowanie:

- get-or-create po placement_id,
- snapshot accepted commercial terms,
- tworzy Engagement planned,
- generuje wymagane agreements/orders/onboarding plan jako draft tasks,
- retry zwraca ten sam aggregate.

### 13.3. Przygotowanie umowy

~~~text
POST /api/engagements/{id}/agreements
POST /api/agreements/{id}/versions/prepare
POST /api/agreement-versions/{id}/approve
~~~

Prepare:

- renderuje raz,
- zapisuje bytes/hash/payload/version,
- nie alokuje ponownie numeru po void,
- zwraca immutable version.

### 13.4. Wysłanie do podpisu

~~~text
POST /api/agreement-versions/{id}/signature-envelopes
POST /api/signature-envelopes/{id}/withdraw
POST /api/signature-envelopes/{id}/resend
~~~

Create:

- wymaga approved version,
- zapisuje ExpectedSigner,
- enqueue outbox,
- nie wykonuje provider call w request.

### 13.5. Start readiness

~~~text
GET /api/engagements/{id}/readiness
POST /api/engagements/{id}/confirm-start
~~~

Readiness zwraca:

- blocking requirements,
- warnings,
- evidence links,
- data quality anomalies,
- can_start boolean,
- evaluated_at i policy_version.

### 13.6. ClientOrder

~~~text
POST /api/engagements/{id}/orders
POST /api/orders/{id}/versions
POST /api/order-versions/{id}/approve
POST /api/orders/{id}/cancel
~~~

Replace nie istnieje jako destructive file replacement. Powstaje nowa version.

### 13.7. Rates

~~~text
GET /api/engagements/{id}/rates?at=...
POST /api/engagements/{id}/rate-terms
POST /api/rate-terms/{id}/supersede
~~~

Create wykonuje preflight overlap i DB transaction.

### 13.8. Onboarding i offboarding

~~~text
POST /api/engagements/{id}/onboarding/generate
POST /api/checklist-items/{id}/complete
POST /api/checklist-items/{id}/waive
POST /api/engagements/{id}/termination/schedule
POST /api/engagements/{id}/offboarding/generate
POST /api/engagements/{id}/end
~~~

Complete:

- wymaga evidence zgodnie z template,
- zapisuje actor/time,
- jest idempotentne.

Waive:

- wymaga capability i reason,
- nie udaje completed.

### 13.9. Timesheet i billing

~~~text
POST /api/engagements/{id}/timesheets
POST /api/timesheets/{id}/submit
POST /api/timesheets/{id}/approve
POST /api/timesheets/{id}/reject
POST /api/timesheets/{id}/revise
POST /api/timesheets/{id}/billing-documents
POST /api/billing-documents/{id}/approve
POST /api/billing-documents/{id}/issue
POST /api/billing-documents/{id}/payments
~~~

### 13.10. Bulk commands

Bulk endpoint przyjmuje maksymalnie ustalony limit i zwraca wynik per item:

~~~json
{
  "results": [
    {
      "id": "uuid",
      "status": "succeeded|blocked|conflict|not_found|forbidden",
      "version": 4,
      "requirements": [],
      "error_code": null
    }
  ]
}
~~~

Nie ma silent skip. Nie ma Activity dla nieistniejącego ID.

### 13.11. Repair commands

Repair:

- osobny admin namespace,
- dry_run default true,
- anomaly class required,
- before/after preview,
- legal/finance approval where required,
- idempotency,
- full audit.

---

## 14. Migracja i reconciliacja danych

### 14.1. Zasada bezpieczeństwa

Nie wolno automatycznie uznać legacy active za:

- podpisany,
- faktycznie rozpoczęty,
- pokryty orderem,
- gotowy do billing.

Backfill ma rozdzielić:

- facts confirmed,
- facts inferred,
- facts missing,
- conflicts requiring review.

### 14.2. Anomaly classes przed backfillem

Minimum:

- ACTIVE_WITHOUT_DOCUMENT,
- ACTIVE_WITHOUT_COMPLETED_SIGNATURE,
- ACTIVE_BEFORE_START_DATE,
- ACTIVE_WITHOUT_JOB,
- ACTIVE_WITHOUT_PLACEMENT,
- HIRED_WITHOUT_CONTRACT,
- PLACEMENT_WITHOUT_CONTRACT,
- SIGNED_WITHOUT_CONTRACT_ACTIVATION,
- COMPLETED_SIGNATURE_WITHOUT_ARTIFACT,
- MULTIPLE_LIVE_CONTRACTS_PER_PROCESS,
- CONTRACT_CLIENT_JOB_MISMATCH,
- ORDER_CLIENT_CONTRACT_MISMATCH,
- ACTIVE_WITHOUT_ORDER_COVERAGE,
- LEGACY_ORDER_DATE_DRIFT,
- RATE_CACHE_DRIFT,
- RATE_TERM_OVERLAP,
- INVOICE_WITHOUT_SOURCE,
- ENDED_WITHOUT_REASON,
- FUTURE_TERMINATION_MARKED_ENDED,
- ENDED_WITH_ASSIGNED_ASSET,
- ENDED_WITHOUT_OFFBOARDING,
- GENERATED_B2B_WITHOUT_CONTRACT_LINK,
- DUPLICATE_CONTRACT_NUMBER,
- STUCK_SIGNATURE,
- REVOKED_LINK_STILL_ACTIVE.

### 14.3. Backfill Engagement

Kolejność dopasowania:

1. canonical Placement z Module 4,
2. RecruitmentProcess + accepted Offer,
3. Contract.job_id + candidate_id + client_id,
4. CandidateStage.hired dla tej samej job,
5. ClientOrder,
6. DrPlacementDetail tylko jako słaby hint, nigdy automatyczny prawny dowód.

Confidence:

- exact — wszystkie klucze zgodne,
- high — jednoznaczny process/job/contract,
- ambiguous — wiele dopasowań,
- orphan — brak process/job/placement.

Tylko exact/high mogą być auto-linked. Ambiguous/orphan trafiają do review queue.

### 14.4. Backfill AgreementVersion

Priorytet źródła:

1. signed ContractDocument bytes,
2. Autenti signed document,
3. snapshot document wskazany przez signature,
4. latest legal document,
5. draft HTML wyłącznie jako unverified legacy draft.

Każdy rekord:

- kopiuje bytes bez re-renderowania,
- liczy SHA-256,
- zapisuje provenance,
- otrzymuje evidence_quality.

Nie wolno automatycznie oznaczyć draft HTML jako fully executed.

### 14.5. Backfill signature

Mapować:

- provider IDs,
- statusy,
- events,
- signer snapshots,
- signed artifact.

Jeżeli brakuje exact document hash albo expected signer role:

- status legacy_completed_unverified,
- nie fully_executed,
- review/waiver policy.

### 14.6. Backfill ClientOrder

Porównać:

- właściwe ClientOrder,
- Contract.client_order_end_date,
- framework,
- files.

Reguły:

- table row ma pierwszeństwo jako strukturalny record,
- legacy scalar może uzupełnić tylko brakującą informację z provenance inferred,
- konflikt nie jest automatycznie naprawiany,
- file bytes dostają hash i immutable version.

### 14.7. Backfill RateTerm

Dla każdego side:

1. schedule rows,
2. cache jako fallback,
3. order/framework source,
4. anomaly przy konflikcie.

Nie wolno:

- wybierać arbitralnie jednego z nakładających się okresów,
- traktować przyszłej stawki jako current,
- sumować walut.

### 14.8. Backfill termination

Legacy end_date i terminated_at nie wystarczą do odzyskania planowanej daty po nadpisaniu.

Źródła pomocnicze:

- ContractAmendment.old_values/new_values,
- Activity history,
- ClientOrder versions/files,
- notification payload,
- Traffit history.

Jeżeli planned end nie jest jednoznaczny:

- unknown, nie równać go automatycznie actual end,
- review queue dla raportów retencji.

### 14.9. Dual-write i shadow-read

Etapy:

1. Nowe tabele, bez zmian zachowania.
2. Backfill + anomaly report.
3. Legacy command adapter pisze nowy model i legacy w jednej transakcji.
4. Nowy model emituje projections.
5. Shadow compare odczytów.
6. Feature flag per surface.
7. Wyłączenie legacy writers.
8. Okres obserwacji zero drift.
9. Drop legacy dopiero w osobnym PR.

### 14.10. Parity gates

Przed cutover:

- 0 nowych active_without_agreement,
- 0 nowych engagement_without_placement,
- 0 nowych order/client mismatch,
- 0 rate overlaps,
- 0 terminal signature regressions,
- 0 issued invoice without source,
- 100% nowych commands z idempotency key,
- 100% external effects przez outbox,
- old/new active counts wyjaśnione per record,
- finance totals parity per currency, nie globalnie.

---

## 15. Szczegółowy plan implementacyjny dla Claude — 41 PR-ów

### 15.1. Zasady wspólne dla każdego PR

Claude ma przed każdym PR:

1. utworzyć świeżą gałąź z aktualnego origin/main,
2. uruchomić git log origin/main..HEAD i sprawdzić, czy feature nie istnieje,
3. nie używać lokalnego Dockera,
4. nie przenosić przypadkowo zmian z wip/uncommitted-main-snapshot,
5. zmienić tylko zakres danego PR,
6. dodać test regresyjny przed lub wraz z poprawką,
7. dla DB użyć Alembic upgrade heads,
8. uzupełnić idempotentnie backend/entrypoint.sh → _COLUMN_STATEMENTS, jeśli PR dodaje kolumnę/tabelę zgodnie z kontraktem repo,
9. nie używać destructive downgrade dla danych prawnych/finansowych,
10. dodać metrics/logs/audit dla nowych ścieżek,
11. uruchomić najmniejszy sensowny host-native check,
12. otworzyć PR, poczekać na pełny hosted CI i poprawić failures,
13. po merge poczekać na deploy,
14. sprawdzić exact SHA przez /api/health z właściwym User-Agent,
15. dla UI wykonać realny browser check i screenshot.

W każdym PR opisać:

- problem,
- inwariant,
- zmianę schematu,
- API compatibility,
- testy,
- telemetry,
- rollout flag,
- forward-fix/rollback.

### Fala A — containment obecnej produkcji

#### PR-00 — Runtime inventory i anomaly scanner

Cel:

- poznać rzeczywistą skalę problemu bez automatycznej naprawy.

Stan zastany na f3e3516:

- Moduł 4 wdrożył już GET /api/admin/pipeline-inventory,
- kontrakt odpowiedzi ma query_version, generated_at, sample_limit, totals, summary, checks, elapsed_ms i auth_mode,
- auth ponownie używa _snapshot_auth,
- każdy check ma timeout i zwraca błąd inline bez wywrócenia całego raportu,
- sample jest limitowane i wolne od PII,
- istnieją już checki hired_no_contract, multiple_live_contracts oraz contract_no_hired.

PR-00 Modułu 5 nie może tworzyć drugiej definicji tych samych trzech anomalii.

Zakres:

- nowy GET /api/admin/engagement-inventory oparty o ten sam wersjonowany response/auth/check contract,
- ewentualne wydzielenie wspólnego check runnera z admin_pipeline_inventory tylko wtedy, gdy diff pozostaje mały i oba endpointy zachowują kompatybilność,
- summary Modułu 5 w /api/admin/snapshot; pełny, potencjalnie droższy drill-down pozostaje w osobnym endpointcie,
- CLI/dry artifact może konsumować endpoint, ale nie duplikuje SQL,
- klasy anomalii z sekcji 14.2,
- jawne odwołanie do trzech istniejących checków Modułu 4 zamiast ich powtórzenia,
- counts, IDs, severity, confidence i suggested owner,
- brak PII w metrykach; pełne IDs tylko dla uprawnionego admina,
- per-currency totals,
- schema revision i source SHA w raporcie.

Pliki orientacyjne:

- backend/app/services/engagement_anomaly_scanner.py,
- backend/app/api/admin_pipeline_inventory.py jako istniejący wzorzec/kontrakt,
- backend/app/api/admin_engagement_inventory.py,
- backend/app/api/admin_snapshot.py wyłącznie dla taniego summary,
- backend/app/schemas/admin_engagement_integrity.py,
- backend/tests/test_engagement_anomaly_scanner.py.

Testy:

- fixture dla każdej anomaly class,
- scanner nie mutuje żadnego row,
- pagination/batching,
- cross-client scope,
- redakcja,
- zgodność response contract z pipeline-inventory,
- błąd/timeout jednego checku nie wywraca pozostałych,
- brak zduplikowanego SQL i podwójnego liczenia trzech istniejących anomaly keys.

AC:

- raport uruchamia się na prod bez lockowania długich tabel,
- każdy count ma drill-down,
- baseline zostaje zapisany w artefakcie CI/operacyjnym,
- brak automatycznych UPDATE,
- operator może zestawić M4 i M5 przez query_version/generated_at bez uznawania sumy duplikatów za nową anomalię.

Rollback:

- wyłączyć endpoint flagą; brak zmian danych.

#### PR-01 — Emergency RBAC, ClientAccess i finance containment

Cel:

- zamknąć nieautoryzowane odczyty i mutacje przed przebudową domeny.

Zakres:

- capability registry: legal.read/write, finance.read/write, signing.read/manage, orders.read/write,
- require_client_capability,
- B2B generator: writer i download scope,
- client amendments: list/download scope,
- ClientOrder: client assignment scope,
- contracts/invoices/exports: require_financial_access lub redacted DTO,
- signing detail: signer PII/provider report tylko dla właściwej capability,
- Activity.details przez redact_financial_fields.

Ważne:

- zachować current framework contract resolve_client_access,
- nie cofać tej naprawy do global TacPlus,
- uwzględniać secondary roles przez has_any_role.

Testy:

- pełna macierz admin/DL/HoR/TAC/recruiter/sourcer/user,
- primary i secondary role,
- przypisany i nieprzypisany client,
- owner/non-owner generated document,
- sekwencyjne ID z innego klienta,
- exports i nested schedules.

AC:

- viewer nie może generate/mutate/download B2B legal data,
- TAC bez finance capability nie widzi stawek/marży/invoice amount,
- DL widzi wyłącznie uprawniony client scope zgodnie z policy,
- 403 następuje przed query do wrażliwej tabeli.

Rollback:

- nie wracać do szerokiego guard; forward-fix policy mapping.

#### PR-02 — Legacy status i future termination containment

Cel:

- natychmiast zatrzymać błędne ended/active writes.

Zakres:

- przenieść wąską lokalną poprawkę future early termination na świeżą gałąź,
- analogicznie poprawić dedicated terminate,
- usunąć status/termination fields z generic create/update,
- bulk mark ended kierować do structured command,
- blokować ponowne terminate terminalnego row,
- date policy Europe/Warsaw i jasna inclusive end date,
- pozostawić compatibility response.

Testy:

- future/today/past amendment,
- future/today/past dedicated terminate,
- repeated command,
- bulk mixed outcomes,
- generic PATCH status = 422,
- end-of-day/timezone boundary.

AC:

- przyszłe zakończenie pozostaje aktywne/ending do daty,
- current production regression ma obowiązkowy test w required CI,
- żadna ogólna ścieżka nie ustawia ended.

Rollback:

- feature flag command adapter; nie przywracać known-bad behavior.

#### PR-03 — Zakaz hard delete, bezpieczny storage i HTML containment

Cel:

- zatrzymać utratę dowodów i stored XSS.

Zakres:

- active/sent/signed/financial Contract nie może być DELETE,
- legal/financial delete → void command z reason,
- Document/Amendment/Invoice/Equipment po evidence nie ma hard delete,
- staged storage protocol,
- blob finalize/GC outbox,
- nie usuwać old blob przed DB commit,
- sanitize draft HTML allowlist,
- preview CSP i sandbox,
- print bez active script,
- WeasyPrint deny-all URL fetcher z allowlistą wyłącznie zatwierdzonych asset IDs i limitowanych data URI,
- blokada http://, https://, file://, CSS url() oraz @import w niezaufanej treści,
- SandboxedEnvironment albo ścisła allowlista Jinja AST bez Python globals, calls i arbitrary attributes.

Testy:

- delete draft bez evidence zgodnie z policy,
- delete active/signed = 409/422,
- rollback podczas replace,
- orphan GC,
- script/onerror/svg/javascript URL payloads,
- http/file URL, CSS url(), @import i redirect SSRF payloads,
- znane SSTI payloads dla Jinja globals/attributes/calls,
- immutable blob/hash.

AC:

- aktywny Contract nie pokazuje Usuń w UI,
- wysłanego/signed artifact nie można zmienić/usunąć,
- żaden storage rollback nie traci effective file,
- XSS payload nie wykonuje się w preview,
- renderer nie wykonuje requestu sieciowego ani odczytu pliku z niezaufanej treści,
- template nie uzyskuje dostępu do Python globals ani callable objects.

#### PR-04 — Atomowe i revocable signing links

Cel:

- zapewnić prawdziwe single-use i revocation.

Schemat:

- token_digest,
- revoked_at/by/reason,
- claimed_at,
- sibling_group/expected_signer_id,
- partial unique active link.

Backend:

- atomowe UPDATE ... RETURNING,
- envelope state gate,
- revoke siblings przy complete/withdraw/regenerate,
- GET/pdf po use zgodnie z jawnie zdefiniowaną post-sign policy,
- nie zapisywać pełnego URL/token w Notification/logu.

Testy:

- 20 concurrent submit,
- replay,
- expired,
- withdrawn,
- regenerated old link,
- completed envelope,
- DB/log redaction.

AC:

- dokładnie jeden concurrent request wygrywa,
- withdrawn link natychmiast 404 zgodnie z polityką nieujawniania istnienia zasobu,
- token plaintext nie jest w DB/log/notification.

#### PR-05 — QES fail-closed, content binding i monotonic signing

Cel:

- wyeliminować fałszywe completed.

Zakres:

- signing policy per document type,
- ExpectedSigner na legacy modelu jako minimalny krok,
- DSS required dla QES,
- compare issued artifact hash z signed artifact/protocol,
- distinct required signer roles,
- terminal transition matrix,
- provider filter w sweeper,
- completed_pending_artifact,
- ordered/duplicate webhook handling,
- health capability status.

Testy:

- brak DSS,
- DSS timeout/malformed response,
- non-QES,
- wrong PDF,
- same signer twice,
- wrong expected identity,
- out-of-order webhook,
- completed bez PDF,
- provider cross-processing.

AC:

- bez potwierdzonego policy/hash/role nie ma completed,
- terminal state nie cofa się,
- UI nie pokazuje Dokument przyjęty po semantycznej porażce.

#### PR-06 — Signing recovery outbox w legacy modelu

Cel:

- usunąć create_task/BackgroundTasks gap i położyć minimalny, współdzielony kernel outbox/inbox przed command layer.

Zakres:

- minimalne wspólne outbox/inbox tables i worker contracts; signing jest pierwszym konsumentem,
- enqueue w tej samej transakcji co signature,
- provider idempotency key,
- lease/retry/backoff/dead-letter,
- reconciler draft/sending/unknown,
- download signed artifact retry bez limitu trzech jako jedynego recovery,
- JobRun metrics.

Testy:

- crash przed provider call,
- crash po provider success przed local update,
- duplicate worker,
- provider timeout,
- restart,
- reconciliation.

AC:

- żaden crash point nie gubi requestu,
- provider nie dostaje logicznego duplikatu,
- stuck age widoczne w admin snapshot,
- późniejsze Engagement commands mogą użyć tego samego transactional enqueue bez nowego równoległego outboxa.

### Fala B — dokument prawny i wspólny podpis

#### PR-07 — LegalAgreement i immutable AgreementVersion

Cel:

- wprowadzić prawne źródło prawdy bez zmiany obecnego UI.

Schemat:

- legal_agreements,
- agreement_versions,
- owner_scope,
- client_id,
- transitional legacy_contract_id,
- bez FK do engagement przed PR-12,
- constraints revision/hash/storage,
- soft void,
- current_version_id,
- provenance/evidence quality.

Implementacja:

- przygotowanie bytes raz,
- canonical payload,
- template/renderer version,
- immutable ORM/service guard,
- object storage checksum.

Testy:

- mutation po prepared,
- hash round-trip,
- concurrent revision,
- supersede,
- void/legal hold.

AC:

- każda nowa przygotowana umowa ma immutable bytes/hash,
- ContractDocument pozostaje compatibility projection,
- candidate agreement ma jednoznaczny legacy Contract owner, a framework agreement client owner; żaden PR nie odwołuje się do jeszcze nieistniejącej tabeli engagements.

#### PR-08 — Migracja ContractDocument i B2BGeneratedContract

Cel:

- powiązać istniejące artefakty z wersjami.

Zakres:

- backfill signed/uploaded ContractDocument,
- B2BGeneratedContract z explicit AgreementVersion oraz legacy Contract/client owner,
- engagement_id zostanie dodany i zbackfillowany w PR-12,
- append-only numbering ledger,
- re-download zwraca original bytes,
- preview bez side effect,
- generated delete → void,
- orphan/ambiguous report.

Testy:

- historyczny signed PDF,
- draft HTML jako unverified,
- duplicate number,
- missing blob,
- re-render code version drift.

AC:

- nowego numeru nie można ponownie użyć,
- download historycznego dokumentu nie renderuje go aktualnym kodem,
- każdy nowy register row ma legal owner/scope.

#### PR-09 — Wspólny SignatureEnvelope i adaptery providerów

Cel:

- jeden lifecycle dla in-house, Autenti i manual.

Schemat:

- signature_envelopes,
- expected_signers,
- signature_evidence,
- signature_events/inbox relation.

Adapter:

- prepare,
- dispatch,
- status,
- withdraw,
- remind,
- fetch artifact.

Manual provider:

- wymaga evidence upload,
- maker-checker approval,
- nie udaje zewnętrznej delivery.

Testy:

- contract tests dla każdego adaptera,
- identyczne normalized transitions,
- provider unavailable,
- manual approval separation.

AC:

- UI i domain service nie zawierają if Autenti/in-house dla lifecycle,
- każdy envelope wskazuje AgreementVersion.

#### PR-10 — Client framework/MSA na modelu LegalAgreement

Cel:

- objąć umowy ramowe tą samą niezmiennością i signing policy.

Zakres:

- ClientFrameworkAgreement variant,
- owner_scope client_framework + client_id; bez obowiązkowego engagement_id,
- applicability do wielu Engagement/Order zamiast ownership przez jeden Engagement,
- client party snapshot,
- versioned terms,
- effective_from/to,
- future effective state,
- parent/supersedes,
- migrate files/signatures,
- ClientAccess capabilities.

Testy:

- future effective,
- expired/superseded,
- wrong client parent,
- file replace creates version,
- scoped read/download.

AC:

- Autenti completed przed effective date nie oznacza jeszcze effective,
- MSA file nie jest zastępowany in-place.

#### PR-11 — Typed AmendmentApplicationService

Cel:

- aneks ma zmieniać obowiązujące warunki dokładnie raz i w terminie.

Zakres:

- proposal z base_version,
- typed change set,
- generated AgreementVersion,
- signing,
- minimalny, generyczny Obligation/JobRun kernel z due_at, state, unique idempotency key i lease,
- effective date obligation jako pierwszy konsument; PR-23/25 ponownie używają tego kernela,
- idempotent apply,
- correction/supersede,
- old/new wyliczane przez server.

Testy:

- stale base version,
- duplicate webhook/apply,
- future effect,
- restart i dwa równoległe workery dla due effect,
- retroactive approved effect,
- rejected/withdrawn,
- multiple ordered amendments.

AC:

- caller nie podaje arbitralnego old_terms,
- signed amendment zmienia terms w określonej dacie dokładnie raz,
- nie istnieje drugi process-local timer dla tej samej zmiany.

### Fala C — kanoniczny Engagement

#### PR-12 — Schemat Engagement w shadow mode

Cel:

- utworzyć aggregate root bez zmiany zachowania użytkownika.

Schemat:

- engagements,
- nullable engagement_id na Contract/Order/Agreement,
- placement/process/candidate/job/client FKs,
- version,
- dates i termination fields,
- partial unique live placement.

Testy:

- DB constraints,
- one live per placement,
- date checks,
- no cascade delete person/client/job.

AC:

- migration jest additive,
- legacy endpoints nadal działają,
- schema revision widoczna w health/admin.

#### PR-13 — Deterministyczny backfill Engagement

Cel:

- zbudować shadow records bez fałszywych automatycznych decyzji.

Zakres:

- matching z sekcji 14.3,
- confidence,
- exception queue,
- batch cursor,
- restart-safe,
- provenance,
- dry-run i apply oddzielnie.

Testy:

- exact/high/ambiguous/orphan,
- duplicate active,
- no job,
- client mismatch,
- rerun.

AC:

- apply nie zmienia legacy lifecycle,
- ambiguous nigdy nie jest auto-linked,
- counts zgadzają się z preflight.

#### PR-14 — Engagement command service i state machine

Cel:

- jeden mutation path.

Zakres:

- transition registry,
- expected_version,
- idempotency ledger,
- DomainEvent,
- AuditEntry,
- transactional outbox,
- requirement evaluation,
- compatibility adapter.

Testy:

- legal/illegal transition matrix,
- concurrent expected_version,
- duplicate idempotency,
- transaction rollback,
- event ordering.

AC:

- nowy state nie jest ustawiany przez setattr,
- każdy transition ma event/audit/version.

#### PR-15 — Jeden CreateEngagementFromPlacement/hire hook

Cel:

- pipeline, bulk, signing i Traffit nie tworzą osobnych draftów.

Zakres:

- command z placement_id,
- get-or-create,
- accepted terms snapshot,
- create draft agreement/order/onboarding tasks,
- legacy hired hook jako adapter,
- disable direct Contract creation on hired za flagą.

Testy:

- UI hire,
- bulk hire,
- imported hire,
- retry,
- two concurrent requests,
- already active Contract,
- cancelled placement.

AC:

- dokładnie jedno Engagement,
- żadna ścieżka nie wymyśla start_date = today bez accepted terms,
- legacy stage jest projekcją/adapterem.

#### PR-16 — Readiness evaluator, start command i UI

Cel:

- active znaczy faktyczny, kontrolowany start.

Backend:

- policy-versioned readiness,
- agreement/order/rates/onboarding/assets/compliance gates,
- waiver model,
- confirm-start command.

Frontend:

- Engagement header,
- readiness panel,
- blockers z deep links,
- planned vs actual start,
- action hidden/disabled zgodnie z capability,
- semantic tabs i accessible errors.

Testy:

- każdy blocker osobno,
- multiple blockers,
- waiver capability,
- future start,
- concurrent start,
- E2E successful start.

AC:

- future planned start nie jest active,
- start zawsze tworzy EngagementStarted,
- UI pokazuje dokładną przyczynę blokady.

### Fala D — ClientOrder i stawki

#### PR-17 — ClientOrder v2 schema i constraints

Cel:

- jedno źródło pokrycia komercyjnego.

Schemat:

- engagement_id,
- order_number,
- coverage,
- quantity/unit/value/currency,
- version/state,
- framework link,
- client/job consistency,
- date checks.

Testy:

- wrong client/job/framework,
- end before start,
- active order on ended engagement,
- zero/negative values,
- concurrency.

AC:

- invalid cross-client record nie może zostać zapisany,
- current order ma formalną definicję.

#### PR-18 — Migracja legacy client_order_end_date

Cel:

- wyłączyć dwa źródła prawdy.

Zakres:

- backfill/scalar comparison,
- drift dashboard,
- alerts/contractors/client profile czytają ClientOrder,
- scalar staje się compatibility projection,
- writer metrics.

Testy:

- table only,
- scalar only,
- conflict,
- multiple orders,
- future/cancelled order.

AC:

- wszystkie aktywne consumer reads używają ClientOrder,
- drift = 0 przed wyłączeniem scalar writes.

#### PR-19 — Immutable ClientOrderVersion i storage

Cel:

- replace PO tworzy wersję, nie niszczy dokument.

Zakres:

- order_versions,
- hash/original bytes,
- staged upload,
- approve/effective commands,
- supersede/cancel,
- file path po realnym ID.

Testy:

- DB rollback,
- blob failure,
- version race,
- old version download,
- cancel/effective.

AC:

- starego PO nie można utracić przez replace,
- każdy effective order wskazuje approved version.

#### PR-20 — Kanoniczny RateTerm

Cel:

- jeden ledger stawek.

Schemat:

- side, Decimal amount, currency, unit, range, source, approval,
- non-overlap exclusion,
- checks.

Service:

- resolve at date,
- append/supersede/correct,
- no full replace.

Testy:

- boundary from/to,
- all future returns none/current policy,
- overlap/same date,
- gap,
- negative/precision,
- currency/unit change.

AC:

- effective_to działa,
- przyszła stawka nie jest current,
- baza odrzuca overlap.

#### PR-21 — Migracja wszystkich konsumentów stawek

Cel:

- usunąć różne definicje marży.

Zakres:

- contracts,
- contractors,
- ClientOrder,
- invoice/billing,
- analytics,
- exports,
- benchmark,
- alerts.

Rollout:

- shadow compute,
- mismatch metrics,
- per-currency parity,
- potem new resolver.

Testy:

- monthly/hourly/daily,
- billing hours,
- Decimal precision,
- future schedule,
- zero/negative policy,
- cross-currency no sum.

AC:

- jeden resolver dla API i projection,
- cache nie jest source of truth.

### Fala E — onboarding, success, offboarding i assets

#### PR-22 — Versioned onboarding templates i plan

Cel:

- onboarding jest kontrolowanym procesem.

Schemat:

- templates/revisions,
- plans,
- item instances,
- owner/dependency/evidence/waiver.

Zakres:

- client/contract type rules,
- pre-start/day1/week1 phases,
- idempotent generation,
- completion audit.

Testy:

- template update nie zmienia istniejącego planu,
- dependencies,
- mandatory/optional,
- evidence,
- waiver permissions,
- duplicate generate.

AC:

- plan jest snapshotem revision,
- mandatory blocker zasila readiness.

#### PR-23 — Asset registry i custody ledger

Cel:

- sprzęt ma append-only historię odpowiedzialności.

Schemat:

- assets,
- assignments,
- custody events,
- evidence,
- deposit settlement.

Testy:

- serial uniqueness,
- double assignment,
- handover acceptance,
- returned fields,
- condition/deposit,
- delete forbidden.

AC:

- nie można stracić historii po zwrocie,
- assigned asset tworzy return obligation.

#### PR-24 — Poprawny termination/renewal model

Cel:

- zachować planned, notice, effective i actual dates.

Zakres:

- ScheduleTermination,
- CancelBeforeStart,
- ConfirmEnded,
- RenewalDecision,
- prolongation/extension command,
- reason taxonomy,
- immutable outcome snapshot.

Testy:

- future/today/past,
- extension po notice,
- cancellation before start,
- retraction/correction,
- actual later/earlier,
- retention calculation.

AC:

- planned_end nigdy nie jest nadpisany,
- 29 legacy unspecified są oznaczone jako data gap, nie fałszywe 100%.

#### PR-25 — Offboarding orchestration

Cel:

- każde planowane zakończenie z PR-24 tworzy kontrolowany plan.

Zakres:

- versioned templates,
- access revoke,
- client confirmation,
- knowledge transfer,
- final timesheet/billing,
- asset return,
- candidate availability,
- blocking/waiver rules,
- obligations oparte o minimalny kernel z PR-11.

Testy:

- immediate/future termination,
- duplicate generation,
- open asset,
- final invoice pending,
- waiver.

AC:

- ended nie zamyka procesu z otwartymi blocking tasks bez jawnego override,
- overdue tasks są widoczne/eskalowane.

#### PR-26 — Consultant Success

Cel:

- mierzyć jakość delivery przed końcem kontraktu.

Zakres:

- check-ins,
- health,
- risks,
- actions,
- owner/deadline,
- satisfaction,
- renewal intent,
- client and consultant perspectives.

UI:

- action center,
- risk badge,
- check-in cadence,
- renewal pipeline.

Testy:

- risk lifecycle,
- overdue action,
- access scope,
- secondary roles,
- PII redaction.

AC:

- każde high risk ma owner/deadline,
- renewal nie jest wyłącznie alertem daty końca.

### Fala F — timesheet i bezpieczny billing

#### PR-27 — TimesheetPeriod i TimeEntry schema

Cel:

- kontrolowane źródło ilości.

Zakres:

- period/revision,
- entries,
- absence categories,
- order allocation,
- source,
- current revision unique.

Testy:

- overlapping periods policy,
- quantity precision,
- daily/hourly,
- order coverage,
- revision.

AC:

- dokładnie jedna current revision per period,
- totals reprodukowalne.

#### PR-28 — Timesheet approval workflow

Cel:

- klient/internal approval jest dowodem.

Stany:

- open,
- submitted,
- rejected,
- approved,
- locked,
- invoiced.

Zakres:

- expected approver,
- approval token/capability,
- evidence,
- reject reason,
- revise creates revision,
- lock.

Testy:

- stale version,
- wrong approver,
- duplicate approve,
- edit approved,
- correction,
- audit.

AC:

- approved row nie jest nadpisywany,
- każda zmiana po approval tworzy revision.

#### PR-29 — BillingDocument/Invoice v2

Cel:

- immutable dokument finansowy z poprawnymi typami.

Schemat:

- documents/lines,
- NUMERIC Decimal,
- net/VAT/gross,
- currency,
- legal party snapshots,
- service period,
- number uniqueness scope,
- artifact hash,
- external/KSeF IDs,
- feature flag: do PR-31 można tworzyć wyłącznie draft; issue/approve writer pozostaje wyłączony.

Testy:

- rounding,
- tax,
- number race,
- issue immutability,
- wrong party/order,
- currency.

AC:

- issued document immutable,
- Integer amount legacy jest tylko compatibility view,
- przed PR-31 nie istnieje ścieżka, która ominie source readiness i wyda dokument.

#### PR-30 — Payment events, credit notes i DSO

Cel:

- payment status jest ledger projection.

Zakres:

- partial payment,
- reversal/refund,
- credit note,
- overdue,
- currency-aware aging,
- cancellation policy.

Testy:

- partial/full/overpay,
- reversal,
- credit,
- cancelled invoice exclusion,
- FX/no-FX aggregation.

AC:

- DSO nie miesza walut,
- paid nie jest ręcznym dowolnym PATCH.

#### PR-31 — Billing readiness gate

Cel:

- faktura powstaje z zatwierdzonej ilości i obowiązującej stawki.

Zakres:

- approved timesheet revision,
- order version,
- RateTerm snapshot,
- quantity × rate,
- tax/rounding,
- exception maker-checker.

Testy:

- missing approval/order/rate,
- changed rate after period,
- partial order coverage,
- rounding,
- duplicate invoice period.

AC:

- każda BillingLine reprodukuje wartość,
- issued invoice bez source jest niemożliwa.

### Fala G — trwała orkiestracja, integracje i projekcje

#### PR-32 — Wspólny Domain Outbox/Inbox

Cel:

- zastąpić lokalny signing outbox wspólną platformą.

Zakres:

- domain events,
- outbox/inbox,
- leases,
- retries/backoff,
- dead-letter,
- correlation/causation,
- replay tools,
- payload versioning.

Migracja:

- przenieść signing,
- Teams,
- mail,
- Slack,
- Traffit,
- reporting events.

Testy:

- duplicate worker,
- crash points,
- replay,
- poison message,
- ordering per aggregate.

AC:

- brak create_task dla krytycznych efektów,
- oldest backlog i failures są mierzalne.

#### PR-33 — Pełny rollout Obligation i JobRun

Cel:

- rozszerzyć minimalny kernel z PR-11 i zastąpić wszystkie exact-date loops trwałymi zobowiązaniami.

Zakres:

- due obligations,
- ujednolicenie schema/lease z PR-11 bez tworzenia drugiej tabeli,
- catch-up,
- recurrence/materialization,
- owner/escalation,
- job cursor/watermark.

Migracja:

- contract alerts,
- order expiry,
- effective amendments,
- signing reminders/expiry,
- onboarding/offboarding due.

Testy:

- 72h downtime,
- two replicas,
- retry,
- extension cancels/reschedules old obligation,
- timezone.

AC:

- żaden overdue alert nie ginie,
- dwa workery nie dublują effect.

#### PR-34 — Notification delivery ledger

Cel:

- odróżnić attempt od realnego dostarczenia.

Zakres:

- requested/attempted/sent/delivered/failed,
- provider ID,
- retry,
- recipient snapshot,
- related entity typed key,
- templates/version,
- redacted content.

Testy:

- HTTP 4xx/5xx,
- provider timeout,
- duplicate,
- Contract ID == Order ID,
- recipient scope.

AC:

- dashboard nie liczy skonfigurowanego kanału jako delivered,
- Slack używa raise_for_status.

#### PR-35 — Traffit ownership i reconciliation

Cel:

- imported hired używa tego samego command.

Zakres:

- owner matrix,
- source version,
- inbox/outbox,
- field-level conflicts,
- review queue,
- idempotent CreateEngagementFromPlacement adapter.

Testy:

- duplicated/reordered import,
- hired without local placement,
- legal/financial overwrite attempt,
- conflict resolution.

AC:

- Traffit nigdy nie nadpisuje legal/signature/billing facts,
- każda imported decision ma provenance.

#### PR-36 — DynaReporter jako rebuildable projection

Cel:

- usunąć ręczny placement truth.

Zakres:

- projection z PlacementAccepted/EngagementStarted/Ended,
- stable client mapping table,
- rebuild command,
- compare legacy,
- KPI derived, bez counters.

Testy:

- replay,
- correction/void,
- client ID mismatch,
- delete event/compensation,
- DL attribution.

AC:

- ręczny create/delete wyłączony po parity,
- projection można odbudować od zera.

#### PR-37 — Canonical analytics projections

Cel:

- jedna definicja placement, active, revenue, margin, utilization, retention i renewal.

Zakres:

- fact tables/events,
- active interval,
- actual quantity,
- RateTerm snapshots,
- per-currency facts,
- data quality coverage,
- analytics v1 consumers.

Testy:

- future start,
- ending,
- partial month,
- early termination,
- multi-currency,
- missing data.

AC:

- client profile, contracts analytics i DynaReporter zgadzają się,
- każda metryka ma definition/version/coverage.

#### PR-38 — Observability, SLO i pełny CI modułu

Cel:

- drift i stuck work są wykrywane przed użytkownikiem.

Zakres:

- anomaly gauges,
- outbox/inbox lag,
- obligation lag,
- signature SLA,
- active without gates,
- schema revision,
- reconciliation dashboard,
- alerts/runbook.

CI:

- modułowy manifest/glob zamiast niepełnej ręcznej listy,
- zakaz silent return w testach,
- pełne fixtures,
- public signing concurrency,
- state-machine property tests,
- prod-snapshot migration upgrade test,
- entrypoint fail-closed test.

AC:

- 230 vs 104 gap przestaje zależeć od ręcznej listy,
- krytyczne testy są required,
- snapshot pokazuje last success, next due, backlog i oldest age.

### Fala H — repair, parity i cutover

#### PR-39 — Audytowane repair tooling

Cel:

- bezpiecznie naprawiać legacy anomalies.

Zakres:

- jedna komenda per anomaly class,
- dry_run default,
- preview,
- maker-checker dla legal/finance,
- batch/cursor,
- idempotency,
- before/after evidence,
- no auto-delete.

Testy:

- every anomaly,
- rerun,
- partial failure,
- authorization,
- rollback przez compensating event.

AC:

- żadna masowa naprawa nie uruchamia się milcząco,
- operator widzi dokładny zakres.

#### PR-40 — Shadow parity, feature-flag cutover i usunięcie legacy writes

Cel:

- przełączyć system bez utraty danych.

Etapy w jednym programie, ale możliwe jako kilka małych deploy commits w PR:

1. shadow reads,
2. mismatch dashboard,
3. 5% internal cohort,
4. 25%,
5. 100%,
6. disable legacy writers,
7. observe zero drift,
8. validate constraints,
9. usunąć legacy UI/actions,
10. osobny późniejszy cleanup columns.

Legacy do wyłączenia:

- Contract status writes,
- client_order_end_date writes,
- cached rate writes jako authority,
- mutable legal document replace,
- manual DynaReporter placement,
- old invoice status/delete,
- old exact-date loops,
- fire-and-forget effects.

AC:

- parity gates z sekcji 14.10 są spełnione,
- rollback przełącza read path, nie kasuje canonical writes,
- production health pokazuje exact SHA i schema revision,
- browser E2E przechodzi pełny lifecycle.

---

## 16. Kolejność wdrożenia i zależności

### 16.1. Krytyczna ścieżka

~~~text
PR-00
 ├─ PR-01
 ├─ PR-02
 ├─ PR-03
 ├─ PR-04 → PR-05 → PR-06
 └─ PR-07 → PR-08 → PR-09 → PR-10 → PR-11
                    ↓
PR-12 → PR-13 → PR-14 → PR-15 → PR-16
                    ↓
PR-17 → PR-18 → PR-19 → PR-20 → PR-21
                    ↓
PR-22 → PR-23 → PR-24 → PR-25 → PR-26
                    ↓
PR-27 → PR-28 → PR-29 → PR-30 → PR-31
                    ↓
PR-32 → PR-33 → PR-34 → PR-35 → PR-36 → PR-37 → PR-38
                    ↓
PR-39 → PR-40
~~~

### 16.2. Co można prowadzić równolegle

Po PR-00:

- PR-01, PR-02 i PR-03 mogą być niezależnymi hotfixami.
- PR-04 może ruszyć równolegle z PR-07, jeżeli schema zmian nie koliduje.
- PR-22 onboarding i PR-23 assets mogą ruszyć po Engagement schema/state machine.
- PR-27 timesheet może powstawać równolegle z PR-22/23 po stabilnym Engagement ID.
- PR-35 Traffit i PR-36 DynaReporter mogą powstawać równolegle po DomainEvent contract.

Nie prowadzić równolegle:

- dwóch PR modyfikujących te same statusy Contract,
- dwóch migracji przebudowujących document_signatures,
- RateTerm schema i consumers bez uzgodnionego resolver contract,
- cutover zanim reconciliation jest produkcyjnie widoczne.

### 16.3. Rekomendowana wartość biznesowa fal

Największy zwrot i redukcja ryzyka:

1. PR-01 do PR-06 — bezpieczeństwo i podpis.
2. PR-12 do PR-16 — jedna współpraca i prawdziwy start.
3. PR-17 do PR-21 — zamówienie i stawki.
4. PR-22 do PR-26 — operacyjna jakość i zakończenie.
5. PR-27 do PR-31 — rzeczywiste rozliczenia.
6. PR-32 do PR-40 — odporność, integracje i finalny cutover.

---

## 17. Wymagana strategia testów

Testy nie mogą być dopisane dopiero przy cutover. Każdy nowy inwariant ma wejść do required CI w tym samym PR, który go wprowadza.

### 17.1. Warstwy testów

| Warstwa | Co chroni | Gdzie uruchamiać |
|---|---|---|
| Unit | kalkulacje, transition matrix, readiness, redakcję DTO | host-native i CI |
| Repository/service | transakcje, constraints, optimistic concurrency | hosted Postgres w CI |
| API integration | RBAC, client scope, komendy, idempotency, error contract | hosted CI |
| Contract tests | adaptery Autenti, DSS, Traffit, DynaReporter, storage | mock provider + hosted CI |
| Worker tests | leases, retry, outbox/inbox, obligations, recovery | hosted CI |
| Frontend component | capabilities, error states, cache invalidation, a11y | Vitest |
| E2E | pełny lifecycle i negatywne flow | Playwright workflow |
| Migration | upgrade ze snapshotu produkcyjnego, backfill, constraints | osobny hosted job |
| Production smoke | exact SHA, health, API i realny UI | po deploy |

### 17.2. Minimalna macierz autoryzacji

Role/capabilities:

- admin,
- przypisany delivery lead,
- nieprzypisany delivery lead,
- TAC przypisany do klienta,
- TAC bez przypisania,
- head of recruitment,
- recruiter własnego procesu,
- recruiter obcego procesu,
- sourcer,
- zwykły viewer/user,
- public signer z ważnym tokenem,
- public signer ze starym/wycofanym tokenem.

Zasoby:

- Engagement,
- LegalAgreement i AgreementVersion,
- framework/MSA i amendment,
- SignatureEnvelope i evidence,
- ClientOrder,
- RateTerm,
- onboarding/offboarding,
- asset,
- timesheet,
- BillingDocument/payment,
- eksport i Activity/AuditEntry.

Operacje:

- list,
- detail,
- create,
- update,
- command transition,
- preview/render,
- upload,
- download,
- export,
- void/archive,
- repair.

Każdy test ma sprawdzać nie tylko status HTTP, ale również:

- brak sekretu/PII/finance w body,
- brak mutacji DB po odmowie,
- brak blob/outbox side effect,
- jednolitą politykę 403/404,
- audit entry dla operacji dozwolonej.

### 17.3. State machine i property tests

Dla Engagement, LegalAgreement, SignatureEnvelope, ClientOrder, TimesheetPeriod i BillingDocument:

- wygenerować wszystkie pary state_from/state_to,
- tylko jawnie dozwolone przejścia mogą przejść,
- terminal state nie może się cofnąć,
- retry tej samej komendy nie zmienia wyniku,
- ten sam idempotency key z innym payloadem zwraca conflict,
- stale expected_version zwraca 409,
- każda skuteczna zmiana ma dokładnie jeden DomainEvent.

Warto użyć testów tabelarycznych lub property-based. Nie kodować transition rules osobno w teście i produkcji w sposób, który pozwala obu kopiom mieć ten sam błąd; testować również inwarianty niezależne od konkretnej implementacji.

### 17.4. Testy dat i czasu

Obowiązkowe przypadki:

- start/end wczoraj, dziś i jutro,
- future early termination,
- termination effective today,
- planowane i faktyczne zakończenie różne,
- ostatni dzień miesiąca,
- rok przestępny,
- DST Europe/Warsaw,
- job przed i po północy UTC oraz czasu biznesowego,
- restart po przekroczeniu exact threshold,
- kilka dni zaległości,
- ponowienie schedulera po częściowym wykonaniu.

Business date powinien być jawny w komendzie/test clock. Test nie może zależeć od rzeczywistego datetime.now().

### 17.5. Testy signing i legal evidence

Obowiązkowe:

1. DSS off, timeout, 5xx, INDETERMINATE i TOTAL_FAILED nie finalizują procesu.
2. Non-QES nie przechodzi policy QES.
3. Obcy PDF z poprawnym podpisem nie przechodzi content binding.
4. Zmiana jednego bajtu bazowego dokumentu jest wykryta.
5. Nieoczekiwany signer nie spełnia wymaganej roli.
6. Dwa podpisy tej samej osoby nie spełniają dwóch stron, jeśli policy tego zabrania.
7. Właściwa incremental PAdES revision i właściwi signerzy kończą envelope.
8. Dwadzieścia równoległych submitów jednego tokenu daje dokładnie jeden sukces, jeden artifact i jeden completion event.
9. Withdraw/regenerate/complete/expiry odcina każdy stary link.
10. Late webhook nie cofa terminalnego statusu.
11. Completed bez pobranego i zahashowanego artifact pozostaje completed_pending_artifact.
12. Replace/supersede nie zmienia bytes wcześniej wysłanej AgreementVersion.

### 17.6. Testy finansowe

- Decimal bez konwersji przez float/int,
- 0.01, duże kwoty i rounding policy,
- candidate/client currency mismatch jest blokowany lub jawnie obsłużony,
- nakładające się RateTerm są odrzucone,
- future rate nie jest current,
- partial month ma jawną politykę proracji,
- BillingLine wskazuje approved TimesheetPeriod,
- void/correction zachowuje historię,
- partial payments sumują się poprawnie,
- invoice nie może przejść do issued bez readiness,
- eksport nie wykonuje formuł z wartości użytkownika.

### 17.7. Testy migracji i reconciliacji

Hosted job musi:

1. odtworzyć zanonimizowany snapshot schematu/kształtu danych,
2. wykonać alembic upgrade heads,
3. uruchomić idempotentny entrypoint safety net,
4. uruchomić backfill w dry-run,
5. wykonać backfill,
6. wykonać go drugi raz,
7. sprawdzić, że drugi run ma zero nowych zmian,
8. uruchomić anomaly scanner,
9. walidować constraints,
10. potwierdzić, że ambiguous/orphan nie zostały arbitralnie połączone.

Zakazane:

- test, który robi return, gdy brakuje fixture,
- automatyczne uznawanie legacy completed za legally verified,
- re-render starego dokumentu zamiast kopiowania bytes,
- pomijanie constraint verification po backfillu.

### 17.8. Referencyjny E2E happy path

1. Accepted Offer tworzy jedno Placement.
2. CreateEngagementFromPlacement tworzy dokładnie jedno Engagement.
3. Candidate agreement i client order są przygotowane jako wersje.
4. Podpis zostaje wysłany dla konkretnego hash.
5. Oczekiwani signerzy kończą envelope.
6. Onboarding plan jest zseedowany z wersjonowanego template.
7. Sprzęt jest wydany z custody evidence.
8. Start readiness zmienia się na ready.
9. Start command zapisuje actual_start_at i event.
10. TimeEntry trafiają do otwartego okresu.
11. Okres jest submit/approved.
12. BillingDocument powstaje z approved quantity i RateTerm.
13. Renewal decision planuje zakończenie.
14. Offboarding zamyka dostępy, sprzęt i rozliczenie.
15. CompleteEngagement ustawia actual_end_at.
16. Wszystkie ekrany pokazują zgodny stan bez reloadu.
17. Analytics używa tej samej projekcji co detail.

### 17.9. Referencyjne E2E negatywne

- aktywacja bez podpisu/orderu/onboardingu jest zablokowana,
- viewer nie tworzy ani nie pobiera umowy,
- nieprzypisany użytkownik nie enumeruje client resources,
- future termination nie kończy współpracy dziś,
- zakończenie z otwartym asset/period ma blockers,
- faktura bez approved timesheet nie powstaje,
- crash workera po remote send zostaje naprawiony przez reconciliation,
- awaria API pokazuje error, nie zero,
- konflikt wersji pokazuje refresh/compare, nie silent overwrite.

---

## 18. Observability, SLO i runbooki

### 18.1. Metryki domenowe

Gauges/counters:

- engagements_by_state,
- active_without_executed_agreement,
- active_without_order_coverage,
- active_without_completed_onboarding,
- future_start_marked_active,
- ended_without_offboarding,
- ended_with_assigned_asset,
- placement_without_engagement,
- engagement_without_placement,
- engagement_without_job,
- duplicate_engagement_candidates,
- rate_term_overlap,
- rate_cache_drift,
- invoice_without_approved_quantity,
- billing_without_rate_provenance.

### 18.2. Metryki orkiestracji

- outbox_pending_total,
- outbox_oldest_age_seconds,
- inbox_unprocessed_total,
- obligation_overdue_total,
- obligation_oldest_lag_seconds,
- worker_last_success_timestamp,
- job_run_failures_total,
- dead_letter_total,
- reconciliation_drift_total.

### 18.3. Metryki signing

- signature_by_state,
- signature_sending_age_seconds,
- completed_pending_artifact_total,
- qes_validation_result_total,
- content_binding_failure_total,
- unexpected_signer_total,
- revoked_link_attempt_total,
- duplicate_submit_rejected_total,
- provider_webhook_out_of_order_total,
- provider_reconciliation_drift_total.

Nie umieszczać w labels:

- email,
- phone,
- candidate name,
- client name przy dużej cardinality,
- token,
- provider payload,
- document number, jeśli grozi cardinality/PII.

### 18.4. Proponowane SLO

| Obszar | Cel początkowy |
|---|---|
| Domain command availability | 99.9% miesięcznie, bez planowanych maintenance |
| Command persistence | 99.99% skutecznych komend ma event/outbox w tej samej transakcji |
| Outbox delivery | 99% w 5 min, 99.9% w 30 min |
| Signing reconciliation | brak sending bez heartbeat starszego niż 15 min |
| Completed artifact | 99.9% completed ma verified bytes/hash w 5 min |
| Daily anomaly scan | zakończony co 24 h |
| Obligation processing | 99% due obligations wykonane w 15 min |
| Projection freshness | p95 poniżej 60 s |
| Critical lifecycle E2E | 100% green przed merge/cutover |

To są cele startowe do zatwierdzenia z właścicielem biznesowym i operacyjnym, nie obietnica obecnego systemu.

### 18.5. Alerty

Page/urgent:

- schema fingerprint niezgodny z oczekiwanym,
- active_without_executed_agreement rośnie po cutover,
- signing QES policy działa bez validator readiness,
- outbox oldest age > 30 min,
- completed_pending_artifact > 15 min,
- provider auth/JWKS failure utrzymuje się,
- double completion invariant violation,
- legal artifact missing/hash mismatch.

Ticket/non-page:

- ambiguous reconciliation queue rośnie,
- onboarding overdue,
- order/rate coverage kończy się,
- asset overdue,
- projection parity drift,
- invoice awaiting approval/payment.

### 18.6. Admin snapshot

Rozszerzać /api/admin/snapshot, nie łamać stabilnego kontraktu /api/health.

Snapshot modułu powinien pokazywać:

- schema heads/fingerprint,
- feature flags i read/write mode,
- counts per lifecycle state,
- anomaly counts z last_scanned_at,
- outbox/inbox backlog i oldest age,
- JobRun last success/next due,
- signing provider readiness bez sekretów,
- migration/backfill cursor,
- shadow parity metrics,
- cutover cohort i rollback readiness.

### 18.7. Minimalne runbooki

1. Signature stuck in sending.
2. Provider reports completed, artifact missing.
3. QES validator unavailable.
4. Revoked token used.
5. Engagement active without gate.
6. Future termination materialized too early/late.
7. Order/rate coverage conflict.
8. Outbox backlog.
9. Migration fingerprint mismatch.
10. Reconciliation drift after release.
11. Missing blob/hash mismatch.
12. Rollback read path after cutover.

Każdy runbook musi mieć:

- symptom i alert,
- bezpieczny read-only diagnosis,
- sposób containment,
- dry-run repair,
- wymagany approver,
- dowód poprawy,
- sposób eskalacji,
- zakaz ręcznego update SQL bez audit/repair command.

---

## 19. Instrukcja wykonawcza dla Claude Code

### 19.1. Zasada nadrzędna

Claude ma implementować ten plan jako serię małych PR-ów. Nie wolno budować wszystkich encji i ekranów na jednej gałęzi ani próbować od razu zastąpić całego Contract.

Każdy PR powinien:

1. mieć jeden dominujący cel,
2. zawierać test poprzednio błędnego scenariusza,
3. nie mieszać refaktoru z migracją biznesową,
4. mieć jawny rollback/feature flag, jeśli zmienia write path,
5. kończyć się green required CI,
6. po merge sprawdzać exact SHA na produkcji,
7. przy UI wykonywać realny browser flow i screenshot.

### 19.2. Bezpieczny start w obecnym repo

Lokalny checkout zawiera WIP i raporty. Claude nie może go resetować, stashować ani absorbować.

Przed każdym PR:

~~~bash
git fetch origin
git status --short --branch
git log --oneline origin/main..HEAD
git log -1 --format='%H %s' origin/main
~~~

Następnie utworzyć czystą gałąź z aktualnego origin/main zgodnie z repo workflow. Jeżeli izolacja w bieżącym worktree nie jest bezpieczna, użyć osobnego worktree, ale nie usuwać istniejącego WIP.

Pierwsza implementacja future termination ma przejrzeć lokalny diff 297c151 tylko jako źródło wąskiej poprawki. Nie wolno cherry-pickować całego lokalnego commitu ani uznać go za wdrożony.

### 19.3. Pierwsze pliki do przeczytania

Backend core:

- backend/app/api/admin_pipeline_inventory.py jako aktualny wzorzec PR-00,
- backend/tests/test_pipeline_inventory.py,
- backend/app/models/contract.py,
- backend/app/schemas/contract.py,
- backend/app/api/contracts.py,
- backend/app/services/contract_service.py,
- backend/app/api/deps.py,
- backend/app/api/financial_access.py.

Legal/signing:

- backend/app/api/b2b_contract_generator.py,
- backend/app/api/contract_templates.py,
- backend/app/api/signing.py,
- backend/app/api/public_signing.py,
- backend/app/services/signing/sender.py,
- backend/app/services/signing/validation.py,
- backend/app/services/signing/pades.py,
- backend/app/api/autenti.py,
- backend/app/services/autenti/.

Order/rates/billing:

- backend/app/api/client_orders.py,
- backend/app/models/client_order.py,
- backend/app/models/contract_candidate_rate.py,
- backend/app/models/contract_client_rate.py,
- backend/app/models/contract_framework_rate.py,
- backend/app/api/invoices.py,
- backend/app/api/contract_analytics.py.

Lifecycle/integrations:

- backend/app/api/pipeline.py,
- backend/app/tasks/contract_alerts.py,
- backend/app/tasks/dl_portal_expiry_scanner.py,
- backend/app/tasks/traffit_sync.py,
- backend/app/main.py,
- backend/entrypoint.sh.

Frontend:

- frontend/src/app/contracts/,
- frontend/src/components/v2/pages/ContractsListV2.tsx,
- frontend/src/components/v2/pages/ContractorsListV2.tsx,
- frontend/src/components/v2/pages/B2BContractGeneratorV2.tsx,
- frontend/src/components/contracts/,
- frontend/src/components/client-profile/,
- frontend/src/components/ContractDocumentsTab.tsx,
- frontend/src/components/ContractOnboardingTab.tsx,
- frontend/src/components/ContractInvoicesTab.tsx,
- frontend/src/app/sign/[token]/.

Delivery/test:

- .github/workflows/ci.yml,
- .github/workflows/deploy.yml,
- backend/tests/test_contracts*.py,
- backend/tests/test_*sign*.py,
- backend/tests/test_autenti*.py,
- backend/tests/test_client_orders*.py,
- backend/tests/test_invoice*.py.

### 19.4. Pierwsze komendy diagnostyczne

Bez mutowania produkcji:

~~~bash
rg -n 'ContractStatus|status\s*=|status:' backend/app
rg -n 'CurrentUser|TacPlus|require_financial_access|resolve_client_access' backend/app/api
rg -n 'delete\(|delete-orphan|ondelete=' backend/app/models backend/app/api
rg -n 'create_task|BackgroundTasks|outbox|inbox' backend/app
rg -n 'rate_candidate|rate_client|margin' backend/app frontend/src
rg -n 'client_order_end_date|ClientOrder' backend/app
rg -n 'invalidateQueries|contracts-v2|\["contracts"' frontend/src
~~~

Wynik PR-00 ma być maszynowo powtarzalny. Nie wklejać jednorazowego ręcznego SQL jako jedynego dowodu.

### 19.5. Host-native verification

Nie używać lokalnego Dockera.

Backend, proporcjonalnie do PR:

~~~bash
cd backend
ruff check app/ tests/test_contracts.py
ruff format --check app/ tests/test_contracts.py
pytest tests/test_contracts.py -v
~~~

Frontend, proporcjonalnie do PR:

~~~bash
cd frontend
npm run type-check
npm run lint
npm run test -- src/lib/__tests__/contract-rate-schedule.test.ts
~~~

Build uruchamiać tylko, gdy nie działa równolegle dev/start. Pełne Postgres, migrations, image build i E2E pozostawić hosted CI zgodnie z repo contract.

### 19.6. Reguła migracji NEXUS

Każda nowa tabela/kolumna/constraint:

1. migracja Alembic z aktualnego head set,
2. alembic upgrade heads, nie pojedyncze head,
3. idempotentne odzwierciedlenie wymaganych elementów w backend/entrypoint.sh zgodnie z project rule,
4. schema preflight/fingerprint,
5. test istniejących danych,
6. expand → backfill → validate → enforce → contract,
7. downgrade tylko, jeśli jest rzeczywiście bezpieczny; przy danych prawnych preferować forward repair.

Nie dodawać kolejnej kompletnej, ręcznej kopii definicji tabeli do entrypoint. Długofalowo safety net ma być mały, wersjonowany i fail-closed.

### 19.7. Reguła API

Nowe endpointy są command-oriented:

- request ma idempotency_key i expected_version,
- response ma command_id, aggregate_id, version, state, blockers/warnings i correlation_id,
- błędy mają stabilny code, nie tylko dowolny detail string,
- 409 oznacza conflict/current version,
- 422 oznacza naruszenie reguły/invalid input,
- 403/404 są zgodne z jedną polityką resource hiding,
- 503 oznacza niedostępną wymaganą capability/integrację bez mutacji stanu.

Nie rozszerzać generic PATCH o kolejne pola lifecycle.

### 19.8. Reguła frontendowa

- UI korzysta z capabilities zwróconych przez backend.
- Ukrycie przycisku nie zastępuje autoryzacji.
- Każda mutacja ma jeden pending lock dla całego command flow.
- Error, empty, loading, forbidden i conflict są osobnymi stanami.
- Centralne query keys i graph invalidation.
- Semantic tokens; bez hardcoded kolorów.
- Dialog primitives z focus trap/Escape.
- Authenticated file download przez blob flow.
- Po user-visible PR: desktop i mobile screenshot przez realny browser.

### 19.9. Reguła merge/deploy

Po każdym PR:

1. required CI green,
2. squash merge do main,
3. deploy workflow i Coolify zakończone,
4. /api/health z User-Agent dynaminds-smoke-test/1.0,
5. status != unhealthy,
6. version zaczyna się od siedmiu znaków merged SHA,
7. backend change: smoke konkretnego endpointu,
8. UI change: realna interakcja w produkcji,
9. feature flag/cohort i anomaly metrics sprawdzone,
10. rollback path nadal działa.

---

## 20. Definition of Done modułu

Moduł nie jest zakończony tylko dlatego, że nowe ekrany istnieją.

### 20.1. Bezpieczeństwo

- zero CurrentUser-only writerów dla legal/finance,
- pełny client/resource scope,
- capability matrix w backendzie,
- finance i signer PII redagowane również w activity/errors/exports,
- signed/legal artifacts immutable,
- public tokens hashowane, revocable i atomowo single-use,
- QES fail-closed,
- SSRF/SSTI/file upload boundary zamknięte,
- brak hard delete prawnych i finansowych dowodów.

### 20.2. Lifecycle

- Placement tworzy jedno Engagement,
- jeden domain command odpowiada za start,
- Contract nie jest źródłem operacyjnego statusu,
- planned i actual dates są rozdzielone,
- future termination nie kończy dziś,
- onboarding/start/offboarding/end mają gate,
- renewal i cancellation before start mają osobne semantyki.

### 20.3. Legal i signing

- AgreementVersion ma bytes/hash/provenance,
- każda SignatureEnvelope wskazuje konkretną wersję,
- expected signer identities/roles są zapisane,
- terminal state jest monotoniczny,
- completed wymaga verified artifact,
- offline exception ma maker-checker i evidence,
- framework, candidate agreement i amendments używają wspólnego modelu.

### 20.4. Order i rates

- ClientOrder ma wersje i coverage,
- legacy client_order_end_date nie jest writerem/source of truth,
- RateTerm jest kanoniczny i bez overlap,
- każdy consumer używa jednego resolvera,
- currency/unit/provenance są jawne,
- cache drift wynosi zero przed usunięciem legacy pól.

### 20.5. Delivery success, assets i offboarding

- versioned onboarding plan,
- evidence/waiver per required step,
- SuccessCheckIn/Risk/Action są na Engagement,
- asset custody jest ledgerem,
- offboarding ma obligations i blockers,
- zakończenie nie pozostawia niejawnie aktywów ani dostępów.

### 20.6. Billing

- approved quantity jest źródłem BillingLine,
- Decimal i jawne rounding/currency,
- invoice jest immutable po issue,
- correction/credit note zamiast delete,
- payments są append-only events,
- DSO ma jednoznaczną definicję,
- brak sumowania różnych walut jako jednej kwoty.

### 20.7. Operacje i dane

- outbox/inbox/obligations restart-safe,
- anomaly scanner i repair tooling działają,
- ambiguous records mają review queue,
- shadow parity osiąga uzgodniony próg,
- schema preflight fail-closed,
- pełne testy są required CI,
- produkcja jest zweryfikowana exact SHA i browser flow.

---

## 21. Decyzje, których Claude nie może podjąć milcząco

Poniższe decyzje wymagają jawnego zatwierdzenia produktu, legal/finance albo właściciela operacyjnego. Claude może przygotować ADR z rekomendacją, ale nie może zakodować arbitralnego założenia.

1. Czy każdy typ candidate agreement wymaga QES, czy część dopuszcza inny poziom podpisu.
2. Jak identyfikujemy upoważnionych company signers i separation of duties.
3. Jak długo przechowujemy dokumenty, evidence, payloady webhook i dane signerów.
4. Jak działa legal hold i kto może go zdjąć.
5. Czy order jest twardym blockerem startu dla każdego klienta, czy istnieją zatwierdzane wyjątki.
6. Kto może zatwierdzić wyjątek start/end i jaki jest maksymalny czas wyjątku.
7. Kto widzi candidate rate, client rate, margin, invoice i payment.
8. Czy TAC ma jakikolwiek dostęp finansowy, skoro aktualna policy wskazuje admin + delivery lead.
9. Jaki jest owner timesheet approval: klient, DL, TAC czy kombinacja.
10. Jak rozliczamy fixed monthly, hourly, daily, overtime, absence i partial month.
11. Jaka jest polityka walut i FX; czy NEXUS tylko przechowuje kurs z systemu finansowego.
12. Jak traktować VAT, reverse charge, credit notes i przyszłe KSeF.
13. Czy planned_end_at jest włącznie ostatnim dniem pracy i w jakiej strefie biznesowej.
14. Kiedy exactly materializuje się actual_end_at.
15. Czy start przed podpisem/orderem jest kiedykolwiek prawnie dopuszczalny.
16. Który system jest authority dla hired/placement podczas coexistence z Traffit.
17. Czy DynaReporter jest tylko projekcją NEXUS, czy ma legalny write-back contract.
18. Jak rozstrzygać legacy records bez job/placement lub z wieloma kandydatami.
19. Czy stare completed signatures bez exact hash mają status unverified czy wymagają ponownego podpisu.
20. Kto może voidować draft, correction i repair oraz gdzie wymagany jest maker-checker.

Do czasu decyzji model ma fail-closed albo jawny blocked/manual_review. Nie wolno zgadywać i oznaczać danych jako verified.

---

## 22. Rekomendowany pierwszy sprint wykonawczy

To nie jest obietnica czasowa. To minimalny zakres kolejności, który redukuje największe obecne ryzyko przed budową nowego modelu.

### Pakiet 1 — inventory i containment

1. PR-00 anomaly scanner + route/auth inventory.
2. PR-01 B2B generator, legal resource scope i finance boundary.
3. PR-02 future termination + zakaz generic status writes.
4. PR-03 hard delete/storage/render containment.

Exit criteria:

- znany baseline anomalies,
- viewer nie mutuje/pobiera legal docs,
- cross-client IDOR zamknięty,
- TAC nie widzi finance bez zatwierdzonej policy,
- future end nie kończy dziś,
- executed evidence nie jest kasowalne.

### Pakiet 2 — podpis

1. PR-04 atomowe linki.
2. PR-05 QES/content/signer binding.
3. PR-06 durable recovery.

Exit criteria:

- stare linki są revocable,
- jeden submit wygrywa,
- DSS unavailable nie finalizuje,
- exact artifact/signer jest dowodliwy,
- crash nie gubi send intent.

### Pakiet 3 — fundament docelowy

1. PR-07 do PR-11 LegalAgreement.
2. PR-12 do PR-16 Engagement shadow mode i start gate.

Exit criteria:

- nowy model istnieje obok legacy,
- backfill jest deterministyczny,
- nowe hires tworzą Placement → Engagement,
- cutover jeszcze nie następuje bez parity.

---

## 23. Gotowy brief startowy dla Claude

Poniższy brief można przekazać jako pierwsze zadanie wykonawcze. Nie zastępuje pełnego planu PR-00.

> Pracuj na najnowszym origin/main NEXUS w czystej gałęzi. Zachowaj lokalny WIP użytkownika i nie używaj Dockera. Zaimplementuj wyłącznie PR-00 z dokumentu Moduł 5: read-only /api/admin/engagement-inventory dla Contract/order/rates/signing/onboarding/assets/invoices. Najpierw przeczytaj wdrożony na f3e3516 /api/admin/pipeline-inventory i ponownie użyj jego _snapshot_auth, wersjonowanego response contract, timeout/error isolation oraz PII-free sample policy. Nie duplikuj checków hired_no_contract, multiple_live_contracts ani contract_no_hired; raport M5 ma się do nich odwoływać. Dodaj tani summary do /api/admin/snapshot, pełne fixtures, testy klasyfikacji i required CI entry. Nie naprawiaj danych ani nie twórz jeszcze Engagement. Dla każdej nowej anomalii zwróć stable key, count, limitowane sample IDs, severity, confidence oraz generated/query version; błąd jednego checku nie może wywrócić raportu. Przed finalizacją porównaj exact origin/main, pokaż diff, uruchom wąskie host-native testy, otwórz PR, doprowadź CI do green, merge/deploy i zweryfikuj exact SHA oraz endpoint produkcyjny.

Po PR-00 kolejny osobny brief powinien dotyczyć PR-01, nie całej reszty planu naraz.

---

## 24. Ostateczna rekomendacja

Najważniejszą zmianą architektoniczną jest wprowadzenie Engagement jako jedynego operacyjnego lifecycle współpracy. Nie jest jednak bezpiecznie zaczynać od tej przebudowy, dopóki obecny system pozwala na:

- nieautoryzowaną mutację umów B2B,
- cross-client odczyt dokumentów i podpisów,
- ekspozycję finansów poza policy,
- fail-open QES,
- ponowne użycie wycofanego linku,
- hard delete evidence,
- przedwczesne zakończenie future-dated,
- start na częściowym schemacie.

Dlatego właściwa kolejność brzmi:

~~~text
Containment → immutable legal evidence → safe signing → Engagement shadow mode
→ order/rates → onboarding/success/offboarding → timesheet/billing
→ durable orchestration → reconciliation → measured cutover
~~~

Sukces biznesowy nie powinien być mierzony liczbą nowych ekranów. Powinien oznaczać, że dla każdej aktywnej współpracy można w kilka sekund wiarygodnie odpowiedzieć:

1. z jakiego Placement powstała,
2. jaka dokładnie wersja umowy została podpisana i przez kogo,
3. jakie zamówienie i stawki obowiązują w danym dniu,
4. czy start/onboarding i compliance są kompletne,
5. kto ma sprzęt i otwarte obowiązki,
6. jaka zatwierdzona ilość jest podstawą rozliczenia,
7. co ma się wydarzyć przy renewal/end,
8. czy offboarding i końcowe rozliczenie są zamknięte,
9. jaki event i operator spowodowali każdą zmianę,
10. czy wszystkie projekcje i integracje zgadzają się z canonical state.

Dopiero wtedy NEXUS będzie zarządzał pełną współpracą, a nie tylko przechowywał luźno powiązane rekordy Contract, dokumenty i raporty.

---

## Appendix A — mapa źródeł dla pierwszych PR-ów

Numery linii pochodzą z czystego snapshotu 6472b67. Przed finalizacją potwierdzono, że żaden wymieniony niżej plik nie zmienił się do aktualnego origin/main f3e3516e717a5f95f38f1de4d42e9f0e74fbd948, więc referencje odpowiadają także audytowanemu stanowi końcowemu. Po kolejnym merge należy wyszukać symbol ponownie, zamiast zakładać, że numer nadal jest aktualny.

### Authorization i finance

- backend/app/api/financial_access.py:16-31 — kanoniczna polityka finance.
- backend/app/api/deps.py:142-152 — CurrentUser obejmuje rolę viewer/user.
- backend/app/api/deps.py:169-172 — TacPlus jako szeroka globalna brama.
- backend/app/api/contracts.py:369-472 — lista umów z polami finansowymi.
- backend/app/api/contracts.py:593-691 — eksport umów.
- backend/app/api/invoices.py:80-277 — odczyt i mutacje invoice przez TacPlus.
- backend/app/api/contractors.py:67-121 — contractor list z danymi finansowymi dla szerszych ról.
- backend/app/api/client_orders.py:160-229,259-277,466-486 — order read/file bez client assignment scope.
- backend/app/api/client_framework_contracts.py:74-87,145-184 — poprawny resolve_client_access, który należy zachować.
- backend/app/api/client_contract_amendments.py:77-97,187-211 — amendment list/download chronione tylko CurrentUser.

### B2B generator i templates

- backend/app/api/b2b_contract_generator.py:216-326 — generate/create/update dowolnego Contract przez CurrentUser.
- backend/app/api/b2b_contract_generator.py:332-379 — detail i DOCX.
- backend/app/api/b2b_contract_generator.py:573-647 — lista/download generated documents.
- backend/app/api/b2b_contract_generator.py:650-751 — owner check dla części mutacji, niespójny z download.
- backend/app/api/contract_templates.py:55-62 — zwykły Jinja Environment.
- backend/app/api/contract_templates.py:127-175 — render context z PII i stawkami.
- backend/app/api/contract_templates.py:302-350 — render dowolnego template + Contract przez CurrentUser.

### Signing i legal evidence

- backend/app/api/signing.py:52-160,200-260 — send/withdraw/regenerate przez szeroką rolę.
- backend/app/api/signing.py:163-197 — list/detail bez target scope.
- backend/app/api/autenti.py:94-134 — drugi rail list/detail bez target scope.
- backend/app/api/public_signing.py:42-149 — valid-link check i nieatomowy submit.
- backend/app/services/signing/sender.py:126-202 — mutable draft/latest document source.
- backend/app/services/signing/sender.py:291-350 — QES validation i finalize.
- backend/app/services/signing/validation.py:56-77,102-154 — INDETERMINATE i mapowanie DSS.
- backend/app/services/signing/pades.py:114-192 — lokalna walidacja bez QES assurance.
- backend/app/services/autenti/pdf_renderer.py:67-100 — render HTML bez deny-all URL fetchera.
- backend/app/services/autenti/webhook_verify.py:119-164 — JWT claims policy.
- backend/app/services/autenti/webhook_handler.py:121-190 — webhook status update bez pełnej monotonicznej state machine.

### Contract lifecycle

- backend/app/services/contract_service.py:17-42 — obecny ograniczony readiness check.
- backend/app/schemas/contract.py:85-175 — status i termination fields w generic create/update schema.
- backend/app/api/contracts.py:1010-1131 — PATCH bez optimistic concurrency.
- backend/app/api/contracts.py:1134-1209 — activate i contract_signed semantics.
- backend/app/api/contracts.py:1545-1562 — hard delete Contract.
- backend/app/api/contracts.py:2225-2306 — terminate ustawia ended niezależnie od future date.

### Frontend

- frontend/src/components/v2/pages/ContractsListV2.tsx:168-199 — query/error state listy.
- frontend/src/components/v2/pages/ContractsListV2.tsx:285-385 — selection i bulk scope.
- frontend/src/app/contracts/[id]/page.tsx:442-468 — invalidacja i delete.
- frontend/src/app/contracts/[id]/page.tsx:485-634 — szeroki edit payload.
- frontend/src/components/v2/modals/DraftCompletionModal.tsx:54-127 — PATCH i activate jako osobne kroki.
- frontend/src/components/v2/pages/B2BContractGeneratorV2.tsx:967-1072 — brak stabilnego contract_id między akcjami.
- frontend/src/components/ContractOnboardingTab.tsx:63-117 — wiele niezależnych create podczas seed.
- frontend/src/components/ContractInvoicesTab.tsx:51-166,192-264 — amount conversion i słabe error states.
- frontend/src/app/sign/[token]/SignForm.tsx:83-172 — sukces UI po ogólnym 200.

Ta mapa nie zastępuje ponownego rg na świeżym origin/main. Jest punktem wejścia do PR-00 i hotfixów, nie trwałym API dokumentacji.
