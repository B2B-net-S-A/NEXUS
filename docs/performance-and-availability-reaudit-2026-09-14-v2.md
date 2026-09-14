# NEXUS — ponowny audyt po PR #1507 i #1509

**14.09.2026, druga kontrola tego dnia.** Cel pozostaje ten sam: zwykła praca 50, następnie 100 jednoczesnych użytkowników bez awarii i nadmiernych opóźnień. Punktem odniesienia jest [poprzedni reaudyt](performance-and-availability-reaudit-2026-09-14.md), a nie pierwotna wersja aplikacji sprzed poprawek.

**Najważniejszy wynik: w trakcie tego audytu produkcja ponownie zwróciła dokładnie `503 no available server`, podczas wdrożenia #1509.** Sam deploy zakończył się sukcesem, a aplikacja wróciła do działania. Poprawki kodu są w większości skuteczne, lecz ciągłość wdrożeń nadal nie spełnia wymagania użytkownika. Gotowość wydajnościowa na 50/100 osób pozostaje nieudowodniona.

Poprzednio wykryte błędy KPI wieloról, odświeżenia powiadomień i nawigacji Insights zostały poprawione w sprawdzonych scenariuszach. Nie należy zgłaszać ich ponownie jako niezmienionych. Nowe ustalenia dotyczą głównie sprzątania cache przy anulowaniu, granic bezpiecznego zwalniania sesji oraz niedziałającego stagingu wskazanego w konfiguracji.

## 1. Bezpośredni dowód przerwy na produkcji

W czasie już trwającego wdrożenia odpytywałem wyłącznie dwie lekkie trasy: frontend `/login` oraz API `/api/health/live`. Zebrano po **42 próbki**, łącznie 84 GET-y. Odstęp między parami wynosił około 5 s, z jedną dłuższą przerwą między seriami. Nie uruchamiałem wdrożenia, nie restartowałem usług i nie wykonywałem testu obciążeniowego.

| Etap, 14.09.2026 | Frontend `/login` | API `/api/health/live` |
|---|---|---|
| Ostatnia dobra próbka przed błędami | 11:16:53 UTC | 11:17:20 UTC, SHA `934aef8f` |
| Pierwszy zarejestrowany błąd | **11:16:59 UTC — 503, `no available server`** | **11:17:25 UTC — 502, `Bad Gateway`** |
| Dalszy przebieg | Kolejne 503 z tym samym komunikatem | 3 próbki 502, następnie 8 próbek 503 `no available server` |
| Ostatni zarejestrowany błąd | 11:18:43 UTC | 11:18:18 UTC |
| Pierwsza dobra próbka po błędach | 11:18:49 UTC — 200 | 11:18:44 UTC — 200, SHA `a30d915c` |
| Suma odpowiedzi w badanym oknie | 25 × 200, **17 × 503** | 31 × 200, **3 × 502 + 8 × 503** |

Czas lokalny w Warszawie to UTC + 2: frontend przestał odpowiadać między próbkami około **13:16:54–13:16:59**, a odzyskał dostępność około **13:18:44–13:18:49**.

Między pierwszą a ostatnią błędną próbką frontendu minęło **104,9 s**, API **52,1 s**. Przedziały pomiędzy sąsiednimi dobrymi próbkami obejmują odpowiednio 115,3 s i 83,4 s. To zakres obserwacji sond, nie pomiar ciągły co milisekundę; nie wyklucza krótkich zmian stanu między próbkami. Nie wyliczam z tego miesięcznego uptime ani normalnego odsetka błędów aplikacji.

