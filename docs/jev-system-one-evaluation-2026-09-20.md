# Jev (TypeSafe AI) w Compass, Atlas i NEXUS — ocena i rekomendacje

Data: 20.09.2026 · Autor: Claude (research + odczyt kodu trzech repo + zapytania read-only do produkcji NEXUSA)

## 1. Werdykt w pięciu zdaniach

1. **Jev to nie „tańszy LLM", tylko inna klasa narzędzia**: model decyzyjny, który nie generuje tekstu. Odpowiada na typowane pytania (wybór, ocena w rubryce, tak/nie) jednym przebiegiem, ze skalibrowanym prawdopodobieństwem, w 0,1–0,5 s, za $0,042 / mln tokenów wejścia (wyjście darmowe).
2. **Nie zastąpi żadnej z naszych ekstrakcji** (odczyt CV, odczyt zamówień z PDF, wyciąganie faktów z notatek, generator CV). Te ścieżki oddają STRINGI, a Jev stringów nie oddaje. To 95% dzisiejszego wydatku na AI w NEXUSIE i większość w Atlasie.
3. **Jego miejsce to bramki, routing, weryfikacja i sędziowanie** — tam, gdzie dziś stoi regex, heurystyka wagowa, „zawsze przepuść" albo drogi model wołany tylko po to, by odpowiedzieć „tak/nie". Największa wartość nie jest w dolarach (nasze AI kosztuje ~$25/mies. poza incydentami), tylko w **latencji (15 s → 0,3 s), kalibracji (można bramkować progiem) i decyzjach, których dziś nie podejmujemy wcale, bo LLM byłby za wolny lub za drogi**.
4. **Najlepsze pierwsze wdrożenia**: Atlas — filtr leadów warstwy 2 (dziś Haiku per lead, per skan, poza rejestrem kosztów); NEXUS — weryfikacja must-have w auto-dopasowaniu (79 tys. decyzji w dry-run na heurystyce) i kategoria kompetencji (5 klas, dziś słowa kluczowe + centroid); Compass — etap 2 dopasowania kandydat↔projekt (jedyne miejsce w 3 apkach z gotowym evalem P@1/MRR/nDCG, więc A/B jest za darmo).
5. **Warunki brzegowe**: early access (waitlist; dostęp alternatywnie przez Vercel AI Gateway / Cloudflare Workers AI), hosting główny w USA i „ZDR nie ustalone" (DPA z SCC jest — trzeba podpisać i pseudonimizować stan), polski niezweryfikowany (japoński działa), model zawsze odpowiada (obowiązkowa opcja „inne"), bias pozycji opcji (88% vs 57%), benchmarki producenta nieodtworzone niezależnie. Każde wdrożenie = najpierw eval na naszych etykietach, potem tryb cienia, potem bramka po confidence z fallbackiem na dzisiejszą ścieżkę.

## 2. Czym jest Jev — fakty

| Cecha | Wartość | Źródło |
|---|---|---|
| Producent / premiera | TypeSafe AI (Diogo Almeida, ex-OpenAI), 15–16.09.2026, early access | typesafe.ai, DataCamp |
| Klasa | „System One model": brak generacji tekstu, próbkowanie równoległe, trening RLCD (RL for Calibrated Decisions) | typesafe.ai |
| Typy pytań | `choice` (≤255 opcji), `score` (rubryka ≤10 poziomów, wynik ciągły + rozkład + confidence), `noul` (tak/nie → prawdopodobieństwo, bez osobnego confidence) | docs, Langfuse |
| Wiele pytań naraz | pytania liczone równolegle i w izolacji na tym samym stanie; 13 pytań w jednym wywołaniu bez utraty jakości; grupowanie = koszt ÷12, czas ÷10 | docs, note.com |
| Cena | $0,042 / mln tokenów wejścia, wyjście $0; ~$0,0004 / decyzję w evalu; producent przyznaje, że cena może być subsydiowana | typesafe.ai, DataCamp |
| Latencja | 70–500 ms deklarowane; zmierzone 92–214 ms (MindStudio), ~0,3 s (USA zach.) | MindStudio, note.com |
| Kontekst | 32k tokenów stanu (+ pytanie), 64k na żądanie | Opper, Cloudflare |
| Benchmark producenta (4 workflowy) | Jev 67,8% / $0,0004 / 0,4 s · GPT-5.6 Terra 67,9% / $0,03 / 10 s · GPT-5.6 Sol 74,1% / $0,08 / 23 s · Opus 5 73,1% / $0,18 / 38 s; 0% błędów struktury. **Etykiety referencyjne = GPT-6 Astra + Fable 5.1, nie ground truth** | evals.typesafe.ai |
| LLM-as-judge (niezależne) | zgodność z werdyktem Fable 5.1: 91,5% za $160 / mln ocen (Fable: $33 000); DeepSeek V4.1 Flash 93,5% za $260 | Langfuse / Good Start Labs |
| Języki | japoński „działa jak jest"; polski nieprzetestowany publicznie | note.com |
| Prywatność | DPA publiczne (SCC Moduł 2, prawo irlandzkie, 72 h na zgłoszenie naruszenia, brak treningu na danych klientów); hosting główny USA; „zero data retention — nie ustalone" | typesafe.ai/legal, Opper |
| Integracje | SDK Python/JS, `POST /v1/systemone`, `langchain_typesafe.TypeSafeClassifier`, `AutoModeMiddleware` (guardrails), Vercel AI Gateway, Cloudflare Workers AI | LangChain, Cloudflare |
| Otwarte odpowiedniki | `simple-jev` (featherless: czyta logity Qwen/Gemma, współdzielony KV-cache; **prawdopodobieństwa nieskalibrowane**), `open-jev-deberta-v3-large`, `openjev` (Qwen3.5 NLI); prior art GLiNER | GitHub, HF |

