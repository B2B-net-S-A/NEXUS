# Audyt generatora CV — boldowanie wymaganych technologii

**Data:** 2026-07-13  
**Zakres:** generator B2B DOCX (`/cv-generator`), źródła kryteriów, prompt AI,
klasyfikacja technologii, render DOCX, podgląd frontendowy i testy.  
**Charakter audytu:** diagnostyczny, bez zmian w kodzie aplikacji.

## Status naprawy — ZREALIZOWANE 2026-07-13

Diagnoza zweryfikowana co do znaku (uruchomiony klasyfikator + realny render DOCX
+ 6-agentowy sweep wszystkich `file:line`). Naprawa wdrożona i zdeployowana w 3 PR-ach:

- **#674** — P0 źródło kryteriów (`OLLAMA_HOST`→`OLLAMA_BASE_URL`, stempel `_source`,
  fallback tech-only bez prozy).
- **#680** — rdzeń: boldowanie oparte na taksonomii NEXUS (`skills`/`skill_aliases`/
  `category`). Hybryda taksonomia+silny-sygnał, usunięty `_is_tech_token_name`,
  denylist B2/C1/UX/UI/QA, ekspansja aliasów, polska fleksja, `C`/`R`/`Jest`,
  wielowyrazowe marki. Nowy `skill_normalize.py`, `champion_builder` przez
  `iter_skill_names` + paren-aware split, prompt v6. Testy E2E asertują realne runy
  `<w:b>` w wyrenderowanym DOCX.
- **#682** — UX: podgląd „co się pogrubi" w modalu kryteriów + nudge regeneracji.