[Deploy #1509](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34837102543) rozpoczął się o 11:13:20 UTC. Jego log kończy się sukcesem, a deep health potwierdza nowy SHA o 11:18:48 UTC. **Zielony deploy i końcowy healthcheck nie wychwyciły jako porażki przerwy odczuwanej przez użytkowników.** [Surowe sondy](../outputs/performance-reaudit-2026-09-14-v2/probe-series.json), [wyliczenie przedziałów](../outputs/performance-reaudit-2026-09-14-v2/incident-summary.json).

Wniosek jest mocniejszy niż w poprzednim raporcie: obecny proces wdrażania nie utrzymuje ciągłości obsługi żądań. W tym incydencie awaria wystąpiła podczas przełączenia wersji; nie trzeba było generować 50/100 sesji. Nie dowodzi to, że każdy wcześniejszy komunikat miał tę samą przyczynę ani że problemy pod obciążeniem są wykluczone. Bez szczegółowych logów proxy/kontenerów nie rozstrzygam udziału restartu, healthchecków i czasu startu w każdej sekundzie tej przerwy.

**Priorytet P1: naprawić ciągłość wdrożeń przed kolejnym zwiększaniem grupy użytkowników.** Deploy poza godzinami pracy ogranicza ekspozycję, ale pozostaje obejściem organizacyjnym.

## 2. Zakres i stan wersji

| Element | Zweryfikowany stan |
|---|---|
| Baseline poprzedniego reaudytu | `2c00f7cb`, wówczas runtime `6504fef5` |
| Główne poprawki | [PR #1507](https://github.com/B2B-net-S-A/NEXUS/pull/1507), merge `0dbd0661` |
| Dodatkowa poprawka kotwic | [PR #1509](https://github.com/B2B-net-S-A/NEXUS/pull/1509), merge **`a30d915c`** |
| Audytowany kod | Izolowana kopia aktualnego `origin/main` na `a30d915c`; uwzględnia też pośrednie zmiany UAT #1506/#1508 |
| CI | [#1507](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34830206697) oraz [#1509](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34835470296): sukces; ich CI Gate także success |
| Produkcja po przerwie | `/api/health` i `/api/health/deep`: 200, healthy, pełny SHA `a30d915c…` o 11:20:21 UTC |
| Schemat | `/api/health/alembic`: DB i code heads `0307_client_deletion_event_history`, orphaned `[]`, reconcilable `true` |
| Przeglądarka | Zalogowany Chrome: Insights, kliknięcie „Źródła”, dashboard HoR; bez zapisu danych biznesowych |

Ostatnie `/api/health`, `/deep`, `/alembic` odpowiedziały w około 183 / 740 / 256 ms z komputera audytora. Są to pojedyncze pomiary dostępności, nie percentyle tras biznesowych. [Odpowiedzi health](../outputs/performance-reaudit-2026-09-14-v2/final-health.json).

## 3. Co poprawiono względem siedmiu ustaleń poprzedniego reaudytu

„Zamknięte w sprawdzonym scenariuszu” oznacza potwierdzenie konkretnej naprawy. Nie oznacza zaliczenia testu pojemności całej aplikacji.

| Poprzedni punkt | Ocena po nowych poprawkach | Dowód i granica |
|---|---|---|
| **R01 — KPI HoR pomija wielorole** | **Zamknięte w sprawdzonym scenariuszu** | `operational_roles_only=False` dla jawnego rosteru; brakujące ID oznaczają `partial`. Niezależny test tej samej funkcji zwrócił osobę TCM + recruiter i jej jeden placement; wcześniej wynik był pusty |
| **R02 — powiadomienia po reconnect** | **Zamknięte w sprawdzonym scenariuszu** | `onopen` po zerwaniu invaliduje notifications i KPI. Test z rzeczywistym hookiem/Query wykazał dodatkowy odczyt po reconnect, bez czekania 5 min |
| **R03 — kotwica Insights ucieka** | **Poprawione; potwierdzone w Chrome** | `pinAnchor` koryguje pozycję, limit liczy widoczny czas, respektuje ręczne sterowanie. Po kliknięciu „Źródła” nagłówek był widoczny: górna krawędź sekcji 350 px przy viewport 987 px, zamiast 3179 px poza ekranem |
| **R04 — pełny odczyt uploadu przed limitem** | **Zamknięte w trzech zmienionych handlerach; F10 częściowe** | `_read_upload_bounded` czyta limit + 1. Test: plik 3 MiB przy limicie 1 MiB → odczyt 1 048 577 bajtów i 413. Nadal brak limitu całego multipart przed handlerem i kolejki ciężkiej pracy |
| **R05 — DB podczas oczekiwania** | **Częściowo; dodatkowy błąd cancellation** | Kontendujący waiter zwalnia czystą sesję przed lockiem, preview przed rerankiem też. Test czystej sesji potwierdza zakończenie transakcji. Nowa ścieżka ma jednak błąd sprzątania opisany w §4 |
| **R06 — retry i fallback** | **Dwa lokalne retry, jitter WS i ukryty fallback poprawione** | Usunięte override’y, domyślnie 3 próby Axios, jitter reconnect 50–100%, hidden fallback nie wykonuje odczytu. Retry-After usunięto, a nie zaimplementowano — patrz niżej |
| **R07 — błędy Query niewidoczne w Sentry** | **Ścieżka w kodzie naprawiona; odbiór operacyjny otwarty** | QueryCache i MutationCache raportują syntetyczne network/timeout/5xx. Test realnego Query kończy się jednym captureException; filtr przepuszcza syntetyczny timeout i próbkowane chunki. Brak dowodu dostarczenia zdarzenia i alertu do operatora |

Źródła: [agregator KPI](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/backend/app/analytics/metrics.py#L301-L344), [adapter rosteru](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/backend/app/services/dashboard_v2_sources.py#L400-L419), [WS](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/frontend/src/hooks/useNotifications.ts#L125-L145), [kotwice](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/frontend/src/lib/anchor-pin.ts#L35-L90), [upload](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/backend/app/api/candidates.py#L5653-L5678), [QueryProvider](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/frontend/src/components/QueryProvider.tsx#L1-L41).

Dodatkowo usunięto wskazane wcześniej **N+1 przy serializacji demandów Delivery Leada**: dashboard używa `_serialize_demands`, pobierającego źródła hurtowo i plan co najwyżej raz. Nie należy nadal przypisywać tej ścieżce pięciu zapytań na każdy demand. Koszt pobrania dużej liczby rekordów, budowy payloadu i samego planu nadal wymaga pomiaru. [Serializacja hurtowa](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/backend/app/api/priority_work.py#L304-L384).

**Retry-After:** obecny CORS wystawia `ETag` i `Content-Disposition`, dlatego nagłówek Retry-After odpowiedzi API nie jest dostępny dla tego kodu przeglądarki. Usunięcie nieprawidłowego parsera porządkuje aktualny kontrakt. Nie jest pełną obsługą zaleceń serwera o czasie ponowienia: syntetyczny test z widocznym nagłówkiem +60 s nadal daje próby 0 / 1,5 / 4,5 s. Przy zmianie proxy/CORS należy wdrożyć wspólną politykę nagłówka i backoffu. Nie podnoszę tego do rangi nowego incydentu produkcyjnego. [Interceptor](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/frontend/src/lib/api.ts#L239-L295).

## 4. Nowe luki w poprawkach

### N01 · P2 · Anulowanie podczas zwalniania DB pozostawia wpis blokady cache

W `cache_single_flight` licznik referencji jest zwiększany, następnie wykonywane jest `await release_idle_connection(db)`, a dopiero dalej zaczyna się `try/finally` sprzątający licznik. Jeżeli task zostanie anulowany w tym nowym `await`, `CancelledError` nie zostaje przechwycony przez `except Exception`, a cleanup nie następuje. [Kod](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/backend/app/core/cache.py#L89-L110).

**Reprodukcja offline na oryginalnej funkcji:** producent trzyma klucz, waiter zatrzymany we własnym `commit()` zostaje anulowany, producent kończy. Pozostaje jeden lock i `refs={'audit-cancel':1}`. Następne udane przejście przez ten klucz nie usuwa wpisu. Każdy kolejny odmienny klucz z takim zdarzeniem może pozostawić następny wpis do końca życia procesu.

Nie stwierdzono deadlocka, zajętego na zawsze połączenia ani produkcyjnego OOM. Potwierdzono wyciek rejestru locków/refcountów w nowej ścieżce cancellation; wcześniejsze testy cancellation bez `db=` go nie obejmują.

**Naprawa:** objąć zewnętrznym `try/finally` cały fragment po zwiększeniu refcount, łącznie z oddawaniem sesji. Nadal propagować anulowanie. **Odbiór:** anulowanie przed/w trakcie/po commit oraz podczas oczekiwania na lock; po zakończeniu wszystkich tasków oba rejestry puste, kolejny producent działa. [Wynik reprodukcji](../outputs/performance-reaudit-2026-09-14-v2/backend-repro-results.json).

### N02 · P2, zabezpieczenie kontraktu helpera · „Czyste ORM” nie znaczy „transakcja tylko do odczytu”

`release_idle_connection` uznaje puste `db.new`, `db.dirty`, `db.deleted` za przesłankę do `commit()`. Po `flush()` zmiany mogą już być wykonane w bazie w ramach nadal niezatwierdzonej transakcji, a te kolekcje są puste. Podobnie zapis wykonany bezpośrednim SQL nie musi być widoczny w tych kolekcjach. [Helper](https://github.com/B2B-net-S-A/NEXUS/blob/a30d915c5e52c2adfb7e18af24de643f7bf3347f/backend/app/core/database.py#L51-L73); rozdział flush i commit opisuje [SQLAlchemy — Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).

**Reprodukcja z rzeczywistą AsyncSession, SQLite w pamięci:** INSERT → flush → wszystkie trzy kolekcje puste → helper zwraca true i commit → późniejsze rollback callera nie usuwa wiersza. W bazie pozostaje jeden syntetyczny rekord.

**Granica ustalenia:** nie wykazano, że aktualni callerzy cache/preview doprowadzają do niezamierzonego zatwierdzenia danych produkcyjnych. Obecne użycia dotyczą głównie ścieżek odczytu; jest to błąd ogólnej gwarancji helpera i ryzyko jego dalszego używania, nie potwierdzona utrata atomowości konkretnej operacji użytkownika.

**Naprawa:** jawny kontrakt „oddaj sesję po zakończonej fazie tylko do odczytu”, kontrolowany przez callera; najlepiej osobna krótka sesja odczytowa i dane odłączone od ORM. Nie traktować trzech kolekcji jako kompletnej ochrony transakcji. Dodać testy pending, flushed oraz SQL DML, zanim helper zostanie rozszerzony na kolejne miejsca.

## 5. Status pierwotnych wymagań F01–F12

| ID | Stan po obu rundach poprawek |
|---|---|
| **F01 — monitoring** | Kod przechwytywania błędów istotnie poprawiony. Brak potwierdzenia ciągłych sond, dostarczania zdarzeń i alarmu; odczyt listy sekretów repo zwrócił 403 |
| **F02 — wspólny proces API/tła** | Nadal pojedynczy Uvicorn i ten sam rejestr 48 zadań tła, uruchamianych zależnie od flag; brak izolacji ciężkiej pracy |
| **F03 — deploy bez przerwy** | **Niespełnione w bezpośredniej obserwacji produkcji**. 503 frontendu i 502/503 API podczas udanego deployu |
| **F04 — startup** | Guard UPDATE zachowany i przetestowany; brak zmiany pozostałego startupu, pomiaru faz i wyniesienia napraw danych przed rollout |
| **F05 — XLSX** | Kodowanie poza event loop zachowane; cała lista wierszy i wynik nadal w pamięci, bez ograniczonej kolejki dużych eksportów |
| **F06 — DB** | Zwalnianie czystych sesji przed wybranymi oczekiwaniami poprawia sytuację. Nadal brak pomiaru checkout wait, budżetów i jawnych timeoutów; główna pula 20+40 na proces |
| **F07 — N+1/cache** | HoR i wskazana serializacja DL poprawione; single-flight działa, ale wymaga N01. Cache i stan realtime nadal lokalne procesu |
| **F08 — ruch przeglądarki** | Polling nadal około 1,8–2,0 GET/min dla modelu pełnego idle dashboardu; globalne/lokalne retry oraz reconnect poprawione. To model, nie HAR całego systemu |
| **F09 — Insights** | Odroczony mount i sprawdzona kotwica poprawione. Brak nowych pomiarów początkowego pakietu requestów, JS, LCP/INP |
| **F10 — importy** | Unikalne tempy i ograniczony odczyt poprawione. Limit przyjęcia multipart, globalna współbieżność, trwałe joby i wpływ importów na CRUD nadal otwarte |
| **F11 — readiness/recovery** | Brak nowego mechanizmu ciągłego routingu, drenażu i odzyskania zawieszonej instancji; końcowy `/live` nie jest dowodem ciągłości |
| **F12 — kwalifikacja 50/100** | Brak wyników takich testów. Skonfigurowany staging został odnaleziony, ale jest zatrzymany/niezdrowy i wskazuje inną wersję — szczegóły niżej |

Nie zmieniono `docker-compose.yml`, Dockerfile FE/BE, `backend/entrypoint.sh` ani workflow wdrażania między poprzednim snapshotem a analizowanym SHA. Zmiany `main.py` dotyczą m.in. dokładniejszej diagnostyki M365, nie przebudowy procesu API i rolloutów.

### Staging istnieje w konfiguracji, lecz nie jest gotowy do testów

Odczyt metadata przez repozytoryjny [workflow `staging-status`](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34837698245), 11:20:27 UTC, zwrócił:

- status **`exited:unhealthy`**;
- gałąź `codex/nexus-dependency-upgrades`;
- SHA `6af30237`, inny niż audytowana produkcja;
- build pack `dockercompose`, pole `fqdn=null`.

To potwierdzenie stanu aplikacji wskazanej przez konfigurację stagingu, nie inwentaryzacja wszystkich środowisk. `fqdn=null` w Compose samo nie dowodzi braku domen poszczególnych usług. **Sukces workflow oznacza udany odczyt metadanych, nie zdrowy staging.** Najpierw trzeba go uruchomić na aktualnym kodzie i zweryfikować reprezentatywność danych oraz izolację od produkcji.

### Monitoring i backup

Najświeższa odnaleziona próbka Uptime pochodzi nadal z 05:51 UTC, a monitor Sentry z 13.09 12:19 UTC. Żaden nie stanowi ciągłej obserwacji dzisiejszego przełączenia. Nowy raport wykonania Claude wprost wymienia operacyjne kroki monitoringu jako niewykonane; niezależny odczyt listy sekretów repo był niedostępny (403), więc nie potwierdzam ich bieżących wartości ani obecności.

Ostatni [Backup Restore Drill](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34805878641) nadal ma status failure z 14.09 04:23. W porannym audycie log wskazywał niekompletną konfigurację dostępu/odszyfrowania przed restore. Nie ma nowego udanego odtworzenia. Nie jest to dowód uszkodzonej kopii.

## 6. Co poprawić teraz — kolejność i kryteria odbioru

### 1. Ciągłość wdrożeń i alarmy — najwyższy priorytet

Obecne Compose nie zapewnia aplikacyjnego rolling update w Coolify. Przenieść FE/API do osobno wdrażanych aplikacji z gotowymi, przypiętymi obrazami; baza, wektory i storage powinny mieć niezależny cykl życia. Nowa instancja musi przejść readiness, zanim stara zostanie wycofana. Obsłużyć drenaż żądań, WS, stare assety, zgodność schematu oraz schedulery podczas nakładania wersji. [Dokumentacja Coolify](https://coolify.io/docs/applications/deployments/rolling-updates) podkreśla, że samo nakładanie kontenerów nie gwarantuje braku przerwy.

**Odbiór:** ciągłe odczyty i bezpieczne zapisy podczas deployu/rollbacku na stagingu, zero nieoczekiwanych 5xx/timeoutów, zero utraconych lub podwójnych zadań; stara otwarta karta nadal działa. Workflow powinien sprawdzać także przejście, nie tylko stan końcowy. Natychmiast potrzebne niezależne sondy FE/API co 30–60 s z alarmem ≤2 min i korelacją z release. Przejściowo ograniczyć wdrożenia w godzinach pracy, zgodnie z nową regułą repo; nie nazywać tego rozwiązaniem wysokiej dostępności.

### 2. Mała naprawa N01 oraz ograniczenie kontraktu N02

Naprawić cleanup przy cancellation i objąć go testem nowej ścieżki `db=`. Doprecyzować i zabezpieczyć użycie `release_idle_connection` bez zmiany atomowości operacji. Zachować poprawione bounded upload, ws reconnect, batch DL i telemetrię.

### 3. Pomiary i ograniczenie ciężkiej pracy

Mierzyć per trasa: p95/p99, 5xx/timeouts, liczbę żądań w toku; ponadto event-loop lag, checkout wait/transaction age, CPU/RAM/IO, kolejki i czasy jobów. Ograniczyć równoczesne importy/eksporty/AI; ciężkie zadania wydzielić do workera z trwałą kolejką i idempotencją. Zaprojektować komunikację powiadomień między procesami przed podziałem.

Nie dodawać bezrefleksyjnie workerów Uvicorna: pomnożą lokalne schedulery i potencjalne pule. Dwa procesy z obecnym 20+40 już dają potencjalny limit 120 głównych połączeń, przed meteringiem i pozostałymi klientami, wobec zadeklarowanego PostgreSQL `max_connections=100`. To limit możliwy, nie zmierzona liczba aktywnych połączeń. Najpierw budżet i pomiar, potem dobór rozmiarów.

### 4. Przywrócić staging i przeprowadzić rzeczywistą kwalifikację

Nie ma potrzeby kolejnej szerokiej rundy drobnych optymalizacji bez pomiarów. Istniejący staging wymaga naprawy, aktualnego SHA i danych o reprezentatywnej wielkości. Generator musi działać poza serwerem aplikacji; różne konta/role/rekordy/cache keys, nie 100 wywołań jednego ciepłego endpointu.

| Scenariusz | Minimalny przebieg |
|---|---|
| Baseline | 1 → 10 → 25 aktywnych sesji, cold/warm cache |
| 50 użytkowników | ≥30 min, listy/profile/rekrutacje/kontrakty/dashboard oraz zwykłe zapisy |
| 100 użytkowników | ≥60 min; podobny profil, duże portfele i dodatkowe karty |
| Ciężka praca w tle | 2 duże XLSX, 5–10 importerów, kolejka CV/AI, reprezentatywna synchronizacja; sprawdzić normalny CRUD |
| Bursty i zależności | Start dnia, 100 reconnectów WS, cold cache, powrót kart do focusu, wolny AI |
| Ciągłość | Deploy, rollback i utrata jednej instancji przy trwającym ruchu i zapisach |
| Długotrwały ruch | ≥4 h przy 100, krótki pik 150, dodatkowo model stałego napływu i kontrola pominiętych iteracji |

Proponowane bramki pozostają: **zero nieoczekiwanych 5xx/timeoutów w nominalnych scenariuszach i planowym deployu; zero utraty/duplikacji zapisów; API p95 ≤500 ms i p99 ≤1500 ms; dashboard p95 ≤1,5 s; interaktywne wyszukiwanie bez generacji AI p95 ≤2 s; brak OOM, narastających kolejek i wyczerpania DB**. Mierzyć każdą istotną trasę i pełne działanie użytkownika osobno, nie mieszać healthchecków z biznesowym p95. LCP p75 ≤2,5 s, INP p75 ≤200 ms na uzgodnionym urządzeniu/sieci; checkout wait p95 <50 ms i loop lag p99 <100 ms jako cele diagnostyczne.

Czas przyjęcia joba, kolejki i wykonania AI raportować oddzielnie. Próg przerwania testu: utrata integralności, OOM/pętla restartów lub >1% nieoczekiwanych błędów przez 60 s. To bezpiecznik, nie dopuszczalny wynik nominalny. Po zaliczeniu etapowy pilot → 25 → 50 → 100 z obserwacją pełnego dnia pracy po zwiększeniu skali.

## 7. Weryfikacja i ograniczenia

- **44 istniejące testy frontendu PASS:** QueryProvider 5, transient retry 10, hook notifications 3, anchor-pin 7, query telemetry 4, kontrakt nawigacji Insights 15.
- **7 niezależnych testów zachowania frontendu PASS:** rzeczywiste Query/Axios/hooki i filtr Sentry, syntetyczne HTTP/WS, bez sieci. Obejmują poprawione reconnect, hidden fallback i capture błędu; test Retry-After dokumentuje jego świadomy brak, a nie zamknięcie obsługi nagłówka.
- **6 istniejących testów backendu PASS:** cache/single-flight/jitter oraz guard UPDATE, host-native, `--noconftest`, bez PostgreSQL i Dockera.
- **Reprodukcje backendu offline:** poprawny bounded read i zwolnienie czystej sesji; potwierdzony wyciek refcount przy cancellation; rzeczywista AsyncSession/SQLite pokazuje commit po flush. Osobny test oryginalnego `team_kpis` z rzeczywistym pierwszym SQL na SQLite i syntetycznymi agregatami potwierdza powrót użytkownika wieloról z prawidłowym fixture’em placementu.
- **Produkcja:** 84 lekkie GET-y podczas naturalnie trwającego wdrożenia, trzy końcowe endpointy health, zalogowany Chrome, odczyt CI/deploy/staging. Bez zmian danych i konfiguracji oraz bez testów obciążeniowych produkcji.
- **Nie wykonano:** testu 50/100, benchmarku SQL/PostgreSQL, pomiaru checkout wait/CPU/RSS, HAR/Web Vitals, kontrolowanego failover ani pełnego odtworzenia backupu. Testy jednostkowe i zielony CI nie zastępują tych dowodów.

[Indeks dowodów tej rundy](../outputs/performance-reaudit-2026-09-14-v2/EVIDENCE.md). Poprzednie raporty zachowano bez nadpisywania. Ten raport potwierdza postęp poprawek, ale **nie dopuszcza deklaracji „stabilne 50/100 osób” przed naprawą ciągłości i testami pojemności**.
