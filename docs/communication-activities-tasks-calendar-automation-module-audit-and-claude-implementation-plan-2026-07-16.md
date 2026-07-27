# Moduł 6 — Komunikacja, aktywności, zadania, kalendarz i automatyzacje pracy

## Audyt, rekomendacja docelowa i szczegółowy plan implementacyjny dla Claude Code

- Data audytu: 2026-07-16
- Repozytorium: NEXUS
- Bazowy commit głębokiego audytu: `77c7bde155d309495a9aa79ea5220e6d9815bda5`
- Końcowy re-anchor kodu: `origin/main = 273cd08a19586003fff7ec577ca816c93c4fbc31`
- Stan produkcji po końcowej kontroli: wersja `273cd08a19586003fff7ec577ca816c93c4fbc31`, HTTP 200, status `healthy`
- Charakter pracy: audyt read-only kodu, produkcji, panelu operacyjnego i UI; bez zmian danych produkcyjnych
- Adresat planu: Claude Code / Opus realizujący serię małych, odwracalnych PR-ów

---

## 1. Streszczenie zarządcze

NEXUS ma już wiele elementów potrzebnych do współpracy zespołu:

- notatki i wzmianki,
- czat przy kandydacie i rekrutacji,
- powiadomienia in-app i WebSocket,
- kalendarz, konflikty oraz integrację Microsoft 365,
- synchronizację emaili,
- CloudTalk, Fireflies, Teams, Slack i Proxycurl,
- rozmowy, transkrypty i nagrania,
- activity feed i KPI aktywności,
- kilkadziesiąt automatycznych triggerów oraz workerów.

Nie tworzą one jednak jednego, spójnego modułu pracy. Obecny system miesza co najmniej siedem odrębnych pojęć:

1. fakt biznesowy, który już zaszedł,
2. ślad audytowy,
3. notatkę człowieka,
4. wiadomość komunikacyjną,
5. powiadomienie o zdarzeniu,
6. zadanie do wykonania,
7. próbę dostarczenia przez konkretny kanał.

Najważniejszy wniosek brzmi:

> Notification nie może być substytutem zadania, Activity nie może być jednocześnie audytem i feedem dla wszystkich, a `asyncio.create_task` nie może być mechanizmem dostarczania ważnych wiadomości. Moduł potrzebuje kanonicznej warstwy zdarzeń, odpowiedzialności i trwałej dystrybucji.

### 1.1. Najpilniejszy problem produkcyjny

Główna akcja „Email” na profilu kandydata otwiera formularz, który po odpowiedzi 2xx pokazuje stan „Email wysłany”. Backend tego endpointu jawnie opisuje operację jako symulację, nie wysyła wiadomości do żadnego providera, a mimo to zapisuje `Activity(action="email_sent")`.

Skutki:

- recruiter otrzymuje fałszywe potwierdzenie wykonania ważnej czynności,
- historia kandydata zawiera nieprawdziwe `email_sent`,
- kandydat nie dostaje wiadomości,
- późniejszy audyt nie odróżnia prawdziwego maila od symulacji,
- preview może zawierać twardo wpisaną, nieaktualną ofertę, datę i widełki.

Pierwszy PR ma wyłączyć tę ścieżkę sukcesu i skierować UI do działającego composera Microsoft 365 albo jednoznacznie oznaczonego draftu. Nie wolno czekać z tym na przebudowę całego modułu.

### 1.2. Pozostałe ryzyka krytyczne

1. Access JWT jest przekazywany w query stringu WebSocketu i może trafiać do logów proxy/APM.
2. Licznik nieprzeczytanych oraz „oznacz wszystkie” mają warunek SQL sprowadzający się do `WHERE false`.
3. Import iCal jest authenticated SSRF, śledzi redirecty i może nadpisywać event innego użytkownika po wspólnym UID.
4. Calendar udostępnia wewnętrznym rolom wszystkie eventy, attendee emails, Teams URL i recording URL bez owner/resource scope.
5. Notes pozwala pobrać bez limitu wszystkie notatki i adresy autorów oraz odczytać dowolną notatkę po ID.
6. Viewer może przez renderer szablonu odczytywać email, telefon i LinkedIn dowolnego kandydata.
7. Compose/reply/bulk email używają `CurrentUser`; read-only viewer może próbować wysyłać wiadomości.
8. Admin i delivery lead mają domyślny dostęp do pełnej treści cudzych skrzynek oraz załączników bez delegacji i break-glass.
9. Calls, CloudTalk i Fireflies nie mają odpowiedniego object-level scope; mapping agenta CloudTalk może zmieniać zwykły użytkownik.
10. Sekret webhooka CloudTalk występuje w ścieżce URL, a podpis nie ma ochrony timestamp/replay.
11. CloudTalk przypisuje kandydata przez ostatnie dziewięć cyfr telefonu i wybiera pierwszy rekord przy kolizji.
12. Recording discovery Microsoft 365 może przypiąć plik do eventu wyłącznie na podstawie bliskości czasu.
13. M365 webhook potwierdza 202 przed trwałym zapisaniem pracy i deduplikuje zdarzenia wyłącznie w pamięci procesu.
14. Crash po zaakceptowaniu wysyłki przez Graph, ale przed lokalnym commitem, może zdublować mail.
15. Zmiana emaila na private lub usunięcie go w Graph nie usuwa trwale zapisanych plików załączników.
16. Wszystkie workery startują na każdej replice; większość nie ma lease, durable dedupe, heartbeat ani supervisor.

### 1.3. Rekomendowany model docelowy

Docelowy moduł powinien mieć rozdzielone agregaty:

1. `DomainEvent` — niezmienny fakt domenowy.
2. `AuditEntry` — bezpieczny, niezmienny ślad kto/co/kiedy.
3. `Conversation` i `Message` — komunikacja przy zasobie, niezależnie od kanału.
4. `Note` i `Comment` — kontekst człowieka, nie komunikat systemowy.
5. `WorkItem` — odpowiedzialność z ownerem, terminem i stanem.
6. `CalendarEvent`, `EventOccurrence` i `EventParticipant` — czas i uczestnictwo.
7. `Notification` — osobista projekcja do przeczytania.
8. `NotificationPreference` — polityka użytkownika i kanałów.
9. `OutboxItem`, `InboxItem`, `InboxReplayRequest`, `ProviderOperation`/
   `ProviderOperationAttempt` oraz `Delivery`/`DeliveryAttempt` — trwała
   dystrybucja, odbiór, jawny replay i wywołania providerów.
10. `IntegrationConnection`, `SyncCursor` i `IntegrationRun` — stan integracji i incydenty widoczne jako nieudane runy/DLQ.
11. `AutomationRule`, `AutomationExecution`, `JobRun`, `WorkerLease` i
    `WorkerHeartbeat` — wersjonowane reguły oraz operacyjna prawda o ich
    wykonaniu.
12. `CommunicationArtifact` i `RetentionManifest` — załączniki, nagrania, transkrypty, retencja i purge.

### 1.4. Rekomendacja wdrożeniowa

Nie wykonywać big-bang rewrite. Plan ma 45 kolejnościowych slotów w siedmiu falach. Szerokie sloty mają obowiązkowy podział na co najmniej 73 osobno mergowane PR-y opisany w sekcji 16.2.

- Fala A — natychmiastowy containment i wymagany test gate.
- Fala B — wspólny kernel zdarzeń, inbox/outbox, delivery i worker leases.
- Fala C — migracja email, M365, Teams, Slack, CloudTalk, Fireflies i Proxycurl.
- Fala D — kanoniczne zadania i obowiązki.
- Fala E — kalendarz, przypomnienia, realtime, presence i chat.
- Fala F — communication hub, timeline, templates, integracje i retencja.
- Fala G — UX, reconciliacja, cutover oraz usunięcie legacy writers.

Jeżeli Moduł 5 wcześniej dostarczy wspólny `DomainEvent`/outbox/obligation kernel, Claude ma go rozszerzyć i wykorzystać, a nie tworzyć konkurencyjne tabele dla Modułu 6.

---

## 2. Zakres i granice modułu

### 2.1. W zakresie

Audyt obejmuje:

- email kandydacki i operacyjny,
- synchronizację skrzynek Microsoft 365,
- szablony, renderowanie, compose, reply i bulk actions,
- czat przy kandydacie i rekrutacji,
- wzmianki, reakcje, read cursor i deep linki,
- notatki i komentarze,
- activity feed, audit trail i timeline encji,
- powiadomienia in-app, email fallback, Teams, Slack i WebSocket,
- preferencje, quiet hours, digest i eskalacje,
- kalendarz, recurring events, konflikty, free/busy i reminder delivery,
- rozmowy telefoniczne, transkrypty i nagrania,
- CloudTalk, Fireflies, Microsoft 365, Teams, Slack i LinkedIn/Proxycurl,
- presence i realtime updates,
- zadania, follow-upy, snooze, ownership, completion i recurrence,
- background workery, webhooki, polling, retry, DLQ i operational status,
- bezpieczeństwo artefaktów komunikacyjnych i retencję,
- UI centrum powiadomień, My Work, Communication Hub oraz ustawienia integracji.

### 2.2. Granica z modułami 1–5

Moduł 6 jest warstwą współpracy i uwagi nad faktami biznesowymi z innych modułów.

- Moduł 1 jest właścicielem klienta, kontaktu i zapotrzebowania.
- Moduł 2 jest właścicielem kandydata, PII, consent i talent data.
- Moduł 3 jest właścicielem matching/scoring/recommendation.
- Moduł 4 jest właścicielem procesu rekrutacyjnego, submission, offer i placement.
- Moduł 5 jest właścicielem engagement, umów, onboardingu, delivery i billing.
- Moduł 6 nie duplikuje tych stanów; reaguje na ich zdarzenia, tworzy zadania, dostarcza wiadomości i pokazuje historię.

Na końcowym `origin/main` Moduł 4 ma już shadow-only
`WorkflowDefinition/WorkflowRevision/StageRevision/WorkflowEdge` oraz
wersjonowany rejestr `semantic_key`; runtime pipeline jeszcze z nich nie czyta.
Moduł 6 ma konsumować identyfikator rewizji, `semantic_key` i
`StageRevision.sla_max_days` w eventach/bridge do WorkItem. Nie wolno mu tworzyć
drugiego grafu procesu rekrutacyjnego. `AutomationRule` z tego raportu jest
regułą reakcji komunikacyjnej/obowiązku, a nie właścicielem dozwolonych przejść
pipeline.

Przykład:

~~~text
Moduł 4: CandidateSubmittedToClient
            |
            +--> Moduł 6: Notification dla ownera
            +--> Moduł 6: WorkItem „follow-up z klientem”
            +--> Moduł 6: Outbox email/Teams według polityki
            +--> Moduł 6: timeline projection
~~~

Moduł 6 nie może zmieniać `CandidateStage` bez wywołania komendy Modułu 4. Kliknięcie akcji w powiadomieniu może wywołać autoryzowaną komendę domenową, ale sama notyfikacja nie jest źródłem prawdy.

### 2.3. Rozróżnienie podstawowych pojęć

#### DomainEvent

Fakt, który już zaszedł i nie może zostać „odczytany” ani „wykonany”. Przykład: `InterviewScheduled`.

#### AuditEntry

Niezmienny ślad wykonania komendy lub dostępu, przeznaczony do audytu. Nie wolno zwracać jego surowych details wszystkim użytkownikom.

#### Note

Treść napisana przez człowieka. Może być edytowalna według polityki, ale historia rewizji musi pozostać audytowalna.

#### Message

Komunikat wysłany lub odebrany w konkretnej rozmowie i kanale. Ma kierunek, uczestników oraz stan providera.

#### Notification

Osobista projekcja informacyjna. `read` oznacza wyłącznie zapoznanie się, nie wykonanie pracy.

#### WorkItem

Obowiązek lub follow-up. Ma assignee, due date, status, priorytet, snooze i historię.

#### DeliveryAttempt

Jedna trwała próba dostarczenia konkretnej wiadomości przez konkretny kanał do konkretnego odbiorcy.

#### Delivery

Logiczny, idempotentny zamiar dostarczenia do odbiorcy/kanału. Może mieć wiele niezmiennych DeliveryAttempt.

### 2.4. Świadomie poza pierwszym rolloutem

Pierwsze fale nie muszą dostarczyć:

- pełnego omnichannel contact center,
- automatycznego speech analytics,
- globalnego indeksu wszystkich treści komunikacji,
- zewnętrznego customer support ticketingu,
- gwarancji exactly-once od zewnętrznego providera, który nie oferuje idempotencji,
- pełnego zastępstwa Outlook/Teams UI.

Muszą jednak zapewnić co najmniej once-safe processing z trwałym dedupe, reconciliacją i jawnie widocznym stanem `unknown`, gdy provider nie pozwala potwierdzić wyniku.

---

## 3. Źródła dowodowe i ograniczenia

### 3.1. Stan repozytorium

Głęboki audyt wykonano na czystym eksporcie bazowego commita:

~~~text
/tmp/nexus-module6-origin-77c7bde
~~~

Bazowy commit użyty do analizy:

