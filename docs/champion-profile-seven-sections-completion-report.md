# Profil Championa — przebudowa na siedem sekcji (09.2026)

Szablon skrócony z rozlanego dokumentu do siedmiu sekcji. Powód podany przez
Artura wprost: **80% profilu Championa to szum** — Delivery Lead wypełnia dużo,
a rekruter i tak czyta trzy rzeczy.

Nowa agenda:

| # | Sekcja | Skąd się bierze |
|---|---|---|
| 1 | Podstawowe informacje | `basics` + 7 pól, które leżały płasko na wierzchu dokumentu |
| 2 | Co wpisać (search) | dawne `sourcing`, przeformułowane z „planu" na „zapytanie" |
| 3 | Stack technologiczny | **nowa** — strukturalna lista MUST/NICE |
| 4 | O projekcie | `project_context.about` (max 2 zdania) + `responsibilities` |
| 5 | Pytania screeningowe | bez zmian |
| 6 | O kliencie | `selling_points` + `internal_consultant_insight` + `historical_client_questions` + `client_standards` + `sectors` |
| 7 | Dokumenty | **nowa** — nazwa + link do SharePointa |

Weryfikacja dwustronna, briefing DL i rekomendowane wyszukiwania **nie są
sekcjami** — mają własne endpointy, są server-stamped i zwykły zapis profilu ich
nie dotyka (decyzja produktowa).

## Dlaczego skrócenie prozy nie zepsuło dopasowań

Odruchowe „skróćmy O projekcie do 2 zdań" byłoby **regresem retrievalu**.
Do 09.2026 jedynym maszynowym sygnałem wymagań dla oferty z Championem był
`_extract_skills_from_champion`: regex po prozie, szukający 153 kanonicznych
skilli i 277 aliasów. Im mniej tekstu, tym mniej trafień — a Champion ma
zmierzony wpływ na jakość (P@5 +67%, R@20n +87%, pomiar 15.08).

Sekcja 3 usuwa zgadywanie. `_extract_skills_from_champion` dostał **Tier 0**,
który zwraca `stack.must` wprost i w ogóle nie dotyka regexa. Dodatkowo
`PUT .../champion-profile` synchronizuje stack do `Job.must_skills`/`nice_skills`
— kolumn, które wygrywają w scoringu, w kafelkach interaktywnego CV
(`requirement_map`) i w filtrach wyszukiwarki, a są puste na ~88% ofert.

**Te dwie zmiany muszą iść razem.** Skrócenie prozy bez wypełnionej sekcji 3 to
mniej sygnału przy tej samej mechanice.

## Co wyszło przy okazji: zapis z UI kasował 12 z 16 pól

Nie hipoteza — uruchomiony kod. `ChampionProfile` nie deklarowało kluczy
zapisywanych przez parser dokumentu, a Pydantic z domyślnym `extra="ignore"`
wyrzucał je przy `model_dump()`. Pierwszy zapis z edytora niszczył m.in.:

* `rate_value` — twardy sufit stawki w `dealbreaker_filters` (bez marginesu, z automatu),
* `seniority_min_years` — kara seniority, zmierzona +4% P@5 (17.08),
* `disqualifiers`, `client_standards` (w tym język CV per klient), `sectors`,
  `role_name`, `work_mode`, `start_date`, `contract_length`, `rate_raw`.

Objaw był **niewidoczny**: profil dalej się otwierał, tylko dwa filtry cicho
przestawały działać. Nowy schemat zna wszystkie te pola, a handler dodatkowo
scala payload NA zapisanym profilu.

## Migracja: leniwa, nie wsadowa

949 ofert niesie stary kształt (import 08.2026, 1095 plików, parser v3).
Migracja dzieje się **przy odczycie** (`model_validator(mode="before")`), a nowy
kształt zapisuje się przy pierwszym zapisie danej oferty. Jednorazowe przepisanie
JSONB odpada: jest odwracalne tylko z kopii, której off-site nie mamy.