Wynik: false-positives (Agile/Scrum/Leadership/English/UX/B2/„Analiza") wyeliminowane;
false-negatives (C/R/Jest/ReactJS/K8s/Postgres/fleksja/wielowyraz) naprawione.
28/28 istniejących testów bold bez regresji.

### Korekty precyzji w tym dokumencie (drobne nieścisłości znalezione przy weryfikacji)

1. Finding 2 (F2-e): union `must+nice` NIE jest boldowany „bezwarunkowo" — jest gated
   (`if champion_dto`/`if highlight`) i FILTROWANY przez `compile_keyword_patterns`
   (Finding 4). To wejście do filtra, nie finalny zbiór boldów.
2. Reprodukcja R2: lowercase `komunikatywność` jest odrzucane wcześniej — na bramce
   „brak wielkiej litery" (`docx_renderer.py:766`), PRZED heurystyką polskich końcówek
   (`_looks_polish_word` operuje dopiero na formie z wielkiej litery).
3. Render/podgląd (B2): `CVGeneratorStandaloneV2.tsx:1097-1119` to tylko PODGLĄD;
   ścieżka pobrania to `handleDownloadGenerated` (~`:324-333`). Oba trafiają w ten sam
   endpoint.
4. Luki testowe (T1): część wymienionych wymiarów (tech-vs-metodyka, case, aliasy,
   wielowyraz, spaced-slash, część fleksji) MIAŁA już testy; realnie brakowało macierzy
   E2E `<w:b>`, testów `from_nexus_job`/parsera manual — dodane w #680.

## Podsumowanie

Problem nie wynika z losowego zachowania Claude ani z renderowania Worda.
Jest skutkiem niespójnego kontraktu danych:

1. `must_skills` i `nice_skills` przechowują ogólne kryteria matchingowe, a nie
   wyłącznie technologie.
2. Generator CV traktuje wszystkie wpisy z obu list jak potencjalne technologie.
3. Dopiero podczas renderowania próbuje zgadnąć, co jest technologią, na podstawie
   wielkich liter, cyfr, znaków specjalnych oraz osobnej ręcznej allowlisty.
4. Ta klasyfikacja nie używa istniejącej w NEXUS taksonomii `skills` /
   `skill_aliases`, jej kategorii ani aliasów.

W rezultacie występują równocześnie:

- **false positives** — boldowane są metodyki, języki, role, soft skills i
  warunki współpracy;
- **false negatives** — część rzeczywistych technologii nie jest boldowana albo
  boldowany jest tylko fragment nazwy;
- **niespójność między sekcjami** — nominatyw technologii może zostać pogrubiony,
  ale polska forma odmieniona już nie;
- **zależność od zapisu** — ta sama technologia działa lub nie działa zależnie od
  kapitalizacji, aliasu, ukośnika albo nazwy dostawcy.

Najważniejszy łańcuch błędu:

```text
opis oferty
  → fallback generowania kryteriów
  → must_skills / nice_skills z wpisami nietechnicznymi
  → połączenie obu list do highlight_keywords
  → heurystyczne zgadywanie „czy to technologia”
  → bold we wszystkich sekcjach DOCX
```

## Ustalenia o najwyższym priorytecie

### 1. Ścieżka Ollama dla kryteriów jest martwa w standardowej konfiguracji

`_generate_criteria_with_ollama()` odczytuje `settings.OLLAMA_HOST`:

- `backend/app/api/recommendations.py:704-709`

Konfiguracja aplikacji i `.env.example` definiują natomiast wyłącznie:

- `OLLAMA_BASE_URL` — `backend/app/core/config.py:106-109`;
- `OLLAMA_BASE_URL` — `.env.example:31-33`.

W efekcie endpointy preview/refresh kryteriów w bieżącym kontrakcie konfiguracji
nie uruchamiają Ollama i przechodzą do `_fallback_criteria_from_text()`.

Fallback:

- wykrywa ograniczoną listę technologii regexem i zapisuje ją jako must-have;
- pierwsze linie wymagań, które nie zawierają rozpoznanej technologii, zapisuje
  w całości jako `nice_skills` (`recommendations.py:752-775`).

Oznacza to, że wpisy takie jak `English B2`, `Agile`, `Scrum`, wymagany staż czy
forma współpracy B2B trafiają do tego samego pola co technologie.

Dodatkowo endpoint sprawdza obecność klucza `_source`, którego generator Ollama
nie dodaje (`recommendations.py:817,838`). Po naprawie adresu źródło nadal byłoby
błędnie raportowane w UI jako heurystyka.

### 2. Ogólne kryteria matchingowe są używane jako lista technologii

Pola `must_skills` i `nice_skills` powstały jako **structured criteria —
matching-engine input**, nie jako lista technologii:

- `backend/alembic/versions/0005_job_structured.py:7-15`.

Prompt ekstrakcji kryteriów prosi o:

- `hard requirements`;
- `preferred but optional skills`;

bez ograniczenia ich do technologii:

- `backend/app/services/llm_prompts.py:50-67`.

Backfill danych jawnie dopuszcza role i kompetencje takie jak:

- `Manual Testing`;
- `Business Analysis`;
- `Project Management`;

(`backend/scripts/backfill_job_criteria_claude.py:41-56`).

Taksonomia używana przez matching zawiera również metodyki i role, m.in. Agile,
Scrum, Kanban oraz role analityczne i managerskie:

- `backend/scripts/seed_skill_aliases.py:199-208`;
- `backend/scripts/seed_skill_aliases.py:217-263`;
- `backend/scripts/seed_skill_aliases.py:297-325`.

Generator CV nie zachowuje tej semantyki. Po odpowiedzi AI bezwarunkowo wykonuje:

```text
highlight_keywords = champion.must_have + champion.nice_to_have
```

Zob. `backend/app/services/cv_generator_b2b/standalone_service.py:1038-1047`.

Oznacza to również, że obecna implementacja boldowania obejmuje zarówno
**MUST-HAVE**, jak i **NICE-TO-HAVE**. Jeżeli reguła biznesowa mówi wyłącznie o
technologiach wymaganych, zakres powinien zostać doprecyzowany.

### 3. Prompt CV błędnie nazywa wszystkie kryteria technologiami

Prompt generatora opisuje całe listy jako:

- `MUST-HAVE TECHNOLOGIES`;
- `NICE-TO-HAVE TECHNOLOGIES`.

Zob.:

- `backend/app/services/cv_generator_b2b/prompts.py:131-150`;
- `backend/app/services/cv_generator_b2b/prompts.py:361-379`.

Jeżeli lista zawiera Agile, język, rolę albo kompetencję miękką, model otrzymuje
instrukcję, by potraktować ten element jak technologię, umieścić go prominentnie
w skills/why-points i zgłosić brak jako brak technologii.

Boldowanie nie jest jednak decyzją modelu. Po wygenerowaniu JSON backend ponownie
dodaje wszystkie surowe wpisy Championa do `highlight_keywords`, niezależnie od
odpowiedzi modelu i jego `warnings`.

### 4. Klasyfikator technologii jest heurystyczny i asymetryczny

`compile_keyword_patterns()` znajduje się w:

- `backend/app/services/cv_generator_b2b/docx_renderer.py:803-891`.

Klasyfikator wykorzystuje trzy główne mechanizmy:

1. `_KNOWN_TECH` — ręczna allowlista 249 wpisów
   (`docx_renderer.py:402-688`);
2. `_is_strong_tech_token()` — za silny sygnał uznaje m.in. dowolną cyfrę,
   uppercase acronym, camelCase albo znaki `+`, `#`, `/`, `.`
   (`docx_renderer.py:365-399`);
3. `_is_tech_token_name()` — praktycznie każdy pojedynczy wyraz zawierający
   wielką literę może zostać uznany za nazwę produktu, jeśli nie wygląda jak
   polskie słowo (`docx_renderer.py:754-770`).

To powoduje zależność od kapitalizacji: `Agile` kwalifikuje się jako technologia,
a `agile` już nie. Jednocześnie lowercase niszowej technologii niewystępującej
w allowliście zostaje odrzucony.

### 5. Generator ignoruje istniejącą taksonomię i aliasy NEXUS

Repozytorium ma już:

- modele `skills` i `skill_aliases` z polem `category` —
  `backend/app/models/skill.py:19-53`;
- loader mapy aliasów —
  `backend/app/services/skill_taxonomy_loader.py:23-39`;
- odporną normalizację różnych formatów JSONB oraz aliasów, używaną przez
  scoring — `backend/app/services/scoring_service.py:421-485`.

Renderer CV utrzymuje równolegle osobną `_KNOWN_TECH`. Dlatego scoring i
generator CV inaczej interpretują ten sam wpis, np. `Postgres`, `ReactJS`,
`K8s` lub `Microsoft Azure`.

### 6. Niezgodne legacy formaty mogą zgubić wszystkie technologie

`from_nexus_job()` zakłada, że `must_skills`/`nice_skills` są listami. Pobiera
jedynie `name`, nie zachowuje `category`, `level`, `years` i nie używa wspólnego
parsera:

- `backend/app/services/cv_generator_b2b/champion_builder.py:45-67`.

Konsekwencje:

- `{"technologies": ["Java", "AWS"]}` jest iterowane jako słownik i daje wpis
  `"technologies"`, nie `Java` i `AWS`;
- JSON zapisany jako string jest iterowany znak po znaku;
- kategoria skilla, nawet jeśli istnieje w danych, zostaje utracona.

Audit matchingowy potwierdza, że w produkcyjnych jobach występują skalarne
wartości `must_skills/nice_skills`:

- `backend/scripts/eval_matching.py:208-223`.

Scoring ma obsługę tych wariantów, generator CV — nie.

## Reprodukcja

### Reprodukcja pełnego przepływu kryteriów i matchera

Próbka:

```text
Title: Senior Java Developer
Requirements:
- Java 17
- English B2
- Agile
- Scrum
- B2B cooperation
- komunikatywność
```

Bieżący fallback zwraca w praktyce:

```text
must: Java
nice: English B2, Agile, Scrum, B2B cooperation, komunikatywność
```

Po złączeniu list obecny matcher boldowania rozpoznaje:

```text
Java, B2, Agile, Scrum, B2B
```

`komunikatywność` jest akurat odrzucana przez heurystykę polskich końcówek.
To dowodzi, że false positives powstają deterministycznie w aktualnym
pipeline, a nie losowo w modelu.

### Reprodukcja pełnego renderu DOCX

Dla:

```text
highlight_keywords = [Agile, B2B, Java, C, Jest]
tekst = "Agile, B2B, Java, C, Jest"
```

rzeczywiste runy Worda zawierają:

| Tekst | Bold |
|---|---:|
| Agile | tak — błędnie |
| B2B | tak — błędnie |
| Java | tak — poprawnie |
| C | nie — błędnie |
| Jest | nie — błędnie |

`Jest` koliduje z polskim stop-wordem `jest`, a `C` jest odrzucane przez limit
minimalnej długości terminu.

### Potwierdzone false positives

Obecna implementacja uznaje za technologie i bolduje m.in.:

- `Agile`, `Scrum`, `Kanban`, `SAFe`;
- `Leadership`, `Mentoring`, `Communication`, `Teamwork`;
- `English`, `Banking`, `Fintech`, `Hybrid`, `Remote`;
- `UX`, `UI`, `QA`, `B2B`, `SaaS`, `C1`, `B2`;
- `Analiza` i inne pojedyncze wyrazy zaczynające się wielką literą, które nie
  wpadają w niepełną heurystykę polskich końcówek;
- `min.` z wpisu `Min. 5 lat doświadczenia`;
- `kat.` z wpisu `Prawo jazdy kat. B`.

Fałszywy wzorzec jest stosowany nie tylko w sekcji technologii. Te same wzorce
działają w:

- why-points — `docx_renderer.py:1269-1275`;
- skills — `docx_renderer.py:1402-1409`;
- certyfikatach — `docx_renderer.py:1415-1423`;
- językach — `docx_renderer.py:1425-1433`;
- obowiązkach — `docx_renderer.py:1491-1493`;
- linii `Technologie:` — `docx_renderer.py:1495-1507`.

Dlatego np. `English` lub `B2` może zostać pogrubione bezpośrednio w sekcji
językowej.

### Potwierdzone false negatives i częściowe dopasowania

| Wymóg / chip | Tekst CV | Wynik |
|---|---|---|
| `C` | `C` | brak bolda |
| `R` | `R` | brak bolda |
| `Jest` | `Jest` | brak bolda — kolizja ze stop-wordem |
| `playwright` | `Playwright` | brak bolda — zależność od kapitalizacji |
| `Bash/Python` | `Bash, Python` | brak obu boldów |
| `React` | `ReactJS` | brak bolda |
| `Kubernetes` | `K8s` | brak bolda |
| `PostgreSQL` | `Postgres` | brak bolda |
| `Python` | `Pythona` / `Pythonie` | brak bolda |
| `Docker` | `Dockera` / `Dockerem` | brak bolda |
| `Kubernetes` | `Kubernetesa` | brak bolda |
| `React` | `Reacta` | brak bolda |
| `Selenium WebDriver` | identyczna nazwa | bold tylko `WebDriver` |
| `Microsoft Power BI` | identyczna nazwa | bold tylko `BI` |
| `Microsoft Azure` | identyczna nazwa | brak bolda |
| `Oracle Service Bus` | identyczna nazwa | brak bolda |
| `Jira Service Management` | identyczna nazwa | brak bolda |
| `Google Analytics 4` | identyczna nazwa | brak bolda |

Prompt AI kanonizuje część nazw (`k8s` → `Kubernetes (K8s)`, `postgres` →
`PostgreSQL`, `gitlab ci` → `GitLab CI/CD`), ale wzorce boldowania powstają z
surowego wpisu Championa. Model i matcher nie używają więc tej samej
kanonizacji.

### Znany przypadek `Bash/Python` nie trafił na main

W historii repo istnieje commit:

```text
38f1fd3 fix(cv-generator): bolduj obie technologie ze złączonego ukośnikiem
chipa (Bash/Python → Bash + Python)
```

Commit znajduje się na branchu `claude/jolly-panini-725306`, ale nie jest
przodkiem aktualnego `main`. Znany i opisany błąd nadal występuje.

Nie należy jednak bezrefleksyjnie cherry-pickować tego commita: powstał przed
późniejszą ochroną przed przeciekaniem wspólnych fragmentów nazw, np. `Apache`
z `Apache Airflow` na `Apache NiFi`. Potrzebne jest wspólne rozwiązanie oparte
na taksonomii, a nie kolejny lokalny split.

## Manual upload / Old mode

Manualny parser Profilu Championa ma dodatkowe źródła błędów:

1. rozcina MUST/NICE po każdym przecinku, średniku lub newline:
   `backend/app/services/cv_generator_b2b/champion_builder.py:200-216`;
2. nie uwzględnia przecinków wewnątrz nawiasów;
3. granice sekcji opierają się na sztywnych polskich nagłówkach, m.in.
   `3. KONTEKST`: `champion_builder.py:166-193`;
4. przy angielskim lub zmodyfikowanym szablonie NICE-TO-HAVE może połknąć dalszą
   część dokumentu i zamienić kontekst projektu lub obowiązki w keywordy.

Przykłady uszkodzenia:

```text
WCAG 2.1/2.2 (AA, AAA)
→ ["WCAG 2.1/2.2 (AA", "AAA)"]

Figma (badania, feedback i dane)
→ dwa niepełne wpisy
```

## Render i podgląd frontendowy

Podgląd nie jest przyczyną błędów:

- frontend pobiera `/api/cv-generator/generated/{id}/docx` zarówno dla podglądu,
  jak i pobrania —
  `frontend/src/components/v2/pages/CVGeneratorStandaloneV2.tsx:1097-1119`;
- endpoint odtwarza ten sam DOCX z zapisanego payloadu —
  `backend/app/api/cv_generator_b2b.py:671-710`;
- backend zapisuje bold bezpośrednio w runie Worda przez
  `run.font.bold = True` — `docx_renderer.py:921-951`;
- `docx-preview` jedynie odczytuje gotowe formatowanie Worda.

Nie ma dodatkowego matchingu Markdown/HTML ani frontendowej logiki, która
mogłaby dodawać błędne boldy.

### Ważne zachowanie zapisanych CV

Wygenerowane CV przechowuje snapshot `render_payload`, w tym ówczesne
`highlight_keywords`:

- `backend/app/services/cv_generator_b2b/standalone_service.py:1070-1077`.

Zmiana chipów must/nice w ofercie nie aktualizuje istniejącego CV. Ponowne
pobranie użyje aktualnego renderera, ale starej listy keywordów. Po poprawieniu
kryteriów CV trzeba wygenerować od nowa.

## Anti-fabrication guard nie zabezpiecza boldów

`_fabrication_warnings()` sprawdza technologie w `experience[].technologies`
oraz certyfikaty:

- `backend/app/services/cv_generator_b2b/standalone_service.py:891-925`.

Nie weryfikuje jednak `highlight_keywords`. Ponadto jest mechanizmem
ostrzegawczym — nie usuwa zakwestionowanego elementu i nie blokuje generacji.
Zmiana modelu Claude nie naprawi więc klasyfikacji boldów.

## Historia zmian potwierdza problem architektoniczny

Między 2026-06-10 a 2026-07-03 na `main` pojawiła się seria kolejnych zmian tego
samego mechanizmu, m.in.:

- boldowanie fraz Championa;
- zawężenie do realnych wymagań;
- boldowanie wszystkich wymagań;
- usuwanie generycznych słów;
- ponowne wydobywanie technologii z opisowych wymagań;
- ograniczenie do technologii, bez konceptów;
- obsługa wersjonowanej `Java 17+`;
- wielowyrazowe nazwy Microsoft;
- usunięcie przecieku `Apache` na niewymagane produkty.

To zachowanie typu whack-a-mole: poprawka konkretnego przykładu zmienia granicę
heurystyki i ujawnia kolejny przypadek. Dalsze dopisywanie wyjątków do
`_KNOWN_TECH`, `_GENERIC_WORDS` lub stop-wordów nie usunie przyczyny.

## Luki testowe

`backend/tests/test_cv_generator_b2b_pipeline.py` zawiera wiele testów
regresyjnych, ale są one dobierane głównie pod wcześniejsze pojedyncze
zgłoszenia. Brakuje pełnego kontraktu:

```text
raw Job / Champion
  → generowanie i normalizacja kryteriów
  → ChampionProfileForPrompt
  → prompt i wynik AI
  → highlight_keywords
  → regex
  → runy <w:b> w DOCX
```

Brakuje w szczególności macierzy obejmującej:

- technologie kontra metodyki, role, języki i soft skills;
- lowercase/uppercase;
- `C`, `R` i kolizję `Jest`;
- aliasy i kanonizację;
- polską fleksję;
- separatory `/`, `&`, `+`;
- pełne wielowyrazowe nazwy produktów;
- legacy formaty JSONB;
- oba tryby: New i manual upload;
- końcowe asercje `<w:b>` w pliku DOCX.

Test dotyczący UI/design sprawdza, że nie boldowane są wybrane koncepty, ale nie
umieszcza `UX` w tekście podlegającym asercji. W efekcie fałszywy wzorzec `UX`
nie powoduje niepowodzenia testu.

Frontendowe testy `frontend/src/lib/__tests__/cv-generator.test.ts` dotyczą
głównie nazwy pobieranego pliku, a nie boldowania.

## Rekomendowany kierunek naprawy

### P0 — naprawić źródło kryteriów

1. Ujednolicić `OLLAMA_HOST` / `OLLAMA_BASE_URL`.
2. Poprawnie raportować źródło kryteriów.
3. Nie zapisywać dowolnych nietechnicznych linii fallbacku jako potencjalnych
   technologii.

### P0 — wprowadzić jawny kontrakt boldowania

Najbezpieczniejszy wariant:

- każdy wymóg ma typ, np. `technology`, `tool`, `platform`, `methodology`,
  `soft_skill`, `human_language`, `role`, `certification`, `experience`, `domain`;
- generator buduje boldy wyłącznie z dozwolonych kategorii technicznych;
- alternatywnie lub dodatkowo kryterium ma jawne pole `highlight_in_cv`;
- należy jawnie ustalić, czy boldowane są tylko MUST-HAVE, czy również
  NICE-TO-HAVE.

### P1 — jedna taksonomia i jedna normalizacja

1. Użyć `skills`, `skill_aliases` i `category` również w generatorze CV.
2. Generować wzorce z nazwy kanonicznej oraz wszystkich aliasów.
3. Zachować mapę aliasów zgodną ze scoringiem i promptem AI.
4. Znormalizować i zmigrować legacy formaty `must_skills/nice_skills`.
5. Domyślnie nie boldować nierozpoznanego wpisu; pozwolić rekruterowi jawnie
   oznaczyć wyjątek.

### P1 — audytowalność

Dla każdej generacji zapisać manifest:

```text
oryginalny wpis
→ znormalizowany wpis
→ nazwa kanoniczna
→ kategoria
→ zaakceptowany/odrzucony
→ aliasy i finalny regex
```

Obecnie odrzucenie terminu jest całkowicie ciche, więc użytkownik nie odróżni
braku technologii w chipach od błędu aliasu lub klasyfikatora.

### P1 — testy end-to-end

1. Zbudować wersjonowany korpus realnych wpisów z produkcji.
2. Dla każdego wpisu określić oczekiwane tech/non-tech i aliasy.
3. Testować cały pipeline aż do runów `<w:b>` w DOCX.
4. Dodać testy dla zapisanych payloadów i obowiązku ponownej generacji.

### P2 — manual upload

Zastąpić regexowy parser Championa ustrukturyzowanym formatem. Jeżeli ma pozostać
DOCX:

- obsłużyć polskie i angielskie nagłówki;
- zachować kolejność XML paragrafów i tabel;
- rozcinać listy ze świadomością nawiasów;
- dodać testy realnych wariantów szablonu.

## Kryteria akceptacji trwałej naprawy

Naprawę można uznać za zakończoną, gdy:

1. `Agile`, `Scrum`, `Leadership`, `English B2`, `B2B` i wymagany staż nie są
   boldowane bez jawnego oznaczenia ich jako technologii.
2. `C`, `R`, `Jest`, lowercase technologie i pełne wielowyrazowe produkty są
   poprawnie rozpoznawane przez wspólną taksonomię.
3. `React`/`ReactJS`, `Kubernetes`/`K8s`, `PostgreSQL`/`Postgres` i inne aliasy
   zachowują się identycznie.
4. Polska fleksja nie powoduje niespójności między sekcjami albo prompt zawsze
   emituje dodatkową kanoniczną linię technologii objętą jednoznacznym boldem.
5. Legacy formaty JSONB są migrowane lub odrzucane walidacją.
6. UI pokazuje, które wymagania zostaną pogrubione przed generacją.
7. Test integracyjny potwierdza finalne runy `<w:b>` w DOCX.
8. Zmiana kryteriów wymusza lub jednoznacznie sugeruje ponowną generację CV.

## Weryfikacja wykonana podczas audytu

- prześledzono pełny przepływ danych od kryteriów oferty do runów DOCX;
- uruchomiono aktualne funkcje `compile_keyword_patterns()` i
  `highlight_spans()` na reprezentatywnym korpusie tech/non-tech;
- wykonano pełny render DOCX i odczytano faktyczne wartości `run.bold`;
- sprawdzono osobno frontendowy podgląd i endpoint ponownego renderu;
- przeanalizowano testy regresyjne i historię zmian Git;
- nie wprowadzono zmian do kodu aplikacji.

Pełny lokalny `pytest` nie został uruchomiony przez systemowy Python 3.9, który
nie obsługuje części składni projektu. Reprodukcje core matchera i pełnego DOCX
wykonano na dostępnym runtime Python 3.12 z rzeczywistym kodem repozytorium.

