# Audyt długu technicznego — stan końcowy, 2026-08-23

> Źródło prawdy: [`tech-debt-backlog.json`](tech-debt-backlog.json) (169 pozycji).
> Czytelny przekrój znalezisk: [`tech-debt-audit-2026-08-21.md`](tech-debt-audit-2026-08-21.md).
> Procedura kopii off-site: [`runbook-backup-201.md`](runbook-backup-201.md).

## Liczby

| status | ile | co to znaczy |
|---|---|---|
| **zrobione** | **153** | zmergowane, wdrożone, z testem i kontrolą negatywną |
| czeka na Ciebie | 10 | sekrety, konta albo decyzja produktowa — nie da się tego zrobić za Ciebie |
| nieaktualne | 4 | zastąpione innym znaleziskiem |
| świadomie odrzucone | 2 | naprawa kosztowałaby więcej niż defekt |

PR-y: #1225–#1229 (fale 1–5), #1235 (#401/#402), #1236 (#403–#407), #1237 (#408, #212, #315).

## Co się okazało ważniejsze niż liczby

**Backlog sam z siebie nie zatrzymuje niczego.** 19 z 31 regresji, które przyszły
w PR-ach z codeksa, było POWTÓRZENIEM klas opisanych w audycie dzień wcześniej.
Notatka nie broni — broni test. Dlatego w tej fali każda naprawa dostała
strażnika, a każdy strażnik przeszedł kontrolę negatywną: sabotuję poprawkę
i sprawdzam, czy test się zapala. Trzy razy okazało się, że **nie**:

- strażnik `_pick_parties` przepuszczał piątą kopię pod inną nazwą,
- testy #408 mockowały funkcję, którą miały weryfikować, więc sklejenie stanów
  przechodziło na zielono,
- test „padnięty commit" podmieniał metodę zamiast psuć transakcję, więc
  przechodził też bez naprawy.

Każdy z tych testów wyglądał na zielony i nie znaczył nic.