Kolejność w `PUT` jest load-bearing: **najpierw normalizacja starego profilu,
potem nałożenie payloadu**. Migracja uzupełnia PUSTE pole nowej sekcji wartością
ze starego klucza — to jej sens; scalanie wprost na surowym profilu sprawiłoby,
że wyczyszczenie frazy w edytorze nigdy by się nie zapisało.

## Wektory 949 ofert nie drgnęły

`champion_view.embedding_parts` jest **celowo węższe** niż `narrative_parts`:
dla starego profilu zwraca dokładnie `about` + `responsibilities` +
`selling_points`, czyli bit w bit to samo co przed przebudową. Indeks nie wymaga
przeliczenia, a przebudowa formularza nie miesza się w pomiarze ze zmianą
retrievalu. Rozszerzenie tego zakresu to osobna zmiana z własnym A/B — pilnuje
tego `test_embedding_text_for_legacy_profile_is_unchanged`.

## Publiczna karta Championa: wąska projekcja

Endpoint `/api/public/champion-card/{token}` zwracał **cały** profil, więc każdy
z linkiem miał w JSON-ie naszą stawkę dla kandydata, firmy docelowe,
dyskwalifikatory i reguły priorytetu klienta — niewidoczne na ekranie, ale obecne
w odpowiedzi, a odbiorcą linku jest strona trzecia. Teraz idzie whitelista.

## Luka, którą złapał dopiero prawdziwy parser

Test kontraktowy wzoru sprawdzał początkowo wyłącznie **nagłówki sekcji** — i
przeszedł na zielono. Dopiero puszczenie wygenerowanego `.docx` przez faktyczny
`parse_champion_from_docx_bytes` pokazało, że etykieta pola „Insight od
**naszego** konsultanta u klienta" nie pasuje do wzorca `INSIGHT OD KONSULTANTA`,
więc treść tego pola cicho nie trafiałaby do promptu generatora CV.

Wzorzec poszerzony o `(?:NASZEGO\s+)?`, a test rozbity na dwa: osobno nagłówki
sekcji, osobno **etykiety pól treściowych** (`CONTENT_FIELD_LABELS` eksportowane
z generatora). Drugi test sprawdza dopasowanie wyłącznie do wzorców
TREŚCIOWYCH — wzorzec graniczny tylko ucina sekcję, więc trafienie w niego nie
znaczy, że treść gdziekolwiek trafi.

Potwierdzenie na wypełnionym dokumencie napisanym po nowemu: parser wyciąga
MUST (`Java, Spring Boot, Kafka`), NICE (`Kubernetes, AWS`), obowiązki,
screening, insight konsultanta i historyczne pytania klienta.

**Lekcja:** replika wyrażenia regularnego w teście nie jest testem parsera.

## Zmienione pliki

**Backend (17):** `schemas/champion.py` (nowy kształt + migracja), **nowy**
`services/champion_view.py` (warstwa odczytu obu kształtów),
`services/champion_profile_ingest.py` (prompt v4 + `build_champion_dict`),
`services/scoring_service.py` (Tier 0, stawka, seniority),
`services/canonical_text.py`, `services/embedding_service.py`,
`services/match_justification_service.py`, `services/champion_draft_service.py`,
`services/llm_prompts.py` (3 kształty promptów),
`services/champion_profile_events.py`, `schemas/champion_suggestion.py`,
`services/cv_generator_b2b/champion_builder.py` (+6 wzorców nagłówków),
`services/cv_generator_b2b/standalone_service.py`, `api/jobs.py`,
`api/talent_radar.py`, `api/public_share.py`, **nowy**
`scripts/generate_champion_template.py`.

**Frontend (6):** `components/ChampionProfileEditor.tsx` (4 sekcje → 7),
`lib/api.ts` (typy), `components/ChampionProfileSuggestionReview.tsx`,
`app/share/champion-card/[token]/page.tsx`, `middleware.ts`, **nowy**
`app/preview/champion-profile/page.tsx` (harness designu).

**Testy:** **nowy** `test_champion_template_agenda.py` (22 testy),
zaktualizowane `test_champion_ai_intake.py`, `test_champion_profile_ingest.py`,
`test_champion_historical_jobs.py`.

