# NEXUS — ponowny audyt wydajności i dostępności po poprawkach Claude

**Data:** 14.09.2026. **Cel:** stabilna zwykła praca 50, następnie 100 aktywnych użytkowników oraz wyjaśnienie ryzyka błędów „no available server”. Użytkownik zgłaszał je podczas zwykłej pracy, bez jednej konkretnej akcji.

**Werdykt: poprawki są rzeczywiste i wartościowe, ale nadal nie ma podstaw do deklaracji „gotowe na 50/100 osób bez spowolnień i przerw”.** PR #1502 ogranicza kilka kosztów aplikacji. Nie usuwa głównych ryzyk ciągłości wdrożeń i współdzielenia procesu API z ciężką pracą. Brakuje testów pojemności. Reaudyt wykrył ponadto trzy regresje: niepełne KPI części użytkowników wieloról, opóźnienie powiadomień po krótkiej przerwie WebSocket oraz błędne położenie kotwicy Insights po doczytaniu sekcji.

To **brak kwalifikacji skali**, a nie dowód, że aplikacja musi się zepsuć przy 50 osobach. Podczas bieżącej kontroli frontend i API działały. W tym zadaniu wykonano audyt i zapisano dowody; nie zmieniano kodu aplikacji, konfiguracji produkcji ani danych biznesowych.

## 1. Co faktycznie sprawdzono