**Trzy strażniki w tym repo nie pilnowały tego, co obiecywały** (#404). `_calls_in`
żył w czterech kopiach, z których trzy liczyły wywołania wyłącznie przez
`ast.Name` — więc `modul.funkcja(...)` było dla nich niewidoczne. Wstrzyknięcie
zakazanego wywołania zostawiało test **zielony**.

**Najgroźniejsza klasa nie objawia się pustką, tylko normalnym wynikiem** (#408).
Gdy Qdrant milczał, oba tiery podpowiedzi milkły, a auto-generator dolewał
pytania jako bezpiecznik. Rekruter dostawał wiarygodną listę i nie miał jak się
dowiedzieć, że dwa najlepsze źródła nie odpowiedziały.

**Poprawka potrafi istnieć dokładnie tam, gdzie nie działa** (#315). Migracja 0238
została poprawiona na `normalize(..., NFC)`, ale jej lustro w `entrypoint.sh` —
to, które realnie wykonuje się na produkcji, bo prod alembic bywa osierocony —
dalej porównywało surowy napis.

## Co czeka na Ciebie

Kolejność wg wagi. Pierwsza pozycja jest jedyną, która grozi utratą danych.

---

### #201 · P0 — Kopia off-site nigdy nie została zweryfikowana: drill przywracania pada 4 tygodnie z rzędu (brak sekretów), a monitor świeżości jest wyłączony — ~136k CV bez potwierdzonej kopii [3 niezależne agenty doszły do tego samego]
NEXUS trzyma ~49k profili kandydatów i ~136k plików CV (~37 GB), które nie istnieją nigdzie
indziej — `pg_dump` zachowuje wyłącznie `candidate_documents.storage_key`, czyli wskaźniki. W
repo jest dowód na dokładnie zero udanych przywróceń end-to-end kopii off-site: `gh run list
--workflow backup-drill.yml` pokazuje failure 2026-08-17, 2026-08-10, 2026-08-03 i 2026-07-27 —
każdy run od czasu, gdy PR #924 (2026-07-27) wprowadził drill, który realnie pobiera,
deszyfruje przez `age -d` i robi `pg_restore` prawdziwego artefaktu off-site. Log runu
31994028868 pokazuje, że `BACKUP_S3_ACCESS_KEY` i `BACKUP_S3_SECRET_KEY` rozwijają się do
pustych stringów, a `gh secret list` na repo zwraca tylko `CLAUDE_CODE_OAUTH_TOKEN`,
`COOLIFY_APP_UUID`, `COOLIFY_TOKEN`, `COOLIFY_URL` — `BACKUP_AGE_PRIVATE_KEY`,
`BACKUP_S3_ACCESS_KEY` i `BACKUP_S3_SECRET_KEY` nie istnieją. Równolegle `gh variable list`
pokazuje `BACKUP_MONITORING_ENABLED=false` (ustawione 2026-07-27), więc job `backup-freshness`
w uptime-probe, który czyta `LATEST.json`, jest skipowany przy każdym godzinowym biegu.
Komentarz w samym workflow mówi, że `LATEST.json` „nie miał ŻADNEGO czytelnika w całym
repozytorium" — to nadal jest prawda. Czyli obie połówki siatki bezpieczeństwa (czy backup w
ogóle powstaje? czy da się go odtworzyć?) są jednocześnie martwe.
**Czego potrzeba od Ciebie:**

Działanie operatorskie, nie zmiana w kodzie: (1) wygeneruj dedykowaną parę kluczy age dla
drilla, dopisz jej publiczną połówkę do rozdzielanej przecinkami listy odbiorców w
`backup/backup.sh` (dzięki czemu nic nie wymaga ponownego szyfrowania) i wstaw prywatną połówkę
do sekretu repo `BACKUP_AGE_PRIVATE_KEY` — nigdy klucza głównego; (2) utwórz read-only
application key w B2 ograniczony do `dynaminds-nexus-offsite` i ustaw `BACKUP_S3_ACCESS_KEY` /
`BACKUP_S3_SECRET_KEY`; (3) odpal `gh workflow run backup-drill.yml` i przeczytaj
`LATEST.json`, który wypisze — ten jeden bieg odpowiada, czy kopia off-site w ogóle istnieje;
(4) przełącz `BACKUP_MONITORING_ENABLED=true`, żeby godzinowa kontrola świeżości przestała być
skipowana. Do czasu, aż (3) zaświeci na zielono, traktuj backup off-site jako nieistniejący.
---
### #37 · P1 — PR #539 usunął jedyne wejście do czytnika wątków M365 na fałszywym uzasadnieniu "duplikat" — 1473 LOC + 7 żywych endpointów osierocone, podczas gdy sync dalej zapisuje na prodzie treści maili kandydatów i załączniki
Rekruter podłącza swoją skrzynkę w Ustawienia → Microsoft 365 (ta karta JEST żywa —
settings/page.tsx:434), a backend następnie zaciąga 12 miesięcy skrzynki odbiorczej i
wysłanych, dopasowuje każdą wiadomość do kandydata i zapisuje `subject`, `from_address`,
`to_addresses`, `cc_addresses`, `body_html`, `body_text` oraz załączniki
(models/m365.py:183-209). Prodowe `/api/health` zwraca `"m365": "healthy"`, co wg
main.py:1416-1435 wymaga włączonej flagi integracji, włączonej pętli syncu **i co najmniej
jednego aktywnego wiersza M365Connection** — więc dzieje się to w tej chwili, na prawdziwej
korespondencji. Nigdzie w produkcie nie ma ekranu, żeby cokolwiek z tego przeczytać. Siedem
żywych endpointów backendu (`GET /api/candidates/{id}/emails`,
`.../emails/thread/{conversationId}`, `GET /api/emails/{id}`, pobieranie załącznika, `POST
.../emails/compose`, `.../emails/reply`, `POST /api/microsoft365/emails/bulk`) ma zero
wołających. Dwie konkretne straty: (a) historia korespondencji z kandydatem, której rekruter
potrzebuje przed rozmową, jest niewidoczna, oraz (b) ponieważ ocalałą akcją jest `mailto:`,
poczta wychodząca leci z własnego Outlooka rekrutera i nigdy nie jest zapisywana z powrotem
przy rekordzie kandydata — więc historia wątku, która JEST synchronizowana, jest wyłącznie
przychodząca i trwale jednostronna. Jest też wątek RODO: treści maili kandydatów są zbierane i
przechowywane bez żadnej powierzchni, która by czemukolwiek służyła.
**Czego potrzeba od Ciebie:**

Najpierw rozstrzygnij intencję produktową, bo oba kierunki są tanie, a jedyny drogi jest stan
obecny. Jeśli czytanie maili ma być: przywróć zakładkę `emails` do tablicy `tabs` w
CandidateDetailV2, renderującą `<EmailThreadList candidateId=… />` — komponent i jego troje
dzieci są nietknięte i wciąż otypowane pod żywą powierzchnię `microsoft365Api`. Commit 4925ac53
(#539, 2026-06-18) usunął zakładkę, twierdząc "Email jest już dostępny w menu Więcej
(przeniesiony w #538)", ale to, co wylądowało w tamtym menu, to kompozytor mailto, a nie
czytnik wątków — więc parytet, który ten commit deklarował, nigdy nie był prawdą. Jeśli
czytanie maili NIE ma być: usuń `src/components/emails/` (1473 LOC) plus `src/lib/email-
threading.ts` (79 LOC), wywal siedem nieużywanych endpointów z `email_threads.py` i wyłącz
`M365_SYNC_LOOP_ENABLED`, żeby produkt przestał przechowywać treści maili kandydatów, których
nie umie pokazać.
---
### #96 · P1 — Wtyczka LinkedIn ma JEDYNĄ ścieżkę logowania — email+hasło — a prod zwraca na niej 503, bo logowanie hasłem jest wyłączone; wtyczka nie ma przycisku Microsoft SSO i nikt tego nie testuje
Rekruter, który instaluje wtyczkę (albo wyczyścił profil Chrome, albo nie używał jej przez 30
dni, albo dostał zmianę roli — co bumpuje `authorization_version` i unieważnia refresh token)
NIE MA jak się zalogować. Modal na LinkedInie na stałe pokazuje „Aby dodawać kandydatów,
zaloguj się do NEXUS", a strona ustawień wypluwa surowy blob `Login failed (HTTP 503):
{"detail":"Logowanie hasłem jest wyłączone. Zaloguj się przez Microsoft."}` — bez żadnej
podpowiedzi, bo wtyczka nie ma przycisku Microsoft SSO. Jedyna ścieżka „jednym kliknięciem z
LinkedIna do bazy" jest dla nowego użytkownika martwa. Osobno: to jest dowód, że zmiana w
backendzie potrafi cicho zabić ten klient — nic go nie testuje, nie ma go w żadnym workflow,
żaden healthcheck go nie dotyka, więc awaria z 19 lipca przeżyła miesiąc bez śladu.
**Czego potrzeba od Ciebie:**

Najpierw zdecyduj, korzystając z odpowiedzi, którą ten finding już daje: jeśli nikt nie trzyma
sesji sprzed 19 lipca, `git rm -r extension/` i usuń osierocony router `/api/candidates/from-
linkedin` (ma ZERO wołających w frontend/src — zweryfikowane grepem — więc wtyczka jest jego
jedynym klientem). Jeśli wtyczka jest nadal w użyciu, ścieżka autoryzacji musi przeżyć tryb
SSO-only. Repo już dostarczyło właściwy mechanizm w migracji 0220: konta serwisowe z `X-API-
Key`, scope'y per konto czytane na świeżo przy każdym requeście, obowiązkowe wygasanie i
natychmiastowa rewokacja. Potrzeba jednej nowej wartości w `ServiceScope` (np.
`candidate:write_linkedin`) i `require_service_scope(...)` na dwóch endpointach wtyczki; strona
ustawień przyjmuje wtedy wklejony klucz `nxs_v2_…` zamiast hasła, co przy okazji usuwa
30-dniowy refresh token z `chrome.storage` w całości. Tak czy inaczej, dodaj extension/ do joba
CI (eslint + test kontraktowy asertujący trzy ciała requestów przeciwko zacommitowanemu
openapi.json), żeby następne przełączenie w backendzie nie mogło go znowu po cichu zabić.
---
### #202 · P1 — Każda z 11 funkcji AI działa na prodzie bez miesięcznego sufitu — warstwa kwot jest fail-open, a limit z Ustawienia→AI nie jest egzekwowany nigdzie
Żywe prodowe `/api/health` zwraca w tej chwili `"ai_features": "uncapped: candidate_summary,cha
mpion_draft,champion_profile_parse,cv_backfill,cv_interactive_chat,cv_parser,cv_requirement_map
,job_description_generator,notes_extraction,order_parser,scoring"` — to wszystkie 11 wartości
`AIFeatureKey` (backend/app/models/ai_feature.py:47-62). Komentarz samej sondy health
(backend/app/main.py:1673) dokumentuje, że „uncapped" obejmuje zarówno brak wiersza, jak i
`monthly_limit = 0`, a docstring `ai_quota.py` potwierdza `monthly_limit = 0` → bez limitu.
Przy `limit = 0` powyższa gałąź nie może się nigdy odpalić, więc `check_and_increment` niczego
nie blokuje. Panel Ustawienia→AI obiecuje adminowi miesięczny sufit per funkcja („Traffit
pokazuje 2 994 / 20 000 scoringów" wg docstringu modelu); na prodzie to pole nie robi nic dla
żadnej funkcji. Najostrzejsza ekspozycja to `cv_interactive_chat`, dostępny dla hiring
managerów w ogóle bez konta w NEXUSIE: public_share.py:404 dokumentuje warstwy jako „rate limit
(IP), dzienny limit pytań per link (429), globalna kwota AI (503)" — dzienny limit jest PER
LINK, więc N udostępnionych linków do CV = N × `CV_INTERACTIVE_CHAT_DAILY_LIMIT` wywołań
Claude'a dziennie, a jedynym globalnym zabezpieczeniem jest kwota, która obecnie jest bez
sufitu. `cv_backfill` (masowe wzbogacanie ~39k CV, z własnym kubełkiem właśnie po to, żeby nie
wyczerpał limitu rekruterów) i `scoring` mają ten sam brak podłogi.
**Czego potrzeba od Ciebie:**

Zasiej wiersz w `ai_features` dla każdej z 11 wartości `AIFeatureKey` ze świadomym
`monthly_limit > 0` (funkcje interaktywne mogą dostać hojne wartości; `cv_backfill` i
`notes_extraction` powinny dostać liczbę wielkości wsadu, a `cv_interactive_chat` wartość,
która przetrwa zły tydzień na jednym udostępnionym linku). Zrób to jako migrację plus lustro
DDL w `entrypoint.sh`, żeby przeżyło ścieżkę z osieroconym alembikiem. Potem potwierdź, że
`/api/health` raportuje `checks.ai_features == "healthy"` — ten string jest testem
akceptacyjnym.
---
### #204 · P1 — Workflow dziennego digestu Sentry raportuje sukces każdego ranka, nie robiąc nic — `SENTRY_AUTH_TOKEN` nigdy nie został ustawiony, więc krok kończy się natychmiast z kodem 0
`gh secret list` na repo zwraca dokładnie cztery sekrety (`CLAUDE_CODE_OAUTH_TOKEN`,
`COOLIFY_APP_UUID`, `COOLIFY_TOKEN`, `COOLIFY_URL`) — ani `SENTRY_AUTH_TOKEN`, ani
`SLACK_WEBHOOK_URL` nie istnieje. API GitHuba dla najnowszego biegu (32342419428, 2026-08-20
07:05) pokazuje, że job wystartował 07:05:39 i zakończył się 07:05:45 z każdym krokiem
„success": sześć sekund łącznie, czyli checkout plus setup-python — `sentry_daily_digest.py` w
ogóle się nie wykonuje. Pięć ostatnich biegów z harmonogramu (08-16 do 08-20) jest zielonych.
Zgodnie z ~/.claude/rules/observability.md Sentry to wyznaczony kanał błędów i wydajności dla
`nexus-be` i `nexus-fe`; dzienny digest jest mechanizmem, który miał postawić przed człowiekiem
pythonowe 500 albo error boundary Reacta. W tej chwili jedyny automatyczny sygnał produkcyjny,
który do kogokolwiek dociera, to uptime-probe (sprawdzający, czy baza odpowiada na `SELECT 1`)
i disk-alert. Burza wyjątków w backendzie daje zielony dashboard Actions.
**Czego potrzeba od Ciebie:**

Zapewnij `SENTRY_AUTH_TOKEN` (Sentry → Settings → Auth Tokens, scope read na b2bnet-sa) i
`SLACK_WEBHOOK_URL` jako sekrety repo, potem `gh workflow run sentry-daily-monitor.yml` i
potwierdź, że digest faktycznie się publikuje. Zmień też gałąź pomijania z `exit 0` na `exit 1`
— backup drill nauczył się tej lekcji w tym samym repo („Drill DR, którego nie da się
uruchomić, to drill PADNIĘTY"); monitor, który nie może monitorować, musi być czerwony, nie
zielony.
---
### #212 · P1 — Suite E2E w Playwrighcie nie weryfikuje niczego: 40 z 46 przypadków testowych nigdy się nie wykonuje z braku sekretów, a jedyny projekt, który faktycznie chodzi, jest czerwony od 21 nocy z rzędu
Każdy zalogowany przepływ użytkownika w ATS — logowanie, tworzenie kandydata, przesuwanie
kandydata między etapami pipeline'u, pisanie notatki z @wzmianką, ręczne wyszukiwanie CV, UX
dopasowań, rekomendacje, ekrany admina dynareportera — nie ma ŻADNEJ weryfikacji na poziomie
przeglądarki i nie ma jej co najmniej od 2026-07-16. Ta luka nakłada się na 27,2% pokrycia
unitami we frontendzie, gdzie każda strona route'u `src/app/**` poza `/login` ma 0% statements.
W połączeniu z findingiem #4 (klient API jest mockowany w 51 ze 148 testów jednostkowych) nic w
tym repozytorium nigdy nie steruje prawdziwą stroną wobec prawdziwego backendu. Regresja w
przejściach etapów albo w tworzeniu kandydata trafia najpierw do rekruterów.
**Czego potrzeba od Ciebie:**

Dwie rozdzielne naprawy. Natychmiastowa (S): zmienić `e2e/candidate-ux-preview.spec.ts:104` na
`getByText("Stawka B2B")`, żeby nocny bieg przestał podnosić fałszywy alarm. Właściwa naprawa
(M): sprovisionować E2E_USER_EMAIL/E2E_USER_PASSWORD dla dedykowanego prodowego konta E2E, żeby
projekt `chromium` faktycznie chodził, i albo dodać powiadomienie o porażce nocnego biegu, albo
przyjąć do wiadomości, że trwale czerwony, nieoglądany workflow jest gorszy niż brak workflow.
**Część kodowa jest już zrobiona:**

(a) asercja na przeterminowanej etykiecie naprawiona wcześniejszą falą — nocny bieg wstał
2026-08-23 po 21 czerwonych nocach; (b) sam SYGNAŁ przestał kłamać — bieg wypisuje teraz własne
pokrycie do podsumowania zadania (6 z 46 przypadków, 1 z 12 plików) i mówi wprost, że zielony
wynik NIE znaczy, że E2E przechodzi. Komentarz twierdzący, że zawężenie zakresu utrzymuje bieg
'green and honest', był fałszywy: zielone przy 13% pokrycia jest ciche, nie uczciwe — ta sama
klasa co awaria udająca pustkę.
---
### #130 · P1 — Wiersze cache zatrute przez #32 nie naprawiają się same — wymagają jednorazowego unieważnienia na produkcji
Poprawka #32 zatrzymuje POWSTAWANIE nowych zaniżonych wyników, ale nie naprawia tych, które już
powstały. Zatruty wiersz ma BIEŻĄCĄ wersję algorytmu i stale=false, więc nowy, poprawny
predykat też uzna go za świeży. Kandydaci, których pipeline ktoś otworzył między bumpem wag
17-18.08 a wdrożeniem poprawki, mają trwale zaniżony pierścień dopasowania (do 60 ze 100
punktów).
**Czego potrzeba od Ciebie:**

Decyzja Artura: (a) tępo i bezpiecznie — UPDATE candidate_job_match_scores SET stale = true
(przeliczenie jest leniwe, przy odczycie, więc koszt rozkłada się w czasie; ceną jest
jednorazowy zimny start scoringu), albo (b) wąsko — unieważnić tylko wiersze, których warstwa
semantyczna ma 0 punktów, a kandydat MA wektor w Qdrancie (wymaga zapytania krzyżowego do
Qdranta). Wymaga dostępu do produkcyjnej bazy, którego nie mam.
---
### #101 · P2 — Cutover RBAC dashboardów z #1031 po cichu odciął konsolę Priority Work: 23 z 24 endpointów są dziś nieosiągalne z jakiejkolwiek trasy, a tworzenie assignmentu — jedyna operacja, która nadaje sens przejściu off→shadow — nigdy nie miało UI w ogóle
1743 linie routera + 1131 linii serwisu + 817 linii polityki + 9 tabel produkcyjnych + pętla w
lifespanie są utrzymywane dla funkcji, której nikt nie może otworzyć. Konkretnie: nie ma ekranu
do opublikowania planu priorytetów, zgłoszenia lub odpowiedzi na zapotrzebowanie, podniesienia
lub rozstrzygnięcia blokera, przyznania wyjątku KPI ani przekazania procesu innemu
właścicielowi. Więc bezpieczny rollout, który zaleca config.py:490-493 („Safe rollout is always
off -> shadow -> enforce"), jest nie tylko nieużywany — jest niewykonalny, bo przestawienie
`RECRUITMENT_PRIORITY_MODE` na `enforce` bez opublikowanego planu zablokowałoby każdemu
rekruterowi otwarcie jakiejkolwiek nowej pary kandydat/rekrutacja, bez UI do odblokowania.
Tymczasem koszt jest płacony codziennie na gorących ścieżkach: `ensure_job_membership` i
`job_scope_clause` rozgałęziają się po tabelach priorytetowych na każdym wejściu do pipeline'u,
/api/jobs odpala dwa dodatkowe podzapytania priorytetowe na każde żądanie listy, a 7 żywych
ścieżek wejściowych wciąż zapisuje wiersze `recruitment_processes`.
**Czego potrzeba od Ciebie:**

Zdecyduj, potem działaj — nie bramkuj. Jeśli model jest nadal chciany: zamontuj ponownie
`TeamAllocationBoard` na presecie HoR w `RoleDashboard`, `MyPriorityQueue` na presecie my-work,
a `PriorityRequestsPanel` na presecie delivery-lead (DeliveryTabs.tsx już to spina) i najpierw
napraw opisany niżej błąd przejścia statusu. Dodaj klientów frontendowych dla 7 endpointów,
które ich nie mają. Jeśli jest porzucony: usuń router+serwis+politykę+task+komponenty w jednym
PR, a DROP tabel zaplanuj osobno — `recruitment_priority_*` niesie FK do `jobs` i `users`, a
`recruitment_processes` jest czytane przez `ensure_job_membership`, więc DROP wymaga takiej
samej analizy, jaką dostał drop dynareportera. Tak czy inaczej, w tej samej zmianie skasuj
~3500 linii niezamontowanych komponentów, żeby następny audytor nie musiał wyprowadzać tego od
nowa.
---
### #323 · P2 — Dla persony, pod którą PR powstał (DL bez przypisań), każdy wiersz rejestru kończy się 403 po kliknięciu — przyczyna źródłowa nietknięta
`delivery_lead_job_pairs` (recruitment_access.py:426) ma w docstringu wprost: „An empty set is
deny-all and must never fall back to the organization." PR nie naprawia pustego zbioru — omija
go na jednej trasie. Dla DL bez żadnego wiersza w ClientTacAssignment (czyli dokładnie dla
przypadku z opisu PR: „an empty relationship graph must not turn the top-level /jobs register
into 'Brak rekrutacji'") zbiór par jest pusty, więc `_assert_delivery_lead_job_visible` odrzuca
KAŻDĄ ofertę. Rejestr pokazuje komplet, ale 100% wierszy jest nieotwieralnych — „Brak
rekrutacji" zamieniło się w listę martwych linków. To ta sama sygnatura, którą CLAUDE.md
opisuje przy Talent Radar i generatorze B2B: „link widoczny, klik = 403" — z tą różnicą, że tam
(#1215, #1216) domknięto ją otwierając też dane pod spodem, a tu otwarto samą listę. Test PR-a
utrwala ten stan jako kontrakt. Łagodzące i dlatego P2, nie wyżej: front obsługuje to poprawnie
— `frontend/src/app/jobs/[id]/page.tsx:1128` renderuje `QueryStateNotice` ze stanem `forbidden`
i komunikatem „Nie masz uprawnień do tej rekrutacji. Rekrutacja istnieje — poproś o dodanie Cię
do jej zespołu albo o rozszerzenie roli.", więc to nie jest 403 udające pustkę ani awarię.
**Czego potrzeba od Ciebie:**

Rozstrzygnąć, co ma być prawdą, zamiast trzymać dwie: albo (a) uzupełnić dane — DL-om brakuje
wierszy `ClientTacAssignment`/`DeliveryLeadClientAssignment` i to jest właściwa naprawa,
jednorazowa i bez zmiany kodu; albo (b) świadomie otworzyć ODCZYT detalu dla DL z tą samą
redakcją pól co lista (salary + champion_profile + close_notes), zostawiając mutacje i pipeline
na dotychczasowym `_ensure_delivery_lead_job_visible`. Wariant (b) zamyka też P1, bo redakcja
staje się jedną, wspólną regułą dla obu powierzchni. Jeśli stan obecny ma zostać — warto to
zapisać w CLAUDE.md, bo dziś docstring `delivery_lead_job_pairs` mówi coś przeciwnego niż
zachowanie `/api/jobs`.
---
### #315 · P3 — Poprawka NFD zastosowana punktowo do jednego wiersza, a nie do predykatu — siostrzane nazwisko z 0238 ma tę samą podatność
0238 dopasowywał osoby przez `lower(trim(ca.name) || ' ' || trim(ca.lastname)) IN (...)`, czyli
porównanie CAŁEGO napisu — i to właśnie się wywróciło na rekordzie zapisanym w NFD, co 0239
naprawia dla Roberta Łuszczyńskiego prefiksem `LIKE 'Łuszcz%'`. Ale na liście 0238 jest jeszcze
jedno nazwisko z tą samą podatnością: `michał leśniak` zawiera `ś` (U+015B), które NFD rozkłada
na `s` + U+0301, dokładnie jak `ń` w `Łuszczyński` (`ł` i `Ł` są atomiczne, więc same z siebie
nie psują porównania). Pozostałe siedem pozycji to albo czysty ASCII, albo wyłącznie `ł`/`ą`
bez znaków rozkładanych w sposób psujący prefiks. 0239 poprawia jeden wiersz i nie usuwa
przyczyny, więc jeśli rekord Leśniaka też jest w NFD, jego kontrakt do dziś zostaje szkicem —
cicho, bo 0238 nie raportuje, ilu z dziewięciu ludzi faktycznie trafił. Nie mam dostępu do
produkcji, więc nie twierdzę, że tak jest — opis PR mówi o dwóch rekordach znalezionych podczas
weryfikacji. Zgłaszam klasę, nie fakt.
**Czego potrzeba od Ciebie:**

Sprawdzić na prodzie `SELECT id, name, lastname, status FROM contracts JOIN candidates ...
WHERE lastname LIKE 'Le%niak'` i przy okazji następnej korekty tego typu porównywać po
`normalize('NFC', ...)` albo po prefiksie bez znaków rozkładanych, zamiast po całym napisie —
inaczej ta sama pułapka wróci przy kolejnej liście nazwisk.
**Część kodowa jest już zrobiona:**

lustro w entrypoint.sh normalizuje teraz kolumnę do NFC, tak jak migracja 0238. To lustro jest
WAŻNIEJSZE od samej rewizji — prod alembic bywa osierocony, więc na produkcji wykonuje się
właśnie ono, czyli poprawka istniała dokładnie tam, gdzie nie działa. Strażnik
test_migration_0238_name_matching rozszerzony na OBA źródła (kontrola negatywna: cofnięcie
normalizacji w lustrze zapala test).
---

## Czego świadomie nie zrobiłem

- **Nie generowałem kluczy ani nie zakładałem kont** (#201, #204, #212). To
  poświadczenia produkcyjne; ich wartości nie powinienem widzieć nawet raz.
  Runbook z dokładnymi komendami leży w `runbook-backup-201.md`.
- **Nie flipnąłem `BACKUP_MONITORING_ENABLED`** — włączenie monitoringu przed
  wgraniem sekretów zrobiłoby z `uptime-probe` trwale czerwony workflow, czyli
  zniszczyłoby jego wartość jako sygnału.
- **Nie aktywowałem kontraktu Michała Leśniaka** (#315). Czy naprawdę został
  szkicem, da się ustalić tylko w prodowej bazie; zmiana danych produkcyjnych
  na podstawie domysłu jest gorsza niż zostawienie tego Tobie.
- **Nie przyjąłem kodu, który agenci napisali w moim drzewie roboczym** bez
  przeglądu (#403). Sam fakt, że kod powstał, nie jest argumentem, że jest
  dobry — sześć rzeczy w nim poprawiłem, w tym strażnika ślepego na dominujący
  idiom repo i docstring, który po zmianie stał się nieprawdziwy.