## Weryfikacja

* backend, obszar Championa: **218 passed** (2 pre-existing faile CloudTalk HMAC,
  potwierdzone na `HEAD` w osobnym worktree — nie regresja);
* scoring / generator CV / Talent Radar / dealbreakery / tekst kanoniczny /
  publiczna powierzchnia: **346 passed, 0 failed**;
* `test_champion_template_agenda.py`: **22 passed**;
* frontend: **2090 passed / 222 plików**, `tsc --noEmit` czysty;
* `ruff check app/` i `ruff format --check app/`: czyste;
* wzór Word przechodzi przez parser CV (test kontraktowy czyta tytuły sekcji
  wprost z generatora);
* edytor obejrzany w przeglądarce na `/preview/champion-profile` — obie karty
  renderują siedem sekcji, profil w starym kształcie ma podniesione pola
  (stawka 122.5, frazy z `sourcing`, insight konsultanta), nowy pokazuje stack
  jako chipy i 2 dokumenty.

## Wzory Word na SharePoincie — podmienione (01.09.2026)

Wszystkie **15** plików w
`/sites/B2B_ALL/Shared Documents/02_Rekrutacja i HR/Wzory/Profil Championa/`
(ogólny) i `.../Profil_Championa_per_Klient/` (14 klienckich) zastąpiono wersją
7-sekcyjną przez SharePoint REST (`Files/add(overwrite=true)`).

**Najpierw przeczytałem stare wzory, dopiero potem je nadpisałem** — i dobrze,
bo wzory per klient niosły wiedzę, której nie ma nigdzie indziej: KPI czasu na
kandydata (Nordea 5 dni roboczych, PFRON 10), konwencję nazwy pliku CV
(`ENERGA_Nazwa projektu_Stanowisko_Imię i Nazwisko`), język CV (Nordea tylko
angielski, PFRON tylko polski), opis klienta i listy wymaganych dokumentów wraz
z linkami do KRK. Nadpisanie ich generykiem skasowałoby to bezpowrotnie.

Ta treść jest teraz w repo: `scripts/champion_template_clients.json`, wstrzykiwana
do sekcji 6 i 7 przy generowaniu. Weryfikacja programowa: wszystkie bloki treści
klienckiej odnalezione w wygenerowanych plikach (0 braków na 14 klientach).

Zaskoczenie: wzory per klient **już miały** sekcje „INFORMACJA O KLIENCIE",
„STANDARDY REKRUTACJI KLIENTA" i „WYMAGANE DOKUMENTY". Nowa agenda w dużej
mierze formalizuje to, co delivery robiło u siebie, i dokłada dwie sekcje, których
nie było nigdzie: **„Co wpisać (search)"** i **„Stack technologiczny"**.

Bezpieczeństwo operacji: biblioteka ma włączone wersjonowanie (limit 500, bez
wymuszonego checkoutu), więc każdy plik dostał nową wersję major, a poprzednia
została w historii — cofnięcie to „Przywróć" na wersji.

Weryfikacja end-to-end po wgraniu: trzy pliki pobrane Z POWROTEM z SharePointa
(ogólny, Nordea, ENERGA, PFRON) mają siedem sekcji, komplet treści klienckiej,
a `extract_document_text` + `parse_champion_from_docx_bytes` NEXUSA czytają je
bez błędu.

## Czego NIE zrobiłem

Do rozważenia osobno (świadomie poza zakresem):

* **A/B na zamrożonym zestawie 50 ofert** przed uznaniem, że sekcja 3 poprawia
  ranking. Kod jej nie pogarsza (stary profil czyta się identycznie), ale zysk
  z Tier 0 zobaczymy dopiero, gdy Delivery Leadowie zaczną wypełniać stack.
* **Backfill sekcji 3 dla 949 istniejących ofert** — parser v4 wyciąga stack
  z dokumentu, ale `ingest_parsed_profile` pisze profil tylko na pusty. Ponowne
  przetworzenie wymaga osobnej decyzji i kwoty AI.