| Element | Stan zweryfikowany w reaudycie |
|---|---|
| Poprzedni audyt | [Raport z 13.09.2026](performance-and-availability-audit-2026-09-13.md), baseline `ab10c8bb` |
| Poprawki Claude | [PR #1502](https://github.com/B2B-net-S-A/NEXUS/pull/1502), merge `6504fef5` |
| Świeży kod analizowany | `origin/main`: `2c00f7cb`, w izolowanej kopii; nie stary, roboczy checkout użytkownika |
| Różnica względem wdrożenia | Między `6504fef5` i `2c00f7cb` zmieniono wyłącznie 3 dokumenty UAT. Kod wykonawczy jest identyczny |
| Produkcyjne API | `/api/health` i `/api/health/deep`: `healthy`, SHA **`6504fef5`** |
| Schemat | `/api/health/alembic`: DB i kod `0307_client_deletion_event_history`, brak orphaned revisions, `reconcilable=true` |
| CI poprawek | [CI PR #1502](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34780789123) i [CI Gate](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34780789039) zakończone sukcesem |
| Wdrożenie poprawek | [Deploy `6504fef5`](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34781753173): sukces; log potwierdza SHA i frontend HTTP 200 |
| Przeglądarka produkcyjna | Zalogowany Chrome: dashboard Admin Ops i Insights wyświetliły dane; sprawdzono również kliknięcie dolnej kotwicy Insights |
| Testy bieżącego audytu | 6 istniejących testów backendu, 30 istniejących testów frontendu, 8 niezależnych testów zachowania frontendu oraz reprodukcje backendu; szczegóły w §7 |

### Bieżące pomiary dostępności

Pojedyncze lekkie GET-y z komputera audytora, **14.09, 08:22:58–08:22:59 UTC / 10:22:58–10:22:59 CEST**:

| Trasa | Wynik | Czas całego żądania |
|---|---|---:|
| Frontend `/`, z przekierowaniem do `/login` | 200 | 192 ms |
| Frontend `/login` | 200 | 150 ms |
| API `/api/health/live` | 200, alive | 134 ms |
| API `/api/health` | 200, healthy | 179 ms |
| API `/api/health/deep` | 200, healthy | 508 ms |
| API `/api/health/alembic` | 200, zgodny schemat | 324 ms |

To potwierdzenie dostępności w chwili kontroli. **Nie są to percentyle, benchmark tras biznesowych ani test równoległej pracy.** Nie porównuję tych pojedynczych czasów z poprzednim audytem jako dowodu przyspieszenia.

## 2. Status wszystkich ustaleń poprzedniego audytu

„Częściowo” oznacza, że wskazany fragment naprawiono, lecz pełne wymaganie lub jego odbiór pozostają otwarte. Identyfikatory F01–F12 zachowano, aby można było porównać raporty.

| ID | Stan po PR #1502 | Potwierdzona poprawa | Pozostały problem |
|---|---|---|---|
| **F01 — obserwowalność** | **Częściowo** | `ERR_NETWORK` dopuszczany do Sentry z próbkowaniem 10% | Obsłużone błędy query nie mają zapewnionej ścieżki raportowania; timeouty/chunki nadal odrzucane; odbiór monitorów i alertów niepotwierdzony |
| **F02 — API i ciężkie tło** | **Otwarte** | Brak zmiany podziału procesów | Jeden proces Uvicorn, 48 rejestracji zadań tła; aktywność zależy od flag. Wspólna pamięć, CPU, DB i cykl życia |
| **F03 — przerwy przy deployu** | **Otwarte** | Brak zmiany mechanizmu rollout | Pojedyncze FE/API w tym samym Compose; brak dowodu podmiany z nakładaniem instancji i bez przerwy |
| **F04 — koszt startu** | **Częściowo** | UPDATE dokumentów ma guard i nie zapisuje ponownie wartości już równej `cv` | Pozostałe migracje, naprawy danych i seed nadal przed HTTP; brak globalnego deadline i pomiaru faz |
| **F05 — eksport XLSX** | **Częściowo** | Kodowanie poza event loop przez `asyncio.to_thread`; GET używa wspólnej, oszczędniejszej ścieżki, CSV strumieniuje | Wszystkie wiersze XLSX i wynik nadal w RAM; brak ograniczonej kolejki eksportów i izolacji procesu |
| **F06 — połączenia DB** | **Otwarte** | Brak zmiany pul i cyklu sesji | Nadal 20+40 na proces; sesje podczas wolnego AI i oczekiwania na cache mogą zajmować połączenia |
| **F07 — N+1 i cache** | **Częściowo + regresja** | HoR: 4 zapytania zamiast 3×N; single-flight i jitter dla wybranych cache | Agregacja HoR pomija część wieloról; N+1 Delivery Lead pozostaje; cache i blokady są lokalne procesu |
| **F08 — polling i retry** | **Częściowo + regresja** | Domyślne retry Query wyłączone; HTTP ma jitter; znacznie rzadszy polling | Dwa lokalne retry nadal mnożą próby; niepełny Retry-After; brak reconcile WS; fallback ukrytych kart |
| **F09 — Insights** | **Częściowo + regresja UI** | 13 grup sekcji montowanych dopiero przy zbliżeniu do viewportu | Produkcyjny skok do dolnej kotwicy kończy się w złym miejscu; brak pomiaru pakietu żądań i czasu UI |
| **F10 — import CV** | **Częściowo** | Unikalne tempy, bezpieczna nazwa, cleanup, limit przed ekstrakcją/zapisem | Limit nadal po pełnym `read()`; brak globalnego ograniczenia ciężkich importów i trwałej kolejki |
| **F11 — readiness i recovery** | **Otwarte** | Zachowane lekkie API `/live` | Brak nowego rozdzielenia gotowości/routingu, testu drenażu i odzyskania zawieszonego procesu |
| **F12 — pomiary i skala** | **Otwarte; opis hosta skorygowany** | Dokumentacja ujednolicona do CCX33, 8 vCPU/32 GB | Brak nowych profili SQL/CPU/RAM, HAR/Web Vitals oraz testów 50/100/soak/deploy |

Nie należy ponownie zgłaszać kolizji tempów, braku guardu UPDATE, bezpośredniego kodowania XLSX na event loop czy globalnego `QueryProvider.retry=1` jako niezmienionych błędów. Te konkretne mechanizmy poprawiono.

## 3. Luki i regresje wykryte podczas ponownej weryfikacji

### R01 · P2 · KPI HoR tracą część poprawnych członków zespołu

Nowy zbiorowy `load_team_kpis` wywołuje `metrics.team_kpis`. Roster uwzględnia role dodatkowe przez `has_any_role`, ale agregator ponownie filtruje wyłącznie główne `User.role`. Przykład: główna rola `talent_community_manager` i dodatkowa `recruiter` kwalifikują osobę do rosteru; agregator jej nie zwraca. Wynik może zaniżyć liczbę placementów, pozostając oznaczony jako kompletny. Dawna ścieżka po pojedynczych ID nie miała tego dodatkowego filtra. [Roster](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/api/priority_work.py#L549-L562), [nowy caller i agregacja](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/services/dashboard_v2.py#L797-L849), [filtr primary-role](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/analytics/metrics.py#L315-L401).

**Reprodukcja:** oryginalna funkcja z bieżącego kodu, rzeczywiste pierwsze SQL wykonane na syntetycznej tabeli SQLite w pamięci, pozostałe agregaty jako kontrolowane fixture’y. `roster_eligible=true`, żądany ID `[700001]`, wynik `[]` mimo syntetycznego jednego hire. To dowód rozbieżności logiki, nie stwierdzenie występowania takiej osoby w aktualnych danych produkcyjnych.

**Naprawa i odbiór:** zachować wszystkie jawnie autoryzowane ID rosteru, bez ponownej selekcji przez primary-role. Test parytetu starego/nowego wyniku dla ról dodatkowych recruiter/TAC/sourcer, zerowej aktywności i pustego rosteru; osobny test wykluczenia osoby spoza scope. Kontrola kompletności ma wykrywać brak ID, a nie tylko poprawny kształt zwróconych wierszy.

### R02 · P2 · Powiadomienia po krótkiej utracie WebSocket mogą być opóźnione do 5 minut

Wydłużono safety polling z 30 do 300 s. Jeżeli sam WS zerwie się na mniej niż 60 s, nowy fallback może nie wykonać żadnego odczytu. Po reconnect zostaje skasowany, lecz `onopen` nie odświeża powiadomień. Backend wysyła `connected`, bez replay pominiętych zdarzeń. Wiadomość zapisana podczas przerwy może być niewidoczna do kolejnego safety poll lub innej invalidacji; nie oznacza to utraty rekordu w DB. [Hook WS](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/hooks/useNotifications.ts#L113-L143), [interwał dzwonka](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/NotificationsDropdown.tsx#L226-L235), [backend connect](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/api/ws.py#L530-L539).

**Reprodukcja:** rzeczywisty hook + Query, syntetyczny WebSocket i zegar; po krótkim disconnect/reconnect liczba GET-ów pozostaje 1 przez kolejne 61 s.

**Naprawa i odbiór:** jeden kontrolowany odczyt po odzyskaniu WS, z deduplikacją; opcjonalnie odczyt po otwarciu nieświeżego dzwonka. Sprawdzić pominięte zdarzenie oraz równoczesny reconnect 100 sesji. Utrzymać korzyść rzadszego pollingu.

### R03 · P2 · Kotwica Insights nie utrzymuje celu po leniwym doczytaniu

**Zaobserwowane na produkcji:** po pierwszym wejściu do Insights i kliknięciu „Źródła” URL poprawnie zmienił się na `#zrodla`. Po doczytaniu widok pokazywał jednak Placementy / Power Calling. Górna krawędź `#zrodla` znajdowała się **3179 px poniżej górnej krawędzi viewportu**, czyli poza ekranem. Dashboard i podsumowanie Insights wcześniej poprawnie wyświetliły dane; konsola badanej karty nie zwróciła wpisów error/warn.

Mechanizm: zwykły link hash ustawia pozycję, a kolejne placeholdery 240 px zostają zastąpione wyższą treścią. Nie ma ponownego dopasowania pozycji do celu. Samo umieszczenie ID poza wrapperem nie zabezpiecza przed zmianą układu. To obserwacja błędu nawigacji, **nie ilościowy pomiar CLS**. [Linki i wrapper sekcji](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/insights/InsightsSectionNav.tsx#L49-L80), [lazy mount](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/v2/DeferUntilVisible.tsx#L23-L50), [sekcje](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/insights/RekrutacjaPanel.tsx#L199-L234).

**Naprawa i odbiór:** skoordynować montowanie z przewinięciem i stabilizacją układu, bez odbierania użytkownikowi ręcznego scrolla. Test w prawdziwej przeglądarce: zimne wejście, kliknięcie odległej kotwicy, bezpośredni hash, back/forward; końcowy nagłówek ma być widoczny. Zachować odroczone ładowanie.

### R04 · P1 · Limit importu nadal nie chroni przed pełnym odczytem do RAM

`from-cv` wykonuje `await file.read()` bez limitu, następnie `_validate_upload_size(content)`. Nowe 413 ogranicza ekstrakcję i zapis, lecz duży obiekt bytes został już utworzony. [Odczyt i walidacja](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/api/candidates.py#L5357-L5394).

**Reprodukcja:** syntetyczny plik 1 MiB + 1 przy limicie 1 MiB; 413 i brak ekstrakcji, ale `read_sizes=[-1]`, wszystkie 1 048 577 bajtów odczytane przed walidacją. Osobno 20 równoczesnych plików `CV.pdf` miało 20 różnych tempów, poprawną treść i pełny cleanup — kolizję skutecznie naprawiono.

**Naprawa i odbiór:** ograniczony odczyt do limitu + 1 lub streaming z licznikiem, limit multipart/body także przed handlerem oraz ograniczenie liczby wykonywanych/oczekujących importów. Test oversized odrzucany bez pełnej alokacji; równoległe importy nie mogą wywoływać OOM ani opóźniać CRUD. To pozostała luka F10, nie nowa kolizja plików.

### R05 · P1 · Single-flight nie gwarantuje uwolnienia połączeń DB przez oczekujących

Blokada cache prawidłowo ogranicza liczbę producentów tego samego klucza. Jednak auth i odczyt scope wcześniej używają requestowej sesji, zamykanej dopiero po handlerze. Oczekiwanie na zimny cache może zatem odbywać się z zajętym połączeniem. Podobny problem pozostaje w preview CV: odczyt DB, następnie zewnętrzny rerank z timeoutem 30 s w tym samym cyklu sesji. [Auth](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/api/deps.py#L149-L173), [scope przed lockiem](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/services/dashboard_v2.py#L1678-L1692), [sesja](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/core/database.py#L29-L61), [preview](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/api/cv_match_preview.py#L318-L333).

Potwierdzono kolejność kodu, **nie zmierzono wyczerpania puli na produkcji**. Testy nie wykazały deadlocka ani błędu cancellation w nowym locku. To ryzyko cyklu sesji F06/F07, również przy jednym procesie.

**Naprawa i odbiór:** rozdzielić krótki odczyt auth/scope/danych od czekania na cache lub AI, zachowując autoryzację i atomowość zapisów. Zmierzyć checkout wait, checked-out i transaction age podczas zimnego cache oraz wolnego AI równolegle ze zwykłą pracą. Nie wstawiać przypadkowych commitów w operacje biznesowe.

### R06 · P2 · Retry i fallback nadal mają wyjątki

- **Dwa lokalne `retry:1`:** [SuggestedCandidatesWidget](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/SuggestedCandidatesWidget.tsx#L169-L190) i [HistoricalCandidatesSection](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/HistoricalCandidatesSection.tsx#L351-L362). Nadal możliwe `(1+1) × (1+2) = 6` prób przy trwałym 503. Niezależny test realnego QueryProvider + Axios potwierdził domyślnie 3, z override 6 prób.
- **Retry-After:** [interceptor](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/lib/api.ts#L252-L259) obsługuje sekundy, obcinając je do 10 s, lecz ignoruje datę HTTP. Obie postacie są prawidłowe według [RFC 9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3). Test dla daty +60 s dał próby w 0 / 1,5 / 4,5 s przy wyzerowanym jitterze. Jeśli termin przekracza budżet UI, zakończyć lub odroczyć retry zamiast ponawiać przed wskazanym czasem. Sprawdzić widoczność nagłówka przez CORS.
- **Ukryte karty:** ręczny `setInterval → invalidateQueries` działa także bez focusu; `refetchIntervalInBackground=false` nie wyłącza takiej invalidacji. Test wykazał kolejny GET po 60 s w ukrytej karcie. Reconnect WS nadal ma deterministyczne 1/2/4/8/16/30 s. [Fallback](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/hooks/useNotifications.ts#L71-L76), [reconnect](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/hooks/useNotifications.ts#L266-L277).

**Odbiór:** jeden właściciel retry, oba formaty Retry-After, jeden kontrolowany fallback respektujący widoczność, jitter WS i test 100 jednoczesnych reconnectów. Nie zakładać stałego podwojenia fallbacku: timery i deduplikacja wpływają na rzeczywistą liczbę żądań.

### R07 · P1 · Zmiana filtra Sentry nie zapewnia jeszcze raportowania typowych awarii

`beforeSend` przepuszcza 10% `ERR_NETWORK`, ale filtr działa dopiero dla zdarzenia dostarczonego do SDK. Zwykłe obsłużone błędy `useQuery` nie muszą trafiać do granicy błędów strony; QueryProvider nie ma globalnego callbacku raportowania. Test realnego Query + Axios zakończył query w stanie error, bez `captureException` i bez `unhandledrejection`. To nie wyklucza breadcrumbs/spanów SDK; dowodzi braku gwarantowanej ścieżki zgłoszenia takiego błędu przez aplikację. [QueryProvider](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/QueryProvider.tsx#L9-L18).

Ponadto timeouty `ECONNABORTED`/`TimeoutError` i błędy chunków pozostają odrzucane. To właśnie klasy ważne dla „wolno” oraz pracy starej karty po deployu. [Konfiguracja Sentry](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/sentry.client.config.ts#L45-L87).

**Naprawa i odbiór:** deduplikowana telemetria końcowych błędów Query/Axios, osobne liczniki timeout/chunk/5xx, minimalny kontekst trasy, czasu i release, bez treści CV/tokenów. Aktywny zewnętrzny monitor FE i API co 30–60 s oraz test dostarczenia alarmu do właściciela w ≤2 min. Odbiór kończy się widocznym zdarzeniem i alarmem, nie samym testem filtra.

## 4. Co dalej może powodować „no available server” lub spowolnienia

### Wdrożenia i recovery pozostają osobnym problemem

Nadal pojedyncze FE/API i `build:` w Compose. Według [dokumentacji Coolify](https://coolify.io/docs/applications/deployments/rolling-updates) aplikacje Docker Compose nie obsługują application-level rolling updates. Wydzielenie FE/API do osobno wdrażanych aplikacji z gotowymi obrazami może umożliwić bezpieczne przełączenie, ale wymaga readiness, drenażu, zgodności schematu i starej karty. Samo rozdzielenie konfiguracji nie dowodzi ciągłości.

**Nowy dowód operacyjny:** najnowszy [deploy `2c00f7cb`](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34788844018), 13.09 około 23:09 UTC, zakończył się błędem `git ls-remote … refs/heads/main`, exit 128. Udostępniony fragment logu nie wyjaśnia właściwej przyczyny SSH/Git. Nie przypisuję go do błędnego klucza ani wyścigu „No such container”. Stara wersja `6504fef5` nadal działa; **nieudane wdrożenie nie jest tutaj dowodem bieżącej niedostępności**. [Kontrola Coolify](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34822503590) zwróciła pustą kolejkę i `running:unknown`, bez metryk kontenerów.

Raport wykonania Claude przypisuje incydenty 06/08.09 wyścigowi „No such container”. Nie odtworzono tej przyczyny z logów incydentów w bieżącym reaudytcie. Wskazane tam `#1414`, jeżeli chodzi o PR NEXUS, dotyczy [matchingowych fraz czynnościowych](https://github.com/B2B-net-S-A/NEXUS/pull/1414), a nie awarii deployu. Potrzebny właściwy log/odnośnik; nie uznawać historycznej diagnozy za niezależnie potwierdzoną przez ten raport.

### Ciężkie operacje nadal współdzielą zasoby zwykłej pracy

48 rejestracji zadań tła i pojedynczy Uvicorn pozostają w [startupie aplikacji](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/main.py#L690-L753). Wydzielenie ciężkich jobów jest zasadne, lecz cztery moduły wysyłają powiadomienia przez lokalny ConnectionManager. Potrzebny kanał między procesami oraz trwałość/idempotencja zadań. Proste dodanie `--workers 4` może powielić schedulery i rozdzielić WebSockety/cache.

Główna pula nadal dopuszcza do **60 połączeń na proces**; dodatkowo metering 2+2. Przy dwóch procesach teoretyczne maksimum to 120+8, przed pozostałymi klientami, wobec zadeklarowanego PG `max_connections=100`. To limity potencjalne, nie liczba stale otwartych połączeń. Budżet należy ustalić dla wszystkich ról i replik, uwzględniając realne oczekiwanie na pulę. [Semantyka pul SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/pooling.html).

XLSX jest już poza event loop, lecz [`_candidate_xlsx`](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/app/api/candidates.py#L2278-L2310) zbiera wszystkie małe wiersze przed budową pliku; dochodzi wynik `BytesIO`. SQL nadal pobiera modele partiami. Potrzebna projekcja kolumn i kontrola współbieżności; większe eksporty do ograniczonego workera. Anulowanie oczekiwania na `to_thread` nie zatrzymuje już wykonywanej funkcji. Pomiar RSS i czasu innych żądań przy dwóch eksportach jest nadal potrzebny.

Guard UPDATE naprawiono, ale `_DATA_STATEMENTS` nadal wykonują się przed HTTP z `statement_timeout=0`. `lock_timeout=3s` ogranicza oczekiwanie na lock, nie czas samego wykonania. Błąd Alembica nadal jest przepuszczany przed późniejszymi kontrolami safety-net. [Entrypoint](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/backend/entrypoint.sh#L6995-L7004). Najpierw zmierzyć fazy startu, następnie przenieść ciężkie naprawy do wznawialnych jobów i migracji wykonywanej raz. Nie usuwać hurtowo osłon schematu.

### Dowody obserwacji i odtworzenia są nadal niepełne

Po merge poprawek odnaleziono trzy udane próbki workflow Uptime: 13.09 22:55, 14.09 00:46 i 05:51 UTC. Między dwiema ostatnimi jest ponad 5 godzin. Sukces tych próbek nie mierzy krótkich przerw pomiędzy nimi. Najnowszy odczytany dzienny monitor Sentry i E2E poprzedzają poprawki; nie ma nowego dowodu odbioru tych mechanizmów po PR #1502. Nie potwierdzono, czy ręczne kroki z raportu Claude — token, Alloy i zewnętrzne sondy — wykonano w panelach.

Dodatkowo dzisiejszy [Backup Restore Drill](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34805878641) **nie dotarł do przywracania**: workflow zgłosił brak kompletnej konfiguracji dostępu/odszyfrowania backupu off-site. To luka dowodu odzyskania systemu, nie dowód uszkodzenia lub braku backupu. Uzupełnić konfigurację i uzyskać poprawny test restore w izolowanym środowisku.

Dokumentacja hosta jest teraz spójna: CCX33 x86, 8 vCPU/32 GB, z odwołaniem do kontroli Hetznera z 20.07.2026. W reaudytcie nie odczytano nowych metryk hosta, limitów cgroup ani ustawień DB z runtime. Nie ma podstaw do rekomendowania zakupu większego serwera jako pierwszej naprawy.

## 5. Ile ruchu udało się ograniczyć

Dla tego samego modelu co poprzednio: jedna widoczna karta dashboardu, otwarte zadania, zdrowy WS, bez kliknięć, nowych zdarzeń, focus/refetch, retry i początkowego ładowania. `P` oznacza liczbę stron onboardingu, `c` liczbę zapytań plakietek sidebaru.

| Składnik | Nowy koszt GET/min |
|---|---:|
| Powiadomienia | 0,2 |
| KPI | 0,2 |
| Aktywność, moje procesy, kompetencje, kalendarz | 0,8 |
| Onboarding — nadal pobierane wszystkie strony | 0,2 × P |
| Sidebar | 0,2 × c |
| **Razem** | **(6 + P + c) / 5** |

Dla `P=1`, `c=2–3`: **1,8–2,0 GET/min/kartę**, wobec około 9,4–9,6 wcześniej — około 80% mniej. Dla 50 kart to 1,5–1,67 RPS, dla 100 kart 3,0–3,33 RPS samego pollingu. Deklarowane w raporcie Claude ~1,5 GET/min pomija część składników pełnego widoku; własny test stałych w PR liczy 2,0. [Stałe pollingu](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/lib/polling.ts#L14-L25), [test budżetu](https://github.com/B2B-net-S-A/NEXUS/blob/6504fef580964904d6096bf1fd0a16263781ea1b/frontend/src/components/__tests__/QueryProvider.test.tsx#L40-L50).

To **model z kodu**, nie zmierzony HAR i nie uniwersalny limit wszystkich ról. Kolejne strony onboardingu zwiększają koszt; HoR ma dodatkowe obłożenie, a powroty do karty mogą odświeżać dane wcześniej niż po 5 min, bo staleTime bywa krótszy. Początkowe ładowanie i przechodzenie między ekranami mają odrębny koszt.

Przykładowo 6 działań/min × 3 requesty/działanie daje około 15 RPS dla 50 osób i 30 RPS dla 100, plus polling: orientacyjnie **17 / 33 RPS**. To założenie do projektowania testu, nie osiągnięta przepustowość. Rzeczywistą liczbę requestów na działanie trzeba ustalić z sesji użytkowników.

Insights rzeczywiście odracza montowanie. Po obejrzeniu wszystkich sekcji pozostają one zamontowane; zmiana okresu może ponownie uruchomić ich zapytania. Statyczne importy nadal pobierają kod sekcji, więc ta poprawka nie dowodzi zmniejszenia bundle JS.

## 6. Rekomendowana kolejność dalszych prac

Raport wykonania opisuje zakres jako „wszystko, co da się zrobić w kodzie aplikacji bez decyzji infrastrukturalnej”. Reaudyt tego nie potwierdza: R01–R07, pozostałe N+1 Delivery Lead, kontrola eksportów i instrumentacja są konkretnymi dalszymi pracami w kodzie. Podział na poniższe etapy ogranicza ryzyko mieszania napraw poprawności z przebudową uruchamiania.

| Kolejność | Zakres | Właściciel | Warunek zamknięcia |
|---|---|---|---|
| **1 — pilnie** | Odczytać pełną przyczynę nieudanego deployu, uruchomić sondy FE/API 30–60 s i sprawdzić alarm; uzupełnić konfigurację restore drill | Ops + backend | Prawidłowy deploy i diagnozowalne błędy; alarm ≤2 min; udany izolowany restore |
| **2 — mały PR naprawczy** | R01 KPI, R02 reconcile WS, R03 kotwice, R04 bounded upload, R06 retry/fallback, R07 telemetry | Backend + frontend | Testy scenariuszy z §3, CI i potwierdzenie realnych widoków/alertów po wdrożeniu |
| **3 — pomiar i kontrola kosztu** | R05 cykl sesji, metryki p95/p99/pool/loop/jobów, pozostałe N+1, projekcja eksportu i limit współbieżności; pomiar faz startupu | Backend | Zwykły CRUD stabilny podczas cold cache, wolnego AI i eksportów; jawne budżety zasobów |
| **4 — izolacja i dostępność** | Osobne ciężkie workery/scheduler, trwałe joby, komunikacja WS, budżet pul; rollout FE/API z gotowymi obrazami, readiness i drenażem | Backend + Ops | Brak duplikacji/utraty jobów, zachowane powiadomienia, ciągła praca podczas deployu/rollbacku |
| **5 — kwalifikacja skali** | Staging i powtarzalne scenariusze 50/100, soak i recovery; generator poza serwerem aplikacji | QA/performance + backend/Ops | Artefakty spełniające bramki poniżej, dla konkretnego SHA i konfiguracji |

Przygotowanie stagingu, metryk i generatora może iść równolegle od początku. Nie ma potrzeby wprowadzania Kubernetes ani dzielenia całego monolitu na mikroserwisy. Nie zwiększać bez pomiaru liczby workerów i rozmiarów pul.

### Minimalny plan kwalifikacji 50 i 100 osób

Dane stagingu powinny mieć co najmniej reprezentatywną obecną skalę kandydatów, dokumentów i relacji; różne konta, role, portfele i klucze cache. Jedno konto oraz jeden ciepły endpoint zaniżą koszt. Orientacyjny profil: 30% listy/wyszukiwanie kandydatów, 15% profile, 15% rekrutacje/pipeline, 15% klienci/kontrakty/zamówienia, 10% dashboard, 10% dopasowanie, 5% zwykłe zapisy. Przerwy użytkownika 5–15 s, aktywne WS, także dodatkowe karty w tle.

1. Baseline 1 → 10 → 25 sesji; ciepły i zimny cache.
2. **50 aktywnych użytkowników przez ≥30 min**, potem **100 przez ≥60 min**.
3. Zwykła praca równolegle z dwoma dużymi XLSX, 5–10 importerami, kolejką CV oraz reprezentatywną synchronizacją; osobno wolny/niedostępny dostawca AI.
4. Start dnia i zmiana focusu wielu kart; cold cache; ponowne połączenie 100 WS; Insights z kotwicami oraz zmianą okresu po przewinięciu całości.
5. Ciągły ruch i zapisy podczas deployu, rollbacku i wyłączenia jednej instancji na stagingu; stara otwarta karta, assety i nieutracone zadania.
6. Soak ≥4 h przy 100 oraz krótki pik 150 sesji; dodatkowo model stałego napływu, aby spowolnienie aplikacji nie ukrywało przeciążenia. Raportować też niewykonane iteracje generatora.

| Proponowana bramka dla ruchu nominalnego | Wymagany wynik |
|---|---|
| Nieoczekiwane 500/502/503/504 i timeouty, także podczas planowego przełączenia | **0**; poprawne scenariusze biznesowe kończą się spodziewanym wynikiem |
| Utrata lub duplikacja zapisów/jobów, błędne przypisanie CV | **0**, również po recovery |
| Zwykłe API | p95 ≤500 ms, p99 ≤1500 ms, osobno dla ważnych tras |
| Złożony dashboard / wyszukiwanie interaktywne bez generacji AI | p95 odpowiednio ≤1,5 s / ≤2 s |
| Przeglądarka | LCP p75 ≤2,5 s, INP p75 ≤200 ms oraz zmierzony czas do użytecznej listy; poprawne kotwice |
| DB i event loop | Checkout wait p95 <50 ms; loop lag p99 <100 ms; brak wyczerpania puli i narastających transakcji |
| Zasoby i kolejki | Zero OOM/nieplanowanych restartów; RAM i czas oczekiwania nie rosną bez końca przy stałym ruchu; zapas na pik/przełączenie |
| Ciężkie joby | Oddzielne czasy przyjęcia, kolejki i wykonania; po uploadzie przyjęcie p95 ≤1 s, czas AI według osobnego uzgodnionego budżetu |
| Monitoring | Wykrycie i dostarczenie alarmu ≤2 min; jednoznaczne FE/API/job/release |

Są to cele odbioru, nie wyniki już osiągnięte. Mierzyć osobno błędy oczekiwane w scenariuszach awarii i kontrolowane 4xx; nie maskować nimi problemów nominalnych. Zatrzymać zwiększanie obciążenia przy utracie integralności, OOM/pętli restartów albo >1% nieoczekiwanych błędów przez 60 s. Ten próg jest bezpiecznikiem, nie progiem zaliczenia.

Po zaliczeniu etapowy wzrost grupy z obserwacją co najmniej pełnego dnia roboczego: pilot → 25 → 50 → 100. Proponowany operacyjny cel dostępności zwykłej pracy pozostaje 99,95% miesięcznie; trzeba go mierzyć niezależnie dla frontendu i API.

## 7. Testy, dowody i granice wnioskowania

- **Backend: 6/6 istniejących testów PASS** — cztery cache/single-flight/jitter i dwa guardu startup. Uruchomione host-native z `--noconftest`, bez DB i bez Dockera. Nie powielam dwóch testów guardu sprawdzonych dodatkowo przez przegląd infrastruktury w łącznej liczbie.
- **Backend: niezależne reprodukcje offline** — oryginalne funkcje/helpery lub prefiks handlera wyodrębnione z AST. 100 waiterów z anulowaniem: 50 sukcesów, 2 obliczenia, zero osieroconych locków; 20 identycznych nazw CV: poprawne odseparowanie treści i cleanup; XLSX builder na innym wątku; potwierdzone pominięcie multi-role i pełny odczyt oversized przed 413. Bez pełnego API, realnego LLM i zapisu DB.
- **Frontend: 30/30 istniejących testów PASS** — QueryProvider (4), transient retry (11), Insights navigation contract (15). **8/8 niezależnych testów PASS** — realne komponenty/hooki, syntetyczne HTTP/WS i zegar. PASS testu charakterystyki potwierdza również wykryty brak; nie oznacza jego naprawienia.
- **Hosted CI:** odczytano wyniki PR #1502 i jego poprawnego deployu. Deklaracji lokalnych testów Claude nie traktowano jako nowych pomiarów reaudytu.
- **Produkcja:** sześć lekkich GET-ów, odczyt workflow i Coolify status; zalogowane widoki dashboard/Insights oraz kontrola kotwicy. Bez eksportowania danych, uploadów, edycji rekordów i sztucznego ruchu 50/100.
- **Nie wykonano:** benchmarku API biznesowego, HAR, LCP/INP/CLS, EXPLAIN na produkcji, profilu CPU/RAM/IO, pomiaru checkoutów/aktywności 48 pętli, load/soak/failover. Brak tych pomiarów jest jawny; nie zastępują ich pojedyncze healthchecki.

Test „50 równoczesnych zimnych odczytów → jedno obliczenie” jest dobrym testem helpera cache, lecz **nie jest testem 50 użytkowników NEXUS**. Używa jednego klucza i syntetycznej pracy, bez HTTP, autoryzacji, SQL, różnych widoków, ciężkich jobów ani deployu.

Materiały z tego reaudytu: [indeks dowodów](../outputs/performance-reaudit-2026-09-14/EVIDENCE.md), [publiczne sondy](../outputs/performance-reaudit-2026-09-14/public-probes.json), [reprodukcje backendu](../outputs/performance-reaudit-2026-09-14/backend-repro-result.json), [wyniki niezależnych testów frontend](../outputs/performance-reaudit-2026-09-14/frontend-results.json), [obserwacje Chrome](../outputs/performance-reaudit-2026-09-14/ui-observations.json). Poprzedni raport pozostaje osobnym dokumentem; niniejszy opisuje stan po poprawkach.