~~~text
77c7bde155d309495a9aa79ea5220e6d9815bda5
feat(finance): FX bez nominalnego 1:1, trend/klienci, bench, filled_at, korekty (plan PR 6) (#783)
2026-07-16T15:06:46+02:00
~~~

Przed finalizacją ponownie wykonano `git fetch origin`. `origin/main` przesunął się o siedem PR-ów do:

~~~text
273cd08a19586003fff7ec577ca816c93c4fbc31
feat(workflow): semantic state registry + wersjonowane workflow w shadow mode (M4 plan PR-05) (#790)
2026-07-16T16:21:35+02:00
~~~

Przejrzano diff `77c7bde..273cd08`, obejmujący siedem merge'ów, w tym CI, `backend/app/main.py`, pipeline, jobs/candidates, rejection emails, engagement inventory, semantic-state/workflow registry oraz frontend Kanban/shortlist/CV share. Zmienił on jedno ustalenie P1: stage notification została przeniesiona za commit biznesowy, dlatego P1.13 opisuje teraz pozostałą lukę post-commit zamiast nieaktualnego ryzyka wysyłki przed commitem. Najnowsze zmiany rejection-email dodały access/redaction i template escaping, ale nie claim/provider reconciliation, więc P0.16 pozostaje aktualne. PR #790 dodał wersjonowane workflow wyłącznie w shadow mode; runtime jeszcze go nie konsumuje, dlatego nie zamyka ustaleń Modułu 6, lecz ustanawia upstream contract opisany w 2.2. CI dopisało łącznie sześć test files od baseline i nadal pomija 126 plików.

Lokalny checkout użytkownika pozostał oddzielną prawdą:

- branch: `wip/uncommitted-main-snapshot-2026-07-15`,
- HEAD: `297c151`,
- zawiera nieśledzone dokumenty z poprzednich audytów,
- nie został zresetowany, stashowany ani użyty jako dowód stanu produkcji.

Raport jest jedynym plikiem dodanym w ramach tej pracy.

### 3.2. Stan produkcji

Bezpośredni `GET https://api.nexus.dynaminds.pl/api/health` z wymaganym User-Agent zwrócił:

~~~json
{
  "status": "healthy",
  "version": "273cd08a19586003fff7ec577ca816c93c4fbc31",
  "deployedAt": "2026-07-16T14:22:26Z",
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

Podczas wcześniejszego re-checku poprzedniego deployu `fc75350` pierwszy
pojedynczy request z `curl -f` zwrócił HTTP 503 (body nie został zachowany przez
tryb fail-fast). Natychmiastowy odczyt body i trzy kolejne niezależne próby
zwróciły 200, `healthy` i SHA `fc75350`. Po ostatnim re-anchor deploy
`273cd08` odpowiedział 200/healthy za pierwszym odczytem. Epizod nie jest
dowodem trwałej awarii ani niespójnego wdrożenia, ale jest realnym transient
sygnałem do korelacji z logami edge/backend; raport nie ukrywa tej obserwacji.

Wniosek:

- wdrożony SHA dokładnie odpowiadał końcowemu `origin/main`,
- baza i M365 były zdrowe,
- CloudTalk był realnie uszkodzony,
- Traffit pozostawał degraded,
- globalne `healthy` nie oznacza zdrowia wszystkich kanałów komunikacyjnych.

### 3.3. Produkcyjny snapshot operacyjny

Chroniony `GET /api/admin/snapshot` pokazał:

~~~json
{
  "background_tasks": {
    "running": 17,
    "expected": 24,
    "tasks": [
      "calendar_reminder",
      "cc_centroid_sync",
      "chat_email_fallback",
      "cloudtalk_sync",
      "competition_autofreeze",
      "contract_alerts",
      "dl_portal_expiry",
      "fx_refresh",
      "m365_rematch",
      "marketplace_sweeper",
      "match_history_ttl",
      "microsoft365_sync",
      "notification_triggers",
      "rejection_email",
      "saved_search_alerts",
      "signing_sweeper",
      "traffit_sync"
    ]
  },
  "alembic": {
    "head": "0152_cv_generated_async_status",
    "applied_at": null
  }
}
~~~

Kod rejestruje 24 taski w `backend/app/main.py:429-455`. Brakujące siedem nazw to głównie workery, które kończą się poprawnie, gdy feature jest wyłączony lub nie ma konfiguracji:

- `slack_sla_alerts`,
- `kpi_coach_nudger`,
- `linkedin_sync`,
- `m365_webhook_renewal`,
- `m365_recording_discovery`,
- `autenti_sweeper`,
- `index_outbox`.

Dlatego `17/24` nie dowodzi siedmiu awarii. Dowodzi, że snapshot nie potrafi rozróżnić:

- intentionally disabled,
- completed,
- crashed,
- blocked by configuration,
- backing off,
- stale heartbeat.

Dodatkowe niespójności snapshotu:

- jego `deployedAt` wskazywał starą datę z maja, podczas gdy bezpośredni health wskazywał bieżący deploy,
- zawierał wyłącznie check bazy, nie pełne checki integracji,
- pokazywał pojedynczy Alembic head `0152`, podczas gdy repo ma migracje do `0176` i rozgałęzione heads,
- `_query_alembic_head()` używa `scalar_one_or_none()`, więc nie modeluje poprawnie wielu heads.

### 3.4. Produkcyjna kontrola UI

Kontrola była read-only i nie wykonywała wysyłki, mapowania, synchronizacji ani zmian danych.

#### Calendar

Zaobserwowano:

- widok miesięczny i tygodniowy,
- wiele eventów o generycznym tytule „Spotkanie”,
- powtarzające się eventy w tych samych godzinach,
- dane kandydatów i klientów w tytułach,
- typy interview, screening, prep call, meeting i deadline,
- akcje `iCal import` i `Nowe wydarzenie`.

Sam wygląd nie przesądza, czy duplikaty są błędne. Kod potwierdza jednak brak jednoznacznego feed ownership, recurrence model i bezpiecznego dedupe.

#### Powiadomienia

Dropdown zawierał wiele podobnych reminderów „Za 15 minut: Spotkanie” oraz alertów kontraktowych. Nie było widocznego pełnego centrum, filtrów, grupowania ani preferencji.

Brak badge sam w sobie nie dowodzi, że rekordy były nieprzeczytane. Kod jednoznacznie potwierdza jednak błąd `WHERE false` w obliczaniu unread count i mark-all.

#### Settings → Integracje

Zaobserwowano:

- Microsoft 365: połączony, świeży sync,
- Fireflies: błąd połączenia, sześć transkryptów, jednocześnie tekst „Jeszcze nie synchronizowano”,
- raw HTML tags wyświetlone jako tekst w tytułach/preview Fireflies,
- treści transkryptów i dane rekrutacyjne na globalnej stronie Settings,
- CloudTalk: błąd autoryzacji 401/403,
- Teams: brak kanałów,
- komunikat „LinkedIn, Slack...” jako „wkrótce”, mimo istniejącego backendu/workerów.

#### Candidate chat

Profil kandydata pokazywał historię, notatki, calls i Team chat z:

- członkami,
- reply,
- reactions,
- read state,
- delete,
- pin.

Nie było wspólnego zadania/follow-upu, a live update candidate chat jest obecnie blokowany przez literówkę protokołu w frontendzie.

### 3.5. Ograniczenia

- Nie wysłano realnego emaila, Teams message ani połączenia.
- Nie uruchomiono Fireflies/CloudTalk sync.
- Nie modyfikowano produkcyjnych settings i mappingów.
- Nie pobierano treści nagrań ani załączników.
- Wnioski o race conditions wynikają z analizy kodu i modelu transakcji, nie z destrukcyjnych prób równoległych na produkcji.
- Produkcyjne dane osobowe zaobserwowane w UI nie zostały skopiowane do raportu.

---

## 4. Obecny przepływ i źródła prawdy

### 4.1. Obecny outbound email ma kilka niezależnych dróg

~~~text
Candidate primary action
  -> SendEmailV2
  -> POST /api/emails/send
  -> log simulation
  -> Activity(email_sent, simulated=true)
  -> UI success
  -> brak zewnętrznej wiadomości

Candidate M365 components
  -> POST /api/candidates/{id}/emails/compose
  -> Graph send
  -> Email row

Pipeline rejection scheduler
  -> claim RejectionEmail
  -> Graph send
  -> local status/notification

Note mention / chat fallback / auth emails
  -> sync SMTP wrapper
  -> best-effort bool

Teams / Slack
  -> untracked asyncio task lub in-process loop
~~~

Każda ścieżka ma inny:

- model stanu,
- retry,
- dedupe,
- logowanie,
- politykę dostępu,
- sposób potwierdzania sukcesu,
- sposób pokazywania błędu w UI.

### 4.2. Obecne communication surfaces

#### Candidate

- legacy simulated email,
- gotowy, ale niepodpięty `EmailThreadList`,
- notes,
- calls/transcripts,
- candidate chat,
- timeline obcięty limitem,
- calendar/schedule interview z drugiego flow.

#### Job

- job chat,
- stage notification rules,
- Activity zapisane w backendzie,
- „Historia” w UI oznaczająca podobne requesty, nie audit timeline.

#### Client

- mutowalne pole notes,
- brak pełnego timeline/communication feed,
- osobne konfiguracje stage notifications.

#### User

- notification bell,
- WebSocket/presence,
- M365 connection,
- email templates,
- prawie brak preferencji kanałów.

### 4.3. Obecne modele historii

NEXUS ma równolegle:

- `Activity` — deklarowany audit trail, ale bez wymuszonej niezmienności i z raw JSON details,
- `UserActivity` — osobny licznik aktywności do KPI/leaderboard,
- `Note` — treść człowieka oraz importy Traffit/Fireflies,
- `ScreeningNote` — osobny model oceny,
- `CandidateStage` — część historii procesu,
- `Call` — osobny kanał,
- `Email` — osobny kanał,
- `JobChatMessage` i `CandidateChatMessage` — dwa prawie równoległe modele,
- `Notification` — read/unread projection i częściowo delivery marker.

Nie ma jednego globalnego cursora timeline ani stabilnego kontraktu widoczności.

### 4.4. Obecne automatyzacje

Lifespan startuje 24 taski, między innymi:

- calendar reminder,
- notification triggers,
- rejection email,
- chat email fallback,
- Slack SLA,
- Teams fire-and-forget w call sites,
- M365 poll/rematch/webhook renewal/recording discovery,
- CloudTalk sync,
- LinkedIn sync,
- Fireflies wyłącznie manualnie,
- contract/signing/saved-search/marketplace workers.

Nie istnieje wspólny kontrakt workera. Każdy sam wybiera:

- własny sleep interval,
- własny in-memory dedupe,
- własny watermark lub jego brak,
- własny sposób obsługi wyjątków,
- własny sposób raportowania lub całkowity brak raportowania.

---

## 5. Co już działa i należy zachować

Plan nie powinien usuwać wartościowych elementów:

1. Microsoft 365 ma realne connection, Graph client, delta sync, compose/reply i attachment pipeline.
2. Search email jest owner-scoped i paginowany.
3. HTML email jest sanitizowany przed zapisem.
4. Jinja używa `SandboxedEnvironment` i autoescape.
5. Candidate chat ma bulk serializer, pagination `before_id`, search, reactions, pins i soft delete.
6. Job chat ma dojrzały zestaw funkcji, który można przenieść do wspólnego Conversation bez utraty UX.
7. Note mentions są zapisywane w tej samej transakcji co notatka.
8. Calendar conflict endpoints mają ograniczone okno siedmiu dni i domyślnie scope bieżącego użytkownika.
9. ScheduleInterviewModal integruje M365, free/busy i conflict check.
10. Notification trigger catalogue pokrywa wiele ważnych sytuacji biznesowych.
11. Rejection email ma model statusu i retry — wymaga utwardzenia, nie wyrzucenia.
12. CloudTalk i M365 mają kill switche.
13. Healthcheck potrafi raportować M365, CloudTalk i Traffit.
14. UI używa React Query i ma podstawowy polling fallback.
15. Kandydacki chat ma resource membership zamiast całkowicie globalnego dostępu.
16. Path traversal przy pobieraniu attachmentu jest blokowany.
17. WebSocket sprawdza aktywność użytkownika.
18. M365 private category czyści body nowej wersji — brakuje tylko pełnego purge artefaktów.

Zachować API kompatybilność przez adaptery, ale nie utrzymywać legacy writerów po osiągnięciu parity.

---

## 6. Ustalenia P0 — bezpieczeństwo, prywatność i prawda o wykonaniu

### P0.1. UI potwierdza email, którego system nie wysłał

Dowody:

- `frontend/src/components/v2/pages/CandidateDetailV2.tsx:1007-1013,1339-1345`,
- `frontend/src/components/v2/modals/SendEmailV2.tsx:113-150`,
- `backend/app/api/emails.py:1-5,531-581`.

Backend:

- loguje `[EMAIL SIMULATION]`,
- nie wywołuje SMTP ani Graph,
- zapisuje `Activity(action="email_sent")`,
- zwraca 2xx i status `simulated`.

Frontend nie sprawdza semantyki odpowiedzi; każdy 2xx zmienia UI na sukces.

Naprawa containment:

1. Ukryć/wyłączyć `SendEmailV2` na produkcji.
2. Główną akcję Email skierować do realnego M365 compose.
3. Jeżeli M365 nie jest połączony, pokazać `draft/not connected`, nigdy success.
4. Endpoint legacy ma zwracać trwałe `410 Gone` z kodem `LEGACY_EMAIL_SIMULATION_DISABLED`; `503` rezerwujemy wyłącznie dla czasowo niedostępnej, realnej integracji.
5. Nie tworzyć `email_sent`; opcjonalny draft zapisać jako `email_draft_created`.
6. Dodać inventory historycznych `email_sent` z `details.simulated=true`.

Docelowy UI nie może sprowadzać wszystkich stanów do „wysłano”:

- lokalne `queued` → „Zakolejkowano”,
- provider `accepted` → „Dostawca przyjął zlecenie”, ale jeszcze nie „Dostarczono”,
- provider `sent` albo potwierdzony rekord w Sent Items → „Wysłano”,
- `delivered` → „Dostarczono” wyłącznie przy wiarygodnym receipt,
- `uncertain` → „Nie można potwierdzić wyniku — trwa weryfikacja”.

Każdy email ma lokalne `outbound_message_id` i `delivery_id`; provider truth wskazuje `provider_message_id`/receipt albo jawny powód jego braku. Generyczny `ProviderOperation` z 11.9a jest dla nie-emailowych komend providera i nie zastępuje email Delivery.

### P0.2. Preview legacy email zawiera fałszywe dane biznesowe

Dowód: `backend/app/api/emails.py:248-269`.

Niezależnie od wybranej rekrutacji preview podstawia m.in.:

- „Senior Java Developer”,
- datę z 2025 roku,
- twardo wpisane widełki,
- twardo wpisanego recruitera.

To nie jest neutralny placeholder. Użytkownik może wysłać lub skopiować nieprawdziwe warunki.

Naprawa:

- usunąć hardcoded business values,
- brak kontekstu ma pozostawić jawny unresolved token,
- wymagać job/offer context dla pól oferty,
- przed send zapisywać immutable render snapshot,
- blokować send przy unresolved required variables.

### P0.3. Access JWT znajduje się w URL WebSocketu

Dowody:

- `frontend/src/hooks/useNotifications.ts:85-100`,
- `backend/app/api/ws.py:367-390`.

URL ma postać:

~~~text
/ws/notifications?token=<pełny access JWT>
~~~

Ryzyka:

- access logs,
- reverse proxy logs,
- APM traces,
- diagnostyka przeglądarki,
- przypadkowe kopiowanie URL.

Naprawa rekomendowana:

1. Dodać `POST /api/realtime/ticket`.
2. Endpoint wymaga zwykłego auth i zwraca opaque, jednorazowy ticket.
3. Ticket ma TTL 30–60 s, audience `realtime`, hash w DB/Redis i atomowe consume.
4. Po upgrade połączenie jest związane z user/session/device.
5. Alternatywa: same-origin HttpOnly secure cookie, jeżeli architektura domen pozwala.
6. Nie przenosić długowiecznego JWT do `Sec-WebSocket-Protocol`, jeśli proxy go loguje; politykę trzeba jawnie zweryfikować.

### P0.4. Unread count i mark-all są logicznie wyłączone

Dowody: `backend/app/api/notifications.py:64-68,94-99,148-151`.

Kod używa:

~~~python
not Notification.is_read
~~~

`InstrumentedAttribute` jest truthy, więc Python oblicza `False` przed zbudowaniem SQL. Query dostaje `WHERE false`.

Skutki:

- unread count zawsze 0,
- mark-all nie aktualizuje żadnego rekordu,
- badge i akcje UI kłamią,
- fallback/digest mogą opierać się na innym stanie niż UI.

Naprawa:

~~~python
Notification.is_read.is_(False)
~~~

W tym samym PR dodać testy endpointów oraz test liczby zmienionych rows.

### P0.5. Renderer szablonu pozwala viewerowi enumerować PII kandydatów

Dowody:

- `backend/app/api/user_email_templates.py:33,137-150`,
- `backend/app/api/user_email_templates.py:272-294,342-402`.

Endpoint ma tylko `CurrentUser`, pobiera dowolnego `Candidate` po ID i wystawia do Jinja:

- email,
- telefon,
- location,
- LinkedIn,
- imię i nazwisko.

Viewer może utworzyć szablon z `{{ candidate.email }}` i renderować kolejne ID.

Containment:

- `CandidatePIIAccess` plus resource scope,
- osobna capability `communication.template.render`,
- allowlista pól zależna od kanału i celu,
- 404/403 bez oracle,
- rate limit i audit render access,
- shared templates tylko dla uprawnionej roli/moderacji.

### P0.6. Notes są globalnym, nieograniczonym źródłem PII

Dowody: `backend/app/api/notes.py:63-115,118-195,198-208`.

Problemy:

- brak wymagania `candidate_id` lub `job_id`,
- brak paginacji i maksymalnego zakresu,
- zwracanie author email,
- get po dowolnym `note_id`,
- create pozwala wskazać dowolnego candidate/job,
- brak sprawdzenia zgodności candidate z job,
- guard jest wyłącznie rolą, nie resource scope.

Containment:

- co najmniej jeden subject wymagany,
- `ResourceAccessService.can_read/write(subject)`,
- cursor pagination,
- redakcja author email do bezpiecznego display identity,
- walidacja powiązań,
- neutralna odpowiedź dla niedostępnego subjectu.

### P0.7. Calendar ujawnia i modyfikuje wszystkie eventy

Dowody:

- `backend/app/api/calendar.py:101-182,264-389`,
- `backend/app/api/recruitment_access.py:41-45`.

List/get zwracają:

- opis,
- attendee emails,
- candidate/job/client,
- Teams URL,
- recording URL,
- created_by.

Update/delete wymagają roli kalendarzowej, lecz nie ownership ani resource scope.

Containment:

- owner zawsze widzi własny event,
- uczestnik widzi projekcję zależną od visibility,
- job/client-linked event wymaga resource access,
- recording URL wymaga osobnej capability,
- cudzy private event ma busy-only projection,
- update/delete tylko organizer/delegate/admin break-glass,
- audit każdego odczytu nagrania i mutacji uczestników.

### P0.8. Import iCal jest SSRF i ma cross-user overwrite

Dowody:

- `backend/app/api/calendar.py:600-627`,
- `backend/app/services/ical_import.py:64-87,124-153`,
- testy `backend/tests/test_ical_import.py:1-57` nie obejmują fetch/security/upsert.

Problemy:

- dowolny `http/https/webcal`,
- `follow_redirects=True`,
- brak blokady loopback, private, link-local i metadata IP,
- brak ponownej walidacji IP po redirect,
- brak limitu response bytes/event count,
- `source_tag` kontrolowany przez użytkownika,
- upsert tylko po `(external_source, external_id)`, bez owner/feed,
- publiczny iCal URL jest sekretem i wraca w response.

Naprawa:

1. Encja `CalendarFeed(owner_id, encrypted_url, url_fingerprint, status)`.
2. HTTPS-only poza jawnie testowym środowiskiem.
3. Resolver DNS i IP policy przed każdym requestem/redirectem.
4. Zakaz loopback/RFC1918/link-local/metadata/ULA.
5. Limit redirectów, bytes, content type, VEVENT count i czasu.
6. Unique `(feed_id, external_uid)`.
7. Nigdy nie zwracać pełnego URL; wyłącznie masked host/fingerprint.

### P0.9. Viewer może wysyłać email przez realny M365 compose

Dowody: `backend/app/api/email_threads.py:324-342,424-449,523-584`.

Compose, reply i bulk mają tylko `CurrentUser`. Brakuje:

- capability write,
- candidate/job scope,
- polityki dozwolonych recipientów,
- server-side potwierdzenia, że kandydat ma związek z kontekstem,
- audytu wysyłki i linkowania.

Naprawa:

- `OperationalCommunicationWrite`,
- resource scope,
- mailbox ownership/delegation,
- recipient normalization i allow/deny policy,
- rate limit per user/mailbox,
- immutable outbound request + idempotency key,
- viewer zawsze 403.

### P0.10. Cudze skrzynki są domyślnie czytelne dla admin/DL

Dowody: `backend/app/api/email_threads.py:145-149,181-321`.

`_can_access_email` pozwala adminowi i delivery leadowi czytać pełną treść oraz pobierać załączniki każdej skrzynki.

Nie ma:

- delegacji właściciela,
- scope klienta/rekrutacji,
- czasu wygaśnięcia,
- powodu,
- break-glass audytu.

Naprawa:

- owner-only domyślnie,
- `MailboxDelegation(owner, delegate, scope, expires_at, reason)`,
- break-glass tylko z powodem i alertem do security ownera,
- natychmiastowe cofnięcie,
- osobna polityka dla matched candidate projection bez ujawniania całej skrzynki.

### P0.11. Calls, CloudTalk i Fireflies omijają object-level access

Dowody:

- `backend/app/api/calls.py:74-110`,
- `backend/app/api/cloudtalk.py:123-288,291-397`,
- `backend/app/api/fireflies.py:22-89`.

Skutki:

- dowolny zalogowany user może czytać calls/transcript/recording dowolnego kandydata,
- zwykły user może dodać ręczny Call,
- zwykły user może przepiąć CloudTalk agent↔user,
- po self-assignment może inicjować call,
- dowolny user może uruchomić globalny Fireflies sync przez mutujący GET,
- globalne meeting previews są dostępne bez owner/team scope.

Containment:

- CloudTalk agent admin: istniejący `AdminUser`; przyszła capability `integration.manage` może go zastąpić dopiero po pełnej mapie siedmiu ról,
- calls/dial: candidate resource access i osobna capability,
- Fireflies sync: POST + istniejący `AdminUser` + rate limit; nie wprowadzać fikcyjnej roli `integration-manager`,
- transcripts/recordings: owner/resource visibility,
- nagranie wyłącznie przez autoryzowany proxy lub krótki signed URL,
- audit odtworzenia/pobrania.

### P0.12. Sekret CloudTalk występuje w URL webhooka i nie ma replay protection

Dowody:

- `backend/app/api/calls.py:459-527`,
- `backend/app/services/cloudtalk/webhook_verify.py:19-34`.

Problemy:

- `/calls/webhook/{token}` może trafić do access logs,
- HMAC obejmuje body, ale nie timestamp,
- brak trwałego event ID/dedupe,
- poprawny request można odtwarzać,
- body nie ma bezpiecznego limitu.

Naprawa:

1. Usunąć secret z path.
2. Obrócić sekret po deployu.
3. Podpis header `timestamp.body`, tolerance window.
4. Durable webhook inbox z unique provider event ID lub hash+timestamp.
5. Limit body i content type.
6. Po rotacji sprawdzić politykę retencji logów proxy/APM.

### P0.13. CloudTalk może przypisać prywatny transkrypt do złego kandydata

Dowody:

- `backend/app/api/calls.py:352-363`,
- `backend/app/tasks/cloudtalk_sync.py:85-97`.

Lookup używa ostatnich dziewięciu cyfr i `.limit(1)`. Współdzielony numer, błędny import lub duplikat wybiera arbitralny rekord.

Naprawa:

- znormalizowany E.164 z quality state,
- wynik `matched`, `ambiguous`, `unmatched`,
- przy wielu wynikach zakaz auto-link i Champion enrichment,
- review queue z audytem ręcznej decyzji,
- backfill inventory kolizji przed włączeniem automatu.

### P0.14. Recording discovery może podpiąć niewłaściwe nagranie

Dowody:

- `backend/app/services/m365/onedrive.py:138-154,180-215`,
- `backend/app/tasks/microsoft365_sync.py:559-582`.

Fallback wybiera najbliższy plik MP4 w szerokim oknie czasu, gdy nie ma silnego meeting ID. Dwa nakładające się spotkania mogą ujawnić treść przy złym kandydacie.

Naprawa:

- wymagany provider recording/meeting identity,
- time-only match co najwyżej `suggested`, nigdy auto-attached,
- ambiguity queue,
- jawny reviewer i audit,
- późniejsze otwarcie przez capability-protected artifact gateway.

### P0.15. M365 webhook zwraca 202 przed trwałym zapisaniem pracy

Dowody: `backend/app/api/microsoft365.py:408-439,447-557`.

Obecnie:

1. in-memory cache oznacza notification jako seen,
2. `asyncio.create_task` planuje pracę,
3. endpoint zwraca 202,
4. restart może zgubić całość.

Dodatkowo klucz resource ID blokuje prawidłowe kolejne zmiany przez długi czas.

Naprawa:

- `GraphWebhookInbox` zapisany i committed przed 202,
- unique notification ID lub canonical hash,
- coalescing dirty generation per connection/resource, nie 24h discard,
- worker z lease/retry/DLQ,
- replay/reconciliation przez delta sync.

### P0.16. Outbound/rejection email ma crash gap i race z cancel

Dowody:

- `backend/app/services/m365/sender.py:137-195`,
- `backend/app/services/rejection_email_scheduler.py:179-257,309-337`,
- `backend/app/api/rejection_emails.py:121-168`.

Provider może zaakceptować send przed lokalnym insertem lub commitem. Crash powoduje retry i potencjalny duplikat. Cancel nie używa CAS i może wygrać z równoległą wysyłką.

Naprawa:

- trwały `OutboundMessage` przed providerem,
- local state machine `draft -> queued -> dispatching -> completed/failed/uncertain` oraz oddzielny provider state `not_requested -> accepted -> sent/delivered/bounced/unknown`,
- provider draft/operation ID,
- warunkowe `UPDATE ... WHERE status/version`,
- reconciliation z Sent Items,
- cancel tylko przed nieodwracalnym provider transition,
- status `unknown` zamiast zgadywania po crashu.

### P0.17. Private/delete M365 nie usuwa wcześniej zapisanych artefaktów

Dowody:

- `backend/app/services/m365/sync.py:334-338,357-379,441-464`,
- `backend/app/services/m365/attachment_handler.py:181-192`.

Zmiana kategorii na private czyści body i nie pobiera nowych załączników, ale stare:

- rows,
- pliki,
- parse results,
- ewentualne candidate enrichment

mogą pozostać. Graph `@removed` usuwa Email row, ale nie ma jawnego protokołu usunięcia pliku.

Naprawa:

- idempotentny artifact purge outbox,
- tombstone przed fizycznym purge,
- retry i DLQ,
- usunięcie/odpięcie derived search/CV artifacts,
- legal hold exception,
- test bytes-on-disk po public→private i `@removed`.

---

## 7. Ustalenia P1 — poważne błędy funkcjonalne i niezawodności

### P1.1. Nie istnieje kanoniczny Task/Follow-up

Repo nie ma domenowego modelu zadania. `backend/app/api/candidates_bulk.py` wprost stwierdza, że NEXUS nie ma Task model.

Obecne substytuty:

- notification `is_read`,
- screening note type `follow_up`,
- `JobShortlistEntry.next_action_at`,
- calendar event,
- free-form notes,
- alert z terminem,
- pola statusowe w pojedynczych modułach.

Żaden z nich nie ma kompletnego:

- assignee,
- ownera/reportera,
- due date i timezone,
- statusu pracy,
- completion/cancellation,
- snooze,
- recurrence,
- escalation,
- optimistic concurrency,
- audytu.

Notification read nie może oznaczać wykonania zadania. Docelowo notification może prowadzić do WorkItem, ale ich stany pozostają niezależne.

### P1.2. Candidate chat i presence nie dostają live events

Dowody:

- `frontend/src/hooks/useNotifications.ts:209-241`,
- `backend/app/api/candidate_chat.py:300-312,353-363`,
- `backend/app/api/ws.py:277-284`.

Frontend sprawdza:

~~~typescript
startsWith("candidate-chat:message: ")
startsWith("presence: ")
~~~

Backend emituje bez końcowej spacji:

~~~text
candidate-chat:message:new
presence:update
~~~

HTTP snapshot presence może wyglądać poprawnie, lecz kolejne zmiany nie przechodzą przez bus. Naprawa nie powinna polegać wyłącznie na usunięciu dwóch spacji. Potrzebny jest współdzielony, wersjonowany discriminated union i contract test emitter↔decoder.

### P1.3. Presence ma IDOR i ujawnia zbyt wiele danych

Dowody:

- `backend/app/api/presence.py:22-33`,
- `backend/app/api/ws.py:346-364`,
- `backend/app/api/ws.py:256-284`.

Każdy authenticated user może subskrybować dowolny `candidate:{id}` lub `job:{id}`. Payload zawiera:

- imię,
- email,
- rolę,
- pola aktualnie edytowane,
- timestamp wejścia.

Naprawa:

- ten sam ResourceAccessService dla HTTP i WS,
- sprawdzenie przy subscribe oraz przed każdym broadcastem,
- natychmiastowe odcięcie po revocation,
- minimalny payload bez emaila,
- allowlista nazw pól lub ogólne `editing=true`,
- privacy setting dla obecności.

### P1.4. WebSocket/presence jest proces-local

`ConnectionManager` przechowuje connections, subscriptions i presence w singletonowych dictach.

Skutki przy wielu replikach:

- użytkownik A i B na różnych replikach nie widzą się,
- notification wysłane przez inną replikę nie trafia do socketu,
- restart usuwa presence,
- admin snapshot nie pokaże realnej liczby połączeń klastra.

Docelowo:

- Redis/pub-sub lub dedykowany realtime gateway,
- presence TTL/heartbeat,
- committed event z sequence/cursor,
- reconnect wykonuje replay albo pełną reconciliację,
- WebSocket pozostaje transportem, nie źródłem prawdy.

### P1.5. Mention generuje dwie notyfikacje i potencjalnie dwa emaile

Dowody:

- `backend/app/api/job_chat.py:249-284`,
- `backend/app/api/candidate_chat.py:266-295`,
- `backend/app/tasks/chat_email_fallback.py:41-45`.

Mentionowany user należy też do zwykłych odbiorców, więc dostaje:

- `job_chat_message`,
- `job_chat_mention`.

Fallback obsługuje oba typy.

Inwariant docelowy:

> Dla jednego message i recipient mention zastępuje general message notification.

Wymagany unique delivery key i test dwóch workerów.

### P1.6. Edycja wiadomości nie powiadamia o nowej wzmiance

Dowody:

- `backend/app/api/job_chat.py:304-354`,
- `backend/app/api/candidate_chat.py:316-364`.

Kod usuwa i odtwarza mention rows, lecz nie oblicza diffu i nie tworzy notification/outbox dla nowych osób. Użyć wzorca diffu z `notes.py:227-283`, ale dostarczyć go przez durable outbox.

### P1.7. Chat nie jest idempotentny i ma check-then-insert races

Problemy:

- create nie ma `client_message_id`,
- podwójny submit/retry tworzy dublet,
- pin limit jest liczony przed zapisem,
- read state i reaction robią select-then-insert,
- concurrent requests mogą naruszyć semantykę.

Dowody:

- `backend/app/api/job_chat.py:197-298,429-446,534-558,648-666`,
- `backend/app/api/candidate_chat.py:219-313,422-439,531-553,638-655`.

Naprawa:

- unique client message ID per conversation/author,
- atomic upsert reaction/read cursor,
- pin pod blokadą conversation lub constraint/service,
- version/If-Match dla edit,
- testy concurrent.

### P1.8. Membership candidate chat nie zgadza się z własną dokumentacją

`backend/app/services/candidate_membership.py:1-10` deklaruje, że autor wcześniejszej wiadomości pozostaje członkiem. Implementacja `is_member_of_candidate_chat()` i lista memberów nie dodają autorów historycznych.

Dodatkowo:

- admin check w jednej ścieżce używa primary role, nie multi-role,
- owner/collaborator IDs nie są wszędzie filtrowane po aktywności,
- notification może zostać skierowana do nieaktywnego usera,
- zmiana pipeline może odebrać autorowi dostęp do własnego wątku bez jawnej polityki.

Należy zdecydować politykę, zakodować ją w jednym resolverze i przetestować revocation/retention.

### P1.9. Deep linki komunikacyjne nie dochodzą do celu

Chat generuje:

~~~text
?tab=chat&msg=<id>
~~~

UI wybiera tab, ale nie:

- pobiera okna zawierającego message,
- scrolluje,
- ustawia focus,
- highlightuje,
- pokazuje deleted/forbidden/not-found.

Calendar reminder/feedback link `?event=N&action=feedback` działa tylko przez specjalny click w otwartym bell. Cold load, refresh i link z emaila nie ustawiają tygodnia ani nie otwierają celu.

Wymagany canonical deep-link resolver z testami cold load/refresh.

### P1.10. Notification center jest tylko dropdownem 20 rekordów

Dowody:

- `frontend/src/components/NotificationsDropdown.tsx:206-216`,
- `backend/app/api/notifications.py:49-85`.

Brakuje:

- cursora,
- filtrowania,
- kategorii/family,
- archiwizacji,
- pełnego inboxu,
- batch actions z wynikiem,
- expires/retention,
- preferences,
- quiet hours,
- digest.

Sort unread-first może powodować, że starsze unread wypychają najnowsze read z limitu 20.

### P1.11. Enum powiadomień i prezentacja frontendu są rozjechane

Backend ma około czterdziestu typów w `backend/app/models/notification.py:12-112`. Frontend mapuje mały podzbiór w `NotificationsDropdown.tsx:43-132`.

Unknown type podszywa się pod `candidate_added`, co daje fałszywą ikonę i znaczenie.

Docelowo:

- wersjonowany registry event/notification family,
- exhaustive TypeScript mapping z compile-time `never`,
- bezpieczny generic fallback, nie „candidate added”,
- semantic design tokens,
- test zgodności wszystkich typów.

### P1.12. Notification dedupe ma zły klucz i ryzyko race

Dowody:

- `backend/app/models/notification.py:143-147`,
- `backend/app/api/notifications.py:190-207`,
- `backend/alembic/versions/0029_notifications_triggers.py:90-100`.

Problemy:

- unique index nie zawiera `related_entity_type`,
- ID z różnych tabel może się zderzyć,
- helper robi read-then-write,
- business day/timezone jest niespójny,
- chat celowo nie ma entity ID i dedupe.

Zastąpić to jawnym `dedupe_key` albo unique:

~~~text
(event_id, recipient_user_id)
~~~

oraz osobnym throttle policy dla agregowanych alertów.

### P1.13. Stage notification jest już po commicie, ale nadal może zostać bezpowrotnie zgubiona

Stan bazowy `77c7bde` wykonywał stage email przed commitem biznesowym. PR #784, obecny w końcowym `origin/main`, przeniósł `notify_stage_change` za commit i tym samym usunął ryzyko maila o wycofanym ruchu.

Pozostały problem w `backend/app/api/pipeline.py`:

- notification/email jest synchronicznym, post-commit `best-effort`,
- wyjątek jest logowany i połykany,
- nie powstaje trwały outbox row,
- restart lub timeout po commicie może bezpowrotnie zgubić komunikat,
- retry ruchu nie może już bezpiecznie powtórzyć tej samej operacji bez business idempotency key.

Docelowo commit ruchu musi atomowo zapisać DomainEvent/OutboxItem. Provider delivery ma wykonać leased worker z retry i reconciliation. PR #784 należy zachować jako poprawny containment, nie cofać go.

### P1.14. Notification WebSocket może pojawić się przed trwałym commitem

Dowody:

- `backend/app/services/notification_triggers.py:79-119`,
- `backend/app/tasks/triggers_loop.py:38-55`.

Użytkownik może zobaczyć ghost notification. Broadcast ma być projekcją committed notification/outbox row.

### P1.15. Slack uznaje błędną odpowiedź HTTP za sukces

Dowód: `backend/app/tasks/slack_sla_alerts.py:83-127`.

Brak `raise_for_status()`. Alert jest zapamiętany w RAM jako wysłany także przy 4xx/5xx. Restart z kolei resetuje set i może zdublować wszystkie alerty.

Naprawa: wspólny `Delivery`, append-only `DeliveryAttempt`, provider status, backoff, DLQ i durable dedupe.

### P1.16. Teams jest fire-and-forget

Dowody:

- `backend/app/services/teams_notifications.py:402-423,478-530`,
- call sites w candidates/pipeline/contracts.

`asyncio.create_task` jest nieśledzone. Restart gubi message, retry endpointu może go zdublować, błędy są połykane.

Payloady zawierają dane candidate/client/decision, ale endpoint nie ma centralnej klasyfikacji kanału. Teams musi przejść na outbox i `DeliveryEndpoint.max_data_classification`.

### P1.17. SMTP i mention delivery nie są trwałe

Dowody:

- `backend/app/services/mention_dispatch.py:107-221`,
- `backend/app/services/email.py:41-75`.

Wysyłka po commicie jest lepsza niż przed commitem, ale nadal:

- błąd jest połykany,
- brak retry/DLQ,
- brak provider ID,
- synchroniczny SMTP jest blokujący,
- brak preference/quiet hours,
- brak ponownej autoryzacji recipienta.

### P1.18. SMTP nie ma jawnej polityki fail-closed TLS

`backend/app/services/email.py:65-70` wywołuje `starttls()` bez jawnego `ssl.create_default_context()` i bez obowiązkowej polityki `SMTP_REQUIRE_TLS`.

Niezależnie od wersji biblioteki produkcyjny kontrakt powinien wprost wymuszać:

- weryfikację CA/hostname,
- STARTTLS lub SMTPS,
- brak fallbacku do plaintext,
- redakcję błędów i credentiali.

### P1.19. M365 delta cursor może przeskoczyć uszkodzony element

Dowody:

- `backend/app/services/m365/sync.py:298-316`,
- analogiczna ścieżka kalendarza `:519-542`.

Błąd pojedynczego itemu jest łapany, ale cursor strony może zostać przesunięty. Wiadomość/event może zostać trwale zgubiony.

Naprawa:

- raw item inbox/poison queue,
- cursor dopiero po trwałym przyjęciu każdego itemu,
- replay i manual repair,
- widoczny poison count.

### P1.20. Identyfikator Graph message jest globalny zamiast mailbox-scoped

Dowody:

- `backend/app/models/m365.py:149-180`,
- `backend/app/services/m365/sync.py:319-338`.

Lookup po samym `m365_message_id` może zaktualizować lub usunąć rekord innego mailboxa przy kolizji. Unikalność powinna być:

~~~text
(mailbox_owner_id, provider_message_id)
~~~

To samo dotyczy external calendar identity.

### P1.21. Outbound M365 ma wadliwy fingerprint idempotencji

Dowód: `backend/app/services/m365/sender.py:65-196,307-381`.

Fingerprint pomija istotny kontekst, a check→Graph→insert nie jest atomowy. Dwie różne wiadomości mogą zostać stłumione albo jeden retry może zostać wysłany dwukrotnie.

Wymagany caller-supplied business `Idempotency-Key` i persisted outbound state przed provider call.

### P1.22. PKCE verifier M365 znajduje się w podpisanym, ale czytelnym state

Dowód: `backend/app/services/m365/oauth.py:89-98`.

Podpis nie szyfruje JWT. State wraca w URL callbacku, więc verifier może trafić do logów. Przechowywać verifier server-side pod losowym, jednorazowym nonce z TTL i atomowym consume.

### P1.23. Kalendarz ma dwa sprzeczne flow tworzenia wydarzenia

Generic `/calendar` tworzy local event przez `/calendar/events`, ma ręczne attendees/link i nie musi użyć M365/free-busy.

Candidate `ScheduleInterviewModal` używa:

- M365 invite,
- free/busy,
- local conflicts,
- Teams meeting.

Interview utworzony z głównego Calendar może ominąć te gwarancje. Oba entrypointy muszą wywoływać jeden `SchedulingCommandService` z jawną provider policy.

### P1.24. Calendar reminders są nietrwałe i ignorują `reminder_minutes`

Dowody: `backend/app/api/calendar.py:731-800`.

Worker:

- skanuje stałe okno 14–16 min,
- zawsze pisze „Za 15 minut”,
- ignoruje wartość eventu,
- pamięta IDs tylko w set,
- dodaje ID przed sukcesem `_send_reminder`,
- uruchamia untracked task,
- po 1000 czyści cały set,
- nie wykonuje catch-up.

Potrzebny `ReminderSchedule` i outbox delivery.

### P1.25. Notification triggers gubią zdarzenia po downtime i w weekend

Dowody:

- `backend/app/services/notification_triggers.py:519-538`,
- `backend/app/tasks/triggers_loop.py:40-44`.

Wąskie okna ±7,5 min oraz globalny weekend skip oznaczają trwałe pominięcie po restarcie lub krótkiej przerwie.

Każda obligation ma persisted `due_at`; worker wybiera `due_at <= now AND delivery missing` i stosuje jawną politykę business calendar per rule.

### P1.26. iCal nie modeluje recurrence, timezone i deletion

Poza SSRF import:

- nie ma trwałego feed cursor/status,
- floating datetime jest traktowany jak UTC,
- all-day staje się zwykłym eventem,
- RRULE nie ma occurrence model,
- EXDATE/RECURRENCE-ID nie tworzą pełnej semantyki,
- usunięty event nie jest reconciliowany,
- source URL ownership nie istnieje.

Rozwiązaniem jest `CalendarFeed` + `ExternalEvent` + occurrence expansion w bounded horizon, nie dokładanie wyjątków do obecnej funkcji.

### P1.27. Free/busy mapuje unknown na „wolne”

Dowody: `frontend/src/components/calendar/ScheduleInterviewModal.tsx:136-221`.

Błędy/nieznany attendee są ukrywane lub mapowane do pustej listy, po czym UI może pokazać zielone „Oba terminy wolne”.

Potrzebny tri-state:

- `free`,
- `busy`,
- `unknown`.

Success wyłącznie, gdy każdy wymagany attendee ma kompletną, jawną odpowiedź free.

### P1.28. Actionable interview confirmation ma niespójny kontrakt HTTP

Dowody:

- `backend/app/services/m365/actionable_messages.py:145-175`,
- `backend/app/api/public_interview_confirmation.py:45-72,111-123`.

Karta/fallback prowadzi GET, endpoint przyjmuje tylko POST. Token jest długowieczny w query URL, a klient może podać źródło potwierdzenia.

Naprawa:

- GET tylko do landing page,
- mutacja POST z CSRF-safe flow,
- opaque, single-use, hashed token,
- revoke po reschedule/cancel,
- source ustalany server-side.

### P1.29. CloudTalk poller nie robi deklarowanego catch-up

Dowody: `backend/app/tasks/cloudtalk_sync.py:85-117,150-257`.

Problemy:

- wymaga phone zanim spróbuje znaleźć istniejący call,
- późny transcript bez phone nie uzupełnia stuba,
- status `initiated` może pozostać,
- globalny `MAX(started_at)` bez overlap gubi late arrivals,
- page error może wyglądać jak sukces,
- deklarowane Champion enrichment nie jest pewnie wykonywane.

Wymagany upsert najpierw po `cloudtalk_call_id`, potem candidate resolution, persisted overlap watermark i per-run status.

### P1.30. Fireflies nie ma trwałego konta, cursora ani stanu

Dowody:

- `backend/app/services/fireflies_sync.py:20-28,313-345`,
- `backend/app/models/note.py:45-51,88-102`.

Status jest w RAM, brak workera w lifespan, `source_ref` nie daje atomowego unique, a check-then-insert może zdublować transcript i LLM enrichment.

Potrzebne `IntegrationConnection`, owner/team visibility, unique external ID, leased scheduler, retention i quarantine dla ambiguous match.

### P1.31. LinkedIn/Proxycurl ma niekontrolowany retry i fałszywy success watermark

Dowody:

- `backend/app/services/proxycurl/client.py:108-137`,
- `backend/app/services/proxycurl/sync.py:119-128`,
- `backend/app/tasks/linkedin_sync.py:57-99`.

Retry 429/503 nie ma właściwego limitu, transient error może ustawić `linkedin_synced_at`, a kolejna próba nastąpi dopiero po długim okresie. Bez lease repliki mogą wykonać podwójny płatny request.

### P1.32. Activity feed ujawnia raw details

Dowód: `backend/app/api/activities.py:223-273`.

Globalny feed zwraca `details` wszystkich Activity użytkownikom operacyjnym. Producenci mogą zapisywać:

- email,
- IP,
- signer identity,
- provider errors,
- dane security flow.

Rozdzielić:

- `SecurityAuditEvent` admin/security-only,
- redacted `TimelineProjection`,
- KPI `UserActivityProjection`.

Surowy JSON nigdy nie powinien automatycznie trafiać do UI.

### P1.33. Historia komunikacji jest fragmentaryczna

Candidate ma notes, calls, chat, timeline i orphaned email inbox w różnych miejscach. Client nie ma pełnego timeline. Job „Historia” nie jest audit history.

Potrzebny jeden cursor-based read model per resource, który pokazuje:

- immutable system events,
- messages,
- notes/comments,
- tasks,
- calendar changes,
- delivery state,

z kontrolowanym summary i linkiem do szczegółu.

### P1.34. Gotowy M365 inbox jest orphanem

`frontend/src/components/emails/EmailThreadList.tsx` ma thread list/search/compose, lecz nie jest używany w żadnym ekranie. Tymczasem primary Email prowadzi do symulatora.

Wpiąć komponent do Candidate Communication Hub i dopiero po tym usunąć legacy modal. Użytkownik musi widzieć connected/reconnect/partial-sync/provider-error state.

### P1.35. Worker registry nie odróżnia disabled od crashed

Dowody:

- `backend/app/main.py:429-455`,
- `backend/app/api/admin_snapshot.py:96-106`.

Task jest „running”, jeśli `not task.done()`. Nie ma:

- declared enabled state,
- exit reason,
- exception,
- heartbeat,
- last success,
- next due,
- lease owner,
- backlog,
- oldest item age,
- restart policy.

Skill/runbook „15 background tasks” jest już nieaktualny wobec 24 rejestrowanych tasków, co potwierdza drift operacyjnej dokumentacji.

### P1.36. Wszystkie background loops startują na każdej replice

Każda instancja aplikacji uruchamia własne 24 taski. Niektóre mają in-memory dedupe, inne w ogóle nie mają claim. To systemowe źródło duplicate side effects.

Docelowo każdy worker musi być:

- stateless względem pamięci procesu,
- oparty o DB/queue lease,
- fencing-safe,
- idempotentny,
- obserwowalny,
- restart-safe.

### P1.37. Shutdown może przerwać cleanup na wcześniej zakończonym wyjątku

`backend/app/main.py:460-469` przy await tasków obsługuje tylko `CancelledError`. Task zakończony innym wyjątkiem może przerwać pętlę przed `engine.dispose()`.

Supervisor powinien zbierać result/exception każdego taska, a shutdown używać bezpiecznego gather z niezależną obsługą błędów.

### P1.38. Semantic key upstream workflow może przeczyć terminalności etapu

Końcowy PR #790 wprowadził wspólny rejestr semantyczny i shadow
`StageRevision`. Obecny validator sprawdza istnienie `semantic_key`, ale nie
spójność z `StageRevision.is_terminal/terminal_type`. Można więc opublikować
`hired` jako nieterminalny albo `on_hold` jako terminalny. Stage-aware WorkItem
lub AutomationRule wyprowadziłby wtedy obowiązek z wewnętrznie sprzecznego
kontraktu.

Przed jakimkolwiek odczytem runtime Moduł 4 musi egzekwować i testować:

~~~text
stage.is_terminal == SEMANTIC_STATES[stage.semantic_key].is_terminal
stage.terminal_type == SEMANTIC_STATES[stage.semantic_key].terminal_type
~~~

Dla nieterminalnego semantic state oba źródła terminal type muszą być `NULL`.
Moduł 6 nie implementuje drugiego validatora jako konkurencyjnej prawdy; blokuje
stage-aware source, dopóki upstream gate nie jest wdrożony.

### P1.39. `published` workflow oznacza dziś shadow parity, nie runtime readiness

Bootstrap PR #790 od razu tworzy rewizję `published`, może pozostawić etapy
`unmapped` i buduje pełny digraf dla zgodności z legacy, również relacje, które
nie są docelową polityką przejść. Sam status `published` nie może więc aktywować
AutomationRule ani WorkItem.

Moduł 4 musi dostarczyć osobny, audytowany gate, np. `runtime_status =
shadow|eligible|retired` z `validated_at`, registry version i command-service
cutover. `eligible` wymaga zera unmapped, spójności semantyki/terminalności,
walidowanego grafu oraz działającego transition-event contractu. Publikacja
nowej rewizji nie przepina istniejących reguł ani historycznych WorkItem;
`follow future revisions` wymaga nowej walidacji i akceptacji.

### P1.40. WorkflowEdge nie ma jeszcze pełnej integralności potrzebnej automatyzacjom

W PR #790 DB nie gwarantuje, że `from_stage_revision_id` i
`to_stage_revision_id` należą do `workflow_revision_id` z tego samego edge.
Ponadto zwykły unique z nullable `from_stage_revision_id` nie blokuje
zduplikowanych entry edges.

Przed runtime adoption wymagane są:

- composite FK `(stage_revision_id, workflow_revision_id)` dla obu końców,
- partial unique `(workflow_revision_id, to_stage_revision_id) WHERE
  from_stage_revision_id IS NULL`,
- validator odrzucający endpoint spoza rewizji,
- preflight istniejących kolizji oraz migration/entrypoint mirror/test.

Do czasu tego gate stage-aware projekcje Modułu 6 pozostają wyłącznie
`shadow_observed`.

---

## 8. Ustalenia P2/P3 — UX, wydajność, retencja i testy

### P2.1. Błąd API jest prezentowany jako pusty zbiór

Przykłady:

- bell ignoruje `isLoading/isError` i pokazuje „Brak powiadomień”,
- Candidate Chat dla większości błędów pokazuje empty,
- Calendar ignoruje error list/conflict,
- Teams 403 może wyglądać jak „brak kanałów”,
- Fireflies/M365 mutations nie mają pełnego onError.

Każdy ekran musi rozróżniać:

- loading,
- initial empty,
- filtered empty,
- stale/revalidating,
- offline/degraded,
- forbidden,
- not found/deleted,
- rate limited,
- server error,
- mutation error z rollback.

### P2.2. Bell nie jest dostępny klawiaturą i na mobile

Dowód: `frontend/src/components/NotificationsDropdown.tsx:158-173,280-357`.

Problemy:

- toast close bez accessible label,
- toast nie prowadzi do linku,
- clickable `li`, nie button/link,
- brak popover/dialog semantics,
- brak Escape/focus management,
- stałe `w-96`,
- brak mobile Sheet.

### P2.3. Chat actions są hover-only

Candidate i Job Chat chowają akcje przez `opacity-0 group-hover`. Na touch i keyboard są trudne lub niemożliwe. Potrzebne:

- accessible action menu,
- `group-focus-within`,
- stały touch affordance,
- confirm dla delete,
- labels inputów,
- zachowanie scroll anchor przy doładowaniu.

### P2.4. Calendar nie ma mobilnej agendy

Obecny sztywny 7-column layout z sidebarem i wysokością viewportu nie skaluje się do 320–390 px. Potrzebny:

- mobile agenda/day,
- responsive filter Sheet,
- dostępne event buttons,
- bezpieczny overflow,
- widoczny timezone.

### P2.5. Generic Calendar wyszukuje tylko pierwszych 100 kandydatów

`frontend/src/app/calendar/page.tsx` pobiera `page_size: 100`, a state `job_id` nie ma pełnego pola wyboru. Kandydat poza pierwszą stroną jest niewidoczny.

Użyć server-side searchable combobox z cursor, resource access i canonical subject selection.

### P2.6. Calls/recording UI zakłada publiczny URL

`frontend/src/components/calls/AudioPlayer.tsx` używa raw URL i otwiera go w nowej karcie. Nie stosuje authenticated fetch→blob ani artifact proxy.

Recording URL może wygasnąć lub ujawnić dostęp. Docelowy UI pobiera short-lived handle z backendu, pokazuje consent/retention/access status i nie utrwala provider URL.

### P2.7. CallButton obiecuje tel fallback, ale go nie wykonuje

Komentarz opisuje fallback, lecz catch kończy się toastem. Po udanym initiate nie ma pełnej invalidacji/pollingu live call state.

### P2.8. Fireflies link prowadzi do niekanonicznej trasy

Settings buduje `/candidates?id=<id>`, podczas gdy canonical profil to `/candidates/<id>`. Link nie otwiera właściwego kandydata.

### P2.9. Fireflies renderuje raw HTML jako tekst

Produkcyjne tytuły/preview pokazały znaczniki `<p>`. Należy budować plain-text title/preview server-side i nigdy nie pokazywać globalnych transcript snippets w admin settings bez konieczności.

### P2.10. Integration Settings miesza personal i admin

Tab Integracje jest widoczny szeroko i montuje M365, Fireflies, CloudTalk i Teams razem.

Docelowo:

- Personal integrations: moja skrzynka, mój status, moje reconnect,
- Admin integrations: provider accounts, mappings, channels, workers, incidents,
- UI renderowane z capabilities, nie tylko nazw roli,
- backend pozostaje ostatecznym enforcement.

### P2.11. Notification UI ma hardcoded kolory

`NotificationsDropdown.tsx` i Calendar używają orange/green/purple/cyan/amber itd. Należy przejść na semantic tokens zgodnie z design systemem.

### P2.12. ActiveViewers ma faktycznie jedną paletę

W `frontend/src/components/v2/presence/ActiveViewers.tsx:34-49` komentarze na jednej linii powodują, że część wartości tablicy jest komentarzem. Należy naprawić przy migracji na semantic avatar tokens.

### P2.13. Notes count dryfuje

`notes.py:152-160` zwiększa `Candidate.notes_count`, ale delete `:288-303` go nie zmniejsza. Dodatkowo imported/tombstoned notes mogą nie odpowiadać licznikowi.

Docelowo licznik jest projekcją/rebuildable counter albo aktualizowany jednym service z testem.

### P2.14. Notes list nie respektuje pełnej semantyki source deletion

`Note.source_deleted_at` istnieje, lecz list/timeline nie stosują spójnej polityki tombstone/visibility. Trzeba rozróżnić deleted at source, local redaction i legal/audit retention.

### P2.15. Job chat ma N+1

Job chat serializuje wiele zależności per message; dla strony 200 wpisów może wykonać setki query. Candidate chat ma lepszy bulk serializer, który może być wzorcem przed wspólnym Conversation.

### P2.16. Activity i timeline nie mają stabilnego globalnego cursora

Obecny candidate timeline scala kilka query z własnymi limitami, a potem tnie wynik. Wstawienie nowych rekordów między requestami może powodować duplikaty/pominięcia.

Docelowy cursor:

~~~text
(occurred_at DESC, event_id DESC)
~~~

### P2.17. Chat soft delete zachowuje treść i stare snippety bez polityki retencji

Soft delete słusznie zachowuje referencje, lecz body, notification previews i email fallback copies nie mają centralnego purge/legal hold policy.

### P2.18. Auto-parser CV z attachmentu modyfikuje kandydata bez review

`backend/app/services/m365/attachment_handler.py:195-272` może zastosować dane z emailowego CV do wspólnego profilu. Potrzebny audit, provenance, confidence, scope i review policy; privacy purge musi objąć pochodne.

### P2.19. Brak pełnej polityki notification preferences

Poza pojedynczymi ustawieniami feature brak:

- per family/channel,
- mandatory vs optional,
- timezone,
- quiet hours,
- digest,
- vacation/delegation,
- escalation override.

### P2.20. Free-form notification links są granicą zaufania

`Notification.link` jest arbitralnym stringiem do `router.push`. Docelowo event registry powinien generować typed action/deep link, walidować wewnętrzną trasę i nie pozwalać na zewnętrzne/open redirect semantics.

### P2.21. Fireflies status ładuje wszystkie meeting notes

`backend/app/api/fireflies.py:81-83` pobiera wszystkie rows, by policzyć count, i liczy wszystkie notes typu meeting, nie tylko Fireflies. Użyć SQL COUNT ze źródłem i owner scope.

### P2.22. Background skill/runbook ma drift 15 vs 24 taski

Dokumentacja operacyjna i kod nie zgadzają się. Registry powinno być źródłem generowanej dokumentacji, a CI powinno wykrywać niezarejestrowany task.

### P2.23. Health nie mierzy freshness/outcome

M365 health sprawdza konfigurację/liczbę kont, CloudTalk może sprawdzać API, ale brakuje spójnych:

- last successful sync,
- watermark age,
- queue lag,
- oldest pending,
- retry/dead count,
- webhook expiry,
- delivery success rate.

Fireflies, SMTP, Teams, Slack i większość workerów nie mają pełnego freshness check.
Podczas kontroli poprzedniego deployu `fc75350` wystąpił także jeden
nieutrwalony HTTP 503, po którym cztery próby były 200/healthy; końcowy deploy
`273cd08` był 200/healthy. Bez request ID, probe history i wspólnej korelacji
edge/backend nie da się po fakcie rozstrzygnąć, czy źródłem był proxy, restart,
timeout DB czy chwilowy wynik aplikacyjnego healthchecku.

### P2.24. Snapshot ma trzy konkurencyjne prawdy o deployu i workerach

Direct health, snapshot health i task registry pokazują różne zakresy. Snapshot `deployedAt` może być stale, a Alembic scalar nie obsługuje wielu heads.

### P2.25. Required CI uruchamia tylko 112 z 238 backend test files

Obliczenie na snapshotcie:

~~~text
backend test_*.py: 238
wymienione w required ci.yml: 112
pominięte: 126
~~~

Poza required gate są m.in.:

- job chat,
- M365 matcher/recording discovery,
- note mentions,
- notification triggers,
- presence API/manager,
- rejection email integration/scheduler,
- stage notification rules,
- Teams notifications,
- część CloudTalk/Proxycurl.

Candidate chat nie ma kompletnego dedykowanego suite.

### P2.26. Frontend prawie nie testuje tego modułu

Brak testów komponentowych/hook dla:

- `NotificationsDropdown`,
- `useNotifications`,
- Candidate/Job Chat live contract,
- Calendar deep links,
- ScheduleInterview free/busy,
- Calls/recordings,
- Presence,
- Integration cards.

### P2.27. E2E może być false green

E2E jest manual/nightly, część krytycznych flow ma `test.fixme`, conditional skip lub kończy się preview, gdy brak sekretu. Acceptance test nie może omijać błędnego endpointu i nadal przechodzić.

### P3.1. Nazewnictwo miesza task techniczny i zadanie człowieka

`background_tasks`, FastAPI `BackgroundTasks`, workery i przyszły biznesowy Task używają tego samego słowa. W kodzie docelowym zalecane nazwy:

- `WorkItem` — praca człowieka,
- `JobRun` — wykonanie workera,
- `OutboxItem` — praca delivery,
- `asyncio.Task` — wyłącznie runtime detail.

### P3.2. Candidate chat używa typów `job_chat_*`

To zaciera semantykę i utrudnia exhaustive registry. W target Conversation notification family może być wspólna, ale subject type musi pozostać jawny.

---

## 9. Najważniejsze scenariusze awarii

### Scenariusz A — recruiter myśli, że kandydat dostał email

1. Recruiter otwiera profil.
2. Kliknie Email i Send.
3. API zwraca 2xx `simulated`.
4. UI pokazuje „wysłany”.
5. Activity zapisuje `email_sent`.
6. Kandydat nic nie otrzymuje.

### Scenariusz B — JWT trafia do logów

WebSocket URL przechodzi przez reverse proxy/APM. Długi access token zostaje w request target i może zostać odczytany przez operatora/log consumer.

### Scenariusz C — iCal skanuje usługę wewnętrzną

Uprawniony calendar writer podaje publiczny URL, który redirectuje do link-local metadata albo private host. Backend wykonuje request z sieci serwera.

### Scenariusz D — wspólny UID nadpisuje event innego usera

Dwa feedy mają ten sam standardowy UID. Drugi import znajduje pierwszy row po globalnym `(source_tag, uid)` i zmienia jego treść.

### Scenariusz E — viewer renderuje cudzy telefon

Viewer tworzy template z `candidate.phone`, iteruje candidate IDs i odczytuje PII przez render endpoint.

### Scenariusz F — mention daje podwójny email

Jedna wiadomość z @mention tworzy general i mention notification. Po 15 minutach fallback wysyła oba emaile.

### Scenariusz G — calendar reminder znika po deployu

Event wchodzi w 14–16 min window podczas restartu. Po starcie jest już poza oknem i nie dostaje reminder.

### Scenariusz H — ghost notification

WS event wychodzi przed commitem, późniejszy błąd wycofuje DB. Użytkownik widzi link do nieistniejącego rekordu.

### Scenariusz I — duplicate rejection email

Graph akceptuje send, proces umiera przed local commit, retry ponownie wysyła tę samą wiadomość.

### Scenariusz J — cancel przegrywa, ale status mówi cancelled

Scheduler i cancel endpoint działają równolegle bez atomowego CAS. Provider wysyła, a DB kończy jako cancelled.

### Scenariusz K — private email pozostawia CV na dysku

Email zostaje oznaczony private, body znika, ale attachment i derived candidate enrichment pozostają dostępne.

### Scenariusz L — transkrypt trafia do złego kandydata

Dwie osoby mają ten sam końcowy fragment numeru. `.limit(1)` wybiera arbitralnie, a transcript uruchamia enrichment nie tej osoby.

### Scenariusz M — recording trafia do złego eventu

Dwa spotkania są blisko czasowo. Time-only fallback wybiera nieprawidłowy MP4 i zapisuje URL przy innym kandydacie.

### Scenariusz N — provider webhook znika po 202

Endpoint odpowiada 202, ale work został tylko `create_task`. Deploy/restart następuje zanim task wykona sync.

### Scenariusz O — trzy repliki wysyłają ten sam Slack/SMTP reminder

Każda replika ma własny loop i własną pamięć dedupe. Brak DB claim powoduje wielokrotny side effect.

### Scenariusz P — free/busy error jest pokazany jako free

Graph nie zwraca attendee lub request failuje. UI mapuje brak intervals na `[]` i pokazuje zielony stan.

### Scenariusz Q — direct link nie otwiera celu

Użytkownik klika email reminder po cold load. Calendar pokazuje bieżący tydzień i nie otwiera eventu spoza widoku.

### Scenariusz R — worker jest disabled, ale snapshot wygląda jak awaria

Task kończy się zgodnie z feature flag. Snapshot liczy tylko `not done()` i pokazuje deficyt bez reason.

---

## 10. Docelowa architektura

### 10.1. Przepływ bazowy

Każda komenda powinna przejść tę samą ścieżkę:

~~~text
HTTP/API
  -> uwierzytelnienie
  -> capability + resource scope + delegation
  -> command service / aggregate
  -> zapis stanu + DomainEvent + OutboxItem w jednej transakcji
  -> COMMIT
  -> projektory Notification / Timeline / WorkItem / Reminder
  -> trwały Delivery w stanie shadow_observed albo pending według routing generation
  -> worker z lease
  -> ponowna autoryzacja odbiorcy i preferences
  -> commit DeliveryAttempt intent z request hash/idempotency key
  -> provider
  -> write-once DeliveryAttempt outcome + aktualizacja Delivery/provider_state + receipt + metryki
~~~

Nigdy:

- SMTP przed commitem,
- Graph przed persisted outbound operation,
- Slack/Teams przez nieśledzone `create_task`,
- WebSocket przed committed projection,
- „sent” na podstawie samego HTTP 2xx aplikacji,
- przyjęcie webhooka bez durable inbox.

### 10.2. Warstwy odpowiedzialności

#### Command layer

Waliduje command, version i idempotency key. Nie buduje dowolnych provider payloadów w route.

#### Policy layer

Łączy:

- role capabilities,
- resource membership,
- mailbox delegation,
- artifact sensitivity,
- endpoint classification,
- active/revoked state.

#### Event layer

Zapisuje minimalny, wersjonowany fakt. Event nie powinien zawierać pełnej treści CV, transcriptu czy emaila, jeśli wystarczy reference.

#### Projection layer

Buduje rebuildable:

- timeline,
- notification,
- unread counters,
- task obligations,
- dashboards.

#### Delivery layer

Rozwiązuje recipienta, preference, quiet hours i endpoint. Ma lease/retry/DLQ oraz provider identity.

#### Integration layer

Przyjmuje webhooki do inbox, utrzymuje connection/cursor/run state i reconciliuje provider z lokalnym stanem.

#### Realtime layer

Dystrybuuje committed event/projection. Nie gwarantuje trwałości i nie zastępuje HTTP reconcile.

### 10.3. Współdzielenie kernela z Modułem 5

`DomainEvent`, `CommandReceipt`, `OutboxItem`, `InboxItem`, `Delivery`, `DeliveryAttempt`, `Obligation/WorkItem` i `JobRun` powinny być wspólną infrastrukturą NEXUS.

Claude przed utworzeniem tabel ma sprawdzić:

- czy PR-y Modułu 5 już dodały odpowiednik,
- czy istnieje aktywny branch/PR z tym schematem,
- czy nazwa/model może zostać rozszerzony,
- czy tworzenie nowego bytu nie da dwóch dispatcherów.

Nie wolno wprowadzać równolegle `communication_outbox` i `domain_outbox`, jeśli mogą obsłużyć ten sam kontrakt.

---

## 11. Docelowe encje i pola

### 11.1. DomainEvent

Minimalne pola:

~~~text
id UUID PK
event_type VARCHAR
schema_version SMALLINT
actor_user_id FK nullable dla systemu
subject_type VARCHAR
subject_id VARCHAR
organization_id nullable
correlation_id UUID
causation_id UUID nullable
producer VARCHAR
command_receipt_id UUID nullable
aggregate_type/aggregate_id
aggregate_version BIGINT
event_ordinal SMALLINT
sensitivity VARCHAR
retention_class VARCHAR
payload JSONB
occurred_at timestamptz
created_at timestamptz
~~~

Constraints:

- partial unique `(aggregate_type, aggregate_id, aggregate_version, event_ordinal) WHERE aggregate_id IS NOT NULL`,
- partial unique `(command_receipt_id, event_ordinal) WHERE command_receipt_id IS NOT NULL`,
- każdy event musi mieć aggregate identity albo niepusty `command_receipt_id`; scheduler/system command tworzy synthetic CommandReceipt z własnym business key,
- event type jako versioned string, nie stale rosnący PostgreSQL enum,
- payload size limit,
- schema registry w kodzie,
- append-only.

Jedna komenda może legalnie utworzyć wiele eventów, np. `message.created`, kilka `message.mentioned` i `work_item.created`. Dlatego idempotencja komendy nie może być unique constraintem „jeden command = jeden DomainEvent”. Nullable `causation_id` służy do trace, nie do dedupe.

### 11.1a. CommandReceipt / CommandDedup

~~~text
id UUID
actor_or_client_key
command_type
idempotency_key
request_hash
aggregate_type/aggregate_id nullable
response_status
response_snapshot_safe JSONB
created_at/expires_at
~~~

Unique `(actor_or_client_key, command_type, idempotency_key)`. Replay z identycznym request hash zwraca zapisany wynik; ten sam key z innym body daje `409 IDEMPOTENCY_KEY_REUSED`. DomainEvent wskazuje receipt i ma własny `event_ordinal`.

### 11.2. AuditEntry

~~~text
id UUID
actor_user_id
action
subject_type/id
result: allowed | denied | success | failed
reason_code
correlation_id
request_id
ip_hash / user_agent_class według polityki
safe_changes JSONB
occurred_at
~~~

Pełny provider payload, token, body emaila, CV i transcript nie trafiają do `safe_changes`.

### 11.3. OutboxItem

~~~text
id UUID
event_id UUID
projector/handler VARCHAR
state shadow_observed | pending | leased | retry_wait | processed | dead | cancelled
attempt_count
next_attempt_at
lease_owner
lease_until
fencing_token
last_error_code
last_error_safe
processed_at
created_at/updated_at
~~~

Unique `(event_id, handler)`. Index `(state, next_attempt_at)`. Claim query zawiera jawne `state IN ('pending','retry_wait')`; `shadow_observed` jest terminalne i nieclaimowalne. Cutover zmienia routing generation wyłącznie dla nowych eventów; nie promuje historycznych shadow rows.

### 11.4. InboxItem / ProviderWebhookInbox

~~~text
id UUID
provider
provider_event_id nullable
fingerprint
connection_id nullable
connection_key NOT NULL
payload_encrypted_or_minimal JSONB/BYTEA
received_at
state shadow_observed | received | leased | retry_wait | processed | quarantined | dead | discarded
attempt_count/next_attempt_at
lease fields
processed_at
retention_until
last_error_safe
~~~

`connection_key` identyfikuje connection albo organizacyjny endpoint i nigdy nie jest `NULL`.

- partial unique `(provider, connection_key, provider_event_id) WHERE provider_event_id IS NOT NULL`,
- fallback partial unique `(provider, connection_key, fingerprint) WHERE provider_event_id IS NULL` tylko wtedy, gdy fingerprint zawiera stabilną provider-specific replay identity/time/signature scope,
- jeśli provider nie daje stabilnej identity, event należy przyjąć, a idempotencję zapewnia handler/business key; sam payload hash nie może odrzucić legalnie powtórzonej treści.

Commit przed odpowiedzią 2xx. `shadow_observed` jest terminalne i nieclaimowalne. Po granicy cutover nowe webhooki canary od razu powstają jako `received`; historyczne shadow eventy wymagają jednostkowej reconciliation. Manual replay nie klonuje InboxItem, bo ten sam provider event poprawnie zajmuje canonical unique key.

`InboxReplayRequest` wskazuje immutable, oryginalny receipt:

~~~text
id UUID
original_inbox_id UUID
replay_generation
requested_by/reason/audit_entry_id
handler_version
state pending | leased | retry_wait | completed | failed | dead | cancelled
lease_owner/lease_until/fencing_token
created_at/completed_at
last_error_safe
~~~

Unique `(original_inbox_id, replay_generation)`. Worker claimuje replay request,
odczytuje oryginalny zaszyfrowany/minimalny payload i uruchamia idempotentny
handler z nowym CommandReceipt. Logical output keys są deterministycznie
wyprowadzone z oryginalnego InboxItem + handler version i **nie** zawierają
replay generation, więc częściowo wykonany replay nie duplikuje WorkItem,
Delivery ani provider operation przy kolejnej próbie. Worker nie tworzy drugiego
receipt z tym samym `provider_event_id`, nie mutuje `shadow_observed -> received`
i zachowuje jawny związek z decyzją operatora.

### 11.5. Notification

~~~text
id UUID
event_id UUID
recipient_user_id
family
notification_type
title
body_preview
action_key / deep_link_params
sensitivity
state unread | read | archived | expired
read_at
archived_at
expires_at
dedupe_key
created_at
~~~

Unique `(event_id, recipient_user_id)` jest bezwarunkowym inwariantem bazowej
projekcji. Digest nie może osłabiać tej unikalności ani tworzyć alternatywnego
klucza deduplikacji Notification.

`NotificationDigest` agreguje istniejące, kanoniczne powiadomienia:

~~~text
id UUID
recipient_user_id
window_start/window_end
family
state building | ready | dispatching | completed | failed | cancelled
scheduled_at/dispatched_at
created_at/updated_at
~~~

Unique `(recipient_user_id, window_start, window_end, family)` stabilizuje rebuild
tego samego okna. Join
`NotificationDigestItem(digest_id, notification_id, position)` ma unique
`(digest_id, notification_id)` oraz FK do Notification. Ta sama Notification
może wejść do co najwyżej jednego aktywnego digestu dla danego schedule window;
rebuild digestu jest idempotentny i nigdy nie duplikuje bazowej projekcji.

### 11.6. NotificationPreference

~~~text
user_id
event_family
channel
delivery_mode immediate | digest | off
quiet_hours_start/end
timezone IANA
digest_schedule
enabled
version
~~~

Mandatory security notifications są kontrolowane przez server-side registry i nie mogą zostać wyłączone przez klienta.

Unique `(user_id, event_family, channel)`. `event_family` i `channel` pochodzą z kontrolowanego rejestru, nie z dowolnego stringa klienta.

### 11.7. DeliveryEndpoint

~~~text
id UUID
channel email | in_app | slack | teams | webhook
owner_user_id nullable
scope_type/id nullable
owner_scope_key NOT NULL
canonical_endpoint_hash NOT NULL
encrypted_address_or_config
verified_at
enabled
max_data_classification
created_at/updated_at
~~~

### 11.8. Delivery i DeliveryAttempt

`Delivery` jest logicznym zamiarem dostarczenia:

~~~text
id UUID
event_id
outbound_message_id nullable
notification_id nullable
reminder_schedule_id nullable
logical_operation_key NOT NULL
recipient_user_id nullable
recipient_key NOT NULL
endpoint_id
channel
template_ref nullable
template_version_id FK nullable  # dodawany/backfillowany dopiero w PR-36a
payload_hash
encrypted_payload_snapshot nullable
state shadow_observed | pending | leased | retry_wait | completed | skipped | dead | cancelled | uncertain
attempt_count/max_attempts
next_attempt_at
next_reconcile_at nullable
lease_owner/lease_until/fencing_token
latest_provider_operation_id/message_id nullable
provider_state not_requested | accepted | sent | delivered | bounced | failed | unknown
accepted_at/sent_at/delivered_at
last_error_code/details_safe
~~~

`recipient_key` jest kanonicznym, niepustym identyfikatorem logicznego odbiorcy, np. `user:<uuid>` albo `address-hash:<sha256>`. `logical_operation_key` zawiera event + projector/rule/purpose, dzięki czemu dwa legalne delivery rules tego samego eventu nie kolidują. Unique `(logical_operation_key, recipient_key, channel, endpoint_id)`; nie opierać unique na nullable `recipient_user_id`.

`DeliveryAttempt` jest niezmiennym zapisem pojedynczego wywołania providera:

~~~text
id UUID
delivery_id
endpoint_id
attempt_no
retry_generation
provider_idempotency_or_request_key
planned_at/request_started_at/finished_at
request_hash
provider_request_id nullable
provider_message_id nullable
provider_receipt_id nullable
outcome nullable | accepted | succeeded | retryable_failure | terminal_failure | unknown
observed_provider_state nullable
safe_response_code/error_code/error_details_safe
created_at
~~~

Unique `(delivery_id, attempt_no)` oraz partial unique `(endpoint_id, provider_receipt_id) WHERE provider_receipt_id IS NOT NULL`. Attempt intent powstaje i commitnie **przed** network call z request hash/idempotency key. `outcome` jest write-once CAS `NULL -> terminal` i po ustawieniu immutable. Admin retry zwiększa retry generation i tworzy nowy attempt; nie nadpisuje historii.

Lease expiry bez attempt intent może zostać reclaimed. Lease expiry z `request_started_at` i `outcome IS NULL` zawsze ustawia Delivery `uncertain` i wymaga provider reconciliation; nigdy blind retry.

`Delivery.state` opisuje logiczną pracę NEXUS, a `provider_state` prawdę zwróconą lub zreconciliowaną u dostawcy. `completed + accepted` nie jest tym samym co `sent`, a `delivered` wymaga receipt. OutboundMessage agreguje Delivery, nigdy pojedynczy attempt.

### 11.9. OutboundMessage

~~~text
id UUID
business_operation_id NOT NULL
command_receipt_id UUID
actor_user_id
mailbox_owner_id
subject_type/id
endpoint_id
subject_snapshot
body_snapshot encrypted lub artifact reference
template_ref nullable
template_version_id FK nullable  # migration dopiero po PR-36a
state draft | queued | dispatching | completed | uncertain | failed | cancelled
provider_draft_id/provider_message_id
created_at/queued_at/accepted_at/sent_at
~~~

`OutboundMessage` oznacza dokładnie jeden provider envelope. Odbiorcy są osobną tabelą:

~~~text
OutboundRecipient
  outbound_message_id
  recipient_type to | cc | bcc
  recipient_key
  address_encrypted
  display_name_encrypted nullable
  UNIQUE(outbound_message_id, recipient_type, recipient_key)
~~~

Dla emaila jeden Delivery odpowiada envelope i ma `recipient_key='envelope:<outbound_message_id>'`; nie tworzymy osobnego provider call per TO/CC/BCC. Opcjonalny `DeliveryRecipientOutcome(delivery_id, recipient_key, provider_state, receipt_id, timestamps)` przechowuje per-recipient receipts, jeśli provider je daje.

Bulk jest osobnym `OutboundBatch(id, business_operation_id, state, counts, created_by, created_at)` z wieloma child OutboundMessage. `partially_completed` należy do batch, nie pojedynczego envelope.

Stan OutboundMessage jest wyliczany z envelope Delivery; pojedynczy immutable attempt nie jest agregatem. `completed` nie znaczy automatycznie `delivered`.

### 11.9a. ProviderOperation

Generyczna operacja providera dla kalendarza, subscription, sync, call initiation i innych działań, których nie wolno wciskać do emailowego `OutboundMessage`.

~~~text
id UUID
event_id
provider
connection_id
connection_key NOT NULL
operation_type
subject_type/id
business_operation_id NOT NULL
request_hash
provider_idempotency_or_request_key
encrypted_request_snapshot nullable
state pending | leased | retry_wait | accepted | completed | uncertain | dead | cancelled
provider_operation_id nullable
provider_resource_id nullable
current_retry_generation
attempt_count/max_attempts
next_attempt_at
next_reconcile_at nullable
lease_owner/lease_until/fencing_token
accepted_at/completed_at
last_error_code/details_safe
created_at/updated_at
~~~

Unique `(provider, connection_key, business_operation_id)`. ProviderOperation nie przechowuje arbitralnego executable payload; adapter interpretuje wersjonowany `operation_type` i walidowany snapshot.

Przed network call worker tworzy i commitnie intent bieżącego
ProviderOperationAttempt z request/idempotency key. Pole rodzica nie jest źródłem
prawdy o tym, czy aktualna generacja rozpoczęła request. Expired lease bez
unresolved attempt w `current_retry_generation` może zostać bezpiecznie
reclaimed; unresolved attempt bieżącej generacji zawsze prowadzi do
`uncertain/reconcile`, nigdy blind retry.

`ProviderOperationAttempt` przechowuje historię prób analogicznie do DeliveryAttempt:

~~~text
id UUID
provider_operation_id
retry_generation
attempt_no
request_hash/provider_request_key
request_started_at/finished_at
outcome nullable | accepted | succeeded | retryable_failure | terminal_failure | unknown
provider_request_id_observed/provider_resource_id_observed nullable
safe_response/error
~~~

Unique `(provider_operation_id, retry_generation, attempt_no)`. Intent commit
przed network, outcome write-once `NULL -> terminal`. Bezpiecznie zatwierdzony
retry zwiększa `current_retry_generation`; attempt z poprzedniej generacji nie
może być dowodem rozpoczęcia requestu w nowej. Reconciliation tworzy osobny
attempt/result i nie nadpisuje historii.

### 11.10. MailboxDelegation

~~~text
mailbox_owner_id
delegate_user_id
scope_type/id
scope_key NOT NULL
can_read
can_send
valid_from/valid_until
reason
granted_by
state active | revoked | expired
created_at/revoked_at
~~~

Admin nie dostaje domyślnej delegacji do personal mailbox.

### 11.11. Conversation

~~~text
id UUID
context_type candidate | job | work_item
context_id
status active | locked | archived
sensitivity
retention_class
created_by
version
created_at/updated_at
~~~

### 11.12. ConversationMembership

~~~text
conversation_id
user_id
source owner | collaborator | resource_role | explicit
permission read | write | moderate
valid_from/valid_until
revoked_at
~~~

To może być projekcja/cache; bieżący ResourceAccessService pozostaje ostatecznym źródłem autoryzacji.

Unique `(conversation_id, user_id, source)` dla aktywnej projekcji. Jawna delegacja i resource-role mogą współistnieć, ale effective permission jest obliczana deterministycznie i cofnięcie ostatniego źródła odbiera dostęp.

### 11.13. Message i encje podrzędne

`Message`:

~~~text
id UUID
conversation_id
author_user_id
client_message_id
reply_to_message_id nullable
body
format
state active | redacted | deleted
version
created_at/edited_at/redacted_at
~~~

Encje podrzędne:

- `MessageRevision`,
- `MessageMention`,
- `MessageReaction`,
- `ConversationReadCursor`,
- `ConversationPin`.

Unique `(conversation_id, author_user_id, client_message_id)`.

### 11.14. WorkItem

~~~text
id UUID
work_type
subject_type/id
title/description
owner_user_id
assignee_user_id
reporter_user_id
status open | in_progress | snoozed | completed | cancelled
priority
due_at
business_timezone
snoozed_until
completed_at/cancelled_at
recurrence_rule nullable
source_event_id nullable
source_type/source_id nullable
source_policy_key/source_policy_version nullable
workflow_revision_id/stage_revision_id nullable
source_semantic_key/source_registry_version nullable
idempotency_key NOT NULL
version
created_at/updated_at
~~~

Encje podrzędne:

- `WorkItemWatcher`,
- `WorkItemStatusHistory`,
- `WorkItemComment`,
- `WorkItemLink`,
- `WorkItemEscalation`.

Unique `(owner_user_id, idempotency_key)` dla komend użytkownika. Dla
automatycznych obowiązków obowiązują dwa jawne partial unique:

- event-driven: `(source_event_id, source_policy_key, source_policy_version,
  work_type) WHERE source_event_id IS NOT NULL`,
- legacy bridge bez eventu: `(source_type, source_id, source_policy_key,
  source_policy_version, work_type) WHERE source_event_id IS NULL`.

Każdy automatyczny row ma non-null `source_policy_key` i
`source_policy_version`; legacy bridge dodatkowo wymaga non-null
`source_type/source_id`. Nie opierać dedupe na nullable składniku bez warunku
lub `NULLS NOT DISTINCT`.

Snapshot `workflow_revision_id/stage_revision_id/semantic_key/registry_version`
jest provenance, nie statusem WorkItem. Lifecycle zadania pozostaje wyłącznie
`open/in_progress/snoozed/completed/cancelled`. Dzięki temu ponowne wejście tego
samego procesu w ten sam stage ma nowy transition event i może legalnie utworzyć
nowy obowiązek, a replay tego samego eventu nie tworzy duplikatu.

### 11.15. ReminderSchedule

~~~text
id UUID
subject_type work_item | calendar_event
subject_id
occurrence_id nullable
subject_version
schedule_generation
recipient_user_id
recipient_key NOT NULL
reminder_type
offset_minutes nullable
due_at
rule_version
logical_key NOT NULL
state scheduled | leased | retry_wait | emitted | dead | cancelled
attempt_count/next_attempt_at
lease fields
emitted_event_id nullable
emitted_at/cancelled_at
~~~

Unique `(logical_key, schedule_generation)`, gdzie key powstaje serwerowo z `(subject_type, subject_id, occurrence_id, recipient_key, reminder_type, rule_version)`. Reschedule anuluje niesłany rekord i tworzy nową generation dla nowej wersji subject. Scheduler tylko emituje DomainEvent; 1:N Delivery wskazują `reminder_schedule_id`. `emitted` nie obiecuje żadnego provider delivery.

Jeżeli reminder został już emitted, polityka produktu musi jawnie zdecydować, czy reschedule tworzy nowy reminder; default fail-safe: nowa generation tylko wtedy, gdy nowy due jest nadal w przyszłości i ten sam offset nie został wysłany dla nowej occurrence/version.

### 11.16. CalendarEvent

~~~text
id UUID
owner_user_id
subject_type/id nullable
source manual | m365 | ical_feed
visibility private | resource | team
title
description encrypted/restricted
starts_at/ends_at UTC
timezone IANA
all_day
lifecycle_state draft | scheduled | cancelled | completed
provider_sync_state not_required | pending | syncing | synced | failed | uncertain
version
created_at/updated_at
~~~

### 11.17. EventOccurrence i EventParticipant

`EventOccurrence`:

- parent event,
- occurrence start/end,
- recurrence ID,
- cancelled/exception state.

`EventParticipant`:

- user/contact/candidate/email reference,
- `canonical_participant_key NOT NULL`, wyliczony server-side po normalizacji typu/ID lub email hash,
- role organizer/required/optional,
- response status,
- visibility level,
- provider participant ID.

### 11.18. CalendarFeed i ExternalEventLink

`CalendarFeed`:

~~~text
id UUID
owner_user_id
encrypted_url
url_fingerprint
status pending_verification | active | paused | degraded | deleted
last_sync_at/next_sync_at
watermark
failure_count
last_error_safe
limits JSONB
~~~

`ExternalEventLink` ma unique `(feed_id, external_uid)` i content hash/last seen.

### 11.19. MessageTemplate i TemplateVersion

`MessageTemplate`:

- owner/scope,
- channel,
- purpose,
- locale,
- state,
- active version,
- approval policy.

`TemplateVersion`:

- immutable subject/body,
- variable schema,
- created/published by/at,
- required variables,
- content hash.

### 11.20. AutomationRule

~~~text
id UUID
trigger_event_type
condition_version/condition
recipient_resolver
channel
template_version_id
source_policy_key
semantic_registry_version nullable
workflow_revision_id nullable
revision_binding fixed | follow_future nullable
throttle_policy
dedupe_policy
state draft | active | paused | retired
version
owner/scope/audit fields
~~~

Warunki muszą być kontrolowanym DSL, nie arbitralnym Python/SQL/Jinja.
Reguła stage-aware zawsze pinująca `semantic_registry_version` i domyślnie
konkretny `workflow_revision_id` może być aktywna dopiero dla rewizji z
upstream `runtime_status=eligible`. `follow_future` nie oznacza automatycznego
przepięcia: publikacja nowej rewizji tworzy pending revalidation, nową wersję
AutomationRule i — gdy wymaga tego scope/fan-out — ponowną akceptację.

### 11.20a. AutomationExecution

Każde rozpatrzenie konkretnej wersji reguły dla eventu ma trwały ledger. Bez
niego replay eventu może ponownie utworzyć WorkItem, Delivery albo provider
operation mimo poprawnego dedupe na niższych warstwach.

~~~text
id UUID
rule_id/rule_version
event_id
state shadow_observed | pending | leased | retry_wait | completed | skipped | dead
decision_snapshot_safe
fanout_snapshot_safe
workflow_revision_id/stage_revision_id/semantic_key/registry_version snapshot nullable
command_receipt_id nullable
correlation_id
logical_output_keys
attempt_count/next_attempt_at
lease_owner/lease_until/fencing_token
started_at/completed_at
last_error_code_safe
created_at/updated_at
~~~

Unique `(rule_id, rule_version, event_id)`. `decision_snapshot_safe` zapisuje
wersję DSL i wynik warunku bez kopiowania PII; `logical_output_keys` są
deterministyczne dla każdego planowanego WorkItem/OutboundMessage/Delivery.
`CommandReceipt` spina atomowe utworzenie ledgeru i wielu eventów wyjściowych.
`shadow_observed` jest terminalne: aktywacja routingu tworzy `pending` wyłącznie
dla nowych eventów po granicy cutover, bez promowania historycznych obserwacji.

### 11.21. IntegrationConnection

~~~text
id UUID
provider
owner_user_id lub organization scope
owner_scope_key NOT NULL
external_account_key NOT NULL
desired_state enabled | disabled
configuration_state unconfigured | configured | reconnect_required | disconnecting
health_state unknown | healthy | degraded | failed
run_state idle | queued | running | retry_wait nullable
credential_reference nullable
cleanup_only_credential_reference nullable
last_success_at
last_attempt_at
next_attempt_at
failure_count
last_error_code_safe
version
~~~

Jedna integracja może być jednocześnie `desired_state=disabled`, `configuration_state=configured` i mieć `health_state=healthy` z ostatniego runu. Nie wolno mieszać tych prawd w jeden enum. Unique `(provider, owner_scope_key, external_account_key)`.

Adapter `/api/health.checks` mapuje wewnętrzne `health_state=failed` na publiczne `unhealthy`, zachowując stabilny health contract; admin UI/snapshot pokazuje wszystkie cztery wymiary.

### 11.22. SyncCursor i IntegrationRun

`SyncCursor` jest per connection/resource stream i ma fencing token/version.

`IntegrationRun`:

- mode,
- requested_by,
- state,
- started/finished,
- counts,
- cursor before/after,
- safe errors,
- correlation ID.

### 11.23. JobRun, WorkerLease i WorkerHeartbeat

`WorkerRegistration` opisuje desired state. `JobRun` opisuje wykonanie. `WorkerLease` zapewnia exclusive work. Heartbeat raportuje świeżość.

Snapshot ma zwracać dla każdego workera:

~~~text
desired_state
runtime_state
reason
lease_owner
last_heartbeat_at
last_success_at
last_error_code
next_due_at
backlog_count
oldest_pending_age_seconds
dead_letter_count
~~~

### 11.24. CommunicationArtifact i RetentionManifest

Artifact obejmuje:

- email attachment,
- recording,
- transcript,
- rendered message body,
- notification snippet,
- provider raw payload,
- derived search/vector/CV data.

Manifest przechowuje:

- sensitivity,
- retention class/until,
- storage location,
- derivatives,
- purge state/attempts.

`RetentionHold` jest oddzielną encją: `artifact/scope`, `reason`, `set_by`, `starts_at`, `released_by/at`. Artefakt może być active albo purge_requested i jednocześnie objęty hold. Hold blokuje claim purge, ale nie zmienia lifecycle ani prawa dostępu.

### 11.25. RealtimeEventProjection

NEXUS nie ma dziś Redis w zatwierdzonym stacku, dlatego pierwsza wersja ma być PostgreSQL-backed, bez wprowadzania nowej infrastruktury tylko dla tego modułu.

~~~text
recipient_sequence BIGINT
event_id UUID
recipient_user_id
event_type/schema_version
resource_type/resource_id
minimal_payload JSONB
occurred_at
expires_at
~~~

Unique `(event_id, recipient_user_id)` i `(recipient_user_id, recipient_sequence)`.

Zwykły globalny PostgreSQL identity nie gwarantuje kolejności commitów i może zgubić spóźniony niższy numer. Dlatego projector blokuje `RealtimeRecipientCursor(user_id, next_sequence)` przez `SELECT ... FOR UPDATE`, przydziela następny numer i trzyma lock do commitu. Druga transakcja dla tego odbiorcy nie przydzieli wyższego cursora przed commitem pierwszej. Przy fan-out cursor rows są zawsze blokowane w deterministycznym `user_id ASC`; deadlock/serialization failure ma bounded retry. `pg_notify` wewnątrz tej samej transakcji zawiera wyłącznie recipient/sequence/event ID i jest emitowane po commicie. HTTP catch-up filtruje `recipient_user_id` oraz `recipient_sequence > after`.

Retencja początkowa: konfigurowalne 7 dni do decyzji security/ops. Jeżeli cursor jest starszy niż retencja, API zwraca `reset_required=true`, a frontend odświeża kanoniczne query. Redis można rozważyć później na podstawie mierzonego obciążenia; nie jest częścią pierwszego planu.

### 11.25a. RealtimeTicket

~~~text
id UUID
ticket_hash UNIQUE
user_id
session_id
audience
issued_at/expires_at
consumed_at nullable
consumed_connection_id nullable
~~~

W URL trafia tylko opaque secret; w DB wyłącznie hash. Consume jest atomowe: `UPDATE ... SET consumed_at=now() WHERE ticket_hash=? AND consumed_at IS NULL AND expires_at>now() AND audience=? RETURNING ...`. Działa między replikami, a dwa równoległe connecty wygrywają dokładnie raz. Cleanup usuwa wygasłe/zużyte rekordy według krótkiej retencji.

### 11.26. Wymagane constraints integralności

Poniższe constraints są częścią modelu, nie opcjonalną optymalizacją aplikacji:

| Encja | Constraint |
|---|---|
| OutboundMessage | unique `(mailbox_owner_id, business_operation_id)` |
| InboxItem | provider ID/fingerprint partial uniques z 11.4; immutable provider receipt |
| InboxReplayRequest | unique `(original_inbox_id, replay_generation)` |
| DeliveryEndpoint | null-safe/partial active unique `(channel, owner_scope_key, canonical_endpoint_hash)` |
| MailboxDelegation | partial unique aktywnej `(mailbox_owner_id, delegate_user_id, scope_key)` |
| Conversation | unique `(context_type, context_id)` |
| MessageMention | unique `(message_id, user_id)` |
| MessageReaction | unique `(message_id, user_id, emoji)` |
| ConversationReadCursor | PK/unique `(conversation_id, user_id)` |
| ConversationPin | unique `(conversation_id, message_id)`; limit liczby pinów egzekwowany pod lockiem Conversation |
| WorkItem | user idempotency + dwa partial unique event/legacy-source z 11.14; automatyczne policy key/version non-null |
| EventOccurrence | unique `(calendar_event_id, recurrence_id)` i check `ends_at > starts_at` |
| EventParticipant | unique kanonicznego participant key w event/occurrence |
| CalendarEvent | check `ends_at > starts_at`; owner/scope non-null zgodnie z visibility |
| CalendarFeed | partial unique aktywnego `(owner_user_id, url_fingerprint)` |
| TemplateVersion | unique `(template_id, version)` i DB/application immutability po publish |
| Notification | unique `(event_id, recipient_user_id)` bez wyjątku dla digestu |
| NotificationDigest | unique `(recipient_user_id, window_start, window_end, family)` |
| AutomationExecution | unique `(rule_id, rule_version, event_id)` |
| IntegrationConnection | unique `(provider, owner_scope_key, external_account_key)`; `disconnecting => desired_state=disabled AND credential_reference IS NULL`; `unconfigured => oba credential refs NULL` |
| SyncCursor | unique `(connection_id, stream_key)` z atomic version/fencing update |
| ProviderOperation | unique `(provider, connection_key, business_operation_id)` |
| ProviderOperationAttempt | unique `(provider_operation_id, retry_generation, attempt_no)`; outcome write-once |

Każdy pre-existing duplicate ma trafić do preflight report/quarantine przed dodaniem constraint. Żaden constraint nie może polegać na nullable części klucza bez `NULLS NOT DISTINCT`, niepustego canonical key albo partial index.

---

## 12. Docelowe state machines

### 12.1. Outbox

~~~text
pending -> leased -> processed
             |\
             | +-> retry_wait -> pending
             +----> dead

pending/retry_wait -> cancelled
~~~

Lease po TTL może zostać przejęty. Stary fencing token nie może zapisać wyniku.

`shadow_observed` jest terminalnym stanem parity i nie ma normalnego transition do pending.

### 12.2. Delivery

~~~text
pending -> leased -> completed
             |\
             | +-> retry_wait -> pending
             | +-> uncertain -> reconcile -> completed/dead/uncertain
             +----> dead

pending/leased -> skipped
pending/retry_wait -> cancelled
dead -> pending             # audytowany retry generation; stare attempts pozostają
~~~

Równolegle, ale oddzielnie, zmienia się `provider_state`:

~~~text
not_requested -> accepted -> sent -> delivered
                     |          +-> bounced
                     +-> unknown -> accepted/sent/failed po reconciliation
not_requested -> unknown    # timeout/crash, nie wiadomo czy provider przyjął
not_requested/accepted -> failed
failed -> not_requested     # tylko nowa retry_generation po retryable/approved failure
unknown -> not_requested    # tylko reconciliation jednoznacznie dowiodła not_sent
~~~

UI nie wyprowadza słowa „wysłano” z `Delivery.state=completed`; używa jawnego `provider_state`.

Jeśli provider nadal nie rozstrzyga wyniku, reconciliation pozostawia Delivery
w `uncertain` i ustawia `next_reconcile_at`; sama liczba prób nie jest dowodem
wysłania ani niewysłania.

`shadow_observed` jest terminalne. Manualny replay po reconciliation tworzy nowy Delivery z nowym audytowanym logical operation key; nie mutuje starego row.

### 12.2a. DeliveryAttempt

Attempt intent jest commitowany przed requestem z `outcome=NULL`. Po zakończeniu dostaje przez CAS dokładnie jeden write-once outcome: `accepted`, `succeeded`, `retryable_failure`, `terminal_failure` albo `unknown`, a potem jest immutable. Crash z unresolved attempt prowadzi Delivery do `uncertain`; reconciliation dopisuje osobny audytowany rezultat/attempt i nie nadpisuje historycznej obserwacji.

### 12.2b. InboxItem

~~~text
received -> leased -> processed
             |\
             | +-> retry_wait -> received
             | +-> quarantined -> received po audytowanym review
             +----> dead
received/retry_wait -> discarded  # tylko zweryfikowany duplikat/nieobsługiwany typ
~~~

2xx dla providera wolno zwrócić dopiero po trwałym `received`. `processed` oznacza zakończony idempotentny handler, nie samo odebranie.

`shadow_observed` nie przechodzi automatycznie do received. Manual replay po
reconciliation tworzy `InboxReplayRequest` wskazujący oryginalny InboxItem;
nie klonuje provider receipt i nie koliduje z unique provider eventu.

### 12.2c. ProviderOperation

~~~text
pending -> leased -> accepted -> completed
             |          |\
             | +-> uncertain -> reconcile -> accepted/completed/dead/uncertain
             |          | +-> uncertain -> reconcile -> completed/dead/uncertain
             |          +----> retry_wait -> pending, tylko gdy bezpieczne
             +-> retry_wait -> pending
             +-> dead
pending/retry_wait -> cancelled
~~~

Timeout/crash po request może dać `leased -> uncertain`, nawet jeśli `accepted` nie zdążyło zostać zapisane. Po `accepted` ani `uncertain` nie wolno ślepo retryować operacji bez provider idempotency albo reconciliation.

Lease reaper patrzy wyłącznie na ProviderOperationAttempt w
`current_retry_generation`: brak unresolved intent → reclaim/retry_wait,
unresolved intent z `outcome IS NULL` → uncertain. Historyczny attempt
poprzedniej generacji nie wpływa na tę decyzję. Ten warunek jest obowiązkowy dla
calendar create/cancel, call initiation i subscription operations.

Reconciliation, która nadal nie daje odpowiedzi, pozostawia `uncertain` i ustawia `next_reconcile_at`. `dead` jest dozwolone dopiero po provider evidence, wyczerpaniu jawnej polityki lub audytowanej decyzji operatora; brak odpowiedzi nie jest dowodem niewykonania.

### 12.2d. OutboundMessage

~~~text
draft -> queued -> dispatching -> completed
             |           |\
             |           | +-> uncertain -> completed/failed
             |           +----> failed
draft/queued -> cancelled
~~~

Po nieodwracalnym provider acceptance cancel nie może zmienić historii na `cancelled`. Zamiast tego pokazuje wynik delivery albo `uncertain` i uruchamia reconciliation.

### 12.2e. OutboundBatch

~~~text
queued -> processing -> completed | partially_completed | failed
queued -> cancelled
~~~

Batch wyłącznie agreguje child OutboundMessage; każdy envelope zachowuje własny Delivery/provider truth i retry.

### 12.3. Notification

~~~text
unread <-> read -> archived
unread/read -> expired
~~~

Nie ma transition do `completed`. Completion należy do WorkItem.

### 12.4. WorkItem

~~~text
open -> in_progress -> completed
 |          |
 +-> snoozed+-> snoozed
 |          |
 +----------+-> cancelled

snoozed -> open/in_progress po `snoozed_until`
completed -> open tylko przez jawne reopen
~~~

### 12.4a. ReminderSchedule

~~~text
scheduled -> leased -> emitted
               |\
               | +-> retry_wait -> scheduled
               +----> dead
scheduled/retry_wait -> cancelled
~~~

`emitted` oznacza committed DomainEvent, nie wysłanie kanałem. Delivery i DeliveryAttempt mają własne stany.

### 12.5. CalendarEvent

Lifecycle domenowy:

~~~text
draft -> scheduled -> completed
           |
           +-> cancelled
~~~

Provider sync jest osobną state machine:

~~~text
not_required
pending -> syncing -> synced
              |\
              | +-> failed -> pending
              +-> uncertain -> synced/failed po reconcile
synced -> pending  # lokalna zmiana wymagająca resync
~~~

Event może być `lifecycle_state=scheduled` i `provider_sync_state=failed`; UI pokazuje oba fakty. `rescheduling` i `cancelling` są typami ProviderOperation, nie konkurencyjnym stanem domenowym eventu.

### 12.6. Message

~~~text
active -> redacted -> purged artifact
active -> deleted tombstone -> purged artifact
~~~

Edit zwiększa version i tworzy revision; nie jest odrębnym terminalnym stanem.

### 12.7. IntegrationConnection

Są cztery ortogonalne state machines:

~~~text
desired:       disabled <-> enabled
configuration: unconfigured -> configured
               configured | reconnect_required -> disconnecting
               reconnect_required -> configured
               disconnecting -> unconfigured
health:        unknown -> healthy <-> degraded -> failed -> unknown/healthy
run:           idle -> queued -> running -> idle/retry_wait -> queued
~~~

Pause ustawia `desired_state=disabled` bez kasowania credentials/ostatniego health. Resume ustawia `enabled`; jeżeli configuration jest `reconnect_required`, run nie startuje i UI prowadzi do reconnect.

Disconnect jest inną komendą niż pause i przebiega dwufazowo. Pierwsza
transakcja/CAS ustawia `desired_state=disabled`, przechodzi
`configured|reconnect_required -> disconnecting`, blokuje nowe runy, renewal i
zwykłe provider operations oraz atomowo tworzy cleanup ProviderOperation.
Credential reference zostaje atomowo przeniesiony, nie skopiowany, do
cleanup-only/sealed capability:
nie jest dostępny dla normalnych workerów ani UI, ale cleanup worker może użyć
go wyłącznie do revoke i usunięcia subscriptions.

Po potwierdzonym cleanup/reconciliation druga transakcja bezpowrotnie usuwa
credential reference i przechodzi `disconnecting -> unconfigured`. Timeout lub
brak odpowiedzi pozostawia jawne `disconnecting/uncertain` z
`next_reconcile_at`; nie wolno obiecać zakończonego revoke. Jeżeli polityka
wymaga natychmiastowego zniszczenia sekretu, operacja kończy się audytowanym
`not_attempted_credentials_erased`, bez fikcyjnego statusu `queued`.

Historia runów, audit i bezpieczne identyfikatory połączenia pozostają;
treść/artefakty są usuwane wyłącznie przez osobną politykę retention, nie jako
efekt uboczny disconnect.

### 12.7a. AutomationRule i AutomationExecution

~~~text
rule: draft -> active <-> paused -> retired
execution: pending -> leased -> completed | skipped
                    |\
                    | +-> retry_wait -> pending
                    +----> dead
~~~

`retired` i `shadow_observed` są terminalne. Edycja aktywnej reguły tworzy nową
wersję zamiast mutować regułę używaną przez istniejące wykonania. Ponowny replay
tego samego `(rule_id, rule_version, event_id)` odczytuje istniejący ledger i nie
tworzy kolejnych logical outputs.

### 12.8. Artifact purge

~~~text
active -> purge_requested -> purging -> purged
                              |
                              +-> retry_wait -> purging
                              +-> dead
~~~

Aktywny RetentionHold jest ortogonalną blokadą: purge worker nie claimuje artefaktu. Po release ponownie ocenia `retention_until` i istniejący `purge_requested`; nie wymusza purge, jeżeli termin jeszcze nie nadszedł.

---

## 13. Nienaruszalne inwarianty

1. Żaden viewer nie wysyła komunikacji ani nie odczytuje PII przez pomocniczy endpoint.
2. Każdy list/detail/mutate/render/send sprawdza capability i resource scope.
3. HTTP, WebSocket, background dispatch i artifact proxy używają tej samej polityki dostępu.
4. Admin nie ma domyślnego dostępu do personal mailbox; potrzebuje delegacji albo audytowanego break-glass.
5. Żaden zewnętrzny side effect nie zachodzi przed commitem odpowiedniego event/outbox row.
6. Odpowiedź 2xx aplikacji nie może być prezentowana jako „sent”, jeśli provider nie potwierdził właściwego stanu.
7. Każda logical send ma business idempotency key.
8. Każdy provider receipt/message ID jest związany z właściwym owner/connection.
9. Retry nie może wysłać drugi raz bez wcześniejszej reconciliacji stanu `unknown`.
10. Mention zastępuje general chat notification dla tego recipienta.
11. Notification read i WorkItem complete są niezależne.
12. Message create jest idempotentne po `client_message_id`.
13. Edit tworzy revision i powiadamia wyłącznie nowo mentionowane osoby.
14. Revoked/inactive user nie dostaje kolejnych delivery; autoryzacja jest ponawiana przed dispatch.
15. Presence nie ujawnia zasobu użytkownikowi bez dostępu.
16. WebSocket URL nie zawiera długowiecznych tokenów ani PII.
17. Reminder nie zależy wyłącznie od pamięci procesu ani wąskiego okna zegarowego.
18. Worker jest multi-replica-safe i fencing-aware.
19. Cursor nie przesuwa się poza item, którego nie przyjęto trwale do inbox/quarantine.
20. External ID jest unikalny w scope provider connection/owner, nie globalnie bez kontekstu.
21. Ambiguous phone/recording/transcript match nigdy nie auto-linkuje.
22. iCal URL nie może dotrzeć do private/link-local/metadata address, także przez redirect/DNS rebinding.
23. Feed external UID jest unikalny w feedzie, nie globalnie.
24. Wszystkie czasy są zapisane UTC, a biznesowa timezone jest IANA i zachowana osobno.
25. `unknown` nigdy nie jest przedstawiane jako free/sent/healthy/success.
26. Template send przechowuje immutable version i final render snapshot.
27. Unresolved required variables blokują wysyłkę.
28. Raw provider payload i error nie trafiają automatycznie do timeline.
29. Privacy/delete propaguje się do body, attachmentów, recordingów, snippets, search/vector i derived CV artifacts.
30. Legal hold blokuje purge, ale nie przywraca dostępu użytkownikom.
31. Timeline jest rebuildable projection z globalnym cursorem.
32. Audit jest append-only i nie jest zwykłym, globalnym feedem.
33. Każda nowa migracja przechodzi `alembic upgrade heads` i ma idempotentny mirror w `backend/entrypoint.sh` zgodnie z kontraktem repo.
34. Stary i nowy dispatcher nigdy nie wysyłają równolegle tego samego kanału.
35. Security containment nie ma flagi rollback przywracającej podatny dostęp.

---

## 14. Docelowe komendy i API

### 14.1. Wspólny kontrakt komend

Nie narzucać sztucznego JSON envelope wszystkim REST endpointom.

- `Idempotency-Key` header jest wymagany dla create oraz nieodwracalnych commands/send/provider operations.
- CommandReceipt zapisuje command type, actor/client, request hash i poprzednią safe response.
- Replay tego samego key + tego samego request hash zwraca ten sam logiczny wynik.
- Ten sam key z innym body zwraca `409 IDEMPOTENCY_KEY_REUSED`.
- `If-Match` albo jawne `expected_version` jest wymagane przy zmianie wersjonowanego agregatu; stale version zwraca `409 VERSION_CONFLICT` z current version bez PII.
- PUT/DELETE po naturalnym kluczu, np. reaction, read cursor albo mark-read, pozostają naturalnie idempotentne i nie wymagają client UUID w body.
- Actor i resource scope pochodzą z auth/path/policy, nigdy z zaufanego body.
- Opcjonalny `client_context.surface` może być telemetry header/pole allowlistowane; nie wpływa na autoryzację.

### 14.2. Notifications

~~~text
GET  /api/v1/notifications?cursor=&state=&family=
POST /api/v1/notifications/{id}/mark-read
POST /api/v1/notifications/{id}/mark-unread
POST /api/v1/notifications/{id}/archive
POST /api/v1/notifications/read-batch
GET  /api/v1/me/notification-preferences
PUT  /api/v1/me/notification-preferences
~~~

### 14.3. Conversations

~~~text
GET    /api/v1/conversations/by-resource/{type}/{id}
GET    /api/v1/conversations/{id}/messages?cursor=
GET    /api/v1/messages/{id}/context?before=&after=
POST   /api/v1/conversations/{id}/messages
PATCH  /api/v1/messages/{id}
POST   /api/v1/messages/{id}/redact
PUT    /api/v1/messages/{id}/reactions/{emoji}
DELETE /api/v1/messages/{id}/reactions/{emoji}
PUT    /api/v1/conversations/{id}/read-cursor
POST   /api/v1/conversations/{id}/pins/{message_id}
DELETE /api/v1/conversations/{id}/pins/{message_id}
~~~

### 14.4. WorkItems

~~~text
POST /api/v1/work-items
GET  /api/v1/work-items?assignee=me&status=&due_before=&cursor=
GET  /api/v1/work-items/{id}
PATCH /api/v1/work-items/{id}
POST /api/v1/work-items/{id}/assign
POST /api/v1/work-items/{id}/start
POST /api/v1/work-items/{id}/complete
POST /api/v1/work-items/{id}/reopen
POST /api/v1/work-items/{id}/snooze
POST /api/v1/work-items/{id}/cancel
POST /api/v1/work-items/bulk-command
~~~

### 14.5. Email i delivery

~~~text
POST /api/v1/communications/email
POST /api/v1/communications/email/{id}/reply
GET  /api/v1/outbound-messages/{id}
GET  /api/v1/deliveries/{id}
GET  /api/v1/deliveries/{id}/attempts
POST /api/v1/admin/deliveries/{id}/retry
POST /api/v1/admin/deliveries/{id}/cancel
GET/POST/DELETE /api/v1/mailbox-delegations
~~~

API send zwraca trwałą lokalną operację `queued`; nie obiecuje jeszcze provider acceptance ani delivery:

~~~json
{
  "outbound_message_id": "...",
  "state": "queued",
  "provider_state": "not_requested"
}
~~~

### 14.6. Calendar

~~~text
POST   /api/v1/calendar/events/schedule
GET    /api/v1/calendar/events?from=&to=&cursor=
GET    /api/v1/calendar/events/{id}
POST   /api/v1/calendar/events/{id}/reschedule
POST   /api/v1/calendar/events/{id}/cancel
POST   /api/v1/calendar/events/{id}/complete
GET    /api/v1/calendar/availability
POST   /api/v1/calendar/feeds
POST   /api/v1/calendar/feeds/{id}/verify
POST   /api/v1/calendar/feeds/{id}/sync
POST   /api/v1/calendar/feeds/{id}/pause
DELETE /api/v1/calendar/feeds/{id}
~~~

`DELETE` tworzy tombstone i uruchamia audytowany purge workflow; nie usuwa natychmiast fizycznie feedu/eventów bez retention/reconciliation.

### 14.7. Templates i automation rules

~~~text
GET/POST       /api/v1/message-templates
GET/PATCH      /api/v1/message-templates/{id}
POST /api/v1/message-templates/{id}/versions
POST /api/v1/template-versions/{id}/publish
POST /api/v1/template-versions/{id}/render
GET/POST       /api/v1/automation-rules
GET/PATCH      /api/v1/automation-rules/{id}
POST /api/v1/automation-rules/{id}/activate
POST /api/v1/automation-rules/{id}/pause
POST /api/v1/automation-rules/{id}/retire
~~~

Publish/activate/pause/retire wymagają `If-Match`/expected version i AuditEntry. Immutable published TemplateVersion nie jest PATCH-owalny.

### 14.8. Timeline

~~~text
GET /api/v1/timeline/{resource_type}/{resource_id}?cursor=&types=
~~~

Timeline zwraca typed summaries, nie surowe Activity.details.

### 14.9. Integrations i operations

~~~text
GET  /api/v1/me/integrations
POST /api/v1/me/integrations/m365/connect
POST /api/v1/me/integrations/m365/sync
POST /api/v1/me/integrations/m365/disconnect

GET  /api/v1/admin/integrations
POST /api/v1/admin/integrations/{id}/sync
POST /api/v1/admin/integrations/{id}/pause
POST /api/v1/admin/integrations/{id}/resume
GET  /api/v1/admin/integrations/{id}/runs
GET  /api/v1/admin/integration-runs?state=failed,dead
GET  /api/v1/admin/dead-letter
POST /api/v1/admin/dead-letter/{id}/replay
~~~

Replay zwraca CommandReceipt. Dla Inbox tworzy `InboxReplayRequest` wskazujący
oryginalny immutable receipt; nie klonuje provider eventu i nie zmienia
terminalnego `shadow_observed`. Dla pozostałych kolejek używa jawnej retry/replay
generation opisanej przez ich state machine, z zachowaniem historycznych prób.

`POST .../disconnect` wymaga `If-Match`/expected connection version i
idempotency key. Pierwsza odpowiedź potwierdza lokalny, atomowy stan
`desired_state=disabled/configuration_state=disconnecting` oraz osobno zwraca
status asynchronicznego revoke/cleanup: `queued`, `completed`, `uncertain`,
`failed` albo `not_attempted_credentials_erased`.
`configuration_state=unconfigured` wolno
zwrócić dopiero po usunięciu credential reference i zakończeniu/świadomym
porzuceniu cleanup zgodnie z polityką. Endpoint nie może czekać bezterminowo na
providera ani przedstawiać braku odpowiedzi jako skutecznego revoke. Ponowienie
tej samej komendy zwraca ten sam CommandReceipt/ProviderOperation.

### 14.10. Realtime

~~~text
POST /api/v1/realtime/ticket
WS   /ws/v1/realtime?ticket=<opaque-one-use>
GET  /api/v1/realtime/events?after=<sequence>&limit=<bounded>
~~~

Event envelope:

~~~json
{
  "event_id": "uuid",
  "sequence": 12345,
  "type": "conversation.message.created.v1",
  "schema_version": 1,
  "resource": {"type": "candidate", "id": "42"},
  "occurred_at": "...",
  "data": {}
}
~~~

`sequence` w wire envelope pochodzi z `RealtimeEventProjection`, nie z DomainEvent. Jest monotonicznym per-recipient cursorem przydzielonym w kolejności commitów; odpowiedź catch-up zawiera `next_sequence` i `reset_required`. WebSocket ticket jest jednorazowy, krótko żyjący i powiązany z user/session; URL nie zawiera access JWT.

---

## 15. Migracja i reconciliacja danych

### 15.1. Zasada bezpieczeństwa

Migracja ma być addytywna:

1. inventory,
2. nowy schema z procesorami off,
3. deterministic backfill,
4. shadow projection,
5. parity report,
6. canary,
7. single-writer flip,
8. observation,
9. legacy read adapter,
10. dopiero później usunięcie legacy writerów.

### 15.2. Inventory przed backfillem

Raport tylko do odczytu powinien policzyć:

- simulated `email_sent`,
- Notifications unread/read i duplikaty logiczne,
- `(type, entity_id)` collisions,
- chat double notifications dla mention,
- candidate/job chat messages bez aktywnego membership,
- notes bez subjectu i notes z wieloma niespójnymi subjectami,
- global calendar events bez ownera,
- iCal UID collisions między creatorami,
- external event IDs bez owner scope,
- email provider IDs współdzielone przez mailboxy,
- private/deleted emails z istniejącymi attachment files,
- orphan files bez DB row i DB rows bez pliku,
- calls z ambiguous phone,
- recordings dopasowane time-only,
- M365 cursors bez świeżego success,
- webhook events możliwe do zidentyfikowania w logach tylko jako utracone,
- stale rejection `sending/processing`,
- `next_action_at` bez zadania,
- reminder events z niestandardowym `reminder_minutes`,
- worker desired/actual state,
- Alembic heads/schema parity.

### 15.3. Backfill Notification

- zachować legacy ID map,
- zbudować event surrogate dla historycznych records,
- ustawić `read_at` z najlepszej dostępnej informacji,
- nie zgadywać completion,
- zduplikowane mention/general oznaczyć w raporcie; nie usuwać bez polityki,
- stare linki przepisać do typed action tylko, gdy parser jest jednoznaczny.

### 15.4. Backfill Conversations

- osobna Conversation per `(context_type, context_id)`,
- mapować job/candidate messages,
- zachować original IDs/external refs,
- wygenerować deterministic `client_message_id` dla legacy,
- przenieść pins/reactions/read state/mentions,
- membership jako projekcja obecnej polityki,
- nie przywracać dostępu osobom revoked/inactive.

### 15.5. Backfill WorkItems

Pierwsze źródła:

- `JobShortlistEntry.next_action_at`,
- jawne future follow-up markers,
- pending feedback obligations,
- calendar reminders tylko wtedy, gdy nadal przyszłe,
- contract/pipeline obligations przez events z właściwego modułu.

Nie zamieniać każdej starej unread notification w Task.

### 15.6. Backfill CalendarFeed identity

- grupować iCal rows po creator/source evidence,
- przy braku pewnego feedu tworzyć `legacy_unknown`,
- collisions kierować do repair queue,
- nie nadpisywać istniejącego eventu podczas backfill,
- pełnego URL nie kopiować do jawnego pola/logu.

### 15.7. Backfill mailbox identity

- raport duplikatów przed constraint,
- provider ID scopić ownerem,
- przy niejednoznacznym ownerze quarantine,
- attachment manifest z hash/bytes/path,
- private/deleted artifacts do purge queue.

### 15.8. Backfill calls/recordings

- oznaczyć match method/confidence,
- last-nine match bez unikalności jako `ambiguous`,
- time-only recording jako `needs_review`,
- wyłączyć auto-enrichment dla ambiguous,
- zachować audit, kto dokonał repair.

### 15.9. Shadow parity

Metryki parity:

- notification recipients/type/count,
- unread projection,
- task obligations expected vs generated,
- outbound delivery created, ale niewysłane w shadow,
- calendar occurrence count,
- sync rows/cursor,
- timeline event count/order,
- worker due/backlog.

### 15.10. Cutover rule

Dla każdego kanału/provider connection routing musi być wzajemnie rozłączny i egzekwowany w query/claim:

1. historyczne shadow rows mają terminalny stan `shadow_observed/non_deliverable` i nie są claimowalne ani masowo promowane,
2. przy canary legacy worker obsługuje wyłącznie `NOT canary`, a nowy worker wyłącznie `canary`,
3. potwierdzić brak active legacy claim w canary scope,
4. atomowo przełączyć routing generation/config; wyłącznie nowe eventy po granicy powstają jako `pending/received`,
5. wykonać synthetic delivery oraz potwierdzić provider/local state,
6. rozszerzać rozłączne scope allowlisty,
7. po 100% switch zatrzymać legacy worker globalnie i potwierdzić telemetry `0`,
8. jeżeli legacy nie potrafi wykluczyć canary w samym query, nie robić częściowego canary: zatrzymać go globalnie i przełączyć nowy processor od razu 100%,
9. dla danego scope nigdy nie mogą równolegle działać legacy i new side-effect processor.

Historyczny shadow row wolno odtworzyć tylko pojedynczo po potwierdzeniu, że legacy nie wykonał side effectu; replay tworzy nowy audytowany row, nie zmienia stanu shadow. Test cutoveru potwierdza, że co najmniej 10 000 historycznych shadow rows pozostaje nieclaimowalne po zmianie routingu.

Canary oraz pełny routing cutover należą do provider/channel PR-u. PR-44 nie przełącza ponownie kanału; finalnie reconciliuje, potwierdza legacy telemetry `0` i usuwa stary kod.

---

## 16. Szczegółowy plan implementacyjny dla Claude — 45 slotów / minimum 73 osobne PR-y

### 16.1. Zasady wspólne dla każdego PR

Każdy PR musi:

1. zaczynać się ze świeżego `origin/main`, nie z lokalnego WIP,
2. sprawdzić, czy feature/fix nie został już wdrożony przez wcześniejszy PR,
3. mieć mały, jednoznaczny zakres,
4. zawierać test regresji w tym samym PR,
5. nie odkładać testów do ostatniej fali,
6. używać backendowego enforcement; ukrycie CTA nie jest zabezpieczeniem,
7. dla nowej tabeli/kolumny dodać Alembic oraz idempotentny mirror w `backend/entrypoint.sh`,
8. testować `alembic upgrade heads`, nie `head`,
9. nie wykonywać lokalnego Dockera,
10. uruchomić najmniejszy właściwy host-native check,
11. przejść required hosted CI,
12. wdrożyć przez zwykły PR/merge/deploy flow,
13. potwierdzić dokładny SHA w `/api/health`,
14. dla UI wykonać produkcyjny smoke w Chrome i screenshot,
15. mieć jawny rollback/kill switch, który nie przywraca podatności.

Nowe procesory startują jako off. Shadow write jest dozwolony wyłącznie do terminalnego stanu `shadow_observed`, którego żadne claim query nie może pobrać. Cutover zmienia routing generation dla nowych eventów, nigdy masowo nie promuje historycznych shadow rows. Dual send jest zabroniony.

### 16.2. Obowiązkowy podział szerokich slotów

Numery `PR-00..PR-44` określają kolejność i wspólny gate. Poniższe szerokie sloty nie są pojedynczymi pull requestami: Claude ma utworzyć oddzielne branche, diffy, CI, deploye i production verification dla każdego suffixu. Pozostałe 30 slotów są pojedynczymi PR-ami. Daje to łącznie minimum 73 osobno mergowane PR-y.

Arytmetyka: 15 splitowanych slotów daje 43 suffix PR-y, plus 30 niesplitowanych = 73.

| Slot | Obowiązkowe osobne PR-y |
|---|---|
| PR-04 | `04a` template render access; `04b` Notes access/pagination/count; `04c` Calendar ACL |
| PR-05 | `05a` mailbox read/delegation; `05b` compose/reply/bulk send ACL; `05c` calls/transcript/recording ACL |
| PR-06 | `06a` CloudTalk agent admin; `06b` Fireflies method/owner/access; `06c` CloudTalk webhook route/HMAC/replay containment |
| PR-08 | `08a` private/delete artifact inventory + purge foundation; `08b` recording matching quarantine/proxy |
| PR-09 | `09a` SMTP verified TLS; `09b` Activity/UserActivity redaction/pagination |
| PR-19 | `19a` connection lease/serialization; `19b` cursor item integrity; `19c` mailbox-scoped external IDs; `19d` server-side OAuth/PKCE state; `19e` durable initial/manual sync requests + M365 inbox processor canary |
| PR-22 | `22a` Teams outbox; `22b` Slack outbox; `22c` chat fallback outbox |
| PR-24 | `24a` CloudTalk watermark/initiate/enrichment; `24b` Fireflies durable account/cursor/retention; `24c` LinkedIn/Proxycurl lease/retry/budget |
| PR-34 | `34a` Conversation schema/API; `34b` candidate chat migration; `34c` job chat migration i cutover |
| PR-36 | `36a` MessageTemplate/TemplateVersion; `36b` AutomationRule builder/approval/fan-out controls |
| PR-37 | `37a` Communication Hub backend/composer contract; `37b` Hub UI i legacy email CTA cutover |
| PR-38 | `38a` Timeline projection/cursor/redaction; `38b` Artifact/RetentionManifest/purge graph |
| PR-39 | `39a` Integration Control Plane backend/snapshot/health; `39b` personal vs admin Settings UI |
| PR-40 | `40a` Notification Center/bell; `40b` Calendar/chat mobile+a11y; `40c` My Work/Hub cross-surface a11y/design cleanup |
| PR-44 | `44a` final reconciliation reports; `44b` potwierdzenie routing cutovers i legacy telemetry=0; `44c` usunięcie legacy read/write/API; `44d` retention/purge data cleanup; `44e` runbook/ADR/flag cleanup |

Jeżeli którykolwiek z pozostałych PR-ów przekracza jedną odwracalną zmianę lub jeden provider, Claude ma go dodatkowo rozbić. Liczba 73 jest minimum, nie limitem.

### 16.3. Zewnętrzny gate Modułu 4 dla stage-aware automations

Core Modułu 6 ma minimum 73 PR-y. Następujące upstream prerequisite'y nie są
wliczone, ponieważ należą do wdrażanego równolegle Modułu 4 i mogą już powstać
w jego PR-06/07. Claude ma zweryfikować je przed stage-aware częścią PR-26,
PR-29, PR-36b i PR-38:

1. **M4-WF-A — semantic consistency:** validator i testy zgodności
   `semantic_key` z `is_terminal/terminal_type`.
2. **M4-WF-B — edge integrity:** composite FK endpointów do tej samej rewizji,
   partial unique entry edge i preflight/migration/entrypoint mirror.
3. **M4-WF-C — runtime readiness:** osobny `runtime_status=eligible`, zero
   unmapped, zwalidowany graf, command-service cutover oraz committed transition
   event z workflow/stage revision i registry version.

Jeżeli któregoś gate brakuje, nie wolno implementować go po cichu wewnątrz
dużego PR-u Modułu 6. Należy utworzyć albo poczekać na osobny PR pod ownership
Modułu 4. Wtedy łączna liczba PR-ów może wzrosnąć do minimum 76; pozostałe,
niezależne flow Modułu 6 nie są przez to blokowane.

---

### Fala A — natychmiastowy containment i safety gate

#### PR-00 — Read-only inventory i communications safety lane

Cel:

- mieć mierzalny baseline przed zmianą danych,
- sprawić, aby krytyczne istniejące testy były rzeczywiście required.

Zakres:

- endpoint/skrypt admin-only generujący inventory z sekcji 15.2,
- żadnych repair writes,
- osobny automatycznie odkrywany pytest marker/job `communications-safety`,
- sentinel: każdy nowy test modułu communications/integrations/work/calendar/realtime musi wejść do required job albo mieć jawny live/manual manifest; nie dopisywać ręcznej listy plików,
- dodać istniejące testy notifications, presence, job chat, note mentions, rejection scheduler, Teams, CloudTalk i M365 recording,
- sentinel wykrywający test files z tego manifestu, które nie są uruchamiane.

Pliki startowe:

- `.github/workflows/ci.yml`,
- `backend/tests/`,
- `backend/app/api/admin_*`,
- `backend/app/main.py` dla routera.

Acceptance:

- inventory działa bez mutacji,
- wynik nie zawiera raw body/PII,
- required CI uruchamia wskazany safety subset,
- nowy oznaczony test automatycznie blokuje merge bez edycji workflow,
- błędny test z tego obszaru blokuje merge.

Rollback:

- endpoint może zostać wyłączony capability/flagą; required tests pozostają.

#### PR-01 — Wyłączenie fałszywego email success

Cel: natychmiast zakończyć kłamliwy flow.

Zakres:

- usunąć primary action prowadzącą do `SendEmailV2` lub skierować ją do realnego M365 compose,
- trwale usuwany `/api/emails/send` zwraca `410 Gone`; czasowe `503` wolno zwrócić wyłącznie z nowego realnego endpointu, gdy provider jest niedostępny,
- nie zapisuje `email_sent`,
- usunąć hardcoded preview job/date/rate,
- UI rozróżnia draft, queued, provider accepted, sent, delivered, failed i uncertain oraz używa copy z P0.1,
- inventory historycznych simulated records.

Testy:

- endpoint nie zwraca success bez providera,
- UI nie pokazuje „wysłano” dla `queued/simulated`,
- unresolved required variables blokują send,
- brak nowego `Activity(email_sent, simulated=true)`.

Rollout:

- bez feature flag przywracającej symulator,
- jeżeli M365 UI nie jest gotowe, CTA ma być disabled z jasnym komunikatem.

#### PR-02 — Naprawa unread count, mark-all i podstawowego kontraktu notification

Cel: przywrócić prawdę badge/read state.

Zakres:

- `is_(False)` w trzech query,
- bounded `limit` z walidacją,
- affected row count dla read-all,
- owner-only regression,
- rozdzielić server unread od ulotnego WS delta,
- frontend error/loading zamiast empty.

Testy:

- mixed read/unread count,
- mark one i mark all,
- cudzej notyfikacji nie można zmienić,
- 100+ badge,
- query error pokazuje retry.

Rollback: zwykły revert jest możliwy wyłącznie do poprawnej wcześniejszej wersji; nie wracać do `WHERE false`.

#### PR-03 — Bezpieczny realtime ticket i presence access

Cel: usunąć JWT z URL i IDOR presence.

Zakres:

- DB-backed `RealtimeTicket` z hashem, TTL, session/audience i atomowym one-use consume; żadnego RAM replay set,
- wspólny resource access check dla HTTP i WS,
- payload presence bez emaila,
- unsubscribe po revocation,
- connection metrics,
- legacy query-token endpoint wyłączyć w tym samym produkcyjnym release; stary cached frontend dostaje fail-closed i wymuszony reload, bez okna z JWT w URL.

Testy:

- WebSocket URL bez access JWT,
- ticket replay/expiry/wrong user,
- issue na replice A, consume na B oraz dwa równoległe consume — dokładnie jeden sukces,
- candidate/job A vs obcy B,
- inactive user,
- revocation mid-session,
- HTTP i WS mają ten sam wynik policy.

Rollout:

- frontend i backend ticket path są wdrażane w skoordynowanym release, a produkcyjna konfiguracja od razu odrzuca legacy query token,
- security rollback oznacza wyłączenie realtime, nie przywrócenie JWT URL.

#### PR-04 — Template, Notes i Calendar resource-scope containment

Cel: zamknąć trzy IDOR-y o wspólnym źródle.

Zakres:

- centralny `CommunicationResourceAccess`, wykorzystujący istniejące candidate/job/client membership,
- renderer template wymaga PII capability i subject access,
- Notes wymaga subject, cursor/limit i redaguje author email,
- Calendar owner/resource/visibility projection,
- recording field wyłącznie z sensitive capability,
- create relacje walidowane server-side.

Test matrix:

- każda rola × owner/member/non-member,
- list/detail/create/update/delete/render,
- brak count/name oracle,
- manual URL/ID tampering,
- admin break-glass audit.

Rollback:

- przy problemie UI ukryć surface lub zawęzić capability; nie wracać do globalnego read.

#### PR-05 — Mailbox, compose/reply/bulk i calls access containment

Cel: uniemożliwić viewerowi send i globalny odczyt cudzej skrzynki/calls.

Zakres:

- `OperationalCommunicationWrite`,
- candidate/job scope dla compose/reply/link,
- mailbox owner-only domyślnie,
- minimalny `MailboxDelegation` read/send z expiry/reason,
- calls list/create/initiate po candidate access,
- transcript/recording osobna capability,
- provider URL usunięty z normalnego DTO.

Testy:

- viewer 403,
- DL bez delegacji 403 do cudzej skrzynki,
- aktywna/cofnięta delegacja,
- obcy candidate B,
- download attachment i recording proxy,
- recipient tampering.

Rollout: w razie braku delegacji cudze mailbox reads świadomie przestaną działać; to poprawne security containment.

#### PR-06 — CloudTalk/Fireflies admin containment i CloudTalk webhook secret

Cel: zamknąć globalne operacje i secret-in-path.

Zakres:

- CloudTalk list/map/sync admin-only,
- aktywny target user i audit mapping,
- Fireflies global sync jako POST `AdminUser`,
- transcript list po resource scope,
- usunąć `/webhook/{token}`,
- HMAC header, body limit i rate limit,
- jeśli CloudTalk dostarcza podpisany timestamp/event ID: bounded timestamp window + minimalny durable fingerprint ledger,
- jeśli provider nie daje wiarygodnego replay key: endpoint pozostaje `503` i `CLOUDTALK_ENABLED=false` do generic durable Inbox z PR-11/23; nie deklarować pełnej replay protection opartej tylko o RAM,
- rotacja sekretu i runbook log retention.

Testy:

- viewer/recruiter nie mapują agentów ani nie uruchamiają Fireflies,
- zły/brak HMAC i replay,
- secret path 404/410,
- Fireflies obcy transcript niewidoczny.

Rollback:

- `CLOUDTALK_ENABLED=false` / `FIREFLIES_SYNC_ENABLED=false`,
- nigdy nie przywracać token-path.

Ewolucja: `06c` jest containment v1. Minimalne fingerprint rows, jeśli powstaną, są migrowane/backfillowane do `InboxItem` w PR-23; nie utrzymywać dwóch aktywnych replay ledgers.

#### PR-07 — SSRF-safe CalendarFeed i scoping external UID

Cel: zabezpieczyć iCal bez czekania na pełny calendar rewrite.

Zakres:

- `CalendarFeed` z ownerem i encrypted URL,
- centralny safe fetcher,
- HTTPS, IP/DNS/redirect validation,
- response/time/event limits,
- server-owned source identity,
- unique `(feed_id, external_uid)`,
- masked response/logging.

Testy:

- loopback, RFC1918, link-local, IPv6 ULA, metadata host,
- redirect do private IP,
- DNS resolution policy,
- oversized body/event bomb,
- dwóch userów z tym samym UID,
- URL token nie pojawia się w log/response.

Migracja:

- addytywna, stary endpoint może tworzyć feed adapter,
- legacy collisions tylko raportować.

#### PR-08 — Private/delete artifact purge i recording quarantine

Cel: zatrzymać trwałe wycieki plików i błędne auto-attach.

Zakres:

- minimalny `ArtifactManifest`/purge queue,
- public→private i Graph `@removed` tworzą purge obligation,
- delete bytes + rows + derived refs,
- time-only recording fallback disabled,
- ambiguous recording do review queue,
- download/proxy sprawdza purge/legal hold state.

Testy:

- bytes istnieją przed, nie istnieją po purge,
- retry po filesystem error,
- legal hold,
- orphan file inventory,
- overlapping meetings nie auto-attachują.

Rollback:

- przy problemie z purge zatrzymać worker i zablokować dostęp; nie przywracać publicznego URL/time-only attach.

#### PR-09 — SMTP TLS fail-closed i activity feed redaction

Cel: zabezpieczyć kanał SMTP i zatrzymać raw detail leak.

Zakres:

- `ssl.create_default_context()`,
- `SMTP_REQUIRE_TLS=true` w prod,
- jawny SMTPS/STARTTLS mode,
- safe errors,
- `PublicActivityProjection` allowlist,
- security/provider details tylko audit/admin.

Testy:

- valid/bad CA/bad hostname/no STARTTLS,
- brak credential/body w logu,
- operational user nie widzi raw security details,
- admin audit ma bezpieczne, potrzebne pola.

Rollout: przy niezgodnym SMTP wyłączyć SMTP; nie luzować TLS.

### Gate po Fali A

- zero simulated success,
- unread badge/read-all działają,
- JWT nie występuje w WebSocket URL,
- viewer nie renderuje PII i nie wysyła,
- notes/calendar/calls/mailbox mają resource scope,
- CloudTalk mapping/Fireflies sync są admin-only,
- secret path wyłączony,
- iCal SSRF tests zielone,
- time-only recording attach wyłączony,
- safety lane blokuje regresję.

---

### Fala B — wspólny kernel trwałości

#### PR-10 — DomainEvent i bezpieczny AuditEntry

Cel: jedno źródło committed facts bez zastępowania tabel domenowych.

Zakres:

- schemat DomainEvent, CommandReceipt i AuditEntry z sekcji 11.1–11.2,
- schema registry i event envelope,
- transaction helper,
- correlation/causation/idempotency,
- payload size/sensitivity/retention validation,
- append-only enforcement aplikacyjne i DB permissions, jeśli możliwe.

Testy:

- command replay same hash zwraca receipt; reused key z innym hash daje 409,
- jedna komenda emituje wiele eventów z unikalnym ordinal bez duplikatu,
- payload schema/version,
- rollback nie zostawia eventu,
- audit redaction,
- event zapisany w tej samej transakcji co przykładowa mutacja.

Rollout: shadow event emission dla jednego niskiego ryzyka flow; brak procesorów.

#### PR-11 — Outbox, Inbox, Delivery/Attempt i foundation integracji

Cel: trwałe jednostki pracy inbound/outbound.

Zakres:

- tabele z sekcji 11.3, 11.4, 11.7, 11.8, 11.9a, dormant `ReminderSchedule` z 11.15 oraz minimalne `IntegrationConnection/SyncCursor/IntegrationRun` z 11.21–11.22,
- indexes/state constraints,
- unique logical keys,
- safe error fields,
- retention timestamps,
- admin read-only queue diagnostics.

Testy:

- unique event/handler,
- duplicate webhook fingerprint,
- niezależne deliveries per channel,
- state constraints,
- migration on existing DB.

Rollout: wszystkie processors off.

`ReminderSchedule` w tym PR jest wyłącznie wspólną addytywną schema/constraint foundation. PR-29 zacznie zapisywać WorkItem recurrence/escalation rows, a PR-31 uruchomi wspólny leased due dispatcher i rozszerzy go na CalendarEvent. Dzięki temu nie istnieje odwrócona zależność PR-29→PR-31.

`template_ref` pozostaje nullable stringiem bez FK, ponieważ TemplateVersion powstaje dopiero w PR-36a; PR-36a dodaje FK, backfill i constraint po parity. `WorkerLease` powstaje w PR-12, a registry/heartbeat w PR-15. PR-39 wyłącznie konsumuje i prezentuje te foundation encje.

#### PR-12 — Distributed lease, fencing i generic dispatchers

Cel: multi-replica-safe processing.

Zakres:

- DB time acquire/renew/release,
- fencing token,
- `FOR UPDATE SKIP LOCKED`,
- retry with exponential backoff+jitter,
- pre-call persisted DeliveryAttempt intent i unresolved-attempt reconciliation gate,
- ProviderOperationAttempt z retry generation oraz reaperem patrzącym wyłącznie
  na unresolved attempt bieżącej generacji,
- dead-letter,
- graceful cancellation,
- feature flags processors off.

Testy fault-injection:

- dwa workery jeden claim,
- crash po claim,
- crash po attempt intent przed request oraz po provider acceptance przed outcome commit,
- lease expiry/takeover,
- expired lease z unresolved attempt przechodzi do uncertain/reconcile, nie blind resend,
- ProviderOperation attempt #1 retryable failure, generation #2 i crash przed
  utworzeniem intentu #2 kończy się reclaimem, nie fałszywym `uncertain`,
- manualny replay InboxItem tworzy InboxReplayRequest i nie łamie unique
  `(provider, connection_key, provider_event_id)`,
- stary fencing token nie zapisuje,
- poison item dead,
- manual replay audit.

#### PR-13 — Notification projection, canonical dedupe i typed registry

Cel: zbudować Notification v2 jako projekcję eventu.

Zakres:

- new schema/read adapter,
- unique `(event, recipient)`,
- agregacja wyłącznie przez NotificationDigest + NotificationDigestItem, bez
  escape hatch osłabiającego bazową unikalność,
- typed family/action registry,
- mention overrides general,
- exhaustive frontend presentation metadata,
- shadow compare z legacy notifications.

Testy:

- entity types o tym samym numeric ID nie kolidują,
- concurrent projector,
- mention single notification,
- równoległy rebuild digestu nie duplikuje Notification ani DigestItem,
- unknown event bez fałszywego candidate icon,
- rebuild projection daje ten sam wynik.

Rollout: shadow read/admin parity, bez user cutover.

#### PR-14 — NotificationPreference, quiet hours i digest

Cel: jawna polityka recipient/channel.

Zakres:

- preference schema/API,
- mandatory registry,
- timezone/quiet hours/DST,
- immediate/digest/off,
- NotificationDigest schedule/window i idempotentne przypięcie kanonicznych
  Notification przez join,
- vacation/delegation policy decyzja jawna,
- dispatcher re-check active/access/preferences.

Testy:

- mandatory nie można wyłączyć,
- quiet hours przez midnight i DST,
- revoked/inactive skip,
- digest dedupe,
- replay tego samego eventu i rebuild tego samego okna nie zmieniają liczby
  bazowych Notification,
- channel classification mismatch skip.

Rollout: początkowo preferences wpływają tylko na nowy testowy family.

#### PR-15 — Worker registry i supervisor observe-only

Cel: zastąpić mylące `running/expected` prawdziwym stanem.

Zakres:

- deklaratywny registry wszystkich tasków,
- manifest 24/24 z ownerem, feature flagą, schedule, side-effect classification oraz wymaganą strategią `single global lease | partition lease | idempotent multi-run | one-shot disabled`,
- desired/runtime state, reason, heartbeat, last success/error, next due,
- backlog/oldest/dead counts z adapterów,
- safe shutdown collect exceptions,
- supervisor bez auto-restart na start,
- snapshot multiple Alembic heads i wspólny deployedAt source.

Testy:

- disabled != failed,
- crashed pokazuje exception code,
- stale heartbeat,
- task spoza registry failuje test,
- shutdown zawsze dispose engine,
- multiple Alembic heads są listą.

Acceptance: żaden z 24 tasków nie może pozostać jako „do późniejszej klasyfikacji”. PR-15 nie musi od razu dodać lease do każdego legacy workera, ale registry ma wskazać konkretny późniejszy PR/owner; final gate blokuje cutover, jeśli enabled side-effecting worker nadal nie ma bezpiecznej strategii współbieżności.

Rollout: observe-only; nowe checks początkowo informational.

### Gate po Fali B

- migracje addytywne i idempotentne,
- processors off poza test/canary,
- concurrency/fencing tests zielone,
- notification shadow parity raportowana,
- snapshot rozróżnia disabled/crashed/running,
- brak produkcyjnego dual-send.

---

### Fala C — migracja kanałów i integracji na trwały kernel

#### PR-16 — OutboundMessage, MailboxDelegation i M365 send state machine

Cel: realny email z persisted intent przed providerem.

Zakres:

- encje 11.9–11.10: jeden OutboundMessage = jeden provider envelope, OutboundRecipient dla TO/CC/BCC, OutboundBatch dla bulk,
- business idempotency key,
- provider draft/message ID,
- owner-scoped mailbox identity,
- state `unknown` i reconciliation,
- compose/reply używa command service,
- legacy adapter zwraca nowy operation status.

Testy:

- double click/retry,
- two valid messages same subject/minute,
- timeout after provider accept,
- owner/delegate scopes,
- disconnected/reconnect/401/429/5xx,
- no false `sent`.
- jeden Graph request z wieloma TO/CC/BCC nie tworzy kilku envelope sends; per-recipient receipts są opcjonalnymi outcomes,
- bulk partial success należy do OutboundBatch, a każdy child message ma własny stan.

Rollout: canary per mailbox owner; stary send zatrzymany dla canary.

#### PR-17 — Rejection email claim/CAS, provider draft i reconcile

Cel: zamknąć duplicate/cancel race.

Zakres:

- atomic claim bez długiego DB lock podczas sieci,
- cancel CAS,
- provider draft przed send,
- `uncertain` state,
- Sent Items reconciliation,
- dead-letter/manual resolution,
- mapping do OutboundMessage/Delivery; każde wywołanie dopisuje immutable DeliveryAttempt.

Testy:

- dwóch dispatcherów,
- cancel przed send i w trakcie,
- crash po draft,
- crash po provider acceptance przed commit,
- reconcile sent/not sent.

Rollout: jedna canary rejection, następnie allowlist; nigdy dwa dispatchery.

#### PR-18 — M365 durable webhook ingress i shadow dirty-generation

Cel: commit przed 202 i trwałe shadow coalescing bez uruchamiania syncu przed lease/cursor protection.

Zakres:

- webhook zapisuje inbox,
- DB failure zwraca retryable 5xx,
- dirty generation per connection/resource,
- kolejne update tego samego resource nie są blokowane 24 h,
- rows pozostają terminalne `shadow_observed/non_deliverable`; processor jest bezwzględnie off,
- payload retention.

Testy:

- restart po commit przed 202,
- duplicate notification,
- dwie kolejne zmiany jednego message,
- burst coalescing,
- shadow parity oraz test, że dispatcher nie claimuje ani nie promuje `shadow_observed`.

Rollout: wyłącznie shadow inbox. Canary processing jest zabroniony do zakończenia PR-19a (lease) i PR-19b (cursor); uruchamia go dopiero PR-19e dla rozłącznego connection scope.

#### PR-19 — M365 leases, cursor integrity, owner-scoped IDs i OAuth state

Cel: zabezpieczyć pełny sync lifecycle.

Zakres:

- lease per connection dla poll/manual/webhook/backfill,
- cursor nie przesuwa się poza failed item,
- poison item queue,
- composite unique message/event identity,
- server-side PKCE verifier i opaque state,
- durable initial/manual sync request w osobnym `19e`,
- po 19a/19b/19e: routing generation kieruje wyłącznie nowe webhooki canary od razu do `received`; historyczne `shadow_observed` pozostają terminalne, a processor uruchamia serialized sync tylko dla nowych rows.

Testy:

- parallel sync paths,
- failed item/restart/replay,
- dwa mailboxy ten sam provider ID,
- state replay/expiry/wrong user,
- OAuth callback restart.

Rollout: preflight collision report przed constraint; następnie connection allowlist z rozłącznym routingiem legacy/new. Bez 19a i 19b nie wolno aktywować processora.

#### PR-20 — M365 subscription i recording lifecycle v2

Cel: poprawić webhook freshness i bezpieczne nagrania.

Zakres:

- unique active subscription per connection/resource,
- leased renewal/recreate,
- expiry risk state,
- strong meeting/recording identity,
- paginowany discovery,
- ambiguity review queue,
- artifact proxy handles.

Testy:

- dwa renewal workery,
- Graph partial failure,
- overlapping meetings,
- recording beyond first page,
- review decision auth/audit,
- revoked signed handle.

#### PR-21 — SMTP/auth/mention delivery przez outbox

Cel: usunąć synchroniczny best-effort SMTP.

Zakres:

- auth/security/mention email tworzą logiczny Delivery; worker dopisuje DeliveryAttempt per provider call,
- SMTP adapter z TLS z PR-09,
- retry/DLQ,
- anti-enumeration response bez zmian,
- mention side effects jako jeden committed event,
- re-check access/active/preferences.

Testy:

- SMTP timeout bez blokowania requestu,
- retry i exactly-one logical delivery,
- mark read/revoke przed dispatch,
- anti-enumeration timing/shape,
- no PII in errors.

Zależności: PR-09, PR-11/12 i PR-14; access/active/preferences są ponownie sprawdzane przed każdym claim/dispatch.

#### PR-22 — Teams, Slack i chat fallback przez outbox

Cel: usunąć untracked taski i RAM dedupe.

Zakres:

- wszystkie `notify_teams` call sites emitują event w transakcji,
- Slack `raise_for_status` i persisted dedupe,
- chat fallback jako claimed delivery,
- provider response IDs/status,
- channel classification.

Testy:

- 4xx/5xx nie oznacza sent,
- restart/two replicas,
- jeden failed channel nie cofa innych,
- mention tylko jeden fallback,
- batch failure isolation.

Rollout: aktywować kolejno Teams, Slack, chat fallback; synthetic per channel.

#### PR-23 — CloudTalk durable inbox, ambiguous resolution i atomic upsert

Cel: trwały i poprawny call lifecycle.

Zakres:

- webhook commit-before-2xx,
- replay ledger,
- `matched/ambiguous/unmatched`,
- atomic upsert po `cloudtalk_call_id`,
- transcript/recording update niezależnie od phone,
- initiated→final reconcile,
- manual resolution audit.

Testy:

- duplicate webhook/poller race,
- shared phone,
- transcript without phone,
- new transcript version,
- ambiguous no enrichment,
- body/replay limits.

Rollout: processor canary per agent; przy problemie CloudTalk off.

#### PR-24 — CloudTalk watermark, Fireflies durable sync i Proxycurl control

Cel: domknąć trzy kosztowne/podatne schedulery wspólnym wzorcem.

Zakres:

- CloudTalk per-account overlap watermark i full pagination success,
- initiate idempotency i transcript-hash enrichment,
- Fireflies IntegrationConnection/cursor/unique external ID/lease/retention,
- Proxycurl bounded retry, last attempt vs success, lease/circuit breaker/budget,
- osobne flags/canaries dla każdego providera.

Testy:

- late CloudTalk call,
- failed page nie przesuwa watermark,
- Fireflies parallel sync bez duplikatu,
- ambiguous participant quarantine,
- Proxycurl two workers one paid call,
- 429 breaker i hard budget.

Uwaga o zakresie: zgodnie z sekcją 16.2 są to obowiązkowo trzy osobne PR-y 24a/24b/24c, każdy z osobnym canary, kosztem i rollbackiem.

### Gate po Fali C

- wszystkie external side effects migrowane w Fali C mają persisted operation/delivery; Calendar/reminders przechodzą ten sam gate dopiero w Fali E,
- M365 ingress commit przed 202,
- cursor gaps widoczne i retryable,
- rejection crash/cancel tests zielone,
- Teams/Slack/SMTP/chat fallback bez dual-send,
- CloudTalk ambiguous nie auto-linkuje,
- Fireflies ma owner/cursor,
- Proxycurl ma lease i budżet.

### Fala D — zadania człowieka i domknięcie pętli działania

#### PR-25 — Kanoniczny `WorkItem` i polityka dostępu

Cel: utworzyć jedno źródło prawdy dla zadania, follow-upu, przypomnienia i obowiązku człowieka.

Zakres:

- addytywna tabela `work_items` zgodna z sekcją 11.14,
- `work_item_assignees`, jeżeli produkt potwierdzi współdzieloną odpowiedzialność; do tego czasu dokładnie jeden `assignee_user_id`,
- `work_item_events` albo DomainEvent jako audyt każdej zmiany stanu,
- atomowy optimistic locking przez `version`,
- capability oraz subject/resource scope na list, get i każdej komendzie,
- indeksy dla `assignee_user_id/state/due_at`, subject oraz idempotency key,
- API create/list/get/assign/start/complete/reopen/snooze/cancel,
- idempotency key na create i expected version na mutacje,
- feature flag `WORK_ITEMS_ENABLED=false`.

Testy:

- pełna macierz ról i ownership/resource scope,
- użytkownik nie może przypisać zadania do nieaktywnego albo niedostępnego usera,
- dwa równoczesne complete nie tworzą dwóch efektów,
- stale version daje `409`, a nie last-write-wins,
- filtry i cursor są stabilne przy identycznym `due_at`,
- create retry zwraca istniejący rekord.

Migracja/rollback:

- addytywna migracja + idempotentny mirror w `backend/entrypoint.sh`,
- schema pozostaje po rollbacku, flaga off,
- nie migrować jeszcze legacy obligations; zrobi to PR-26.

Acceptance:

- WorkItem może bezpiecznie istnieć w produkcji bez wpływu na stare flow,
- WorkItem, CommandReceipt, AuditEntry i DomainEvent są zapisywane atomowo w tej samej transakcji i stają się widoczne dopiero po commicie,
- żadna lista nie jest globalna bez jawnej capability.

#### PR-26 — Bridge i backfill istniejących obowiązków

Cel: zmapować istniejące `next_action_at`, rejected email, interview feedback i contract alerts na WorkItem bez podwójnego źródła prawdy.

Zakres:

- read-only inventory liczby i jakości legacy obligations,
- deterministyczne klucze: legacy
  `source_type/source_id/source_policy_key/source_policy_version`, a dla eventów
  `source_event_id/source_policy_key/source_policy_version`,
- shadow backfill dla:
  - `JobShortlistEntry.next_action_at`,
  - oczekującego interview feedback,
  - zaplanowanych rejection emails wymagających kontroli,
  - follow-upów wynikających z candidate/client workflow,
  - wybranych alertów kontraktowych,
- dla workflow rekrutacyjnego reuse istniejących
  `WorkflowRevision/StageRevision/semantic_key/sla_max_days` z Modułu 4;
  WorkItem powstaje dopiero z committed transition eventu zawierającego process,
  workflow revision i stage revision, nigdy z samego shadow registry,
- deterministyczny key workflow-derived WorkItem opiera się na transition event/
  process instance + policy version; sam `stage_revision_id` nie wystarcza, bo
  wiele procesów legalnie przechodzi przez ten sam etap,
- jednokierunkowy bridge legacy→WorkItem tylko przed per-source writer cutover,
- per-source single-writer switch: przed cutover WorkItem jest shadow/read-only; po cutover legacy field staje się adapterem/read-only albo zapisuje wyłącznie przez WorkItem command service,
- writer telemetry rozróżnia legacy/new i blokuje równoległe aktywne źródła,
- reconciliation report: missing, duplicate, conflicting due date, inaccessible assignee,
- żadnego WorkItem dla czysto informacyjnego alertu,
- flaga per source, nie jeden globalny switch.

Testy:

- rerun backfill jest idempotentny,
- zmiana legacy due aktualizuje ten sam otwarty WorkItem,
- completed/cancelled WorkItem nie jest wskrzeszany bez jawnej reguły,
- deleted/revoked subject zamyka lub redaguje zadanie,
- brak assignee trafia do jawnej kolejki triage, nie do losowego admina.

Rollout:

Źródło workflow-derived pozostaje off, dopóki Moduł 4 nie przełączy runtime na
wersjonowany command service i nie emituje committed transition eventu z
revision IDs. Nie blokuje to migracji pozostałych źródeł PR-26.

1. inventory,
2. dry-run CSV/JSON bez PII,
3. shadow-write jednego źródła,
4. parity przez minimum pełen cykl,
5. UI może czytać WorkItem,
6. dla jednego source przełączyć writer atomowo i dopiero wtedy włączyć mutacje UI,
7. potwierdzić, że późniejsza zmiana legacy nie nadpisuje ani nie wskrzesza WorkItem.

#### PR-27 — „Moja praca” i kontekstowe zadania w UI

Cel: dać użytkownikowi jedną kolejkę pracy zamiast polowania po bellu, kalendarzu i profilach.

Zakres:

- strona `/work` z zakładkami `Dzisiaj`, `Zaległe`, `Nadchodzące`, `Zakończone`,
- cursor pagination, server-side filters, sort `due_at/id`,
- widok listy oraz mobilna agenda; bez ciężkiego kanbana w pierwszym wydaniu,
- szybkie `Rozpocznij`, `Zakończ`, `Odłóż`, `Przypisz`,
- mutacje produkcyjne aktywne wyłącznie dla source'ów, które przeszły single-writer gate PR-26; pozostałe są read-only z jasnym komunikatem,
- optimistic UI wyłącznie z rollbackiem po `409/403`,
- kontekst subject jako bezpieczny link, bez kopiowania PII do URL,
- sekcja zadań na profilu kandydata, stanowiska i klienta,
- jawne stany loading/empty/error/offline,
- token-first components z istniejącego `frontend/src/components/ds/`.

Testy:

- stale optimistic update wraca do stanu serwera,
- keyboard-only i focus po modalach,
- mobile 320/375/768 px,
- deep link do WorkItem po refreshu,
- brak obcego subject snippet w odpowiedzi 403/404,
- duża lista nie robi N+1.

Acceptance:

- użytkownik może znaleźć i zakończyć własne zadanie w maksymalnie dwóch interakcjach,
- error nie wygląda jak pusty inbox,
- UI nie zakłada, że notification jest zadaniem.

#### PR-28 — Actionable notifications jako delegacja do komendy WorkItem

Cel: bell ma prowadzić do trwałej komendy, a nie implementować drugi system workflow.

Zakres:

- typed action registry po `notification_type/schema_version`,
- akcje `complete`, `snooze`, `open subject`, `open conversation`,
- notification wskazuje `work_item_id`, jeśli alert wymaga pracy,
- action endpoint wykonuje WorkItem command i aktualizuje notification w jednej transakcji albo przez niezawodny event,
- kliknięcie dwa razy ma jeden efekt,
- read/archived nie oznacza completed,
- poprawa kontraktu interview confirmation/feedback,
- cold-load routing bez zależności od lokalnego stanu komponentu.

Testy:

- retry action,
- revoked access pomiędzy utworzeniem alertu i kliknięciem,
- completed elsewhere,
- deep link z emaila i po refreshu,
- action failure pozostawia czytelny stan i możliwość retry,
- click bell nie wywołuje niejawnej mutacji poza zadeklarowaną akcją.

#### PR-29 — Recurrence, escalation i polityki due

Cel: modelować cykliczną pracę i eskalację bez wąskich okien czasowych.

Zakres:

- jawna IANA timezone i lokalna semantyka due,
- ograniczony, walidowany recurrence contract; bez dowolnego wykonywalnego DSL,
- generator następnego wystąpienia po commicie poprzedniego,
- persisted escalation rows w dormant `ReminderSchedule` dostarczonym przez PR-11,
- reguły `overdue`, `unassigned`, `not acknowledged`,
- quiet hours i weekend calendar według odbiorcy/zespołu,
- escalation recipients przez PolicyService, nie adres z payloadu,
- limit generacji i horizon, aby błędna reguła nie utworzyła milionów rekordów,
- audit wersji reguły.
- dla stage-derived due policy użycie opublikowanego
  `StageRevision.sla_max_days` i `workflow_revision_id` zamiast drugiej tabeli
  SLA; zmiana workflow wpływa wyłącznie na nowe transition events, nie przelicza
  historycznych WorkItem bez jawnej migracji.

Testy:

- DST spring/fall, zmiana timezone, weekend i święto,
- downtime i catch-up,
- complete tuż przed escalation,
- edycja recurrence nie zmienia historycznych wystąpień,
- rule explosion guard,
- dwóch schedulerów z lease.

Rollout: PR-29 może generować terminalne `shadow_observed` schedules do parity, ale nie wysyła ich ani później nie promuje. Delivery pozostaje off do wspólnego due dispatchera z PR-31; do tego momentu legacy alert pozostaje jedynym active senderem.

Zależności: PR-11/12, PR-14 preferences/quiet hours i PR-25 WorkItem.

### Gate po Fali D

- legacy obligation parity jest mierzalne i bez duplikatów,
- WorkItem ma pełny object-level access i optimistic locking,
- „Moja praca” działa desktop/mobile/keyboard,
- notification action deleguje do kanonicznej komendy,
- downtime nie gubi recurrence ani escalation,
- żaden informacyjny alert nie staje się automatycznie zadaniem.

### Fala E — kalendarz, rozmowy i realtime

#### PR-30 — Jedna usługa scheduling i jeden model `CalendarEvent`

Cel: scalić generic Calendar i M365 scheduling w jeden kontrakt domenowy.

Zakres:

- `CalendarEvent`, `EventParticipant` i `EventOccurrence`,
- create/update/cancel przez command service,
- provider adapter opcjonalny: manual/local albo M365,
- state `scheduled/cancelled/completed`, version i owner/visibility,
- capability + subject scope + attendee minimization,
- create/update/cancel providera jako persisted `ProviderOperation` z PR-11; nie używać emailowego OutboundMessage,
- żadnego Graph call przed business commit,
- meeting URL i recording przez chronione handle,
- compatibility adapter dla obecnych endpointów.

Testy:

- local i M365 event mają ten sam kontrakt UI,
- Graph timeout/retry/reconcile,
- cancel race z provider update,
- attendee bez dostępu nie dostaje wewnętrznego PII,
- private event nie przecieka przez list/get,
- optimistic locking.

Rollout: shadow-create projection, parity, read switch, write switch; nigdy dual create u providera.

#### PR-31 — Persisted reminders i wspólny due ledger

Cel: zastąpić RAM set, 14–16 minut i narrow windows trwałą kolejką due.

Zakres:

- `ReminderSchedule` dla CalendarEvent i WorkItem,
- aktywacja generycznego due dispatchera dla nowych ReminderSchedule tworzonych po routing cutover; historyczne shadow rows PR-29 pozostają non-deliverable,
- dowolny dozwolony `reminder_minutes`, wiele offsetów według produktu,
- `due_at <= now`, catch-up horizon i jawna polityka przeterminowanych alertów,
- claim/lease/retry/dead-letter,
- cancel/complete anuluje pending reminder,
- notification triggers T+15/T+45/T+2h na tym samym mechanizmie,
- WS dopiero po committed notification,
- metric lateness i skipped reason.

Testy:

- restart, dwie repliki, crash po claim,
- custom offset,
- 30-min downtime,
- weekend/DST,
- event przesunięty po utworzeniu reminderów,
- provider/channel failure,
- delete/cancel przed send.

Zależności: PR-11–14, PR-21/22 dla aktywnych zewnętrznych kanałów, PR-29 i PR-30. Bez gotowego adaptera reminder może emitować wyłącznie in-app Delivery.

#### PR-32 — `CalendarFeed` v2: recurrence, timezone i deletion

Cel: zrobić poprawny, izolowany import zewnętrznych kalendarzy.

Zakres:

- owner-scoped feed z zaszyfrowanym canonical URL i hashem,
- `(feed_id, external_uid)` jako identity,
- SSRF-safe fetcher z PR-07 przy każdym redirect/resolution,
- RFC 5545 parsing dla DTSTART/DTEND/TZID/all-day/RECURRENCE-ID/STATUS,
- ograniczona ekspansja RRULE z horyzontem,
- content hash i `last_seen_at`,
- oznaczanie usunięć po kompletnym, udanym syncu; nigdy po częściowej stronie/błędzie,
- ETag/Last-Modified, bytes/event/time limits,
- per-feed lease, status, lag i sanitized error,
- pause/delete z purge polityką.

Testy:

- dwa feedy z tym samym UID,
- redirect do private IP i DNS rebinding fixture,
- recurrence exception/cancelled occurrence,
- all-day DST,
- oversized feed/zip-bomb-like payload,
- failed sync nie usuwa eventów,
- URL/credentials nie trafiają do logów.

#### PR-33 — Typed realtime broker z reconnect catch-up

Cel: uczynić realtime transportem committed projections, nie źródłem prawdy.

Zakres:

- jeden versioned envelope: `event_id`, `sequence`, `type`, `schema_version`, `resource`, `occurred_at`, minimal `data`,
- frontend registry generowany lub współdzielony kontraktowo,
- usunięcie string-prefix magic i spacji,
- subskrypcja wyłącznie po PolicyService,
- krótko żyjący one-time WebSocket ticket poza URL JWT,
- PostgreSQL-backed `RealtimeEventProjection` i `LISTEN/NOTIFY` między replikami; nie dodawać Redis w tym PR,
- reconnect z ostatnim `sequence` i bounded catch-up przez HTTP,
- żadnych emaili/telefonów/ról w presence payloadzie bez potrzeby,
- heartbeat i backpressure/disconnect slow consumer.

Testy:

- dwie instancje backendu,
- reconnect w środku sekwencji,
- duplicate/out-of-order event,
- expired/reused ticket,
- subscribe do obcego resource,
- slow consumer,
- event przed commit nie jest publikowany.
- dwie transakcje dla jednego recipienta z wymuszoną odwrotną kolejnością commitów nie gubią niższego eventu; cursor lock zachowuje commit order.

Rollout/rollback:

- najpierw shadow projection i porównanie liczby committed notifications/messages,
- potem canary userów z dual-read, ale bez podwójnych toastów,
- wyłączenie WS v2 pozostawia HTTP polling/catch-up i kanoniczne query,
- health pokazuje listener state, projection lag i oldest retained sequence.

#### PR-34 — Unified `Conversation` i bezpieczna migracja chatów

Cel: usunąć dwa podobne, niespójne systemy candidate/job chat.

Zakres:

- `Conversation` po resource i wersjonowany `Message`,
- membership jako projekcja resource scope z re-checkiem,
- `client_message_id` i command idempotency,
- atomowe reactions, pins i read cursor,
- revisions oraz nowe mentions po edycji,
- jeden mention event zamiast zwykłej i mention notification,
- bounded cursor pagination bez N+1,
- tombstone/redaction + retencja,
- compatibility endpoints i dual-read parity,
- rename `job_chat_*` dla candidate chat dopiero po kompatybilnym enum mappingu.

Testy:

- retry po network timeout,
- równoczesna reakcja/pin/read,
- edit adding/removing mention,
- reply do usuniętej wiadomości,
- membership revoked po otwarciu ekranu,
- parity stary/nowy chat,
- 10k messages pagination.

#### PR-35 — Deep links, free/busy i workflow interview feedback

Cel: doprowadzić użytkownika z powiadomienia lub emaila do dokładnego celu.

Zakres:

- kanoniczny route parser dla `event`, `message`, `conversation`, `work_item`,
- cold-load oraz refresh bez pamięci komponentu,
- focus/scroll/highlight z dostępnym komunikatem,
- wygasły/usunięty/niedostępny cel ma bezpieczny fallback,
- free/busy `unknown/error` nie jest `free`,
- interview confirmation/feedback jako typed command + WorkItem,
- powiadomienie zamyka się dopiero po udanym commandzie,
- linki emailowe nie zawierają PII ani bearer tokenów.

Testy:

- bezpośredni URL w nowej sesji,
- refresh i back/forward,
- message na kolejnej stronie cursora,
- unavailable resource,
- free/busy provider 429/500/partial,
- keyboard focus i screen reader announcement.

### Gate po Fali E

- Calendar manual/M365 ma jeden kontrakt,
- przypomnienia przeżywają deploy i downtime,
- feedy są owner-scoped i poprawnie obsługują recurrence/deletion,
- realtime działa między dwiema replikami i ma catch-up,
- chat retry nie duplikuje wiadomości,
- każdy obsługiwany deep link działa po cold load,
- free/busy nigdy nie zamienia błędu w dostępność.

### Fala F — centrum komunikacji, historia i control plane integracji

#### PR-36 — Wersjonowane templates i bezpieczny automation rule builder

Cel: usunąć arbitralne renderowanie PII i zmienne szablony bez historii.

Zakres:

- `MessageTemplate` + immutable `TemplateVersion`,
- scope private/team/organization i publish capability,
- allowlist variable schema per purpose/channel,
- server-side context builder po autoryzowanym subject,
- preview redaction zgodna z capability,
- wysyłka zapisuje wersję i finalny snapshot/hash,
- `AutomationRule` jako walidowany, wersjonowany warunek, recipient resolver i throttle/dedupe,
- stage-aware rule pinning do semantic registry/workflow revision; opcja
  `follow_future` zawsze tworzy revalidation + nową rule version, nigdy silent switch,
- aktywacja stage-aware rule wymaga upstream workflow `runtime_status=eligible`
  oraz transition-event contractu Modułu 4; samo `published` z PR #790 nie wystarcza,
- `AutomationExecution` jako trwały ledger unique
  `(rule_id, rule_version, event_id)` z deterministycznymi logical output keys,
- atomowe spięcie wykonania i fan-out eventów przez CommandReceipt; replay
  odczytuje istniejące wykonanie zamiast emitować duplikaty,
- dry-run na sample synthetic data,
- approval flow dla organization-wide automation,
- kill switch i max fan-out.

Testy:

- viewer nie renderuje obcego kandydata,
- nieznana zmienna failuje przed publikacją,
- zmiana draftu nie zmienia historycznej wysyłki,
- malicious template nie wykonuje kodu ani nie tworzy arbitrary link,
- rule replay/dedupe/throttle,
- semantic terminal mismatch, `unmapped`, parity full-graph lub rewizja bez
  runtime eligibility blokują activation,
- publikacja nowej workflow revision nie zmienia aktywnej pinned rule ani
  historycznych AutomationExecution; follow-future trafia do reapproval,
- replay eventu nie tworzy drugiego WorkItem, OutboundMessage ani Delivery,
- równoległe claimy tej samej reguły kończą się jednym AutomationExecution,
- shadow execution jest terminalne i nie jest promowane po aktywacji,
- fan-out guard.

Zależności/rollout:

- `36a` MessageTemplate/TemplateVersion musi zostać wdrożony przed Communication Hub,
- `36b` AutomationRule korzysta wyłącznie z opublikowanych wersji z `36a`,
- `36b` najpierw wdraża AutomationExecution w trybie terminalnego shadow parity;
  dopiero osobny routing cutover tworzy `pending` dla nowych eventów,
- istniejące template'y najpierw backfill/shadow render; write cutover dopiero po parity,
- organization-wide rules pozostają off do approval i fan-out dry-run.

#### PR-37 — Communication Hub i prawdziwy composer

Cel: zastąpić rozproszone przyciski jednym, prawdziwym flow komunikacji.

Zakres:

- `/communications` z inboxem kontekstowym, outbound queue i delivery status,
- composer wybiera realny endpoint/channel i pokazuje osobno local state i provider state,
- legacy `SendEmailV2` usunięty albo przekształcony w adapter do `/api/v1/communications/email`,
- preview renderowane przez backend z opublikowanego TemplateVersion/context z PR-36a,
- jawne `Od`, delegation, `Do/CC/BCC`, subject, attachments i classification,
- disabled state, jeśli user nie ma realnej skrzynki/delegation,
- retries nie są prezentowane jako nowa wiadomość,
- bulk send jako batch z per-recipient result, limitem i confirmation,
- UI dla dead/uncertain bez obietnicy sukcesu.

Testy:

- queued→accepted→sent oraz queued→retry→dead,
- Graph/SMTP uncertain outcome,
- delegation expiry w czasie composera,
- attachment access/size/type,
- partial bulk result,
- no fake hardcoded preview data,
- `completed + provider accepted` nie renderuje „dostarczono”,
- no success toast przed persisted queued/accepted contract.

Zależności: PR-16, PR-21/22 i PR-36a. `37a` dostarcza backend/API, `37b` UI i dopiero wtedy przełącza legacy CTA.

#### PR-38 — Kanoniczny Timeline i retencja artefaktów

Cel: połączyć historię bez utraty audytu i bez globalnych raw details.

Zakres:

- TimelineEvent jako redagowana projekcja DomainEvent,
- stabilny cursor `(occurred_at,event_id)`,
- subject/resource scope przy każdym odczycie,
- mapowanie Note/Activity/UserActivity/call/email/calendar/chat,
- transition events zachowują snapshot workflow/stage revision, semantic key i
  registry version; timeline nie reinterpretuje historii według najnowszej rewizji,
- jawne źródło i link do kanonicznego artefaktu,
- `CommunicationArtifact/RetentionManifest`,
- purge graph dla body, attachment, recording, transcript, preview, search/vector derivative i cache,
- private/delete/redaction propagowane asynchronicznie z retry/DLQ,
- legal hold i audit purge,
- przejściowe reconciliation między starymi ledgerami i timeline.

Testy:

- identyczny timestamp bez utraty/duplikatu,
- raw details redaction,
- inaccessible event pominięty bez side-channel count,
- private mail usuwa wcześniej zapisany plik/snippet,
- purge retry i legal hold,
- backfill rerun.
- publikacja/zmiana labela nowej workflow revision nie zmienia historycznego
  timeline ani provenance WorkItem.

#### PR-39 — Integration Control Plane i rozdzielenie ustawień personal/admin

Cel: pokazać prawdziwy stan połączeń, workerów i odpowiedzialności.

Zakres:

- read model/API nad `IntegrationConnection/SyncCursor/IntegrationRun` z PR-11, `WorkerLease` z PR-12 i registry/heartbeat z PR-15; bez tworzenia konkurencyjnych tabel,
- personal settings: własna skrzynka, preferencje, dozwolone endpointy,
- admin settings: provisioning, mappings, kill switches, backlog/DLQ, manual retry,
- spójne osobne pola `desired_state`, `configuration_state`, `health_state` i `run_state` zgodne z 11.21; UI nie skleja ich w jeden enum,
- last attempt, last success, lag, cursor, backlog, dead-letter, lease owner,
- CloudTalk/Fireflies/M365/Teams/Slack/Proxycurl cards korzystają z jednego kontraktu,
- znikają placeholdery „coming soon” dla istniejącego backendu,
- raw provider response/sekrety nigdy nie są renderowane,
- manual sync jest POST + persisted JobRun,
- pause i disconnect są osobnymi komendami; disconnect atomowo blokuje nowe
  runy i przenosi credential reference do sealed cleanup-only capability, a
  usuwa go dopiero po revoke/reconciliation albo jawnej polityce immediate erase,
- UI pokazuje `disconnecting` i osobny wynik revoke/cleanup zamiast przedwcześnie
  deklarować `unconfigured`,
- snapshot i health korzystają z tego samego registry.

Testy:

- personal user nie widzi admin controls ani cudzych connection details,
- disabled nie wygląda jak crashed,
- stale success daje degraded,
- manual click retry nie uruchamia dwóch runów,
- disconnect podczas running sync nie pozwala odnowić lease ani rozpocząć
  kolejnego runu, a timeout revoke pozostaje `uncertain`, nie „rozłączono u providera”,
- zwykły worker/UI nie odczyta cleanup-only credential, cleanup worker może go
  użyć tylko dla przypisanego revoke operation, a sukces usuwa referencję,
- immediate credential erase kończy cleanup wynikiem
  `not_attempted_credentials_erased`, nigdy fikcyjnym `queued`,
- ponowienie disconnect z tym samym idempotency key zwraca ten sam operation,
- secret/error scrubbing,
- snapshot count equals registry.

### Gate po Fali F

- composer mówi prawdę o queued/sent/failed,
- template rendering ma pełny subject access i immutable version,
- timeline ma stabilny cursor i redakcję,
- purge obejmuje wszystkie pochodne artefaktu,
- personal/admin integration settings są rozdzielone,
- snapshot, health i UI pokazują tę samą prawdę o workerach.

### Fala G — jakość wydania, CI, migracja i wyłączenie legacy

#### PR-40 — Dostępność, mobile i spójny design system

Cel: domknąć główne powierzchnie modułu dla klawiatury, screen readera i mobile.

Zakres:

- bell jako właściwy button/menu/dialog, nie klikalne `li`,
- pełny Notification Center z filtrami, cursor, archive i preferences,
- chat actions dostępne bez hover,
- Calendar mobile agenda i bezpieczny overflow,
- Communication Hub i My Work w 320–1440 px,
- focus management, live regions, accessible names i error summary,
- reduced motion, kontrast i tokeny zamiast hardcoded kolorów,
- naprawa ActiveViewers palette,
- brak raw HTML/URL w Fireflies/calls,
- loading/empty/error/partial/offline states.

Źródła UI:

- przed implementacją przeczytać `frontend/docs/ds/ADDING-BLOCKS.md`,
- application UI adaptować z Tailwind Plus wyłącznie do semantic tokens,
- nie uruchamiać `npx shadcn add`,
- nie dodawać nowej biblioteki design systemu.

Testy:

- axe component/page,
- keyboard-only scripts,
- screen reader semantics snapshots,
- viewport 320/375/768/1024/1440,
- forced error/slow/offline,
- dark/soft themes,
- screenshot regression kluczowych stanów.

#### PR-41 — Backend test discovery i required safety suites

Cel: zakończyć sytuację, w której required CI pomija 126 z 238 test files.

Zakres:

- przejście z ręcznej listy na marker-based/test-discovery jobs albo sentinel wymagający jawnego powodu pominięcia,
- osobne równoległe shardy: auth/policy, communications, integrations, workers, migrations,
- live tests oznaczone i wyłączone w zwykłym CI, ale widoczne w manifest,
- required tests dla wszystkich P0/P1 z tego raportu,
- migration from empty oraz upgrade from representative production head(s),
- entrypoint mirror contract test,
- test registry wykrywa worker uruchomiony poza supervisorem.

Acceptance:

- każdy `backend/tests/test_*.py` jest wykonywany lub jawnie sklasyfikowany,
- nowy test file automatycznie wchodzi do CI,
- celowe `skip/xfail` ma reason i limit czasu,
- CI nie używa lokalnego Dockera i mieści się w uzgodnionym czasie przez sharding.

#### PR-42 — Frontend component/contract/a11y test lane

Cel: objąć testami krytyczne, dotąd prawie niechronione surface.

Zakres:

- MSW/contract fixtures z wersjonowanymi payloadami,
- tests dla Notification Center, WorkItem, Conversation, Calendar, Composer, integrations,
- błędy 401/403/404/409/422/429/500 i network offline,
- reconnect/out-of-order/duplicate realtime,
- deep link/cold load,
- axe i keyboard,
- test, że nieznany notification type ma neutralny fallback i telemetry, nie błędną semantykę,
- test, że success toast odpowiada kontraktowi `queued/sent`, nie samemu HTTP 2xx.

Acceptance:

- każdy nowy typed event ma frontend handler albo jawny fallback test,
- żadna krytyczna mutacja nie jest testowana tylko happy-path,
- tests są częścią required CI.

#### PR-43 — E2E i fault-injection release gate

Cel: udowodnić end-to-end prawdę o delivery, dostępie i odporności na crash.

Scenariusze obowiązkowe:

- wszystkie siedem ról (`admin`, `head_of_recruitment`, `delivery_lead`, `tac`, `recruiter`, `sourcer`, `user`) oraz inactive vs owner/assigned/explicit member/team/non-member/unrelated resource,
- compose queued→provider receipt→timeline,
- crash po provider acceptance przed local success,
- webhook commit przed 2xx i replay,
- dwa workery, lease expiry i fencing,
- cursor item failure,
- chat retry/reconnect/edit mention,
- WorkItem complete/snooze/escalation,
- Calendar DST/recurrence/cancel/reminder,
- private/delete artifact purge,
- ambiguous call/recording review,
- cold deep links,
- mobile/keyboard production-like flow.

Zasady:

- PR-blocking fault tests używają kontraktowego fake providera, który deterministycznie modeluje `accepted/sent/unknown/reconcile`, crash i retry; nie wolno użyć bezwarunkowego stub success,
- prawdziwy M365/CloudTalk/Teams działa jako osobny scheduled/manual smoke na kontrolowanym test tenant; brak sekretu ma dać jawny `not_configured/skip with reason`, nigdy fałszywie zielony dowód delivery,
- żadnych testów opartych wyłącznie o fake `sent`, gdy asercja dotyczy wiarygodnego provider receipt,
- fixtures nie zawierają realnego PII,
- test nie może być false green przez bezwarunkowy catch albo brak asercji,
- zewnętrzne live smoke osobno i z kontrolowanym tenantem.

#### PR-44 — Reconciliation, cutover, usunięcie legacy i runbooki

Cel: po wykonanych już provider/channel cutoverach potwierdzić parytet, usunąć legacy i zostawić system operacyjnie obsługiwalny.

Zakres:

- finalne inventory i reconciliation dla notifications, chats, obligations, calendar, mailbox IDs, calls/recordings i artifacts,
- shadow parity reports z zaakceptowanymi progami,
- potwierdzenie, że każdy provider PR wykonał rozłączny canary i pełny routing cutover,
- potwierdzenie braku active legacy claims oraz legacy writer telemetry `0`,
- read switch tylko tam, gdzie zreconciliowany legacy→new bridge już działa; write source został wcześniej przełączony przez owner PR,
- usunięcie fałszywego `/api/emails/send`, RAM reminder set, untracked `create_task`, token-path webhook i orphan endpoints,
- pozostawienie compatibility redirects przez jedno wersjonowane okno,
- aktualizacja OpenAPI, ADR, data map, retention policy, threat model i operator runbooks,
- runbook: backlog, DLQ replay, uncertain send, cursor gap, lease stuck, webhook secret rotation, provider outage, data purge,
- aktualizacja skill/runbook listy workerów z 15 do declarative registry zamiast liczby wpisanej ręcznie,
- restore/rollback drill bez destrukcyjnego downgrade,
- usunięcie flag dopiero po minimum dwóch stabilnych cyklach wydania.

Acceptance:

- każdy legacy write path ma telemetry `0` przez uzgodnione okno,
- zero dual-send i zero nierozliczonych shadow mismatch,
- wszystkie pending/uncertain/DLQ rekordy mają właściciela decyzji,
- rollback flag został przećwiczony przed usunięciem legacy,
- operator potrafi zidentyfikować deployed SHA, worker outcome i provider delivery bez zaglądania do surowej bazy,
- wszystkie required CI/E2E są zielone,
- wdrożony SHA jest zgodny z `/api/health`, a UI przechodzi produkcyjny smoke test.

### Gate końcowy po Fali G

- P0: zero otwartych ustaleń,
- P1: zero otwartych ustaleń albo jawna, zaakceptowana exception z ownerem i terminem,
- nie ma fałszywych komunikatów „wysłano”,
- każda external side effect ma trwały operation ID, wynik i reconciliation path,
- każda human obligation ma WorkItem albo jest jawnie tylko informacyjna,
- każdy event i message ma object-level policy,
- registry rozlicza 24/24 taski jako enabled/disabled/running/failed, a każdy enabled multi-replica side-effecting worker w zakresie modułu ma lease/fencing albo udowodnioną, udokumentowaną idempotentną concurrency strategy; każdy worker ma heartbeat/outcome/backlog adekwatny do typu,
- każda usunięta/prywatna treść ma sprawdzony purge graph,
- required CI odkrywa nowe testy automatycznie,
- produkcja jest sprawdzona exact-SHA oraz realną interakcją w przeglądarce.

---

## 17. Kolejność, zależności i możliwość pracy równoległej

### 17.1. Uproszczony roadmap

```text
PR-00 inventory
  -> PR-01..09 containment
  -> PR-10 DomainEvent
  -> PR-11 Outbox/Inbox/Delivery
  -> PR-12 leases/dispatchers
  -> PR-13 notifications + PR-15 supervisor
  -> PR-16..24 provider migrations
  -> PR-25 WorkItem
  -> PR-30 Calendar + PR-33 realtime + PR-34 conversations
  -> PR-36 Templates -> PR-37 Communication Hub + PR-38 Timeline
  -> PR-41..43 release gates
  -> PR-44 cutover
```

Nie wolno rozpoczynać cutoveru tylko dlatego, że docelowe tabele istnieją. Minimalny warunek to: trwały dispatcher, idempotencja, telemetry, reconciliation i rollback flag.

Powyższy diagram jest orientacyjnym roadmapem, nie pełnym grafem. Tabela 17.2 jest jedynym źródłem prawdy o `depends_on`; w razie rozbieżności obowiązuje tabela.

### 17.2. Jawny DAG wykonawczy

Suffixy z sekcji 16.2 dziedziczą dependency rodzica, ale w ramach slotu są mergowane w kolejności alfabetycznej, chyba że poniżej wskazano inaczej.

| Slot | `depends_on` | Tworzy/rozszerza | Zastępuje dopiero po gate |
|---|---|---|---|
| 00 | — | inventory, required safety lane | nic |
| 01 | 00 | prawdziwy contract CTA | simulated email success |
| 02 | 00 | poprawny unread/read API | błędne filtry |
| 03 | 00 | realtime ticket + presence ACL v1 | JWT w URL, global presence |
| 04 | 00 | template/note/calendar ACL v1 | global IDOR paths |
| 05 | 00, 04 | delegation/send/call ACL v1 | implicit mailbox/call access |
| 06 | 00 | provider admin + webhook containment v1 | global sync/map, secret path |
| 07 | 00 | CalendarFeed/safe fetch v1 | arbitrary iCal fetch/UID scope |
| 08 | 05, 06 | artifact inventory/purge v1, recording quarantine | direct raw artifact/auto-attach |
| 09 | 00 | verified SMTP TLS, safe activity projection | insecure TLS/raw details |
| 10 | Fala A gate | DomainEvent/AuditEntry | ad-hoc committed fact emission, po migracji flow |
| 11 | 10 | Outbox/Inbox/Delivery/Endpoint/ProviderOperation/Reminder + IntegrationConnection/Cursor/Run foundation | RAM-only units of work, po cutoverach |
| 12 | 11 | lease/fencing/dispatchers | unleased processing, per worker cutover |
| 13 | 10–12 | Notification v2 projection/registry | legacy notification writer po parity |
| 14 | 13 | preferences/digest/quiet hours | hardcoded per-channel choices |
| 15 | 12 | 24/24 worker registry/supervisor observe-only | misleading running/expected snapshot |
| 16 | 05, 11, 12 | OutboundMessage/MailboxDelegation/send lifecycle | direct M365 send path po canary |
| 17 | 16 | rejection claim/draft/reconcile | legacy rejection dispatcher |
| 18 | 11 | durable M365 shadow webhook ingress | RAM `create_task` ingress; processor nadal off |
| 19 | 18, 12 | M365 lease/cursor/identity/OAuth/request integrity + processor canary w 19e | legacy sync primitives |
| 20 | 08, 19 | subscription + recording lifecycle | duplicate renewal/time-only matching |
| 21 | 09, 11, 12, 14 | SMTP/auth/mention adapter z preferences re-check | synchronous SMTP paths |
| 22 | 11, 12, 21 | Teams/Slack/chat fallback adapters | fire-and-forget/best-effort paths |
| 23 | 06, 11, 12 | CloudTalk durable inbox/matching/upsert | containment webhook/poller write path |
| 24 | 12, 23 | provider-specific durable schedulers | CloudTalk/Fireflies/Proxycurl legacy loops |
| 25 | 10 | WorkItem schema/API | brak kanonicznego zadania |
| 26 | 25; M4-WF-A/B/C tylko dla workflow source | legacy obligation bridge/backfill | legacy fields jako write source po parity |
| 27 | 25 | My Work UI | rozproszone listy obowiązków |
| 28 | 13, 25, 27 | actionable notification commands | UI-specific workflow mutations |
| 29 | 11, 12, 14, 25; M4-WF-A/B/C dla stage SLA | recurrence/escalation shadow schedules | narrow WorkItem trigger windows po PR-31 |
| 30 | 11, 12, 19 | CalendarEvent/ProviderOperation scheduling | dwa create flows |
| 31 | 11–14, 21, 22, 29, 30 | wspólny due dispatcher i channel delivery | RAM reminders/narrow triggers |
| 32 | 07, 12, 30 | CalendarFeed v2 | v1 containment importer |
| 33 | 03, 10, 13 | PostgreSQL realtime projection/catch-up | process-local broadcast |
| 34 | 10–12, 33 | Conversation/Message + chat migrations | candidate/job chat writers per cutover |
| 35 | 28, 30, 33, 34 | deep-link/free-busy/feedback flow | component-local routing |
| 36 | 10–12, 14, właściwe adaptery 21/22; M4-WF-A/B/C dla stage rules | 36a versioned templates; 36b dormant rule builder, activation dopiero po adapter gate | mutable/ad-hoc templates po parity |
| 37 | 16, 21, 22, 36a | Communication Hub/composer | legacy email CTA po `37b` |
| 38 | 08, 10, 20, 23, 25, 30, 34, 37; M4-WF-C dla stage timeline | Timeline adapters + artifact purge graph | fragmented read models/purge paths |
| 39 | 11, 12, 15, 18–24 | Integration Control Plane jako read model/UI | per-provider RAM/status screens |
| 40 | 14, 27, 33–39 | notification/mobile/a11y/design release polish | stare UI surfaces per suffix |
| 41 | wcześniejsze backend PR-y | required backend discovery/safety suites | manual allowlist CI |
| 42 | 27, 35, 37, 39, 40 | frontend contract/a11y lane | happy-path-only coverage |
| 43 | 41, 42 | deterministic E2E/fault release gate | rozproszone nie-required smoke |
| 44 | wszystkie gates, 43 | reconciliation/cutover/runbooks | legacy writers/workers/flags |

Ewolucja nie może tworzyć konkurencyjnych modeli:

| Containment/foundation | Rozszerzenie docelowe | Reguła |
|---|---|---|
| PR-03 ticket/presence ACL v1 | PR-33 broker/projection/catch-up v2 | rozszerzyć ten sam ticket contract; wycofać v1 po canary |
| PR-05 minimal MailboxDelegation | PR-16 pełny send lifecycle | migracja tej samej tabeli/serwisu, nie drugi delegation model |
| PR-07 CalendarFeed identity/safe fetch v1 | PR-32 RFC recurrence/deletion v2 | zachować feed IDs i owner scope |
| PR-08 artifact inventory/purge foundation | PR-38 RetentionManifest/purge graph | backfill manifestu, potem jeden purge worker |
| PR-00 required safety lane | PR-41 pełne test discovery | PR-41 rozszerza lane; nie usuwa wcześniejszych regresji |
| PR-06 replay containment v1 | PR-23 generic Inbox | jeden aktywny ledger po migracji |

### 17.3. Co można robić równolegle

Ready set bezpośrednio po PR-00: PR-01, PR-02, PR-03, PR-04, PR-06, PR-07 i PR-09. Mogą być rozwijane równolegle, ale migracje muszą być rebase'owane na jeden kontrolowany head/merge head zgodnie z bieżącą strukturą Alembic.

Następny ready set:

- PR-05 dopiero po właściwym wspólnym policy/resource-scope fundamencie z PR-04,
- PR-08a/08b dopiero po odpowiadających im 05c/06b/06c,
- development może zacząć na contract fixtures wcześniej, ale merge order pozostaje zgodny z 17.2.

Po PR-12:

- notification projection,
- worker supervisor,
- M365 ingress,
- CloudTalk ingress,
- SMTP adapter,

mogą być rozwijane równolegle pod warunkiem, że processory i routing switch pozostają wyłączone.

Teams/Slack/chat fallback mogą być przygotowywane na adapter interface, ale ich merge/activation pozostaje po PR-21 zgodnie z DAG.

Po PR-25:

- bridge legacy obligations,
- My Work UI w trybie read-only/shadow,
- recurrence/escalation,

mogą być rozwijane równolegle na jednym kontrakcie API. Produkcyjne mutacje My Work wolno włączyć tylko dla source'ów, które przeszły per-source writer cutover z PR-26.

Po ustabilizowaniu API:

- Calendar UI,
- Conversation UI,
- Communication Hub,
- Notification Center,

mogą być realizowane równolegle, ale powinny współdzielić generated/validated contract types i ten sam deep-link router.

### 17.4. Czego nie łączyć w jednym deployu

Nie łączyć bez osobnego canary i obserwacji:

- migracji schema oraz aktywacji nowego processora,
- aktywacji dwóch outbound channels,
- przełączenia read i write path tego samego agregatu,
- M365 webhook ingestion i wyłączenia pollingu recovery,
- CloudTalk webhook v2 i automatycznego enrichment,
- backfillu WorkItems i włączenia escalation,
- CalendarFeed deletion reconciliation i masowego purge,
- supervisor auto-restart oraz nowych workerów,
- retencji/purge oraz legal-hold migration.

### 17.5. Sugerowane ownership lanes

| Lane | Odpowiedzialność | PR-y |
|---|---|---|
| Security/policy | capability, resource scope, privacy, SSRF, TLS | 01–09 |
| Kernel/platform | events, outbox/inbox, lease, supervisor | 10–15 |
| Provider integrations | M365, SMTP, Teams, Slack, CloudTalk, Fireflies, Proxycurl | 16–24 |
| Work management | WorkItem, bridge, My Work, escalation | 25–29 |
| Scheduling/realtime | Calendar, reminders, feeds, WS, conversations | 30–35 |
| Product surfaces | Hub, templates, timeline, settings | 36–40 |
| Quality/release | CI, contract tests, E2E, reconciliation/cutover | 41–44 |

Ownership lane nie oznacza osobnego modelu autoryzacji ani osobnej kolejki. Wspólny kernel i PolicyService pozostają centralne.

---

## 18. Strategia testów

### 18.1. Macierz RBAC i resource scope

NEXUS ma siedem rzeczywistych ról: `admin`, `head_of_recruitment`, `delivery_lead`, `tac`, `recruiter`, `sourcer` i `user`. W pierwszych PR-ach containment używać istniejących zależności (`AdminUser`, właściwe *Access), a capability model wprowadzać dopiero z jawną mapą wszystkich siedmiu ról. Nie tworzyć nazw ról, których nie ma w `UserRole`.

Każdy endpoint odczytu oraz mutacji musi być testowany dla każdej roli w kombinacji z `owner`, `explicit member/delegate`, `team/resource member`, `non-member` oraz `inactive/revoked`. Minimalne oczekiwania:

| Aktor | Resource | Oczekiwany wynik |
|---|---|---|
| user | własny/dozwolony | tylko jawnie dozwolony read; brak send/admin |
| user | obcy | 403 albo 404 według jednolitej polityki |
| sourcer | owner/member/non-member | capability i candidate resource scope, osobno dla PII/send |
| recruiter | przypisany kandydat/job/client | capability-dependent read/write |
| recruiter | nieprzypisany | brak dostępu, chyba że jawny team scope |
| tac | owner/team/non-member | jawnie zmapowany client/candidate scope, bez implicit mailbox access |
| delivery lead | własny zakres zespołu | tylko zdefiniowana delegacja/scope |
| head of recruitment | organization/team/non-member | jawna mapa capability, bez implicit mailbox delegation |
| admin | zasób organizacji | admin capability, ale mailbox read/send tylko z delegacją lub break-glass |
| inactive/revoked user | dowolny | brak nowego delivery i brak dostępu |
| service worker | subject utracił dostęp przed dispatch | `skipped/revoked`, bez wysyłki |

Obowiązkowe obiekty:

- Note i TimelineEvent,
- Notification i WorkItem,
- Conversation/Message/Presence,
- CalendarEvent/Feed/Recording,
- mailbox thread/attachment/compose/reply/bulk,
- Call/Transcript/Fireflies note,
- Template render/publish,
- IntegrationConnection/Run/DLQ.

Nie wystarczy test roli. Musi istnieć test konkretnego `subject_id` spoza scope, ponieważ większość ustaleń P0 to IDOR przy poprawnie zalogowanym użytkowniku.

### 18.2. Realtime

Testy jednostkowe/kontraktowe:

- envelope version i unknown type,
- ticket issue/consume/expire/replay,
- DB-backed ticket atomic consume z dwóch replik,
- payload minimization,
- policy dla subscription.

Testy integracyjne:

- commit przed publish,
- dwie instancje backendu,
- reconnect z cursor,
- duplicate i out-of-order,
- slow consumer/backpressure,
- revocation w czasie aktywnego połączenia,
- missed-event HTTP catch-up.
- odwrotna kolejność transakcji/fan-out cursor locks bez zgubienia eventu i bez deadlocku.

Testy frontendowe:

- reconnect indicator,
- event dla aktualnej i innej strony,
- optimistic update + server conflict,
- brak podwójnego toastu/message,
- unknown schema ma telemetry i bezpieczny fallback.

### 18.3. Email i external delivery

Dla każdego kanału testować parę `(Delivery.state, provider_state)` oraz immutable attempt outcomes, a nie tylko wywołanie mocka:

```text
(shadow_observed, not_requested)                           # terminalne, nigdy claim/promote
nowy event po routing generation -> (pending, not_requested)
(pending, not_requested) -> (leased, not_requested)
  -> Attempt(outcome=accepted) -> (completed, accepted)
  -> reconciliation -> (completed, sent|delivered)
(leased, not_requested) -> Attempt(retryable_failure)
  -> (retry_wait, not_requested) -> (pending, not_requested)
(leased, not_requested) -> Attempt(unknown)
  -> (uncertain, unknown) -> reconciled (completed|dead, accepted|sent|failed)
(pending|retry_wait, not_requested) -> (cancelled, not_requested)
(leased, *) + brak attempt intent/request_started -> lease expired -> reclaimed
(leased, *) + request_started_at i outcome NULL -> lease expired -> (uncertain, unknown) -> reconcile
```

Historyczna tabela prób ma osobne asercje:

```text
Attempt #1 unknown       # immutable
Attempt #2 reconciliation/safe retry outcome
Delivery aggregate state wyliczony z obu, bez nadpisania #1
```

ProviderOperation ma dodatkową asercję granicy generacji:

```text
generation 1 / attempt 1 -> retryable_failure
approved retry -> current_retry_generation=2
crash po claimie, przed intentem generation 2 -> lease reclaim/retry_wait
intent generation 2 z outcome NULL -> lease expiry -> uncertain/reconcile
attempt generation 1 nigdy nie decyduje o stanie requestu generation 2
```

Provider `failed` jest zachowany w DeliveryAttempt. Jeżeli failure jest retryable albo admin zatwierdzi bezpieczny retry, nowa `retry_generation` resetuje agregat provider_state `failed -> not_requested`. `unknown` wolno zresetować tylko po reconciliation=`not_sent`; nigdy samym kliknięciem retry.

Obowiązkowe fault points:

- crash przed provider request,
- crash po committed attempt intent przed request — konserwatywne
  uncertain/reconcile, nigdy blind resend,
- timeout podczas requestu,
- provider accepted, crash przed local commit,
- lease expiry z unresolved attempt wymusza reconciliation zamiast blind retry,
- 401/token refresh,
- 429/Retry-After,
- 4xx permanent,
- 5xx transient,
- response bez provider ID,
- ponowny command z tym samym idempotency key,
- odbiorca traci uprawnienie przed dispatch,
- template albo endpoint zostaje wyłączony przed dispatch.

Provider stub musi modelować niepewny wynik; `200` w mocku nie dowodzi exactly-once.

### 18.4. WorkItems

Minimalne scenariusze:

- create, assign, start, complete, reopen, snooze, cancel,
- stale `expected_version`,
- dwa complete i assign/complete race,
- due w UTC i prezentacja w IANA timezone,
- recurrence DST/weekend,
- catch-up po downtime,
- escalation cancel race,
- subject deleted/restricted,
- bridge rerun/backfill parity,
- notification action retry,
- list cursor przy równych timestampach,
- 10k rekordów bez N+1.

### 18.5. Calendar i feeds

Minimalny zestaw fixtures:

- timed event z TZID,
- floating time — jawnie odrzucony albo z kontrolowaną polityką,
- all-day,
- RRULE daily/weekly/monthly,
- EXDATE i RECURRENCE-ID override,
- cancelled occurrence,
- DST Europe/Warsaw i inna timezone uczestnika,
- dwa feedy z tym samym UID,
- zmiana i usunięcie po udanym sync,
- niepełny/błędny feed bez deletion,
- ETag 304,
- redirect/private IP/oversize/timeout,
- overlapping meeting recordings,
- provider free/busy error/unknown/partial.

### 18.6. Integracje

M365:

- webhook validation handshake,
- commit-before-202,
- replay i dirty generation,
- cursor poison item,
- concurrent manual/poll/webhook sync,
- owner-scoped Graph IDs,
- OAuth state one-time/TTL/wrong user,
- subscription duplicate/renewal failure,
- recording ambiguity and pagination,
- private/delete purge.

CloudTalk:

- HMAC/header/body limit/replay,
- webhook+poller race,
- shared phone ambiguity,
- initiated→completed,
- transcript version,
- pagination failure/watermark,
- double click initiate,
- enrichment hash dedupe.

Fireflies:

- account ownership,
- duplicate transcript and parallel sync,
- ambiguous participant,
- cursor/restart,
- status counts only proper source,
- retention/deletion.

Proxycurl/LinkedIn:

- exact hostname,
- two workers/one paid request,
- 429 breaker,
- budget hard stop,
- attempt vs success watermark,
- retained-field allowlist.

### 18.7. UX, accessibility i mobile

Każdy kluczowy ekran testować w stanach:

- loading,
- empty,
- populated,
- partial data,
- permission denied,
- validation error,
- conflict,
- provider degraded,
- offline/reconnecting,
- success,
- queued,
- failed/uncertain.

Minimalne viewports: 320×568, 375×812, 768×1024, 1024×768 i 1440×900.

Minimalne interakcje:

- pełny keyboard path,
- widoczny focus,
- Escape/Tab w dialogach,
- screen reader name/state/error,
- touch target,
- reduced motion,
- dark/soft theme,
- długi polski tekst, długi email i bardzo długa nazwa.

### 18.8. Testy migracji i zgodności

Każda migracja:

- `alembic upgrade heads` na pustej bazie CI,
- upgrade z reprezentatywnego snapshotu schema,
- mirror w `_COLUMN_STATEMENTS`/odpowiedniej strukturze entrypointu, jeśli dotyczy,
- idempotentny ponowny startup,
- preflight dla unique constraint,
- backfill z checkpoint i dry-run,
- rollback aplikacyjny bez destrukcyjnego downgrade,
- reconciliation count/hash bez PII.

### 18.9. Wymagane komendy w CI

Claude powinien korzystać z repo-native commands, a nie tworzyć alternatywnego toolchainu:

```bash
cd backend
ruff check app/
ruff format --check app/
alembic -c alembic/alembic.ini upgrade heads
pytest <focused-files> -v

cd ../frontend
npm ci --legacy-peer-deps
npm run lint
npm run type-check
npm run test
npm run build
```

Lokalnie uruchamiać najmniejszy host-native zestaw adekwatny do PR. Pełne shardy, build, migracje reprezentatywne i E2E mają być required gate w hosted CI. Lokalny Docker jest zabroniony.

---

## 19. Obserwowalność, SLO i alerty

### 19.1. Zasada

„Worker działa” nie jest wystarczającym sygnałem. Potrzebne są cztery niezależne prawdy:

1. proces/task żyje,
2. lease/heartbeat jest świeży,
3. ostatnia praca zakończyła się sukcesem,
4. backlog i lag mieszczą się w granicy.

### 19.2. Metryki obowiązkowe

Per event/projector/channel/provider:

- `events_created_total`,
- `outbox_pending`, `outbox_oldest_age_seconds`,
- `inbox_pending`, `inbox_oldest_age_seconds`,
- `deliveries_total{state,provider_state}`, `delivery_latency_seconds`,
- `delivery_attempts_total{outcome}`, `delivery_reconciliations_total{result}`,
- `delivery_retries_total`, `delivery_dead_letter_total`,
- `webhook_received/duplicate/rejected/processed/dead_total`,
- `worker_heartbeat_age_seconds`,
- `worker_last_success_age_seconds`,
- `worker_runs_total{result}`, `worker_run_duration_seconds`,
- `lease_contention_total`, `lease_lost_total`,
- `sync_cursor_lag_seconds`,
- `reminder_lateness_seconds`,
- `work_items_overdue`, `work_items_unassigned`,
- `realtime_connections`, `realtime_disconnects`, `realtime_catchup_events`,
- `artifact_purge_pending/dead`,
- `ambiguous_matches_pending`,
- provider cost/budget counters tam, gdzie API jest płatne.

Nie umieszczać candidate ID, email, phone, message body, subject ani URL z credentialami jako metric labels.

### 19.3. Proponowane SLO

Wartości początkowe do zatwierdzenia z produktem/ops:

| Obszar | SLO początkowe |
|---|---|
| In-app notification | 99% committed projections do 60 s |
| Realtime | 99% online events do 5 s; catch-up po reconnect do 30 s |
| Calendar reminder | 99% nie później niż 2 min po due przy zdrowym providerze |
| WorkItem command | 99.9% trwały wynik API bez provider dependency |
| Outbound email | 99% Delivery osiąga jawny terminal/attention state (`completed/dead/uncertain`) i jawny provider outcome (`accepted/sent/delivered/failed/unknown`) w 15 min |
| Webhook ingress | 99.9% trwały commit przed 2xx; zero świadomej utraty |
| M365/CloudTalk sync | freshness zgodna z interwałem + zdefiniowany grace |
| Artifact purge | 99% w czasie wynikającym z polityki retencji |

SLO delivery musi rozróżniać awarię NEXUS od potwierdzonej awarii providera.

Początkowe budżety wydajnościowe do mierzenia na produkcyjnie reprezentatywnych danych:

- command API p95 ≤ 500 ms bez oczekiwania na provider,
- paginowane WorkItem/Notification list p95 ≤ 500 ms dla page 50,
- Timeline/Conversation page p95 ≤ 750 ms dla page 50 i bez N+1,
- realtime catch-up p95 ≤ 2 s dla 500 eventów,
- provider network call nigdy nie wydłuża transakcji DB ani requestu command ponad jego timeout contract,
- oldest pending dla security/auth mail > 5 min = P0; dla pozostałych immediate deliveries > 15 min = P1,
- dowolny nowy dead-letter security mail = P0; >5 dead-letterów jednego providera/15 min = P1 i circuit breaker review,
- webhook inbox oldest age > 5 min albo sync lag > 2× deklarowany interwał + grace = degraded/alert.

Docelowe RTO/RPO oraz dni retencji dla body, attachments, recordings, transcripts i webhook payloads są decyzjami z sekcji 22. Production enable danego purge/sync flow jest blokowane, dopóki wartości nie są jawnie zapisane w wersjonowanej konfiguracji/polityce — nie wolno pozostawić bezterminowego defaultu.

### 19.4. Alerty

P0/page:

- rosnący DLQ dla security/auth email,
- outbox oldest age ponad krytyczny próg,
- webhook 2xx bez zapisu — powinno być niemożliwe i testowane,
- możliwy dual-send,
- purge deadline breach dla private/deleted PII,
- budget runaway płatnego providera,
- deployed health `version` niezgodny z oczekiwanym SHA po rollout.

P1/ticket:

- stale worker success,
- subscription expiry risk,
- cursor lag,
- reminder lateness,
- rosnące ambiguous review,
- reconciliation mismatch,
- integration degraded przez więcej niż grace period.

### 19.5. Snapshot i health

Zachować top-level kontrakt `/api/health`:

```json
{
  "status": "healthy|degraded|unhealthy",
  "version": "<sha>",
  "deployedAt": "<timestamp>",
  "checks": {"database": "healthy"}
}
```

Nowe checks mogą rozszerzać `checks`, ale nie powinny zmieniać shape. Szczegółowy backlog, errors i worker registry pozostają w chronionym `/api/admin/snapshot`, bez sekretów/PII.

Snapshot musi pokazywać osobno:

- configured,
- enabled,
- process state,
- lease state,
- last attempt,
- last success,
- last error code,
- lag/backlog/DLQ,
- deployed app SHA i schema heads.

---

## 20. Instrukcja wykonawcza dla Claude Code

### 20.1. Przed każdym PR

1. Przeczytaj `AGENTS.md` i pliki wskazane w danym PR.
2. Uruchom:

   ```bash
   git fetch origin
   git status --short --branch
   git log --oneline origin/main..HEAD
   ```

3. Potwierdź, że feature/fix nie został już wdrożony w nowszym `origin/main`.
4. Nie pracuj na brudnym, wielotematycznym checkout. Utwórz izolowaną gałąź/worktree zgodnie z zasadami repo.
5. Zapisz baseline:
   - właściwy count/query,
   - aktualny test reprodukujący błąd,
   - aktualny health/snapshot, jeśli PR dotyczy runtime.
6. Dla UI przeczytaj `frontend/docs/ds/ADDING-BLOCKS.md`.

### 20.2. W trakcie implementacji

- najpierw test reprodukujący albo contract fixture,
- jeden problem i jeden rollback boundary na PR,
- komenda biznesowa + event/outbox w jednej transakcji,
- network/provider call wyłącznie po commicie,
- każda mutacja ma jawny `Idempotency-Key` albo udowodnioną naturalną idempotencję oraz autoryzację object-level,
- nie loguj payloadów z PII, tokenów ani provider secrets,
- nie dodawaj enum PostgreSQL, jeśli typ zdarzenia ma ewoluować — użyj walidowanego, wersjonowanego string registry,
- każda nowa tabela/kolumna: Alembic + entrypoint mirror + test upgrade,
- żadnego `asyncio.create_task` dla wymaganej pracy biznesowej,
- żadnego RAM-only dedupe/cursor/status,
- żadnego `not Model.boolean_column` w SQLAlchemy filters; używaj `.is_(False/True)`,
- żadnego client-controlled arbitrary URL bez SSRF-safe fetchera,
- żadnego raw provider URL do chronionego artefaktu,
- żadnego frontend success wyłącznie na podstawie HTTP 2xx, jeśli kontrakt oznacza tylko `queued`.

### 20.3. Weryfikacja PR

1. Uruchom najmniejszy focused host-native test/lint/typecheck.
2. Przejrzyj dokładny diff i sprawdź, czy nie objął cudzych zmian.
3. Sprawdź migration heads i idempotency entrypointu.
4. Sprawdź negatywną macierz dostępu, nie tylko happy path.
5. Commit conventional, push task branch, otwórz PR.
6. Poczekaj na required hosted CI.
7. Przy błędzie popraw najwęższy kontrakt, bez szerokiego refactoru.
8. Merge dopiero green.
9. Poczekaj na Coolify deploy.
10. Sprawdź `/api/health` z wymaganym User-Agent i exact 7-char SHA.
11. Dla UI wykonaj realną produkcyjną interakcję w Chrome i screenshot.
12. Dla workera/provider flow sprawdź persisted run/delivery/outcome, nie tylko status procesu.

### 20.4. Format opisu każdego PR

Claude powinien w PR umieścić:

- problem i dowód reprodukcji,
- zakres i jawny out-of-scope,
- threat/failure model,
- schema/API/state transition,
- migrację i backfill,
- flagę, canary i kolejność aktywacji,
- rollback bez utraty pending work,
- testy lokalne i CI,
- telemetry/alert,
- production verification plan.

### 20.5. Zakazane skróty

Claude nie może:

- oznaczyć symulacji jako wysyłki,
- naprawić IDOR tylko ukrywając przycisk,
- traktować admina jako automatycznego delegata cudzej skrzynki,
- użyć `.limit(1)` do rozwiązania niejednoznacznej tożsamości,
- przesunąć cursor po częściowo nieudanym batchu,
- zwrócić 2xx webhookowi przed trwałym zapisem,
- użyć timestamp window jako jedynej idempotencji,
- aktywować stary i nowy sender równolegle,
- wykonać destructive cleanup bez reconciliation i rollbacku,
- uruchomić lokalnego Dockera,
- pominąć production exact-SHA verification.

---

## 21. Definition of Done dla całego modułu

### Bezpieczeństwo i prywatność

- [ ] Każdy endpoint ma capability i object/resource scope.
- [ ] WebSocket nie przenosi bearer JWT w URL.
- [ ] Presence nie ujawnia zbędnego emaila/roli/pola edycji.
- [ ] CalendarFeed blokuje SSRF po każdym redirect i DNS resolution.
- [ ] Mailbox read/send wymaga ownership/delegation/break-glass.
- [ ] Template render nie jest kanałem enumeracji PII.
- [ ] Call/transcript/recording ma candidate/event access.
- [ ] Webhook secrets nie występują w URL/logach.
- [ ] SMTP wymusza weryfikowany TLS.
- [ ] Retencja/purge obejmuje wszystkie pochodne i cache.

### Prawda biznesowa i niezawodność

- [ ] UI rozróżnia draft, queued, sent, failed, dead i uncertain.
- [ ] Każdy external side effect ma trwałe operation/delivery ID.
- [ ] Event/outbox powstaje w tej samej transakcji co stan biznesowy.
- [ ] Webhook zapisuje inbox przed 2xx.
- [ ] Retry jest idempotentny, a provider uncertainty ma reconcile.
- [ ] Cursor nie przesuwa się ponad niezapisany element.
- [ ] Workery mają lease/fencing/heartbeat/last success/backlog.
- [ ] Downtime nie gubi reminderów, triggerów ani recurrence.
- [ ] Ambiguous identity nigdy nie auto-linkuje prywatnych danych.
- [ ] Stage-aware WorkItem/AutomationRule czyta wyłącznie runtime-eligible
      workflow z semantic/edge integrity i pinowaną revision/registry version.

### Produkt

- [ ] Istnieje jeden kanoniczny WorkItem.
- [ ] Bell nie jest systemem zadań; actionable alert deleguje do WorkItem.
- [ ] Manual i M365 Calendar korzystają z jednego kontraktu.
- [ ] Candidate/job chat korzystają z jednego Conversation modelu.
- [ ] Jest pełny Notification Center i Communication Hub.
- [ ] Deep link działa po cold load/refresh.
- [ ] Free/busy error nie jest prezentowany jako free.
- [ ] Templates są wersjonowane i mają scope/publish controls.
- [ ] Status WorkItem pozostaje niezależny od recruitment semantic state, a
      workflow provenance jest niezmiennym snapshotem transition eventu.
- [ ] Timeline jest redagowaną projekcją ze stabilnym cursorem.
- [ ] Settings rozdzielają personal i admin operations.

### UX

- [ ] Kluczowe flow działa keyboard-only.
- [ ] Bell/chat/calendar/hub/work mają właściwe semantics i focus.
- [ ] 320–1440 px jest obsłużone.
- [ ] Loading/empty/error/partial/offline są rozróżnione.
- [ ] Brak hardcoded kolorów poza uzasadnionym data visualization mapping.
- [ ] Brak raw HTML i raw protected URL.
- [ ] Axe nie wykrywa krytycznych naruszeń.

### Testy i release

- [ ] Required CI automatycznie odkrywa wszystkie test files.
- [ ] P0/P1 mają regression tests.
- [ ] Concurrency/crash/replay/cursor/lease fault tests są wymagane.
- [ ] Frontend ma component, contract, a11y i deep-link tests.
- [ ] E2E obejmuje RBAC i rzeczywisty state transition.
- [ ] Migracje przechodzą `upgrade heads` i entrypoint mirror.
- [ ] Shadow parity i reconciliation są bez nierozliczonych różnic.
- [ ] Każdy cutover ma feature flag/canary/rollback.
- [ ] Green PR jest merged i deployed.
- [ ] `/api/health.version` odpowiada wdrożonemu SHA.
- [ ] User-visible flow jest sprawdzony w produkcji w Chrome.

---

## 22. Decyzje, których Claude nie może podjąć po cichu

W raporcie należy rozróżnić trzy poziomy:

| Status | Znaczenie | Przykład |
|---|---|---|
| `CONFIRMED CURRENT` | fakt potwierdzony w kodzie/produkcji | admin/DL mają obecnie szeroki mailbox read; Calendar list jest globalna |
| `RECOMMENDED FAIL-CLOSED` | bezpieczne zachowanie proponowane do czasu decyzji | mailbox owner-only; ambiguous recording bez auto-attach |
| `PRODUCT/SECURITY DECISION` | polityka, której kod nie może sam ustalić | break-glass, retencja, recurrence, fan-out |

Domyślny admin/DL mailbox access i globalna calendar visibility są potwierdzonym stanem obecnym, nie zatwierdzoną polityką docelową. Owner-only/delegation/break-glass to rekomendacja bezpieczeństwa wymagająca formalnej akceptacji przed szerokim rolloutem.

Przed finalnym modelem lub rolloutem potrzebna jest decyzja ownera produktu/security dla:

1. Czy admin ma kiedykolwiek czytać cudzą skrzynkę bez formalnego break-glass?
2. Jaki jest dokładny resource scope recruitera i Delivery Leada dla kandydatów, jobów i klientów?
3. Czy WorkItem ma jednego assignee, czy współdzieloną odpowiedzialność?
4. Które alerty są obowiązkowe i nie mogą być wyłączone preferencją?
5. Jakie quiet hours/weekend/holiday calendars obowiązują?
6. Jak długo przechowywać body emaila, chat, transkrypt, nagranie, recording URL i rendered preview?
7. Jak działa legal hold i kto może go ustawić/zdjąć?
8. Czy deleted chat ma zachować tombstone/revision dla audytu, a jeśli tak — jak długo?
9. Które template variables są dozwolone per channel/purpose?
10. Kto może publikować organization-wide template/automation?
11. Jaki jest maksymalny fan-out/bulk send i czy wymaga akceptacji drugiej osoby?
12. Czy recurrence ma wspierać pełne RRULE, czy ograniczony produktowy podzbiór?
13. Jaki jest catch-up horizon dla przeterminowanych reminderów?
14. Czy prywatne eventy M365 mogą być przechowywane jako busy-only?
15. Jak obsłużyć istniejące niejednoznaczne phone/recording/transcript links?
16. Kiedy provider outcome `uncertain` można ręcznie uznać za sent/not sent?
17. Jakie SLO i progi alertów zatwierdza ops?
18. Czy Redis jest zatwierdzonym elementem produkcyjnym dla realtime, czy użyć DB-backed fallback?
19. Jak długo utrzymywać compatibility endpoints i stare URL-e?
20. Kto akceptuje reconciliation mismatch przed cutoverem?

Domyślna bezpieczna odpowiedź do czasu decyzji: brak dostępu, brak automatycznego linkowania, brak wysyłki, brak purge objętego legal hold oraz jawny stan wymagający review.

---

## 23. Rekomendowany pierwszy sprint

Pierwszy sprint nie powinien budować Communication Hub ani nowego kalendarza. Najpierw trzeba przywrócić prawdę i zamknąć największe wycieki.

### Sprint 1 — zakres

1. PR-00 inventory/safety lane.
2. PR-01 wyłączenie fałszywego email success.
3. PR-02 unread/mark-all.
4. PR-03 WebSocket ticket + presence access/minimization.
5. PR-04 Template/Notes/Calendar scope containment.
6. PR-05 mailbox/send/calls containment.
7. PR-06 CloudTalk/Fireflies admin + webhook route containment.
8. PR-07 SSRF-safe CalendarFeed.
9. PR-08 artifact quarantine/purge foundation.
10. PR-09 SMTP TLS i Activity redaction.

### Sprint 1 — mierzalny wynik

- użytkownik nie dostaje fałszywego „wysłano”,
- notification unread działa,
- JWT nie jest w WS URL,
- viewer nie enumeruje PII przez template/notes/calendar/calls,
- user bez delegacji nie wysyła i nie czyta cudzej skrzynki,
- CloudTalk secret nie trafia do URL,
- iCal nie może sięgnąć do sieci prywatnej,
- ambiguous recording jest quarantined,
- SMTP failuje zamknięcie przy złym TLS,
- Activity nie zwraca raw details globalnie.

### Sprint 1 — nie w zakresie

- nowy WorkItem,
- redesign całego Calendar,
- Communication Hub,
- pełny outbox,
- migracja chatów,
- automatyczny purge historycznych artifacts bez wcześniej zatwierdzonej retencji.

To świadomy containment sprint. Po nim Fala B buduje kernel, bez którego kolejne feature'y tylko zwiększyłyby liczbę nietrwałych ścieżek.

---

## 24. Gotowy brief do przekazania Claude Code

```text
Pracujesz w repozytorium NEXUS.

Źródło planu:
docs/communication-activities-tasks-calendar-automation-module-audit-and-claude-implementation-plan-2026-07-16.md

Wykonuj plan PR po PR, zaczynając od PR-00. Nie implementuj całego modułu w jednym branchu.

Obowiązkowo:
1. Przeczytaj AGENTS.md oraz sekcje 13, 16, 18, 20 i 21 raportu.
2. Przed zmianą fetch origin/main i sprawdź, czy fix nie istnieje.
3. Zachowaj obce lokalne zmiany; pracuj na izolowanej gałęzi/worktree.
4. Najpierw reprodukcja/regression test, potem minimalna zmiana.
5. Każdy access fix egzekwuj backendowo capability + object/resource scope.
6. Każdy external side effect modeluj jako persisted operation po business commit.
7. Każda schema change: Alembic upgrade heads + entrypoint mirror + test.
8. Nie używaj lokalnego Dockera ani npx shadcn add.
9. Dla każdego PR opisz flagę, canary, reconciliation i rollback.
10. Uruchom focused host-native checks, potem hosted CI.
11. Merge tylko green, obserwuj deploy, sprawdź exact SHA w /api/health z wymaganym User-Agent.
12. Każdą widoczną zmianę sprawdź w produkcji w Chrome.

Nie zmieniaj po cichu decyzji z sekcji 22. Przy braku decyzji wybierz bezpieczne fail-closed i zatrzymaj tylko ten fragment, nie cały pozostały PR.

Po każdym PR zwróć:
- commit i PR,
- zmieniony kontrakt,
- testy i CI,
- migrację/backfill,
- rollout flag/canary,
- deployed SHA,
- production verification,
- pozostałe ryzyko i następny PR.
```

---

## 25. Rekomendacja końcowa

Moduł nie potrzebuje kolejnej warstwy przycisków i cronów. Potrzebuje jednej sprawdzalnej pętli:

```text
uprawniona komenda
  -> trwały stan biznesowy
  -> committed event
  -> trwała projekcja/zadanie/delivery
  -> leased worker
  -> ponowna kontrola dostępu
  -> provider albo UI
  -> potwierdzony wynik
  -> timeline, telemetry i reconciliation
```

Najpierw należy wdrożyć containment P0. Następnie wspólny kernel trwałości. Dopiero później WorkItem, Calendar/Conversation v2 i nowe product surfaces. Odwrócenie tej kolejności stworzyłoby ładniejszy interfejs nad systemem, który nadal może zgubić wiadomość, przypisać transkrypt do złej osoby albo potwierdzić wysyłkę, której nie było.

Po wykonaniu planu NEXUS będzie miał:

- prawdziwą, audytowalną komunikację,
- jedną kolejkę pracy człowieka,
- odporny na restart kalendarz i reminders,
- bezpieczny realtime i conversations,
- kontrolowane integracje z jasnym ownerem i stanem,
- jedną redagowaną historię,
- testy i operacyjne dowody wystarczające do bezpiecznego rozwijania kolejnych automatyzacji.

---

## 26. Mapa najważniejszych źródeł kodowych

Poniższa mapa ma ułatwić Claude wejście w implementację; numery linii mogą się przesunąć po kolejnych merge'ach, dlatego przed zmianą należy ponownie użyć `rg` i czytać bieżący `origin/main`.

| Obszar | Główne pliki |
|---|---|
| Fake email i templates | `backend/app/api/emails.py`, `frontend/src/components/SendEmailV2.tsx`, `backend/app/api/user_email_templates.py` |
| Notifications | `backend/app/api/notifications.py`, `backend/app/services/notification_service.py`, `backend/app/tasks/notification_triggers.py`, frontendowy hook/bell |
| WebSocket/presence | `backend/app/api/ws.py`, `backend/app/api/presence.py`, frontendowy `useNotifications` i realtime hooks |
| Notes/activity/timeline | `backend/app/api/notes.py`, Activity/UserActivity models i candidate/job timeline UI |
| Candidate/job chat | candidate-chat i job-chat routers/services/models oraz oba frontendowe chat views |
| Calendar/iCal | `backend/app/api/calendar.py`, `backend/app/services/ical_import.py`, calendar frontend |
| M365 mail/calendar/webhooks | `backend/app/api/microsoft365.py`, `backend/app/api/email_threads.py`, `backend/app/services/m365/`, `backend/app/tasks/microsoft365_sync.py` |
| Rejection/outbound mail | rejection email API/scheduler, `backend/app/services/m365/sender.py`, SMTP email service |
| Calls/CloudTalk | `backend/app/api/calls.py`, `backend/app/api/cloudtalk.py`, `backend/app/services/cloudtalk/`, `backend/app/tasks/cloudtalk_sync.py` |
| Fireflies | `backend/app/api/fireflies.py` i service/model notes integration |
| LinkedIn/Proxycurl | odpowiedni sync task/service oraz candidate enrichment models |
| Upstream workflow Modułu 4 | `backend/app/models/workflow_revision.py`, `backend/app/services/semantic_states.py`, `backend/app/services/workflow_registry_service.py`, `backend/app/api/admin_workflows.py` |
| Background registry | `backend/app/main.py`, task modules, admin snapshot |
| CI | `.github/workflows/ci.yml`, frontend Vitest/Playwright config i backend test manifest |
| Migrations/startup | `backend/alembic/`, `backend/entrypoint.sh` |

Koniec raportu.

---