**Zmierzone słabości (z niezależnych testów):**

- Brak abstencji: pytany o dział dla „godzin stołówki" bez opcji „inne" wybrał „sprzedaż" z confidence 0,31. Każde pytanie `choice` MUSI mieć opcję „inne / nie dotyczy / nie wiem".
- Bias pozycji: 88% trafności, gdy poprawna opcja jest pierwsza, 57%, gdy ostatnia (216 przypadków). W produkcji: losować kolejność opcji per wywołanie albo pytać serią `noul` zamiast jednym `choice`.
- Liczenie i rozumowanie sekwencyjne: 117/216 błędów w liczeniu znaków; słabe na długich sekwencjach. Nie pytać „ile", pytać „czy".
- „Context rot": trafność spada, gdy stan niesie dużo nieistotnego tekstu. Wycinać stan do tego, co pytanie potrzebuje (u nas: sekcja CV, nie całe CV z RODO-klauzulą).
- Brak uzasadnień: nic do audytu poza liczbą. Dla decyzji dotyczących ludzi (Compass, NEXUS) człowiek zostaje w pętli.
- Negacja obsłużona poprawnie („nie proszę o zwrot" → 3%), prosty prompt injection odparty — ale to pojedyncze testy, nie dowód odporności.

## 3. Wzorzec użycia, który obowiązuje we wszystkich trzech apkach

1. **Trzy warstwy, każda do swojego**: kod (deterministyczne reguły, słowniki, daty, kwoty) → Jev (semantyczny wybór, ocena, tak/nie) → LLM (wyłącznie generacja tekstu i ekstrakcja stringów). Jev wchodzi tam, gdzie dziś jest regex/heurystyka ALBO gdzie dziś nie ma nic, bo LLM był za drogi — a nie zamiast działającej ekstrakcji.
2. **Trzy ścieżki po confidence**: ≥ próg wysoki → działaj automatycznie; pasmo środkowe → człowiek; poniżej → dzisiejsza ścieżka (fallback). Progi ustalane na NASZYCH etykietach, nie z dokumentacji.
3. **Higiena pytań**: pytania atomowe (jeden czynnik = jedno pytanie, łączenie w kodzie); opcja „inne" w każdym `choice`; losowa kolejność opcji; stan przycięty do sekcji, o którą pytamy; instrukcja z jawnymi warunkami „prawda gdy… / fałsz gdy…" (wzorzec z docs TypeSafe).
4. **AI = dodatek, nigdy bramka bez wyjścia** (reguła z NEXUSA po 10–11.09): wyłącznik per zastosowanie, timeout 2 s, fallback = to, co działa dziś. Awaria Jev nie może zatrzymać przepływu.
5. **Eval przed wdrożeniem, cień przed przełączeniem**: każde zastosowanie ma wskazany istniejący zbiór etykiet (niżej). Kryteria: zgodność z etykietami ≥ dzisiejszej ścieżki, sprawdzenie kalibracji na naszych danych (czy 0,9 znaczy ~90%), test na polskim, test biasu pozycji (ten sam stan, opcje w odwrotnej kolejności).
6. **RODO**: podpisać DPA (SCC Moduł 2), dopisać TypeSafe do listy podprocesorów w politykach prywatności kandydatów (NEXUS) i pracowników (Compass), **pseudonimizować stan** — większość pytań nie potrzebuje imienia, e-maila ani telefonu (usuwać nagłówek CV, zostawiać treść). Decyzje dotyczące osób (odrzucenie kandydata, ocena pracownika, eskalacja) — Jev tylko podpowiada, człowiek decyduje (art. 22 RODO).
7. **Telemetria w istniejących rejestrach**: NEXUS `ai_provider_calls` (nowy `provider=typesafe` + cennik w `ai_metering._PRICES`), Atlas `ai_call_logs`, Compass `ai_assistant_logs`. Bez tego nie da się porównać kosztu ani trafności.

## 4. NEXUS

### 4.1 Stan dziś (produkcja, zapytania read-only 20.09.2026)

Koszt AI 1–15.09 (bez burstu scrapera): **~$22 łącznie** — generator CV $12, ekstrakcja notatek $4,6, mapa wymagań CV $2,9, parser Championa $2,0, reszta grosze. Burst 16–18.09: `cv_parser` 10 123 wywołań, $260, średnio 3 281 tokenów wejścia / 1 908 wyjścia / **15,6 s** na wywołanie.

Wniosek: **pieniądze nie są problemem NEXUSA; latencja i brak tanich decyzji są**. Auto-dopasowanie w dry-run zapisało 79 241 decyzji (55 575 `ineligible`, 23 650 `below_threshold`, 11 `must_gap`, 5 `dry_run`) — wszystkie z heurystyki, żadna z modelu. Poczta M365: 3 047 maili dopasowanych po nazwisku (`smart_name`, najsłabsza metoda), 1 482 po wątku, 428 ściśle, 37 bez dopasowania. Załączniki: 2 250 odrzucone regułą MIME/nazwa, 55 uznane za CV. Kolejka zamówień z maila: 90 dokumentów łącznie (36 automatycznie, 10 ręcznie, 41 odrzuconych).

### 4.2 Zastosowania — priorytetowo

| # | Powierzchnia | Dziś | Z Jev | Dane do evalu | Wartość | Wysiłek | Priorytet |
|---|---|---|---|---|---|---|---|
| N1 | **Weryfikacja must-have w auto-dopasowaniu i pełnym przeglądzie** (`auto_match_rules`, `search_dealbreaker_inputs`, polityka `review`) | must-have to często PROZA (`must_skills`), a bramka pyta o znane skille; brak dowodu = przepuść | per wymaganie `noul`: „czy CV dowodzi X na wymaganym poziomie?" + `score` seniority; 5–13 pytań w jednym wywołaniu, stan = sekcja doświadczenia CV (≤8k tokenów) | 79 tys. decyzji dry-run; `match_outcomes` (dodania do pipeline'u); dowody wymagań zweryfikowane przez rekruterów (`reviewed evidence` w eval) | wysoka: to jest to, czego Radar i C2 nie potrafią dziś powiedzieć; ~$0,03 na pełny przegląd 200-osobowej puli | średni (klient + jedno miejsce polityki) | **1** |
| N2 | **Kategoria kompetencji (5 CC)** (`cc_classifier`: 0,4 słowa kluczowe + 0,6 centroid; remis <0,10; backfill 49 tys.) | hybryda bez kalibracji, „tie" gdy blisko | jedno `choice` z 5 CC + „inne"; primary + 2 secondary z rozkładu; confidence zamiast progów 0,65/0,40 | wpisy `source='manual'` w `candidate_competence_categories` (etykiety ludzi) | średnia-wysoka: filtr listy i odznaka; backfill całej bazy ≈ 49k × 3k tokenów ≈ $6 | niski | **2** |
| N3 | **Bramka przed płatnym odczytem CV** (`/from-cv`, `BulkImportCVsV2`, załączniki M365 `is_cv_candidate_attachment`) | sito bajtów + e-mail/telefon z nagłówka (jednostronne, bez nazwiska — decyzja Artura); załączniki po MIME/nazwie | `noul` „to jest CV?", `choice` język, `choice` „ta sama osoba co [top-5 kandydatów z sita po nazwisku] / żadna" jako **druga opinia**: sito trafiło → Jev potwierdza (mniej fałszywych 409 = mniej CV obcej osoby u kogoś); sito nie trafiło, Jev ≥0,95 → flaga „możliwy duplikat" dla człowieka, NIE 409 | kohorta burstu (9 739 odczytów / 689 kandydatów), historyczne 409 | średnia: burst kosztowałby ~$4 zamiast $245, ale sito po PR #1603 już łapie ~95%; realna wartość = 2 250 odrzuconych załączników, których nikt nie sprawdził | niski | 3 |
| N4 | **Poczta M365: weryfikator dopasowania + intencja** | `smart_name` (3 047) bez weryfikacji treści; brak klasyfikacji intencji | `noul` „ten mail dotyczy kandydata X?" na dopasowaniach po nazwisku; `choice` intencja (odmowa / pytanie o stawkę / dostępność / OOO / newsletter / inne) → sygnał na tablicy i w dzwonku | `manual` / `unmatched` jako etykiety; próbka 200 maili do ręcznej oceny | średnia: pierwsza klasyfikacja intencji w NEXUSIE; ~$0,50/mies. | średni | 4 |
| N5 | **Straż przed wstrzyknięciem i treścią** (`_PROMPT_INJECTION_RE` w podsumowaniu aktywności, czat interaktywnego CV, CV do generatora) | regex PL/EN, łatwy do obejścia | `noul` „tekst zawiera instrukcje skierowane do AI?" + `noul` „zawiera dane wykraczające poza CV (stawki, notatki wewnętrzne)?" przed każdym płatnym wywołaniem | zestaw zdań z regexu + 50 przykładów adwersarialnych | średnia (bezpieczeństwo), koszt zerowy | niski | 5 |
| N6 | **Sędzia i etykieciarz do evali** (`eval_matching.py`, `weekly_eval`, końcowa kontrola CV #1602 na Lunie) | etykiety ręczne / droższy model | `score` trafności kandydat↔oferta (graded relevance) dla nDCG; pre-filtr kontroli CV: `noul` „zdanie ma pokrycie w źródle?" per zdanie, Luna tylko dla niskiego confidence | 91,5% zgodności z Fable w LLM-as-judge (Langfuse) — sprawdzić na naszym | średnia: 200× tańsze etykiety = częstsze evale | niski | 6 |
| N7 | **Jakość profilu Championa** (`ineligible_must`, `unresolved`, walidacja intake) | reguły długości, normalizator | `noul` „to jest technologia/umiejętność, nie proza?", `choice` seniority, `noul` „stawka w dokumencie to netto/h?" jako podpowiedź w oknie importu | 949 profili + `intake.unresolved` | średnia | niski | 7 |
| N8 | **Poczta zamówień: rozpoznanie klienta, `non_order`, numer spośród kandydatów** | regex + LLM; `extract_order_number_candidates` konfrontowane z rejestrem | `choice` numer zamówienia spośród kandydatów regexu (wzorzec „value extraction" z MindStudio), `noul` „to zamówienie, nie faktura/oferta?" | 90 dokumentów — za mało; zbierać | niska (wolumen 1–3/dzień) | niski | 9 |
| N9 | **Powiadomienia i routing MINDY** | reguły per typ; czat = LLM | `score` priorytet powiadomienia, `choice` intencja pytania w MINDY przed drogim modelem | logi `notifications`, `mindy_chat` | niska | niski | 10 |

**Czego NIE robić Jevem w NEXUSIE:** `cv_parser`, `cv_backfill`, `notes_extraction`, `order_parser`, `champion_profile_parse`, `cv_generator`, `candidate_summary` — to ekstrakcja lub generacja stringów. Dwa powody: Jev nie oddaje tekstu, a nasze ekstrakcje mają już wielomiesięczne kontrakty testowe (safeguards lat, dat, RODO), których Jev nie odtworzy.

### 4.3 Gdzie się wpina

- Nowy moduł `app/services/system_one_client.py` (nie przez `call_claude` — inny kształt żądania i odpowiedzi; nie ma tekstu, `stop_reason`, bloków). Ten sam wzorzec ponowień/deadline i metering (`ai_metering` z `provider="typesafe"`, cena `$0.042/M in, $0 out`).
- Rejestr `ai_models.py` dostaje osobną klasę wpisu (nie `ModelChoice` chatowy): `AIFeatureKey.match_requirement_check`, `cc_classify`, `cv_gate`, `mail_intent`, `injection_guard` — każdy z własnym wyłącznikiem, jak dziś.
- Kolejność w pipeline: N3 przed `parse_cv`; N1 w `search_dealbreaker_inputs` (jedno miejsce polityki — CLAUDE.md), N2 w `apply_candidate_cc_scores` (jedyne źródło zapisu CC).
- Stan wysyłany do TypeSafe: bez nagłówka CV (imię, kontakt), bez notatek wewnętrznych, bez stawek; ID kandydata zostaje po naszej stronie.

## 5. Atlas (lead-gen)

### 5.1 Stan dziś (z odczytu kodu)

Atlas ma najwięcej klasyfikacji w 3 apkach i najmniej kontroli nad nimi: filtr leadów warstwy 2 (`data_sources/ai_filter.py`) woła Haiku **per lead, per skan**, przez SDK z pominięciem `AIService`, więc **nie trafia do `ai_call_logs`** — koszt tej najgorętszej ścieżki jest nieznany. Scoring reguł (690 + 1 154 linii stałych) miesza się 50/50 z oceną AI. Silnik reguł ma 5% losowego holdoutu i dziennik `rule_executions` — gotowa infrastruktura do trybu cienia. Osiem modułów AI (`ai_categorizer`, `ai_deduplicator`, `ai_scorer`, `ai_extractor`, `ai_contact_finder`, `ai_competitor_detector`, `ai_learning`, `signal_matcher`) jest napisanych i **nigdzie nie podpiętych**. Brak jakiegokolwiek evalu klasyfikatorów.

### 5.2 Zastosowania — priorytetowo

| # | Powierzchnia | Dziś | Z Jev | Dane do evalu | Wartość | Wysiłek | Priorytet |
|---|---|---|---|---|---|---|---|
| A1 | **Filtr leadów warstwy 2** (`ai_filter.py`: verdict / pillar / intent / confidence) | Haiku per lead per skan, poza rejestrem kosztów, confidence z promptu (nieskalibrowane) | `choice` verdict, `choice` filar (4 + „inne"), `choice` intencja, `score` pilność — jedno wywołanie, ~200 ms; skalibrowane confidence zamiast liczby z promptu; 50/50 blend z regułami staje się bramką po confidence | `lead_feedback` (opinie użytkowników), dziennik Haiku jako etykiety w cieniu, 5% holdout silnika reguł | **najwyższa w 3 apkach**: największy wolumen, ścieżka bez rejestru, czas skanu ÷50 | średni | **1** |
| A2 | **Przetargi: prefiltr trafności** (`tenders/ai_matcher.py` na Sonnecie per przetarg; przed nim `business_filters`, taksonomia CPV, prefiltr Voyage) | Sonnet ocenia każdy przetarg, który przeszedł tanie reguły | `score` trafności per filar (4 pytania) między prefiltrem Voyage a Sonnetem; Sonnet tylko dla `score` ≥ próg lub confidence niskiego; SWZ parser (ekstrakcja) zostaje na Haiku | `tender_min_ai_score`, historyczne oceny Sonneta jako etykiety | wysoka: Sonnet na przetargach to najdroższe wywołanie Atlasu per sztuka | niski | **2** |
| A3 | **Posty LinkedIn** (`ai_post_analyzer`: konkurent / TOP22 / kwalifikacja) i **tagowanie leadów** (`linkedin_lead_tagger`, 3–5 tagów) | AIService per post w cronach `account_monitor`, `competitor_monitor` | `choice` typ postu, `noul` sygnał zakupowy, `score` siła; tagi jako seria `noul` po STAŁEJ taksonomii (Jev nie wymyśli nowego tagu — i dobrze: taksonomia zamknięta = raporty spójne) | posty z ręczną oceną w `linkedin_leads` | średnia-wysoka | niski | 3 |
| A4 | **„Czy nazwa firmy to osoba?"** (`lead_company_extractor.py:323`, Haiku) | Haiku per lead | `noul` + `choice` typ podmiotu (firma / osoba / agencja / inne) — pytanie idealnie „System One" | logi Haiku | średnia, minimalny wysiłek | trywialny | 4 |
| A5 | **Dopasowanie transkryptu Fireflies → deal** (`fireflies_ai_matcher`, Haiku) i **maile MS Graph → kontakt/deal** (dziś tylko dokładny e-mail, bez fuzzy) | LLM wybiera deal; maile tylko po adresie | `choice` deal spośród kandydatów (stan = transkrypt ≤32k) + „żaden"; dla maili `noul` „ten mail dotyczy deala X?" jako bezpieczne poszerzenie poza dokładny adres | dopasowania ręczne | średnia; latencja webhooka ÷20 | niski | 5 |
| A6 | **Sygnały prasowe** (`press_v2_*`: enrichment = podsumowanie, dedup 2-etapowy w trybie cienia) | podsumowanie Haiku (zostaje), dedup fingerprint + pgvector | `choice` typ sygnału / `score` istotność dla TOP22 przed drogim wzbogaceniem; dla par z pgvector `noul` „to samo wydarzenie?" → precyzja dedupu mierzona, nie zgadywana | `dedup_shadow_log` | średnia | niski | 6 |
| A7 | **Odpowiedzi na outreach** (MS Graph mail) | brak klasyfikacji | `choice` zainteresowany / nie teraz / nie / OOO / odbicie / przekierowanie + `score` sentyment → kolejka handlowca | próbka 300 odpowiedzi | wysoka biznesowo, jeśli outreach idzie przez Graph | średni | 7 |
| A8 | **Czat NL→filtry** (`chat_service.py`, 1 119 linii) | AIService wykrywa intencję i generuje odpowiedź | `choice` intencja + `choice` encja przed LLM; LLM tylko generuje odpowiedź | logi czatu | średnia (latencja UI) | niski | 8 |
| A9 | **Taksonomia stanowisk** (`contact_taxonomy.py`, regex tytuł → seniority/dział), **klasyfikator chmury** (`cloud_classifier.py`) | regex; heurystyka DNS | `choice` seniority / dział jako fallback dla tytułów, których regex nie zna; chmura zostaje na DNS (deterministyczne) | kontakty z ręczną korektą | niska-średnia | trywialny | 9 |
| A10 | **Uśpione moduły `ai_categorizer` / `ai_deduplicator`** | napisane, niepodpięte | nie wskrzeszać jako prompty Haiku; ich semantyka (kategoria firmy, „ta sama firma?") to pytania Jev — przepisać cieńsze | `duplicate_finder` (NIP → nazwa) | średnia; sprzątanie długu | niski | 10 |

**Warunek wstępny A0**: zanim cokolwiek, doprowadzić `ai_filter.py`, `press_*`, `swz_parser`, `fireflies_ai_matcher` do `ai_call_logs` (dziś omijają jedyny rejestr) i dać `AIService` nadpisanie modelu per wywołanie. Bez tego nie da się zmierzyć, ile A1 oszczędza — a A1 to główny argument.

**Czego NIE robić Jevem w Atlasie:** parser SWZ (ekstrakcja ~30k znaków), wzbogacanie prasy (podsumowania), narracja raportu CEO, generowanie odpowiedzi w czacie, parsowanie feedbacku na reguły (`learning.py` — tam poprawić przestarzały ID `claude-3-haiku-20240307`).

## 6. Compass (HR)

### 6.1 Stan dziś (z odczytu kodu)

Najmniejsza powierzchnia AI: dwa wywołania produkcyjne (ekstrakcja z CV przy uploadzie, Haiku przez `lib/ai/llm.ts`), embeddingi Voyage, pgvector kandydat↔projekt. Zero rozliczania kosztów, zero flag AI. Za to **jedyny w 3 apkach eval z bramką regresji**: `scripts/eval_matching.ts` (P@1 / R@5 / MRR / nDCG@5 vs `eval-baseline.json`, `exit 1` przy spadku >2 pp). Automatyczny import maili do skrzynki wsparcia **usunięto** (Faza 44) po tym, jak heurystyka wątków założyła 178 zgłoszeń w dwa dni — dokładnie klasa błędu, do której Jev jest stworzony. Pozycje monitora prawnego pisze zewnętrzny pipeline AI; Compass tylko je przegląda.

### 6.2 Zastosowania — priorytetowo

| # | Powierzchnia | Dziś | Z Jev | Dane do evalu | Wartość | Wysiłek | Priorytet |
|---|---|---|---|---|---|---|---|
| C1 | **Etap 2 dopasowania kandydat↔projekt** (Voyage → batch Claude) | Claude ocenia partie par | `score` dopasowania + `noul` per `required_skills` projektu; wynik = kombinacja w kodzie | **`eval_matching.ts` — gotowy A/B**: podmienić etap 2, odpalić `npm run test:eval`, porównać z baseline | wysoka: jedyny pomiar od ręki; latencja | niski | **1** |
| C2 | **Skrzynka wsparcia / Compass Assist** (`support_tickets`, `compass_assist_tickets`, `_knowledge`) | routing ręczny; auto-ingest maili wyłączony po incydencie 178 zgłoszeń | `choice` „ten mail to: odpowiedź w wątku [lista otwartych] / nowe zgłoszenie / spam / OOO" — z confidence ≥0,9 automat, niżej kolejka; `choice` kategoria, `score` pilność, `choice` artykuł bazy wiedzy do podpowiedzi | 178 błędnych zgłoszeń z Fazy 44 jako zbiór negatywny; historyczne bilety | wysoka: przywraca auto-ingest bez powtórki incydentu | średni | **2** |
| C3 | **Zdrowie konsultanta** (`contractor_pulse_responses`, `contractor_check_ins`, `contractor_client_feedback`, `health-snapshot.ts` zielony/bursztyn/czerwony) | rollup z pól strukturalnych; wolny tekst nieczytany | `score` ryzyko odejścia / niezadowolenia z wolnego tekstu pulsu i check-inu, `choice` temat (obciążenie, klient, wynagrodzenie, rozwój, inne) → wchodzi do rollupu jako sygnał, nie werdykt | historia `contractor_health_status_history` vs późniejsze `exit_cases` | wysoka biznesowo (retencja) | średni | 3 |
| C4 | **Monitor prawny** (`legal_monitor_items`, `alert-selection.ts` red/ops) | reguły wyboru alertów na pozycjach z zewnętrznego AI | druga opinia: `noul` „dotyczy naszych umów B2B/obsady?", `score` istotność, `choice` adresat (red / ops / nikt) — mniej pozycji do ręcznego przeglądu | decyzje recenzentów w `legal_monitor_runs` | średnia | niski | 4 |
| C5 | **Klasyfikacja dokumentów przy uploadzie** (`app_documents`, `user_contract_documents`, indeksowanie `ai_document_indexing`) | typ wybiera człowiek; indeksowanie bez kontroli | `choice` typ (umowa / aneks / NDA / faktura / CV / zaświadczenie / inne), `noul` „zawiera dane wrażliwe (PESEL, zdrowie)?" PRZED indeksowaniem do asystenta | metadane istniejących dokumentów | średnia (RODO) | niski | 5 |
| C6 | **Wywiady wyjściowe i onboarding** (`exit_interviews`, `contractor_exit_interviews`, `onboarding_cases`) | tekst czytany ręcznie | `choice` przyczyna odejścia z zamkniętej taksonomii (spójność z `termination_reason` w NEXUSIE), `score` polecenie pracodawcy | istniejące wywiady | średnia (analityka odejść w Insights NEXUSA) | niski | 6 |
| C7 | **Sygnały sprzedażowe od konsultantów** (`sales_signals` → Atlas `compass_signal_poll`) | eksport bez oceny | `choice` typ sygnału, `score` siła — przed wysłaniem do Atlasu, żeby Atlas nie płacił za klasyfikację drugi raz | feedback Atlasu (`status push back`) | średnia | trywialny | 7 |

**Czego NIE robić Jevem w Compassie:** ekstrakcja z CV (imię, skille, klienci, bio — stringi), dopasowanie tożsamości kontraktor↔NEXUS (celowo tylko po e-mailu — ryzyko błędnego scalenia PII, nie dokładać „inteligencji"), decyzje kadrowe (urlopy, oceny okresowe, wypowiedzenia) — art. 22 RODO, człowiek decyduje.

## 7. Ryzyka i jak je domykamy

| Ryzyko | Skutek | Domknięcie |
|---|---|---|
| Early access, cena subsydiowana, jeden dostawca | znika / drożeje | cienki klient z interfejsem „stan + pytania → rozkłady"; zapasowa implementacja `simple-jev` na własnym Qwen/Gemma (ta sama sygnatura, gorsza kalibracja) |
| Hosting USA, ZDR „nie ustalone" | dane kandydatów/pracowników poza EOG | DPA + SCC, pseudonimizacja stanu, lista podprocesorów; najpierw zastosowania na danych firm (Atlas), potem na osobach |
| Polski niezweryfikowany | cicha utrata jakości | eval na polskich etykietach jako bramka wejścia; porównanie tego samego zbioru PL vs EN (przetłumaczonego) |
| Bias pozycji, brak abstencji | pewne błędne odpowiedzi | opcja „inne" zawsze; losowanie kolejności; test symetrii na 100 przypadkach; serie `noul` zamiast dużych `choice` |
| Brak uzasadnień | nie da się wyjaśnić decyzji o osobie | Jev = sygnał, człowiek = decyzja tam, gdzie dotyczy ludzi; dla niskiego confidence eskalacja do LLM z uzasadnieniem |
| Benchmarki producenta vs etykiety z dużych modeli | trafność niższa niż reklamowana | nie ufać liczbom; mierzyć na naszych etykietach (wskazane przy każdym zastosowaniu) |
| Context rot na długim stanie | trafność spada na całych CV / transkryptach | przycinać stan do sekcji; limit 24k tokenów w kliencie |

## 8. Plan wdrożenia (6 tygodni, bez blokowania bieżących prac)

**Tydzień 0–1 — dostęp i pomiar.** Waitlist TypeSafe + równolegle Vercel AI Gateway ($15 kredytu ≈ 1 mln klasyfikacji) do evalu; podpisanie DPA. Wspólny cienki klient (Python dla NEXUS/Atlas, TS dla Compass): wyłącznik, timeout 2 s, losowanie opcji, opcja „inne", metering do istniejących rejestrów. Atlas A0 (rejestr kosztów `ai_filter`). Trzy evale offline: NEXUS N2 na etykietach `manual`, Atlas A1 w cieniu Haiku na 2 000 leadów, Compass C1 przez `eval_matching.ts`. Test PL/EN i test biasu pozycji na każdym.

**Tydzień 2–3 — cień.** NEXUS N1 dopisany do dry-run auto-dopasowania (kolumna „Jev mówi" w `candidate_auto_match_log`), N2 równolegle z hybrydą (porównanie zgodności z ludźmi); Atlas A1 na 5% holdoucie silnika reguł + A4; Compass C1 za flagą.

**Tydzień 4–6 — przełączenie z bramką.** Tam, gdzie cień wygrał: automat ≥ próg, człowiek w paśmie, fallback poniżej. Druga fala: N3, N5, A2, A3, C2 (przywrócenie auto-ingestu maili wsparcia).

**Koszt**: przy dzisiejszych wolumenach łącznie < $20/mies. na 3 apki (Atlas A1 nieznany do czasu A0). Wysiłek: ~6–8 dni inżynierskich na fundament + 1–3 dni na zastosowanie.

**Kryteria sukcesu**: N1 — trafność `must_gap` vs dowody rekruterów ≥ 85%; N2 — zgodność z `manual` ≥ hybrydy dziś; A1 — zgodność z Haiku ≥ 90% przy czasie skanu ÷10 i koszcie widocznym w rejestrze; C1 — nDCG@5 nie spada > 2 pp przy latencji ÷20.

## 9. Źródła

- TypeSafe AI — [Introducing System One Models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) · [docs](https://docs.typesafe.ai) · [evals](https://evals.typesafe.ai) · [DPA](https://typesafe.ai/legal/data-processing)
- LangChain — [Building a harness with Jev](https://www.langchain.com/blog/building-a-harness-with-jev)
- Langfuse — [Using TypeSafe's Jev for evals](https://langfuse.com/blog/2026-09-18-using-typesafes-jev-for-evals)
- DataCamp — [Jev: TypeSafe's System One Model](https://www.datacamp.com/blog/system-one-models-jev)
- MindStudio — [Jev AI Tested](https://www.mindstudio.ai/blog/jev-system-one-model-classification)
- Latent Space — [AINews: Jev](https://www.latent.space/p/ainews-jev-a-system-one-model-that)
- note.com (masa_wunder) — [Deep dive: Jev](https://note.com/masa_wunder/n/ne5540ae961f4) (bias pozycji, japoński, grupowanie pytań)
- Sam Witteveen — [Jev - The Ultimate Classification Model?](https://www.youtube.com/watch?v=X117w2Rark8) · [omówienie daily.dev](https://daily.dev/posts/jev---the-ultimate-classification-model--adcdu4y6u)
- Cloudflare — [Jev (typesafe)](https://developers.cloudflare.com/ai/models/typesafe/jev/) · Opper — [Jev 1.13](https://opper.ai/typesafe/jev-1-13-0)
- Otwarte odpowiedniki — [simple-jev](https://github.com/featherless-ai/simple-jev) · [open-jev-deberta-v3-large](https://huggingface.co/com-kotobalabs/open-jev-deberta-v3-large) · [openjev](https://huggingface.co/AlexWortega/openjev) · [HN: open-sourced jev architecture](https://news.ycombinator.com/item?id=49736660)
