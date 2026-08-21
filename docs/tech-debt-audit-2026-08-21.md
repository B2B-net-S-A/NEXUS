# Audyt długu technicznego — NEXUS ATS

> HEAD `61a217d9` · 21.08.2026 · raport interaktywny: <https://claude.ai/code/artifact/5607c694-87dc-4643-aeef-59da2459a7d3>
> **Pełne dane** (scenariusze awarii, dowody w kodzie, notatki weryfikatorów) i **stan realizacji**:
> [`docs/tech-debt-backlog.json`](./tech-debt-backlog.json). To jest źródło prawdy — ten plik to czytelny przekrój.

## Jak to policzono

170 agentów, 40,5 mln tokenów, 6 700 wywołań narzędzi, 5,2 h. Fazy: rekonesans na żywej produkcji →
16 równoległych finderów → **adwersarialna weryfikacja każdego zgłoszenia przez osobnego agenta**
z instrukcją obalenia go → krytyk kompletności → druga runda na wskazanych lukach.

Ze 125 zgłoszeń głównej rundy **21 obalono**. Zostały 104 zweryfikowane + 24 z rekonesansu
(oznaczone `verified: false` w backlogu — nie przeszły weryfikacji adwersarialnej).

**128 znalezisk:** 3× P0 · 58× P1 · 57× P2 · 10× P3.
Wg wpływu: 58× nie działa · 18× dług · 52× ryzyko.

**Ograniczenia.** Agenty miały dostęp wyłącznie do publicznych endpointów produkcji — nic za
autoryzacją nie zostało sprawdzone na żywo. Znaleziska z rekonesansu nie przeszły weryfikacji
adwersarialnej (wyjątek: kopia zapasowa — trzy niezależne agenty doszły do niej osobno).

---

## Wzorce systemowe

Każda klasa ma jedną zmianę, która zatrzymuje produkcję kolejnych egzemplarzy. **To ona jest tu
warta więcej niż lista naprawionych wystąpień** — i dlatego kolejność napraw idzie od wzorca do wystąpień.

### 1. Pieniądze liczone ze stalej kolumny · `P0` · 9 znalezisk

Pięć powierzchni finansowych — analytics, board/sales, /my-clients, admin clients-overview i marża zamówienia — sumują cache'owane kolumny `contracts.rate_*`, odświeżane wyłącznie przy ZAPISIE kontraktu. Tylko profil klienta czyta harmonogramy stawek efektywnych. Do tego kanoniczny filtr MRR to negacja `status != draft`, która wpuszcza `ready_for_signature` i `void`, a liczniki konsultantów biorą `status == active`, gubiąc każdego w ostatnich 30 dniach.

**Jedna zmiana, która zabija całą klasę:** Jeden resolver stawek efektywnych (`_effective_rate_fields`) i test kontraktowy, który zabrania czytać `contracts.rate_*` poza nim. Filtry statusu wyliczaj z jednej listy pozytywnej, nigdy z negacji.

Znaleziska: [#23](#f23), [#27](#f27), [#64](#f64), [#28](#f28), [#29](#f29), [#24](#f24), [#31](#f31), [#6](#f6), [#30](#f30)

### 2. Cache dopasowań truje sam siebie · `P0` · 8 znalezisk

`/jobs/{id}/pipeline-scores` ma własną, niepełną definicję „świeżego” wiersza — bez predykatu `scoring_algorithm_version`. Po każdym bumpie wag (ostatnio 17–18.08) przelicza stare wiersze z wyzerowaną warstwą semantyczną (0 z 60 pkt) i zapisuje je jako świeże pod NOWĄ wersją. Zaniżony pierścień na kanbanie zostaje na zawsze i wycieka do wszystkich innych czytelników tego klucza.

**Jedna zmiana, która zabija całą klasę:** Jedna definicja świeżości cache w jednym miejscu. Zakaz zapisu do cache, gdy warstwa semantyczna nie dostała danych (`allow_cache_write=False`). Jednorazowy UPDATE czyszczący wiersze zatrute od 17.08.

Znaleziska: [#32](#f32), [#9](#f9), [#34](#f34), [#35](#f35), [#63](#f63), [#7](#f7), [#8](#f8), [#25](#f25)

### 3. Kopia zapasowa nigdy nie została zweryfikowana · `P0` · 1 znalezisk

Obie połowy siatki bezpieczeństwa są martwe jednocześnie. Drill przywracania pada od 27.07 co tydzień, bo `BACKUP_AGE_PRIVATE_KEY`, `BACKUP_S3_ACCESS_KEY` i `BACKUP_S3_SECRET_KEY` nie istnieją w repo. `BACKUP_MONITORING_ENABLED=false`, więc godzinowy check świeżości jest pomijany. W repo jest dowód na dokładnie ZERO udanych przywróceń kopii off-site.

**Jedna zmiana, która zabija całą klasę:** To robota operatora, nie zmiana w kodzie: osobna para kluczy age dla drilla, read-only klucz B2, ręczne `gh workflow run backup-drill.yml` i przeczytanie LATEST.json. Do zielonego przebiegu traktuj kopię off-site jako nieistniejącą.

Znaleziska: [#201](#f201)

### 4. Awaria renderuje się jako pustka albo cisza · `P1` · 12 znalezisk

Najczęstsza klasa defektu w tym repo, mimo że jest udokumentowana w CLAUDE.md. Kalendarz rysuje pełny, pusty tydzień na 403. Zakładka „Umowy” zamienia 403 w „Brak umów ramowych”. `/contracts/analytics` na 588 linii nie ma ani jednej gałęzi `isError` — `?? []` zamienia padnięty fetch marży w pewne siebie „0,00 zł”. Nieudane zapisy są niewidoczne w całej aplikacji.

**Jedna zmiana, która zabija całą klasę:** Wspólny `&lt;QueryBoundary&gt;` i reguła ESLint: `useQuery` bez gałęzi `isError` oraz `useMutation` bez `onError` = błąd lintu, nie code review.

Znaleziska: [#11](#f11), [#12](#f12), [#43](#f43), [#44](#f44), [#45](#f45), [#46](#f46), [#48](#f48), [#65](#f65), [#104](#f104), [#47](#f47), [#38](#f38), [#55](#f55)

### 5. Wydatki na AI poza bramką · `P1` · 10 znalezisk

Wszystkie 11 funkcji AI chodzi na prodzie bez miesięcznego sufitu — warstwa kwot fail-open, limit z Ustawień nie jest egzekwowany nigdzie. Admin kill-switch nie zatrzymuje generacji CV B2B, czyli najdroższego wywołania Claude'a w produkcie. Dwa endpointy MINDY są całkowicie poza systemem kwot. Osiem ścieżek płaci kwotą, ale loguje się jako UNGATED. `GET /api/settings/ai` zwraca dziś 500 na prodzie.

**Jedna zmiana, która zabija całą klasę:** Jedno wejście `ai_feature()` z twardym miesięcznym sufitem. Provider boundary odrzuca każde wywołanie bez deklaracji — wtedy „UNGATED” w logu przestaje być notatką, a staje się blokadą.

Znaleziska: [#33](#f33), [#92](#f92), [#93](#f93), [#94](#f94), [#95](#f95), [#91](#f91), [#26](#f26), [#36](#f36), [#202](#f202), [#222](#f222)

### 6. Czas i sortowanie: UTC vs Warszawa, musl vs ICU · `P1` · 11 znalezisk

113 wywołań `date.today()` chodzi na zegarze kontenera w UTC, a `BUSINESS_TZ='Europe/Warsaw'` jest honorowane w 6 miejscach. Podia konkursów kubełkują zdarzenia po miesiącu UTC, a panel KPI tego samego rekrutera — po miesiącu warszawskim. Osobno: Postgres chodzi na musl, więc polskie nazwiska sortują się po bajtach; zwycięzca nagrody 1500 PLN jest wyłaniany nieoznaczonym tie-breakiem bajtowym i zamrażany bez możliwości korekty.

**Jedna zmiana, która zabija całą klasę:** Jedna funkcja granic okresu w `Europe/Warsaw`, używana wszędzie. Kolacja `pl-PL-x-icu` albo obraz na glibc — plus asercja kolacji w `/api/health/deep`, żeby regresja była widoczna.

Znaleziska: [#77](#f77), [#78](#f78), [#79](#f79), [#76](#f76), [#86](#f86), [#87](#f87), [#88](#f88), [#89](#f89), [#90](#f90), [#218](#f218), [#221](#f221)

### 7. Lustra ról rozjeżdżają się dalej · `P1` · 10 znalezisk

Lista ról jest kopiowana do pięciu miejsc i kopie znów się rozjechały. Panel rate-cards daje Delivery Leadowi UI dodaj/edytuj/usuń, które za każdym razem kończy się 403 (usuwanie po cichu). Dashboard HoR linkuje do trasy, której middleware zabrania HoR-owi i adminowi. Konsola Priority Work została odcięta — 23 z 24 endpointów jest nieosiągalnych z żadnej trasy. Żaden test nie porównuje literału roli po stronie FE z guardem w Pythonie.

**Jedna zmiana, która zabija całą klasę:** Jedno źródło macierzy uprawnień, generowane do TypeScriptu, plus test kontraktowy porównujący literały ról po obu stronach. Dopóki go nie ma, każde otwarcie dostępu trzeba ręcznie przemiatać po pięciu lustrach.

Znaleziska: [#11](#f11), [#12](#f12), [#38](#f38), [#47](#f47), [#67](#f67), [#101](#f101), [#102](#f102), [#103](#f103), [#104](#f104), [#97](#f97)

### 8. RODO: usunięcie kandydata nie usuwa wszystkiego · `P1` · 7 znalezisk

Hard delete gubi wynik czyszczenia Qdranta i storage zamiast zakolejkować trwały retry, który bliźniacza ścieżka kwarantanny już ma. Wymazanie nigdy nie unieważnia linku do wygenerowanego CV — publiczny `/api/public/cv-i/{token}` serwuje pełne CV wymazanej osoby dalej. `RedactingFilter` przepisuje tylko `record.msg`. Refresh token na 30 dni jedzie jako parametr URL, a filtr redakcji go nie maskuje.

**Jedna zmiana, która zabija całą klasę:** Rejestr powierzchni trzymających dane kandydata i test „erasure pokrywa N powierzchni”, który rośnie razem z listą — inaczej każda nowa funkcja cicho poszerza lukę.

Znaleziska: [#68](#f68), [#69](#f69), [#70](#f70), [#71](#f71), [#15](#f15), [#13](#f13), [#14](#f14)

### 9. Zadania w tle: nikt nie wie, że umarły · `P1` · 13 znalezisk

Martwa pętla lifespan jest niewykrywalna i nigdy nie restartowana — `AsyncioIntegration` jest bezczynne, bo init leci przy imporcie, przed pętlą zdarzeń. Sześć żywych pętli loguje awarie całego cyklu na WARNING, poniżej progu zdarzeń Sentry. Przypomnienie T-15 przed rozmową ma 120-sekundowe okno dostarczenia, więc każdy redeploy Coolify je gubi. Nic w systemie nie odróżnia świeżego kursu NBP od sprzed miesięcy.

**Jedna zmiana, która zabija całą klasę:** Heartbeat każdej pętli w `/api/health/deep` i awaria cyklu logowana na ERROR, nie WARNING — inaczej Sentry jej nie zobaczy, a health dalej będzie zielony.

Znaleziska: [#19](#f19), [#20](#f20), [#21](#f21), [#22](#f22), [#16](#f16), [#17](#f17), [#4](#f4), [#5](#f5), [#18](#f18), [#80](#f80), [#81](#f81), [#219](#f219), [#205](#f205)

### 10. Bramka jakości przepuszcza to, co miała chwytać · `P1` · 10 znalezisk

239 backendowych funkcji testowych jest wyłączonych z CI, 188 w 17 plikach znanych jako czerwone — w tym 63 pokrywające parsowanie CV. Suite Playwright nie weryfikuje niczego: 40 z 46 przypadków nigdy nie startuje przez brak sekretów, a jedyny działający projekt jest czerwony od 21 nocy z rzędu. `next.config.ts` wyłącza type-check i lint podczas `next build`. Trivy nie jest report-only, tylko report-to-nowhere. Sentry digest raportuje sukces, nie robiąc nic.

**Jedna zmiana, która zabija całą klasę:** CI musi liczyć i raportować, ile testów POMINIĘTO. Pominięcie większe od zera bez jawnego powodu = czerwony build. Zielony przebieg, który nic nie uruchomił, jest gorszy niż brak przebiegu.

Znaleziska: [#66](#f66), [#67](#f67), [#63](#f63), [#215](#f215), [#216](#f216), [#214](#f214), [#212](#f212), [#213](#f213), [#203](#f203), [#204](#f204)

### 11. Frontend: retry, timeouty i martwe klucze cache · `P1` · 6 znalezisk

Interceptor retry nie ma guardu na metodę HTTP — jego najszersza gałąź powtarza POST/PATCH/DELETE dwa razy przy każdym timeoutcie klienta lub padzie bez CORS. Cztery POST-y LLM chodzą na 30-sekundowym pułapie CRUD zamiast `SLOW_ENDPOINT_TIMEOUT_MS`, więc każdy abort zamienia się w dwa kolejne pełne przebiegi. Cztery mutacje unieważniają klucze cache, których nikt nie produkuje.

**Jedna zmiana, która zabija całą klasę:** Retry wyłącznie dla metod idempotentnych. Klucze cache z jednego rejestru zamiast literałów wpisywanych w miejscu wywołania — literał z literówką jest niewidoczny do momentu, aż użytkownik zgłosi „nie odświeża się”.

Znaleziska: [#42](#f42), [#49](#f49), [#50](#f50), [#51](#f51), [#52](#f52), [#53](#f53)

### 12. Publiczna powierzchnia i sekrety · `P2` · 8 znalezisk

Produkcyjne `/openapi.json`, `/docs` i `/redoc` są publiczne i nieuwierzytelnione — 747 endpointów i 876 schematów ATS-a do wyliczenia przez każdego, plus 118 641 znaków wewnętrznego uzasadnienia inżynierskiego. `/docs` i `/redoc` zwracają 200 i renderują pustą stronę. gitleaks — bramka blokująca deploy — jest ślepy na dwa pliki workflow obsługujące prawdziwe poświadczenia, w tym prywatny klucz age do backupu.

**Jedna zmiana, która zabija całą klasę:** Dokumentacja API za auth na prodzie, każdy publiczny endpoint z limitem, a allowlista gitleaks bez wpisów ścieżkowych na pliki, które faktycznie dotykają sekretów.

Znaleziska: [#72](#f72), [#73](#f73), [#74](#f74), [#75](#f75), [#13](#f13), [#206](#f206), [#211](#f211), [#217](#f217)

### 13. Dostawa i zależności · `P2` · 4 znalezisk

Brak jakiegokolwiek lockfile'a Pythona: każda zależność przechodnia backendu pływa, a Coolify buduje obraz ze źródeł przy każdym deployu. Produkcyjny obraz frontendu buduje się przez `npm install`, nie `npm ci` — lockfile, który CI egzekwuje, jest w obrazie tylko poradą. Kontener backendu nie ma healthchecku w jedynym compose, który Coolify czyta. Automatyczne review pada na 100% PR-ów Dependabota, bo bota nie ma w `allowed_bots`.

**Jedna zmiana, która zabija całą klasę:** Zamroź zależności (pip-tools/uv lock po stronie Pythona, `npm ci` w obrazie) i wpuść dependabota do review — dziś jedyna klasa PR-ów zmieniająca cudzy kod jest jedyną bez recenzji.

Znaleziska: [#209](#f209), [#210](#f210), [#207](#f207), [#208](#f208)

### 14. Generator B2B renderuje na żywym rejestrze · `P2` · 5 znalezisk

Ponowne pobranie wygenerowanej umowy B2B renderuje ją względem ŻYWYCH rejestrów — tabeli klauzul per klient i mutowalnej tabeli ról — a nie snapshotu. O tym, które prawnie wiążące klauzule wejdą do dokumentu, decyduje case-insensitive dopasowanie PODCIĄGU wolnotekstowej nazwy klienta, pierwsze trafienie wygrywa. Aplikacja nadpisań klauzul nie ma kanału sukcesu: licznik jest wyrzucany, więc cicha porażka wygląda jak sukces.

**Jedna zmiana, która zabija całą klasę:** Snapshot rejestru klauzul w chwili generacji i dopasowanie po ID klienta, nie po podciągu nazwy. To samo pole nazwy jest nadpisywane przez import z Traffita.

Znaleziska: [#82](#f82), [#83](#f83), [#84](#f84), [#85](#f85), [#220](#f220)

### 15. Martwy kod i odcięte moduły · `P2` · 12 znalezisk

29 plików frontendu / 5734 LOC jest nieosiągalnych z jakiejkolwiek trasy, ~1000 LOC osierocone wewnątrz jednego PR-a RBAC, cztery pliki kompilują się wyłącznie dzięki własnym testom. PR #539 skasował jedyne wejście do czytnika wątków M365 na fałszywej przesłance „duplikat”. Konsola Priority Work została odcięta w całości. Do tego martwe knobki konfiguracji, które kłamią operatorowi.

**Jedna zmiana, która zabija całą klasę:** knip/ts-prune w CI jako raport plus kwartalny przegląd. Każde PR-owe usunięcie trasy musi wskazać nowe wejście do modułu — inaczej moduł zostaje w buildzie i w głowie zespołu, ale nie w produkcie.

Znaleziska: [#40](#f40), [#101](#f101), [#37](#f37), [#1](#f1), [#2](#f2), [#3](#f3), [#41](#f41), [#54](#f54), [#61](#f61), [#56](#f56), [#100](#f100), [#224](#f224)

### 16. Wtyczka LinkedIn bez siatki bezpieczeństwa · `P2` · 6 znalezisk

Wtyczka, której rekruterzy używają codziennie, ma zero CI, zero testów i dwa commity w historii, a trzyma 30-dniowy refresh token i wildcard host permissions obejmujący trzy panele Coolify i dwie obce apki produkcyjne. Na Sales Navigatorze scraper bierze PIERWSZĄ kotwicę `/in/` w całym dokumencie. Ma jedyną ścieżkę logowania.

**Jedna zmiana, która zabija całą klasę:** Wtyczka wchodzi do CI (lint plus test scrapera na zapisanych DOM-ach) albo zostaje świadomie wycofana. Zawężenie `host_permissions` do samego LinkedIna i API to zmiana na jedną linię.

Znaleziska: [#96](#f96), [#97](#f97), [#98](#f98), [#99](#f99), [#100](#f100), [#223](#f223)

---

## Indeks

| # | Sev | Nakład | Obszar | Plik | Tytuł |
|---|-----|--------|--------|------|-------|
| [#23](#f23) | P0 | M | Backend · analityka | `backend/app/analytics/metrics.py:518` | Analityka finansowa sumuje przeterminowane, cache'owane kolumny `contracts.rate_*` zamiast harmonogramów stawek, które… |
| [#32](#f32) | P0 | S | Backend · API | `backend/app/api/recommendations.py:602` | `/jobs/{id}/pipeline-scores` reimplementuje regułę świeżości cache bez predykatu `scoring_algorithm_version`, więc po … |
| [#201](#f201) | P0 | M | CI/CD | `.github/workflows/backup-drill.yml:71` | Kopia off-site nigdy nie została zweryfikowana: drill przywracania pada 4 tygodnie z rzędu (brak sekretów), a monitor … |
| [#4](#f4) | P1 | M | Backend · serwisy | `backend/app/services/traffit/importer.py:1954` | Sześć nocnych faz Traffita nadal używa `db.rollback()` na poziomie sesji per wiersz z jednym commitem po pętli — ten s… |
| [#5](#f5) | P1 | M | Backend · serwisy | `backend/app/services/match_justification_service.py:508` | Wywołania AI lecą wewnątrz otwartej transakcji DB wołającego: połączenie z puli i blokada wiersza `ai_usage_logs` są t… |
| [#6](#f6) | P1 | S | Backend · API | `backend/app/api/reports.py:1541` | Board i Sales liczą trend 12-miesięczny krokiem 30 dni — luty znika, sąsiedni miesiąc dubluje się co roku w marcu–maju… |
| [#8](#f8) | P1 | M | Backend · API | `backend/app/api/matching.py:296` | Awaria Voyage/Qdranta po cichu zrzuca `/api/jobs/{id}/ai-matches` do rankingu po tagach na dowolnej 100-wierszowej pró… |
| [#9](#f9) | P1 | M | Backend · serwisy | `backend/app/services/embedding_service.py:478` | Jeden przejściowy błąd Voyage podczas zakładania kandydata trwale wypycha go z matchingu wektorowego: `False` z `embed… |
| [#11](#f11) | P1 | M | Frontend · UI | `frontend/src/components/FrameworkContractsTab.tsx:52` | Zakładka "Umowy" na profilu klienta zamienia backendowe 403 w "Brak umów ramowych" — recruiter/sourcer/finance/nieprzy… |
| [#12](#f12) | P1 | S | Frontend · UI | `frontend/src/components/RateCardsTab.tsx:166` | Panel cenników nigdy nie odzwierciedlił cutoveru finansowego z 04.08: Delivery Lead dostaje UI do dodawania/edycji/usu… |
| [#15](#f15) | P1 | S | Backend · API | `backend/app/api/auth.py:492` | `POST /api/auth/refresh` przyjmuje 30-dniowy refresh token jako parametr query w URL, a własny filtr redakcji logów w … |
| [#16](#f16) | P1 | M | Schemat / boot | `backend/entrypoint.sh:4913` | Safety-net `CREATE INDEX CONCURRENTLY` w entrypoincie nie ma odzyskiwania po nieprawidłowym indeksie — anulowany build… |
| [#17](#f17) | P1 | S | Schemat / boot | `backend/entrypoint.sh:4892` | Faza DDL przy starcie w `entrypoint.sh` wykonuje 500+ instrukcji biorących zamki (253 `ALTER TABLE`, 210 zwykłych `CRE… |
| [#19](#f19) | P1 | S | Backend · API | `backend/app/api/calendar.py:1054` | Przypomnienie T-15 o rozmowie jest dostarczalne tylko w 120-sekundowym oknie kwalifikowalności na zdarzenie, więc każd… |
| [#20](#f20) | P1 | M | Backend · serwisy | `backend/app/services/fx_service.py:198` | Nic w systemie nie odróżni świeżego kursu NBP od sprzed miesięcy: każda nieudana pobranie kończy się jako `logger.warn… |
| [#24](#f24) | P1 | S | Backend · API | `backend/app/api/my_clients.py:389` | Zakładka Analityka w profilu klienta liczy konsultantów tylko po `status == active`, więc każdy konsultant w swoich os… |
| [#25](#f25) | P1 | M | Backend · API | `backend/app/api/matching.py:107` | /ai-matches buduje swoje chipy skilli ✓/✗ wyłącznie z `candidate.skills` — pustego dla 49 440 z 49 802 kandydatów na p… |
| [#27](#f27) | P1 | L | Backend · analityka | `backend/app/analytics/metrics.py:518` | Tylko profil klienta wyprowadza stawki z harmonogramów z datami obowiązywania; analityka, raporty Board/Sales, /my-cli… |
| [#28](#f28) | P1 | S | Backend · analityka | `backend/app/analytics/metrics.py:452` | Kanoniczny filtr MRR to negatywne `status != draft`, które po cichu wpuszcza `ready_for_signature` i `void` — zasila Ż… |
| [#29](#f29) | P1 | M | Backend · API | `backend/app/api/admin_clients_overview.py:164` | Admiński przegląd klientów liczy konsultantów i marżę tylko po `status == active` — a dzienny cron promuje active→endi… |
| [#30](#f30) | P1 | S | Backend · API | `backend/app/api/md_consumption.py:344` | Zduplikowane wiersze konsultanta w jednym arkuszu MD nadpisują się zamiast sumować — odejmowane jest tylko MD z ostatn… |
| [#33](#f33) | P1 | M | Backend · serwisy | `backend/app/services/cv_generator_b2b/ai_client.py:384` | Administracyjny kill-switch AI nie zatrzymuje generowania CV B2B (najdroższego wywołania Claude w produkcie) — zatrzym… |
| [#34](#f34) | P1 | M | Backend · serwisy | `backend/app/services/traffit/importer.py:1676` | Traffit sync zapisuje intencję reindeksu wyłącznie dla INSERT-ów — fazy CV/enrich nadpisują raw_cv_text, ai_summary, s… |
| [#35](#f35) | P1 | S | Backend · tło | `backend/app/tasks/compute_proposals.py:250` | Snapshot propozycji nigdy nie stosuje historycznego boostu, który /recommendations dokłada przed odcięciem po min-scor… |
| [#37](#f37) | P1 | M | Frontend · UI | `frontend/src/components/emails/EmailThreadList.tsx:36` | PR #539 usunął jedyne wejście do czytnika wątków M365 na fałszywym uzasadnieniu "duplikat" — 1473 LOC + 7 żywych endpo… |
| [#42](#f42) | P1 | S | Frontend · lib | `frontend/src/lib/api.ts:182` | Interceptor retry w axiosie nie ma guardu na metodę HTTP: jego najszersza gałąź (!err.response) powtarza POST/PATCH/DE… |
| [#43](#f43) | P1 | M | Frontend · UI | `frontend/src/app/contracts/analytics/page.tsx:234` | /contracts/analytics nie ma gałęzi isError w 588 liniach: `?? []` zamienia nieudane pobranie marży w pewne siebie „0,0… |
| [#44](#f44) | P1 | S | Frontend · UI | `frontend/src/app/calendar/page.tsx:175` | Tygodniowa siatka kalendarza nie ma gałęzi isError: 403 z guardu rolowego (rola viewer widzi link w sidebarze, ale bac… |
| [#45](#f45) | P1 | S | Frontend · UI | `frontend/src/components/contracts/ClientContractRegister.tsx:546` | Rejestr kontraktów per klient nigdy nie czyta isError — 5xx/timeout albo 403 renderuje się jako „0 kontraktów" + „Brak… |
| [#46](#f46) | P1 | M | Frontend · UI | `frontend/src/components/v2/modals/ScreeningSheet.tsx:118` | Nieudane zapisy są niewidoczne w całej aplikacji — nie ma globalnego handlera błędów mutacji, a 86 miejsc useMutation … |
| [#49](#f49) | P1 | S | Frontend · lib | `frontend/src/lib/api.ts:3654` | Cztery POST-y champion-draft do LLM chodzą na 30-sekundowym suficie dla CRUD-a zamiast na `SLOW_ENDPOINT_TIMEOUT_MS`, … |
| [#53](#f53) | P1 | S | Frontend · lib | `frontend/src/lib/filter-options.ts:125` | Filtr „Typ" na `/contracts` i jego eksport XLSX/CSV zawsze kończą się 500 — wszystkie trzy opcje (`body_leasing`/`fixe… |
| [#55](#f55) | P1 | M | Frontend · UI | `frontend/src/components/AppShell.tsx:1438` | `AddJobModal` zapisuje obiektowy `detail` z 503 o wyczerpanej kwocie AI w stanie typu string i renderuje go jako dziec… |
| [#60](#f60) | P1 | S | Frontend · UI | `frontend/src/components/Toast.tsx:101` | Niezmemoizowana wartość ToastContext re-renderuje każdego zamontowanego konsumenta useToast() przy każdym toaście — a … |
| [#63](#f63) | P1 | M | Testy | `backend/tests/test_index_coverage_write_paths.py:39` | Poprawka "kandydaci brakujący w indeksie" z 28 lipca wyliczyła ręcznie 4 ścieżki zapisu i pominęła żywą kolejkę zgłosz… |
| [#64](#f64) | P1 | M | Backend · API | `backend/app/api/client_orders.py:173` | Marża zamówienia czyta contracts.rate_* — cache zapisywany przy zapisie, bez żadnego odświeżacza — więc każdy krok sta… |
| [#67](#f67) | P1 | M | Testy | `frontend/src/lib/__tests__/capabilities.test.ts:38` | Żaden test po żadnej ze stron nie porównuje literału roli z frontendu ze strażnikiem w Pythonie — `RateCardsTab` nadal… |
| [#68](#f68) | P1 | M | Backend · API | `backend/app/api/candidates.py:4313` | Twarde usunięcie kandydata porzuca wynik sprzątania Qdranta/storage zamiast zakolejkować trwały retry, którego bliźnia… |
| [#69](#f69) | P1 | S | Backend · API | `backend/app/api/public_share.py:278` | Usunięcie kandydata nigdy nie odwołuje linku współdzielenia jego wygenerowanego CV: publiczny endpoint `/api/public/cv… |
| [#70](#f70) | P1 | M | Backend · rdzeń | `backend/app/core/logging_config.py:83` | `RedactingFilter` przepisuje wyłącznie `record.msg` — formatter emituje `record.exc_info` osobno, a przy braku `hide_p… |
| [#80](#f80) | P1 | S | Backend · API | `backend/app/api/microsoft365.py:247` | Ponowne połączenie M365 czyści martwą kolumnę `delta_token_messages` zamiast żywych kursorów per-folder, więc `backfil… |
| [#81](#f81) | P1 | M | Backend · serwisy | `backend/app/services/m365/sync.py:90` | Sync M365 nie ma bramki per skrzynka: `last_sync_status = running` jest zapisywany i nigdy nie czytany, więc backfill … |
| [#82](#f82) | P1 | M | Backend · API | `backend/app/api/b2b_contract_generator.py:1407` | Ponowne pobranie wygenerowanej umowy B2B renderuje ją względem ŻYWYCH rejestrów (tabeli klauzul per klient ORAZ mutowa… |
| [#86](#f86) | P1 | M | Backend · API | `backend/app/api/candidates.py:1091` | Sortowanie „Nazwisko (A-Z)" na liście kandydatów wykonuje ORDER BY pod kolacją bajtową musl (i sortuje po IMIENIU, nie… |
| [#88](#f88) | P1 | M | Backend · API | `backend/app/api/clients.py:269` | Porządkowanie polskich nazw na prodzie jest porządkiem bajtowym, bo DB stoi na musl — lista kandydatów wydaje sortowan… |
| [#89](#f89) | P1 | M | Infra | `docker-compose.yml:24` | Polskie nazwiska już teraz sortują się źle pod musl (rozpoznane w repo, ale błędnie zdiagnozowane jako brak `unaccent`… |
| [#91](#f91) | P1 | S | Backend · API | `backend/app/api/ai_settings.py:69` | `GET /api/settings/ai` zwraca 500 na prodzie: niefiltrowany `select(AIFeatureConfig)` hydratuje osierocone wiersze `ai… |
| [#93](#f93) | P1 | M | Backend · API | `backend/app/api/cv_match_preview.py:235` | Obciążenie kwoty nie deklaruje wywołania: osiem ścieżek płaci przez gołe `check_and_increment` i mimo to loguje się ja… |
| [#96](#f96) | P1 | L | Wtyczka | `extension/src/shared/api-client.js:108` | Wtyczka LinkedIn ma JEDYNĄ ścieżkę logowania — email+hasło — a prod zwraca na niej 503, bo logowanie hasłem jest wyłąc… |
| [#97](#f97) | P1 | S | Backend · API | `backend/app/api/candidates.py:2546` | POST /api/candidates/from-linkedin zapisuje `CandidateStage` dla już istniejącego kandydata po sprawdzeniu WYŁĄCZNIE w… |
| [#202](#f202) | P1 | S | Backend · serwisy | `backend/app/services/ai_quota.py:172` | Każda z 11 funkcji AI działa na prodzie bez miesięcznego sufitu — warstwa kwot jest fail-open, a limit z Ustawienia→AI… |
| [#203](#f203) | P1 | S | Testy | `frontend/e2e/candidate-ux-preview.spec.ts:104` | Nocny E2E na produkcji jest czerwony od 12+ nocy z rzędu na etykiecie zmienionej trzy tygodnie temu — jedyny automatyc… |
| [#204](#f204) | P1 | S | CI/CD | `.github/workflows/sentry-daily-monitor.yml:38` | Workflow dziennego digestu Sentry raportuje sukces każdego ranka, nie robiąc nic — `SENTRY_AUTH_TOKEN` nigdy nie zosta… |
| [#207](#f207) | P1 | S | Infra | `docker-compose.yml:114` | Kontener backendu nie ma healthchecka w jedynym pliku compose, który czyta Coolify — definicja siedzi w `docker-compos… |
| [#208](#f208) | P1 | S | CI/CD | `.github/workflows/claude-review.yml:33` | Automatyczne review PR-ów pada na 100% PR-ów Dependabota, bo `dependabot` nie jest w `allowed_bots` — jedyna klasa PR-… |
| [#212](#f212) | P1 | M | CI/CD | `.github/workflows/e2e.yml:41` | Suite E2E w Playwrighcie nie weryfikuje niczego: 40 z 46 przypadków testowych nigdy się nie wykonuje z braku sekretów,… |
| [#213](#f213) | P1 | S | Frontend · UI | `frontend/next.config.ts:12` | next.config.ts wyłącza type-checking i linting podczas `next build`, co unieważnia dokładnie tę siatkę bezpieczeństwa,… |
| [#217](#f217) | P1 | S | Backend | `backend/app/main.py:643` | Produkcyjne Swagger UI, ReDoc i openapi.json są publiczne i bez uwierzytelnienia — 747 endpointów i 876 schematów ATS-… |
| [#218](#f218) | P1 | M | Backend · tło | `backend/app/tasks/contract_alerts.py:54` | 113 wywołań date.today() działa na zegarze kontenera w UTC, podczas gdy BUSINESS_TZ='Europe/Warsaw' jest respektowane … |
| [#219](#f219) | P1 | M | Backend · API | `backend/app/api/microsoft365.py:573` | 21 miejsc z asyncio.create_task() typu fire-and-forget nie trzyma silnej referencji — CPython może je zebrać GC w loci… |
| [#220](#f220) | P1 | M | Backend · serwisy | `backend/app/services/b2b_contract_generator/clause_overrides.py:48` | O tym, które prawnie wiążące klauzule trafią do generowanej umowy B2B, decyduje dopasowanie PODCIĄGU bez rozróżniania … |
| [#7](#f7) | P2 | M | Backend · API | `backend/app/api/candidates.py:1617` | Kolumna `match` na liście kandydatów przelicza od zera każdą parę (kandydat ze strony × opublikowana oferta) przy każd… |
| [#10](#f10) | P2 | S | Backend · API | `backend/app/api/pipeline.py:1277` | `POST /api/pipeline/stages/{id}/screening` połyka invalidację cache'u match-score bez ani jednej linii logu — jedyny t… |
| [#13](#f13) | P2 | S | Backend · API | `backend/app/api/public_engagement.py:13` | Publiczna trasa magic-link do deklaracji zaangażowania nie ma rate limitu ani `max_length` na polu tekstowym, łamiąc w… |
| [#14](#f14) | P2 | S | Backend · API | `backend/app/api/oauth_token.py:104` | Funkcja OAuth2 client-credentials jest wdrożona w połowie: Ustawienia reklamują klucze API dla n8n/ChatGPT/Zapier, a e… |
| [#18](#f18) | P2 | S | Backend | `backend/app/main.py:1928` | `/api/health/deep` — jedyna bramka schematu po deployu — sonduje 41 tabel, ale nie `users`, `candidate_stages`, `notes… |
| [#21](#f21) | P2 | M | Backend · API | `backend/app/api/admin_snapshot.py:133` | Martwa pętla z lifespanu jest niewykrywalna i nigdy nie restartowana: `AsyncioIntegration` jest bezczynne (init leci p… |
| [#22](#f22) | P2 | S | Backend · tło | `backend/app/tasks/match_history_ttl.py:72` | Sześć żywych pętli w tle loguje awarie całych cykli na poziomie WARNING, poniżej progu ERROR dla Sentry — własny audyt… |
| [#26](#f26) | P2 | M | Backend · API | `backend/app/api/ai_writer.py:227` | POST /api/ai/generate-job buduje surowego klienta Anthropic z domyślnym timeoutem SDK 600 s, więc trzyma jeden z 40 ws… |
| [#31](#f31) | P2 | S | Backend · API | `backend/app/api/client_order_groups.py:442` | Sumy PLN zamówień kosztowych (budget_amount / budget_used / budget_remaining / invoiced_total / unsettled_total) omija… |
| [#36](#f36) | P2 | S | Backend · API | `backend/app/api/ai_writer.py:227` | POST /api/ai/generate-job połyka KAŻDĄ awarię Claude'a (łącznie z JSON-em uciętym przez max_tokens, na czym to repo ju… |
| [#38](#f38) | P2 | M | Frontend · UI | `frontend/src/middleware.ts:83` | Alerty nadzoru nad kontaktem na dashboardzie HoR linkują do /candidates/contact-queue — trasy, której middleware odmaw… |
| [#39](#f39) | P2 | S | Frontend · UI | `frontend/src/components/v2/shell/SidebarV2.tsx:517` | Sidebar odpytuje admin-only /api/pipeline/pending-verifications dla delivery_lead i head_of_recruitment — gwarantowane… |
| [#40](#f40) | P2 | M | Frontend · UI | `frontend/src/components/v2/pages/AnalyticsDashboard.tsx:542` | 29 plików frontendu / 5734 LOC jest nieosiągalnych z jakiejkolwiek trasy; ~1000 LOC z tego osierocone w jednym PR-ze R… |
| [#47](#f47) | P2 | S | Frontend · UI | `frontend/src/app/settings/rate-benchmarks/page.tsx:30` | Ustawienia → Zaawansowane oferują kafelki rolom, które RequireRole na stronie docelowej odrzuca; fallback domyślnie je… |
| [#48](#f48) | P2 | S | Frontend · UI | `frontend/src/components/v2/forms/OnboardingRecruiterV2.tsx:89` | Lista rekrutacji w onboardingu nie ma gałęzi isError: każda awaria — w tym deterministyczne 403 dla dowolnej hybrydy h… |
| [#50](#f50) | P2 | S | Frontend · UI | `frontend/src/components/RequestHistorySection.tsx:133` | „Dodaj championa" (rekrutacja → Historia) inwaliduje `["kanban"/"job", <number>]`, podczas gdy strona rekrutacji cachu… |
| [#51](#f51) | P2 | S | Frontend · UI | `frontend/src/components/v2/shell/QuickActionsV2.tsx:88` | Globalne „+ Dodaj → Dodaj firmę" inwaliduje `["clients-v2"]`, czyli klucz bez producenta — katalog klientów (`["client… |
| [#52](#f52) | P2 | S | Frontend · UI | `frontend/src/components/contracts/ContractTerminationDialog.tsx:41` | Zakończenie kontraktu / aneks / edycja / usunięcie inwalidują martwy klucz `["contracts"]` — osierocony po skasowaniu … |
| [#56](#f56) | P2 | M | Frontend · UI | `frontend/src/components/v2/pages/ContractsListV2.tsx:71` | Globalny rejestr kontraktów wciąż używa martwej mapy statusów z kwietnia 2026 (`expiring`/`terminated`, bez `ending`),… |
| [#57](#f57) | P2 | M | Frontend · UI | `frontend/src/components/v2/pages/CandidateDetailV2.tsx:8` | TipTap/ProseMirror siedzi w bundlu trasy /candidates/[id], choć jego jedyny konsument wymaga trzech świadomych kroków … |
| [#58](#f58) | P2 | M | Frontend · UI | `frontend/src/components/AppShell.tsx:229` | Lokalny dla pliku FieldGroup w AppShell renderuje <label> jako rodzeństwo bez htmlFor, więc klik-w-etykietę-by-sfokuso… |
| [#59](#f59) | P2 | M | Frontend · UI | `frontend/src/components/contracts/ContractTerminationDialog.tsx:47` | ~19 ręcznie sklecionych szkieletów modali (zakończenie umowy, admin reset hasła, przedłużenie zamówienia, zamknięcie r… |
| [#62](#f62) | P2 | S | Frontend · UI | `frontend/src/app/clients/[id]/page.tsx:888` | Zwinięty panel "Statystyki współpracy" na domyślnej zakładce profilu klienta odpala niecache'owany 6-iteracyjny raport… |
| [#66](#f66) | P2 | S | Testy | `backend/tests/conftest.py:295` | Heurystyka conftestu oparta na NAZWIE fixture'a błędnie klasyfikuje in-process test ASGI jako live-server: wszystkie 6… |
| [#71](#f71) | P2 | S | Backend · API | `backend/app/api/admin_candidate_pii_orphans.py:113` | Raport o lukach usuwania danych nadal twierdzi, że na `contracts` jest CASCADE, które migracja 0225 zamieniła na SET N… |
| [#72](#f72) | P2 | S | Backend | `backend/app/main.py:643` | Produkcyjne `/openapi.json`, `/docs` i `/redoc` są publiczne i nieuwierzytelnione — 747 ścieżek, 876 schematów i 118 K… |
| [#73](#f73) | P2 | M | Backend · API | `backend/app/api/auth.py:633` | Produkcyjny `/openapi.json` jest publiczny i publikuje 118 641 znaków wewnętrznego uzasadnienia inżynierskiego — w tym… |
| [#74](#f74) | P2 | S | Backend · rdzeń | `backend/app/core/rate_limit.py:70` | `/openapi.json` jest nieuwierzytelniony i nielimitowany: ~20 ms synchronicznego `json.dumps` re-serializowanego na każ… |
| [#75](#f75) | P2 | S | Backend | `backend/app/main.py:318` | `/docs` i `/redoc` zwracają 200, ale renderują się pusto — własne CSP aplikacji zabija cały ich runtime, na fałszywej … |
| [#76](#f76) | P2 | S | Frontend · UI | `frontend/src/components/ContractInvoicesTab.tsx:34` | „Oznacz jako zapłaconą" stempluje `paid_date` ze zamrożonej na poziomie modułu, przesuniętej do UTC stałej — kolumna f… |
| [#77](#f77) | P2 | M | Backend · serwisy | `backend/app/services/competitions.py:112` | Podia konkursów kubełkują zdarzenia milestone'ów po miesiącu/kwartale UTC, podczas gdy własny panel KPI rekrutera kube… |
| [#78](#f78) | P2 | M | Backend · serwisy | `backend/app/services/dashboard_metrics.py:74` | `date.today()` porównywane z kolumną `timestamptz` kompiluje się do `$1::DATE` i jest rozwiązywane na północy UTC sesj… |
| [#83](#f83) | P2 | S | Frontend · UI | `frontend/src/components/v2/pages/B2BContractGeneratorV2.tsx:261` | Baner „ten klient ma specyficzne zapisy" duplikuje backendową tabelę needle'i klauzul i już się rozjechał: nazwy „E-Zd… |
| [#84](#f84) | P2 | S | Backend · serwisy | `backend/app/services/b2b_contract_generator/clause_overrides.py:33` | Matcher klauzul B2B nie normalizuje do NFC; dokładnie jeden needle („rehabilitacji osób niepełnosprawnych") zawiera zn… |
| [#85](#f85) | P2 | M | Backend · serwisy | `backend/app/services/b2b_contract_generator/docx_renderer.py:66` | Nakładanie override'ów klauzul nie ma kanału sukcesu: udokumentowany licznik z `apply_ops_docx` jest wyrzucany w docx_… |
| [#87](#f87) | P2 | S | Backend · serwisy | `backend/app/services/competitions.py:508` | Zwycięzca miesięcznej nagrody 1500 PLN jest wybierany przez nieoznaczony tie-break po porządku bajtowym nazwy, a potem… |
| [#90](#f90) | P2 | S | Frontend · UI | `frontend/src/components/v2/pages/CandidatesListV2.tsx:406` | Klucz sortowania "name" jest zaimplementowany w dwóch przeciwnych porządkach: `/api/candidates` sortuje po imieniu pod… |
| [#92](#f92) | P2 | M | Backend · API | `backend/app/api/dynareporter_mindy.py:235` | Dwa endpointy Claude'a w MINDY są żywe i stoją całkowicie poza systemem kwot AI — nie mają `AIFeatureKey`, więc główny… |
| [#94](#f94) | P2 | S | Backend · API | `backend/app/api/notes.py:364` | `POST /api/notes/{id}/link-job` obciąża `champion_draft` dwa razy na kliknięcie i jest jedynym miejscem wywołania kwot… |
| [#95](#f95) | P2 | M | Backend · serwisy | `backend/app/services/candidate_activity_summary_service.py:1132` | `candidate_activity_summary_service` nadal ręcznie klepie bramkę kwot AI poza `ai_feature()`, więc karta „Podsumowanie… |
| [#98](#f98) | P2 | S | Wtyczka | `extension/manifest.json:27` | Wtyczka deklaruje `scripting` i `activeTab`, których żadna linia nie wywołuje, oraz wildcard `https://*.dynaminds.pl/*… |
| [#99](#f99) | P2 | M | Wtyczka | `extension/src/content/linkedin-scraper.js:74` | Na Sales Navigatorze i Recruiterze scraper bierze PIERWSZĄ kotwicę `/in/` w całym dokumencie — brak zawężenia do karty… |
| [#101](#f101) | P2 | L | Backend · API | `backend/app/api/priority_work.py:768` | Cutover RBAC dashboardów z #1031 po cichu odciął konsolę Priority Work: 23 z 24 endpointów są dziś nieosiągalne z jaki… |
| [#102](#f102) | P2 | S | Frontend · UI | `frontend/src/components/v2/priority-work/JobPriorityContext.tsx:155` | Karta Priority Work na każdej stronie rekrutacji mówi rolom operacyjnym, że nie wolno im dodawać nowych kandydatów — o… |
| [#104](#f104) | P2 | S | Frontend · UI | `frontend/src/components/v2/priority-work/JobPriorityContext.tsx:58` | Karta Priority Work zamienia 403 z kontroli członkostwa w czerwony blok `role="alert"` „nie udało się wczytać" z przyc… |
| [#205](#f205) | P2 | M | CI/CD | `.github/workflows/uptime-probe.yml:46` | Trzynaście z czternastu checków `/api/health` nie ma żadnego automatycznego czytelnika — godzinowa sonda asertuje tylk… |
| [#206](#f206) | P2 | S | Backend · API | `backend/app/api/public_share.py:71` | `GET /api/public/champion-card/{token}` to jedyny publiczny endpoint w tym pliku bez rate limitu — bez uwierzytelnieni… |
| [#209](#f209) | P2 | M | Backend | `backend/requirements.txt:30` | Zero lockfile'a po stronie Pythona: każda zależność przechodnia backendu pływa, do tego jeden bezpośredni pływający za… |
| [#210](#f210) | P2 | S | Frontend · UI | `frontend/Dockerfile:6` | Produkcyjny obraz frontendu buduje się przez `npm install`, nie `npm ci` — lockfile, który CI egzekwuje, jest tylko po… |
| [#211](#f211) | P2 | S | Infra | `.gitleaks.toml:16` | gitleaks — bramka sekretów blokująca deploy — jest ślepy na ścieżki dwóch plików workflow, które obsługują realne pośw… |
| [#214](#f214) | P2 | L | Frontend · lib | `frontend/src/lib/api.ts:20` | src/lib/api.ts — jedyny, 6153-liniowy klient HTTP całego frontendu — ma 0,45% pokrycia funkcji, bo 51 ze 148 plików te… |
| [#215](#f215) | P2 | L | CI/CD | `.github/workflows/ci.yml:139` | 239 backendowych funkcji testowych jest wyłączonych z CI, 188 z nich w 17 plikach, o których wiadomo, że są czerwone —… |
| [#216](#f216) | P2 | S | CI/CD | `.github/workflows/ci.yml:267` | Job Trivy nie jest report-only, tylko report-donikąd: nie może paść, nie emituje artefaktu ani adnotacji, a po cichu f… |
| [#221](#f221) | P2 | M | Backend · serwisy | `backend/app/services/client_order_lines.py:186` | Nic w repo nie przypina ani nie weryfikuje collation produkcyjnego Postgresa, a każda lista poza jedną sortuje polskie… |
| [#222](#f222) | P2 | S | Backend · serwisy | `backend/app/services/ai_quota.py:172` | Każda funkcja AI na produkcji działa bez miesięcznego sufitu wydatków — zweryfikowane na żywo — a jedyną powierzchnią,… |
| [#223](#f223) | P2 | M | Wtyczka | `extension/manifest.json:27` | Wtyczka do przeglądarki, z której rekruterzy korzystają codziennie, ma zero CI, zero testów i dwa commity w historii, … |
| [#224](#f224) | P2 | L | Backend · tło | `backend/app/tasks/priority_work.py:298` | RECRUITMENT_PRIORITY_MODE='off' zatrzymuje tylko pętlę workera — wszystkie 22 endpointy priority-work zostają otwarte … |
| [#1](#f1) | P3 | S | Backend · serwisy | `backend/app/services/email.py:125` | Komentarz w `config.py:452` reklamuje kanał SMTP dla alertów post-interview T+45, który nigdy nie został podpięty; `se… |
| [#2](#f2) | P3 | S | Backend · serwisy | `backend/app/services/contract_lifecycle.py:300` | `contract_lifecycle.reopen_contract()` nie ma ani jednego wywołania — nie jest nawet importowana; naprawa `ended/endin… |
| [#3](#f3) | P3 | S | Backend · rdzeń | `backend/app/core/config.py:27` | `QDRANT_API_KEY` to martwa gałka konfiguracyjna — nigdy nie przekazywana do żadnej z 25 konstrukcji `QdrantClient`, a … |
| [#41](#f41) | P3 | S | Frontend · UI | `frontend/src/components/jobs/AiStatusBanner.tsx:29` | Domyślna wartość `manualSearchHref` w AiStatusBanner jest autoreferencyjna: banner renderuje się wyłącznie wewnątrz Ca… |
| [#54](#f54) | P3 | M | Frontend · UI | `frontend/src/app/jobs/[id]/page.tsx:785` | Martwe gałęzie degradacji w admin-only panelu legacy matchingu: testuje `search_type` „bm25"/„unavailable" oraz `meta.… |
| [#61](#f61) | P3 | S | Frontend · UI | `frontend/src/components/v2/pages/KanbanBoardV2.tsx:1573` | memo() na CandidateKanbanCard nigdy nie może zadziałać — toggleSelect nie jest opakowany, a trzy sąsiednie propsy to i… |
| [#65](#f65) | P3 | L | Frontend · UI | `frontend/src/components/v2/pages/CandidateDetailV2.tsx:2017` | Jedno zapytanie na profilu kandydata (dokumenty kontraktu, `CandidateDetailV2.tsx:2017`) renderuje przejściową awarię … |
| [#79](#f79) | P3 | S | Frontend · UI | `frontend/src/components/contracts/ContractEquipmentTab.tsx:53` | Sprzęt z terminem DZIŚ jest malowany jako po terminie od 02:00 czasu warszawskiego — data bez godziny parsowana jako p… |
| [#100](#f100) | P3 | S | Wtyczka | `extension/src/content/modal-host.js:299` | Backend dodaje `assignment_skipped_reason` właśnie po to, żeby popup przestał być cichym no-opem; wtyczka nigdy tego p… |
| [#103](#f103) | P3 | S | Frontend · UI | `frontend/src/components/v2/priority-work/PriorityRequestsPanel.tsx:348` | Panel priorytetów tylko dla DL oferuje „Oznacz jako zrealizowane" → `fulfilled`, czyli przejście, którego backend wpro… |

---

## Znaleziska

<a id="f23"></a>

### #23 · P0 · Analityka finansowa sumuje przeterminowane, cache'owane kolumny `contracts.rate_*` zamiast harmonogramów stawek, które sama eager-loaduje — a ponieważ `rate_client` ma dokładnie JEDNEGO zapisującego w całym backendzie, dzisiejsze MRR/marża na boardzie też są złe, nie tylko historia

nakład **M** · obszar **Backend · analityka** · **nie działa** · kategoria `broken`

`backend/app/analytics/metrics.py:518`

**Co to kosztuje.** Każda złotówka na zarządczej powierzchni finansowej — `/api/analytics/v1/finance/summary`, `/finance/trend`, `/finance/clients`, `/executive/board`, `/clients/{id}/finance` — jest liczona z `contracts.rate_client` / `contracts.rate_candidate`, czyli cache'owanych kolumn odświeżanych wyłącznie wtedy, gdy ktoś ZAPISZE kontrakt. Rejestr (`/api/contracts`), strona szczegółów kontraktu i tabela konsultantów w profilu klienta przeszły na stawki wyprowadzane z harmonogramów właśnie dlatego, że te kolumny kłamią; moduł analityki nie przeszedł. Dwie powierzchnie odpowiadają więc na to samo pytanie różnymi liczbami, a ta, którą właściciel zacytowałby na zarządzie, jest tą błędną. Kontrakt `meta/metrics` w `metrics.py:862` mówi czytelnikowi „Suma monthly_rate_client aktywnych (date-effective) kontraktów" — „date-effective" jest prawdą o tym, KTÓRE kontrakty się liczą, a fałszem o KWOCIE, jaką każdy wnosi, i to jest dokładnie ten rodzaj półprawdy w definicji, przez który nikt tego nie zauważa.

**Naprawa.** `_sum_finance` już dostaje `on`, a wywołujący już eager-loaduje wszystkie trzy harmonogramy — wszystko, czego trzeba, jest pod ręką. Zamień `c.monthly_rate_client` / `c.monthly_margin` na `c.monthly_rate(c.effective_client_rate(on))` i odpowiadającą stawkę kandydata, albo lepiej: zaimportuj `_effective_rate_fields` z `contracts.py` tak, jak robi to już `clients.py:51`, zawołaj z `on` i wyczytaj `monthly_rate_client` / `monthly_margin` ze zwróconego słownika, żeby była jedna implementacja zamiast dwóch. Potem popraw string definicji w `meta/metrics` w `metrics.py:862`, żeby mówił, że kwota też jest date-effective. To samo podstawienie dotyczy `reports.py:69-74` (`_monthly_rate_client` / `_monthly_margin` oba czytają zapisane kolumny), `contract_analytics.py:143-144` i `admin_clients_overview.py:172` — tamte agregaty SQL nie mogą wołać helpera w Pythonie, więc potrzebują udokumentowanej adnotacji, że są „na stan ostatniego zapisu", albo zmaterializowanej kolumny ze stawką obowiązującą.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 23` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f32"></a>

### #32 · P0 · `/jobs/{id}/pipeline-scores` reimplementuje regułę świeżości cache bez predykatu `scoring_algorithm_version`, więc po każdym bumpie wersji przelicza wiersze przestarzałe wersyjnie z wyzerowaną warstwą semantyczną (0 z 60 pkt) i nadpisuje je jako świeże pod nową wersją — zaniżony pierścień na kanbanie jest wtedy trwały i wycieka do każdego innego czytelnika tego klucza cache

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/recommendations.py:602`

**Co to kosztuje.** Każdy rekruter pracujący na pipelinie widzi trwale błędny pierścień dopasowania AI na kartach kanbanowych kandydatów, którymi aktywnie się zajmuje — zaniżony nawet o 60 ze 100 punktów, bo warstwa semantyczna (SEMANTIC_MAX = 60.0) daje 0. Błędna wartość jest zapisywana z powrotem do `candidate_job_match_scores` oznaczona jako świeża i nie-stale pod BIEŻĄCĄ wersją algorytmu, więc nic jej nigdy nie przeliczy: kolumna "Dopasowanie" na liście kandydatów i każdy późniejszy odczyt tej pary serwuje tę samą zatrutą liczbę. To jest żywe na prodzie w tej chwili — wbudowane domyślne wagi są częścią digestu `scoring_algorithm_version()`, a zmieniły się na 60/10/15/5/0/10 17-18.08, więc każdy wcześniejszy wiersz cache jest przestarzały wersyjnie i nie-stale, czyli dokładnie w stanie, który to wyzwala. Własny docstring endpointu w recommendations.py:565-571 obiecuje coś przeciwnego: "so the semantic layer is never silently zeroed regardless of the candidate's global rank, and we never persist a deflated score into the cache shared with /recommendations."

**Naprawa.** Dodaj `CandidateJobMatchScore.scoring_algorithm_version == scoring_algorithm_version()` do klauzuli WHERE w `cached_id_rows`, żeby definicja "cached" w endpoincie zgadzała się z definicją `bulk_get_or_compute`. Dla pewności: przekazuj `allow_cache_write=False` na każdej ścieżce, gdzie `similarity_map` nie pokrywa wszystkich ocenianych kandydatów — lustrzanie do tego, co `/recommendations` i `candidates.py:1616` już robią z tego samego powodu (M3-CACHE-01). Jednorazowy `UPDATE candidate_job_match_scores SET stale=true WHERE scoring_algorithm_version <> '<current>'` czyści wiersze już zatrute od 17-18.08. Obecnie nie ma ŻADNEGO testu na ten endpoint (`grep -rln "pipeline_match_scores" tests/` jest puste) — dodaj taki, który stempluje przestarzałą wersję i asertuje, że zapisany wiersz zachowuje niezerową warstwę semantyczną.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 32` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f201"></a>

### #201 · P0 · Kopia off-site nigdy nie została zweryfikowana: drill przywracania pada 4 tygodnie z rzędu (brak sekretów), a monitor świeżości jest wyłączony — ~136k CV bez potwierdzonej kopii [3 niezależne agenty doszły do tego samego]

nakład **M** · obszar **CI/CD** · **ryzyko** · kategoria `ops` · **rekonesans — nieweryfikowane adwersarialnie**

`.github/workflows/backup-drill.yml:71`

**Co to kosztuje.** NEXUS trzyma ~49k profili kandydatów i ~136k plików CV (~37 GB), które nie istnieją nigdzie indziej — `pg_dump` zachowuje wyłącznie `candidate_documents.storage_key`, czyli wskaźniki. W repo jest dowód na dokładnie zero udanych przywróceń end-to-end kopii off-site: `gh run list --workflow backup-drill.yml` pokazuje failure 2026-08-17, 2026-08-10, 2026-08-03 i 2026-07-27 — każdy run od czasu, gdy PR #924 (2026-07-27) wprowadził drill, który realnie pobiera, deszyfruje przez `age -d` i robi `pg_restore` prawdziwego artefaktu off-site. Log runu 31994028868 pokazuje, że `BACKUP_S3_ACCESS_KEY` i `BACKUP_S3_SECRET_KEY` rozwijają się do pustych stringów, a `gh secret list` na repo zwraca tylko `CLAUDE_CODE_OAUTH_TOKEN`, `COOLIFY_APP_UUID`, `COOLIFY_TOKEN`, `COOLIFY_URL` — `BACKUP_AGE_PRIVATE_KEY`, `BACKUP_S3_ACCESS_KEY` i `BACKUP_S3_SECRET_KEY` nie istnieją. Równolegle `gh variable list` pokazuje `BACKUP_MONITORING_ENABLED=false` (ustawione 2026-07-27), więc job `backup-freshness` w uptime-probe, który czyta `LATEST.json`, jest skipowany przy każdym godzinowym biegu. Komentarz w samym workflow mówi, że `LATEST.json` „nie miał ŻADNEGO czytelnika w całym repozytorium" — to nadal jest prawda. Czyli obie połówki siatki bezpieczeństwa (czy backup w ogóle powstaje? czy da się go odtworzyć?) są jednocześnie martwe.

**Naprawa.** Działanie operatorskie, nie zmiana w kodzie: (1) wygeneruj dedykowaną parę kluczy age dla drilla, dopisz jej publiczną połówkę do rozdzielanej przecinkami listy odbiorców w `backup/backup.sh` (dzięki czemu nic nie wymaga ponownego szyfrowania) i wstaw prywatną połówkę do sekretu repo `BACKUP_AGE_PRIVATE_KEY` — nigdy klucza głównego; (2) utwórz read-only application key w B2 ograniczony do `dynaminds-nexus-offsite` i ustaw `BACKUP_S3_ACCESS_KEY` / `BACKUP_S3_SECRET_KEY`; (3) odpal `gh workflow run backup-drill.yml` i przeczytaj `LATEST.json`, który wypisze — ten jeden bieg odpowiada, czy kopia off-site w ogóle istnieje; (4) przełącz `BACKUP_MONITORING_ENABLED=true`, żeby godzinowa kontrola świeżości przestała być skipowana. Do czasu, aż (3) zaświeci na zielono, traktuj backup off-site jako nieistniejący.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 201` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f4"></a>

### #4 · P1 · Sześć nocnych faz Traffita nadal używa `db.rollback()` na poziomie sesji per wiersz z jednym commitem po pętli — ten sam defekt, który naprawiono dla `workflows`/`candidates` — więc jeden zły wiersz po cichu kasuje wszystkie rekordy zapisane wcześniej w tej fazie, a liczniki nadal raportują je jako zapisane

nakład **M** · obszar **Backend · serwisy** · **nie działa** · kategoria `broken`

`backend/app/services/traffit/importer.py:1954`

**Co to kosztuje.** CLAUDE.md dokumentuje dokładnie ten defekt jako znaleziony i naprawiony dla fazy `workflows` („stary handler wołał `db.rollback()`, czyli rollback SESJI, a faza commituje raz na końcu — jeden zepsuty workflow kasował wszystkie zapisane wcześniej w tym biegu... `processed: 2, updated: 2, errors: 1` nie znaczyło «1 z 2 padł», tylko «0 z 2 zapisanych», 23 biegi z rzędu"). Naprawa przez SAVEPOINT (`async with self.db.begin_nested()`, `importer.py:1302` dla workflows, `:1624` dla candidates) nigdy nie została przeniesiona do pozostałych sześciu faz. Wszystkie sześć chodzą co noc: `_phase_plan` w `app/tasks/traffit_sync.py:505-533` wymienia `users`, `clients`, `contacts`, `jobs`, `talents`, `candidate_sources`, a każda z nich ma identyczny goły `await self.db.rollback()` w `except` per rekord, z jedynym `commit()` po pętli — `importer.py:1042` (clients), `:1089` (contacts), `:1243` (users), `:1954` (jobs), `:1998` (talents), `:3710` (candidate_sources). Stawką są rekrutacje, klienci, kontakty, konta rekruterów i atrybucja źródeł kandydatów — kręgosłup ATS-a. Gorsza od samej utraty jest jej niewidoczność: `progress.inserted`/`progress.updated` zostały już zinkrementowane dla wierszy, które rollback wyrzucił, więc `/api/admin/traffit/sync/status` raportuje je jako zaimportowane. Żywy prod pokazuje obecnie `traffit: degraded`, czyli błędy na poziomie wiersza W TYM pipelinie zachodzą właśnie teraz.

**Naprawa.** Owiń zapis per rekord w każdej z sześciu faz w `async with self.db.begin_nested():`, dokładnie tak jak już robią to `import_workflows` (`importer.py:1302`) i `import_candidates` (`:1624`), i wykorzystaj istniejący helper `needs_session_rollback(err, past_savepoint=...)` (`importer.py:662`) do decyzji, czy sesja naprawdę musi być podniesiona. Przenieś inkrementację liczników za moment, w którym savepoint się utrzymał — `import_workflows` już tak robi i wyjaśnia dlaczego w `:1324`. Dodaj test regresyjny, który przepuszcza przez każdą fazę dwa dobre wiersze i jeden zatruty, i asertuje, że oba dobre są obecne po `commit()`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 4` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f5"></a>

### #5 · P1 · Wywołania AI lecą wewnątrz otwartej transakcji DB wołającego: połączenie z puli i blokada wiersza `ai_usage_logs` są trzymane przez cały round-trip do Claude'a — serializując równoległe żądania AI jednego użytkownika i przypinając horyzont vacuum na 25 kolejnych wywołań LLM podczas backfillu CV

nakład **M** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk`

`backend/app/services/match_justification_service.py:508`

**Co to kosztuje.** `ai_feature` (`app/services/ai_quota.py:242-283`) woła `check_and_increment`, które wykonuje `pg_insert(AIUsageLog)...on_conflict_do_update` (`ai_quota.py:184-203`) w sesji WOŁAJĄCEGO i celowo nie commituje — docstring mówi to wprost: „The increment lives in the caller's session". Wywołanie do providera dzieje się potem wewnątrz tej samej otwartej transakcji, a commit jest w linii 528, po nim. `call_claude` ponawia `range(retries + 1)` = 3 próby (`claude_client.py:172`) przy `ANTHROPIC_TIMEOUT_SECONDS = 90.0` z `ANTHROPIC_MAX_RETRIES = 2` (`config.py:321-322`) plus backoff 1 s + 2 s, więc najgorszy przypadek to ~273 s. Przez całe to okno `AsyncSession` trzyma wypożyczone połączenie z puli, a Postgres trzyma blokadę wiersza na `(feature, user_id, period_start)`. Ten kształt dzieli siedem miejsc wywołań (`match_justification_service.py:508`, `champion_draft_service.py:484` i `:526`, `cv_parser.py:528`, `cv_field_backfill.py:253`, `admin_champion_ingest.py:136`, `talent_radar.py:235`); jedyną ścieżką, która zrobiła to dobrze, jest czat interaktywnego CV — commituje przed wywołaniem LLM (`interactive_chat.py:207-208`) — co pokazuje, że naprawa jest znana i po prostu nie została zastosowana gdzie indziej. Dwie konsekwencje: (a) pula to 20+40=60 połączeń na JEDNYM workerze uvicorna (`entrypoint.sh:5197`, bez `--workers`), więc ~60 równoległych żądań AI wyczerpuje ją, a każde inne żądanie w aplikacji — lista kandydatów, logowanie, ruchy w pipelinie — blokuje się wtedy na puli i wywala 500; (b) transakcja otwarta przez minuty przypina horyzont xmin całego klastra, więc autovacuum nie może odzyskać martwych krotek nigdzie, dopóki jakiekolwiek wywołanie AI jest w locie, a na tabeli takiej jak `candidates` (~57 tys. wierszy, stale aktualizowana) to dokładnie tak narasta bloat indeksów.

**Naprawa.** Obciążaj kwotę na dedykowanej, krótko żyjącej sesji, tak jak `index_outbox_service._enqueue_isolated` (`index_outbox_service.py:233`) już izoluje swój zapis, albo po prostu `await db.commit()` natychmiast po powrocie `check_and_increment` i przed `yield` — dokładnie to robi `interactive_chat.py:207-208`, a jego komentarz („commit od razu, żeby licznik nie przepadł przy późniejszym rollbacku ścieżki LLM") już to argumentuje. Potem upewnij się, że między tym commitem a wywołaniem providera nie leci żadne `db.execute` (w `interactive_chat.py` późniejszy odczyt `_history()` ponownie otwiera transakcję i ponownie przypina połączenie, więc ta ścieżka wymaga też przeniesienia odczytu nad commit). Dodaj test asertujący, że `db.in_transaction()` jest `False` w momencie wejścia do `call_claude`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 5` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f6"></a>

### #6 · P1 · Board i Sales liczą trend 12-miesięczny krokiem 30 dni — luty znika, sąsiedni miesiąc dubluje się co roku w marcu–maju; poprawna wersja istniała i została utracona w rewercie z 2026-07-15

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/reports.py:1541`

**Co to kosztuje.** Dwanaście miesięcy to nie 360 dni, więc `today.replace(day=1) - timedelta(days=i*30)` nie przesuwa się o jeden miesiąc kalendarzowy na iterację. Przeliczyłem tę arytmetykę dla każdego możliwego miesiąca raportowego 2026: dla `today` w marcu, kwietniu i maju dwanaście wyprodukowanych kubełków zawiera duplikat i całkowicie gubi jeden miesiąc. Dla 2026-03-15 seria to [2025-04 … 2025-12, **2025-12**, 2026-01, 2026-03] — grudzień pojawia się dwa razy, a **lutego 2026 nie ma**. Dla 2026-04-15 i 2026-05-15 dubluje się styczeń, a lutego brak. Ta sama zepsuta konstrukcja występuje dosłownie w drugim endpoincie, trendzie MRR w `report_sales` (`reports.py:432`), więc zarówno podsumowanie dla Rady Nadzorczej (`GET /api/reports/board`, ograniczone do Finance/Admin — `reports.py:1424-1428`, „Executive summary for the Supervisory Board (Rada Nadzorcza)"), jak i wykres MRR sprzedaży gubią ten sam miesiąc. W ATS-ie to znaczy, że placementy i przychód miesięczny za pełny miesiąc znikają z linii trendu prezentowanej radzie, a sąsiedni miesiąc jest liczony podwójnie — liczba idzie do rady nadzorczej i nie daje się uzgodnić z modułem finansów. Do tego każda z dwunastu iteracji odpala nieograniczony `select(Contract)`, który materializuje każdy nakładający się kontrakt jako pełne obiekty ORM (`reports.py:1558-1575` i `:1439-1456`), bez limitu i bez eager loadingu, więc raport to także 12 pełnych ładowań tabeli kontraktów plus round-trip `rates_to_pln` na każdy miesiąc.

**Naprawa.** Zastąp arytmetykę 30-dniową prawdziwym krokiem po miesiącach kalendarzowych — np. zbuduj kotwicę z liczb `(year, month)` i dekrementuj przez `divmod`, albo użyj obliczenia `month_end` już obecnego w pętli do cofania się. Wyciągnij to do jednego wspólnego helpera, żeby `reports.py:432` i `reports.py:1541` nie mogły się znowu rozjechać, i dodaj test tabelaryczny asertujący, że dla każdego z dwunastu możliwych miesięcy `today` wyprodukowana seria ma 12 różnych, kolejnych etykiet `YYYY-MM`. Przy okazji zastąp comiesięczne pełne ładowania `select(Contract)` jednym zgrupowanym agregatem SQL po całym 12-miesięcznym oknie.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 6` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f8"></a>

### #8 · P1 · Awaria Voyage/Qdranta po cichu zrzuca `/api/jobs/{id}/ai-matches` do rankingu po tagach na dowolnej 100-wierszowej próbce tabeli `candidates`, nie emitując żadnego `meta`, przez co gotowy już na stronie oferty baner „wyszukiwanie semantyczne niedostępne" jest martwym kodem, a awaria renderuje się albo jako nieoznaczona lista dopasowań, albo jako „Brak pasujących kandydatów w bazie"

nakład **M** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/matching.py:296`

**Co to kosztuje.** Podczas awarii Qdranta lub Voyage zakładka „Dopasowania" na rekrutacji renderuje listę kandydatów wziętych z góry tabeli `candidates` w kolejności fizycznej — a nie ranking — pod nagłówkiem „Znaleziono N pasujących kandydatów", przy zwyczajnym braku badge'a „Semantic AI". `match_score` dla tych wierszy to `len(matching)/len(req_set)`, a gdy oferta nie ma `required_skills` — proxy kompletności profilu (`_build_match_info`, `matching.py:120-131`), więc każdy wiersz i tak pokazuje wiarygodny procent. Rekruter nie ma jak odróżnić tego od prawdziwej listy dopasowań; następnym krokiem na tym ekranie jest „dodaj do pipeline'u", a po nim CV idzie do klienta. NEXUS miał już dwugodzinną awarię Qdranta, a bratnie ścieżki dowodzą, że zespół wie, iż trzeba to oflagować: `/jobs/{id}/recommendations` zwraca `meta.degraded`, a `compute_proposals.py:259-262` ustawia `snap.degraded = semantic_degraded` z komentarzem „so the UI can flag this ranking as a fallback instead of a healthy one". Ten endpoint nigdy tego nie dostał, a gałąź UI, która by to pokazała (`bm25` / `unavailable`), dopasowuje się do wartości, której `/ai-matches` nie potrafi wyprodukować.

**Naprawa.** Zwracaj `"meta": {"degraded": True}` (albo reużyj `RecommendationMeta`/`_meta()`, jak już robi `recommendations.py`) z gałęzi tag-fallback w `matching.py:426`, i dodaj gałąź badge'a `searchType === "tag_fallback"` w `frontend/src/app/jobs/[id]/page.tsx` obok istniejących `bm25`/`unavailable`. Jeszcze taniej: reużyj dokładnie semantyki `snap.degraded` z `compute_proposals.py`, żeby wszystkie trzy powierzchnie matchingu dzieliły jeden słownik degradacji zamiast trzech.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 8` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f9"></a>

### #9 · P1 · Jeden przejściowy błąd Voyage podczas zakładania kandydata trwale wypycha go z matchingu wektorowego: `False` z `embed_candidate` jest odrzucane, żaden wiersz outboxu nie powstaje (`enqueue()` jest no-opem przy wyłączonej fladze), a reconciler dryfu z założenia pomija rekordy nigdy nieindeksowane — więc nawet włączenie wszystkich flag `AI_INDEX_*` tego nie naprawi

nakład **M** · obszar **Backend · serwisy** · **nie działa** · kategoria `broken`

`backend/app/services/embedding_service.py:478`

**Co to kosztuje.** Kandydat, któremu nie udało się policzyć embeddingu, zostaje utworzony poprawnie, endpoint zwraca 201, a rekord normalnie pojawia się na liście kandydatów — będąc jednocześnie trwale nieobecnym w matchingu AI, `/recommendations`, wyszukiwaniu hybrydowym, Talent Radarze i skanie Marketplace, bo wszystkie te powierzchnie czytają id z Qdranta. `app/api/admin_index_coverage.py` opisuje konsekwencję wprost: "Rekord bez wektora nie jest 'gorzej dopasowany' — on po prostu nie bierze udziału... a rekruter nie ma jak zauważyć, że kogoś brakuje". Powstałą w ten sposób lukę zmierzono raz: 8 272 z 55 217 kandydatów. Nic nie zapobiega jej ponownemu narastaniu: ścieżka zapisu nie odróżnia sukcesu od porażki, żaden background job tego nie naprawia (worker outboxu i reconciler oba domyślnie `False`), żywy `/api/health` nie ma checku indeksu ani outboxu, a o ile oferty dostały endpoint naprawczy (`POST /api/phase3/jobs/embed-all`, phase3.py:500, selekcja po `Job.embedding_id.is_(None)`), o tyle kandydaci nie dostali żadnego — jedyna naprawa dla kandydatów to `scripts/reembed_collections.py`, wymagający shella na hoście produkcyjnym. Z włączonym outboxem kształt jest ten sam, tylko wolniejszy: `ev.status = "dead" if ev.attempts >= max_attempts else "failed"` (index_outbox_service.py:369) przy `AI_INDEX_MAX_ATTEMPTS=5`, a reconciler, który re-enqueue'owałby te wiersze, jest wygaszony osobną flagą.

**Naprawa.** Zrób porażkę trwałą, zamiast robić zwracaną wartość głośniejszą: przy `False` z `schedule_or_embed_candidate` zapisz wiersz, na którym system może zadziałać (bezwarunkowy enqueue do `index_outbox_events` albo stempel `needs_reindex`), żeby naprawa nie zależała od requestu, który padł. Dodaj kandydacki bliźniak `POST /api/phase3/jobs/embed-all` selekcjonujący po `Candidate.embedding_id.is_(None)` oraz klucz `index` w `/api/health` zasilany licznikami, które `admin_index_coverage.py` i tak już liczy — żeby luka była widoczna dla godzinowej sondy, a nie tylko dla ręcznego wywołania admina.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 9` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f11"></a>

### #11 · P1 · Zakładka "Umowy" na profilu klienta zamienia backendowe 403 w "Brak umów ramowych" — recruiter/sourcer/finance/nieprzypisany TAC dostają informację, że klient nie ma MSA, i zaproszenie do założenia duplikatu

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/FrameworkContractsTab.tsx:52`

**Co to kosztuje.** Rekruter albo sourcer otwierający dowolnego klienta i klikający "Umowy" dostaje pewnym siebie zdaniem informację, że klient nie ma umowy ramowej i że powinien założyć pierwszą. W biznesie body-leasingowym to zdanie jest różnicą między "możemy obsadzić tego klienta" a "nie możemy" — to dokładnie wzorzec awaria-jako-pusty-stan, przeciw któremu to repo ma już regułę, a tutaj pusty stan nie tylko ukrywa dane, ale wprost twierdzi nieprawdę handlową i zaprasza użytkownika do zduplikowania MSA, która już istnieje. Przycisk "Nowa umowa" nie ma żadnej bramki, więc użytkownik wypełnia formularz uploadu, a POST zwraca 403 (`DlAssignedOrAdmin`).

**Naprawa.** Dwie niezależne poprawki, obie małe. (1) Zabramkuj zakładkę: nadaj wpisowi `umowy-ramowe` capability tak, jak zabramkowane są `/cortex` i `/finance` — backendową prawdą jest `ClientAccess.can_view_legal_documents` (admin/HoR/DL/TAC + jawne przypisanie), więc zakładka powinna być odfiltrowana z `TABS` dla pozostałych, a przycisk "Nowa umowa" opakowany zgodnie z `DlAssignedOrAdmin`. (2) Daj zapytaniu gałąź `isError`: destrukturyzuj `isError`/`error` i renderuj osobne "Brak uprawnień do dokumentów prawnych tego klienta" dla 403 oraz "Ponów" dla wszystkiego innego — nigdy tekstu pustego stanu. Lista generatora B2B robi dokładnie to (osobna gałąź `isError` z przyciskiem ponowienia) i to jest wzorzec do skopiowania.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 11` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f12"></a>

### #12 · P1 · Panel cenników nigdy nie odzwierciedlił cutoveru finansowego z 04.08: Delivery Lead dostaje UI do dodawania/edycji/usuwania, które za każdym razem zwraca 403 (usuwanie po cichu), a 403 na odczycie renderuje się jako "Brak wpisów cennika" — podczas gdy finance, jedyna autoryzowana rola nie-admin, nie dostaje żadnych kontrolek

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/RateCardsTab.tsx:166`

**Co to kosztuje.** Delivery Lead otwiera zakładkę "Umowy" klienta, rozwija "Cennik (rate cards)", widzi pusty cennik, klika "Dodaj wpis cennika", wypełnia widełki stawek kandydata/klienta dla roli i zapisuje — i za każdym razem dostaje `Request failed with status code 403` w boksie błędu. Cennik jest wejściem do auto-podpowiedzi używanej przy tworzeniu kontraktu, więc praca po prostu przepada. Równocześnie rola Finance, czyli jedyna nie-adminowa rola, którą backend faktycznie autoryzuje do tych danych, w ogóle nie widzi przycisku. Obie połówki lustra są błędne, w przeciwnych kierunkach.

**Naprawa.** Zastąp ręcznie pisaną listę ról tym samym źródłem prawdy, którego używa backend. Store auth już wystawia `hasAnalyticsCapability(user, "manage_finance")` / `"view_finance"` (frontend/src/store/auth.ts) — zabramkuj cały blok `<details>` na `view_finance`, a kontrolki dodawania/edycji/usuwania na `manage_finance`, i wyrzuć literał `["admin","delivery_lead"]`. Dodaj gałąź `isError`, żeby 403 na odczycie mówiło "Brak uprawnień do cennika" zamiast "Brak wpisów cennika". Rozważ dodanie wpisu capability (np. `client.rate_card.manage`) do `lib/capabilities.ts`, żeby ta lista przestała być szóstą prywatną kopią.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 12` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f15"></a>

### #15 · P1 · `POST /api/auth/refresh` przyjmuje 30-dniowy refresh token jako parametr query w URL, a własny filtr redakcji logów w repo NIE maskuje `refresh_token=` (`\b` przed `token` nie może dopasować się po podkreślniku), więc access log uvicorna zapisuje odnawialną, pełnouprawnioną sesję ATS dosłownie — na żywej ścieżce używanej przez rozszerzenie LinkedIn, nie na martwej

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/auth.py:492`

**Co to kosztuje.** Poświadczenie o 30-dniowym czasie życia (`REFRESH_TOKEN_EXPIRE_DAYS: int = 30`, backend/app/core/config.py:19), które wydaje 8-godzinne access tokeny do pełnej sesji ATS, jest transportowane w URL — gdzie ląduje w linii access loga uvicorna, w historii przeglądarki i w każdym payloadzie Referera lub raportowania błędów, który przechwytuje URL-e requestów. Repo już rozumie dokładnie to zagrożenie: usunięto wariant CloudTalka `POST /api/calls/webhook/{token}` właśnie dlatego, że wstawienie signing secretu w ścieżkę URL wycieka go do access logów Cloudflare/Traefika. To samo rozumowanie stosuje się tutaj, a własny access log uvicorna — który idzie na stdout kontenera, potem do json-file, potem do Grafana Loki zgodnie ze standardem observability — zawiera query string dosłownie.

**Naprawa.** Najmniejsza poprawna zmiana: przenieś token do body — jednopolowy model Pydantic (`class RefreshRequest(BaseModel): refresh_token: str`) przyjmowany jako `payload: RefreshRequest`, co jest prostą podmianą, bo nie ma wywołującego, którego by to zepsuło. Potem zdecyduj, czy ten flow ma w ogóle istnieć: jeśli produkt nie używa refresh tokenów, przestań zwracać `refresh_token` z `/login` i `/exchange` i usuń trasę; jeśli ma używać, dodaj rotację (unieważnienie przedstawionego tokena, wykrywanie ponownego użycia) oraz `POST /api/auth/logout`, który stempluje `tokens_valid_after = now()`, żeby użytkownik mógł realnie zakończyć własną sesję.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 15` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f16"></a>

### #16 · P1 · Safety-net `CREATE INDEX CONCURRENTLY` w entrypoincie nie ma odzyskiwania po nieprawidłowym indeksie — anulowany build jest trwały, bo `IF NOT EXISTS` go pomija, a 4 UNIQUE indeksy częściowe z tej listy niosą inwarianty biznesowe (jedno główne CV na kandydata, jeden bieżący miesiąc finansowy), które raport schema-drift liczy jako obecne niezależnie od `indisvalid`

nakład **M** · obszar **Schemat / boot** · **ryzyko** · kategoria `risk`

`backend/entrypoint.sh:4913`

**Co to kosztuje.** Komentarz opisuje model odzyskiwania — "nieudany indeks powtórzy się przy następnym starcie" — i dla CONCURRENTLY to nieprawda. PostgreSQL zostawia INVALID index, gdy build CONCURRENTLY zostanie anulowany albo padnie; `IF NOT EXISTS` widzi wtedy nazwę relacji i pomija go na zawsze. Czyli jedyny tryb awarii, który timeout miał przetrwać, jest dokładnie tym, który staje się trwały. Dwa koszty. Wydajność: planner nigdy nie użyje nieprawidłowego indeksu, więc np. `ix_candidates_availability_status` albo `ix_notifications_related_entity_id` po cichu przestają istnieć, a zapytania listy kandydatów / powiadomień spadają do sequential scanów po ~49k kandydatów. Integralność: cztery z 44 są UNIQUE i niosą inwarianty biznesowe — `ux_candidate_documents_active_primary_cv` (dokładnie jedno główne CV na kandydata, przy ~136k dokumentów), `uq_finance_import_runs_current_period` (dokładnie jeden bieżący miesięczny import finansowy), `ux_client_tac_one_first_priority_client`, `ux_user_cc_one_primary`. Nieprawidłowy indeks unikalny nie wymusza niczego, więc duplikaty mogą narastać miesiącami — kandydat z dwoma "głównymi" CV oznacza, że do klienta idzie złe CV, a dwa wiersze `status='current'` dla jednego miesiąca oznaczają, że moduł Finanse ma dwie konkurencyjne prawdy o wyniku tego miesiąca. Nic tego nie ujawnia: wyjątek jest połykany do kontenerowego `print()` (docker-compose.yml:189 bramkuje profilem shipper logów Alloy, więc ten stdout niekoniecznie gdziekolwiek trafia), a jedyne narzędzie, które mogłoby to wykryć, `_actual_indexes` w backend/app/api/admin_schema_drift.py:151-166, selekcjonuje `ix.indisunique` z `pg_index`, ale nigdy nie filtruje po `ix.indisvalid` — więc nieprawidłowy indeks liczy się jako obecny, a raport mówi o zerze brakujących indeksów.

**Naprawa.** Trzy małe zmiany. (1) Przed pętlą `_INDEX_STATEMENTS` najpierw zrób DROP każdego nieprawidłowego indeksu po nazwie: zapytaj `SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE NOT i.indisvalid` i wydaj `DROP INDEX CONCURRENTLY IF EXISTS <name>` dla każdego, który występuje w `_INDEX_STATEMENTS`, żeby ponowienie obiecywane przez komentarz faktycznie następowało. (2) Dodaj `AND ix.indisvalid AND ix.indisready` do zapytania po `pg_index` w admin_schema_drift.py:157, żeby nieprawidłowy indeks był raportowany jako brakujący — endpoint już modeluje to poprawnie dla dwóch sond podsystemowych w app/main.py:2044 i :2481, to ten sam predykat. (3) Podnieś albo zdejmij `statement_timeout` konkretnie dla CONCURRENTLY (ogranicza build, który z założenia ma czekać), albo zostaw ograniczenie, ale zapisuj porażkę gdzieś, gdzie ktoś to czyta — minimalnie dodaj liczbę nieprawidłowych indeksów do `/api/health/deep`, żeby zepsuty build zapalał następny deploy na czerwono.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 16` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f17"></a>

### #17 · P1 · Faza DDL przy starcie w `entrypoint.sh` wykonuje 500+ instrukcji biorących zamki (253 `ALTER TABLE`, 210 zwykłych `CREATE INDEX`, 55 `ADD CONSTRAINT`) bez `lock_timeout` — jeden kolidujący zamek zawiesza boot kontenera bez końca, a żaden healthcheck tego nie zauważy

nakład **S** · obszar **Schemat / boot** · **ryzyko** · kategoria `ops`

`backend/entrypoint.sh:4892`

**Co to kosztuje.** Ten sam plik zawiera już i diagnozę, i lekarstwo — zastosowane w dwóch miejscach i nigdzie indziej. `entrypoint.sh:4989-4996` brzmi: „Wcześniej całość leciała w jednej transakcji bez lock_timeout, a ALTER TABLE ... ADD CONSTRAINT bierze ACCESS EXCLUSIVE na gorącym recruitment_processes. Na obciążonej produkcji potrafił więc czekać bez końca — a czekając w kolejce po ten zamek blokował KAŻDEGO czytelnika tabeli. To nie jest awaria, tylko zwis, więc `|| echo ... continuing` na dole nigdy by go nie złapał." To jest dokładny opis zagrożenia, a dwa bloki, które ustawiają `SET LOCAL lock_timeout`, to `entrypoint.sh:4860` (jeden `ALTER` na `candidates`) i `:5085` (blok FK dla priority-work). 463 instrukcje w `_COLUMN_STATEMENTS` plus 55 kolejnych w `_CONSTRAINT_STATEMENTS` nie dostają żadnego z nich. Policzyłem cele `ALTER TABLE`: `candidates` 32, `b2b_generated_contracts` 17, `client_orders` 16, `contracts` 12, `client_order_groups` 12, `recruitment_processes` 11, `calls` 10, `notes` 7, `clients` 7, `jobs` 6, `users` 6. Każda z nich bierze ACCESS EXCLUSIVE nawet wtedy, gdy jest no-opem — PostgreSQL zakłada zamek zanim wyliczy `IF NOT EXISTS`. Gorzej: 210 instrukcji w tej samej nieobjętej timeoutem fazie to zwykłe `CREATE INDEX` (bez CONCURRENTLY), w tym 5 na `candidates`, 5 na `notes` i powyższe indeksy analityczne na `candidate_stages`; zwykły `CREATE INDEX` trzyma SHARE przez cały czas budowy, co blokuje każdy zapis do tabeli pipeline'u. To leci przy każdym deployu, a Coolify robi rolling update, więc stary kontener przez cały ten czas obsługuje rekruterów.

**Naprawa.** Jedna linia na fazę. Zaraz po `conn = await asyncpg.connect(url)` w `entrypoint.sh:4885` wykonaj `SET lock_timeout = '3s'` (i opcjonalnie `SET statement_timeout = '60s'`), żeby instrukcja DDL trafiająca na kontencję poddała się zamiast formować kolejkę; istniejący per-instrukcja `except Exception … print(...)` już toleruje wynikające z tego `LockNotAvailable`, a instrukcja ponowi się przy następnym boocie — to jest dokładnie model odzyskiwania, który ten plik zakłada wszędzie indziej. Zresetuj oba przed fazą `_INDEX_STATEMENTS`, gdzie wartość 120 s jest celowa. Osobno: 210 zwykłych `CREATE INDEX IF NOT EXISTS` siedzących w `_COLUMN_STATEMENTS` należy do `_INDEX_STATEMENTS` z CONCURRENTLY, tak jak napisane są 44 już tam obecne.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 17` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f19"></a>

### #19 · P1 · Przypomnienie T-15 o rozmowie jest dostarczalne tylko w 120-sekundowym oknie kwalifikowalności na zdarzenie, więc każda przerwa backendu dłuższa niż 2 minuty (każdy redeploy Coolify, udokumentowany jako „4-6 min cold") bezpowrotnie gubi przypomnienia dla zdarzeń startujących 14-16 min później — bez nadrabiania, bez fallbacku mailowego, bez wpisu w logu

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/calendar.py:1054`

**Co to kosztuje.** Przypomnienie jest ograniczone z OBU stron (`start_time >= now+14min AND start_time <= now+16min`). Gdy czas startu zdarzenia spadnie poniżej `now+14min`, nie może już nigdy wrócić do okna, `reminder_sent_at` zostaje NULL na zawsze, a rekruter po prostu nigdy nie dostaje powiadomienia „Za 15 minut: <tytuł>". `_dispatch_reminder` jest jedynym nadawcą — nie ma fallbacku mailowego ani sweepu nadrabiającego. Restarty backendu są częste (Coolify przebudowuje przy każdym pushu na main; `git log origin/main` pokazuje 5-50 commitów dziennie), a każdy restart jest wolny: `entrypoint.sh` ma 5197 linii i wykonuje `alembic upgrade heads` plus dużą siatkę bezpieczeństwa DDL plus seedowanie przed `exec uvicorn` w linii 5197. Każde takie okno restartu po cichu połyka przypomnienia o rozmowach zaczynających się 14-16 minut później. Dla ATS-a to jest powiadomienie, na którym rekruterzy polegają, żeby zdążyć na rozmowę z klientem.

**Naprawa.** Zrób dolną granicę otwartą i pozwól trwałemu stemplowi `reminder_sent_at` robić deduplikację, do której i tak został zbudowany: `start_time <= now + 16min AND start_time > now` (opcjonalnie `>= now - grace`, żeby zdarzenie, które wystartowało w trakcie długiego restartu, dawało spóźnione powiadomienie „rozmowa właśnie się zaczęła" zamiast ciszy). `FOR UPDATE SKIP LOCKED` w `_dispatch_reminder` już gwarantuje at-most-once, więc poszerzenie skanu niczego nie zduplikuje.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 19` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f20"></a>

### #20 · P1 · Nic w systemie nie odróżni świeżego kursu NBP od sprzed miesięcy: każda nieudana pobranie kończy się jako `logger.warning` (poniżej progu ERROR dla zdarzeń Sentry), `fx_age_days` nie ma ani jednego wywołania, `/api/health` nie ma checku fx, a obie ścieżki odczytu raportują nieograniczenie stary kurs jako znaleziony — więc faktury w EUR/USD/GBP i sumy finansowe są sumowane do PLN po zamrożonym kursie i oznaczane jako kompletne

nakład **M** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk`

`backend/app/services/fx_service.py:198`

**Co to kosztuje.** `fx_refresh_loop` jest jedynym zapisującym do `fx_rates`. Wołana przez nią funkcja zwraca 0 na każdej ścieżce błędu — HTTP inne niż 200, dowolny wyjątek, payload niebędący niepustą listą, brakujący `effectiveDate` (te dwa ostatnie wracają w ogóle bez logowania) — więc gałąź `except` pętli jest nieosiągalna, a pętla nie umie odróżnić „NBP nie opublikował nic nowego" od „NBP jest nieosiągalny od miesiąca". Po stronie odczytu `get_rate_to_pln` bierze najnowszy wiersz z `effective_date <= target` niezależnie od wieku i zwraca `rate_found=True`; tylko całkowity brak jakiegokolwiek wiersza dla waluty degraduje do 1:1 z flagą `fx_missing`. Jedyny helper napisany po to, żeby to ujawniać — `async def fx_age_days(db, currency)` w `fx_service.py:178` — ma **zero wywołań w całym repozytorium** (zweryfikowane grepem po `app/`), a `/api/health` nie ma checku `fx`. Konsumenci to powierzchnie pieniężne: `api/invoices.py:203` (sumy faktur widoczne dla klienta i DSO per klient), `api/reports.py:391/463/496`, `api/contract_analytics.py:73` oraz `analytics/metrics.py:506` (udokumentowane w `metrics.py:474` jako kanoniczne sumowanie finansów). Dla agencji body-leasingowej z kontraktami w EUR/USD po cichu zamrożony kurs EUR/PLN zafałszowuje każdą marżę i każdą sumę faktury w obcej walucie o tyle, o ile kurs zdążył odjechać.

**Naprawa.** Niech `fetch_and_store_nbp_today` zwraca wynik, który wywołujący może ocenić (albo rzuca przy awarii transportu/kształtu) i zapisuj `last_successful_fetch_at`. Następnie (a) dodaj wpis `fx` do checków `/api/health`, który przechodzi w `degraded`, gdy najnowsza `FxRate.effective_date` jest starsza niż N dni roboczych — funkcja sondująca `fx_age_days` już istnieje i potrzebuje tylko wywołania; (b) spraw, żeby `get_rate_to_pln`/`rates_to_pln` zwracały `found=False` (albo osobne `stale=True`) po przekroczeniu sufitu przeterminowania, żeby istniejąca instalacja `fx_incomplete`/`fx_missing` w `invoices.py` i `metrics.py` się zapaliła zamiast po cichu wyceniać po starym kursie.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 20` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f24"></a>

### #24 · P1 · Zakładka Analityka w profilu klienta liczy konsultantów tylko po `status == active`, więc każdy konsultant w swoich ostatnich 30 dniach znika z obu liczników — „Konsultanci aktywni" i „zakończonych" — a zakładka Profil tej samej strony ich liczy

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/my_clients.py:389`

**Co to kosztuje.** `GET /api/my-clients/{client_id}/dashboard` to własny widok Delivery Leada na portfel, za który odpowiada. Obie jego nagłówkowe liczby — `active_consultants` oraz `monthly_margin_total` / `monthly_margin_pct` — są liczone regułą, która nie istnieje nigdzie indziej w kodzie: dokładnie `status == active`, plus cache'owane kolumny stawek. Piętnaście innych miejsc w backendzie używa `status.in_((active, ending))` na pytanie „czy to zaangażowanie jest żywe", w tym profil klienta, do którego DL dochodzi klikając z tej właśnie karty. Zacytowany wyżej komentarz z `clients.py` jest lekarstwem na bug ze stałą kolumną, zapisanym, w bratnim pliku — a identyczny defekt jest tu wciąż żywy.

**Naprawa.** Dwie zmiany klasy „jedna linia" w tym samym bloku. (1) Poszerz predykat do `if contract.status not in (ContractStatus.active, ContractStatus.ending): continue` i zmień `active_consultants`, żeby liczył oba statusy — zgodnie z `contract_service.py:57` `_LIVE_STATUSES`, która już istnieje jako kanoniczna krotka i którą wystarczy tu zaimportować. (2) Dodaj trzy `selectinload` do `select(Contract)` w liniach 381-385 i zamień `contract.monthly_margin` na `_effective_rate_fields(contract, date.today())["monthly_margin"]`, dokładnie jak robi `clients.py:51/468`. Zwróć uwagę, że zapytanie ładuje też wszystkie kontrakty klienta (szkice, zakończone, unieważnione) i filtruje w Pythonie — zepchnięcie filtra statusu do klauzuli WHERE naprawia to przy okazji.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 24` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f25"></a>

### #25 · P1 · /ai-matches buduje swoje chipy skilli ✓/✗ wyłącznie z `candidate.skills` — pustego dla 49 440 z 49 802 kandydatów na prodzie — więc wymagania renderują się na czerwono pod wynikiem 0.94, a ta sama reguła zamienia awarię Qdranta/Voyage w "Brak pasujących kandydatów w bazie"

nakład **M** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/matching.py:107`

**Co to kosztuje.** `GET /api/jobs/{job_id}/ai-matches` zwraca `matching_skills` i `gaps`, a `frontend/src/app/jobs/[id]/page.tsx:903-905` renderuje je jako zielone/czerwone chipy pod każdym wierszem kandydata na stronie rekrutacji. Ranking, w którym te wiersze stoją, pochodzi z Qdranta + rerank Voyage po `_build_candidate_text`, które zwija w sobie `raw_cv_text[:3000]`, `verified_tech`, `experience`, `ai_summary` i `tags` (embedding_service.py:342-419). Chipy biorą się wyłącznie z `candidate.skills`. Te dwie rzeczy nigdy nie musiały się zgadzać i się nie zgadzają: silnik rankuje po CV, a chipy czytają kolumnę, którą scoring service dokumentuje jako pustą dla ~99% kandydatów zaimportowanych z Traffita. Reguła dopuszczalności na dokładnie tym endpoincie została ujednolicona z `/recommendations` 2026-08-20 właśnie z tego powodu — "Same engine, same page, two different containment rules" (matching.py:315-321). Reguła skilli to ten sam defekt, jedną funkcję niżej, wciąż nienaprawiony.

**Naprawa.** Usuń `_normalize_skill`, `_extract_skills` i `_canon_skill` z matching.py i przepuść `_build_match_info` przez regułę samego silnika: `canonical_skill_names(candidate.skills) + canonical_skill_names(getattr(candidate, "verified_tech", None)) + _skills_from_cv_extracted(candidate)` po stronie kandydata i `canonical_skill_names(required_skills)` po stronie rekrutacji, żeby obie strony siedziały w tej samej przestrzeni aliasów, a `_candidate_has_skill` stało się zwykłym sprawdzeniem przynależności do zbioru. `ALIAS_MAP` jest już nawadniany na starcie przez `skill_taxonomy_loader.refresh_alias_map` (main.py:493-500), więc nie trzeba ładować niczego nowego. Osobno: gałąź tag-fallback nie może przedstawiać wyniku zdegradowanego jako pustego — zwracaj flagę `degraded: true` obok `search_type: "tag_fallback"` i niech strona rekrutacji renderuje baner w stylu `isError`, który już ma, tak jak talent_radar robi to z `meta.degraded`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 25` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f27"></a>

### #27 · P1 · Tylko profil klienta wyprowadza stawki z harmonogramów z datami obowiązywania; analityka, raporty Board/Sales, /my-clients i admiński przegląd klientów sumują cache'owane kolumny `contracts.rate_*`, których nic nie odświeża w dniu wejścia w życie zaplanowanego kroku — więc ten sam kontrakt raportuje dwie różne wartości MRR/marży, a żywe miesiące trendu MRR są wycenione po dzisiejszej stawce

nakład **L** · obszar **Backend · analityka** · **nie działa** · kategoria `broken`

`backend/app/analytics/metrics.py:518`

**Co to kosztuje.** CLAUDE.md dokumentuje, że cache'owana kolumna "niesie wartość zapisaną przy ostatnim ZAPISIE kontraktu, więc stawka progresywna albo aneks z datą, która już nadeszła, pokazywały tu STARĄ kwotę — a wraz z nią złą marżę i zaniżone »Aktywne MRR«". Ta naprawa trafiła na dokładnie jedną powierzchnię: profil klienta (`clients.py:468` / `:527`). `_effective_rate_fields` ma w całym backendzie tylko dwóch importerów — `contracts.py` i `clients.py`. Analityka (`/api/analytics/v1/finance/summary|trend|clients`), raport Board, raport Sales i raport trendu klienta nadal czytają nieaktualną kolumnę, więc dashboardy Zarządu/Finansów nie zgadzają się z profilem klienta dla tego samego kontraktu. Gorzej: nic nigdy nie odświeża tej kolumny w dniu wejścia kroku w życie: `contract.rate_client = contract.effective_client_rate(date.today())` wykonuje się wyłącznie wewnątrz handlerów PATCH/aneksów (`contracts.py:2554-2555`, `:1516`, `:1141`), a żaden background task tego nie zapisuje — grep po zapisujących zwraca tylko te handlery. Drabinka stawek progresywnych rozpisana raz przy zakładaniu kontraktu jest więc błędna od kroku 2 wzwyż, na zawsze, na każdym dashboardzie finansowym.

**Naprawa.** Spraw, żeby `_sum_finance` brało stawkę na punkt w czasie: zastąp `c.monthly_rate_client` / `c.monthly_margin` przez `c.monthly_rate(c.effective_client_rate(on))` i odpowiadającą stawkę kandydata (harmonogramy są już eager-loadowane, więc bez dodatkowego zapytania i bez ryzyka MissingGreenlet). Zrób to samo w `reports.py` w `_monthly_rate_client` / `_monthly_margin` — ale tam zapytania o kontrakty (np. reports.py:440) muszą najpierw dostać trzy `selectinload`, inaczej resolver zrobi lazy-load w async i zwróci 500 bez CORS. Potem usuń `Contract.monthly_rate_client` / `monthly_rate_candidate` / `monthly_margin` całkiem albo przemianuj je na `*_cached_*`, żeby żadne nowe miejsce wywołania nie trafiło przypadkiem na nieaktualną ścieżkę; test kontraktowy może asertować, że `_effective_rate_fields` (albo równoważny resolver) jest jedynym źródłem stawek osiągalnym z `app/analytics` i `app/api/reports.py`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 27` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f28"></a>

### #28 · P1 · Kanoniczny filtr MRR to negatywne `status != draft`, które po cichu wpuszcza `ready_for_signature` i `void` — zasila ŻYWY kafel MRR w `/api/dashboard/v2/finance` i nie zgadza się z pozytywną allowlistą, której `reports.py` używa do tej samej liczby

nakład **S** · obszar **Backend · analityka** · **nie działa** · kategoria `broken`

`backend/app/analytics/metrics.py:452`

**Co to kosztuje.** `void` to udokumentowany soft-delete dla wykonanych kontraktów ("The safe alternative to a hard DELETE"), a `ready_for_signature` jest w modelu wprost opisany jako "A NON-active gate: an unsigned contract may never skip straight to `active`". Oba zostały wprowadzone 2026-07-22 (commit 37e1bebb); filtr `!= draft` był ostatnio ruszany 2026-07-21 (commit 844a341d, refaktor point-in-time) i nigdy nie został do niego wrócony. Ponieważ `void_contract` celowo zachowuje `start_date`/`end_date`, anulowany kontrakt, którego okno nadal obejmuje dziś, spełnia wszystkie cztery predykaty i jest wliczany do MRR, marży miesięcznej, `active_contracts`, `clients.active` oraz mianownika bench/utilization — czyli tych samych błędnych liczb, z których czyta się dashboardy Finansów i Zarządu. To nie jest jeden endpoint: identyczny predykat występuje w metrics.py:88, :98, :109, :452, :563, :573, :640, :789 oraz w dashboard_metrics.py:45. `dashboard_metrics.py` przeczy sam sobie wewnątrz jednej funkcji — `clients_active` używa `!= draft`, a `contracts_active` pięć linii niżej używa `== active`.

**Naprawa.** Zastąp każde `Contract.status != ContractStatus.draft` w `app/analytics/metrics.py` i `app/services/dashboard_metrics.py` pozytywną allowlistą — jednym `REVENUE_STATUSES = (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)` na poziomie modułu (dokładnie ten zbiór, którego `reports.py:446-452` już używa do swojego trendu MRR) — żeby przyszły członek enuma nie mógł dołączyć do ścieżki pieniędzy przez przeoczenie. Przy okazji uzgodnij `dashboard_metrics.clients_active` (`!= draft`) z `contracts_active` (`== active`), żeby jedna funkcja przestała nieść dwie definicje "aktywnego". Dodaj test regresyjny asertujący, że kontrakt `void` z żywym oknem dat wnosi zero do `finance_summary`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 28` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f29"></a>

### #29 · P1 · Admiński przegląd klientów liczy konsultantów i marżę tylko po `status == active` — a dzienny cron promuje active→ending na 30 dni przed końcem, więc zarówno `/` (linia 164), jak i `/by-dl` (linia 305) po cichu gubią każdego konsultanta na czas w jego ostatnim miesiącu, a klient, którego cała obsada jest `ending`, renderuje marżę jako "—"

nakład **M** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/admin_clients_overview.py:164`

**Co to kosztuje.** `_promote_statuses` chodzi raz dziennie i przestawia `active → ending`, gdy tylko `end_date - today <= 30`. Konsultant w ostatnim miesiącu nadal pracuje i nadal fakturuje, ale `/api/admin/clients-overview` i `/by-dl` (ten sam defekt w linii 303) przestają go liczyć w ogóle — `active_consultants` spada o jeden, a `monthly_margin_total` traci całą jego marżę. Profil klienta (`clients.py:439`) i baner wygasających (`contracts.py:1297`) używają `in_((active, ending))`, więc admiński przegląd przeczy ekranowi per klient, który ten sam admin otwiera chwilę później. Repo już się na tym uczyło gdzie indziej — `dashboard_metrics.py:59-62` niesie komentarz "active + ending: the cron promotes active→ending at the 30-day mark, so an active-only count under-reports (often to 0)". Ta powierzchnia nigdy nie dostała tej poprawki. Jest osiągalna i używana: `/settings/clients-overview` oraz panel Insights → Klienci czytają z niej (`frontend/src/lib/api/dlPortal.ts:435`). Wtórny defekt w tym samym bloku: czyta nieaktualne kolumny `rate_client`/`rate_candidate` (rodzina znaleziska #1), a `rev_lookup` sumuje `ClientOrder.total_value` przez różne waluty bez przeliczenia FX, co `reports.py` wprost nazywa produkowaniem "both wrong totals and a wrong ranking".

**Naprawa.** Zmień obie klauzule `.where(Contract.status == ContractStatus.active)` (linie 164 i 303) na `.where(Contract.status.in_((ContractStatus.active, ContractStatus.ending)))`, zgodnie z `clients.py:439`. W tym samym przejściu wybieraj kontrakty (nie gołe kolumny) z trzema `selectinload` i przepuść marżę przez `_effective_rate_fields`, żeby ten ekran przestał przeczyć profilowi klienta również co do stawki, nie tylko co do liczby osób; a `total_value` per waluta przepuść przez `rates_to_pln` przed sumowaniem, reużywając `reports._fold_finance_pln`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 29` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f30"></a>

### #30 · P1 · Zduplikowane wiersze konsultanta w jednym arkuszu MD nadpisują się zamiast sumować — odejmowane jest tylko MD z ostatniego wiersza; ten sam defekt powtarza się w assign_row, podczas gdy kolumna faktur tego samego wiersza buforuje i sumuje

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/md_consumption.py:344`

**Co to kosztuje.** Fakturowa połowa tej pętli buforuje do `pending_invoices` i zapisuje jeden zsumowany wiersz na (linia, miesiąc); połowa MD woła `_apply_to_line` wewnątrz pętli po wierszach, więc `INSERT … ON CONFLICT DO UPDATE` ustawia `md_reported` na wartość z OSTATNIEGO wiersza, a MD z wcześniejszych wierszy znika. `recompute_remaining` przelicza potem `md_remaining = md_total - SUM(konsumpcja)` z tego jednego ocalałego wiersza, więc budżet wygląda na pełniejszy niż jest. Oba wiersze są nadal oznaczone `Zaktualizowano` w podsumowaniu importu, więc operator nie ma żadnego sygnału — licznik wierszy mówi dwa, a odjęcie odzwierciedla jeden. Zespół już wie, że taki kształt arkusza występuje w rzeczywistości: `backend/tests/test_order_lifecycle_and_cost.py:703` nazywa się dosłownie `test_two_rows_for_one_person_are_summed_not_overwritten` i podaje `(names[0], 5, "SAP …", 10000), (names[0], 5, "SAP …", 5000)` — ta sama osoba dwa razy, z MD w obu wierszach. Ten test asertuje jednak wyłącznie `budget_remaining` i `invoiced_total`; ponieważ linia kosztowa ma `md_total IS NULL`, nigdy nie przechodzi przez ścieżkę MD, a `tests/test_multi_consultant_orders.py` nie ma odpowiednika tego przypadku. Czyli fixture dowodzący istnienia tego kształtu wejścia jest w repo, a strona MD tego samego przypadku jest nieprzetestowana i zepsuta.

**Naprawa.** Buforuj ścieżkę MD dokładnie tak, jak już robi to ścieżka faktur: akumuluj `pending_md: dict[int, Decimal]` kluczowane po `match.order.id` wewnątrz pętli po wierszach (nadal stemplując każdy `MdConsumptionImportRow` własnym `matched_order_id`), a po pętli zawołaj `_apply_to_line` raz na zamówienie ze zsumowaną wartością — to zachowuje idempotencję `(linia, miesiąc)` i sprawia, że ponowny import identycznego pliku daje identyczną sumę. Dodaj brakujący bliźniak MD dla `test_two_rows_for_one_person_are_summed_not_overwritten` na linii MD (z ustawionym `md_total`), asertujący `md_remaining == md_total - 20`. Uwaga: `assign_row` (linia 619) stosuje po jednym wierszu naraz i też musiałby dodawać do zapisanej wartości, a nie ją zastępować, gdyby to samo zamówienie zostało rozstrzygnięte dwa razy.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 30` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f33"></a>

### #33 · P1 · Administracyjny kill-switch AI nie zatrzymuje generowania CV B2B (najdroższego wywołania Claude w produkcie) — zatrzymuje za to tani precompute mapy wymagań w tym samym background-jobie, podczas gdy UI bezwarunkowo twierdzi "Wszystkie funkcje AI są wyłączone globalnie"

nakład **M** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk`

`backend/app/services/cv_generator_b2b/ai_client.py:384`

**Co to kosztuje.** Generowanie CV odpala `claude-sonnet-4-6` z `claude-opus-4-8` jako fallbackiem przy 16384 max output tokens, do 3 retry na model przez 2 modele, na `POST /api/cv-generator/generate` i `/generate-upload` (oba `@limiter.limit("10/minute")`, otwarte dla każdej roli z CandidateDocumentAccess). Żaden z tych wydatków nie jest liczony w `ai_usage_log`, nic z tego nie widać w Ustawienia -> AI i niczego z tego nie da się ograniczyć miesięcznym limitem — nie ma dla tego w ogóle żadnego `AIFeatureKey`. Gorzej: przestawienie `AIMasterToggle.enabled = False` (udokumentowane w models/ai_feature.py:163-166 jako "Global kill-switch for all AI features … every quota-checked endpoint returns 503") NIE zatrzymuje generowania CV, bo ten toggle jest sprawdzany wyłącznie wewnątrz `check_and_increment`. Zaprojektowany catch-all też tego nie widzi: `claude_client._assert_declared` powstał dokładnie dlatego, że background taski i webhooki omijały dekoratory tras, ale uruchamia się tylko wewnątrz `call_claude`, a ten moduł konstruuje SDK bezpośrednio — więc przestawienie `AI_QUOTA_STRICT=True` (udokumentowane remedium w config.py:242-249) i tak by tego nie objęło. `/api/health.checks.ai_features` to jedyny kanał ostrzegania o wydatkach i wymienia 11 nielimitowanych kluczy — generowania CV wśród nich nie ma, więc dla tego ostrzeżenia też jest niewidoczne.

**Naprawa.** Dodaj `cv_generator = "cv_generator"` do `AIFeatureKey` (+ migracja enuma w Postgresie + seed wiersza w `ai_features` + lustro DDL w entrypoint.sh, bo prod alembic jest orphaned) i opakuj dwa background-joby `_run_generate_new_job` / wywołanie `generate_cv_from_uploads` w threadpoolu w `async with ai_feature(db, AIFeatureKey.cv_generator, user_id=...)` — kontekst propaguje się do `run_in_threadpool` zgodnie z ai_quota.py:262-264. Osobno: przepuść `cv_generator_b2b/ai_client._call_model` przez `claude_client.call_claude` (ma już tę samą politykę timeout/backoff — claude_client.py:4-5 mówi, że została przeniesiona właśnie z tego pliku), żeby `_assert_declared` odzyskał właściwość "jedno miejsce, przez które przechodzi niemal cały ruch". To samo dotyczy `b2b_contract_generator/uop_check.py`, który reużywa tego klienta.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 33` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f34"></a>

### #34 · P1 · Traffit sync zapisuje intencję reindeksu wyłącznie dla INSERT-ów — fazy CV/enrich nadpisują raw_cv_text, ai_summary, skills i experience (wszystko to wejścia embeddingu) bez żadnej intencji, więc wzbogaceni kandydaci zostają z wektorem zbudowanym z tekstu "? ?" sprzed wzbogacenia; reconciler dryfu napisany dokładnie na to jedzie z wyłączoną flagą

nakład **M** · obszar **Backend · serwisy** · **nie działa** · kategoria `broken`

`backend/app/services/traffit/importer.py:1676`

**Co to kosztuje.** Importer Traffita to dominująca ścieżka zapisu w tym produkcie (~49k kandydatów, dzienna delta + tygodniowy pełny sweep). `DO UPDATE SET` w `_UPSERT_CANDIDATE` nadpisuje `name`, `lastname`, `profile_about` i scala `cv_extracted_data` — a `name`/`lastname` to dosłownie dwa pierwsze wywołania `parts.append` w `_build_candidate_text_v1` (embedding_service.py:346-349). Faza `candidates_enrich_names` jest gorsza: woła `cv_backfill`, który zapisuje `candidate.raw_cv_text = raw_text`, a potem `_apply_cv_enrichment(...)` (skills, experience, education, ai_summary, years_it_experience) w cv_backfill.py:253-260 — kolejnych sześć wejść do tego samego tekstu embeddingu — i też nic nie zapisuje. Więc kandydat, któremu w Traffit zmieniło się CV albo umiejętności, zostaje z wektorem w Qdrancie zbudowanym ze STAREGO tekstu i wierszem `candidate_job_match_scores` policzonym ze STAREGO tekstu (żadne `mark_stale_for_candidate` na tych ścieżkach; `grep -rn mark_stale_for_candidate app/services/traffit/` jest pusty). Rekruter szuka umiejętności, która właśnie została dodana, a kandydat się nie pojawia. Nic tego nie wykrywa: `/api/health.checks.traffit` to sonda świeżości, nie kompletności.

**Naprawa.** Zbieraj id zaktualizowanych obok `new_candidate_ids` i przekaż je do tego samego wywołania `record_bulk_reindex` w importer.py:1800 (helper jest jawnie udokumentowany jako bulk-safe i jako NIE no-opujący na fladze outboxa — index_outbox_service.py:178-186), oraz dodaj `mark_stale_for_many_candidates` dla tego samego zbioru. To samo w `cv_backfill.backfill_missing_names`. Uwaga: udokumentowane uzasadnienie pozostawienia `AI_INDEX_RECONCILER_ENABLED=False` już nie obowiązuje: config.py:96-100 mówi, że "MUST NOT be enabled before the provider health probes", a te już istnieją i raportują — `_probe_qdrant` wykonuje realne zapytanie, a `record_provider_call("voyage", …)` siedzi w bloku finally `_voyage_embed_batch`. Załatanie trzech faz nadal jest właściwą główną poprawką (wg config.py:81-85 reconciler istnieje dlatego, że "patching those three fixes three, not the next one somebody adds"), ale reconciler powinien teraz zostać włączony jako zabezpieczenie.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 34` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f35"></a>

### #35 · P1 · Snapshot propozycji nigdy nie stosuje historycznego boostu, który /recommendations dokłada przed odcięciem po min-score — domyślna lista "Rekomendowani kandydaci" jest rankowana słabszym wzorem niż każdy filtrowany widok i niż wzór, który harness ewaluacyjny zapisuje jako "prod"

nakład **S** · obszar **Backend · tło** · **nie działa** · kategoria `broken`

`backend/app/tasks/compute_proposals.py:250`

**Co to kosztuje.** Komentarz twierdzi, że snapshot odzwierciedla `/recommendations`, więc oba "zgadzają się co do tego, kto pasuje". Nie zgadzają się. `/recommendations` woła `fetch_historical_boost_map` + `_apply_historical_boost` w recommendations.py:490-494, dodając do 15 punktów i sortując ponownie, PRZED tym samym odcięciem `>= RECOMMENDATION_MIN_SCORE`. `grep -rn "fetch_historical_boost_map\|_apply_historical_boost" app/` pokazuje, że oba żyją wyłącznie w recommendations.py — compute_proposals nie woła żadnego z nich. `SuggestedCandidatesWidget` startuje w trybie snapshot (`const [mode, setMode] = useState<Mode>("snapshot")`, linia 99) i przełącza się na live endpoint dopiero gdy aktywny jest filtr lokalizacji albo dealbreakera, więc DOMYŚLNY widok "Sugerowani kandydaci" to ten bez boostu. Przy RECOMMENDATION_MIN_SCORE=40 kandydat ze score 28, który przepracował trzy semantycznie podobne projekty, osiąga 43 na ścieżce live i po prostu nie ma go w domyślnym snapshocie — a sygnał "pierwszy ogień", który ten boost ma kodować (ludzie już sprawdzeni na podobnej pracy), to dokładnie ten sygnał, który rekruter chce zobaczyć najpierw.

**Naprawa.** Wywołaj `fetch_historical_boost_map(session, job_id)` w `compute_proposal_for_job` i zastosuj to samo `_apply_historical_boost` przed odcięciem `RECOMMENDATION_MIN_SCORE`. Funkcja żyje obecnie w routerze (`recommendations.py:243`) — przenieś ją obok `boost_points_for_sources` do `services/similar_job_candidates.py`, żeby task snapshotu, router i harness ewaluacyjny współdzieliły jedną implementację zamiast trzech (harness ma czwartą kopię inline w eval_matching.py:570-575). Uwaga: boost musi zostać poza utrwalanymi breakdownami z `bulk_get_or_compute`, jak tłumaczy recommendations.py:487-488 — stosuj go tylko do zwracanej listy.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 35` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f37"></a>

### #37 · P1 · PR #539 usunął jedyne wejście do czytnika wątków M365 na fałszywym uzasadnieniu "duplikat" — 1473 LOC + 7 żywych endpointów osierocone, podczas gdy sync dalej zapisuje na prodzie treści maili kandydatów i załączniki

nakład **M** · obszar **Frontend · UI** · **dług** · kategoria `dead-code`

`frontend/src/components/emails/EmailThreadList.tsx:36`

**Co to kosztuje.** Rekruter podłącza swoją skrzynkę w Ustawienia → Microsoft 365 (ta karta JEST żywa — settings/page.tsx:434), a backend następnie zaciąga 12 miesięcy skrzynki odbiorczej i wysłanych, dopasowuje każdą wiadomość do kandydata i zapisuje `subject`, `from_address`, `to_addresses`, `cc_addresses`, `body_html`, `body_text` oraz załączniki (models/m365.py:183-209). Prodowe `/api/health` zwraca `"m365": "healthy"`, co wg main.py:1416-1435 wymaga włączonej flagi integracji, włączonej pętli syncu **i co najmniej jednego aktywnego wiersza M365Connection** — więc dzieje się to w tej chwili, na prawdziwej korespondencji. Nigdzie w produkcie nie ma ekranu, żeby cokolwiek z tego przeczytać. Siedem żywych endpointów backendu (`GET /api/candidates/{id}/emails`, `.../emails/thread/{conversationId}`, `GET /api/emails/{id}`, pobieranie załącznika, `POST .../emails/compose`, `.../emails/reply`, `POST /api/microsoft365/emails/bulk`) ma zero wołających. Dwie konkretne straty: (a) historia korespondencji z kandydatem, której rekruter potrzebuje przed rozmową, jest niewidoczna, oraz (b) ponieważ ocalałą akcją jest `mailto:`, poczta wychodząca leci z własnego Outlooka rekrutera i nigdy nie jest zapisywana z powrotem przy rekordzie kandydata — więc historia wątku, która JEST synchronizowana, jest wyłącznie przychodząca i trwale jednostronna. Jest też wątek RODO: treści maili kandydatów są zbierane i przechowywane bez żadnej powierzchni, która by czemukolwiek służyła.

**Naprawa.** Najpierw rozstrzygnij intencję produktową, bo oba kierunki są tanie, a jedyny drogi jest stan obecny. Jeśli czytanie maili ma być: przywróć zakładkę `emails` do tablicy `tabs` w CandidateDetailV2, renderującą `<EmailThreadList candidateId=… />` — komponent i jego troje dzieci są nietknięte i wciąż otypowane pod żywą powierzchnię `microsoft365Api`. Commit 4925ac53 (#539, 2026-06-18) usunął zakładkę, twierdząc "Email jest już dostępny w menu Więcej (przeniesiony w #538)", ale to, co wylądowało w tamtym menu, to kompozytor mailto, a nie czytnik wątków — więc parytet, który ten commit deklarował, nigdy nie był prawdą. Jeśli czytanie maili NIE ma być: usuń `src/components/emails/` (1473 LOC) plus `src/lib/email-threading.ts` (79 LOC), wywal siedem nieużywanych endpointów z `email_threads.py` i wyłącz `M365_SYNC_LOOP_ENABLED`, żeby produkt przestał przechowywać treści maili kandydatów, których nie umie pokazać.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 37` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f42"></a>

### #42 · P1 · Interceptor retry w axiosie nie ma guardu na metodę HTTP: jego najszersza gałąź (!err.response) powtarza POST/PATCH/DELETE dwa razy przy każdym timeoucie po stronie klienta albo awarii z obciętym CORS — i jest to jedyna warstwa retry dla mutacji

nakład **S** · obszar **Frontend · lib** · **nie działa** · kategoria `broken`

`frontend/src/lib/api.ts:182`

**Co to kosztuje.** Zduplikowane zapisy w całym ATS-ie i zwielokrotniony koszt LLM, jedno i drugie niewidoczne dla użytkownika. Nie ma guardu na metodę HTTP: `api.request(config)` powtarza dowolny czasownik, który dostał, a to JEDYNA warstwa retry dla zapisów (QueryProvider.tsx:11-14 ustawia retry tylko pod `queries`, więc domyślne 0 retry dla mutacji w react-query zostawia ten interceptor bez przeciwwagi). Gałąź `!err.response` jest tą szeroką — jest prawdziwa dla timeoutu axiosa po stronie klienta ORAZ dla trybu awarii, który pamięć tego repo dokumentuje jako typowy przypadek: backendowe 500, któremu nagłówki CORS obcięło najbardziej zewnętrzne ServerErrorMiddleware Starlette (backend/app/main.py:658 dodaje CORSMiddleware wewnątrz niego), co dociera do przeglądarki jako bezcielesny network error. Więc zwykłe nieobsłużone 500 na POST /api/notes, POST /api/candidates, POST /api/invoices albo POST /api/pipeline/{id}/accept-verification jest klasyfikowane jako 'transient' i wysyłane dwa razy ponownie. W produkcie rekrutacyjnym konkretna szkoda to zduplikowane wiersze kandydatów (repo traktuje dedup/merge w Cortexie jako nieodwracalny), zduplikowane notatki na profilu kandydata i zduplikowane pozycje faktur. Gałąź kosztowa jest gorsza: frontend/src/lib/http-timeouts.ts:10-13 już nazywa tę awarię („przeglądarka zrywa połączenie, backend kończy generację i PŁACI za nią"), ale tylko w sensie ręcznego odświeżenia — ten interceptor to automatyzuje, więc jeden parsing profilu Championa albo wywołanie scoringu, które przekroczy swój sufit, jest fakturowany Anthropikowi trzy razy, bez jednego kliknięcia i bez linijki logu, którą użytkownik kiedykolwiek zobaczy.

**Naprawa.** Ogranicz gałąź transient do czasowników idempotentnych: powtarzaj tylko, gdy `config.method` to get/head/options, albo gdy wywołujący jawnie się zgłosi flagą w configu żądania. Jeśli retry POST-ów są naprawdę pożądane dla okna 502/503 przy deployu Coolify, które ten kod motywowało, zawęź to dokładnie do `err.response?.status` w {502,503} (gdzie żądanie dowodliwie nigdy nie dotarło do aplikacji) i wyklucz zarówno `!err.response`, jak i 504 — to właśnie te dwa przypadki, w których backend mógł ukończyć pracę.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 42` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f43"></a>

### #43 · P1 · /contracts/analytics nie ma gałęzi isError w 588 liniach: `?? []` zamienia nieudane pobranie marży w pewne siebie „0,00 zł" marży miesięcznej, a celowy sygnał degradacji fx_warnings z backendu w ogóle nie istnieje w typie frontendowym

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/app/contracts/analytics/page.tsx:234`

**Co to kosztuje.** To jest ekran, który admin otwiera, żeby odpowiedzieć na pytanie „ile zarabiamy w tym miesiącu". Żadne z jego siedmiu wywołań useQuery nie destrukturyzuje isError ani error, i nigdzie w tym 588-liniowym pliku nie ma gałęzi sprawdzającej awarię — `?? []` zwija 500, 403 albo błąd sieci w pustą tablicę, którą reduktory zamieniają w pewne siebie `formatCurrency(0, "PLN")` na kafelkach KPI „Miesięczna marża" i „Miesięczny przychód" (linie 259-274). Leaderboardy poniżej wypisują „Brak danych." (linia 106), a RoleClientMixCard „Brak aktywnych kontraktów do analizy." (linia 344) — trzy niezależne twierdzenia, że firma nie ma kontraktów. Kompensuje to drugi, cichszy defekt: backend celowo zwraca ostrzeżenie o degradacji („Brak kursu NBP dla walut: … — kwoty w tych walutach POMINIĘTE w prognozie", backend/app/api/contract_analytics.py:428-430), ale frontendowy `interface Forecast` w liniach 53-56 deklaruje tylko `horizon_months` i `months`, a `fx_warnings`/`fx_missing` nie występują nigdzie we froncie — więc 12-miesięczna prognoza przychodów, która po cichu wyrzuciła wszystkie kontrakty w EUR/USD, renderuje się jakby była kompletna.

**Naprawa.** Wyciągnij `isError, error, refetch` ze wszystkich siedmiu zapytań i przepuść ciało strony przez `resolveViewState` z lib/view-state.ts, które to repo napisało dokładnie po to (jego docstring w linii 7 nazywa „403 na GET bywał zgłaszany jako skazało mi dane"). W minimalnym wariancie oba kafelki KPI muszą renderować „—", a nie sformatowane zero, gdy `byClient` jest undefined, a ForecastChart musi przyjmować prop `isLoading`/`isError` zamiast wnioskować pustkę z `!forecast`. Osobno: dodaj `fx_warnings: string[]` i `fx_missing` do interfejsu Forecast i renderuj ostrzeżenie nad wykresem.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 43` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f44"></a>

### #44 · P1 · Tygodniowa siatka kalendarza nie ma gałęzi isError: 403 z guardu rolowego (rola viewer widzi link w sidebarze, ale backend go odmawia) renderuje się jako w pełni narysowany, całkowicie pusty tydzień — bez błędu, bez ponowienia, a panel „Najbliższe" po cichu znika

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/app/calendar/page.tsx:175`

**Co to kosztuje.** Domyślne `= []` to komponentowa wersja „złap błąd API i ustaw stan na pusty". Jedyna gałąź konsumenta to `{isLoading ? <spinner> : <WeekGrid events={events} …/>}` w liniach 318-333 — nigdzie w tym 1252-liniowym pliku nie ma isError. Gdy /api/calendar/events pada, siatka maluje w pełni narysowany, poprawnie datowany, całkowicie pusty tydzień: bez spinnera, bez komunikatu, bez ponowienia. Rekruter skanujący poniedziałek rano widzi zero rozmów i odchodzi. Przegapienie zaplanowanej rozmowy z kandydatem to najdroższa cicha awaria w ATS-ie — pali jednocześnie kandydata, hiring managera i relację z klientem. Bliźniacze zapytanie `conflictPairs` (linia 183) ma ten sam kształt przez `conflictPairs ?? {}`, więc ostrzeżenia o podwójnych rezerwacjach też znikają po cichu, co znaczy, że rekruter może zostać doprowadzony do zarezerwowania slotu, który już ma konflikt. Zwróć uwagę, że bramkowanie jest na `isLoading`, nie na `isPending` — przy globalnym `retry: 1` w QueryProvider.tsx:13 istnieje też okno ~1 s między próbami, gdzie isLoading jest false, isError jest false, a data jest undefined, więc pusty tydzień mignie nawet po drodze do docelowego stanu błędu.

**Naprawa.** Wyciągnij `isError, error, refetch`; renderuj jawny wiersz awarii nad siatką („Nie udało się wczytać kalendarza" + „Ponów") i zostaw pustą siatkę tylko przy `isSuccess && events.length === 0`. Zdejmij domyślne `= []`, żeby wywołujący nie pomylił „nie wiadomo" z „nie ma", i bramkuj na `isPending`, a nie na `isLoading`, żeby przerwa między retry nie malowała pustego stanu.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 44` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f45"></a>

### #45 · P1 · Rejestr kontraktów per klient nigdy nie czyta isError — 5xx/timeout albo 403 renderuje się jako „0 kontraktów" + „Brak kontraktów dla tego klienta", podczas gdy globalny rejestr trzy linijki dalej na tej samej stronie poprawnie używa resolveViewState (F-20)

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/contracts/ClientContractRegister.tsx:546`

**Co to kosztuje.** To jest rejestr, który odpowiada na pytanie „kogo mamy ulokowanego u tego klienta i na jakich warunkach", i zamienia każdą awarię w pewne siebie, zachęcające do działania kłamstwo. Zapytanie w linii 310 destrukturyzuje tylko `{ data, isLoading, isFetching }` — bez isError, bez error, bez retry — a nagłówek w linii 425 dokłada do tego wypisanie `${total} kontraktów`, czyli „0 kontraktów", z tego samego niezdefiniowanego payloadu. CTA tworzenia czyni to istotnie gorszym od pozostałych defektów pustego stanu: bliźniaczy kod w tym samym pliku wie lepiej (ProlongationCell w liniach 108-128 robi porządny optimistic update z rollbackiem), a lib/view-state.ts:14 formułuje regułę wprost — „sukces + 0 rekordów → empty — dopiero tutaj wolno zachęcać do dodania". 403 w tym miejscu to dokładnie ten scenariusz, na którym repo już się sparzyło: awaria uprawnień czytana jako utrata danych.

**Naprawa.** Wyciągnij `isError, error, refetch` i przepuść ciało tabeli przez `resolveViewState({ isLoading: isPending, isError, error, isEmpty: items.length === 0 })` (tak jak robi to już bliźniaczy ContractsListV2.tsx:224), renderując QueryStateNotice dla forbidden/error i rezerwując CTA „Dodaj pierwszy kontrakt" dla `viewState === "empty"`. Spraw też, żeby licznik w nagłówku renderował „—", a nie 0, gdy zapytanie nie zakończyło się sukcesem.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 45` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f46"></a>

### #46 · P1 · Nieudane zapisy są niewidoczne w całej aplikacji — nie ma globalnego handlera błędów mutacji, a 86 miejsc useMutation nie ma onError; zapis screeningu przez Head of Recruitment po cichu zwraca 403 przy każdej próbie, bo bramka odczytu jest szersza niż bramka zapisu

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/v2/modals/ScreeningSheet.tsx:118`

**Co to kosztuje.** Zliczenie w całym repo z parsowania po dopasowaniu klamer każdego obiektu opcji useMutation: 87 z 394 nie ma `onError`; w 18 z zawierających je plików nie ma nigdzie w pliku showError, toast, setError, isError ani `.error`, więc awaria nie ma dosłownie gdzie się ujawnić. Te instancje nie są peryferyjne. ScreeningSheet zapisuje `deal_breaker_hit` per pytanie — flagi zasilające twardy, bezmarginesowy sufit dealbreakerów w matchingu — a jego jedyną ścieżką wyjścia jest onSuccess. ScorecardV2.tsx:91-111 jest identyczne dla scorecardów z rozmów. ContractInvoicesTab.tsx:57-80 ma trzy (utworzenie faktury, oznaczenie jako opłacona, usunięcie) bez żadnego UI błędu w pliku. components/settings/admin/AdminUsersTab.tsx:52-100 ma pięć, obejmujących tworzenie użytkownika, zmiany ról, dezaktywację i reset hasła — po cichu nieudana zmiana roli to stan RBAC, który admin uważa za zastosowany. Ponieważ modal zamyka się tylko przy sukcesie, widocznym efektem awarii jest: spinner leci, spinner staje, sheet dalej otwarty, przycisk znowu mówi „Zapisz screening". Użytkownik nie odróżni odrzuconego zapisu od kliknięcia, które nie zadziałało, więc racjonalną reakcją jest kliknięcie ponownie — co w połączeniu ze znaleziskiem 1 zamienia faktycznie zacommitowany-a-potem-500 zapis w kilka wierszy.

**Naprawa.** Dodaj `onError: (e) => showError(extractErrorMsg(e))` do tych mutacji — extractErrorMsg już istnieje w lib/api.ts:47 i już obsługuje osobno 429 oraz surowy detail 403 `Requires one of roles:`, więc hydraulika jest gotowa. Priorytetowo cztery powierzchnie wprowadzania danych, na których użytkownik wpisał coś, co straci albo źle oceni: ScreeningSheet, ScorecardV2, ContractInvoicesTab, AdminUsersTab. Reguła lintu wymagająca `onError` przy każdym useMutation zatrzymałaby przyrost pozostałych 83.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 46` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f49"></a>

### #49 · P1 · Cztery POST-y champion-draft do LLM chodzą na 30-sekundowym suficie dla CRUD-a zamiast na `SLOW_ENDPOINT_TIMEOUT_MS`, a ślepy interceptor retry na błędy przejściowe zamienia każde przerwanie w dwa kolejne pełne przebiegi backendu — jedno kliknięcie obciąża kwotę `champion_draft` i Sonnet-5 nawet 3×, a profil, który backend faktycznie zapisał, pozostaje niewidoczny

nakład **S** · obszar **Frontend · lib** · **nie działa** · kategoria `broken`

`frontend/src/lib/api.ts:3654`

**Co to kosztuje.** `lib/api.ts:19` ustawia `DEFAULT_REQUEST_TIMEOUT_MS = 30_000` na współdzielonej instancji, a `lib/http-timeouts.ts` istnieje dokładnie po to, by podnieść to do 120 s dla „wywołań, w których liczy model" — jego docstring wprost mówi, że tryb awarii jest gorszy niż czekanie: „backend kończy generację i PŁACI za nią, a użytkownik widzi błąd i klika 'odśwież' — czyli mnoży ten koszt". Ten override zastosowano w radarze (#1210/#1211) i w 14 miejscach w `api.ts`, ale nigdy w powyższych czterech punktach wejścia champion-draft. Wszystkie cztery to synchroniczne, wykonywane w requeście wywołania Claude — `backend/app/api/jobs.py:2506` (generate-from-jd), `:2565` (generate-from-history), `:2328` (recommended-searches/generate) oraz `backend/app/api/notes.py:364` (briefing) — na `claude-sonnet-5` z `max_tokens: int = 4000` (`champion_draft_service.py:100`), a własny budżet backendu na próbę to `ANTHROPIC_TIMEOUT_SECONDS: float = 90.0` przy `ANTHROPIC_MAX_RETRIES: int = 2` (`config.py:321-322`), czyli do ~270 s plus backoff. Najostrzejsza jest ścieżka briefingu: `_summarize_transcript_for_champion` robi map-reduce transkryptu z Fireflies na kawałki po 30 000 znaków i wysyła po jednym sekwencyjnym `call_claude` na kawałek (`champion_draft_service.py:255-262`) przed finalnym promptem championa — realny transkrypt spotkania nie ma szans zmieścić się w 30 s. W tym czasie `check_and_increment(db, AIFeatureKey.champion_draft, …)` wykonuje się i jest `await db.commit()`-owane PRZED wywołaniem modelu (`jobs.py:2505-2519`), więc przerwanie po stronie przeglądarki niczego nie zwraca. Zwróć uwagę na kontrast: generacja CV została świadomie przeniesiona na enqueue w tle (`CVGeneratorV2.tsx` toastuje „Generacja ruszyła w tle"); champion draft jest jedyną dużą powierzchnią LLM, która została synchroniczna — i jedyną wciąż pod sufitem CRUD-a.

**Naprawa.** Dodaj `{ timeout: SLOW_ENDPOINT_TIMEOUT_MS }` do `setBriefing`, `generateRecommendedSearches`, `generateFromJd` i `generateFromHistory` w `lib/api.ts` — ta sama konfiguracja jako trzeci argument jest już użyta 14 razy w tym pliku. Potem zamknij całą klasę tak, jak zamknięto defekt z FormData/multipart: repo ma dla tamtego strażnika skanującego źródło (`src/lib/__tests__/formdata-multipart.test.ts`, który tłumaczy, dlaczego test jednostkowy mockujący `@/lib/api` przechodzi obok zepsutej warstwy), a dla timeoutów nie ma odpowiednika; bliźniaczy skaner asertujący, że każdy `api.post` na ścieżkę z zadeklarowanej listy endpointów LLM niesie override, zatrzymałby następny taki przypadek. W dłuższym horyzoncie przenieś champion draft na ten sam wzorzec enqueue w tle, którego używa już generacja CV, i przesuń `check_and_increment` za wywołanie modelu (albo zwracaj kwotę przy błędzie), żeby przerwany request nie palił limitu.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 49` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f53"></a>

### #53 · P1 · Filtr „Typ" na `/contracts` i jego eksport XLSX/CSV zawsze kończą się 500 — wszystkie trzy opcje (`body_leasing`/`fixed_price`/`t_and_m`) są odrzucane przez enum PG `contracttype` (b2b/uop/uzlecenie), odtworzone na Postgresie 16

nakład **S** · obszar **Frontend · lib** · **nie działa** · kategoria `broken`

`frontend/src/lib/filter-options.ts:125`

**Co to kosztuje.** Na `/contracts` — głównym rejestrze kontraktów używanym przez admina, Delivery Leada i TAC — multi-select „Typ" jest martwy w każdej pozycji. Każda oferowana przez niego wartość jest odrzucana przez Postgresa dla kolumny `contracttype` (SQLAlchemy 2.0 przepuszcza nieznane stringi bez walidacji, `sqltypes.py:1677` `if not self.validate_strings and isinstance(elem, str): return elem`), więc request pada z `invalid input value for enum contracttype`; w najżyczliwszej interpretacji może co najwyżej nigdy nie trafić w żaden wiersz. Te same parametry zasilają `GET /api/contracts/export`, więc eksport kontraktów do Excela/CSV z filtrem po typie jest zepsuty tak samo. Użytkownik filtrujący „Body leasing" wnioskuje, że firma nie ma kontraktów body-leasingowych, co jest odwrotnością prawdy — body leasing to podstawowy model współpracy. Słownik został niemal na pewno skopiowany z `RecruitmentType` (body_leasing/sales_project/tender), który żyje na `Job`, nie na `Contract`.

**Naprawa.** Zamień `CONTRACT_TYPE_OPTIONS` na prawdziwy enum: `{b2b: "B2B", uop: "Umowa o pracę", uzlecenie: "Umowa zlecenie"}` — etykiety istnieją już po stronie serwera w `backend/app/api/contracts.py:666-670` (`_CONTRACT_TYPE_LABELS`). Potem zmień sygnaturę handlera na `Optional[list[ContractType]]`, żeby FastAPI zwracało czytelne 422 zamiast przepuszczać złą wartość do sterownika — lustrzanie do tego, co dwie linie wyżej robi już `status: Optional[list[ContractStatus]]`. `backend/tests/test_contracts_filters_multi.py` przekazuje wyłącznie b2b/uop/uzlecenie, więc dodaj przypadek z wartością, którą faktycznie wysyła UI.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 53` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f55"></a>

### #55 · P1 · `AddJobModal` zapisuje obiektowy `detail` z 503 o wyczerpanej kwocie AI w stanie typu string i renderuje go jako dziecko Reacta — „Dodaj rekrutację" zostaje zastąpione przez error boundary, a wypełniony formularz przepada

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/AppShell.tsx:1438`

**Co to kosztuje.** Ustawienia → AI wystawiają master toggle i miesięczny limit per funkcja (`frontend/src/app/settings/ai/page.tsx:129, 272`), więc `AIQuotaExceeded` jest o jedno kliknięcie admina, a nie stanem teoretycznym. Gdy odpali w „Generuj AI" wewnątrz modala „Dodaj rekrutację", React dostaje zwykły obiekt jako dziecko i rzuca „Objects are not valid as a React child" w trakcie renderu — error boundary App Routera podmienia stronę, a wypełniony do połowy formularz rekrutacji (tytuł, klient, TAC, DL, wymagania) przepada. Na pozostałych endpointach ten sam blok daje trzy różne doświadczenia użytkownika z jednej przyczyny: czyste polskie zdanie (`candidate_scoring`), angielski string wewnętrzny wyciekający klucz funkcji („AI quota for champion_draft blocked: …") oraz — ponieważ `jobs.py:2354` używa 429 — gałąź rate-limitu w `extractErrorMsg` mówi rekruterowi w kółko „Zbyt wiele prób w krótkim czasie — odczekaj minutę" dla stanu, którego czekanie nie rozwiąże.

**Naprawa.** Wybierz jeden kształt dla `AIQuotaExceeded` i użyj go we wszystkich dziewięciu miejscach wywołania: 503 z `detail={"message": exc.reason, "code": "ai_quota", "feature": …, "used": …, "limit": …}` — samo dodanie `message` sprawia, że `extractErrorMsg` jest już wszędzie poprawne. Wyrzuć 429 z `jobs.py:2354` (to nie jest rate limit i koliduje z gałęzią 429 w `extractErrorMsg`) i przestań używać `str(exc)`, które wycieka angielski prefiks i klucz funkcji. Potem przepuść handler z `AppShell` (i ~60 pozostałych surowych odczytów `response.data.detail`) przez `extractErrorMsg`, żeby niestringowy `detail` nigdy nie mógł trafić do slotu JSX.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 55` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f60"></a>

### #60 · P1 · Niezmemoizowana wartość ToastContext re-renderuje każdego zamontowanego konsumenta useToast() przy każdym toaście — a ponieważ InsightsView trzyma cały obiekt kontekstu w tablicy zależności useEffect, użytkownik otwierający /insights?tab= dla zakładki bez uprawnień dostaje samonapędzającą się pętlę toast/render zamiast jednego błędu

nakład **S** · obszar **Frontend · UI** · **ryzyko** · kategoria `perf`

`frontend/src/components/Toast.tsx:101`

**Co to kosztuje.** `{children}` to stabilna referencja elementu przekazywana w dół z RootLayout, więc React normalnie zrezygnowałby z re-renderu poddrzewa aplikacji, gdy zmienia się stan toastów w providerze. Niezmemoizowana wartość niweczy dokładnie ten bailout dla 99 komponentów czytających kontekst — a to te ciężkie. Akcje masowe bolą najbardziej: zaznaczenie 50 kandydatów i dodanie ich do talent poola albo masowe przesunięcie kart na tablicy pipeline'u produkuje toast na operację, a każdy toast wymusza dwa pełne re-rendery listy kandydatów (włącznie z każdym widocznym wirtualnym wierszem i jego badge'ami) oraz wszystkiego innego, co jest zamontowane. Efekt: interakcja robi się lepka dokładnie wtedy, gdy rekruter wykonuje powtarzalną pracę o dużym wolumenie. To poprawka na jedną linię, co czyni pozostawienie jej trudnym do uzasadnienia.

**Naprawa.** Jedna linia: opakuj wartość — `const value = useMemo(() => ({ showToast, showSuccess, showError, showActionToast }), [showToast, showSuccess, showError, showActionToast])` i przekaż `value={value}`. Wszystkie cztery zależności są już stabilne przez useCallback, więc memo nigdy się nie unieważni, a konsumenci całkowicie przestaną re-renderować się przy ruchu toastów. Przy okazji rozważ wydzielenie renderowania listy toastów do komponentu-rodzeństwa, żeby zmiany stanu providera nie re-renderowały w ogóle providera, który jest właścicielem kontekstu.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 60` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f63"></a>

### #63 · P1 · Poprawka "kandydaci brakujący w indeksie" z 28 lipca wyliczyła ręcznie 4 ścieżki zapisu i pominęła żywą kolejkę zgłoszeń, która od 22 lipca tworzy niezaindeksowanych kandydatów — a test-guard utrwala to pominięcie

nakład **M** · obszar **Testy** · **dług** · kategoria `test-gap`

`backend/tests/test_index_coverage_write_paths.py:39`

**Co to kosztuje.** Kandydat, który nigdy nie trafia do Qdranta, nie jest "gorzej rankowany" — ten rekord w ogóle nie bierze udziału. Rekomendacje, wyszukiwanie hybrydowe i sweep Marketplace'u czytają id z kolekcji, więc niezaindeksowany aplikujący jest niewidoczny dla każdej powierzchni matchingu, podczas gdy lista kandydatów pokazuje go normalnie — i właśnie dlatego nikt tego nie zauważa. Kolejka zgłoszeń (/applications → "Utwórz kandydata", podpięta do POST /api/application-submissions/{id}/resolve z src/app/applications/page.tsx:118) to żywa, sterowana z UI ścieżka wejścia dla osób, które zaaplikowały na ogłoszenie — czyli najcieplejszych kandydatów w bazie — i każdy utworzony w ten sposób jest obecnie poza matchingiem.

**Naprawa.** Dwie części, i to druga zatrzymuje nawroty. (1) Dodaj intencję indeksowania do obu ścieżek: schedule_or_embed_candidate dla jednorekordowej gałęzi application-submission, record_bulk_reindex dla bulk_import_candidates (bulk nie może embedować inline — jeden call do Voyage na wiersz, zgodnie z regułą asertowaną już w test_bulk_paths_do_not_embed_inline). (2) Zastąp ręcznie utrzymywane _WRITE_PATHS odkrywaniem: przejdź AST-em po backend/app szukając każdej funkcji, która konstruuje `Candidate(` i woła na nim db.add, po czym zasertuj, że każda z nich dociera do _INDEXING_CALLS. To jedyna wersja tego testu, która robi to, co obiecuje jego docstring — łapie piątą ścieżkę napisaną przez kogoś, kto nie zna reguły. Trzymaj jawną listę wyłączeń dla konstrukcji naprawdę nieindeksowalnych (np. wiersze kwarantanny), żeby wyjątek był widocznym diffem.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 63` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f64"></a>

### #64 · P1 · Marża zamówienia czyta contracts.rate_* — cache zapisywany przy zapisie, bez żadnego odświeżacza — więc każdy krok stawki wchodzący w życie po ostatnim zapisie umowy pokazuje złą marżę, a client_orders.py w ogóle nie ładuje harmonogramu stawek

nakład **M** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/client_orders.py:173`

**Co to kosztuje.** Złe pieniądze na trzech powierzchniach, które ludzie kwotują klientom: każdy wiersz zamówienia w zakładce Zamówienia klienta (przez _build_order_read, linia 408), `latest_order_monthly_margin` na liście kontraktorów z zamówieniami (linia 514) oraz odpowiedź pokazywana po utworzeniu nowego zamówienia kontraktorskiego (linia 1275). Dla każdej umowy niosącej stawkę progresywną albo datowany aneks rate_change, którego data już minęła, wszystkie trzy wyświetlają marżę z PIERWSZEGO okresu stawkowego. Zespół zapłacił za ten błąd już raz — CLAUDE.md odnotowuje, że tabela konsultantów w Klienci→Profil pokazywała "starą kwotę, złą marżę i zaniżone Aktywne MRR" dokładnie z tego powodu — i naprawiono tylko jedną z dwóch implementacji.

**Naprawa.** Spraw, by _compute_monthly_margin przyjmowała `on: date` i czytała `contract.effective_client_rate(on)` / `contract.effective_candidate_rate(on)` zamiast kolumn, zachowując na wierzchu istniejące nadpisanie `order.rate_client if not None` (stawka na poziomie zamówienia to fakt o tym zamówieniu i nadal musi wygrywać). Każde miejsce wywołania musi wtedy eager-loadować candidate_rate_schedule i client_rate_schedule, inaczej resolver robi lazy-load wewnątrz sesji async i rzuca MissingGreenlet — ścieżka listy w linii 498 używa już selectinload, więc rozszerz to options() zamiast dokładać zapytania. Dodaj test regresyjny, którego ten moduł nigdy nie miał, wzorowany na test_client_profile.py::_seed_scheduled_contract: zasiej umowę, której legacy kolumny trzymają kwoty z okresu 1, a harmonogram wszedł krokiem w przeszłości, po czym zasertuj, że monthly_margin wiersza zamówienia równa się różnicy z okresu 2, a nie z okresu 1.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 64` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f67"></a>

### #67 · P1 · Żaden test po żadnej ze stron nie porównuje literału roli z frontendu ze strażnikiem w Pythonie — `RateCardsTab` nadal bramkuje na `["admin","delivery_lead"]` po cutoverze z 2026-08-04, który przeniósł `/api/rate-cards` na finance-only, więc Delivery Lead widzi fałszywe „Brak wpisów cennika" i przycisk Zapisz, który zwraca 403, podczas gdy `finance` (jedyna autoryzowana rola poza adminem) w ogóle nie widzi tego przycisku

nakład **M** · obszar **Testy** · **dług** · kategoria `test-gap`

`frontend/src/lib/__tests__/capabilities.test.ts:38`

**Co to kosztuje.** Wiążąca reguła rolowa mieszka w Pythonie (zależności `require_*` w `backend/app/api/*_access.py` i `deps.py`); frontend powtarza ją pięć razy i weryfikuje każde powtórzenie względem literału wpisanego przez tę samą osobę w tym samym PR. Nic po żadnej ze stron nie czyta drugiej — grep po wszystkich 494 plikach testowych backendu za „frontend" zwraca tylko komentarze prozą, nigdy odczytu pliku. Więc jedynym detektorem rozjazdu jest użytkownik, który się na niego natnie. Zaobserwowana awaria ma dwa kierunki i oba już wjechały na prod: link widoczny → 403 po kliknięciu (Talent Radar dla Head of Recruitment, generator B2B dla finance/recruiter/sourcer) oraz backend otwarty → UI nadal to ukrywa (piąte lustro, które przeżyło #1212 i #1215). Każdy taki incydent kosztuje pełny sweep po pięciu plikach plus deploy na produkcję.

**Naprawa.** Dodaj jeden test kontraktowy między warstwami, który sprawia, że rozjazdu nie da się mechanicznie przeoczyć. Wyeksportuj zbiory ról z backendu jako dane maszynowo czytelne — mały JSON emitowany z zależności `require_*` (trzymają już literalne krotki, np. `CONTRACT_LEGAL_ROLES`) — i niech przypadek w vitest go wczyta i asertuje, że `CAPABILITY_ROLES`, `ROLE_ROUTES` i wpisy w `SidebarV2` są każdy podzbiorem zbioru z backendu dla odpowiadającej trasy, głośno padając na każdej capability, której plik nie zna. Niezależnie: zwiń piąte lustro — in-page `RequireRole` duplikujący regułę wyrażoną już w middleware albo w rejestrze capability powinien zostać skasowany, a test powinien asertować, że żaden komponent strony nie wpisuje na sztywno tablicy `roles={[...]}`, która występuje też w `CAPABILITY_ROLES`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 67` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f68"></a>

### #68 · P1 · Twarde usunięcie kandydata porzuca wynik sprzątania Qdranta/storage zamiast zakolejkować trwały retry, którego bliźniacza ścieżka kwarantanny już używa — nieudane sprzątanie jest nie do odzyskania, a wiersz audytu RODO nadal twierdzi, że usunięcie się powiodło

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/candidates.py:4313`

**Co to kosztuje.** To jest endpoint odpowiadający na żądanie usunięcia danych z art. 17. Kiedy padnie w połowie, awaria jest nie do odzyskania z samej konstrukcji: klucze storage zostały odczytane z `candidate_documents` chwilę przed `db.delete(candidate)`, więc po zacommitowaniu transakcji nigdzie nie zostaje wiersz, który wie, które obiekty S3 należały do tej osoby. Ich CV w PDF zostaje w buckecie Hetznera na zawsze, jest mirrorowane do kopii off-site pod `candidate-documents/current/` — którą `backup.sh:348` celowo wyklucza z przycinania retencji — a ich nazwisko plus fragmenty CV zostają w indeksie pasaży Qdranta, gdzie wyszukiwanie semantyczne będzie je dalej zwracać jako osierocone trafienie. Firma powiadomi tę osobę na piśmie, że jej dane zostały usunięte, a jedynym śladem, że tak nie było, będzie linia WARNING w Loki.

**Naprawa.** Kontrakt już istnieje i to jedyny wywołujący, który go ignoruje. `delete_candidate_embedding` jest zadeklarowany jako `-> bool` (`embedding_service.py:483`), a jego komentarz inline mówi, że awaria aktywnej kolekcji musi wyjść na zewnątrz, żeby „zewnętrzny handler zwraca wtedy False, a kwarantanna (`if not deleted:`) stage'uje trwały retry". `candidate_identity_quarantine.py:366` to honoruje — wstawia oczekujący wiersz outboxu `operation="delete"` *przed* wywołaniem, a potem sprawdza `if not deleted:`. Zrób tak samo tutaj: zakolejkuj wiersz kasujący w index-outbox przed `db.commit()`, sprawdź boolean i dodaj równoważną trwałą kolejkę (albo tabelę nagrobków `deleted_storage_keys`) dla kluczy object storage, żeby nieudany `delete_cv` dało się ponowić po zniknięciu wiersza. Obsłuż też `is_available()` zwracające `False` — dziś to cicho pomija kasowanie CV w całości, bez żadnego zapisu.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 68` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f69"></a>

### #69 · P1 · Usunięcie kandydata nigdy nie odwołuje linku współdzielenia jego wygenerowanego CV: publiczny endpoint `/api/public/cv-i/{token}` dalej serwuje pełne CV usuniętej osoby — a jego czat AI dalej odpowiada na nowe pytania o nią — dopóki nie minie TTL tokena (maks. 90 dni)

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/public_share.py:278`

**Co to kosztuje.** Istnieją trzy rodziny tokenów współdzielenia i dwie usuwają się poprawnie — `champion_share.py:24` kaskaduje z `candidate_stages`, a `cv_share_token.py:34` z `candidate_stage_cvs`, przy czym obie kaskadują z kandydata. `CvGeneratedShareToken` to ta trzecia, która się rozjechała: kaskaduje z `cv_generated_documents`, których FK do kandydata to `ondelete="SET NULL"` (`cv_generated_document.py:31`). Więc po usunięciu wiersz przeżywa, niosąc `candidate_name` i `render_payload` — kompletne wygenerowane CV, razem z historią zatrudnienia — a token, który je odblokowuje, przeżywa razem z nim. Te linki wysyła się dokładnie do hiring managerów w firmach klienckich, więc odbiorcą wycieku jest ktoś na zewnątrz. Docstring `delete_candidate` twierdzi, że jedyną pozostałą luką jest `traffit_webhook_events` („To znany brak"), a raport o lukach usuwania ocenia `cv_generated_documents_unlinked` zaledwie na „medium", opisując to jako zatrzymane *dane* — żadne z nich nie wspomina, że żywy, nieuwierzytelniony URL nadal je serwuje.

**Naprawa.** W `delete_candidate`, przed `db.delete(candidate)`, odwołaj każdy token współdzielenia osiągalny z tego kandydata: `UPDATE cv_generated_share_tokens SET revoked=true, revoked_at=now(), revoke_reason='candidate_erasure' WHERE generated_document_id IN (SELECT id FROM cv_generated_documents WHERE candidate_id = :id)`. Niezależnie dodaj do `_generated_doc_or_404` strażnika sprawdzającego istnienie kandydata, tak żeby dokument, któremu wyzerowano `candidate_id` przy `mode='new'`, zwracał 404 — to zamyka tę samą dziurę dla każdej przyszłej ścieżki odpinającej dokument z pominięciem endpointu kasującego.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 69` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f70"></a>

### #70 · P1 · `RedactingFilter` przepisuje wyłącznie `record.msg` — formatter emituje `record.exc_info` osobno, a przy braku `hide_parameters=True` na silniku każdy błąd SQLAlchemy wkłada imię/e-mail/telefon/lokalizację kandydata do linii logu jako parametry bindowane

nakład **M** · obszar **Backend · rdzeń** · **ryzyko** · kategoria `security`

`backend/app/core/logging_config.py:83`

**Co to kosztuje.** Docstring klasy dwie linie wyżej obiecuje, że to „scrubs PII/secrets from every emitted record", a nagłówek modułu podaje powód: „NEXUS ships structured logs to Loki/Grafana, so candidate PII (emails) and any secret that leaks into an exception message must be scrubbed before emission". Filtr dotyka `record.msg` i niczego więcej. `record.exc_info` jest nietknięte, a formatter renderuje z niego traceback niezależnie — odtworzyłem to wprost: po przepuszczeniu przez filtr wiadomość wyszła jako `boom [email]`, podczas gdy ładunek wyjątku dalej brzmiał `IntegrityError [parameters: ('Jan','Kowalski','jan@x.pl','+48601234567')]`. `create_async_engine` w `core/database.py:29-36` nie przekazuje `hide_parameters=True`, więc każdy `StatementError` SQLAlchemy niesie `[SQL: ...]` i `[parameters: (...)]` z prawdziwymi bindowanymi wartościami. Jest 117 miejsc wywołania `logger.exception`, plus własne „Exception in ASGI application" uvicorna dla każdego nieobsłużonego 500 — a `main.py:124-127` kieruje `uvicorn.error` przez ten sam handler. Dla ATS-a, którego logi siedzą w warstwie Loki na 50 GB, to dane osobowe kandydatów lądujące w zewnętrznym systemie observability, który został zbudowany właśnie po to, żeby ich tam nie było.

**Naprawa.** Dwie niezależne poprawki, obie tanie: (a) w `RedactingFilter.filter` przepuszczaj `redact_sensitive` również po sformatowanym wyjątku — ustaw `record.exc_text = redact_sensitive(logging.Formatter().formatException(record.exc_info))`, gdy `record.exc_info` jest obecne, oraz po dodatkowych polach w `record.__dict__`; (b) przekaż `hide_parameters=True` do `create_async_engine`, żeby bindowane wartości w ogóle nie trafiały do stringu wyjątku. Zwróć uwagę, że suite testowy dziś tego nie złapie: oba testy `RedactingFilter` (`tests/test_logging_redaction.py:81`, `:97`) konstruują rekord z `exc_info=None`, a end-to-endowy `test_log_contract_redaction_applies_to_json_output` asertuje wyłącznie na `record["message"]` — żaden test w repo nigdy nie emituje wyjątku przez handler JSON.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 70` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f80"></a>

### #80 · P1 · Ponowne połączenie M365 czyści martwą kolumnę `delta_token_messages` zamiast żywych kursorów per-folder, więc `backfill_completed_at` nigdy nie jest zapisywane ponownie — wieczny spinner „Pobieramy historię" i na stałe wyszarzone „Synchronizuj teraz"

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/microsoft365.py:247`

**Co to kosztuje.** Każdy rekruter, który kiedykolwiek kliknął „Połącz ponownie" na karcie Microsoft 365 w Ustawieniach, zostaje z trwale zepsutym panelem: niebieski alert ze spinnerem „Pobieramy historię (ostatnie 12 miesięcy) — wątki zaczną pojawiać się na profilach kandydatów po zakończeniu backfilla", który nigdy nie znika, i przyciskiem „Synchronizuj teraz" wyszarzonym na zawsze, z tooltipem „Backfill w toku — poczekaj na jego zakończenie". Ręczna furtka awaryjna, na którą wskazują zarówno CLAUDE.md, jak i komentarze w pętli synchronizacji („Artur może wymusić przez `POST /api/microsoft365/sync/trigger`"), to dokładnie ta kontrolka, którą to wyłącza. Drugi, cichszy koszt to ten, który komentarz w linii 246 twierdzi, że kupuje: skrzynka odłączona przez tygodnie (odwołany token, rotacja szyfru, runaway delta-410 → `is_active=False`) NIE dostaje przy ponownym połączeniu ponownego pobrania 12-miesięcznej historii, bo żywe kursory per-folder przeżywają; w najlepszym razie Graph odtwarza od starego `deltaLink`, w najgorszym odpowiada 410 i `sync.py:302` schodzi do fallbacku 30 dni. Maile i załączniki z martwego okna nigdy nie trafiają na profile kandydatów, więc wątek mailowy rekrutera przy kandydacie po cichu zaniża korespondencję. Produkcyjny `/api/health` zwraca `"m365": "healthy"`, co zgodnie z `main.py:1416-1433` wymaga włączonej pętli i ≥1 aktywnego połączenia — to jest żywe, nie uśpione. Efekt uboczny: `conn.synced_through` ma tego samego, jedynego pisarza wewnątrz bloku `if any_backfill:`, więc też zamarza.

**Naprawa.** W gałęzi reconnect w `microsoft365.py` oraz w `services/m365/connection_status.py:32` (`mark_reconnect_required`, który niesie identyczny rozjazd) czyść ŻYWE kursory — `existing.delta_token_inbox = None; existing.delta_token_sent = None` — obok `delta_token_events`. Wtedy `is_backfill` jest `True` dla obu folderów przy najbliższej synchronizacji, ponowne pobranie 12 miesięcy faktycznie się dzieje, a `sync.py:198` stempluje ponownie `backfill_completed_at`, więc baner znika i przycisk znów działa. Albo usuń `delta_token_messages` całkowicie (okno na rollback zamknęło się dawno temu), albo — jeśli musi zostać — dodaj test asertujący, że każde miejsce zapisu dotykające kursora delty nazywa kolumny per-folder; obecnie nie ma zerowego pokrycia testami ani resetu przy reconnect, ani `backfill_completed_at`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 80` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f81"></a>

### #81 · P1 · Sync M365 nie ma bramki per skrzynka: `last_sync_status = running` jest zapisywany i nigdy nie czytany, więc backfill z callbacku OAuth i zaplanowana pętla robią dwa równoległe 12-miesięczne backfille tej samej skrzynki — a wynikające z tego naruszenie UNIQUE zatruwa sesję tak mocno, że nawet commit z samego handlera błędu rzuca wyjątkiem, zostawiając wiersz zablokowany w `running` z `last_sync_at` NULL i bez włączonego 30-minutowego backoffu

nakład **M** · obszar **Backend · serwisy** · **nie działa** · kategoria `broken`

`backend/app/services/m365/sync.py:90`

**Co to kosztuje.** `last_sync_at` jest stemplowany tylko wtedy, gdy sync się KOŃCZY (sync.py:135 oraz w każdej gałęzi błędu), nigdy przy starcie, a jedyne pole, które faktycznie zapisuje „sync jest w toku" — last_sync_status = running — nie jest przez nic konsumowane. Nic w systemie nie jest więc w stanie stwierdzić, że skrzynka jest już synchronizowana. Własny twardy timeout `sync_connection` to 8 minut (`_SYNC_TIMEOUT_SECONDS = 8 * 60`), podczas gdy interwał pętli to 300 s — czyli kod jawnie toleruje sync trwający prawie dwa razy dłużej niż odstęp między decyzjami o zaplanowaniu. Konkretnie oznacza to, że dwa pełne 12-miesięczne backfille tej samej skrzynki działają jednocześnie, z dwóch osobnych AsyncSession trzymających dwie osobne kopie ORM tego samego wiersza `M365Connection`: podwajają każde wywołanie Graph względem limitu throttlingu rekrutera, ściągają każdy załącznik dwa razy do object storage i ścigają się na `setattr(conn, cursor_attr, last_delta_link)` (sync.py:323), więc kursor delta jednego przebiegu po cichu nadpisuje kursor drugiego. Gorzej: `_upsert_message` to SELECT-then-INSERT kluczowany po `m365_message_id`, który ma indeks UNIQUE (alembic/versions/0036_microsoft365.py:227, `unique=True`); gdy oba przebiegi chybią w SELECT i oba zrobią INSERT, przegrany dostaje IntegrityError. `except Exception` per wiadomość w sync.py:311 połyka go i dalej kręci pętlę na sesji, która wymaga już rollbacku, a `await db.commit()` na poziomie strony w linii 317 stoi POZA tym handlerem — więc cała strona maili przepada, a wyjątek ucieka. W ścieżce /sync/trigger `_run()` nie ma ani try/except, ani żadnej referencji, więc ta ucieczka jest niewidoczna: wychodzi wyłącznie jako asyncio-we „Task exception was never retrieved" w momencie GC. Produkcyjne `/api/health` zwraca `"m365": "healthy"`, co zgodnie z main.py:1418-1433 jest osiągalne tylko przy `M365_SYNC_LOOP_ENABLED=true` i co najmniej jednym aktywnym połączeniu.

**Naprawa.** Daj `sync_connection` mutex per połączenie, przez który muszą przejść zarówno pętla, jak i wywołania fire-and-forget. Najtańsza poprawna wersja: nadaj `last_sync_status = running` znaczenie — stempluj obok niego `last_sync_started_at`, dodaj `M365Connection.last_sync_status != M365SyncStatus.running OR last_sync_started_at < now - _SYNC_TIMEOUT_SECONDS` do predykatu pętli w microsoft365_sync.py:95, a samo `sync_connection` niech odmawia (zwraca pusty `SyncResult`), gdy wiersz jest już w stanie running i nie jest przeterminowany. Dodaj tę samą kontrolę do `trigger_backfill`, `_webhook_dispatch_sync` i /sync/trigger, żeby podwójne kliknięcie „Synchronizuj teraz" (rate limit 10/minutę, żadnej innej bramki) nie mogło stackować przebiegów. Niezależnie od tego przerób `_upsert_message` na prawdziwy upsert (`insert(...).on_conflict_do_update(index_elements=[Email.m365_message_id])`), żeby kolizja nie mogła zatruć sesji, i przenieś commit na poziomie strony do handlera, który najpierw robi rollback.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 81` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f82"></a>

### #82 · P1 · Ponowne pobranie wygenerowanej umowy B2B renderuje ją względem ŻYWYCH rejestrów (tabeli klauzul per klient ORAZ mutowalnej tabeli ról), a nie snapshotu — dwa commity w pięć tygodni po cichu zmieniły treść prawną już dostarczonych umów, endpoint nie ma bramki podpisu, a jego docstring twierdzi coś przeciwnego

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `risk`

`backend/app/api/b2b_contract_generator.py:1407`

**Co to kosztuje.** „Pobierz DOCX ponownie" (B2BContractGeneratorV2.tsx:2143, bramkowane wyłącznie na `r.can_download`) to żywy przycisk per wiersz w rejestrze Generatora Umów B2B. Endpoint pobierania NIE ma bramki podpisu — woła tylko `_assert_generator_client_access`, w odróżnieniu od PATCH, który zwraca 409 przy `signature_status == "signed_both"` — więc w pełni podpisaną umowę można pobrać ponownie i uzyskać inną, prawnie wiążącą treść niż wersja faktycznie podpisana przez Partnera i Klienta. Ktokolwiek pobierze ją ponownie (żeby odesłać Partnerowi, dołączyć do audytu, odpowiedzieć na „co dokładnie podpisaliśmy"), dostaje dokument, który czyta się jak autorytatywny, a nim nie jest. Nic w wierszu nie zapisuje, który zestaw klauzul został zastosowany, więc populacji dotkniętych umów nie da się nawet wyliczyć po fakcie: `B2BGeneratedContract` nie ma kolumny override, `render_payload` to gołe `payload.model_dump(mode="json")` danych z formularza, w clause_overrides.py / clause_override_content.py / docx_renderer.py nie ma zerowego logowania, a `B2BRenderHtmlResponse` niesie tylko `{html, contract_number}`. Po incydencie z 2026-07-28, w którym BNP Paribas Cardif dowodnie dostał §4 innego banku, nie było jak wylistować, które umowy wyszły błędnie.

**Naprawa.** Dwa kroki, najpierw tani. (1) Zrób snapshot rozstrzygnięcia w momencie generacji: dodaj kolumnę `override_key` (albo wpis `render_payload['_clause_override']`) zapisującą, który wpis `CLIENT_OVERRIDES` wygrał, plus stempel wersji rejestru — to jest retroaktywnie użyteczne dla audytu Cardif i nie zmienia zachowania renderu. (2) Spraw, żeby ponowne pobranie serwowało snapshot zamiast rozstrzygać na nowo: albo zapisz rozstrzygnięte operacje (lub wyprodukowane bajty DOCX) w wierszu, albo zwiąż render ze ostemplowaną wersją rejestru. Popraw docstring w tej samej zmianie — w obecnym brzmieniu zachęca wołających, by traktowali ponowne pobranie jako dowód tego, co zostało podpisane. Docelowo przenieś wybór z wolnego tekstu nazwy na `B2BGeneratedContract.client_id` (kolumna już jest w wierszu), używając wzorca listy z env stosowanego przy bramkach zamówień kosztowych, zostawiając nazwę tylko do wyświetlania.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 82` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f86"></a>

### #86 · P1 · Sortowanie „Nazwisko (A-Z)" na liście kandydatów wykonuje ORDER BY pod kolacją bajtową musl (i sortuje po IMIENIU, nie po nazwisku) — placeholdery „?" lądują na stronie 1, nazwiska na Ł i wszelkie nazwy z małej litery trafiają za Z; to samo sortowanie zasila eksport dla klienta

nakład **M** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/candidates.py:1091`

**Co to kosztuje.** To największa pojedyncza powierzchnia w produkcie — lista rekrutera nad ~49 tys. kandydatów — a „Nazwisko (A-Z)" to jedna z zaledwie czterech oferowanych opcji sortowania (frontend/src/components/v2/pages/CandidatesListV2.tsx:406). Ponieważ porządkowanie robi się w SQL-u pod kolacją, która nie ma pojęcia o polszczyźnie, a strona jest cięta po stronie serwera przez OFFSET/LIMIT, każdy kandydat, którego imię zaczyna się na Ł, Ś, Ż, Ź, Ć, Ó, Ą, Ę albo Ń, nie jest po prostu wyświetlany nisko — jest NIEOBECNY na każdej stronie poza kilkoma ostatnimi. Łukasz to jedno z najpospolitszych polskich imion męskich w bazie kandydatów IT; rekruter alfabetyzujący listę, żeby systematycznie ją przerobić, pominie całą tę grupę. Repozytorium raz już zdiagnozowało dokładnie ten defekt i naprawiło go w Pythonie dla jednego dropdownu (client_order_lines.py:189: „prod nie ma rozszerzenia `unaccent`, więc «Łukasz» w SQL-u wylądowałby za «Zbigniewem»"), ale poprawka nigdy nie trafiła na listę kandydatów.

**Naprawa.** ICU jest już wkompilowane w spinowany obraz — zweryfikowałem 908 wierszy w `pg_collation` z `collprovider='i'` oraz że `'Łukasz' < 'Zbigniew' COLLATE "pl-PL-x-icu"` zwraca prawdę, bez instalacji rozszerzenia i bez potrzeby superusera. Zmień ORDER BY na `Candidate.name.collate('pl-PL-x-icu')` / `Candidate.lastname.collate('pl-PL-x-icu')`; jeśli koszt sortowania nad 49 tys. wierszy ma znaczenie, podeprzyj to indeksem wyrażeniowym `CREATE INDEX ... ON candidates (lastname COLLATE "pl-PL-x-icu", name COLLATE "pl-PL-x-icu")` (plus lustro w entrypoint.sh). Alternatywa — użycie `normalize_person_name_part` jako klucza sortowania w kolumnie generowanej STORED, na wzór tego, co migracja 0159 zrobiła już dla `search_doc_unaccented` — utrzymuje porządkowanie niezależne od kolacji i jest bezpieczniejszym wyborem w świetle znaleziska #4.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 86` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f88"></a>

### #88 · P1 · Porządkowanie polskich nazw na prodzie jest porządkiem bajtowym, bo DB stoi na musl — lista kandydatów wydaje sortowanie opisane „Nazwisko (A-Z)", które wyrzuca każdą nazwę na Ł/Ś/Ż za Z, a `lower()` użyte na listach klientów naprawia tylko połowę dotyczącą wielkości liter

nakład **M** · obszar **Backend · API** · **dług** · kategoria `debt`

`backend/app/api/clients.py:269`

**Co to kosztuje.** `func.lower()` nie jest wyborem stylistycznym — to częściowe obejście dokładnie tego problemu z kolacją (porządek bajtowy stawia każdą małą literę za każdą wielką, więc bez tego 'adam' sortuje się za 'Zbigniew'). Zweryfikowałem, że ta połowa działa: na musl `lower('ŁUKASZ')` poprawnie zwraca 'łukasz', bo musl implementuje unicodowe mapowanie wielkości liter, choć nie implementuje żadnej kolacji. Ale połowa diakrytyczna jest nietknięta — 'ł' to U+0142, bajty C5 82, wciąż większe niż 'z' pod 0x7A. Więc ktokolwiek pisał te dwie linie, trafił w objaw, naprawił składową wielkości liter i wydał zmianę w przekonaniu, że porządkowanie jest poprawne. To gorsze niż zwykłe miejsca z `ORDER BY name`, bo czyta się jak problem rozwiązany. Istnieją teraz trzy równoległe implementacje jednej reguły (normalizacja w Pythonie / `lower()` / w ogóle nic), rozrzucone po 26+ porządkowaniach, bez wspólnego helpera i bez testu, który pinuje którekolwiek z nich.

**Naprawa.** Wybierz jedną regułę i uczyń ją jedyną. Albo (a) wspólny SQL-owy helper `polish_sort_key()` zwracający `<col> COLLATE "pl-PL-x-icu"`, używany przez każde widoczne dla użytkownika ORDER BY na kolumnie z nazwą/tytułem, albo (b) rozszerz podejście `normalize_person_name_part`, którego skuteczność `client_order_lines` już dowodzi, jako kolumny generowane STORED we wzorcu, który migracja 0159 ustanowiła dla `search_doc_unaccented`. Potem dodaj jeden test, który sortuje fixture zawierający Łukasz/Świderski/Ćwikła/Żabka i asertuje, że lądują przed Z — dziś takiego testu nie ma nigdzie w żadnej połowie repo.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 88` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f89"></a>

### #89 · P1 · Polskie nazwiska już teraz sortują się źle pod musl (rozpoznane w repo, ale błędnie zdiagnozowane jako brak `unaccent`), a jednolinijkowa „naprawa" — podmiana niepinowanego obrazu `postgres:16-alpine` — po cichu psuje każdy tekstowy btree: bez ostrzeżenia, bez healthchecku, bez sprawdzenia driftu, bez ścieżki REINDEX

nakład **M** · obszar **Infra** · **ryzyko** · kategoria `risk`

`docker-compose.yml:24`

**Co to kosztuje.** Collation, według której cały ten ATS sortuje polskie nazwiska, jest wybierana niejawnie przez jeden nieopisany tag obrazu. `grep -rn 'lc_collate|datcollate|pg_collation|COLLATE "'` po backend/app, backend/alembic i backend/tests nie zwraca nic; `/api/health/deep` sonduje 42 tabele, ale nie collation; `admin_schema_drift` jej nie sprawdza. Dwie konsekwencje zmierzone bezpośrednio. Po pierwsze, katalog kłamie: `postgres:16-alpine` i `postgres:16` oba raportują `datcollate = en_US.utf8`, a mimo to `'Łukasz' < 'Zbigniew'` jest fałszem na pierwszym i prawdą na drugim — więc każdy, kto „sprawdzi collation" czytając `pg_database`, dostaje złą odpowiedź. Po drugie, i gorzej: `datcollversion` jest PUSTYM STRINGIEM pod musl (zmierzyłem `''` na alpine vs `'2.41'` na obrazie glibc). PostgreSQL podnosi swoje ostrzeżenie „collation version mismatch, rebuild indexes" tylko wtedy, gdy zapisana wersja jest niepusta i różna — więc na tym wdrożeniu ten mechanizm bezpieczeństwa nie może wystrzelić nigdy. Oczywista naprawa dla findingów #1-#3 — przejście na obraz z glibc albo z providerem ICU, żeby dostać poprawne polskie sortowanie — wykonana na istniejącym wolumenie `nexus-prod-storage` przestawiłaby porządek porównań tekstu pod każdym indeksem btree zbudowanym na kolumnie tekstowej, bez jednej linijki w logu. Skany po indeksie zaczęłyby wtedy gubić istniejące wiersze, a ograniczenia UNIQUE na tekście przestałyby łapać duplikaty: `uq_stage_name_in_template (template_id, name)` pilnuje polskich nazw etapów pipeline'u (pipeline_template.py:113), a importer już na nim polega (traffit/importer.py:1348). 225 instrukcji `CREATE INDEX IF NOT EXISTS` w entrypoincie ma dokładnie zły kształt do odtworzenia — `IF NOT EXISTS` pomija indeks, który istnieje, ale jest teraz źle uporządkowany.

**Naprawa.** Trzy tanie kroki, żaden nie wymaga wcześniejszego rozstrzygnięcia kwestii sortowania. (1) Dodaj `datcollate`, `datlocprovider`, `datcollversion` oraz żywą sondę `SELECT 'Ł' < 'Z'` do `/api/health/deep`, żeby odpowiedź przestała być nieznana, a zmiana stała się widoczna w smoke teście. (2) Postaw komentarz przy docker-compose.yml:24 mówiący, że ten tag decyduje o porządku tekstu, że musl nie raportuje wersji collation, więc Postgres nie ostrzeże, i że nigdy nie wolno go zmieniać na istniejącym wolumenie bez `REINDEX DATABASE` — repo już używa tego stylu nośnego komentarza przy qdrant v1.17.1 dwie usługi niżej. (3) Jeśli porządek zostanie naprawiony przez ICU per kolumna (finding #1), collation ICU MA wersję (`pl-PL-x-icu` raportuje `153.136.48`), więc ostrzeżenie PostgreSQL o dryfie zacznie działać dokładnie dla tych indeksów, o które chodzi.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 89` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f91"></a>

### #91 · P1 · `GET /api/settings/ai` zwraca 500 na prodzie: niefiltrowany `select(AIFeatureConfig)` hydratuje osierocone wiersze `ai_features` (pozostawione przez revert #703 → #713) do `AIFeatureKey` i podnosi `LookupError`, więc jedyny w produkcie panel limitów wydatków AI / kill-switcha jest nieosiągalny

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/ai_settings.py:69`

**Co to kosztuje.** To jedyna powierzchnia w produkcie, gdzie admin może (a) zobaczyć zużycie AI per funkcja, (b) ustawić `monthly_limit`, który zakończyłby stan bez limitu, i (c) przełączyć globalny kill-switch AI. Wszystkie trzy są nieosiągalne na prodzie. Gałąź błędu we froncie (settings/ai/page.tsx:363-374) renderuje „Nie udało się załadować ustawień AI. Sprawdź czy masz uprawnienia administratora." — więc adminowi mówi się, że to problem z uprawnieniami, i przestaje szukać. To niemal na pewno powód, dla którego wszystkie 11 funkcji stoi na `monthly_limit = 0` i nikt nic z tym nie zrobił. Gorzej: `PATCH /settings/ai/master` commituje przełącznik, a POTEM zwraca `await get_ai_settings(admin, db)` (ai_settings.py:119-121), co rzuca wyjątkiem — więc admin próbujący ubić wydatki na AI w trakcie incydentu widzi „Nie udało się zapisać zmiany" przy zmianie, która faktycznie się utrwaliła, i nie ma działającego panelu, żeby sprawdzić realny stan.

**Naprawa.** Odwzoruj naprawę już zastosowaną w sondzie health: wybieraj `cast(AIFeatureConfig.feature, Text)` plus kolumny skalarne zamiast obiektów ORM, buduj `FeatureConfig` tylko dla wartości, które rozwiązują się do `AIFeatureKey`, a nierozwiązywalne wiersze pokazuj jako osobną listę „stale config" zamiast po cichu je gubić. Potem migracja danych (plus lustro w entrypoint.sh, bo prodowy alembic jest osierocony), która usuwa wiersze `ai_features`, których `feature` nie jest elementem `AIFeatureKey`. Dodaj test integracyjny, który obiecywał własny docstring pliku z testami schematów i którego nigdy nie dostarczono: tests/test_ai_settings_schemas.py:4-6 mówi „Integration coverage (actual ``/api/settings/ai`` endpoints) lives in tests/test_api_integration.py once we wire it through `app_client`" — grep potwierdza, że żaden test w repo nie woła tej trasy, i dlatego 500 na prodzie pozostało niewidoczne.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 91` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f93"></a>

### #93 · P1 · Obciążenie kwoty nie deklaruje wywołania: osiem ścieżek płaci przez gołe `check_and_increment` i mimo to loguje się jako „UNGATED" na granicy providera — zatruwa to detektor, na którym opiera się `AI_QUOTA_STRICT`, i już teraz podwójnie obciąża jedną żywą ścieżkę

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `risk`

`backend/app/api/cv_match_preview.py:235`

**Co to kosztuje.** Bramka na granicy providera to jedyny mechanizm produktu do znajdowania wywołań LLM, których nikt nie obciążył — ai_quota.py:216-222 tłumaczy, że istnieje właśnie dlatego, że „trzy z pięciu ścieżek docierających do Claude'a bez sprawdzenia kwoty w ogóle nie są trasami". Dziś wyjście tego detektora to w większości fałszywe alarmy: osiem poprawnie obciążonych ścieżek emituje to samo ostrzeżenie „UNGATED LLM call" + 8-ramkowy stos co jedna faktycznie nieobjęta bramką powierzchnia (MINDY, finding #2), więc w logu są nie do odróżnienia. claude_client.py:113-117 argumentuje, że wybrano WARNING po to, żeby „pojedyncze zapomniane miejsce wywołania nie emitowało jednego wpisu na wywołanie i nie zasypało realnych błędów" — szum jest teraz większością, a okno obserwacji, któremu to miało służyć, nie może niczego rozstrzygnąć. Gorsze jest utajone: przełączenie `AI_QUOTA_STRICT=true` — udokumentowany koniec tego cyklu obserwacji — sprawia, że `_assert_declared` rzuca `AIQuotaUngated` wewnątrz `call_claude` na wszystkich ośmiu. Parsowanie PDF zamówień i parsowanie CV połykają to i po cichu degradują do fallbacków regex/Ollama (gorzej wyciągnięte dane, żadnego błędu na ekranie); publiczny czat interaktywnego CV zamienia to w 502 dla hiring managera; zadanie w tle budujące mapę wymagań i podsumowanie aktywności kandydata padają wprost.

**Naprawa.** Uczyń `check_and_increment` niepublicznym dla wołających i przekonwertuj wszystkie osiem miejsc na `async with ai_feature(...)`, które obciąża i deklaruje w jednym kroku (usuń zbędne już obciążenie na poziomie trasy w notes.py, patrz finding #4). Potem dodaj test-strażnik, który przechodzi AST w poszukiwaniu wywołań `check_and_increment` poza ai_quota.py i pada na każdym nowym — istniejący zestaw ma test na surową konstrukcję `anthropic.Anthropic()` (test_ai_quota_provider_gate.py::test_no_new_raw_provider_client_appears), ale nic równoważnego dla kształtu „obciąż bez deklaracji". Przełącz `AI_QUOTA_STRICT` dopiero, gdy ta lista będzie pusta.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 93` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f96"></a>

### #96 · P1 · Wtyczka LinkedIn ma JEDYNĄ ścieżkę logowania — email+hasło — a prod zwraca na niej 503, bo logowanie hasłem jest wyłączone; wtyczka nie ma przycisku Microsoft SSO i nikt tego nie testuje

nakład **L** · obszar **Wtyczka** · **nie działa** · kategoria `broken`

`extension/src/shared/api-client.js:108`

**Co to kosztuje.** Rekruter, który instaluje wtyczkę (albo wyczyścił profil Chrome, albo nie używał jej przez 30 dni, albo dostał zmianę roli — co bumpuje `authorization_version` i unieważnia refresh token) NIE MA jak się zalogować. Modal na LinkedInie na stałe pokazuje „Aby dodawać kandydatów, zaloguj się do NEXUS", a strona ustawień wypluwa surowy blob `Login failed (HTTP 503): {"detail":"Logowanie hasłem jest wyłączone. Zaloguj się przez Microsoft."}` — bez żadnej podpowiedzi, bo wtyczka nie ma przycisku Microsoft SSO. Jedyna ścieżka „jednym kliknięciem z LinkedIna do bazy" jest dla nowego użytkownika martwa. Osobno: to jest dowód, że zmiana w backendzie potrafi cicho zabić ten klient — nic go nie testuje, nie ma go w żadnym workflow, żaden healthcheck go nie dotyka, więc awaria z 19 lipca przeżyła miesiąc bez śladu.

**Naprawa.** Najpierw zdecyduj, korzystając z odpowiedzi, którą ten finding już daje: jeśli nikt nie trzyma sesji sprzed 19 lipca, `git rm -r extension/` i usuń osierocony router `/api/candidates/from-linkedin` (ma ZERO wołających w frontend/src — zweryfikowane grepem — więc wtyczka jest jego jedynym klientem). Jeśli wtyczka jest nadal w użyciu, ścieżka autoryzacji musi przeżyć tryb SSO-only. Repo już dostarczyło właściwy mechanizm w migracji 0220: konta serwisowe z `X-API-Key`, scope'y per konto czytane na świeżo przy każdym requeście, obowiązkowe wygasanie i natychmiastowa rewokacja. Potrzeba jednej nowej wartości w `ServiceScope` (np. `candidate:write_linkedin`) i `require_service_scope(...)` na dwóch endpointach wtyczki; strona ustawień przyjmuje wtedy wklejony klucz `nxs_v2_…` zamiast hasła, co przy okazji usuwa 30-dniowy refresh token z `chrome.storage` w całości. Tak czy inaczej, dodaj extension/ do joba CI (eslint + test kontraktowy asertujący trzy ciała requestów przeciwko zacommitowanemu openapi.json), żeby następne przełączenie w backendzie nie mogło go znowu po cichu zabić.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 96` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f97"></a>

### #97 · P1 · POST /api/candidates/from-linkedin zapisuje `CandidateStage` dla już istniejącego kandydata po sprawdzeniu WYŁĄCZNIE werdyktu hiring managera — cztery twarde powody niedopuszczalności (globalna czarna lista, czarna lista klienta, NDA, konkurent) nie są w ogóle sprawdzane, a ta sama niepełna bramka istnieje w POST /api/jobs/{job_id}/candidates („Dodaj championa z historii")

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/candidates.py:2546`

**Co to kosztuje.** Kandydat objęty NDA z klientem, wpisany przez tego klienta na czarną listę, albo oznaczony jako konflikt konkurencyjny, trafia do pipeline'u TEGO klienta jednym kliknięciem — i to od razu na dowolny z czterech etapów oferowanych w modalu, łącznie z `interview`. To jest dokładnie ta klasa zdarzenia, przed którą bramka powstała: konsekwencje są prawne (naruszenie NDA) i handlowe (przedstawienie klientowi osoby, którą sam wcześniej zablokował), a nie kosmetyczne. Wiersz ląduje w bazie po cichu — 409 z polskim powodem, który rekruter zobaczyłby wchodząc tą samą osobą przez rekomendacje albo przez kanban, tutaj nie pada. Ścieżka dedupu to NIE jest przypadek brzegowy: przy 49 tys. kandydatów w bazie „ten profil już mamy" jest normą, a nie wyjątkiem — to cały sens gałęzi „Już w bazie".

**Naprawa.** Dodaj bramkę wewnątrz `_assign_candidate_to_job` (candidates.py:2415), żeby objąć oba miejsca wywołania naraz: `Job` jest tam już załadowany na potrzeby sprawdzenia 404, więc `await assert_candidate_move_eligible(db, candidate_id=candidate_id, job=job, now=datetime.now(timezone.utc), enforce_manager_verdict=False)` — `enforce_manager_verdict=False`, bo wywołujący w :2539 sam już rozstrzyga werdykt i świadomie degraduje go do `assignment_skipped_reason` zamiast 409. Następnie przechwyć `HTTPException(409)` w miejscu wywołania na ścieżce dedupu i przekieruj jego polski `detail` do TEJ SAMEJ zmiennej `assignment_skipped`, która już istnieje (:2544) — dzięki temu reużywasz istniejący kontrakt degradacji wtyczki zamiast wywalać cały dodawany rekord. Rozszerz wzorzec AST w backend/tests/test_index_coverage_write_paths.py o drugi guard, asertujący, że każda funkcja zapisująca `CandidateStage` woła jeden z helperów dopuszczalności — ta sama technika strukturalna, która już chroni niezmiennik indeksowania.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 97` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f202"></a>

### #202 · P1 · Każda z 11 funkcji AI działa na prodzie bez miesięcznego sufitu — warstwa kwot jest fail-open, a limit z Ustawienia→AI nie jest egzekwowany nigdzie

nakład **S** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/services/ai_quota.py:172`

**Co to kosztuje.** Żywe prodowe `/api/health` zwraca w tej chwili `"ai_features": "uncapped: candidate_summary,champion_draft,champion_profile_parse,cv_backfill,cv_interactive_chat,cv_parser,cv_requirement_map,job_description_generator,notes_extraction,order_parser,scoring"` — to wszystkie 11 wartości `AIFeatureKey` (backend/app/models/ai_feature.py:47-62). Komentarz samej sondy health (backend/app/main.py:1673) dokumentuje, że „uncapped" obejmuje zarówno brak wiersza, jak i `monthly_limit = 0`, a docstring `ai_quota.py` potwierdza `monthly_limit = 0` → bez limitu. Przy `limit = 0` powyższa gałąź nie może się nigdy odpalić, więc `check_and_increment` niczego nie blokuje. Panel Ustawienia→AI obiecuje adminowi miesięczny sufit per funkcja („Traffit pokazuje 2 994 / 20 000 scoringów" wg docstringu modelu); na prodzie to pole nie robi nic dla żadnej funkcji. Najostrzejsza ekspozycja to `cv_interactive_chat`, dostępny dla hiring managerów w ogóle bez konta w NEXUSIE: public_share.py:404 dokumentuje warstwy jako „rate limit (IP), dzienny limit pytań per link (429), globalna kwota AI (503)" — dzienny limit jest PER LINK, więc N udostępnionych linków do CV = N × `CV_INTERACTIVE_CHAT_DAILY_LIMIT` wywołań Claude'a dziennie, a jedynym globalnym zabezpieczeniem jest kwota, która obecnie jest bez sufitu. `cv_backfill` (masowe wzbogacanie ~39k CV, z własnym kubełkiem właśnie po to, żeby nie wyczerpał limitu rekruterów) i `scoring` mają ten sam brak podłogi.

**Naprawa.** Zasiej wiersz w `ai_features` dla każdej z 11 wartości `AIFeatureKey` ze świadomym `monthly_limit > 0` (funkcje interaktywne mogą dostać hojne wartości; `cv_backfill` i `notes_extraction` powinny dostać liczbę wielkości wsadu, a `cv_interactive_chat` wartość, która przetrwa zły tydzień na jednym udostępnionym linku). Zrób to jako migrację plus lustro DDL w `entrypoint.sh`, żeby przeżyło ścieżkę z osieroconym alembikiem. Potem potwierdź, że `/api/health` raportuje `checks.ai_features == "healthy"` — ten string jest testem akceptacyjnym.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 202` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f203"></a>

### #203 · P1 · Nocny E2E na produkcji jest czerwony od 12+ nocy z rzędu na etykiecie zmienionej trzy tygodnie temu — jedyny automatyczny test dotykający produkcji to martwy alarm

nakład **S** · obszar **Testy** · **dług** · kategoria `test-gap` · **rekonesans — nieweryfikowane adwersarialnie**

`frontend/e2e/candidate-ux-preview.spec.ts:104`

**Co to kosztuje.** `gh run list --workflow e2e.yml` to failure na każdym nocnym biegu od 2026-08-09 do 2026-08-20 (12 z rzędu, a etykieta zmieniła się 2026-07-30, więc niemal na pewno dłużej). Log runu 32328497187 pada dokładnie na linii 104: „Error: expect(locator).toBeVisible() failed / element(s) not found". String „Oczekiwana stawka" występuje dziś tylko w jednym komponencie w całym froncie (CandidateNotesInsightsCard.tsx:230) i w ogóle nie ma go w quick view. To jedyny zestaw testów, który leci przeciw https://nexus.dynaminds.pl — `e2e.yml` jest wyłącznie z harmonogramu i jawnie „nie blokuje CI na poziomie PR", więc nic od niego nie zależy i nikt nie jest zmuszony patrzeć. Komentarz w workflow (e2e.yml:34-38) mówi, że listę projektów przycięto do publicznych speców preview-chromium właśnie po to, „żeby nocny bieg był zielony i uczciwy"; ta intencja jest przekreślona od trzech tygodni. Prawdziwa regresja produkcyjna w quick view kandydata — powierzchni, której rekruterzy używają do triage'u 53k kandydatów — dawałaby dziś dokładnie ten sam czerwony X co przeterminowana asercja i byłaby od niej nie do odróżnienia.

**Naprawa.** Zmień linię 104 tak, żeby asertowała etykietę, którą harness faktycznie renderuje („Stawka B2B"), albo lepiej — asertuj po stabilnym id `KeyFact`, a nie po widocznym polskim stringu, żeby zmiana tekstu nie mogła znowu zepsuć alarmu. Potem odpal `gh workflow run e2e.yml` i potwierdź zieleń, zanim zaufasz temu kanałowi. Osobno warto zdecydować, czy zestaw z harmonogramu, od którego nic nie zależy, nie powinien kogoś wołać, gdy jest czerwony dłużej niż dwie noce z rzędu.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 203` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f204"></a>

### #204 · P1 · Workflow dziennego digestu Sentry raportuje sukces każdego ranka, nie robiąc nic — `SENTRY_AUTH_TOKEN` nigdy nie został ustawiony, więc krok kończy się natychmiast z kodem 0

nakład **S** · obszar **CI/CD** · **ryzyko** · kategoria `ops` · **rekonesans — nieweryfikowane adwersarialnie**

`.github/workflows/sentry-daily-monitor.yml:38`

**Co to kosztuje.** `gh secret list` na repo zwraca dokładnie cztery sekrety (`CLAUDE_CODE_OAUTH_TOKEN`, `COOLIFY_APP_UUID`, `COOLIFY_TOKEN`, `COOLIFY_URL`) — ani `SENTRY_AUTH_TOKEN`, ani `SLACK_WEBHOOK_URL` nie istnieje. API GitHuba dla najnowszego biegu (32342419428, 2026-08-20 07:05) pokazuje, że job wystartował 07:05:39 i zakończył się 07:05:45 z każdym krokiem „success": sześć sekund łącznie, czyli checkout plus setup-python — `sentry_daily_digest.py` w ogóle się nie wykonuje. Pięć ostatnich biegów z harmonogramu (08-16 do 08-20) jest zielonych. Zgodnie z ~/.claude/rules/observability.md Sentry to wyznaczony kanał błędów i wydajności dla `nexus-be` i `nexus-fe`; dzienny digest jest mechanizmem, który miał postawić przed człowiekiem pythonowe 500 albo error boundary Reacta. W tej chwili jedyny automatyczny sygnał produkcyjny, który do kogokolwiek dociera, to uptime-probe (sprawdzający, czy baza odpowiada na `SELECT 1`) i disk-alert. Burza wyjątków w backendzie daje zielony dashboard Actions.

**Naprawa.** Zapewnij `SENTRY_AUTH_TOKEN` (Sentry → Settings → Auth Tokens, scope read na b2bnet-sa) i `SLACK_WEBHOOK_URL` jako sekrety repo, potem `gh workflow run sentry-daily-monitor.yml` i potwierdź, że digest faktycznie się publikuje. Zmień też gałąź pomijania z `exit 0` na `exit 1` — backup drill nauczył się tej lekcji w tym samym repo („Drill DR, którego nie da się uruchomić, to drill PADNIĘTY"); monitor, który nie może monitorować, musi być czerwony, nie zielony.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 204` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f207"></a>

### #207 · P1 · Kontener backendu nie ma healthchecka w jedynym pliku compose, który czyta Coolify — definicja siedzi w `docker-compose.prod.yml`, o którym nagłówek tego samego pliku mówi, że na prodzie nigdy nie jest stosowany

nakład **S** · obszar **Infra** · **ryzyko** · kategoria `ops` · **rekonesans — nieweryfikowane adwersarialnie**

`docker-compose.yml:114`

**Co to kosztuje.** To identyczna klasa defektu, którą zespół już znalazł i naprawił dla `mem_limit` 2026-08-12 — poprawka przeniosła limity pamięci z overlayu i zostawiła healthcheck na miejscu. Dwie konkretne konsekwencje na prodzie. Po pierwsze, rolling update Coolify przełącza Traefika na nowy kontener, gdy tylko Docker zgłosi „running", czyli w momencie startu `entrypoint.sh` — zanim skończą się `alembic upgrade heads`, ~5000-liniowa siatka bezpieczeństwa DDL, `seed.py` i import portfela klientów. `start_period: 60s`, napisany specjalnie jako „zapas na alembic upgrade head uruchamiany w entrypoint na starcie", nigdy nie obowiązywał, więc każdy deploy ma realne okno 502 dla rekruterów w trakcie pracy. Po drugie, `restart: unless-stopped` reaguje tylko na wyjście procesu, nigdy na unhealthy — backend, który stoi, ale się zakleszczył (wyczerpana pula połączeń, jedna z 24 pętli w tle blokująca event loop, alembic wiszący na locku), będzie tam siedział i nie serwował niczego w nieskończoność. Smoke test w workflow deployu łapie to tylko w chwili deployu; o 03:00 we wtorek nie ma żadnego sygnału. Frontend też ma `depends_on: - backend` bez `condition`, więc również nie może czekać.

**Naprawa.** Przenieś blok healthcheck dosłownie z docker-compose.prod.yml:27-38 do serwisu backend w `docker-compose.yml` (curl jest już zainstalowany w backend/Dockerfile, linia 24). Przy okazji zmień frontendowe `depends_on: - backend` na `backend: {condition: service_healthy}`. Rozważ też danie healthchecka Qdrantowi — nie ma żadnego, a backend na niego nie czeka. Zweryfikuj po deployu przez `docker inspect --format '{{.State.Health.Status}}' <backend>`, tak samo jak wyłapano `Memory=0` 2026-08-12.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 207` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f208"></a>

### #208 · P1 · Automatyczne review PR-ów pada na 100% PR-ów Dependabota, bo `dependabot` nie jest w `allowed_bots` — jedyna klasa PR-ów zmieniająca kod firm trzecich to jedyna klasa, której nikt nie recenzuje

nakład **S** · obszar **CI/CD** · **ryzyko** · kategoria `ops` · **rekonesans — nieweryfikowane adwersarialnie**

`.github/workflows/claude-review.yml:33`

**Co to kosztuje.** Dwa osobne koszty. (a) Review, które `ci-cd-unified.md` nazywa główną bramką jakości dla repo solo-deva, po cichu nigdy nie odpala się na zmianach zależności — dokładnie na tej powierzchni supply chain, którą przyszedłby skompromitowany albo psujący pakiet, i dokładnie na klasie, na której to repo już się przejechało (bump `qdrant-client` 1.18 przeszedł CI i healthcheck, podczas gdy wyszukiwanie semantyczne po cichu zwracało „brak wyników"). (b) Każdy PR Dependabota nosi trwały czerwony X. `review` nie jest wymaganym kontekstem, więc nie blokuje merge'a — co jest gorsze, nie lepsze: uczy właściciela mergować PR-y z zależnościami mimo czerwonego checka i bez patrzenia, więc w dniu, w którym padnie tam prawdziwy check, będzie nie do odróżnienia od stałego szumu. Tymczasem pociąg stoi: nic nie zostało zmergowane od 2026-07-27, a sam PR #1167 niesie uvicorn 0.52.1→0.52.3 (dwie poprawki parsowania requestów HTTP/1.1 na ścieżce żądania), sqlalchemy, sentry-sdk i boto3. Awaria jest strukturalna, nie przejściowa: nawet po dopuszczeniu aktora log pokazuje `claude_code_oauth_token: ""`, bo biegi w kontekście Dependabota czytają ze store'u sekretów Dependabota, nie Actions.

**Naprawa.** Albo pomiń job czysto dla Dependabota, żeby przestał emitować fałszywą czerwień — dodaj `github.actor != 'dependabot[bot]'` do istniejącego `if: vars.CLAUDE_ENABLED == 'true'` — albo, lepiej, recenzuj je porządnie: odpalaj przez `pull_request_target` (lub follow-up przez `workflow_run`), żeby token OAuth rozwiązywał się ze store'u sekretów Actions, i dodaj `dependabot` do `allowed_bots`. Nie używaj `allowed_bots: '*'`; wybór jednego nazwanego bota w linii 32 jest świadomy i słuszny. Osobno: opróżnij 10 otwartych PR-ów przez `scripts/merge-train.sh`, zaczynając od trzech grup minor-patch.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 208` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f212"></a>

### #212 · P1 · Suite E2E w Playwrighcie nie weryfikuje niczego: 40 z 46 przypadków testowych nigdy się nie wykonuje z braku sekretów, a jedyny projekt, który faktycznie chodzi, jest czerwony od 21 nocy z rzędu

nakład **M** · obszar **CI/CD** · **dług** · kategoria `test-gap` · **rekonesans — nieweryfikowane adwersarialnie**

`.github/workflows/e2e.yml:41`

**Co to kosztuje.** Każdy zalogowany przepływ użytkownika w ATS — logowanie, tworzenie kandydata, przesuwanie kandydata między etapami pipeline'u, pisanie notatki z @wzmianką, ręczne wyszukiwanie CV, UX dopasowań, rekomendacje, ekrany admina dynareportera — nie ma ŻADNEJ weryfikacji na poziomie przeglądarki i nie ma jej co najmniej od 2026-07-16. Ta luka nakłada się na 27,2% pokrycia unitami we frontendzie, gdzie każda strona route'u `src/app/**` poza `/login` ma 0% statements. W połączeniu z findingiem #4 (klient API jest mockowany w 51 ze 148 testów jednostkowych) nic w tym repozytorium nigdy nie steruje prawdziwą stroną wobec prawdziwego backendu. Regresja w przejściach etapów albo w tworzeniu kandydata trafia najpierw do rekruterów.

**Naprawa.** Dwie rozdzielne naprawy. Natychmiastowa (S): zmienić `e2e/candidate-ux-preview.spec.ts:104` na `getByText("Stawka B2B")`, żeby nocny bieg przestał podnosić fałszywy alarm. Właściwa naprawa (M): sprovisionować E2E_USER_EMAIL/E2E_USER_PASSWORD dla dedykowanego prodowego konta E2E, żeby projekt `chromium` faktycznie chodził, i albo dodać powiadomienie o porażce nocnego biegu, albo przyjąć do wiadomości, że trwale czerwony, nieoglądany workflow jest gorszy niż brak workflow.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 212` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f213"></a>

### #213 · P1 · next.config.ts wyłącza type-checking i linting podczas `next build`, co unieważnia dokładnie tę siatkę bezpieczeństwa, na którą powołuje się ci-gate.yml, uzasadniając brak bramkowania deployu na frontendzie

nakład **S** · obszar **Frontend · UI** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`frontend/next.config.ts:12`

**Co to kosztuje.** Pipeline deployu wierzy, że ma dwie niezależne kontrole frontendu, a ma jedną. Rekruterzy dostają białą stronę albo stronę, która rzuca wyjątkiem przy montowaniu, a jedynym sygnałem jest czerwony job „CI" na main, który ląduje już po tym, jak produkcja serwuje zepsuty bundle. Udokumentowana ścieżka odzyskania to rollback w Coolify, czyli minuty niedostępności narzędzia, w którym pracuje cały zespół rekrutacyjny.

**Naprawa.** Najtańsza poprawna naprawa: dodać do ci-gate.yml job `frontend-fast` odpalający `npm ci --legacy-peer-deps && npm run type-check` (~2 min, mieści się w budżecie bramki), żeby bramka deployu faktycznie pokrywała to, co twierdzi jej komentarz. Alternatywnie zdjąć `typescript.ignoreBuildErrors`, żeby build w Coolify naprawdę był drugą kontrolą — ale to spowalnia każdy rebuild produkcyjny, czyli dokładnie to, czemu ta flaga miała zapobiec. Tak czy inaczej komentarz z uzasadnieniem w ci-gate.yml musi przestać powoływać się na kontrolę, która nie istnieje.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 213` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f217"></a>

### #217 · P1 · Produkcyjne Swagger UI, ReDoc i openapi.json są publiczne i bez uwierzytelnienia — 747 endpointów i 876 schematów ATS-a do wyliczenia przez każdego

nakład **S** · obszar **Backend** · **ryzyko** · kategoria `security` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/main.py:643`

**Co to kosztuje.** Zweryfikowane na żywo na produkcji w tej sesji: `curl https://api.nexus.dynaminds.pl/openapi.json` → HTTP 200, 1 392 735 bajtów, 747 ścieżek, 876 schematów komponentów; `/docs` → 200 (Swagger UI); `/redoc` → 200. Nie jest przekazywane żadne `docs_url=None`, `redoc_url=None` ani `openapi_url=None`, a na tym konstruktorze nie ma żadnej bramki DEBUG/env (grep po docs_url/redoc_url/openapi_url w app/main.py i app/core/config.py nie zwraca nic). Każda trasa admina (/api/admin/snapshot, /api/admin/clients-overview, /api/admin/client-portfolio/*), każda powierzchnia kont serwisowych i OAuth, każda nazwa pola schematu kandydata/PII i każda wartość enuma są opublikowane w internecie. Atakującemu usuwa to całą fazę rozpoznania wobec systemu trzymającego 49 tys. profili kandydatów i 136 tys. CV; podaje mu też dokładne ciała żądań dla powierzchni bez uwierzytelnienia, które audyt już zgłosił (magic link public_engagement, parametr query w /api/auth/refresh, publiczne tokeny udostępniania CV).

**Naprawa.** Do zbadania: (1) potwierdź, czy ekspozycja jest zamierzona — przegrepuj git log/PR-y pod kątem docs_url i sprawdź, czy wtyczka do LinkedIna, integracje OAuth ChatGPT/n8n albo jakikolwiek zewnętrzny konsument faktycznie pobiera /openapi.json (extension/src/shared/api-client.js tego nie robi); (2) zdecyduj między bramką na settings.DEBUG (`docs_url=None if not settings.DEBUG else '/docs'`) a zostawieniem /openapi.json przy jednoczesnym schowaniu /docs i /redoc za JWT admina; (3) sprawdź, czy Cloudflare mógłby wymusić to na brzegu, oraz czy jakiś smoke test lub job CI asertuje, że /docs zwraca 200 (co by się wywaliło); (4) przed decyzją przejrzyj diffem publikowane opisy pod kątem wyciekającego wewnętrznego uzasadnienia.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 217` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f218"></a>

### #218 · P1 · 113 wywołań date.today() działa na zegarze kontenera w UTC, podczas gdy BUSINESS_TZ='Europe/Warsaw' jest respektowane tylko w 6 miejscach — każda granica daty w produkcie jest przesunięta o 1–2 godziny względem polskiego dnia roboczego

nakład **M** · obszar **Backend · tło** · **nie działa** · kategoria `broken` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/tasks/contract_alerts.py:54`

**Co to kosztuje.** `grep -c 'date.today()' backend/app` = 113; `grep -c 'ZoneInfo|Europe/Warsaw'` = 43, a sam BUSINESS_TZ ma tylko 6 konsumentów (triggers_loop, candidate_contact, m365/calendar). backend/Dockerfile to `FROM python:3.13-slim` i ustawia wyłącznie GIT_SHA oraz BUILT_AT — brak `ENV TZ`; ani docker-compose.yml, ani docker-compose.prod.yml nie ustawia TZ (grep 'TZ=' nie zwraca nic). Zegar kontenera jest więc w UTC, a `date.today()` to data UTC, która między 22:00 a 24:00 czasu warszawskiego (CEST) to wciąż *wczoraj*. Konkretnie: promocja statusów kontraktów active→ending→ended, promocja wygasania portalu DL/zamówień (dl_portal_expiry_scanner.py:98/123/171), arytmetyka 'days_left' w alertach kontraktowych (contract_alerts.py:467/514), autofreeze konkursu oraz stemple `datetime.now(timezone.utc).date().isoformat()` w application_submissions.py:343 i candidate_stage_cv.py:491 — wszystkie używają błędnego dnia kalendarzowego przez ostatnie dwie godziny każdego polskiego dnia. Kontrakt, którego end_date przypada dziś, po 22:00 wciąż raportuje '1 dzień'; rekord utworzony 1. dnia miesiąca o 00:30 jest stemplowany do poprzedniego miesiąca.

**Naprawa.** Do zbadania: (1) potwierdź TZ produkcyjnego kontenera — `docker exec nexus-backend date` albo dodaj linię TZ do /api/health; (2) zinwentaryzuj, które ze 113 miejsc z date.today() są wrażliwe na dzień roboczy (promocja kontraktów/zamówień, liczniki dni w alertach, koszykowanie miesięczne w md_consumption/finance/analytics `_current_period_start`), a które są wyłącznie wewnętrzne; (3) zdecyduj, czy tania globalna poprawka (`ENV TZ=Europe/Warsaw` w backend/Dockerfile plus tzdata) jest bezpieczna, skoro znaczniki czasu są zapisywane jako tz-aware UTC — zweryfikuj, że po zmianie żadne porównanie nie miesza naiwnej daty lokalnej z datą wyprowadzoną z UTC; (4) dodaj test zamrażający zegar na 22:30 UTC i asertujący, że promocja kontraktów używa daty warszawskiej.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 218` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f219"></a>

### #219 · P1 · 21 miejsc z asyncio.create_task() typu fire-and-forget nie trzyma silnej referencji — CPython może je zebrać GC w locie; app/api/cortex.py naprawił dokładnie tę klasę błędu u siebie i nikt nie zastosował tego nigdzie indziej

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/api/microsoft365.py:573`

**Co to kosztuje.** Istnieje 56 wywołań create_task; 34 to pętle z lifespanu trzymane w app.state.background_tasks; z pozostałych 22 dokładnie jeden moduł (cortex.py) trzyma zbiór referencji. Te 21 bez referencji to długo działające joby administracyjne oraz efekty uboczne powiadomień/integracji: admin_candidates.py:99/198/295 (backfill imion, backfill CC, backfill pól CV po 49 tys. kandydatów), admin_traffit.py:111 (ręczny sync Traffit, który operatorom każe się odpalać wielokrotnie, żeby przesunąć kursor sweepu plików/CV), admin_import.py:180, admin_notes_insights.py:46, admin_recruitment_processes.py:112, admin_talent_pools.py:60, pipeline.py:1717/1802, contracts.py:1668 (notify_contract_signed_by_id), candidates.py:2320 (Teams 'candidate_added'), autenti.py:86 (send_to_autenti — wysyła umowę do podpisu!), microsoft365.py:254/260/355/573. Dwa osobne zagrożenia: (a) udokumentowane zagrożenie GC, które nazywa cortex.py, oraz (b) shutdown — handler lifespanu anuluje wyłącznie `app.state.background_tasks.values()`, więc przy każdym redeployu Coolify (czyli przy każdym pushu na main) każdy trwający backfill lub wysyłka do Autenti jest ucinana bez handlera anulowania i bez linii w logu.

**Naprawa.** Do zbadania: (1) wypisz te 21 miejsc (`grep -rn 'asyncio.create_task(' backend/app | grep -v main.py | grep -v cortex.py`) i sklasyfikuj każde jako krótki efekt uboczny albo długi job; (2) awansuj `_spawn` z cortex.py do współdzielonego helpera (app/core/tasks.py) i przepuść przez niego wszystkie 21, żeby done_callback mógł logować wyjątki; (3) osobno ustal politykę shutdownu dla długich jobów administracyjnych — albo zarejestruj je w app.state, żeby lifespan czekał na nie z timeoutem, albo zapisuj wiersz przebiegu, żeby restart mógł wznowić (admin_traffit ma już stan kursora; backfille kandydatów deklarują wznawialność, ale endpoint statusu nie odróżnia 'running' od 'po cichu ubity'); (4) sprawdź, czy Sentry kiedykolwiek dostał ostrzeżenie 'Task was destroyed but it is pending' — jego brak potwierdziłby, że nikt tego nie pilnuje.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 219` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f220"></a>

### #220 · P1 · O tym, które prawnie wiążące klauzule trafią do generowanej umowy B2B, decyduje dopasowanie PODCIĄGU bez rozróżniania wielkości liter w wolnotekstowej nazwie klienta, wygrywa pierwsze trafienie, a brak trafienia jest cichy

nakład **M** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/services/b2b_contract_generator/clause_overrides.py:48`

**Co to kosztuje.** 2729 linii tekstu klauzul napisanych przez prawników (§10 zakaz konkurencji + kary umowne, §4 BNP, aneksy CA/BIK) jest wybieranych przez `needle in normalized_name`. Wejściem jest `payload.client_name` — wolnotekstowy string w żądaniu (b2b_contract_generator.py:1078), a w ścieżce DOCX `client.get("name")` (docx_renderer.py:61), czyli `Client.name`, o którym CLAUDE.md mówi, że Traffit nadpisuje go przy każdym syncu. Trzy niezabezpieczone tryby awarii: (a) brak trafienia → `return []` → umowa renderuje się BEZ wynegocjowanych klauzul zakazu konkurencji/kar i nic nikogo nie ostrzega; komentarz w samym rejestrze odnotowuje, że już raz się to zdarzyło („umowa wychodziła bez §10/PFRON"); (b) kolizja — `"bik"` to trzyznakowy podciąg, a jedynym zabezpieczeniem przed kolizją w całym rejestrze jest ręcznie ustawiona kolejność BNP-Cardif przed BNP-Paribas, o której komentarz przyznaje, że jest load-bearing; (c) nie ma zapisu, KTÓRY override został zastosowany, więc dla już podpisanej umowy nie odpowiesz na pytanie „czy ten dokument zawierał §10?" bez ponownego renderowania — a ponowne renderowanie czyta nazwę, która mogła się od tego czasu zmienić.

**Naprawa.** Do zbadania: (1) puść rejestr na realnej liście klientów — `SELECT id, lower(name) FROM clients` — i zaraportuj każdy wiersz pasujący do więcej niż jednego zestawu igieł oraz każdy wiersz, który historycznie pasował, a dziś już nie; (2) sprawdź, czy B2BGeneratedContract.render_payload zapisuje klucz zastosowanego override'u (grep po polu; jeśli go nie ma, to jest luka audytowa do domknięcia w pierwszej kolejności, bo jest tania i użyteczna wstecznie); (3) zdecyduj, czy przenieść wybór na client_id, zostawiając wolnotekstową nazwę wyłącznie do wyświetlania, używając tego samego wzorca listy z env, którego używają już bramki zamówień kosztowych/wielo-konsultantowych (MULTI_CONSULTANT_ORDER_CLIENT_IDS), zamiast dopasowania po nazwie; (4) dodaj sygnał w UI — „ta umowa zawiera modyfikacje dla klienta X" / „brak modyfikacji" — żeby ciche niedopasowanie stało się widoczne przed podpisem; (5) dodaj test rejestru asertujący, że żadna igła nie jest podciągiem kanonicznej nazwy innego wpisu w rejestrze.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 220` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f7"></a>

### #7 · P2 · Kolumna `match` na liście kandydatów przelicza od zera każdą parę (kandydat ze strony × opublikowana oferta) przy każdym żądaniu — zapisy są wyłączone, więc ta ścieżka nigdy nie może zagrzać własnego cache'u, a regex po umiejętnościach na tekście JD+CV liczony per parę jest w pełni redundantny, blokując pojedynczą pętlę zdarzeń uvicorna na ~1–3 s na stronę (widok mobilny wymusza tę ścieżkę bezwarunkowo)

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `perf`

`backend/app/api/candidates.py:1617`

**Co to kosztuje.** Komentarz nad pętlą uzasadnia projekt słowami „na ciepłym cache 50 zapytań" — ale już następny akapit wyłącza zapisy do cache'u, więc ta ścieżka nie może zagrzać cache'u, od którego zależy. Ciepłe są tylko pary już wyliczone przez `/api/recommendations` albo flow matchingu; dla dowolnej strony z 49-tysięcznej listy kandydatów skrzyżowanej z 50 opublikowanymi rekrutacjami praktycznie każda para (kandydat, oferta) to miss. Przy missie `bulk_get_or_compute` (`match_score_cache.py:335-361`) wykonuje jeden SELECT z cache'u i jedno `build_job_scoring_context` (dwa kolejne zapytania, `scoring_service.py:1596+`) na ofertę — ~150 round-tripów na stronę — a potem odpala `score_candidate_job` per kandydat per oferta w czystym Pythonie: do 100 × 50 = 5 000 synchronicznych obliczeń scoringu. Ponieważ `entrypoint.sh` startuje dokładnie jednego workera uvicorna (`exec uvicorn app.main:app --host 0.0.0.0 --port 8000`), ten burn CPU dzieje się na jedynej pętli zdarzeń w procesie — blokuje każde inne żądanie HTTP i wszystkie 33 pętle w tle zarejestrowane w `app/main.py:588-626` (sync Traffita, index outbox, triggery powiadomień, alerty kontraktowe) na cały swój czas trwania. Kolumna jest włączona w presecie „Sourcing" i w widoku kafelkowym, więc to rutynowa akcja rekrutera, nie przypadek brzegowy.

**Naprawa.** Albo dostarcz tej ścieżce brakującą warstwę semantyczną — pobierz `similarity_map` z Qdranta dla strony, żeby `allow_cache_write=True` stało się bezpieczne i cache faktycznie się grzał — albo utrwalaj kompozyty pod jawnym znacznikiem degradacji (np. flaga `semantic_neutral` na `CandidateJobMatchScore`), którą `/api/recommendations` odfiltrowuje, co usuwa obawę o zatruwanie cache'u przywołaną w komentarzu, a jednocześnie pozwala liście reużyć własną pracę. Jeśli żadne z tych — przenieś pętlę scoringu przez `run_in_threadpool`, żeby przestała blokować jedyną pętlę zdarzeń, i ogranicz interakcję `_MATCH_STATS_JOB_CAP`/`page_size`, żeby zamknąć najgorszy przypadek.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 7` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f10"></a>

### #10 · P2 · `POST /api/pipeline/stages/{id}/screening` połyka invalidację cache'u match-score bez ani jednej linii logu — jedyny taki handler w `app/api` — a cache nie ma TTL, więc kompozyt (kandydat, oferta) może serwować przedscreeningowy `champion_fit` w nieskończoność

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/pipeline.py:1277`

**Co to kosztuje.** Odpowiedzi ze screeningu są tym, co napędza warstwę scoringu `champion_fit` (`_score_champion_fit`, scoring_service.py:1480-1512 — brak odpowiedzi oznacza `_unscored(max_pts, "brak screeningu")`). Gdy invalidacja padnie, zapis się udaje i zwraca 200 ze świeżym `match_percent`, podczas gdy `/recommendations` i każda cache'owana powierzchnia dalej serwują przedscreeningowy kompozyt, dopóki coś innego przypadkiem nie zinwaliduje tego kandydata. Ponieważ handler nie loguje nic — nawet na poziomie debug — nie ma linii w Loki, nie ma zdarzenia w Sentry (`LoggingIntegration` mostkuje wyłącznie `logger.error`) i nie ma pola w odpowiedzi. Rekruter widzi zapisany screening i niezmieniony wynik w zakładce, co czyta się jako "AI nie zgadza się z moim screeningiem", a nie "invalidacja padła". Najbardziej prawdopodobny wyzwalacz jest banalny: zewnętrzny `await db.commit()` w linii 1271 już się wykonał, więc dowolny przejściowy błąd bazy, deadlock na `match_score_cache` albo `PendingRollbackError` na sesji zabrudzonej przez wcześniejszy efekt uboczny ląduje tutaj i zostaje wymazany.

**Naprawa.** Jedna linia: `except Exception as exc: logger.warning("match-score staleness marking failed for candidate=%s: %s", stage.candidate_id, exc)` przed rollbackiem, spójnie z trzema siostrzanymi handlerami w tym samym pliku. Jeśli świeżość cache'u waży więcej niż 200, zwracaj dodatkowo pole `cache_stale: false`, żeby UI mogło zaproponować odświeżenie zamiast po cichu pokazywać stary wynik.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 10` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f13"></a>

### #13 · P2 · Publiczna trasa magic-link do deklaracji zaangażowania nie ma rate limitu ani `max_length` na polu tekstowym, łamiąc wzorzec, który stosuje każdy inny nieuwierzytelniony zapis do kandydata w tym repo — a jej docstring powołuje się na globalny limit slowapi, który jest skonfigurowany jako pusty

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/public_engagement.py:13`

**Co to kosztuje.** To jedyny nieuwierzytelniony endpoint w aplikacji, który ZAPISUJE do wiersza kandydata, i jedyny publiczny endpoint, którego deklarowana ochrona jest wyimaginowana. Każda siostrzana publiczna powierzchnia niesie jawny dekorator (`public_signing` 30/min i 5/min;30/hour, `public_interview_confirmation` 10/hour, `public_share` cv 30/min i apply 5/min;30/hour) — ten nie niesie żadnego, a jego docstring jest powodem, dla którego nikt tego nie zauważył. Ktokolwiek posiadający albo zgadujący link może generować nieograniczoną liczbę round-tripów do produkcyjnego Postgresa, a przy poprawnym tokenie dopisać dowolnie duży, kontrolowany przez atakującego ciąg do `candidates.engagement_notes`, które rekruterzy czytają jako zaufane notatki wewnętrzne na rekordzie objętym RODO.

**Naprawa.** Zaimportuj `limiter` z `app.core.rate_limit` i udekoruj obie trasy spójnie z siostrzanymi powierzchniami publicznymi — `@limiter.limit("30/minute")` na GET, `@limiter.limit("5/minute; 30/hour")` na POST (kolejność dekoratorów: `@router.post(...)` najbardziej zewnętrznie, `@limiter.limit(...)` bezpośrednio nad funkcją, tak jak w public_signing.py). Uwaga: ten moduł ma `from __future__ import annotations` w linii 17, co wg CLAUDE.md jest niekompatybilne ze slowapi, gdy obecne są guardy `Annotated` — ten handler ich nie ma, ale i tak usuń ten import, żeby zostać w ramach udokumentowanej reguły. Ogranicz notatkę: `notes: Optional[str] = Field(None, max_length=2000)`. Następnie popraw docstring, żeby kolejny czytelnik nie dostał informacji o ochronie, która nie istnieje — i przegrepuj pozostałe publiczne routery pod kątem tego samego zdania.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 13` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f14"></a>

### #14 · P2 · Funkcja OAuth2 client-credentials jest wdrożona w połowie: Ustawienia reklamują klucze API dla n8n/ChatGPT/Zapier, a endpoint tokena wydaje poprawne tokeny, ale żadna trasa w aplikacji ich nie akceptuje

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/oauth_token.py:104`

**Co to kosztuje.** Repo płaci pełen koszt powierzchni OAuth client-credentials i nie ma z niej żadnej korzyści. To JEDYNY endpoint weryfikujący poświadczenia w całej aplikacji, który nie ma rate limitu — `/api/auth/login` ma 30/min, `/api/auth/register` 3/min, `/api/auth/reset-password` 5/min, `/api/oauth/token` nieograniczony — i uruchamia bcrypt (`verify_password`, ten sam helper co przy hasłach użytkowników) raz na request dla dowolnego istniejącego `client_id`, co czyni z niego tanią, nieuwierzytelnioną dźwignię wyczerpania CPU wobec backendu, który obsługuje też rekruterów. Osobno: reklamowany kontrakt integracyjny nie istnieje — zewnętrzny partner idący za opisem z CLAUDE.md, że klienci OAuth to "kontrakt zgodności dla integracji migrujących z Traffita", uzyska token i odkryje, że każdy endpoint go odrzuca.

**Naprawa.** Dwie linie obrony, potem decyzja. Natychmiast: zaimportuj `limiter` i dodaj `@limiter.limit("10/minute; 100/hour")` do `issue_token`, spójnie z traktowaniem każdego innego endpointu poświadczeń. Potem rozstrzygnij los tej powierzchni — albo podepnij `require_scope` do endpointów integracyjnych, dla których był pisany (i dodaj test asertujący, że co najmniej jedna trasa go konsumuje, żeby nie mógł po cichu znowu obumrzeć), albo zabramkuj cały router flagą `OAUTH_CLIENTS_ENABLED` domyślnie `false`, tak jak `CLOUDTALK_ENABLED` neutralizuje uśpioną integrację telefoniczną. Zostawienie żywego, nielimitowanego, nieuwierzytelnionego endpointu bcryptowego, który nic nie przyznaje, to jedyna opcja z kosztem i bez korzyści.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 14` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f18"></a>

### #18 · P2 · `/api/health/deep` — jedyna bramka schematu po deployu — sonduje 41 tabel, ale nie `users`, `candidate_stages`, `notes`, `candidate_documents` ani `notifications`, więc rozjechana kolumna na tabeli autoryzacji albo pipeline'u wjeżdża na zielono

nakład **S** · obszar **Backend** · **ryzyko** · kategoria `ops`

`backend/app/main.py:1928`

**Co to kosztuje.** Ten endpoint istnieje właśnie po to, żeby łapać sytuację „migracja dodająca KOLUMNĘ do ISTNIEJĄCEJ tabeli nie trafia nigdzie" — docstring w `app/main.py:1813-1820` opisuje incydent z 2026-07-06, gdy migracja 0154 dodała `contract_candidate_rates.effective_to`, o lustrze zapomniano, i całe `/api/contracts` przez dobę zwracało 503 za zielonym deployem. `.github/workflows/deploy.yml:365-436` robi z tego prawdziwą bramkę: „Deep healthcheck (core modules not 503)" wywala deploy, gdy którykolwiek check jest unhealthy, a komunikat błędu wskazuje operatorowi wprost `_COLUMN_STATEMENTS`. Bramka działa. Tylko nie obejmuje tabeli, z której ATS korzysta najczęściej. `candidate_stages` to pipeline — czyta go każdy ruch między etapami, każde renderowanie Kanbana, każdy lejek KPI — i dostawał kolumny jeszcze niedawno: 0199 (`candidate_stage_removals`), 0122 (`client_rate_value`/`unit`/`currency`) i 0056 (`verification_status`, `expected_rate_*`). Jest też odpytywany wprost przez własne widoki analityczne entrypointu (`entrypoint.sh:2252-2292`) i przez guard 409 w `delete_job`. `notes` (0129 dodała `audio_url`/`source_ref`) i `candidate_documents` (0079 `storage_key`, 0195 `document_kind`) są w tej samej sytuacji. Sondowanie `Candidate` nie pomaga: `select(Candidate).limit(1)` rozwiązuje wyłącznie kolumny `candidates`; docstring już rozpoznaje ten problem dla leniwie ładowanych dzieci i z dokładnie tego powodu wymienia jawnie `contract_*_rates`.

**Naprawa.** Dopisz `("candidate_stages", CandidateStage)`, `("notes", Note)`, `("candidate_documents", CandidateDocument)`, `("users", User)` i `("notifications", Notification)` do `core_checks` w `app/main.py:1899`. Każde to jedna linia i jedno dodatkowe `SELECT … LIMIT 1` z istniejącym timeoutem 3 s i izolacją świeżej sesji. Docelowo lista jest utrzymywana ręcznie i znów się rozjedzie — tanim zabezpieczeniem jest test asertujący, że każda tabela nazwana w bloku `CREATE TABLE` w `_COLUMN_STATEMENTS` entrypointu (albo każda tabela z więcej niż N zmapowanymi kolumnami) występuje w `core_checks`, żeby przeoczenie wywalało CI zamiast być zauważone po awarii.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 18` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f21"></a>

### #21 · P2 · Martwa pętla z lifespanu jest niewykrywalna i nigdy nie restartowana: `AsyncioIntegration` jest bezczynne (init leci przy imporcie, przed jakąkolwiek pętlą zdarzeń), silna referencja w rejestrze tłumi własny log błędu asyncio, a wszystkie trzy powierzchnie raportujące „running/expected" utrwalają ułamek, który z założenia jest nierówny (23 z 34 pętli kończą się celowo)

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `ops`

`backend/app/api/admin_snapshot.py:133`

**Co to kosztuje.** Nie ma supervisora: nic w kodzie nie odtwarza zakończonego taska, więc pętla, która umrze na nieobsłużonym wyjątku poza swoim `try` (albo na `BaseException`), zostaje martwa do następnego deployu. Jedyny element introspekcji tego nie wykryje, bo `task.done()` jest True także dla 17 pętli, które kończą się celowo. Żywe `/api/health` w tej chwili dowodzi, że co najmniej trzy są wyłączone świadomie (`autenti: unconfigured` → `autenti_sweeper` i `signature_reconciler` kończą; `priority_work: disabled` → ta pętla kończy), a osiem kolejnych jest wyłączonych domyślną konfiguracją (`AI_INDEX_WORKER_ENABLED`, `AI_INDEX_RECONCILER_ENABLED`, `WEEKLY_EVAL_ENABLED`, `MATCH_DIGEST_ENABLED`, `NOTES_INSIGHTS_SYNC_ENABLED`, `KPI_COACH_NUDGER_ENABLED`, `CANDIDATE_CONTACT_ENABLED`, `CLOUDTALK_ENABLED` — wszystkie `False` w `core/config.py`). Więc `running: 22, expected: 33` jest normalnym, zdrowym odczytem, a `running: 21` — jedna pętla padła — jest od niego nieodróżnialne. Endpoint stoi dodatkowo za autoryzacją admina i, wedle fazy rozpoznania, nie jest odpytywany przez żadną automatyzację. Wtórny defekt w tym samym bloku: jeśli jakiś task już zakończył się prawdziwym wyjątkiem, `await t` w `main.py:637` podnosi go ponownie (to nie jest `CancelledError`), co przerywa pętlę zamykania, więc pozostałe taski nigdy nie są doczekane, a `engine.dispose()` w linii 640 nigdy nie leci.

**Naprawa.** Zmień `_background_tasks_status` tak, żeby klasyfikował każdy wpis — `running` / `exited_cleanly` (task z `done()`, którego `.exception()` jest None, czyli powrót z kill-switcha) / `crashed` (task z `done()` i niepustym `.exception()`, dołącz `repr`) — żeby „crashed" było liczbą, która przy zdrowym stanie wynosi zero. Wystaw `crashed > 0` jako wpis `background_tasks` w `/api/health.checks` (to jedyne miejsce, w którym automatyczny czytelnik mógłby to zobaczyć) i dodaj `task.add_done_callback`, który loguje na poziomie ERROR z wyjątkiem, żeby Sentry dostał zdarzenie w chwili śmierci, a nie przy zamykaniu. W bloku zamykania złap `BaseException` wokół `await t` (albo użyj `asyncio.gather(*tasks, return_exceptions=True)`), żeby jeden martwy task nie mógł pominąć `engine.dispose()`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 21` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f22"></a>

### #22 · P2 · Sześć żywych pętli w tle loguje awarie całych cykli na poziomie WARNING, poniżej progu ERROR dla Sentry — własny audyt w repo wymienia to jako pozycję otwartą, a PR #1154 domknął tylko 2 z 4 pętli, które nazwał

nakład **S** · obszar **Backend · tło** · **ryzyko** · kategoria `ops`

`backend/app/tasks/match_history_ttl.py:72`

**Co to kosztuje.** Sentry jest skonfigurowany z `event_level=logging.ERROR`, więc `logger.warning` produkuje breadcrumb i nic więcej. Pętla, której każdy cykl rzuca wyjątkiem, kręci się więc w nieskończoność, wypluwając jedną linię warning do Loki i generując zero alertów — a to jest dokładnie to rozumowanie, które zapisano w `contract_alerts.py` i `slack_sla_alerts.py` (`:296-299`), gdy zmieniono je na `logger.exception`. Regułę ustalono raz i zastosowano w dwóch z dziesięciu miejsc; pozostałe osiem odjechało. Konsekwencje nie są kosmetyczne, biorąc pod uwagę, co te pętle robią: `saved_search_alerts` to alertowanie rekruterów o nowych kandydatach, `calendar_reminder_loop` to przypomnienia o rozmowach, `fx_refresh_loop` to jedyne źródło kursów FX używanych do przeliczeń faktur i marż, `match_history_ttl` ogranicza nieograniczony wzrost `match_history`, a `competition_autofreeze` zamraża okresy konkursów zasilające wyliczenia KPI/premii.

**Naprawa.** Zamień `logger.warning(...)` na `logger.exception(...)` w ośmiu wymienionych wyżej handlerach cyklu najwyższego poziomu — ta sama jednoliniowa zmiana, którą zrobiono już w `contract_alerts.py` i `slack_sla_alerts.py`, przy okazji wrzucająca traceback do logu. Handlery per element wewnątrz cyklu (np. warning per CC w `_bootstrap_if_needed`, `cc_centroid_sync.py:51`) mogą zostać na WARNING; rozróżnienie, które ma znaczenie, to „padł cały cykl". Tani zabezpieczacz regresji: test przechodzący `ast`-em po `app/tasks/*.py`, znajdujący gałąź `except` podpiętą do ciała każdego `while True` i asertujący, że wywołanie to `logger.exception`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 22` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f26"></a>

### #26 · P2 · POST /api/ai/generate-job buduje surowego klienta Anthropic z domyślnym timeoutem SDK 600 s, więc trzyma jeden z 40 współdzielonych tokenów threadpoola nawet przez 3×600 s na requestach, które przeglądarka porzuciła po 120 s — i nigdy nie dociera do circuit breakera Claude'a (znany dług, zamrożony ratchetem)

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `risk`

`backend/app/api/ai_writer.py:227`

**Co to kosztuje.** `grep -rn 'anthropic.Anthropic('` po backend/app zwraca dokładnie trzy miejsca konstrukcji. Jedno to współdzielony helper. Refaktor, który go stworzył, wymienił migrowanych callerów; `ai_writer.py` i `cv_generator_b2b/ai_client.py` nie były na tej liście i nigdy nie zostały przeniesione, więc kod niesie dziś trzy niezależne polityki odporności Anthropic dla jednego dostawcy. Konkretnie: `ai_writer.py:227` nie przekazuje ŻADNEGO timeoutu, więc dziedziczy domyślne 600 s, które docstring współdzielonego modułu nazywa błędem, dla którego naprawy ten moduł istnieje. `ai_client.py` czyta swój timeout, retry, max_tokens i łańcuch modeli wprost z `os.environ` (`CV_B2B_REQUEST_TIMEOUT`=120 s, `CV_B2B_MAX_RETRIES`=3) — `grep -c CV_B2B app/core/config.py` zwraca 0, więc nic z tego nie jest w Settings, nic nie jest walidowane i nic nie występuje w kontrakcie env Coolify, podczas gdy `settings.ANTHROPIC_TIMEOUT_SECONDS`=90 / `ANTHROPIC_MAX_RETRIES`=2 rządzą całą resztą. Obie niezmigrowane ścieżki pomijają też `_record_health` (claude_client.py:85-89), które jest JEDYNYM callerem `record_provider_call("claude", …)` — więc wpis `anthropic` w `/api/health` i jego circuit breaker są ślepe na generator CV B2B, najcięższego konsumenta Claude'a w produkcie: 16 384 max_tokens na wywołanie plus łańcuch modeli fallbackowych. Do tego `is_retryable_anthropic_error` (claude_client.py:48) i `_is_retryable` (ai_client.py:204) to duplikaty co do bajtu, więc każda przyszła zmiana predykatu retry musi być zrobiona dwa razy albo po cichu się rozjedzie.

**Naprawa.** Najmniejsza poprawna naprawa ostrej połowy: zastąp ai_writer.py:227 wywołaniem `call_claude(...)` z `app.services.claude_client` — zwraca ten sam `anthropic.types.Message`, więc istniejące zbieranie bloków tekstu w linii 265 zostaje bez zmian, a przy okazji wnosi timeout sterowany z Settings, dostrojony backoff i `record_provider_call`. Zahardkodowany `model="claude-sonnet-5"` powinien przy tej okazji przejść do Settings. Dla `cv_generator_b2b/ai_client.py` migracja jest większa, bo ten moduł ma własny łańcuch fallbacku modeli, którego `call_claude` nie ma: albo podnieś pętlę fallbacku do `claude_client` i niech `_call_model` deleguje per próbę, albo przynajmniej opakuj jego `client.messages.create` w `_record_health`, żeby circuit breaker widział generację CV, przenieś `CV_B2B_*` do `Settings` i usuń `_is_retryable` na rzecz importu `is_retryable_anthropic_error`. Osobno: popraw komentarz w ai_quota.py:221 albo zrób go prawdziwym — `AIFeatureKey` nie ma członka dla generacji CV B2B, więc ta funkcja nie ma żadnego kubełka kwoty, a `requirement_map.py:276` / `interactive_chat.py:207` / `client_orders.py:846` wołają `check_and_increment` bez wejścia w `ai_feature(...)`, czyli naliczają poprawnie, ale RZUCIŁYBY `AIQuotaUngated` w dniu, w którym ktoś ustawi `AI_QUOTA_STRICT=true`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 26` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f31"></a>

### #31 · P2 · Sumy PLN zamówień kosztowych (budget_amount / budget_used / budget_remaining / invoiced_total / unsettled_total) omijają bramkę with_finance w _group_to_read, więc TAC i Head of Recruitment dostają wartość zamówienia i sumy zafakturowane, które siostrzany moduł zamówień redaguje jako total_value

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/client_order_groups.py:442`

**Co to kosztuje.** `OrderGroupReader` (linia 226) wpuszcza `tac` i `head_of_recruitment`; żadna z tych ról nie ma `AnalyticsCapability.VIEW_FINANCE` (`app/analytics/capabilities.py:79-104`), a `_has_md_line_management_role` wyklucza obie, więc `_can_see_finance` jest dla nich False — i dlatego `rate_cost`, `rate_revenue` oraz `input_value` w trybie kwotowym są zerowane. Ale `budget_amount`, `budget_used`, `budget_remaining`, `invoiced_total` i `unsettled_total` są zadeklarowane jako `MoneyPLN` w `app/schemas/client_order_group.py` (linie 264, 269, 308-310) i wychodzą bezwarunkowo. Frontend renderuje je każdemu: `frontend/src/components/client-profile/orders/OrderGroupCard.tsx:79-83` wypisuje "Kwota {budget_amount} · wykorzystano {budget_used} · pozostało {budget_remaining}" bez żadnego guardu `canManage`/finance. CLAUDE.md wprost mówi, że HoR jest trzymany poza powierzchniami finansowymi ("przy powierzchniach finansowych repo konsekwentnie trzyma go poza") i że TAC "zostaje przy redakcji" — to przeczy obu. Linia MD-vs-pieniądze, którą rysuje kod, jest spójna (liczby MD są operacyjne); wartość zamówienia w PLN i sumy zafakturowane grupy są po złej stronie tej linii.

**Naprawa.** Zabramkuj pola pieniężne tą samą flagą `with_finance`, która już rządzi stawkami linii: w `_group_to_read` zwracaj `budget_amount`/`budget_used`/`budget_remaining` (oraz `budget_manual_adjustment`) jako `None`, gdy `with_finance` jest False, i przestań przekazywać `invoiced`/`unsettled` do `_line_to_read` w tym przypadku — `_line_to_read` już dostaje tę flagę. Potem ukryj cały `BudgetBar` w `OrderGroupCard.tsx`, gdy kwoty wracają jako null (trzykrotne renderowanie "—" jest gorsze niż nierenderowanie paska). Jeśli intencją naprawdę jest, że zużycie budżetu jest operacyjne, podejmij tę decyzję jawnie i udokumentuj ją obok redakcji `input_value` — obie nie mogą być jednocześnie słuszne, bo `md_total` plus `budget_amount` odtwarza zredagowaną stawkę.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 31` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f36"></a>

### #36 · P2 · POST /api/ai/generate-job połyka KAŻDĄ awarię Claude'a (łącznie z JSON-em uciętym przez max_tokens, na czym to repo już się przejechało) i zwraca zahardkodowany polski szablon w identycznym kształcie odpowiedzi — formularz rekrutera dostaje zmyślone widełki płacowe bez niczego, co oznaczałoby, że to nie AI

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/ai_writer.py:227`

**Co to kosztuje.** Dwa osobne defekty na tym samym wywołaniu. (1) `claude_client.py:4-9` opisuje cały powód swojego istnienia: wołacze Claude'a na ścieżce requestu "used to construct ``anthropic.Anthropic(api_key)`` with the SDK's **600 s default timeout** and **no retry**, so a hung provider pinned a threadpool slot for ten minutes and a single transient 429/529 turned into a hard 502". Wymienia `match_justification_service`, `champion_draft_service` i `dynareporter_mindy` jako naprawione; `ai_writer` został pominięty i nadal robi dokładnie to, przez `run_in_threadpool(client.messages.create, …)` w liniach 253-261. Frontend poddaje się po 120 s (`SLOW_ENDPOINT_TIMEOUT_MS` w lib/api.ts:837), więc zawieszone wywołanie Anthropica trzyma wątek workera FastAPI przez kolejne osiem minut po tym, jak użytkownik już zobaczył błąd, a przejściowe 429 — które `call_claude` ponowiłby z backoffem — jest tu twardą awarią. (2) Przy JAKIMKOLWIEK wyjątku handler przechodzi do `_generate_mock`, czystego buildera szablonów stringowych, i zwraca go w tym samym kształcie `GenerateJobResponse`, bez żadnego pola odróżniającego oba przypadki. Rekruter klika "Generuj AI", dostaje boilerplate "Wymagane technologie (uzupełnij)" i nie ma jak się dowiedzieć, że Claude nigdy nie odpowiedział — a tymczasem `check_and_increment(job_description_generator)` został już zacommitowany w linii 396, więc licznik kwoty twierdzi, że wywołanie Claude'a się odbyło.

**Naprawa.** Zastąp surowego klienta wywołaniem `await run_in_threadpool(call_claude, messages=[...], model=..., max_tokens=1500, thinking={"type": "disabled"})` — to daje jawny `ANTHROPIC_TIMEOUT_SECONDS`, backoff na 429/529, telemetrię circuit-breakera przez `_record_health` ORAZ uwidacznia wywołanie dla `_assert_declared`. Potem zawęź `except Exception` w linii 414, żeby awaria dostawcy wychodziła jako 503 zamiast mocka, albo dodaj pole `source: "claude" | "template"` do `GenerateJobResponse` i wyrenderuj je na FE — `/api/jobs/{id}/criteria` robi już dokładnie to (`"source": "ollama" if criteria and "_source" in criteria else "heuristic"`, recommendations.py:1136), więc wzorzec w kodzie istnieje.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 36` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f38"></a>

### #38 · P2 · Alerty nadzoru nad kontaktem na dashboardzie HoR linkują do /candidates/contact-queue — trasy, której middleware odmawia rolom head_of_recruitment i admin (→/403); capability przepisywania jest osierocona razem z niezamontowanym ContactOversightPanel

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/middleware.ts:83`

**Co to kosztuje.** Head of Recruitment i admin nie mają żadnej powierzchni do kolejki telefonów pierwszego kontaktu: middleware.ts wysyła ich na /403, jeśli otworzą /candidates/contact-queue, wpis w sidebarze (SidebarV2.tsx:98-102) jest ograniczony do `["tac", "recruiter", "sourcer"]`, a panel dashboardu, na który wskazują obie bramki, został usunięty 16 dni temu. Panel nie jest ozdobą — renderuje opóźnienie SLA, przypadki `unassigned`, `awaiting_capacity`, `blocked_no_phone` i `handoff_pending` oraz pozwala HoR je przepisywać (`REASSIGNABLE_STATUSES`, ContactOversightPanel.tsx:36-42). `GET /api/candidate-contact/oversight` (candidate_contact.py:597) nadal żyje, jest za bramką `ContactOversight` i ma zero wołających. Rekruterzy osobno stracili `MyContactQueueWidget` ze swojego dashboardu; do kolejki dalej dochodzą przez sidebar, więc ich strata to regresja odkrywalności, a nie odcięcie. W ATS-ie, w którym CLAUDE.md odnotowuje adopcję na poziomie 0,5%, osoba, której zadaniem jest wyłapywanie utkniętej pracy, jest dokładnie tą, która teraz lata na ślepo.

**Naprawa.** Zamontuj `<ContactOversightPanel />` w gałęzi `head-of-recruitment` (i `admin-ops`) funkcji `presetContent()` w components/v2/dashboard/RoleDashboard.tsx — komponent jest nietknięty, wciąż kompiluje się względem żywego `candidateContactApi` i ma przechodzący test bramki rolloutu. To samo zrób z `<MyContactQueueWidget />` w presecie `my-work`. Jeśli natomiast decyzja jest taka, że HoR ma czytać kolejkę bezpośrednio, poszerz regułę middleware w linii 83 i wpis SidebarV2 w linii 101 o `admin` i `head_of_recruitment`, a oba komponenty plus nieosiągalny już endpoint `/oversight` usuń. Tak czy siak, popraw komentarz w middleware, żeby przestał powoływać się na powierzchnię, która nie istnieje.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 38` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f39"></a>

### #39 · P2 · Sidebar odpytuje admin-only /api/pipeline/pending-verifications dla delivery_lead i head_of_recruitment — gwarantowane 403, które allSettled mapuje na 0, zasilając badgeKey, którego jedyny element nawigacji jest zakomentowany

nakład **S** · obszar **Frontend · UI** · **ryzyko** · kategoria `perf`

`frontend/src/components/v2/shell/SidebarV2.tsx:517`

**Co to kosztuje.** Trzy defekty spiętrzone na gorącej ścieżce, którą montuje każda zalogowana strona. (1) Badge jest martwy — linia 233 to jedyne `badgeKey: "pendingVerifications"` w pliku i siedzi w bloku `/* */` ukrytym 2026-05-28, więc licznik jest liczony i wyrzucany przy każdym refetchu. (2) Dla delivery_lead i head_of_recruitment request może skończyć się wyłącznie 403; przy globalnym `staleTime: 30_000` react-query (QueryProvider.tsx:11) to gwarantowanie odrzucane wywołanie mniej więcej co 30 sekund tak długo, jak DL albo HoR ma otwartą aplikację. (3) Dla admina wywołanie się udaje i jest nieograniczone — handler robi czterostronne złączenie (CandidateStage × Candidate × Job × User) bez LIMIT, potem buduje po jednym w pełni wypełnionym `PendingVerificationListItem` na wiersz, każdy z wywołaniem `normalize_rate_to_monthly()`, a frontend czyta `.data.length` i wyrzuca payload. Sztorm 403 jest niewidoczny z każdej strony: `Promise.allSettled` go połyka, a `sentry.client.config.ts:60-66` jawnie zwraca `null` dla statusów 401/403/404, więc nie dociera też do Sentry.

**Naprawa.** Usuń blok `if (isApproverForBadge)` (SidebarV2.tsx:516-519), pole `pendingVerifications` z `BadgeCounts` (linia 50) i odczyt w liniach 535/556 — badge nie ma konsumenta od 2026-05-28. Jeśli element nawigacji Panel Managera kiedyś zostanie odkomentowany, przywróć fetch jako endpoint zliczający (`?page_size=1` zwracający `total`), a nie pełną listę, i zrównaj `isApproverForBadge` z faktycznym guardem `AdminUser` na endpoincie, żeby DL i HoR przestali generować 403. Osobno: `list_pending_verifications` powinien przyjmować `limit`/`page_size` — nieograniczony endpoint listujący na rosnącej tabeli to utajony problem niezależnie od tego wołającego.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 39` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f40"></a>

### #40 · P2 · 29 plików frontendu / 5734 LOC jest nieosiągalnych z jakiejkolwiek trasy; ~1000 LOC z tego osierocone w jednym PR-ze RBAC z 1301 usunięciami, 4 pliki kompilują się wyłącznie dzięki własnym testom, a martwy helper kwoty słownie w PLN już zdążył rozjechać się z żywym backendowym

nakład **M** · obszar **Frontend · UI** · **dług** · kategoria `dead-code`

`frontend/src/components/v2/pages/AnalyticsDashboard.tsx:542`

**Co to kosztuje.** To nie jest wiekowy gruz i właśnie dlatego coś kosztuje. Jeden PR — 6ddbfd4c (#1031, 2026-08-04, 16 dni przed tym audytem) — osierocił 1150 LOC jednym ruchem: AnalyticsDashboard (643), ContactOversightPanel (244), CompactGamification (150) i MyContactQueueWidget (113), bo zastąpił trzy dashboardy rolowe przez RoleDashboard/DashboardV2Preset i nigdy nie zamontował z powrotem tego, co tamte strony hostowały. Jeden z tych czterech to żywa regresja funkcjonalna (znalezisko #2) i to jest powód, dla którego ta sterta ma znaczenie zamiast być kosmetyką: martwe komponenty i usunięte funkcje są nie do odróżnienia w diffie, więc realna strata wjeżdża razem z szumem. Pięć plików kompiluje się wyłącznie dzięki własnym testom (AnalyticsDashboard, ContactOversightPanel, MyContactQueueWidget, SavedSearchPicker, lib/email-threading.ts), co oznacza, że CI jest zielone na kodzie, do którego żaden użytkownik nie dotrze — te testy nie orzekają niczego o produkcji. Podatek utrzymaniowy jest mierzalny: PR #1103 (2026-08-10), rename "Oferty"→"Rekrutacje", wymienia "global search" wśród zaktualizowanych powierzchni i edytuje GlobalSearchBar.tsx w liniach 220 i 255 — komponent na 458 LOC z zerem importujących. `lib/number-to-words.ts` (162 LOC, `liczbaSlownie`) to martwy frontendowy bliźniak żywego `backend/app/services/b2b_contract_generator/number_words.py`, czyli kwoty słownie używanej w polskich umowach B2B — dokładnie taka para, która daje dwie różne odpowiedzi, jeśli ktoś kiedyś podepnie tę martwą.

**Naprawa.** Usuwaj w trzech partiach, żeby review pozostało uczciwe. Partia 1 (nie wymaga decyzji): GlobalSearchBar (458), CandidatesBulkBar (217), AdvancedFilterBar (195), SavedSearchPicker (193), FirefliesTranscriptsWidget (173), ListScaffoldV2 (163), lib/number-to-words.ts (162), PowerCallingSection (152), CompactGamification (150), FilterChipPopover (97), MatchHistoryWidget (92), JobRow (85), CandidateCard (68), CandidateProfileHeader (46), SearchBar (33) — plus trzy nieużywane przestrzenie nazw w lib/api.ts: `dashboardApi`, `activitiesApi`, `contactsApi` (~25 LOC). Usuwaj test każdego komponentu razem z nim; test, którego przedmiot został usunięty, niczego nie dowodzi. Partia 2 wymaga decyzji produktowej: emails/* (1473, znalezisko #1). Partia 3 wymaga decyzji RBAC ze znaleziska #2: ContactOversightPanel + MyContactQueueWidget. Potem dodaj krok CI, który liczy to samo domknięcie grafu importów i failuje na nowych nieosiągalnych plikach nietestowych, żeby kolejne przepisanie dashboardu nie mogło po cichu wywalić funkcji.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 40` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f47"></a>

### #47 · P2 · Ustawienia → Zaawansowane oferują kafelki rolom, które RequireRole na stronie docelowej odrzuca; fallback domyślnie jest null i żadna z tras nie ma wpisu w middleware, więc kliknięcie ląduje na pustej powłoce aplikacji — a dla /settings/contract-templates UI jest surowsze niż własna ContractLegalAccess backendu (admin/HoR/DL/TAC)

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/app/settings/rate-benchmarks/page.tsx:30`

**Co to kosztuje.** Dwie równoległe kopie tej samej reguły dostępu rozjechały się. Kafelek nawigacji w app/settings/page.tsx:129-136 deklaruje `roles: ["admin", "delivery_lead"]` z komentarzem „benchmarki stawek = finanse (DL+/admin)", a app/settings/page.tsx:398-400 filtruje kafelki dokładnie po tej liście — więc Delivery Lead widzi kartę „Stawki rynkowe". Strona bramkuje potem tylko na `["admin"]`. RequireRole (components/RequireRole.tsx:41) ma domyślne `fallback = null`, więc DL dostaje powłokę aplikacji z całkowicie pustym obszarem treści: bez komunikatu, bez 403, bez linku powrotnego. Ten sam kształt trafia każdego nie-admina na /settings/contract-templates, którego kafelek (app/settings/page.tsx:137-142) nie ma w ogóle klucza `roles` i jest wobec tego pokazywany każdej roli, która może otworzyć /settings, podczas gdy strona bramkuje na `["admin"]` bez fallbacku (app/settings/contract-templates/page.tsx:167). Żadna z tras nie ma wpisu w middleware.ts, więc przekierowanie na /403 z middleware też ich nie obejmuje — a middleware.ts:50-52 stwierdza, że wyłapywanie tego jest dokładnie powodem istnienia tych wpisów („ten wpis pilnuje, żeby wejście z paska adresu kończyło się /403, a nie pustym ekranem"). Pusty ekran jest najgorszym możliwym renderowaniem awarii uprawnień: jest nieodróżnialny od zwiechy strony, więc zgłaszany jest jako „aplikacja się wysypała", a nie „nie mam uprawnień".

**Naprawa.** Albo zgraj obie listy, albo dostarcz fallback. Poprawną naprawą jest jedno i drugie: przekaż `fallback={<QueryStateNotice state="forbidden" description=… />}` na tych bramkach poziomu strony, tak jak robi to już app/finance/page.tsx:66-74, i uzgodnij role kafelka z rolami strony (DL albo może widzieć benchmarki stawek, albo nie — dziś aplikacja mówi jedno i drugie). Dodanie wpisów w middleware dla /settings/rate-benchmarks i /settings/contract-templates dałoby tę samą obronę w głąb, którą mają już siostrzane podstrony ustawień. Zwróć uwagę, że ten sam dryf istnieje w drugą stronę dla /settings/clients-overview: kafelek dopuszcza head_of_recruitment (app/settings/page.tsx:201-205), a middleware.ts:69 dopuszcza tylko admina, więc HoR jest odbijany na /403 z kafelka, który UI mu pokazało.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 47` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f48"></a>

### #48 · P2 · Lista rekrutacji w onboardingu nie ma gałęzi isError: każda awaria — w tym deterministyczne 403 dla dowolnej hybrydy head_of_recruitment+delivery_lead — renderuje się jako „nie ma rekrutacji", a jedyna aktywna kontrolka kończy onboarding na zawsze (409 przy ponowieniu)

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/v2/forms/OnboardingRecruiterV2.tsx:89`

**Co to kosztuje.** Zgodnie z CLAUDE.md konto z samodzielnej rejestracji to Recruiter z `profile_completed=false`, a aplikacja blokuje powłokę oraz powierzchnie kandydackie/RODO do zakończenia onboardingu — więc to dosłownie pierwszy ekran, jaki widzi nowa osoba. Zapytanie destrukturyzuje tylko `{ data, isLoading }`; `isError` nie jest nigdzie na stronie czytane. Przy dowolnej awarii `GET /api/users/me/onboarding/jobs` (500, 403 z guardu scope'u, przerwa w sieci, challenge Cloudflare, 30-sekundowy sufit axiosa) `isLoading` przechodzi w false przy `data === undefined`, więc `allJobs` to `[]`, a ekran stwierdza jako fakt, że firma z ~53 tys. kandydatów i dziesiątkami żywych rekrutacji nie ma żadnej. `backend/app/api/onboarding.py:266` przestawia potem `current_user.profile_completed = True` bezwarunkowo przy submit, bez ścieżki powrotnej w UI — rekruter zostaje trwale zapisany jako współpracujący przy zerze rekrutacji, co jest wejściem do „Mojej pracy", priority-work i KPI. To jest dokładnie ta reguła, którą repo już sobie spisało („awaria ≠ pustka" oraz komentarz w FinanceResultsTab.tsx:100-105 tłumaczący, dlaczego gałąź pusta musi wisieć na sukcesie, a nie na `!isLoading`); onboarding nigdy nie został przemieciony. `OnboardingDLV2.tsx:103` to identyczny defekt dla Delivery Leadów („Nie masz jeszcze rekrutacji w systemie. Możesz pominąć ten krok — uzupełnisz priorytety później"), w obu krokach jego dwuetapowego kreatora.

**Naprawa.** Wyciągnij `isError` (i `isSuccess`) z zapytania w obu plikach i daj awarii własną gałąź — jawne „Nie udało się wczytać listy rekrutacji" z przyciskiem ponowienia — przed gałęzią pustą, a gałąź pustą bramkuj na `isSuccess`, a nie na `!isLoading`, zgodnie z kolejnością, którą FinanceResultsTab już dokumentuje. Wyłącz „Zakończ onboarding", dopóki zapytanie listy jest w stanie błędu, żeby nieudanego pobrania nie dało się zamienić w trwałe `profile_completed=true` z pustym wyborem.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 48` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f50"></a>

### #50 · P2 · „Dodaj championa" (rekrutacja → Historia) inwaliduje `["kanban"/"job", <number>]`, podczas gdy strona rekrutacji cachuje oba pod stringowym parametrem trasy — obie inwalidacje są no-opami, więc zakładka Pipeline i nagłówek rekrutacji dalej pokazują stan sprzed dodania, mimo toasta o sukcesie

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/RequestHistorySection.tsx:133`

**Co to kosztuje.** `RequestHistorySection` deklaruje `jobId: number` (linia 42), a strona rekrutacji przekazuje `jobId={Number(id)}` (`jobs/[id]/page.tsx:1441`). Ale tablica kanban i nagłówek rekrutacji są cachowane SUROWYM parametrem trasy: `const { id } = useParams();` (`jobs/[id]/page.tsx:981`) zasila `queryKey: ["job", id]` (`:1069`) i `queryKey: ["kanban", id]` (`:1074`) — czyli stringiem. React Query dopasowuje klucze inwalidacji przez `partialDeepEqual`, który porównuje prymitywy przez `===`, więc `["kanban", 123]` nie może trafić w `["kanban", "123"]`. Obie inwalidacje są martwe. Każde inne miejsce wywołania w repo asekuruje się, odpalając obie formy właśnie z powodu tej niejednoznaczności — `jobs/[id]/page.tsx:744-745`, `HistoricalCandidatesSection.tsx:175-176` i `:388-389`, `AddCandidatesQuickModal.tsx:109-110`, `KanbanBoardV2.tsx:1262-1263` robią `["kanban", String(jobId)]` ORAZ `["kanban", jobId]`. `CandidateSearchView.tsx:319-322` wręcz zapisuje to zagrożenie wprost: „The job page caches its kanban via react-query ([\"kanban\", id] with the route param as a STRING). Adding candidates from search … must invalidate it, or the Pipeline tab keeps showing stale counts until a full page reload." `RequestHistorySection` to jedyne miejsce, do którego ta notatka nie dotarła. Obie kwerendy żyją w komponencie strony, nie w dziecku warunkowanym zakładką, więc przełączenie zakładek ich nie odmontowuje i nic nie wymusza refetchu.

**Naprawa.** Odwzoruj pięć pozostałych miejsc wywołania: inwaliduj `["kanban", String(jobId)]` i `["job", String(jobId)]` obok form liczbowych, a także `["pipeline-scores", String(jobId)]` (kwerenda pierścienia scoringu w `jobs/[id]/page.tsx:1082`, której to miejsce w ogóle nie dotyka). Trwała naprawa to przestać wpuszczać surową wartość z `useParams()` do klucza cache'u: normalizuj na granicy tak, jak robi to już `candidate-query-keys.ts` (`const candidateId = (id: number | string) => Number(id)`), i dodaj fabrykę `jobQueryKeys`, żeby klucze job/kanban/pipeline-scores nie mogły znowu rozjechać się typem.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 50` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f51"></a>

### #51 · P2 · Globalne „+ Dodaj → Dodaj firmę" inwaliduje `["clients-v2"]`, czyli klucz bez producenta — katalog klientów (`["clients-directory", …]`) nie odświeża się po udanym utworzeniu, wbrew własnemu toastowi o sukcesie

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/v2/shell/QuickActionsV2.tsx:88`

**Co to kosztuje.** `QuickActionsV2` to menu dodawania w żywym shellu (`app/layout.tsx:125` montuje `AppShellV2`), a jego `showToast` pełni jednocześnie rolę hooka inwalidacji po utworzeniu dla wszystkich pięciu modali: `{modal === "client" && <AddClientModal onClose={…} onSuccess={showToast} />}` (linia 150). Komentarz nad tym blokiem twierdzi „Aktywne listy V2 używają kluczy z sufiksem `-v2`" — prawda dla kandydatów i rekrutacji, fałsz dla klientów. Katalog klientów to `queryKey: ["clients-directory", category, querySearch, page]` (`ClientsListV2.tsx:283`). Przegrepowałem całe `src/`: `clients-v2` występuje dokładnie w dwóch miejscach, oba to te linie inwalidacji (`AppShell.tsx:2151` i `QuickActionsV2.tsx:88`); producenta nie ma. Ścieżka dodawania z poziomu strony zna właściwy klucz — `ClientsListV2.tsx:381` robi `invalidateQueries({ queryKey: ["clients-directory"] })` — i zna go też ścieżka edycji, która ma nawet komentarz na ten temat (`clients/[id]/page.tsx:991-992`). Dwie implementacje tej samej reguły, rozjechane, i to ta globalna jest zepsuta. `["contacts"]` w kolejnej linii ma ten sam problem (prawdziwy klucz to `["client-contacts", clientId]`, `clients/[id]/page.tsx:445`), więc „Dodaj osobę kontaktową" jest tak samo bezczynne. Zduplikowane wiersze klientów nie są w tym produkcie kosmetyką: kontrakty, zamówienia, przypisania TAC/DL, harmonogramy stawek i MRR wiszą na `client_id`, a rozbicie jednego klienta na dwa wiersze po cichu rozbija obraz przychodów.

**Naprawa.** Zamień `["clients-v2"]` na `["clients-directory"]` i `["contacts"]` na `["client-contacts"]` zarówno w `QuickActionsV2.tsx:87-89`, jak i w identycznym bloku w `AppShell.tsx:2150-2152`. Naprawa całościowa to przestać wpisywać literały kluczy ręcznie w blokach inwalidacji: moduł kandydatów już to centralizuje (`candidate-query-keys.ts` + `candidate-cache.ts::candidateInvalidationKeys`) — rozciągnij ten sam wzorzec fabryki na klientów/kontakty/kalendarz i dodaj skan źródeł w vitest (wzorzec `formdata-multipart.test.ts`) asertujący, że każdy literał przekazany do `invalidateQueries` ma w `src` co najmniej jeden producencki `queryKey`. To właśnie ten skan znalazł ten przypadek; puszczony na dzisiejszym drzewie wskazuje też `["contracts"]`, `["postings-stats"]`, `["candidate-screenings"]`, `["client-contracts"]` i `["calendar"]`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 51` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f52"></a>

### #52 · P2 · Zakończenie kontraktu / aneks / edycja / usunięcie inwalidują martwy klucz `["contracts"]` — osierocony po skasowaniu listy V1 — więc rejestr serwuje nieaktualny wiersz nawet przez 30 s, a baner wygasania w 30 dni zawyżony licznik nawet przez 5 min

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/contracts/ContractTerminationDialog.tsx:41`

**Co to kosztuje.** Wyliczyłem każdy literał `queryKey` w `src/`: `["contracts"]` występuje wyłącznie jako cel inwalidacji, w czterech miejscach — `ContractTerminationDialog.tsx:41` (Zakończ współpracę), `ContractAmendmentsTab.tsx:96` (aneks) oraz `contracts/[id]/page.tsx:459` (edycja/zmiana statusu) i `:478` (usunięcie). Żadna kwerenda nie jest pod nim zarejestrowana. Prawdziwi producenci to `["contracts-v2", debouncedSearch, statusFilter, typeFilter, endingSoon, page]` (`ContractsListV2.tsx:192`), `["contracts-expiring-v2"]` ze `staleTime: 5 * 60 * 1000` (`ContractsListV2.tsx:212-214`) oraz `["contractors-v2", tab, page]` + `["contractors-stats-v2"]` (`ContractorsListV2.tsx:103,111`). Właściwe nazwy są używane poprawnie gdzie indziej w tym samym drzewie — `ContractsListV2.tsx:414-415` inwaliduje `["contracts-v2"]` i `["contracts-expiring-v2"]` po akcjach masowych, a `B2BContractGeneratorV2.tsx:1727-1728` inwaliduje `["contractors-v2"]`/`["contractors-stats-v2"]` — więc to dryf, nie niezaimplementowana funkcja. Konsekwencje dotyczą pieniędzy: lista Kontraktorzy dzieli dane po `tab` (active/ending/ended) i pokazuje liczniki na kaflach, a panel „Kończące się" to ostrzeżenie o wygasaniu w 30 dni, na którym pracują Delivery Leadowie. Aneks przedłużający kontrakt o 3 miesiące zostawia go w panelu wygasających nawet na 5 minut, a zakończenie zostawia kontraktora w kubełku aktywnych do chwili, gdy lista przypadkiem odmontuje się w stanie stale.

**Naprawa.** Zamień `["contracts"]` we wszystkich czterech miejscach na klucze, które istnieją — `["contracts-v2"]`, `["contracts-expiring-v2"]`, `["contractors-v2"]`, `["contractors-stats-v2"]` — a ponieważ zakończenie zasila też profil klienta, dodaj `["client-profile", clientId]` (co `TerminateContractModal.tsx:41` robi już poprawnie w bliźniaczym dialogu po stronie klienta). Potem dodaj skan źródeł „producent istnieje" opisany w poprzednim znalezisku, żeby zmiana nazwy klucza listy nigdy więcej nie zostawiła po sobie martwej inwalidacji.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 52` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f56"></a>

### #56 · P2 · Globalny rejestr kontraktów wciąż używa martwej mapy statusów z kwietnia 2026 (`expiring`/`terminated`, bez `ending`), podczas gdy poprawna polska mapa istnieje już w `lib/contract-register.ts` i jest używana przez rejestr per klient na tej samej stronie — więc `ending` traci swój bursztynowy kolor ostrzegawczy, a plakietka drukuje surowy angielski enum

nakład **M** · obszar **Frontend · UI** · **dług** · kategoria `debt`

`frontend/src/components/v2/pages/ContractsListV2.tsx:71`

**Co to kosztuje.** Dwie konkretne straty na rejestrze kontraktów, czyli ekranie, na którym Delivery Leadowie pilnują marży i wygasania. Po pierwsze, `ending` („< 30 dni do końca") nie ma wpisu w `STATUS_VARIANT`, więc jedyny status istniejący po to, by ostrzegać, że współpraca kontraktora się kończy, renderuje się w neutralnym szarym fallbacku zamiast w kolorze ostrzegawczym, który zarezerwowano dla `expiring` — wartości, której nic nie produkuje. Po drugie, plakietka drukuje surowy klucz enuma, więc polskojęzyczny rejestr pokazuje „active", „ending", „draft", a dla kontraktów w procesie podpisu dosłowny string „ready_for_signature" — stan realnie osiągalny przez `contract_lifecycle.move_to_ready_for_signature`, którego filtr na `/contracts` nawet nie umie wybrać, więc takich kontraktów nie da się znaleźć po statusie. `void` (miękko usunięty, trzymany jako dowód podpisu) jest osiągalny bezpośrednim URL-em i renderuje się na stronie szczegółów bez stylu i bez etykiety.

**Naprawa.** Stwórz jeden eksportowany moduł (np. `lib/contract-status.ts`) trzymający wszystkie sześć wartości `ContractStatus` z polską etykietą i wariantem plakietki, wygenerowany z `backend/app/api/contracts.py:671` `_CONTRACT_STATUS_LABELS` albo sprawdzany względem niego, i spraw, by `ContractsListV2`, `contracts/[id]/page.tsx`, `filter-options.ts` oraz `ContractorStatus` go importowały. Skasuj klucze `expiring` i `terminated` — nic ich nie emituje. Dodaj test jednostkowy asertujący, że zbiór kluczy mapy z FE jest równy enumowi z backendu, żeby kolejne dodanie wartości do enuma wywalało CI zamiast wyciekać angielski identyfikator do UI.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 56` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f57"></a>

### #57 · P2 · TipTap/ProseMirror siedzi w bundlu trasy /candidates/[id], choć jego jedyny konsument wymaga trzech świadomych kroków nawigacji plus istniejącego draftu umowy, a nic nie prefetchuje tego chunku (recharts ma ten sam kształt na /dashboard); 2 granice dynamic() na 177k LOC, brak analyzera

nakład **M** · obszar **Frontend · UI** · **ryzyko** · kategoria `perf`

`frontend/src/components/v2/pages/CandidateDetailV2.tsx:8`

**Co to kosztuje.** Profil kandydata to ekran, który rekruterzy otwierają dziesiątki razy dziennie przy triażu bazy 49k kandydatów, i jest to najcięższa trasa w aplikacji: 614 kB First Load JS, z czego 372 kB to część specyficzna dla trasy, doliczana do 242 kB, które płaci już każda trasa. Sporą część tego stanowi edytor rich-text oparty na ProseMirror, który renderuje się wyłącznie za ścieżką Dokumenty -> Umowy -> konkretny draft umowy — a większość wizyt na profilu nigdy tam nie idzie. /dashboard ma 465 kB z tego samego powodu (recharts, importowany statycznie dla jednego wykresu trendu). Na biurowym wifi to dodatkowa sekunda lub więcej pobierania i parsowania na głównym wątku przy każdym zimnym otwarciu profilu, powtarzana przez cały dzień, dla kodu, o który użytkownik nie prosił. Ponieważ nigdzie nie ma konfiguracji bundle-analyzera, koszt jest też niewidoczny: nikt nie dostaje sygnału, gdy kolejna ciężka biblioteka wyląduje w imporcie na poziomie modułu.

**Naprawa.** Przenieś obie ciężkie biblioteki za next/dynamic dokładnie tak, jak robi to już settings/page.tsx: (a) wyciągnij blok edytora draftu umowy z CandidateDetailV2.tsx do osobnego pliku i zaimportuj go przez `dynamic(() => import("./ContractDraftEditor"), { ssr: false, loading: ... })`, kasując importy @tiptap z poziomu modułu; (b) w RecruitmentStatsSection.tsx zamień statyczny import RecruitmentTrendChart na `dynamic(...)`. Potem dodaj @next/bundle-analyzer za flagą env w next.config.ts i wypisuj rozmiary tras w jobie CI Frontend, żeby następna regresja była widoczna. Tabela builda w CI już emituje First Load JS per trasa — asercja sufitu na /candidates/[id] zamieniłaby to w bramkę zamiast okresowego sprzątania.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 57` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f58"></a>

### #58 · P2 · Lokalny dla pliku FieldGroup w AppShell renderuje <label> jako rodzeństwo bez htmlFor, więc klik-w-etykietę-by-sfokusować jest martwy na wszystkich 60 polach modali Dodaj/Edytuj Kandydata/Ofertę/Klienta, a 23 kontrolki — 18 z nich to <select>, gdzie placeholder nie zastąpi nazwy — nie mają w ogóle dostępnej nazwy

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/AppShell.tsx:229`

**Co to kosztuje.** Każdy rekruter dodający lub edytujący kandydata, rekrutację czy klienta pracuje w formularzu, w którym kliknięcie podpisu pola nie robi nic — standardowe zachowanie klik-w-etykietę-by-sfokusować jest po cichu nieobecne na ~578 kontrolkach, w tym na 60 w modalach Dodaj/Edytuj Kandydata i Dodaj/Edytuj Ofertę. Dla kogoś korzystającego z czytnika ekranu te same formularze są znacznie gorsze: każda kontrolka jest odczytywana jako nienazwane pole edycji, więc wypełnienie formularza Dodaj kandydata oznacza zgadywanie, które puste pole to Imię, a które Nazwisko. Sterowanie głosem ("kliknij Imię") zawodzi z tego samego powodu. To produkt, do którego agencja sprzedaje dostęp i na którym prowadzi całą operację rekrutacyjną; formularze są jego drzwiami wejściowymi.

**Naprawa.** Nadaj FieldGroup wygenerowane id i zepnij oba końce: `const id = React.useId()` w FieldGroup, `htmlFor={id}` na <label> i przekaż id w dół — albo klonując pojedyncze dziecko (`React.cloneElement(children, { id })`), albo, czyściej, zmieniając sygnaturę na `children: (id: string) => ReactNode`. Naprawa tego jednego helpera pokrywa 65 miejsc wywołania i osiem modali w AppShell.tsx jedną zmianą. Potem dodaj reguły `label-has-associated-control` i `control-has-associated-label` z eslint-plugin-jsx-a11y; ESLint chodzi obecnie na 184 przy limicie 300 warningów, więc jest zapas, żeby wprowadzić je najpierw jako warningi i dokręcać.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 58` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f59"></a>

### #59 · P2 · ~19 ręcznie sklecionych szkieletów modali (zakończenie umowy, admin reset hasła, przedłużenie zamówienia, zamknięcie rekrutacji jako przegranej) nie ma obsługi Escape, focus trapu/przywrócenia fokusu ani roli dialog — 14 z nich nie ma też zamykania kliknięciem w tło, więc jedyne wyjście to klik myszką; komentarze w samym repo już nazywają to antywzorcem, a tylko 8 modali zmigrowano na Radix

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/contracts/ContractTerminationDialog.tsx:47`

**Co to kosztuje.** Escape nie zamyka żadnego z tych dialogów — łącznie z tymi, które bramkują operacje destrukcyjne i związane z pieniędzmi: zakończenie współpracy z konsultantem, reset hasła innego użytkownika, zamknięcie rekrutacji jako przegranej, przedłużenie zamówienia. Escape-żeby-anulować to odruch każdego użytkownika, więc na 22 ekranach aplikacja po prostu nie reaguje. Dla użytkowników klawiatury awaria jest większa: bez focus trapu Tab wychodzi prosto z dialogu na stronę pod spodem, gdzie elementy są wizualnie zasłonięte overlayem, ale wciąż fokusowalne i klikalne — można przejść tabem do kontrolki, której nie widać, i ją uruchomić. Czytniki ekranu nie dostają w ogóle ogłoszonej granicy dialogu (brak role="dialog"/aria-modal), więc modal czyta się jak zwykła treść strony i użytkownik nie ma sygnału, że reszta strony jest nieaktywna.

**Naprawa.** Wszystkie mają ten sam 20-liniowy kształt, więc to robota mechaniczna: zastąp zewnętrzny `<div className="fixed inset-0 …">` plus wewnętrzny panel przez `<AppModal open onOpenChange={onClose} title=…>` (components/ds/AppModal.tsx), który idzie już przez Radix i dziedziczy focus trap, Escape, aria-modal oraz przywrócenie fokusu przy zamknięciu. Zacznij od czterech, które bramkują operacje destrukcyjne lub na poświadczeniach (ContractTerminationDialog, ResetPasswordModal, CloseJobAsLostModal, UserModal), potem przerób resztę. Potem dodaj guard w lincie — skrypt check-modals w duchu istniejącego scripts/check-candidate-token-usage.mjs, wywalający się na overlayu `fixed inset-0` w pliku, który nie importuje żadnego prymitywu dialogu — żeby numer 23 nie dał się dodać po cichu.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 59` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f62"></a>

### #62 · P2 · Zwinięty panel "Statystyki współpracy" na domyślnej zakładce profilu klienta odpala niecache'owany 6-iteracyjny raport hit-ratio (~20 sekwencyjnych round tripów do bazy) przy każdym otwarciu

nakład **S** · obszar **Frontend · UI** · **ryzyko** · kategoria `perf`

`frontend/src/app/clients/[id]/page.tsx:888`

**Co to kosztuje.** Każde otwarcie profilu klienta kosztuje pięć round tripów API dla trzech paneli, które użytkownik ogląda w stanie zwiniętym. Te requesty konkurują z widoczną treścią (własne zapytanie client-profile w ProfileTab, FrameworkContractsTab w :928) o budżet połączeń przeglądarki i o pojemność backendu — a jeden z nich, MaterialsTab, to powierzchnia listowania dokumentów, najcięższa z całej grupy. Delivery Leadzi i TAC-e otwierają profile klientów bez przerwy, więc to stała wielokrotność obciążenia, jakie ta trasa generuje na produkcyjnym Postgresie, w całości dla danych, które nigdy nie są rysowane. Komentarz w :882 uczciwie tłumaczy wybór — natywne `<details>` wybrano, żeby uniknąć stanu Reacta — ale kosztem tego kompromisu jest dokładnie to, że `<details>` nie potrafi montować leniwie.

**Naprawa.** Zostaw natywne <details> (argument o braku stanu Reacta jest sensowny) i zabramkuj wyłącznie montowanie: trzymaj flagę otwarcia przez `onToggle={(e) => setOpen(e.currentTarget.open)}` na każdym <details> i renderuj `{open && <MaterialsTab …/>}`, albo wyciągnij drobny wrapper `<LazyDetails summary={…}>`, który robi to raz, i użyj go w :888, :909, :930 i :968. Tańszy wariant, jeśli dotykanie markupu jest niemile widziane, to przekazanie `enabled` w dół do useQuery każdego dziecka — ale to wpycha troskę layoutową do czterech komponentów pobierających dane, więc wrapper jest lepszym kształtem.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 62` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f66"></a>

### #66 · P2 · Heurystyka conftestu oparta na NAZWIE fixture'a błędnie klasyfikuje in-process test ASGI jako live-server: wszystkie 6 testów w `test_dynareporter_readonly.py` jest SKIPPED przy każdym biegu CI, przez co blokada zapisu `DYNAREPORTER_MODE=read_only` (domyślnie żywa na prodzie) ma zerowe wykonane pokrycie — a `test_ci_coverage_contract.py` tego nie widzi, bo audytuje wyłącznie `--ignore`, nigdy skipów w runtime

nakład **S** · obszar **Testy** · **dług** · kategoria `test-gap`

`backend/tests/conftest.py:295`

**Co to kosztuje.** Reguła skipowania dopasowuje się po NAZWIE fixture'a, więc nie odróżnia live-serverowego fixture'a z conftestu od lokalnego override'u na `ASGITransport`. `test_dynareporter_readonly.py` nie jest na liście `--ignore` w CI i jest zbierany przy każdym biegu, a następnie cicho oznaczany jako SKIPPED — łącznie z `test_read_only_blocks_every_report_write`, który enumeruje każdą mutującą trasę `/api/dynareporter` z żywej tablicy routera i asertuje, że każda zwraca 409. Poprawka P0.3, którą ten test miał zabetonować (`read_only` cicho przyjmujący POST/PUT/PATCH/DELETE, czyli „archiwum", które nadal przyjmuje zapisy), nigdy nie została zweryfikowana przez CI, a razem z nią niezweryfikowane są lista wyjątków (mindy / read-marker / upload) i override break-glass. W całym suicie ta sama reguła cicho usuwa 37 funkcji testowych w 7 plikach, a skoro `RUN_LIVE_TESTS` jest na sztywno ustawione na „0", nie biegną one w żadnym środowisku.

**Naprawa.** Przestań dopasowywać po nazwie. Oznacz dwa legacy live-serverowe fixture'y w `conftest.py` markerem (np. `pytest.mark.live`) albo sprawdzaj `item.fixturenames` względem faktycznego miejsca definicji fixture'a przez `item._fixtureinfo.name2fixturedefs["client"][-1].baseid` i skipuj tylko, gdy rozwiązuje się to do conftestu — plik, który lokalnie nadpisuje `client`, nie może być łapany. Najtańszy poprawny wariant: przemianuj fixture w confteście na `live_client` i zaktualizuj 37 miejsc użycia, co usuwa niejednoznaczność na stałe. Potem potwierdź, że 6 testów z `test_dynareporter_readonly.py` faktycznie się wykonuje i przechodzi, zanim zaczniesz na nich polegać.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 66` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f71"></a>

### #71 · P2 · Raport o lukach usuwania danych nadal twierdzi, że na `contracts` jest CASCADE, które migracja 0225 zamieniła na SET NULL 2026-08-12 — jego główna liczba „evidence rows a hard delete would destroy" jest teraz fikcją, a docstring dalej twierdzi, że endpoint twardego usunięcia jest wyłączony

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `ops`

`backend/app/api/admin_candidate_pii_orphans.py:113`

**Co to kosztuje.** `/api/admin/candidate-pii-orphans` to jedyne narzędzie w produkcie do decydowania, czy usunięcie danych w trybie RODO można bezpiecznie wykonać, a jego `summary.evidence_rows_a_hard_delete_would_destroy` to liczba, na którą operator spojrzy najpierw. Ta liczba jest teraz czystą fikcją: migracja `0225_contract_survives_candidate_delete` przeniosła `contracts.candidate_id` z ON DELETE CASCADE na SET NULL i dodała pseudonim `candidate_subject_ref` dokładnie po to, żeby faktury, `document_signatures` i `client_orders` przeżyły. Raport był ostatnio ruszany 2026-07-29 (b5105207); zmiana FK i ponowne włączenie endpointu DELETE weszły oba 2026-08-12 (2c42e11f). Docstring modułu jest nieaktualny w tym samym kierunku — nadal mówi „This is the safe first step of the erasure work. It deliberately does NOT re-enable the disabled DELETE endpoint", co już nie jest prawdą. Operator, który to przeczyta, albo odmówi zgodnego z prawem żądania usunięcia, które powinien uhonorować, albo straci zaufanie do całego raportu.

**Naprawa.** Przepisz trzy opisy `blast_*` tak, żeby opisywały SET NULL (kontrakty przeżywają, odpięte i spseudonimizowane), zmień nazwę klucza podsumowania z `evidence_rows_a_hard_delete_would_destroy` na inną, podbij `QUERY_VERSION` powyżej `candidate-pii-orphans-v2`, żeby stare i nowe biegi dało się odróżnić, i wywal akapit „does NOT re-enable the disabled DELETE endpoint". Przy okazji: `traffit_webhook_events_total` ma ocenę „high", ale żaden endpoint nigdzie nie pisze do tej tabeli, więc zawsze raportuje 0 — zdecyduj, czy w ogóle należy do tego raportu.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 71` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f72"></a>

### #72 · P2 · Produkcyjne `/openapi.json`, `/docs` i `/redoc` są publiczne i nieuwierzytelnione — 747 ścieżek, 876 schematów i 118 KB wewnętrznych docstringów o bezpieczeństwie (w tym nazwy env kill-switchy i allowlista break-glass) serwowane anonimowym wywołującym

nakład **S** · obszar **Backend** · **ryzyko** · kategoria `security`

`backend/app/main.py:643`

**Co to kosztuje.** Ktokolwiek w internecie dostaje kompletny plan architektoniczny ATS-a trzymającego ~49 tys. profili kandydatów i ~136 tys. CV, bez uwierzytelnienia. Zweryfikowane na żywo: `/openapi.json` zwraca 200 i 1 392 735 bajtów (747 ścieżek, 906 operacji, 876 schematów); `/docs` i `/redoc` też zwracają 200. Ponieważ FastAPI emituje blok `security` tylko dla operacji niosących zależność bearer, opublikowana specyfikacja jest precyzyjnym, maszynowo czytelnym inwentarzem powierzchni ataku: 874 operacje deklarują HTTPBearer, a dokładnie 32 nie deklarują nic. Ta lista — każda trasa `/api/auth/*`, wszystkie siedem tokenowych powierzchni `/api/public/*`, webhooki CloudTalk i Microsoft Graph, `/api/oauth/token`, `/api/autenti/webhook`, `/api/health/deep` i `/api/health/alembic` — to cała faza rekonesansu, wydana za jednego anonimowego GET-a. Specyfikacja publikuje też dokładne kształty żądań dla tych nieuwierzytelnionych tras, w tym zgłoszony już wcześniej `refresh_token` jako parametr `in: "query"` na `POST /api/auth/refresh` oraz body `PublicEngagementSubmit` na nielimitowanej publicznej trasie engagement. Nie ma żadnej kontroli kompensacyjnej na brzegu: `api.nexus.dynaminds.pl` odpowiada z `server: uvicorn` i bez `cf-ray`, czyli jest gray-cloud i nie stoi za żadnym WAF-em Cloudflare — fakt, który repo samo dokumentuje w `backend/app/core/rate_limit.py`. Nic tej specyfikacji nie konsumuje: wtyczka LinkedIn nie ma do niej żadnych odwołań, żaden workflow ani smoke test nie dotyka `/docs`, a jedyni dwaj wywołujący `app.openapi()` to testy odpalające to jako metodę in-process.

**Naprawa.** Przepuść trzy parametry dokumentacji przez bramkę DEBUG, której ten plik używa już osiem linii wyżej dla HSTS/CSP: `app = FastAPI(..., docs_url="/docs" if settings.DEBUG else None, redoc_url="/redoc" if settings.DEBUG else None, openapi_url="/openapi.json" if settings.DEBUG else None)`. Zweryfikowane jako bezpieczne: żaden workflow, smoke test, uptime probe, skrypt ani plik rozszerzenia nie odwołuje się do żadnego z tych trzech URL-i, a dwa testy używające schematu (`test_analytics_release_gates.py:281`, `test_m365_candidate_access.py:74`) wołają METODĘ `app.openapi()`, która nadal buduje schemat, gdy trasa jest pominięta — przepuść te dwa testy ponownie, żeby to potwierdzić. Jeśli zespół chce mieć to UI do użytku wewnętrznego, zamontuj te trzy trasy za istniejącą zależnością admin JWT zamiast je kasować; nie polegaj na Cloudflare, bo ten host celowo nie jest proxowany.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 72` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f73"></a>

### #73 · P2 · Produkcyjny `/openapi.json` jest publiczny i publikuje 118 641 znaków wewnętrznego uzasadnienia inżynierskiego — w tym allowlistę break-glass, która trzyma przy życiu LOGOWANIE hasłem (nie tylko odzyskiwanie), podczas gdy tryb SSO-only zwraca 503 wszystkim pozostałym

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `security`

`backend/app/api/auth.py:633`

**Co to kosztuje.** FastAPI kopiuje każdy docstring handlera do pola `description` w publicznej specyfikacji. Wyciągnąłem je z żywego produkcyjnego `/openapi.json`: 559 z 906 operacji je niesie, łącznie 118 641 znaków. Ta baza kodu pisze wyjątkowo szczere docstringi — to instytucjonalna pamięć zespołu — i całość jest teraz publiczna. Same zacytowane dwie linijki mówią nieuwierzytelnionemu czytelnikowi, że produkcja jest wyłącznie na Microsoft SSO (`POST /api/auth/login` publikuje: „na produkcji jedyną drogą wejścia jest Microsoft SSO... Flaga stoi tam na False → 503"), że ISTNIEJE imienna allowlista adresów e-mail, która omija tę bramkę, i że odzyskiwanie hasła nadal działa dla adresów z tej listy. To zamienia „logowanie hasłem jest wyłączone" z kontroli w problem namierzania celu: znajdź tego jednego admina break-glass. Ta sama ekstrakcja opublikowała też `POST /api/microsoft365/webhooks` ogłaszający „No slowapi rate limit by design" wraz z uzasadnieniem (atakujący nie musi odkrywać, który endpoint jest nielimitowany — to jest udokumentowane); `POST /api/calls/webhook` wyjaśniający, że gdy `CLOUDTALK_ENABLED` jest `False`, handler zwraca 200 „bez sprawdzenia HMAC (sekret może nie być jeszcze skonfigurowany)" — a CLAUDE.md odnotowuje, że CloudTalk jest celowo uśpiony, czyli że to właśnie ta gałąź jest żywa; `DELETE /api/candidates/{id}` wyliczający, czego usuwanie RODO celowo NIE czyści („`traffit_webhook_events` nie ma FK na kandydata, więc surowy payload integracji zostaje. To znany brak"); oraz `GET /api/team-structure/dl-clients` ujawniający migrację firmowej poczty @b2bnetwork.pl → @inframinds.eu i to, że pracownicy mają zdublowane konta w obu domenach — dokładnie te dwa fakty, których kampania phishingowa przeciw tenantowi SSO potrzebuje najbardziej. Opublikowane zostały także 23 wewnętrzne nazwy zmiennych środowiskowych, w tym `ANALYTICS_CUTOVER_BREAKGLASS` i `KPI_COACH_DEBUG_BREAKGLASS`.

**Naprawa.** Zamknięcie `/openapi.json` (finding powyżej) natychmiast to domyka i jest priorytetem. Osobno: ustal stałą politykę, żeby nie otworzyło się to po cichu ponownie — uzasadnienia wrażliwe bezpieczeństwowo należą do komentarzy `#` (których FastAPI nigdy nie publikuje), nie do docstringów. Przenieś akapit o break-glass z `auth.py:633`, blok „No slowapi rate limit by design" z `microsoft365.py`, opis DRY-RUN/brak HMAC dla CloudTalka z `calls.py` i akapit „to znany brak" z `DELETE` w `candidates.py` nad `def` jako komentarze; w docstringu zostaw zachowanie widoczne dla wołającego (kody statusu, kształt żądania, gwarancję anti-enumeration). Tani test-strażnik może asertować, że żaden opis operacji w `app.openapi()` nie pasuje do /BREAK_?GLASS|break-glass|no .*rate limit|znany brak/i.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 73` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f74"></a>

### #74 · P2 · `/openapi.json` jest nieuwierzytelniony i nielimitowany: ~20 ms synchronicznego `json.dumps` re-serializowanego na każde uderzenie, na celowo jednoworkerowej pętli zdarzeń (koszt na łączu to 224 KB po gzipie, nie 1,39 MB)

nakład **S** · obszar **Backend · rdzeń** · **ryzyko** · kategoria `perf`

`backend/app/core/rate_limit.py:70`

**Co to kosztuje.** `default_limits=[]` oznacza, że slowapi nie stosuje niczego, dopóki handler nie niesie jawnego `@limiter.limit`, a wbudowana trasa `/openapi.json` FastAPI żadnego nie ma — więc to jedyny nieuwierzytelniony endpoint w produkcie, który zwraca 1,39 MB. FastAPI cache'uje SŁOWNIK schematu, ale `JSONResponse` Starlette re-serializuje go przy każdym pojedynczym żądaniu; zmierzyłem `json.dumps` dokładnego produkcyjnego payloadu na 20–23 ms, czyli 20+ ms synchronicznego CPU na pętli zdarzeń na jedno uderzenie, zanim te 1,39 MB w ogóle zostanie wypisane. Ta pętla zdarzeń jest jednym procesem z jawnego założenia — `backend/entrypoint.sh:5197` to `exec uvicorn app.main:app --host 0.0.0.0 --port 8000` bez `--workers`, a `docker-compose.yml:51` ostrzega „to NIE jest zaproszenie do dokładania workerów uvicorna" — więc cokolwiek ją blokuje, blokuje jednocześnie każdego rekrutera. I nie ma przed nią edge'a: `curl -I` na tym hoście zwraca `server: uvicorn` bez `cf-ray`, zgodnie z notatką w docstringu tego samego pliku, że api.nexus.dynaminds.pl jest gray-cloud. Pomiar na produkcji: `/api/health` trzymał stabilne 0,203 / 0,205 / 0,243 s TTFB; przy 8 równoczesnych anonimowych żądaniach `/openapi.json` w locie ta sama sonda zwróciła 1,804 s i 3,948 s — mniej więcej 19×. Bieg sekwencyjny też wyprodukował jedno 3,820 s TTFB bez prowokacji. Pojedynczy burst z jednego zewnętrznego hosta, więc dokładne liczby traktuj jako poglądowe, nie jako wynik load-testu; kierunek odtworzył się dwukrotnie.

**Naprawa.** Usunięcie trasy na produkcji (jednolinijkowiec z findingu #1) eliminuje to całkowicie i jest właściwą naprawą. Jeśli trasa z jakiegoś powodu musi zostać, potrzebuje jednocześnie jawnego `@limiter.limit` i wstępnie zserializowanego body — zbuduj bajty JSON raz przy starcie i zwracaj `Response(content=cached_bytes, media_type="application/json")`, żeby 20 ms `json.dumps` nie powtarzało się na żądanie. Nie rozwiązuj tego dokładaniem workerów uvicorna: `docker-compose.yml:51` oraz rejestr `background_tasks` w `app/main.py` zakładają, że proces jest dokładnie jeden.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 74` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f75"></a>

### #75 · P2 · `/docs` i `/redoc` zwracają 200, ale renderują się pusto — własne CSP aplikacji zabija cały ich runtime, na fałszywej przesłance zapisanej w komentarzu middleware'u, podczas gdy surowy `openapi.json` (747 ścieżek) działa nietknięty

nakład **S** · obszar **Backend** · **nie działa** · kategoria `broken`

`backend/app/main.py:318`

**Co to kosztuje.** Przesłanka z komentarza jest faktycznie nieprawdziwa: ta aplikacja serwuje HTML na co najmniej siedmiu trasach, z czego trzy są własnymi trasami frameworka (`/docs`, `/redoc`, `/docs/oauth2-redirect`). `curl -I https://api.nexus.dynaminds.pl/docs` zwraca 200 z `content-security-policy: default-src 'none'; frame-ancestors 'none';`, a zwracane body to standardowa strona Swaggera z FastAPI, której runtime jest w całości zewnętrzny plus inline: `<link ... href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">`, `<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js">` i inline'owy `<script>` wołający `SwaggerUIBundle`. Przy `default-src 'none'` i bez `script-src` ani `'unsafe-inline'` przeglądarka blokuje arkusz stylów, bundle z CDN i inline'owy bootstrap — strona renderuje się jako pusty `<div id="swagger-ui">`. `/redoc` jest identyczne (bundle redoc z cdn.jsdelivr.net plus arkusz z Google Fonts). Wynik jest dokładnie odwrócony: połowa, której deweloper faktycznie by chciał (przeglądalne UI), jest martwa, a połowa niosąca całe ryzyko (surowa, maszynowo czytelna specyfikacja, która jest JSON-em i CSP jej nie dotyczy) działa bez zarzutu. Baza kodu zna już poprawny wzorzec i stosuje go gdzie indziej — `contracts.py:1931` i `contract_templates.py:371` doklejają własny nagłówek `Content-Security-Policy` do swojego `HTMLResponse`, a ponieważ ten middleware używa `setdefault`, jawny nagłówek wygrywa. Po prostu nigdy nie zastosowano tego do własnych stron frameworka, przez przekonanie zakodowane w komentarzu.

**Naprawa.** Preferowane: usuń te trzy trasy na produkcji zgodnie z findingiem #1 — wtedy komentarz znów staje się prawdziwy i nie ma zepsutej strony do tłumaczenia. Jeśli natomiast UI dokumentacji ma zostać do użytku wewnętrznego za autoryzacją, napraw też przesłankę: popraw komentarz (ta aplikacja JEDNAK serwuje HTML — `/docs`, `/redoc` oraz widoki wydruku kontraktów/CV) i albo wyłącz ścieżki dokumentacji w `SecurityHeadersMiddleware.dispatch`, albo hostuj assety Swaggera/ReDoc u siebie i doklej per-response CSP w rodzaju `default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'` — tą samą techniką jawnego nagłówka, którą `contracts.py:1931` już skutecznie stosuje.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 75` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f76"></a>

### #76 · P2 · „Oznacz jako zapłaconą" stempluje `paid_date` ze zamrożonej na poziomie modułu, przesuniętej do UTC stałej — kolumna finansowa tylko-do-zapisu, bez ścieżki korekty w UI

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/ContractInvoicesTab.tsx:34`

**Co to kosztuje.** `paid_date` jest wejściem do jedynej metryki należności, jaką produkuje moduł Finanse — `avg_dso_days` w `GET /api/invoices/dso` (Days Sales Outstanding per klient). `grep -rn paid_date frontend/src` zwraca dokładnie dwa trafienia: deklarację pola w TypeScripcie i ten zapis. Nigdzie we froncie nie ma date pickera ani formularza edycji, więc użytkownik Finansów, któremu wyjdzie zły `paid_date`, nie poprawi go bez bezpośredniego dostępu do bazy. Na tej jednej linii siedzą dwa niezależne defekty: (a) `toISOString()` jest w UTC, więc między 00:00 a 02:00 czasu warszawskiego stempel to wczoraj — płatność potwierdzona 1 września o 00:30 księguje się na 31 sierpnia i ląduje w złym miesiącu przy uzgadnianiu; (b) o wiele gorsze — `TODAY` jest stałą NA POZIOMIE MODUŁU. To komponent `"use client"` importowany statycznie przez `/contracts/[id]/page.tsx`, więc jest wyliczany raz, przy pierwszym wykonaniu chunku trasy w karcie, i nigdy nie jest przeliczany przy miękkich nawigacjach. Karta ATS zostawiona otwarta przez kilka dni — czyli normalny sposób używania tego produktu — zamraża datę płatności na moment otwarcia karty. Tylko dwa pliki w całym, 177-tysięcznolinijkowym froncie mają ten wzorzec stałej modułowej i oba to domyślne daty w obszarze finansowo-prawnym.

**Naprawa.** Usuń stałą na poziomie modułu i licz datę w momencie wywołania, w strefie warszawskiej — np. wspólny helper `todayWarsaw()` na `new Intl.DateTimeFormat('sv-SE', {timeZone:'Europe/Warsaw'}).format(new Date())` (sv-SE daje `YYYY-MM-DD`). Jeszcze lepiej: w ogóle przestań wysyłać `paid_date` z klienta — niech handler PATCH stempluje ją po stronie serwera przy przejściu statusu na `paid`, żeby daty płatności nie dyktowała nieświeża przeglądarka. Zastosuj ten sam helper do bliźniaczej zamrożonej stałej w `ContractAmendmentsTab.tsx:62` i do pozostałych 15 miejsc z `new Date().toISOString().slice(0,10)`. Dodaj naruszenie `paid >= issue` do odpowiedzi DSO jako jawną flagę jakości, zamiast po cichu filtrować wiersz.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 76` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f77"></a>

### #77 · P2 · Podia konkursów kubełkują zdarzenia milestone'ów po miesiącu/kwartale UTC, podczas gdy własny panel KPI rekrutera kubełkuje te same zdarzenia po miesiącu warszawskim — dwie rozjechane implementacje jednej reguły, a wynik konkursu jest potem zamrażany na stałe, z przypiętą nagrodą pieniężną

nakład **M** · obszar **Backend · serwisy** · **nie działa** · kategoria `broken`

`backend/app/services/competitions.py:112`

**Co to kosztuje.** Od tego okna zależą realne pieniądze: `MONTHLY_RACE_PRIZE_PLN = 1500` (voucher) i `QUARTERLY_PRIZES_PLN = {1: 5000, 2: 3000, 3: 2000}`. Granice UTC oznaczają, że polski miesiąc kalendarzowy jest liczony jako [1. dnia 02:00 czasu warszawskiego, 1. dnia następnego miesiąca 02:00). To rozjechana, równoległa implementacja jednej reguły, a nie odosobniona wpadka: TE SAME bazowe zdarzenia `hired` / rekomendacji są kubełkowane do miesięcy warszawskich przez `kpi_engine.period_bounds` (`start = now_w.replace(day=1, hour=0, ...)` po `_as_warsaw`, `kpi_engine.py:94`) na potrzeby panelu KPI rekrutera, więc obie powierzchnie mogą się nie zgadzać co do tego, do którego miesiąca należy dane wstawienie. Moduł zna już kalendarz warszawski — definiuje `_WARSAW = ZoneInfo(DEFAULT_TZ)` w linii 67 i używa go, starannie i z odpornym na DST trikiem z południem, w `business_days_elapsed_in_month` — więc granice UTC to niespójność wewnątrz jednego pliku, nie brakująca funkcjonalność. I błąd sam się nie koryguje: `freeze_competition` (`competitions.py:786`) dokumentuje, że „zamrożony okres historyczny jest niezmienny", a ponowne zamrożenie to jawny, logowany no-op — więc gdy godzinowy autofreeze zapisze podium, błędne przypisanie da się cofnąć tylko ręczną edycją `competition_winners`.

**Naprawa.** Zbuduj `month_bounds`/`quarter_bounds` na `_WARSAW` (`datetime(year, month, 1, tzinfo=_WARSAW)`) — porównania idą już przeciw kolumnom `timestamptz` ze świadomością strefy, więc nic dalej się nie zmienia — i wyprowadź `today` w `competition_autofreeze._run_once` z `local_now(settings.BUSINESS_TZ).date()` zamiast `date.today()`. Ponieważ istniejące wiersze `competition_winners` są z założenia niezmienne, wypuść to jako zmianę tylko-w-przód i odnotuj przesunięcie granicy; nie przeliczaj historii. Dodaj test regresyjny przypinający zegar (wymaga freezegun, którego backend obecnie nie ma) na 2026-08-31T22:40Z i asertujący, że zdarzenie wpada w okno wrześniowe.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 77` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f78"></a>

### #78 · P2 · `date.today()` porównywane z kolumną `timestamptz` kompiluje się do `$1::DATE` i jest rozwiązywane na północy UTC sesji Postgresa, a nie na granicy miesiąca warszawskiego — a `ENV TZ=Europe/Warsaw` dowodnie tej granicy NIE przesuwa. Widoczna dla użytkownika instancja to kafel KPI „Nowe (ten miesiąc)" zasilany z `reports.py:400`, a nie martwy w UI `/api/dashboard/stats`, który cytuje zgłoszenie.

nakład **M** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk`

`backend/app/services/dashboard_metrics.py:74`

**Co to kosztuje.** 113 wywołań `date.today()` implementuje polskie granice dni roboczych na kontenerze, którego zegar jest w UTC — udowodnione, nie założone: żadne `TZ` nie występuje w `backend/Dockerfile`, w żadnym z plików compose, w overlayu ani w `entrypoint.sh`, a dokładny, przypięty digestem obraz bazowy (`python:3.13-slim@sha256:6771159cd4fa...`) raportuje `time.tzname ('UTC','UTC')` z `/etc/localtime -> Etc/UTC`. `moved_at` jest `DateTime(timezone=True)` (`recruitment_pipeline.py:114-116`), więc ta linia porównuje `timestamptz` z naiwną datą Pythona. Zmierzyłem, co to robi na prawdziwym stacku (SQLAlchemy 2.0.36 + asyncpg 0.30.0 + Postgres 16, `SHOW TimeZone` = UTC): binduje się bez błędu i rozwiązuje na północy UTC — moja sonda naliczyła 1 z 2 wierszy, gubiąc ten o 2026-08-31T22:30Z. Powodem, dla którego to zgłaszam zamiast wzruszyć ramionami nad dwugodzinnym pasem, jest pułapka w lekarstwie: ustawienie `ENV TZ=Europe/Warsaw` naprawia `date.today()` i wyglądałoby, jakby naprawiło wszystko, podczas gdy to porównanie zostaje błędne (o granicy decyduje `TimeZone` sesji Postgresa, nie aplikacji), a `competitions.month_bounds` — które hardcoduje `tzinfo=timezone.utc` — nie jest ruszone przez żadną zmienną środowiskową. Dodatkowo przesunęłoby to 7 miejsc z naiwnym `datetime.now()` na warszawski zegar ścienny. Nic w repo nie potrafi wyłapać żadnego z tych stanów: `grep -rn 'freeze_time|freezegun|time_machine' backend/tests` = 0, a freezegun nie jest zależnością — więc laptop deweloperski w strefie warszawskiej i runner CI w UTC nie zgadzają się co do `date.today()` i żaden z nich nie jest przypięty.

**Naprawa.** Nie polegaj na zegarze procesu. Wprowadź jeden helper `business_today()` (`local_now(settings.BUSINESS_TZ).date()`, obok istniejącego `local_day_bounds` w `app/core/scheduling.py`) i przemigruj do niego te wywołania `date.today()`, które są wrażliwe na dzień roboczy. Osobno: przy każdym porównaniu z kolumną `timestamptz` przekazuj datetime ze strefą, nie datę — tutaj `datetime(y, m, 1, tzinfo=ZoneInfo('Europe/Warsaw'))` — bo bind naiwnej daty będzie się dalej rozwiązywał na północy UTC niezależnie od tego, jakie `TZ` ma kontener. Dodaj freezegun do requirements i test przypięty na 2026-08-31T23:00Z asertujący, że zatrudnienie ląduje we wrześniu. Ustawienie `ENV TZ=Europe/Warsaw` jest w porządku jako obrona w głąb, ale nie może być wypuszczone jako naprawa.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 78` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f83"></a>

### #83 · P2 · Baner „ten klient ma specyficzne zapisy" duplikuje backendową tabelę needle'i klauzul i już się rozjechał: nazwy „E-Zdrowie"/„eZdrowie" dostają w pełni podmieniony §10 bez żadnego ostrzeżenia

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/v2/pages/B2BContractGeneratorV2.tsx:261`

**Co to kosztuje.** Ten baner to JEDYNY sygnał, jaki rekruter kiedykolwiek dostaje, że generowany dokument nie jest standardową umową — nie ma pola po stronie serwera, nie ma linii logu, nie ma odpowiednika negatywnego. Gdy się nie wyrenderuje, rekruter wierzy, że produkuje czysty szablon B2B, podczas gdy backend faktycznie podmienia cały §10 na wynegocjowane klauzule o zakazie konkurencji i kary umowne. Wiadomo już, że oba lustra rozjeżdżają się w praktyce: dokładnie ten commit f142a2bc, który poszerzył needle w backendzie, ZAKTUALIZOWAŁ trzecie lustro w frontend/src/components/contracts/ContractRegisterDialog.tsx (jego komentarz do dziś wskazuje na clause_override_content.py), ale zostawił `hasSpecialClauses` nietknięte — zweryfikowane przez `git show f142a2bc --name-only`, które listuje ContractRegisterDialog.tsx i nie listuje B2BContractGeneratorV2.tsx. Test frontendowy utrwala to pominięcie: B2BContractGeneratorSpecialClauses.test.ts asertuje wyłącznie „Centrum e-Zdrowia", podczas gdy backendowy `test_ezdrowie_raw_row_names_hit_centrum_override` asertuje „E-Zdrowie", „eZdrowie" i „e-zdrowie" — obie zestawy testów rozjeżdżają się dokładnie tam, gdzie rozjeżdżają się implementacje, więc CI jest zielone.

**Naprawa.** Przestań utrzymywać trzy kopie jednej reguły. Niech odpowiedź render/preview zwraca rozstrzygnięty klucz override (albo przynajmniej boolean `has_override`, który backend i tak już liczy przez `has_override()`) i steruj banerem z odpowiedzi serwera; usuń `hasSpecialClauses` i wsuń lookup etykiety z ContractRegisterDialog do tej samej odpowiedzi. Jeśli kopia po stronie klienta musi zostać na potrzeby feedbacku przed wysyłką, to minimum: dodaj dwa brakujące needle, odwzoruj zwijanie `\s+` i zasil zarówno suite Pythona, jak i Vitest z jednej wspólnej listy fixture'owej nazw klientów, żeby przyszła zmiana needle'a nie mogła przejść CI po jednej stronie.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 83` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f84"></a>

### #84 · P2 · Matcher klauzul B2B nie normalizuje do NFC; dokładnie jeden needle („rehabilitacji osób niepełnosprawnych") zawiera znak rozkładalny, więc ręcznie wklejona nazwa prawna PFRON w NFD po cichu gubi wynegocjowany §10 (zakaz konkurencji + kary umowne) i renderuje klauzulę domyślną, bez logu i bez banera

nakład **S** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk`

`backend/app/services/b2b_contract_generator/clause_overrides.py:33`

**Co to kosztuje.** Dwa z siedmiu wpisów rejestru zależą od polskich znaków diakrytycznych, a dla PFRON needle z diakrytykami to jedyna droga trafienia kanonicznej nazwy. W zacommitowanym rosterze (client_portfolio_2026_07_30.json) `legal_name` to 'PAŃSTWOWY FUNDUSZ REHABILITACJI OSÓB NIEPEŁNOSPRAWNYCH', który w ogóle nie zawiera podciągu „pfron" — zweryfikowałem to — więc jest łapany wyłącznie przez needle „rehabilitacji osób niepełnosprawnych". Jeśli ten ciąg przyjdzie w formie zdekomponowanej, umowa dla instytucji państwowej wychodzi ze standardowym §10 zamiast wynegocjowanego zakazu konkurencji i kar umownych, oraz (patrz znalezisko 2) bez banera i (patrz znalezisko 4) bez linii logu, która pozwoliłaby to zauważyć. Nazwa klienta jest wolnym tekstem: picker oferuje „Użyj: „{clientQuery}"" dla dowolnej wpisanej lub wklejonej wartości, a samo `Client.name` jest nadpisywane przez każdy sync Traffita, więc matcher nie kontroluje formy bajtowej własnego wejścia. Ta baza kodu dostała już dwa razy po głowie od NFD — poprawki w advanced_candidate_search.py i contracts.py istnieją właśnie dlatego, że zdekomponowane wejście nie dopasowywało się do niczego — a dopasowanie tekstu o najwyższej stawce w produkcie jest tym, które tej poprawki nigdy nie dostało.

**Naprawa.** Jedna linia: `return re.sub(r"\s+", " ", unicodedata.normalize("NFC", name or "").strip().lower())` — dokładnie to, co contracts.py:325 już robi dla wyszukiwania umów. Odwzoruj to na froncie (`String.prototype.normalize("NFC")`), jeśli kopia po stronie klienta przetrwa znalezisko 2. Dodaj test rejestru asertujący, że każdy needle z diakrytykami wciąż dopasowuje swoją kanoniczną nazwę klienta zarówno w formie NFC, jak i NFD, żeby ta gwarancja nie wygasła po cichu przy najbliższej edycji needle'a.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 84` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f85"></a>

### #85 · P2 · Nakładanie override'ów klauzul nie ma kanału sukcesu: udokumentowany licznik z `apply_ops_docx` jest wyrzucany w docx_renderer.py:66, `apply_ops_html` w ogóle nie ma licznika, a cała ścieżka ma zerowe logowanie i zero wyjątków — po cichu pominięta klauzula § jest nie do odróżnienia od poprawnej, czystej umowy

nakład **M** · obszar **Backend · serwisy** · **nie działa** · kategoria `broken`

`backend/app/services/b2b_contract_generator/docx_renderer.py:66`

**Co to kosztuje.** Funkcja jest udokumentowana jako zwracająca liczbę wykonanych operacji, a jedyny produkcyjny wołający ją ignoruje, więc `replace_section`, który nie znajdzie swojego nagłówka §, jest pomijany przez `continue`, a umowa zostaje zapisana i wydana tak, jakby nic się nie stało. Renderer podglądu HTML jest gorszy — nie ma licznika do zignorowania, każda gałąź to gołe `if span:` / `if idx != -1:` / `if pos != -1:` bez żadnego `else` — a jego ramię `after_table` ma zaszyte `out.find("</table>")`, podczas gdy ramię DOCX honoruje `doc.tables[idx]`, więc dwie równoległe implementacje jednej operacji z założenia nie są równoważne. W połączeniu z zerowym logowaniem w clause_overrides.py, clause_override_content.py i docx_renderer.py, brakiem pola w `B2BRenderHtmlResponse` i brakiem negatywnego stanu UI (baner ze znaleziska 2 renderuje się wyłącznie pozytywnie) nie ma żadnego kanału, przez który błędny lub brakujący zestaw klauzul mógłby się zgłosić. To jest ta luka detekcyjna, która stoi za oboma wdrożonymi incydentami: umowa Cardif niosła §4 innego banku od 2026-06-10 do 2026-07-28, a umowy e-Zdrowie wyszły „bez §10/PFRON" zgodnie z komentarzem w samym rejestrze — oba wykrył człowiek czytający umowę, nigdy system.

**Naprawa.** Niech krok nakładania asertuje, a nie wzrusza ramionami: `apply_ops_docx` i `apply_ops_html` mają zwracać `(applied, expected)`, `render_from_context` i gałąź html w /render mają je porównywać i głośno failować (500 z jasnym komunikatem plus `logger.error`, żeby trafiło do Sentry), gdy `applied != len(ops)` — umowa bez wynegocjowanej klauzuli jest wprost gorsza niż nieudane pobranie. Loguj wygrywający klucz override przy każdej generacji, niezależnie od wyniku — to zarazem dostarcza zapisu audytowego, którego potrzebuje znalezisko 1. Daj `apply_ops_html` tę samą semantykę indeksu docelowego co ramieniu DOCX, żeby podgląd i dostarczony dokument nie mogły się rozjechać. Dodaj test renderujący każdego klienta z rejestru na obu realnych szablonach i asertujący pełne zastosowanie, żeby edycje szablonu psuły CI zamiast umów.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 85` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f87"></a>

### #87 · P2 · Zwycięzca miesięcznej nagrody 1500 PLN jest wybierany przez nieoznaczony tie-break po porządku bajtowym nazwy, a potem zamrażany niezmiennie — remisujący „Łukasz" zawsze przegrywa

nakład **S** · obszar **Backend · serwisy** · **nie działa** · kategoria `broken`

`backend/app/services/competitions.py:508`

**Co to kosztuje.** `MONTHLY_RACE_PRIZE_PLN = 1500` i `MONTHLY_RACE_RANKING_SIZE = 10` (competitions.py:45, :65). Zwycięzca, którego wskazuje system, to dosłownie pierwszy wiersz tego porządkowania — `qualified_leader = next(entry for entry in ranking if not entry["excluded"] and entry.get("qualified", True))` w competitions.py:680-684. `recommendations` to liczba ruchów `cv_sent` w jednym miesiącu w zespole około dziesięciu rekruterów, więc remisy na całkowitych liczbach na szczycie są rutyną, nie egzotyką. Tie-break jest porównaniem bajtowym, czyli nie jest neutralnym rzutem monetą — systematycznie i trwale stawia nazwy z polskimi diakrytykami na końcu. To samo wyrażenie napędza dwa kolejne zapytania nagrodowe/rankingowe z twardym cięciem: competitions.py:187 (`ORDER BY count(*) DESC, u.name ASC {limit_sql}`) i competitions.py:633 (`ORDER BY count(*) DESC, u.name ASC LIMIT :limit`). Rekruter o imieniu Łukasz albo nazwisku Świderski jest strukturalnie poszkodowany w konkursie o pieniądze i nigdzie nie ma komentarza, który by to przyznawał.

**Naprawa.** Rozstrzygaj remisy po czymś, co nie jest ciągiem zależnym od locale — `u.id ASC` jest już wszędzie indziej w repo wybranym stabilnym tie-breakiem (candidates.py:1093, clients.py:269) i całkowicie usuwa to skrzywienie. Jeśli naprawdę chcesz sensownego dla człowieka tie-breaku alfabetycznego, użyj `ORDER BY t.name COLLATE "pl-PL-x-icu" ASC` we wszystkich trzech zapytaniach; nie naprawiaj jednego, zostawiając pozostałe.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 87` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f90"></a>

### #90 · P2 · Klucz sortowania "name" jest zaimplementowany w dwóch przeciwnych porządkach: `/api/candidates` sortuje po imieniu pod etykietą „Nazwisko (A-Z)", a `/api/search` sortuje po nazwisku

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/v2/pages/CandidatesListV2.tsx:406`

**Co to kosztuje.** `Candidate.name` to imię, a `Candidate.lastname` nazwisko (models/candidate.py:86-87, a `__repr__` w linii 428 drukuje je w tej kolejności). Kontrolka obiecuje porządek po nazwisku, a dostarcza porządek po imieniu, więc rekruter układający alfabetycznie 49 tys. kandydatów, żeby znaleźć albo przerobić literę K, dostaje Adama Zebrowskiego przed Zbigniewem Abackim. W ATS to nazwisko jest identyfikatorem, po którym ludzie nawigują — to jedyna kontrolka alfabetyczna na ekranie i odpowiada na inne pytanie niż to, którym jest podpisana. Własny opis OpenAPI backendu w candidates.py:1486 dokumentuje realne zachowanie ("'name' = name ASC, lastname ASC"), więc te dwie połówki po prostu nigdy nie zostały uzgodnione; żaden test nie porównuje etykiety z porządkiem.

**Naprawa.** Zdecyduj, który kontrakt jest właściwy, i doprowadź obie strony do zgody. Biorąc pod uwagę etykietę i konwencję ATS, backend powinien sortować najpierw po `Candidate.lastname`, potem `Candidate.name`, potem `Candidate.id` — jednolinijkowa zamiana w candidates.py:1092-1093 plus opis OpenAPI w :1486. Zrób to w tej samej zmianie co finding #1, żeby wrapper collate wylądował na kolumnie, która faktycznie prowadzi.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 90` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f92"></a>

### #92 · P2 · Dwa endpointy Claude'a w MINDY są żywe i stoją całkowicie poza systemem kwot AI — nie mają `AIFeatureKey`, więc główny przełącznik, miesięczny sufit i `ai_usage_log` ich nie widzą; ścieżka przeglądarkowa jest martwa, więc zasięg to wyłącznie bezpośrednie API

nakład **M** · obszar **Backend · API** · **ryzyko** · kategoria `risk`

`backend/app/api/dynareporter_mindy.py:235`

**Co to kosztuje.** Zaseedowanie `monthly_limit` dla wszystkich 11 wartości `AIFeatureKey` — naprawa, na którą wskazuje cały ten obszar — i tak zostawiłoby tę powierzchnię bez limitu, bo nie ma ona klucza do ograniczenia. To swobodny czat: `MindyChatRequest` dopuszcza do 20 wiadomości (`max_length=20`), których `content: str` nie ma żadnego `max_length`, więc uwierzytelniony użytkownik kontroluje cały prompt wysyłany do Sonnet 5 na koncie firmy. W pliku nie ma nigdzie `@limiter.limit` (grep za `limiter` nie zwraca nic), a bliźniaczy `GET /commentary` jest odpalany automatycznie przy montowaniu strony przez bezwarunkowy `useQuery` (frontend/src/app/dynareporter/mindy/page.tsx:58-65), więc samo otwarcie `/dynareporter/mindy` spala wywołanie Claude'a. Nic z tego nie pojawia się w `ai_usage_log`, więc raport zużycia w Ustawienia → AI — gdy już finding #1 zostanie naprawiony i raport znowu się wyrenderuje — nadal będzie zaniżał realne wydatki.

**Naprawa.** Albo owiń oba handlery w `async with ai_feature(db, AIFeatureKey.<nowy klucz>, user_id=current_user.id)` — co wymaga nowego elementu enuma, migracji `ALTER TYPE aifeaturekey ADD VALUE`, odpowiadających linii seed w entrypoint.sh `_ENUM_STATEMENTS` + `_DATA_STATEMENTS` oraz wpisu w `FEATURE_LABELS`/`FEATURE_DATA_SENT` — albo, skoro DynaReporter jest wygaszany, ustaw `DYNAREPORTER_MODE=off` i usuń moduł. Cokolwiek wybierzesz, dodaj `max_length` na treść pojedynczej wiadomości i limit slowapi; uwaga, że dynareporter_mindy.py niesie obecnie `from __future__ import annotations`, co zgodnie z CLAUDE.md musi zostać usunięte, zanim do modułu doda się jakikolwiek `@limiter.limit`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 92` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f94"></a>

### #94 · P2 · `POST /api/notes/{id}/link-job` obciąża `champion_draft` dwa razy na kliknięcie i jest jedynym miejscem wywołania kwoty w `app/api`, z którego `AIQuotaExceeded` ucieka jako 500 — naprawa na poziomie trasy (#1069) nigdy nie została usunięta po tym, jak zastąpiła ją bramka na poziomie serwisu (#1088)

nakład **S** · obszar **Backend · API** · **nie działa** · kategoria `broken`

`backend/app/api/notes.py:364`

**Co to kosztuje.** Dwie konsekwencje na trasie, której Delivery Leadzi używają z panelu „Sugerowane meetingi". Po pierwsze, licznik `champion_draft` jest dla tej ścieżki zawyżony 2×, więc w momencie, w którym admin faktycznie ustawi miesięczny sufit (o co w tym całym obszarze chodzi), ta trasa zjada go w podwójnym tempie, a liczba dla `champion_draft` w Ustawienia → AI zawyża realne wywołania Claude'a. Po drugie i ostrzej: to jedyne miejsce wywołania kwoty w `app/api` bez `try/except` wokół, a nie ma handlera `AIQuotaExceeded` na poziomie aplikacji (app/main.py rejestruje dokładnie jeden handler wyjątków, dla `RateLimitExceeded`, w linii 653). Więc gdy główny kill-switch AI jest wyłączony albo limit został osiągnięty, request zwraca 500 zamiast 503, które zwraca każdy bliźniaczy handler — a ponieważ obciążenie leci przed `note.job_id = body.job_id`, powiązanie notatki ze spotkania z rekrutacją pada całkowicie. Wyłączenie AI psuje operację na danych, która AI nie potrzebuje.

**Naprawa.** Usuń tutaj wywołanie `check_and_increment` i jego komentarz; `enrich_from_meeting` już obciąża i deklaruje dla każdego punktu wejścia. Jeśli chcesz odrzucenia przed zapisem `note.job_id`, użyj sprawdzenia tylko do odczytu (`get_master_enabled` + `get_feature_config` + `get_total_usage_for_period`) i mapuj `AIQuotaExceeded` na 503 z tym samym ustrukturyzowanym słownikiem `detail`, którego używają bliźniacze handlery, żeby istniejąca gałąź błędu kwoty we froncie zadziałała.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 94` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f95"></a>

### #95 · P2 · `candidate_activity_summary_service` nadal ręcznie klepie bramkę kwot AI poza `ai_feature()`, więc karta „Podsumowanie aktywności" loguje się dziś jako UNGATED, a w momencie przełączenia `AI_QUOTA_STRICT` zamieni się w 502, które i tak spali kwotę — a test-strażnik asertujący, że „równoległa implementacja zniknęła", parsuje wyłącznie match_justification_service.py

nakład **M** · obszar **Backend · serwisy** · **dług** · kategoria `test-gap`

`backend/app/services/candidate_activity_summary_service.py:1132`

**Co to kosztuje.** Repo traktuje „istnieje dokładnie jedna bramka" jako ustalony, otestowany niezmiennik — własny docstring testu nazywa dwie niezgodne kopie „najgorszym rodzajem buga, bo obie kopie wyglądały poprawnie". Niezmiennik jest fałszywy, a test tego nie widzi. Konkretnie: ta kopia reimplementuje główny przełącznik + `enabled` + limit + upsert `ON CONFLICT` (co do tej samej nazwy ograniczenia), ale nigdy nie ustawia kontekstu wywołania AI, więc karta „Podsumowanie aktywności kandydata" jest jedną z ośmiu ścieżek z findingu #3: dziś loguje się jako UNGATED przy każdej generacji, a pod `AI_QUOTA_STRICT` rzuciłaby wyjątkiem, zabijając funkcję, która w rzeczywistości jest poprawnie obciążana. Do tego robi dwa dodatkowe round tripy na wywołanie (`_ensure_feature_enabled` pobiera konfigurację, a potem `_gate_and_count` pobiera ją znowu) wewnątrz requestu. Każda przyszła zmiana semantyki kwot — granica okresu w czasie warszawskim, sufit per użytkownik, pasmo miękkiego ostrzeżenia — musi zostać zrobiona w dwóch miejscach, inaczej `candidate_summary` po cichu zostanie przy starej regule.

**Naprawa.** Zastąp `_gate_and_count` przez `async with ai_feature(db, AIFeatureKey.candidate_summary, user_id=user_id)` owinięte wokół wywołania `_call_claude_text` w linii 1107 (wołający i tak commituje w linii 1536, więc obciążenie przed wydatkiem zostaje zachowane) i wyrzuć zdublowane pobranie konfiguracji z `_ensure_feature_enabled`. Potem poszerz test-strażnik tak, żeby przechodził każdy plik pod app/ w poszukiwaniu funkcji o nazwie `_gate_and_count` albo `pg_insert(AIUsageLog)` poza app/services/ai_quota.py, zamiast wskazywać jedną ścieżkę.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 95` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f98"></a>

### #98 · P2 · Wtyczka deklaruje `scripting` i `activeTab`, których żadna linia nie wywołuje, oraz wildcard `https://*.dynaminds.pl/*` obejmujący trzy panele Coolify i dwie obce apki produkcyjne — mimo że kod może dosięgnąć wyłącznie `nexus.dynaminds.pl`

nakład **S** · obszar **Wtyczka** · **ryzyko** · kategoria `security`

`extension/manifest.json:27`

**Co to kosztuje.** Wtyczka, której nikt nie lintuje, nie testuje i nie przeglądał od 15 miesięcy w kategoriach cyklu życia backendu, dostaje prawo wstrzykiwania skryptu i czytania odpowiedzi z panelu, z którego steruje się deploymentem NEXUSA — oraz z dwóch niepowiązanych aplikacji produkcyjnych trzymających dane HR (Compass) i dane leadów (Atlas). To nie jest teoretyczne: `chrome.scripting` + host permission = wykonanie kodu w zalogowanej sesji operatora Coolify. Trzy z czterech wpisów są nadmiarowe, a dwa uprawnienia z `permissions` są kompletnie martwe. W praktyce oznacza to też, że wtyczki NIE DA SIĘ wysłać do Chrome Web Store bez uzasadnienia każdego host_permission (README:130 sam to wymienia jako TODO) — a uzasadnienia dla `*.dynaminds.pl` nie ma, bo kod z tego nie korzysta.

**Naprawa.** Usuń `activeTab` i `scripting` z `permissions` (nic ich nie wywołuje). Zamień `https://*.dynaminds.pl/*` na jedyny host, który kod faktycznie odpytuje, `https://nexus.dynaminds.pl/*`, zachowując `https://api.nexus.dynaminds.pl/*`. Wyrzuć `http://localhost/*` z wysyłanego manifestu i trzymaj `manifest.dev.json` do pracy lokalnej, albo zawęź do `http://localhost:8000/*` i pogódź się z tym, że Chrome i tak zignoruje port. Wszystkie cztery zmiany są mechaniczne i żadna nie dotyka kodu, bo żadne z usuwanych uprawnień nie jest nigdzie referencowane.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 98` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f99"></a>

### #99 · P2 · Na Sales Navigatorze i Recruiterze scraper bierze PIERWSZĄ kotwicę `/in/` w całym dokumencie — brak zawężenia do karty profilu, brak weryfikacji slug↔nazwisko, więc klucz dedupu i cel enrichmentu Proxycurl mogą należeć do innej osoby niż pokazuje podgląd

nakład **M** · obszar **Wtyczka** · **nie działa** · kategoria `broken`

`extension/src/content/linkedin-scraper.js:74`

**Co to kosztuje.** Rekruter patrzy na profil Anny Nowak w Sales Navigatorze, modal pokazuje „Anna Nowak" (bo `name` idzie z `data-anonymize="person-name"`, czyli z zupełnie innego źródła niż URL), klika „Dodaj do NEXUS" — a do bazy leci `linkedin_url` kogoś innego. Dwa skutki, oba ciche. Na ścieżce dedupu system trafia w cudzy rekord i dopisuje go do rekrutacji, a modal wyświetla „Już w bazie: <inne nazwisko>" — jedyny moment, w którym pomyłka jest widoczna, i to tylko jeśli rekruter przeczyta banner. Na ścieżce tworzenia rekord powstaje z PRAWIDŁOWYM nazwiskiem z preview, po czym Proxycurl — który schemat opisuje wprost jako „the authoritative source [that] will overwrite these within minutes" — nadpisuje firmę, stanowisko, lokalizację i historię zatrudnienia danymi obcej osoby. Tego już nikt nie wychwyci wzrokiem, a rekord jest daną osobową w rozumieniu RODO.

**Naprawa.** Zawęź zapytanie do kontenera profilu, zanim zejdziesz do fallbacku na cały dokument: na /sales/ preferuj kotwicę wewnątrz topcarda/lockupa, który już niesie stabilne zaczepy tej powierzchni (przodkowie z `[data-anonymize]`, `.profile-topcard*`), na /talent/ wewnątrz `.profile-info` / `.profile-header`, i dopiero potem poszerzaj. Następnie dodaj tani guard spójności, niezależny od DOM LinkedIna: jeśli zescrapowane nazwisko nie jest puste, a żaden z jego znormalizowanych tokenów nie występuje w rozwiązanym slugu, nie wysyłaj po cichu — pokaż rozwiązany URL w podglądzie modala i każ rekruterowi go potwierdzić. Kontrola krzyżowa na tej samej stronie, bez dodatkowego requestu, a niewidzialny zapis na złą osobę staje się widzialny.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 99` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f101"></a>

### #101 · P2 · Cutover RBAC dashboardów z #1031 po cichu odciął konsolę Priority Work: 23 z 24 endpointów są dziś nieosiągalne z jakiejkolwiek trasy, a tworzenie assignmentu — jedyna operacja, która nadaje sens przejściu off→shadow — nigdy nie miało UI w ogóle

nakład **L** · obszar **Backend · API** · **dług** · kategoria `dead-code`

`backend/app/api/priority_work.py:768`

**Co to kosztuje.** 1743 linie routera + 1131 linii serwisu + 817 linii polityki + 9 tabel produkcyjnych + pętla w lifespanie są utrzymywane dla funkcji, której nikt nie może otworzyć. Konkretnie: nie ma ekranu do opublikowania planu priorytetów, zgłoszenia lub odpowiedzi na zapotrzebowanie, podniesienia lub rozstrzygnięcia blokera, przyznania wyjątku KPI ani przekazania procesu innemu właścicielowi. Więc bezpieczny rollout, który zaleca config.py:490-493 („Safe rollout is always off -> shadow -> enforce"), jest nie tylko nieużywany — jest niewykonalny, bo przestawienie `RECRUITMENT_PRIORITY_MODE` na `enforce` bez opublikowanego planu zablokowałoby każdemu rekruterowi otwarcie jakiejkolwiek nowej pary kandydat/rekrutacja, bez UI do odblokowania. Tymczasem koszt jest płacony codziennie na gorących ścieżkach: `ensure_job_membership` i `job_scope_clause` rozgałęziają się po tabelach priorytetowych na każdym wejściu do pipeline'u, /api/jobs odpala dwa dodatkowe podzapytania priorytetowe na każde żądanie listy, a 7 żywych ścieżek wejściowych wciąż zapisuje wiersze `recruitment_processes`.

**Naprawa.** Zdecyduj, potem działaj — nie bramkuj. Jeśli model jest nadal chciany: zamontuj ponownie `TeamAllocationBoard` na presecie HoR w `RoleDashboard`, `MyPriorityQueue` na presecie my-work, a `PriorityRequestsPanel` na presecie delivery-lead (DeliveryTabs.tsx już to spina) i najpierw napraw opisany niżej błąd przejścia statusu. Dodaj klientów frontendowych dla 7 endpointów, które ich nie mają. Jeśli jest porzucony: usuń router+serwis+politykę+task+komponenty w jednym PR, a DROP tabel zaplanuj osobno — `recruitment_priority_*` niesie FK do `jobs` i `users`, a `recruitment_processes` jest czytane przez `ensure_job_membership`, więc DROP wymaga takiej samej analizy, jaką dostał drop dynareportera. Tak czy inaczej, w tej samej zmianie skasuj ~3500 linii niezamontowanych komponentów, żeby następny audytor nie musiał wyprowadzać tego od nowa.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 101` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f102"></a>

### #102 · P2 · Karta Priority Work na każdej stronie rekrutacji mówi rolom operacyjnym, że nie wolno im dodawać nowych kandydatów — ograniczenie, które przy mode=off nie istnieje, wydrukowane w tej samej karcie, która mówi, że funkcja jest wyłączona

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/v2/priority-work/JobPriorityContext.tsx:155`

**Co to kosztuje.** Na najbardziej obłożonym ekranie w ATS-ie admin / head_of_recruitment / delivery_lead / tac / recruiter / sourcer widzą zdanie stwierdzające, że dodawanie nowych kandydatów do tej rekrutacji jest zabronione. To nieprawda: `decide_priority_work_access` zwraca `allowed=True, reason=PriorityWorkReason.mode_off` w priority_work_policy.py:671-679, a `ensure_job_membership` pomija całą gałąź priorytetową w recruitment_access.py:225. Karta zaprzecza sama sobie w jednym widoku, bo `ModeNotice` dwie linie wyżej (renderowany w linii 100) drukuje „Priority Work jest wyłączony — Plan jest widoczny informacyjnie. Obowiązują dotychczasowe zasady pracy." Rekruter, który uwierzy w drugie zdanie, przestaje sourcować na tej rekrutacji i eskaluje; rekruter, który uwierzy w pierwsze, uczy się ignorować komunikaty o polityce w aplikacji, co jest gorsze w dniu, w którym tryb naprawdę przejdzie na enforce.

**Naprawa.** Zwracaj null z `JobPriorityContext`, gdy `mode === "off"` — przy mode=off karta nie ma nic prawdziwego do powiedzenia. Jeśli karta musi zostać dla licznika carry-over, uzależnij opis od trybu: stwierdzaj ograniczenie tylko przy trybie "enforce", pisz „wykrywane, nie blokowane" dla "shadow", a dla "off" usuń to zdanie w całości.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 102` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f104"></a>

### #104 · P2 · Karta Priority Work zamienia 403 z kontroli członkostwa w czerwony blok `role="alert"` „nie udało się wczytać" z przyciskiem Ponów, który nie ma prawa się udać — dotyka recruitera, sourcera, TAC i delivery_leada (nie tylko dwóch pierwszych) na każdej stronie rekrutacji, do której nie należą, a prod raportuje obecnie priority_work: disabled, co zabija jedyną furtkę, która mogła to 403 ominąć

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/v2/priority-work/JobPriorityContext.tsx:58`

**Co to kosztuje.** Strona szczegółów rekrutacji jest otwarta dla każdej roli operacyjnej — GET /api/jobs/{job_id} (jobs.py:1138-1149) nakłada wyłącznie scope delivery-leada, a middleware.ts nie ma wpisu /jobs — więc rekruter albo sourcer przeglądający listę Rekrutacje może otworzyć dowolną opublikowaną rekrutację. Ale endpoint danych karty priorytetowej egzekwuje scope zasobu: `get_job_priority_context` woła `await ensure_job_membership(db, current_user, job_id)` (priority_work.py:1130), które przepuszcza wyłącznie admina i head_of_recruitment (`_JOB_MEMBERSHIP_BYPASS_ROLES`, recruitment_access.py:192-195), a poza tym wymaga `recruiter_id` / `delivery_lead_id` / `tac_id` albo aktywnego współpracownika (job_membership.py:38-52). 403 ląduje w tej gałęzi, a `WidgetErrorBlock` renderuje `role="alert"` z destrukcyjną ikoną i przyciskiem „Spróbuj ponownie" (WidgetState.tsx:60-78). Ponowienie wysyła to samo 403 — react-query jest skonfigurowane na `retry: 1`, więc każde otwarcie strony kosztuje już dwa 403. Efektem jest stały czerwony alert na dole większości stron rekrutacji, dla funkcji, która jest wyłączona i której użytkownik słusznie nie ma prawa widzieć. Uczy to też zespół ignorowania czerwonych alertów na stronie rekrutacji, czyli tej samej klasy szkody, którą repo już gdzie indziej odnotowało (403, które czyta się jak utrata danych).

**Naprawa.** Odróżnij 403 od realnej awarii w tej gałęzi: przy `error.response?.status === 403` nie renderuj nic (karta nie niesie żadnej informacji, do której użytkownik ma prawo). Zostaw `WidgetErrorBlock` dla 5xx i błędów sieci. Jeśli najpierw wejdzie fix ze znaleziska 2 — zwracanie null zawsze, gdy tryb to "off" — to przestanie strzelać przy okazji, ale gałąź traktującą 403 jak błąd i tak trzeba poprawić na dzień, w którym flaga zostanie przestawiona.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 104` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f205"></a>

### #205 · P2 · Trzynaście z czternastu checków `/api/health` nie ma żadnego automatycznego czytelnika — godzinowa sonda asertuje tylko `status != "unhealthy"`, a status z konstrukcji zależy wyłącznie od bazy

nakład **M** · obszar **CI/CD** · **ryzyko** · kategoria `ops` · **rekonesans — nieweryfikowane adwersarialnie**

`.github/workflows/uptime-probe.yml:46`

**Co to kosztuje.** `/api/health` wylicza czternaście checków (`database`, `m365`, `m365_encryption`, `autenti`, `traffit`, `cortex`, `qdrant`, `priority_work`, `anthropic`, `voyage`, `reranker`, `ai_features`, `disk`) z niemałą starannością — każdy niesie komentarz opisujący przeszły incydent, do łapania którego istnieje. Tylko `database` może ruszyć `overall`; każdy inny check jest udokumentowany jako „informacyjny, nigdy nie przestawia overall". Jedyny automatyczny konsument endpointu asertuje `.status != "unhealthy"`, więc może wykryć wyłącznie martwą bazę — czyli tę jedną awarię, która i tak kładzie całą aplikację i nie potrzebuje sondy. W praktyce znaczy to, że `traffit: degraded` (import z Traffita stanął albo się sypie), `ai_features: uncapped: <11 funkcji>` (nigdzie żadnego sufitu wydatków) oraz degradacja `qdrant`/`cortex` są dla automatyki niewidoczne. `disk-alert.yml` jest jedynym kontrprzykładem i świadomie czyta pole `diskPercent` z najwyższego poziomu, a nie `checks` — dowód, że wzorzec działa i po prostu nigdy go nie rozszerzono. Endpoint health wykonuje realną pracę diagnostyczną do kanału bez słuchacza; dlatego ostrzeżenie o nielimitowanym AI i zdegradowany sync Traffita utrzymują się bez wywołania kogokolwiek.

**Naprawa.** Dodaj do joba `probe` w uptime-probe drugi krok, który pada (albo otwiera/odświeża issue, tak jak już robi `disk-alert.yml`), gdy którykolwiek wpis w `.checks` jest „unhealthy", i ostrzega przy „degraded" oraz wartościach zaczynających się od „uncapped". Trzymaj go poza bramką `.status`, żeby nie mógł zwrócić 503 na kontenerze ani wywalić deployu — workflow disk-alert to działający wzorzec dokładnie na to (przeczytaj pole, otwórz lub skomentuj issue, wyjdź z 1, żeby GitHub wysłał maila właścicielowi). Stany oczekiwane, takie jak `priority_work='disabled'` i `autenti='unconfigured'`, potrzebują jawnej allowlisty, żeby nowy check nie zaczynał życia już na czerwono.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 205` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f206"></a>

### #206 · P2 · `GET /api/public/champion-card/{token}` to jedyny publiczny endpoint w tym pliku bez rate limitu — bez uwierzytelnienia, cztery round tripy do bazy, zwraca PII kandydata

nakład **S** · obszar **Backend · API** · **ryzyko** · kategoria `security` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/api/public_share.py:71`

**Co to kosztuje.** Zweryfikowane empirycznie na prodzie: 40 sekwencyjnych nieuwierzytelnionych requestów do `/api/public/champion-card/<zmienny token>` zwróciło 40× HTTP 404 i zero 429. Pozostałych pięć publicznych handlerów w `public_share.py` ma limity (cv 30/min, cv-i 30/min, cv-i chat 5/min;60/godz., apply GET 30/min, apply POST 5/min;30/godz.), a `rate_limit.py` ustawia `default_limits=[]`, więc nic tej luki nie przykrywa. Każdy request wykonuje cztery sekwencyjne `await` (lookup tokenu, `CandidateStage`, `Candidate`, `Job`) na produkcyjnej puli Postgresa przed zwróceniem odpowiedzi, a przy poprawnym tokenie ciało odpowiedzi niesie imię, nazwisko, `competence_category`, lokalizację i `years_it_experience` kandydata plus tytuł oferty oraz pełny `champion_profile` i `screening_answers` — czyli PII na rekordzie istotnym z punktu widzenia RODO. Sam token udostępnienia to `secrets.token_urlsafe(36)` (pipeline.py:1325), więc zgadywanie nie jest ryzykiem; ryzyko polega na tym, że jedyny endpoint, o którym wszyscy zapomnieli, jest zarazem najtańszym nieuwierzytelnionym sposobem na konsumowanie połączeń do bazy, oraz że wyciekniętym-i-potem-odwołanym linkiem można odpytywać bez ograniczeń.

**Naprawa.** Dodaj `@limiter.limit("30/minute")` pod dekoratorem trasy oraz parametr `request: Request` (slowapi tego wymaga), dokładnie jak w `get_public_cv`. Zwróć uwagę na ograniczenie udokumentowane dla tej bazy kodu na poziomie pliku: moduły używające `@limiter.limit` nie mogą dostać `from __future__ import annotations` — `public_share.py` obecnie tego nie ma, więc nic więcej nie wymaga zmiany. Warto dodać test asertujący, że każda trasa w `public_share.py` ma limiter, skoro ten endpoint wypadł z konwencji, którą trzyma pięć sąsiadów.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 206` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f209"></a>

### #209 · P2 · Zero lockfile'a po stronie Pythona: każda zależność przechodnia backendu pływa, do tego jeden bezpośredni pływający zakres, a Coolify przebudowuje obraz ze źródeł przy KAŻDYM deployu ORAZ przy każdym rollbacku

nakład **M** · obszar **Backend** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/requirements.txt:30`

**Co to kosztuje.** Dwa buildy tego samego SHA z gita mogą zainstalować różny kod. To psuje trzy rzeczy, na których to repo aktywnie polega. Po pierwsze rollback: udokumentowana procedura (CLAUDE.md, runbook §2) to Coolify → Deployments → poprzedni → Redeploy, co ponownie klonuje repo i ponownie odpala `pip install -r requirements.txt` — więc cofnięcie kodu aplikacji NIE cofa jej zależności, a rollback wywołany regresją w zależności wiernie tę regresję zainstaluje ponownie. Po drugie gwarancja CI: shardy pytest instalują to samo niezapinowane domknięcie w innym momencie niż build produkcyjny, więc zielone CI jest dowodem na jedno rozwiązanie zależności, a prod uruchamia inne. Po trzecie skan Trivy w ci.yml czyta requirements.txt, czyli 39 bezpośrednich pinów, i jest strukturalnie ślepy na wersje przechodnie, które faktycznie jadą na prod. Zakres `anthropic` to najostrzejszy pojedynczy przypadek: leży na ścieżce krytycznej generowania CV, uzasadnień dopasowania i chatu w interaktywnym CV, a bump wersji minor ląduje na prodzie bez review, w dowolnym momencie następnego deployu. Zespół już raz udokumentował dokładnie ten scenariusz awarii poziom wyżej — komentarz przy qdrant-client opisuje bump, który „przeszło CI i healthcheck", podczas gdy wyszukiwanie semantyczne po cichu zwracało puste wyniki przy status: healthy.

**Naprawa.** Wdrożyć pip-tools: requirements.in jako plik edytowany ręcznie, requirements.txt generowany przez `pip-compile --generate-hashes`, a w backend/Dockerfile zmiana na `pip install --require-hashes -r requirements.txt`. To czyni obraz odtwarzalnym co do bajta, sprawia, że rollback faktycznie cofa, i pozwala Dependabotowi dalej działać na requirements.in. Tańszy krok przejściowy, jeśli to za duża zmiana: przypiąć anthropic do dokładnej wersji, żeby ostatnia pływająca bezpośrednia zależność przestała ruszać się sama z siebie.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 209` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f210"></a>

### #210 · P2 · Produkcyjny obraz frontendu buduje się przez `npm install`, nie `npm ci` — lockfile, który CI egzekwuje, jest tylko poglądowy w obrazie, który naprawdę jedzie na prod

nakład **S** · obszar **Frontend · UI** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`frontend/Dockerfile:6`

**Co to kosztuje.** `npm ci` przerywa działanie, gdy package.json i package-lock.json się nie zgadzają; `npm install` po cichu godzi różnicę, rozwiązując zależności od nowa z registry i przepisując lock wewnątrz kontenera builda. Dwie ścieżki mają więc przeciwne tryby awarii na tym samym wejściu: package.json zedytowany bez regeneracji locka daje czerwone CI i zielony build produkcyjny — z drzewem zależności, którego żaden test nigdy nie przeszedł. W repo, które robi squash-merge z 552 gałęzi, rozjazd locka to rutynowy artefakt mergowania, nie hipoteza. Glob `package-lock.json*` w linii 5 to pogłębia: jeśli lockfile kiedykolwiek zniknie albo zmieni nazwę, COPY i tak się powiedzie, a `npm install` rozwiąże całe drzewo od zera — tam gdzie `npm ci` padłby głośno. Dalej: skan Trivy w ci.yml audytuje zacommitowany package-lock.json — plik, który build produkcyjny może swobodnie zignorować — więc raport podatności opisuje drzewo, które może nie być tym, które serwuje dane kandydatów.

**Naprawa.** Zmienić linię 6 na `npm ci --legacy-peer-deps` i usunąć `*` z `package-lock.json*` w linii 5, żeby brak lockfile'a wywalał build zamiast po cichu poszerzać zakresy. Dzięki temu obraz produkcyjny jest identyczny z tym, co przetestowało CI i co przeskanowało Trivy. frontend/.npmrc ma już `legacy-peer-deps=true`, więc flaga też może zniknąć, gdy potwierdzi się, że działa w kontenerze.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 210` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f211"></a>

### #211 · P2 · gitleaks — bramka sekretów blokująca deploy — jest ślepy na ścieżki dwóch plików workflow, które obsługują realne poświadczenia, w tym prywatny klucz age do backupów

nakład **S** · obszar **Infra** · **ryzyko** · kategoria `security` · **rekonesans — nieweryfikowane adwersarialnie**

`.gitleaks.toml:16`

**Co to kosztuje.** gitleaks jest required status checkiem i siedzi w ci-gate.yml właśnie dlatego, że „sekret w obrazie jest nieodwracalny, musi blokować deploy". Dwa pliki są z niego wyjęte po ścieżce i nie są to przypadkowe pliki: backup-drill.yml to jedyne miejsce w repozytorium, które dotyka prywatnej połowy klucza age chroniącego wszystkie backupy kandydatów, plus klucze dostępowy i sekretny Backblaze B2. ci.yml to drugi mocno ruchliwy workflow. Allowlistowanie po ścieżce oznacza, że gitleaks w ogóle tych plików nie skanuje — nie konkretnej linii, tylko całego pliku, na zawsze. Autor konfiguracji zdaje sobie sprawę z zagrożenia i sam to zapisał: to właśnie allowlistowanie ścieżek pozwoliło przeleżeć niewykrytemu działającemu hasłu administratora. Allowlisty po WARTOŚCI potrzebne dla dwóch testowych haseł CI są obecne niezależnie, więc usunięcie wpisów ścieżkowych nic nie kosztuje.

**Naprawa.** Usunąć linie 16 i 17 z globalnej listy paths i potwierdzić, że skan dalej przechodzi — oba DSN-y CI są już pokryte regexami po wartości w liniach 41-42 oraz allowlistą per-reguła pod hardcoded-db-password. Przy okazji zrobić ten sam audyt dla pozostałych szerokich wpisów ścieżkowych: frontend/package-lock.json (linia 12) i prefiks .claude/ (linia 23). Zweryfikować przez `gitleaks detect --no-git --config .gitleaks.toml --redact --verbose --exit-code 1`, czyli dokładnie tę komendę, którą odpala ci-gate.yml.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 211` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f214"></a>

### #214 · P2 · src/lib/api.ts — jedyny, 6153-liniowy klient HTTP całego frontendu — ma 0,45% pokrycia funkcji, bo 51 ze 148 plików testowych podmienia go na mocka

nakład **L** · obszar **Frontend · lib** · **dług** · kategoria `test-gap` · **rekonesans — nieweryfikowane adwersarialnie**

`frontend/src/lib/api.ts:20`

**Co to kosztuje.** Ten plik jest właścicielem interceptora nagłówka auth, obsługi 401, globalnego timeoutu 30 s oraz per-requestowego override'u 120 s dla calli LLM/scoringu/generowania dokumentów, a także obsługi multipart przy wgrywaniu CV. To są dokładnie te mechanizmy, które produkują dwie najgorzej wyglądające awarie widziane przez użytkownika w tym produkcie — upload odpowiadający 422 „file required" i call scoringu albo generowania CV, który umiera na 30 s i wychodzi jako generyczny błąd — i żaden test w repozytorium nie wykonuje żadnego z nich. 51 mockujących plików asertuje, że komponent woła stub; nie są w stanie zaobserwować requestu, który faktycznie się buduje. Przy martwym suicie E2E (finding #2) nie ma drugiej siatki.

**Naprawa.** Dodać cienką warstwę integracyjną, która ćwiczy prawdziwą instancję `api` wobec przechwyconego adaptera (MSW albo `axios-mock-adapter`), zamiast podmieniać moduł: asertować kształt wychodzącego requestu — nagłówek Authorization, efektywny timeout, Content-Type dla ścieżek z FormData — dla tej garstki endpointów, na których to już się kiedyś wywaliło na produkcji. Nie wymaga to odmockowania 51 istniejących testów komponentów; wymaga tego, żeby cokolwiek, gdziekolwiek, wykonywało ten klient.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 214` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f215"></a>

### #215 · P2 · 239 backendowych funkcji testowych jest wyłączonych z CI, 188 z nich w 17 plikach, o których wiadomo, że są czerwone — w tym 63 pokrywające parsowanie i wzbogacanie CV, czyli ścieżkę wejściową całej bazy kandydatów

nakład **L** · obszar **CI/CD** · **dług** · kategoria `test-gap` · **rekonesans — nieweryfikowane adwersarialnie**

`.github/workflows/ci.yml:139`

**Co to kosztuje.** Niechroniona powierzchnia nie jest peryferyjna: test_cv_parser.py (33 testy) i test_cv_enrichment.py (30) pokrywają zamianę wgranego CV w rekord kandydata, czyli sposób, w jaki powstał praktycznie każdy wiersz w tej bazie; test_marketplace_service.py (20) + test_marketplace_flow.py (7) pokrywają powiadomienia o dopasowaniach; test_proposals.py (7) + test_shortlist_and_proposal.py (7) pokrywają proponowanie kandydatów klientowi, czyli zdarzenie przychodowe. Regresja w którymkolwiek z nich jedzie na prod na zielono.

**Naprawa.** Przerabiać listę FAILING od najstarszych, jeden plik na diff, i przy każdym potwierdzić zapisaną diagnozę PRZED tknięciem testu — precedens z 0226 mówi, że co najmniej jeden „stale fixture" był w rzeczywistości poprawnym testem. Priorytetyzować po zasięgu rażenia, nie po koszcie naprawy: najpierw test_cv_parser.py i test_cv_enrichment.py (63 testy na ścieżce wejściowej danych), potem proposals/shortlist (14 testów na przepływie pieniędzy do klienta). Aktualizować nagłówkową liczbę spalanego długu w docstringu kontraktu, gdy się zmienia — obecnie mówi „439 test modules on disk", podczas gdy jest ich 488.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 215` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f216"></a>

### #216 · P2 · Job Trivy nie jest report-only, tylko report-donikąd: nie może paść, nie emituje artefaktu ani adnotacji, a po cichu flaguje dwa naprawialne CVE o wadze HIGH we wpisach produkcyjnego lockfile'a

nakład **S** · obszar **CI/CD** · **ryzyko** · kategoria `security` · **rekonesans — nieweryfikowane adwersarialnie**

`.github/workflows/ci.yml:267`

**Co to kosztuje.** Repo płaci za skaner podatności przy każdym PR i każdym pushu na main i nie dostaje z niego żadnego konsumowalnego wyniku. W tej chwili ukrywa to dwa advisory o wadze HIGH z już opublikowanymi wersjami naprawczymi, oba na niedeweloperskich wpisach w wysyłanym lockfile. `sharp` w szczególności to pipeline obrazków Next.js i jest obecny w standalone'owym obrazie runtime, więc jest to żywa zależność produkcyjnego frontendu, a nie sprawa wyłącznie build-time.

**Naprawa.** Dwie małe zmiany zachowujące charakter advisory: dodać `format: sarif` + `output: trivy.sarif` oraz krok `github/codeql-action/upload-sarif`, żeby znaleziska lądowały w zakładce Security, gdzie da się je zatriagować i odrzucić z uzasadnieniem — albo przynajmniej wrzucać tabelę jako artefakt builda. Osobno: podbić postcss do >=8.5.18 i sharp do >=0.35.0 w lockfile. Dopiero gdy istnieje czytelny raport, przełączenie `exit-code: '1'` staje się decyzją, którą ktokolwiek może podjąć.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 216` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f221"></a>

### #221 · P2 · Nic w repo nie przypina ani nie weryfikuje collation produkcyjnego Postgresa, a każda lista poza jedną sortuje polskie nazwiska przez ORDER BY w SQL — i ten jeden wyjątek przeniesiono do Pythona właśnie dlatego, że SQL robił to źle

nakład **M** · obszar **Backend · serwisy** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/services/client_order_lines.py:186`

**Co to kosztuje.** `grep -rn 'lc_collate|datcollate|pg_collation|COLLATE "' backend/app backend/alembic backend/tests` zwraca ZERO trafień — collation bazy nie jest nigdzie przypięte, udokumentowane, asertowane w migracji, odzwierciedlone w entrypoint.sh ani pokryte testem, a /api/health/deep go nie raportuje. Tymczasem co najmniej 18 SQL-owych ORDER BY sortuje widoczne dla użytkownika listy polskich nazwisk (team_structure.py:396/586/602/865, users.py:76/137/150/161, jobs.py:3185, priority_work.py:512, linkedin_metrics.py:99/136, scoring_weights.py:92, cztery moduły dynareportera). Kontener to postgres:16-alpine, czyli musl libc, gdzie locale inne niż C nie są zaimplementowane, a collation tekstu degraduje się do kolejności bajtowej — w której Ł (U+0141), Ą, Ć, Ę, Ń, Ó, Ś, Ź, Ż sortują się PO Z. Albo tak właśnie jest (i wtedy każdy dropdown rekruterów, konsultantów i klientów wyrzuca osoby o polskich nazwiskach na sam dół — dokładnie ten błąd, który client_order_lines.py obchodzi ręcznie), albo nie — i nikt w tym repo nie ustalił, jak jest.

**Naprawa.** Do zbadania: (1) najpierw ustal fakt — odpal na produkcji `SELECT datcollate, datctype FROM pg_database WHERE datname=current_database();` oraz `SELECT 'Łukasz' < 'Zbigniew';` (przez workflow Coolify set env albo tymczasową sondę w /api/health/deep), bo wszystko inne zależy od odpowiedzi; (2) jeśli collation jest C/zdegradowane przez musl, zdecyduj między poprawką po stronie aplikacji (reużycie `normalize_person_name_part` we wspólnym kluczu sortowania, tak jak robi już client_order_lines) a poprawką po stronie bazy (collation ICU na kolumnach z nazwiskami — uwaga: zmiana collation unieważnia każdy indeks zbudowany na tych kolumnach i wymagałaby przebudowy CONCURRENTLY, z której safety net indeksów w entrypoint.sh obecnie się nie podniesie); (3) dodaj collation do /api/health/deep, żeby odpowiedź przestała być nieznana.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 221` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f222"></a>

### #222 · P2 · Każda funkcja AI na produkcji działa bez miesięcznego sufitu wydatków — zweryfikowane na żywo — a jedyną powierzchnią, która o tym mówi, jest informacyjny string w healthchecku, na którym nikt nie stawia bramki

nakład **S** · obszar **Backend · serwisy** · **ryzyko** · kategoria `ops` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/services/ai_quota.py:172`

**Co to kosztuje.** Odpowiedź z żywej produkcji w tej sesji: `"ai_features": "uncapped: candidate_summary,champion_draft,champion_profile_parse,cv_backfill,cv_interactive_chat,cv_parser,cv_requirement_map,job_description_generator,notes_extraction,order_parser,scoring"` — czyli WSZYSTKIE jedenaście wartości AIFeatureKey ma monthly_limit <= 0, a więc sufit jest wyłączony dla każdej rozliczanej przez Claude/Voyage funkcji w produkcie, włącznie z dwiema najdroższymi (cv_backfill i scoring). Semantyka fail-open jest celowa i udokumentowana w docstringu modułu; NIEudokumentowane jest to, że ta celowa furtka awaryjna jest trwałym stanem produkcji. Kontrolą kompensującą jest `checks.ai_features` w /api/health — ale health tylko to raportuje, `overall` liczy się wyłącznie z bazy, a smoke test w deploy.yml asertuje `.status != "unhealthy"`, więc stan bez sufitu jedzie na zielono w nieskończoność. Audyt wykazał, że kill-switch AI nie zatrzymuje generowania CV B2B; w połączeniu z tym nie ma żadnej działającej bariery wydatkowej: przełącznik, który działa, nie jest podłączony do drogiej ścieżki, a sufit, który by to złapał, jest nieustawiony.

**Naprawa.** Do zbadania: (1) wyciągnij faktyczne wydatki per funkcja z `ai_usage_logs` pogrupowane po miesiącu i funkcji za ostatnie 3 miesiące — to daje liczby potrzebne do dobrania realnych sufitów; (2) zaseeduj AIFeatureConfig.monthly_limit dla wszystkich 11 kluczy (seed `_DATA_STATEMENTS` w entrypoint.sh dla ai_features już istnieje, zgodnie z precedensem 0217 — sprawdź, czy seeduje limity, czy tylko wiersze); (3) zdecyduj, czy `ai_features: uncapped` powinno degradować `overall` w `/api/health` do `degraded` (NIE może stać się `unhealthy` — to bramkuje 503 i restartuje kontenery), czy raczej disk-alert.yml/sentry-daily-monitor.yml powinny dostać tanią asercję na tym stringu; (4) potwierdź, że `_current_period_start()` liczy granicę miesiąca w Europe/Warsaw, a nie w UTC — patrz finding o strefie czasowej.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 222` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f223"></a>

### #223 · P2 · Wtyczka do przeglądarki, z której rekruterzy korzystają codziennie, ma zero CI, zero testów i dwa commity w historii, a trzyma 30-dniowy refresh token i wildcardowe uprawnienia hostowe na *.dynaminds.pl

nakład **M** · obszar **Wtyczka** · **ryzyko** · kategoria `risk` · **rekonesans — nieweryfikowane adwersarialnie**

`extension/manifest.json:27`

**Co to kosztuje.** `grep -rn 'extension/' .github/ Makefile` nie zwraca nic — wtyczka nie jest lintowana, testowana, budowana ani nawet wymieniona w filtrze ścieżek CI, a `git log --oneline -- extension/` pokazuje łącznie 2 commity, ostatni z 2026-05-16, przy backendzie, który w 90 dni przyjął 894 commity. To żywy produkcyjny klient API: robi POST /api/candidates/from-linkedin (endpoint wciąż obecny w produkcyjnym OpenAPI) i sam odświeża sesje. Jej host_permissions dają jej `https://*.dynaminds.pl/*` — co obejmuje panele sterowania Coolify coolify-nexus/compass/atlas.dynaminds.pl — oraz `http://localhost/*` po cleartekście, a backend_url jest ustawialny przez użytkownika ze strony opcji (`setBackendUrl` przyjmuje dowolny string i tylko obcina końcowe slashe). Refresh token, który przechowuje, to to samo 30-dniowe poświadczenie z pełnymi uprawnieniami, które audyt już zgłosił jako logowane w URL przez /api/auth/refresh — a api-client.js jest dokładnie tym wywołującym, który je tam wkłada.

**Naprawa.** Do zbadania: (1) porównaj extension/src/shared/api-client.js z żywymi schematami żądań z /openapi.json dla /api/auth/login, /api/auth/refresh i /api/candidates/from-linkedin i zaraportuj każdy dryf od 2026-05-16; (2) ustal, czy wtyczka jest w ogóle jeszcze używana — odpytaj logi ai/audit albo tabelę candidates o wiersze utworzone ścieżką from-linkedin w ostatnich 30 dniach; jeśli odpowiedź to zero, to jest martwy kod do usunięcia, a nie dług do obsłużenia; (3) jeśli jest żywa, dodaj minimalny job CI (eslint + test kontraktowy asertujący trzy ciała żądań wobec zacommitowanego OpenAPI) i zawęź host_permissions do api.nexus.dynaminds.pl (zdejmując wildcard *.dynaminds.pl, który sięga paneli Coolify, oraz wpis cleartext http://localhost).

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 223` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f224"></a>

### #224 · P2 · RECRUITMENT_PRIORITY_MODE='off' zatrzymuje tylko pętlę workera — wszystkie 22 endpointy priority-work zostają otwarte na zapis, więc 'priority_work: disabled' w /api/health mówi więcej, niż jest naprawdę wyłączone

nakład **L** · obszar **Backend · tło** · **dług** · kategoria `debt` · **rekonesans — nieweryfikowane adwersarialnie**

`backend/app/tasks/priority_work.py:298`

**Co to kosztuje.** Żywa produkcja raportuje `"priority_work": "disabled"`. Flaga bramkuje dokładnie jedną rzecz — pętlę sweepu — a moduł API nigdy się na niej nie rozgałęzia: w produkcyjnym OpenAPI obecne są 22 ścieżki priority-work (/api/priority-work/current, /mine, /team, /demands, /assignments, /plans/draft, /plans/{id}, …), wsparte 1743 liniami routera + 1131 liniami serwisu i 9 tabelami, których istnienie na produkcji potwierdza /api/health/deep (recruitment_priority_plans, _plan_members, _demands, _assignments, _blockers, _exceptions, _state, _user_modes, _alerts, _audit_events). Head of Recruitment może stworzyć plan, przypisać zapotrzebowania i wziąć blokady SELECT ... FOR UPDATE na wierszach `jobs` (priority_work.py:644/702/710/786) dla modelu, którego worker nigdy nie ruszy, nigdy nie awansuje statusu i nigdy nie zaalertuje. Pamięć projektu odnotowuje model priority-work jako porzucony; nic w kodzie ani w wyjściu healthchecka tego nie mówi.

**Naprawa.** Do zbadania: (1) ustal, czy na produkcji istnieją jakiekolwiek wiersze w 9 tabelach recruitment_priority_* (przez /api/admin/snapshot albo zapytanie read-only) — niepuste tabele oznaczają, że ktoś już korzystał z tej powierzchni, kiedy była 'disabled'; (2) potwierdź, czy frontend w ogóle routuje na /priority-work przy mode=off (sprawdź middleware.ts i capability w sidebarze), bo dostępne UI na bezczynnym backendzie to gorszy z dwóch stanów; (3) zdecyduj o dyspozycji — albo zabramkuj każdy endpoint zapisu na mode != 'off' z 503 nazywającym flagę (S), albo, jeśli model jest potwierdzenie porzucony, zaplanuj usunięcie routera, serwisu, pętli i tabel (XL, przy czym tabele niosą FK do jobs/users, więc DROP wymaga tej samej ostrożności co analiza DROP-a dynareportera); (4) tak czy inaczej, spraw, żeby string w healthchecku był uczciwy — 'disabled (worker only; API open)' albo zabramkuj API.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 224` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f1"></a>

### #1 · P3 · Komentarz w `config.py:452` reklamuje kanał SMTP dla alertów post-interview T+45, który nigdy nie został podpięty; `send_post_interview_reminder()` to rusztowanie bez ani jednego wywołania, a wymagane przez nie ustawienie `FRONTEND_URL_BASE` nie istnieje

nakład **S** · obszar **Backend · serwisy** · **dług** · kategoria `dead-code`

`backend/app/services/email.py:125`

**Co to kosztuje.** Zebranie feedbacku od klienta po rozmowie to follow-up o najwyższej dźwigni w lejku rekrutacyjnym — to on przesuwa kandydata z „po rozmowie" do „oferta" albo zwalnia slot. Projekt przewiduje trzy narastające pingi (T+15, T+45, T+2h), a `config.py:452` dokumentuje SMTP jako ich drugi KANAŁ: „Email (SMTP) — fallback kanał po T+45 dla post-interview alertów". Ten kanał nigdy nie został podłączony. Każdy ping idzie wyłącznie in-app. Przy adopcji in-app mierzonej w tym produkcie jednocyfrowymi procentami przypomnienie tylko in-app to przypomnienie, którego większość rekruterów nie zobaczy, a oczywiste lekarstwo operatora — włączenie `SMTP_ENABLED`, które realnie działa dla resetów haseł, maili weryfikacyjnych, wzmianek i fallbacku czatu — nie wyśle ani jednego maila post-interview.

**Naprawa.** W `check_post_interview_t45` (`notification_triggers.py:691`), po udanym emicie in-app, wyszukaj email każdego odbiorcy i zawołaj `email.send_post_interview_reminder(...)` pod strażą `settings.SMTP_ENABLED` — `send_email()` już jest no-opem, który loguje i zwraca `False`, gdy SMTP nie jest skonfigurowany, więc to nie może wywalić pętli triggerów. Eskalacja w `check_post_interview_t2h_escalation` zasługuje na to samo. Jeśli natomiast decyzja jest taka, że maila tu nie chcemy — usuń funkcję i popraw mylący komentarz w `config.py:452`.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 1` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f2"></a>

### #2 · P3 · `contract_lifecycle.reopen_contract()` nie ma ani jednego wywołania — nie jest nawet importowana; naprawa `ended/ending→active` jest ręcznie wklejona w `contracts.py:1225` i `:2482`, ale tylko kopia z `/bulk-extend` realnie gubi audyt statusu

nakład **S** · obszar **Backend · serwisy** · **dług** · kategoria `debt`

`backend/app/services/contract_lifecycle.py:300`

**Co to kosztuje.** `contract_lifecycle.py` to strzeżone, audytowane miejsce każdego przejścia statusu kontraktu — `activate`, `revert`, `void` przechodzą przez `assert_transition()` i zapisują wiersz `Activity` przez `_audit()` z `from_status`/`to_status`. Przedłużenie kontraktu to jedyne przejście, które to wszystko omija, w dwóch osobnych ręcznie napisanych kopiach. Efekt: przejście najściślej powiązane z przychodem — zakończony konsultant wracający na `active`, bo współpracę przedłużono — jest jedynym bez wpisu `from_status`/`to_status` w feedzie aktywności. Ktokolwiek będzie odtwarzał ze śladu audytowego, dlaczego kontrakt jest w danym miesiącu aktywny, znajdzie aktywację i terminację, ale nie reopen. A ponieważ reguła żyje teraz w trzech miejscach, następna jej zmiana (powiedzmy dopuszczenie leczenia `suspended` albo wymóg sprawdzenia podpisu) trafi do jednego lub dwóch z nich.

**Naprawa.** Zastąp oba bloki inline wywołaniem `await reopen_contract(db, contract, actor_id=current_user.id)` — zwraca już `bool`, więc ścieżka bulk może dalej zliczać, i ma już udokumentowane, dlaczego nie ma tu ponownego sprawdzenia podpisu. To zwija trzy kopie do jednej i przywraca brakujące wiersze audytu `contract_reopened`. Rozważ też zmianę nazwy `reopen_contract_endpoint`, bo czytelnik porównujący nazwę endpointu z nazwą funkcji serwisowej rozsądnie założy, że to ta sama operacja, a nie jest.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 2` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f3"></a>

### #3 · P3 · `QDRANT_API_KEY` to martwa gałka konfiguracyjna — nigdy nie przekazywana do żadnej z 25 konstrukcji `QdrantClient`, a `qdrant-client` 1.12.1 nie ma fallbacku na env, który by ją podchwycił

nakład **S** · obszar **Backend · rdzeń** · **dług** · kategoria `dead-code`

`backend/app/core/config.py:27`

**Co to kosztuje.** Qdrant trzyma embeddingi dla około 49 tys. profili kandydatów — indeks stojący za wyszukiwaniem semantycznym, Talent Radar, rekomendacjami, matchingiem marketplace i klasyfikacją kategorii kompetencji. Siedząc w `config.py` obok `QDRANT_HOST` i `QDRANT_PORT`, które OBA są honorowane, `QDRANT_API_KEY` czyta się jako „ten deployment umie się uwierzytelnić do Qdranta". Nie umie. Ustawienie tej zmiennej to no-op, więc operator, który ustawi ją w ramach hardeningu, dostaje fałszywe zapewnienie, że połączenie do vector store jest uwierzytelnione, podczas gdy nadal jest anonimowe. Odwrotny kierunek jest gorszy: standardowym sposobem zabezpieczenia Qdranta jest ustawienie `service.api_key` po stronie serwera, a zrobienie tego naraz zwróciłoby 401 na wszystkich 24 klientach, przy czym nic w aplikacji nie ma jak dostarczyć klucza.

**Naprawa.** Wprowadź jedną fabrykę (`embedding_service` ma już taką w linii 74 — zrób z niej jedyną), która przekazuje `api_key=settings.QDRANT_API_KEY or None`, i przepuść przez nią pozostałe 23 miejsca. To jednocześnie czyni ustawienie realnym i usuwa 24 zduplikowane connection stringi. Jeśli uwierzytelnianie Qdranta naprawdę jest poza zakresem — usuń ustawienie zamiast tego; klucz konfiguracyjny, który po cichu nic nie robi, jest gorszy niż jego brak. Ta sama jednolinijkowa zmiana pozwoliłaby rozwiązać tak samo `EMBEDDING_DIMENSION` (`config.py:35`, również nigdy nieczytane, przesłonięte zahardkodowanym `VECTOR_SIZE = 1024` w `embedding_service.py:21`).

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 3` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f41"></a>

### #41 · P3 · Domyślna wartość `manualSearchHref` w AiStatusBanner jest autoreferencyjna: banner renderuje się wyłącznie wewnątrz CandidateSearchView, więc jego CTA „wyszukaj manualnie" wskazuje na widok, w którym już jesteśmy (a z zakładki oferty — wyprowadza z niego)

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/jobs/AiStatusBanner.tsx:29`

**Co to kosztuje.** Psują się dwie rzeczy naraz. Po pierwsze, samodzielna strona wyszukiwania manualnego — CandidateSearchView ma 1321 linii i jest udokumentowanym fallbackiem na wypadek niedostępności Voyage/Qdrant — jest nieosiągalna dla rekrutera, który nie zna URL-a na pamięć. Nie ma jej w sidebarze ani w palecie ⌘K. Po drugie, i gorzej: jedyny link, który na nią wskazuje, renderuje się *wewnątrz* CandidateSearchView, który strona oferty osadza jako swoją zakładkę wyszukiwania manualnego. Więc gdy `ai_status` przechodzi w `degraded`/`down`, rekruterka stojąca na zakładce wyszukiwania manualnego oferty #482 dostaje czerwony alert z wezwaniem „Wyszukaj kandydatów manualnie →" — jest już na miejscu, a kliknięcie przenosi ją na stronę globalną, gubiąc `addToJob` (brak masowego dodania do pipeline'u), `buildJobSearchPrefill(job)` (wszystkie filtry oferty) i `exclude_in_job_id` (kandydaci już w pipelinie wracają na listę). Wyjście awaryjne bannera niszczy kontekst, w którym się pojawia, a odpala się tylko podczas awarii AI — dokładnie wtedy, gdy rekruter najbardziej potrzebuje działającego fallbacku. To repo już się na tym sparzyło (pamięć: sonda łączności z Qdrantem świeciła na zielono przez dwugodzinną awarię), i właśnie dlatego ten banner w ogóle istnieje.

**Naprawa.** Przekaż udokumentowany override tam, gdzie prop był zaprojektowany do użycia: daj CandidateSearchView opcjonalny `manualSearchHref` i niech `ManualSearchTab` (app/jobs/[id]/page.tsx:1548) przekazuje ograniczony do oferty `?tab=manual-search`, albo po prostu ukryj CTA, gdy `addToJob` jest ustawione — użytkownik jest już na powierzchni manualnej, więc link jest w najlepszym razie no-opem, a w najgorszym destrukcyjny. Osobno: daj /candidates/search prawdziwe wejście — pozycję w CommandPaletteV2 („Wyszukiwanie manualne") bramkowaną na `nav.candidates` i/lub link z toolbara /candidates. Jeśli samodzielna strona nie jest chciana jako powierzchnia produktowa, usuń src/app/candidates/search/page.tsx i zdejmij domyślny href, żeby prop stał się wymagany.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 41` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f54"></a>

### #54 · P3 · Martwe gałęzie degradacji w admin-only panelu legacy matchingu: testuje `search_type` „bm25"/„unavailable" oraz `meta.degraded`, a `/api/jobs/{id}/ai-matches` nie emituje żadnej z tych wartości (widget dla rekrutera na tej samej zakładce jest nietknięty)

nakład **M** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/app/jobs/[id]/page.tsx:785`

**Co to kosztuje.** Kiedy Qdrant albo Voyage jest niedostępny — albo po prostu gdy rekrutacja nie została jeszcze zaindeksowana, co jest częstym przypadkiem dla świeżo utworzonych rekrutacji — zakładka „Dopasowania" po cichu podmienia ranking semantyczny na proxy oparte na słowach kluczowych i kompletności profilu, i nie daje rekruterowi żadnego sygnału. `search_type` ma wtedy wartość „tag_fallback", która nie pasuje do żadnej z trzech gałęzi, a `degraded` jest trwale fałszywe, bo ten endpoint nie ma klucza `meta`. Jedyną różnicą jest brak małej plakietki „Semantic AI", a brak czegoś nie jest sygnałem. Rekruter czyta listę uporządkowaną po tym, jak kompletne jest CV, jako „najlepsze dopasowania AI do tej rekrutacji" i zaczyna do tych ludzi dzwonić. NEXUS miał już dwugodzinną awarię Qdranta, która pozostała zielona na sondzie health; widget rekomendacji naprawiono dokładnie pod tym kątem, tej trasy nie.

**Naprawa.** Skasuj dwie martwe gałęzie i oprzyj się na tym, co backend faktycznie emituje: traktuj każdy `search_type` inny niż wartość `semantic*` jako zdegradowany i renderuj istniejące ostrzeżenie. Lepiej: spraw, żeby `/ai-matches` emitowało tę samą kopertę `meta`, którą buduje już `/recommendations` (`{mode, degraded, reason, hidden}`), tak by obie powierzchnie miały jeden kontrakt, i usuń `"bm25" | "unavailable"` z obu unii literałowych w `lib/api.ts`, bo nic ich nie produkuje.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 54` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f61"></a>

### #61 · P3 · memo() na CandidateKanbanCard nigdy nie może zadziałać — toggleSelect nie jest opakowany, a trzy sąsiednie propsy to inline'owe strzałki, więc granica memo na poziomie karty jest martwym kodem (ScoreRing jest bez znaczenia; tablica widzi ~1,6 ręcznego ruchu dziennie w całej firmie)

nakład **S** · obszar **Frontend · UI** · **ryzyko** · kategoria `perf`

`frontend/src/components/v2/pages/KanbanBoardV2.tsx:1573`

**Co to kosztuje.** Tablica pipeline'u to miejsce, w którym rekruterzy spędzają dzień roboczy przy aktywnej rekrutacji, a multi-select jest normalnym sposobem przenoszenia grupy kandydatów między etapami. Ponieważ obie granice memo są zniweczone, każde tiknięcie checkboxa re-renderuje każdą kartę w każdej kolumnie — a każda karta niesie SVG-owy ScoreRing (zmemoizowany w :244, tak samo zniweczony przez kaskadę), badge'y, tooltipy i wrapper Draggable. Otwarcie dowolnego modala tablicy (prompt screeningowy, weryfikacja odrzucenia, usunięcie z rekrutacji) i każdy toast robią to samo. Autor projektował ewidentnie pod coś przeciwnego: trzy granice memo() i boolowski prop `selected` istnieją właśnie po to, żeby zmiana jednej karty kosztowała render jednej karty. Tablica płaci pełny koszt, niosąc jednocześnie pełną złożoność tej optymalizacji.

**Naprawa.** Opakuj `toggleSelect` w useCallback z pustą tablicą zależności (forma z setterem i tak czyni go wolnym od zależności) i wynieś trzy inline'owe strzałki z :1574, :1582 i :1585 do handlerów w useCallback, obok istniejącego handleAcceptVerification. `scoreMap` jest już w useMemo w rodzicu (jobs/[id]/page.tsx:1087), a `selected` to prawdziwa wartość stanu, więc gdy cztery callbacki staną się stabilne, obie granice memo zaczną działać i zmiana zaznaczenia re-renderuje jedną kartę. Zweryfikuj przez "Highlight updates" w React DevTools — sprawdzenie jest wizualne i zajmuje minutę.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 61` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f65"></a>

### #65 · P3 · Jedno zapytanie na profilu kandydata (dokumenty kontraktu, `CandidateDetailV2.tsx:2017`) renderuje przejściową awarię backendu jako „Brak załączników" — czyli fałszywe twierdzenie o załącznikach kontraktu. Osiągalne tylko przez admin/delivery_lead/tac i tylko przy błędzie przejściowym; główna teza zgłaszającego, że cały 4724-liniowy ekran nie ma obsługi błędów, jest nieprawdziwa.

nakład **L** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/v2/pages/CandidateDetailV2.tsx:2017`

**Co to kosztuje.** Profil kandydata to ekran, na którym rekruterzy siedzą na co dzień. Piętnaście niezależnych zapytań na nim (dokumenty, snapshoty CV, stan brandowanego CV, feed aktywności, szkic kontraktu, …) nie ma w ogóle gałęzi błędu — grep po `isError` w całych 4724 liniach zwraca zero trafień — więc 500, 403 albo zerwane połączenie jest rysowane jako „nic tu nie ma". „Brak załączników" przy podpisanym kontrakcie B2B to najgorszy przypadek: mówi użytkownikowi fakt o kontrakcie, który jest fałszywy. To udokumentowany w tym repo własny anty-wzorzec (awaria nigdy nie może renderować się jako pustka), a przeżywa akurat na tym ekranie, bo żaden test nigdy go nie wyrenderował: ani `CandidateDetailV2`, ani `CandidatesListV2` nie jest importowany przez żaden ze 148 plików testowych frontendu. Razem mają 8311 linii; w całym frontendzie 20 z 53 komponentów ≥500 linii (20 735 z 57 130 linii) nie jest wspomniane przez żaden test.

**Naprawa.** Zdestrukturyzuj `isError` w każdym z 15 zapytań i rozbij trzy stany wprost — kolejność, której repo już używa gdzie indziej, to najpierw `isError`, potem jeszcze-nie-`isSuccess`, a na końcu prawdziwy pusty stan (patrz `MultiConsultantOrdersTab.tsx:301`, gdzie jest komentarz wyjaśniający, dlaczego gałąź pustego stanu musi wisieć na `isSuccess`, a nie na `!isLoading`). Każdej gałęzi awarii daj możliwość ponowienia zamiast cichego tekstu. Potem dodaj pierwszy plik testowy dla `CandidateDetailV2` pokrywający dokładnie to: zamockuj wywołanie dokumentów tak, żeby odrzuciło, i asertuj, że panel NIE mówi „Brak załączników". Reguła linta zakazująca gołej destrukturyzacji `{ data } = useQuery` w komponentach renderujących pusty stan zatrzymałaby kolejny taki przypadek.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 65` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f79"></a>

### #79 · P3 · Sprzęt z terminem DZIŚ jest malowany jako po terminie od 02:00 czasu warszawskiego — data bez godziny parsowana jako północ UTC i porównywana z chwilą, więc wiersz pokazuje jednocześnie „20.08.2026" i czerwony trójkąt spóźnienia

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `ux`

`frontend/src/components/contracts/ContractEquipmentTab.tsx:53`

**Co to kosztuje.** `return_due_date` jest stringiem z samą datą; `new Date("2026-08-20")` jest parsowane przez ECMAScript jako północ UTC, czyli 02:00 czasu warszawskiego. Porównywanie tej chwili z `new Date()` oznacza, że każda pozycja `pending`, której termin przypada DZIŚ, testuje się jako po terminie od 02:00 czasu warszawskiego — 22 godziny z 24 w CEST, 23 w CET. Wiersz jest malowany `bg-destructive/10` i dostaje `AlertTriangle` obok daty (linie 143 i 164), więc Delivery Lead ścigający zwroty laptopów widzi czerwony sygnał „spóźnione" dla sprzętu, którego termin jest dziś i który jeszcze nie jest spóźniony. Backend implementuje tę samą regułę i się z tym nie zgadza: `contract_alerts.py` liczy `days_left = (item.return_due_date - date.today()).days`, a powiadomienie dla tej samej pozycji brzmi „ma być zwrócony 2026-08-20 (0 dni)". Dwie implementacje jednej reguły, które się rozjechały — a rozjazd zawsze myli się w stronę fałszywego alarmu, czyli w tę, która uczy ludzi ignorować badge.

**Naprawa.** Porównuj dni kalendarzowe, a nie chwile: parsuj termin jako dzień w strefie warszawskiej i testuj `dueDay < todayWarsaw()` tym samym wspólnym helperem `todayWarsaw()`, który wprowadzasz przy naprawie `ContractInvoicesTab`/`ContractAmendmentsTab` (porównanie stringów na `YYYY-MM-DD` w zupełności wystarcza i całkowicie omija parsowanie `Date`: `item.return_due_date < todayWarsaw()`).

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 79` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f100"></a>

### #100 · P3 · Backend dodaje `assignment_skipped_reason` właśnie po to, żeby popup przestał być cichym no-opem; wtyczka nigdy tego pola nie czyta (zero trafień w extension/src), więc przypisanie do rekrutacji, które serwer świadomie pominął, renderuje się jako dokładnie ten sam banner sukcesu co przypisanie udane

nakład **S** · obszar **Wtyczka** · **dług** · kategoria `debt`

`extension/src/content/modal-host.js:299`

**Co to kosztuje.** Rekruter wybiera rekrutację w modalu, klika „Dodaj do NEXUS", dostaje banner z linkiem do profilu i odchodzi przekonany, że kandydat siedzi w pipelinie tej rekrutacji. Nie siedzi — serwer świadomie pominął przypisanie i powiedział o tym w polu, którego nikt nie czyta. Powód pominięcia („manager tej rekrutacji już odrzucił tę osobę po rozmowie") jest informacją, którą rekruter POWINIEN zobaczyć, bo inaczej za tydzień szuka jej w kanbanie i nie znajduje, albo dodaje ją drugi raz. To jest dokładnie ta klasa defektu, którą to repo nazywa po imieniu w innych miejscach: sukces udający wynik.

**Naprawa.** W `renderResult`, po istniejącym bannerze, renderuj `c.assignment_skipped_reason` jako wiersz ostrzeżenia, gdy jest obecny (string jest już gotowym polskim zdaniem z `verdict.as_polish_detail()`), i zdejmij sugestię, że przypisanie do rekrutacji nastąpiło — np. „Zapisany w bazie, ale NIE dodany do rekrutacji: <powód>". Ten sam kształt co istniejący blok `resyncNote` trzy linie niżej, więc to zmiana na pięć linii. Zabezpiecz ją testem kontraktowym proponowanym w znalezisku #1, żeby kolejne dodanie pola do schematu odpowiedzi nie mogło wejść nieprzeczytane.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 100` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

<a id="f103"></a>

### #103 · P3 · Panel priorytetów tylko dla DL oferuje „Oznacz jako zrealizowane" → `fulfilled`, czyli przejście, którego backend wprost zabrania roli delivery_lead i ma na nie dedykowany test odrzucenia — dziś martwy kod (panel osierocony dwa poziomy wyżej, moduł uśpiony)

nakład **S** · obszar **Frontend · UI** · **nie działa** · kategoria `broken`

`frontend/src/components/v2/priority-work/PriorityRequestsPanel.tsx:348`

**Co to kosztuje.** Utajone dziś tylko dlatego, że `PriorityRequestsPanel` nie jest zamontowany (znalezisko 1) — ale to dokładnie ten defekt, który sprawi, że „wystarczy zamontować panel z powrotem" wywali się przy pierwszym kliknięciu. Panel renderuje się wyłącznie dla delivery_lead (`if (!hydrated || !isDeliveryLead) return null`, linia 464), a `_DEMAND_STATUS_TRANSITIONS_DL` w backend/app/services/priority_work_service.py:62-75 przyznaje delivery_leadowi dokładnie {paused, cancelled} z `open`, {paused, cancelled} z `covered`, {open, cancelled} z `paused` — `fulfilled` nie występuje w żadnym wpisie DL, tylko w `_DEMAND_STATUS_TRANSITIONS_HOR` (linie 76-92). `update_priority_demand` przekazuje `actor_is_hor=_is_hor(current_user)` (priority_work.py:754), więc czysty DL dostaje `HTTPException(422, PRIORITY_DEMAND_TRANSITION_INVALID)` w 100% przypadków. Sąsiedni przycisk „Wstrzymaj" obok jest legalny, więc awaria wygląda na arbitralną. Żaden test tego nie pokrywa: suite frontendowy mockuje całego klienta (`updateDemand: vi.fn()`, PriorityRequestsPanel.test.tsx:21), a jedyny backendowy test behawioralny `update_priority_demand` prowadzi go z `_FakeUser(UserRole.head_of_recruitment)` i nigdy nie ustawia statusu — kontrakt jest „pokryty" wyłącznie asercją na stringu źródła, `assert "assert_demand_status_transition(" in update_source` (test_priority_work_api.py:564), która przechodzi niezależnie od zawartości tabeli przejść.

**Naprawa.** Jedno z dwóch, rozstrzygane intencją: albo usuń przycisk z `PriorityRequestsPanel` (jest to akcja HoR zgodnie z `_DEMAND_STATUS_TRANSITIONS_HOR`, a DL ma już Wstrzymaj/Anuluj), albo dodaj `PriorityDemandStatus.fulfilled` do wpisów DL dla `open` i `covered`. Potem dołóż brakujący test — wywołaj `update_priority_demand` z aktorem delivery_lead i status="fulfilled" i zaasertuj zamierzony wynik, żeby frontend i tabela przejść nie mogły znowu rozjechać się za zamockowanym klientem.

<sub>Scenariusz awarii, dowód w kodzie i potwierdzenie weryfikatora: `id: 103` w [tech-debt-backlog.json](./tech-debt-backlog.json).</sub>

---

## Nie ruszać — wygląda jak dług, jest decyzją

- **Lustro DDL w `entrypoint.sh`** — Nie jest duplikacją migracji — produkcyjny alembic jest osierocony, a to jedyna rzecz, która stawia kolumny na prodzie.
- **Trzy wycofane powody zamknięcia w enumie B2B** — Zniknęły z pickera, ale zostają w Literalu i CHECK-u, bo produkcja ma wiersze, które je niosą. Zawężenie domeny wywali `ADD CONSTRAINT`.
- **Brak `from __future__ import annotations` w modułach ze slowapi** — PEP 563 + slowapi #579 zamienia guardy `Annotated` w wymagane parametry query.
- **Rola `finance` z pełnym dostępem operacyjnym** — Decyzja z 19.08, nie luka RBAC.
- **CloudTalk jako martwy kod** — Zneutralizowany świadomie po decyzji kosztowej z 28.07.
- **Twardy sufit dealbreakerów bez marginesu** — Rewizja z 19.08. Nieznana wartość przechodzi.
- **Trasy `/preview/*`** — Harness wizualny. Muszą wykonywać zero zapytań do API — to ich kontrakt.
- **Awaryjny pin `qdrant-client==1.12.1`** — Wraz z wpisem ignorującym go w Dependabocie. Świadomy.

## Obalone tropy

Weryfikacja adwersarialna odrzuciła 21 zgłoszeń. Zapisane, żeby następny audyt nie zaczynał od nich od nowa.

- **Traffit bidirectional integration is a fully built, fully wired-to-nothing subsystem: 9 production tables, ~1,130 LOC of app code, ~200 lines of entrypoint DDL and 24 con** — `backend/app/core/config.py` — REFUTED on two independent grounds: a load-bearing piece of the claimed impact is factually false, and the state is explicitly documented as intentional.

(1) FALSE EVIDENCE — "are asserted by /api/health/deep — permanently carrying schema and health-check weight". None of the 9 tables is probed by /api/health/deep. The `core_checks` list in backend/app/main.py:1899-1957 contains exactly two traff
- **AI_UNIFIED_RETRIEVAL_ENABLED / _SURFACES are read only by the orphaned orchestrator that nothing calls — and the admin diagnostics endpoint reports them as live configura** — `backend/app/services/matching_orchestrator.py` — The dead-code fact is true but the framing that makes it a P2 collapses on two independent attacks.

(a) It is DOCUMENTED staged work, not undocumented rot. matching_orchestrator.py:11-12 docstring: "Flag-gated per surface via ``surface_enabled``; existing surfaces are untouched until opted in." docs/ai-matching-scoring-recommendations-and-implementation-plan-2026-07-15.md:725 scopes PR8 as the or
- **Financial adjustments is a write-only ledger: no frontend calls any of its 3 endpoints, and no code anywhere reads an approved adjustment into any sum, despite the model ** — `backend/app/models/financial_adjustment.py` — The factual skeleton (no reader, no FE) is true, but every load-bearing part of the claim's framing collapses.

1) THE "PROMISE" IS A PLAN-ERA DOCSTRING, NOT A CONTRACT — AND IT IS PROVABLY STALE ONE LINE ABOVE THE QUOTE. The finder quotes model lines 8-9 as "the model's own contract". Line 7 of the same docstring says:
    backend/app/models/financial_adjustment.py:7  "- write: wyłącznie admin; r
- **The candidate list's match column picks 50 published recruitments with LIMIT and no ORDER BY, then renders that arbitrary count as the denominator — "3/50 rekrutacji" is ** — `backend/app/api/candidates.py` — The quoted code is accurate, but its premise is not. The claim requires ">50 published recruitments — the normal state for a body-leasing shop". Two independent production measurements in this repo say the real number is 14.

In-repo evidence, docs/suggested-jobs-draft-published-completion-report.md:17 (dated 2026-06-02, marked "zweryfikowane na prodzie"):

    **Root cause** (zweryfikowane na pro
- **GET /api/candidates/{id}/history returns contract rate_candidate AND rate_client — i.e. the per-consultant margin — to all seven operational roles, while both sibling rat** — `backend/app/api/candidates.py` — The handler has exactly ONE return, and it is a redaction wrapper. The finder quoted lines 3382-3399 (dict construction) and stopped before line 3427.

backend/app/api/candidates.py:3427 — the only `return` in `get_candidate_history` (verified with `awk 'NR>=3269 && NR<=3430 && /return /'` → one hit):
    return _candidate_history_response_for_user(response, current_user)

backend/app/api/candidat
- **Every Qdrant operation builds a brand-new client that is never closed — 21 construction sites, no shared client, no connection reuse on the hottest read path** — `backend/app/services/embedding_service.py` — The code pattern is quoted accurately, but three of the four load-bearing claims about it are wrong, and the perf harm does not materialize.

1) "Every Qdrant call pays a fresh TCP connect instead of reusing a warm connection" — the connect is not the cost, and construction does not touch the network at all. I unpacked the pinned wheel (`qdrant-client==1.12.1`, requirements.txt:29) and read `Qdran
- **The session cookie carrying the JWT is written without the Secure attribute** — `frontend/src/lib/session.ts` — The attribute really is absent, but the failure scenario cannot occur. The exploit needs a profile that HOLDS the cookie and has NO HSTS pin for nexus.dynaminds.pl. That state is unreachable.

The cookie is written exclusively by browser JS, from exactly two call sites — `frontend/src/store/auth.ts:516` (`writeAuthCookie(token)` inside `setAuth`) and the session-probe re-hydration at `frontend/src
- **The only automated comparison of the migration chain against the entrypoint safety net asserts nothing about the drift it measures, and its CI contract explicitly accepts** — `backend/tests/test_schema_inventory.py` — Three independent legs of the claim fail.

(1) THE HEADLINE PREMISE IS STALE — the finder quoted a code comment as a current measurement. backend/scripts/schema_inventory.py:542-546 says create_all fails "as it does on prod — an ORM FK references a table the models never map". That comment was written by the commit that INTRODUCED the tool. `git show 6878b0cf` (2026-07-22) names the exact FK verba
- **cc_centroid_sync sleeps 24h BEFORE its first iteration, and it is the only caller of compute_pool_centroid — so talent-pool centroids are never built and the "Sugerowane ** — `backend/app/tasks/cc_centroid_sync.py` — The mechanism is real but all three claimed consequences are false.

(A) "nexus_pool_centroids stays empty / the feature is dead" — refuted by this repo's own production measurements. docs/faza0-pomiary-produkcji-2026-07-27.md:140:
    "| `nexus_pool_centroids` | 84 | green |"
and independently 11 days later, docs/champion-talent-search-readiness-audit-2026-08-07.md:104:
    "Kolekcje Qdranta: `ne
- **Nine production tables, nine ORM models and nineteen environment settings for the Traffit bidirectional integration have zero readers — five of them are kill-switches an ** — `backend/app/core/config.py` — REFUTED — this is documented, dated, fail-closed staged work, and both of the finder's harm scenarios fail on inspection.

1) DELIBERATE AND DOCUMENTED, WITH A CORRECT RATIONALE. The finder quotes the migration docstring's own admission but treats it as an aside. It is the disposition. `backend/alembic/versions/0173_traffit_bidirectional_persistence.py:18`:
    "UWAGA: zapisów do tych tabel nie wy
- **The eval harness — and therefore the weekly matching-regression guardian — skips three production stages (eligibility gate, dealbreaker budget ceiling, historical boost),** — `backend/scripts/eval_matching.py` — The finding's central premise — that `_score_job_candidates` should reproduce `/api/recommendations` and is defective because it doesn't — is arithmetically self-defeating. The harness's ground truth IS the job's pipeline, and the endpoint's default is to delete the job's pipeline from its result set.

Ground truth construction, scripts/eval_matching.py:453-465:
```
    stages_res = await db.execu
- **Three drifted copies of the availability/status label catalogs — two of them render on the same /candidates screen and disagree, under a docstring that promises a single-** — `frontend/src/lib/filter-options.ts` — REFUTED on four independent grounds.

(1) NOT DRIFT — both catalogs were authored in ONE commit with a systematic abbreviation scheme. `git log -S'"Otwarty na projekty"' -- frontend/src/lib/filter-options.ts` and `git log -S'open_to_offers: "Otwarty"' -- .../ActiveFilterChips.tsx` both point at the same introducing commit `9193cf16 feat(filters): multi-select w dropdownach (status/typ/kategoria/re
- **The "siostrzane requesty" preview in the new-recruitment modal keys its cache without the job description it sends, so the banner never updates after the DL pastes the JD** — `frontend/src/components/AppShell.tsx` — The mechanical observation is accurate but the claimed harm does not exist. Four independent refutations:

(1) THE FAILURE SCENARIO IS ARITHMETICALLY IMPOSSIBLE. The banner count cannot depend on `raw_description` for the case described. `backend/app/services/request_history.py:352` sizes the vector search as `qdrant_limit = max(top_k * QDRANT_OVERSAMPLE_FACTOR, top_k)` with `QDRANT_OVERSAMPLE_FAC
- **Rate normalisation that fixes the pending-verification budget comparison is computed by the backend and dropped by the frontend — the approver still sees 150 PLN/h next t** — `frontend/src/lib/api.ts` — The literal contract drift is real (the two fields are on the wire and no component renders them), but every claimed HARM is contradicted by the code the finder did not read.

1) THE GATE IS NOT DEFEATED — the list contains ONLY rows the normalization already rejected. `backend/app/api/pipeline.py:651-661`:

        normalized_monthly, normalization_note = normalize_rate_to_monthly(
            De
- **"N dokumentów wygasa w 30 dni" on /my-clients is fed by a query that counts framework contracts that have ALREADY expired — the 30-day window was never implemented** — `backend/app/api/my_clients.py` — The quoted snippet is verbatim accurate (`backend/app/api/my_clients.py:256`) and `today.replace(day=today.day) == today` (verified in python3). But three separate load-bearing claims collapse:

**1. "What it does count is contracts whose expiry date has ALREADY passed" — FALSE.** A daily scanner flips exactly that population out of `active` before it can ever be counted. `backend/app/tasks/dl_por
- **Admin impersonation writes an audit trail nobody reads, and misattributes every CV download and candidate export made while impersonating to the impersonated employee** — `backend/app/api/deps.py` — HALF 1 — "leaves no record" is factually wrong. The finder grepped for `impersonator_id`, which is not the symbol the audit trail uses. The actual record is written by the endpoint that starts impersonation, backend/app/api/admin.py:437-450:

    db.add(
        Activity(
            entity_type="user",
            entity_id=target.id,
            action="impersonation_started",
            user_i
- **No storage-limitation mechanism exists anywhere: ~49k candidate records are kept indefinitely with no consent field, and the matching telemetry names a retention/DSAR job** — `backend/app/models/match_telemetry.py` — REFUTED on four independent grounds. Only a P3 residue survives.

(1) THE MISREADING THAT CARRIES THE FINDING. The finder writes: "the pseudonymisation claim does not hold uniformly: user_ref and client_ref are salted hashes but candidate_id on line 70 is a raw Integer". The docstring never claimed otherwise. Verbatim, match_telemetry.py:19-20:
    "  job. User/client identifiers are stored *pseud
- **Aneks (contract amendment) pre-fills effective_date from a frozen module-level TODAY, silently back-dating the rate-schedule step that drives margin and MRR** — `frontend/src/components/ContractAmendmentsTab.tsx` — The stated harm — "days already invoiced at the old client rate are re-priced at the new one in every margin/MRR surface" — does not exist in this codebase. Nothing anywhere integrates rate steps over a period; every consumer resolves a SINGLE point-in-time rate.

backend/app/models/contract.py:452-454 (the only resolver, reached by effective_client_rate / effective_candidate_rate / _effective_rat
- **Lifespan shutdown drains only the 34 registry loops, so every Coolify redeploy silently drops the 17 unreferenced create_task jobs — ruff's own RUF006 flags all 17 and th** — `backend/app/main.py` — Three sub-facts in the claim are literally true and I reproduced them, but every causal step from those facts to the stated impact fails.

1) THE CENTRAL CAUSAL CLAIM IS FALSE. Title: "so every Coolify redeploy silently drops the 17 UNREFERENCED create_task jobs". Being unreferenced has nothing to do with it. On redeploy the process exits; a task holding a strong reference dies exactly the same wa
- **The paid CV-fields backfill's only resume cursor lives in a module dict reset at import — the module docstring justifies that cursor by "Coolify restartuje kontener przy ** — `backend/app/api/admin_candidates.py` — The structural half is true and I reproduced it: `backend/app/api/admin_candidates.py:218` is literally `_CV_FIELDS_JOB: dict[str, Any] = {"running": False}`, there is no table/model/migration behind it (grep over `backend/alembic/versions/` and `backend/app/models/` for `cv_backfill` returns only the `AIFeatureKey` enum + `0223_cv_backfill_ai_feature.py` seed), and after a restart `GET /backfill-
- **/api/health reports priority_work "disabled" while 22 paths / 24 operations stay open and 9 tables keep taking writes — and the guard test file titled "must be INERT" onl** — `backend/app/main.py` — REFUTED on three independent grounds, plus one factually false impact statement.

(1) THE OPEN WRITES ARE INERT AT off. The claim's whole blast-radius argument assumes rows written at mode=off do something. They do not. Admission policy short-circuits before any assignment lookup — backend/app/services/priority_work_policy.py:671:

    if mode is PriorityMode.off:
        return PriorityWorkDecisi
