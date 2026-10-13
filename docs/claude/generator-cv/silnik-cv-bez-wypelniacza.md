# Silnik CV bez wypełniacza (13.10.2026, D1–D3)
<!-- indeks: punkt „Posiada kluczowe technologie…” usunięty, pytanie screeningu ≠ fakt, strażnik terminów z pytań i wymagań, branża tylko ze źródła, nagłówek = nazwa roli od klienta bez tłumaczenia (`cv_role_title`), lata bez nadpisywania stażem całej kariery, notatki bez stawek, dostępności, transkryptów i prepów, kontrola AI nie chowa zastrzeżeń -->

Zespół zgłaszał, że generator „wpisuje głupoty”. Pomiar produkcji z 13.10.2026
(30 dni, 759 CV) pokazał przyczyny w prompcie i w kodzie, nie w modelu:
punkt „Posiada kluczowe technologie wymagane na stanowisku” w 376 z 565 CV
„Pod rekrutację”, zgadnięta branża w 471 CV, 22 CV z liczbą lat zepsutą przez
kod („4.4 years”), umiejętności wzięte z treści pytań screeningu
(„OpenTelemetry”) i z nice-to-have Championa („Kafka Connect SMT”), odpowiedzi
ze screeningu wklejone jako obowiązki roli. Makiety i decyzje:
https://claude.ai/artifact/BZZRshjBDC4CMEGGP6m4Wr

Dotyczy ścieżki produkcyjnej `legacy_v7` (domyślnej). Kod v10 bez zmian.

- **Bez punktu wyliczającego wymagania.** Prompt (`legacy_v7/prompts.py`) nie
  każe już dodawać „Posiada kluczowe technologie…” — zakazuje go. Must-have
  w „Dlaczego nasz kandydat” tylko jako zwykły fakt z doświadczenia. Ton
  why_points rzeczowy we wszystkich trybach (reguła „marketingowa
  i atrakcyjna” zniknęła). Technologie roli tylko z tej roli w CV albo
  z odpowiedzi wskazującej tę firmę; wymagania klienta nie są powodem
  dopisania technologii.
- **Pytanie ≠ fakt (D3).** Linie `P:` w notatkach (`_format_candidate_answers`)
  to pytania rekrutera. Faktem jest tylko twierdząca odpowiedź; przeczenie
  usuwa rzecz z CV (bez „podstawowa znajomość”). Fakt z rozmowy trafia do
  obowiązków konkretnej roli tylko wtedy, gdy odpowiedź nazywa jej firmę;
  inaczej do umiejętności i „Dlaczego nasz kandydat”.
- **Strażnik w kodzie, nie tylko prośba w prompcie:**
  `legacy_v7._helpers.strip_unsupported_terms` (w `pipeline.py` po poprawce
  lat, przed bezpiecznikami, kontrolą AI i migawką). Usuwa z technologii ról
  i umiejętności termin, którego nie ma w CV ani w odpowiedziach (dopasowanie
  luźne: rdzeń słowa, „REST API” ↔ „RESTful APIs”, „Grafana” ↔ „Grafany”,
  „Java” ↔ „Javie”, alternatywa w nawiasie), a którego wszystkie słowa stoją
  w pytaniach albo w must/nice Championa. Słowa dostawcy i przyrostki nie
  rozstrzygają („Apache Kafka” = „Kafka”, „Vue.js” = „Vue”, „GitLab CI/CD”
  = „GitLab”, `_GENERIC_TERM_TOKENS`), a inny zapis tej samej technologii
  się liczy („k8s”, „JS”, „NodeJS”, „MS SQL”, „dotnet”, `_TERM_ALIASES`) —
  kandydat zwykle ma dokładnie technologie z wymagań, a model normalizuje
  pisownię. Wątpliwość = termin zostaje; braki pokazuje potem QC.
  Umiejętności dzielone po przecinkach poza nawiasami („AWS (EC2, S3)” to
  jedna pozycja). Pozycja z dopiskiem o braku doświadczenia znika; dopisek
  o braku doświadczenia w czymś innym („Python (bez praktycznego
  doświadczenia w ML)”) znika sam, pozycja zostaje. Każde usunięcie = uwaga
  „WERYFIKUJ: usunięto…”. Pytanie z listą w kilku liniach jest jedną linią
  `P:`, żeby „- OpenTelemetry” z pytania nie wyglądało na odpowiedź.
  Bezpieczniki (`_fabrication_warnings`) i kontrola AI dostają notatki BEZ
  linii pytań (`screening_text_without_questions`).
- **Branża tylko ze źródła (D1).** Schemat promptu: branża tylko, gdy CV ją
  opisuje; brak = pusty string. `_normalize_candidate_data` nie wpisuje już
  „IT”; blind drukuje wtedy samo „Firma”.
- **Nagłówek = nazwa roli od klienta (D2).**
  `job_working_title.cv_role_title(title, client_reference, client_names)`
  zdejmuje prefiks klienta (`job_public_profile._strip_client_prefix`), numer
  zapytania (`_strip_reference`), numery w nawiasie („(51234)”, „(ITVM-5894)”),
  RITM/REQ/Pep, końcówki `_PKN…`, „x1 … Zamówienie 18”, „- 3.iteracja”,
  „(dodatkowy profil)”, „- … project”, kraj i znane miasta na początku
  („Poland - Warsaw/Gdansk”) i kody projektu z separatorem („PRJ 4412 -”,
  „BCCM RRP: SP1”, „PL-EBSD-”). Nie tłumaczy i nie rusza seniority ani
  wielkości liter nazwy. Zostają: „(K8s)”, certyfikaty „(PL-300)”,
  „(ISO 27001)”, „ISO 27001 Auditor”, „UI-UX Designer”, technologia z cyfrą
  bez separatora („MS365 Administrator”, „DB2 Administrator”), jeden skrót
  z dwukropkiem („SQL: Administrator”), „iOS Developer”, „dbt Engineer”.
  Gdy rekruter zostawi w polu „Stanowisko” tytuł rekrutacji, nagłówek bierze
  `cv_role_title`, nie surowy tytuł.
  Wołają ją `standalone_service.load_candidate_generation_source` (z nazwami
  klienta) i `legacy_v7.pipeline` (wzorce bez bazy, dla uploadu). Przy
  polityce centralnej nagłówek i nazwa pliku to: stanowisko wpisane przez
  rekrutera → `cv_role_title(job)` → dopiero potem wynik modelu.
  `presentation_title.instructions` każe modelowi przepisać rolę bez zmian.
  QC CV ma porównywać nagłówek z tą samą funkcją (PR 2).
- **Lata** (`_helpers._fix_experience_years`, `_fix_scoped_years`):
  - liczba z ułamkiem jest dopasowywana w całości (`4,5 roku` nie daje już
    `4.4 lata`), liczby > 99 to daty i zostają („od 2023 roku”);
  - ogólny staż („N lat doświadczenia (w IT)”, „N years of experience”) =
    suma wszystkich ról, jak dotąd;
  - „N lat doświadczenia jako X” = `min(cała kariera, max(liczba modelu,
    role X))` — kod nigdy nie dopisuje lat z cudzych ról („3 lata jako Data
    Engineer” przy latach w sklepie nie staje się „13 lat”);
  - cała reszta („2 lata w SQL”, „2.5 years combined …”) zostaje, jak
    napisał model.
- **Notatki dla modelu** (`collect_screening_notes_text`):
  - `AI_SOURCE_DEFAULTS = {"transcripts": False, "prep": False}` — rozmowy
    nie mają pola rekrutacji (wchodziły rozmowy o innych procesach), a prep
    niesie ocenę rekrutera i tematy na następny prep; parametr `sources`
    dostanie przełączniki w karcie „CV do klienta” (PR 4);
  - `money_text.strip_rates_and_availability` wycina z notatek, notatki
    procesu, rekomendacji, transkryptów i notatek bez procesu
    (`collect_candidate_notes_text`) fragmenty o pieniądzach kandydata
    (każda kwota: „150 PLN/h + VAT”, „Oczekiwania: 20 000 PLN netto”,
    „Oczekuje 22k netto”, „Ma ofertę za 200 PLN dziennie”) i jego
    dostępności („Kandydat dostępny od 1.11”, „dostępna 06.03.2023”, „od
    zaraz”, „1 miesiąc wypowiedzenia”). Zostają: budżet projektu
    („Zarządzał budżetem 2 mln PLN”), „dostępność systemu 99,9%”, „API
    dostępne w chmurze”. QC czyta tylko wspólny wzorzec kwoty (`MONEY_RE`,
    `is_rate_text`); lista słów kandydata (oczekiwania, netto) jest tylko
    dla generatora;
  - minimum notatek z reguły klienta (`require_screening_notes_min_chars`)
    liczy ten sam tekst — bez transkryptów i prepów. 13.10.2026 żadna z 15
    reguł klientów nie miała minimum; kto je ustawia, musi wiedzieć, że
    rozmowa nagrana w Teams nie wlicza się, dopóki rekruter nie włączy
    transkryptów (PR 4).
- **Kontrola AI nie chowa zastrzeżeń** (`factual_verification.verify_final_cv`):
  odrzucone twierdzenia i twierdzenia z błędnym cytatem idą razem; błędny
  cytat w liście uwag ma prefiks „WERYFIKUJ (kontrola AI)”, nie „BRAK
  POKRYCIA”. Do 13.10.2026 jeden błędny cytat ukrywał resztę (86 z 759 CV).
- `PROMPT_VERSION = 8` w `legacy_v7/pipeline.py` (`editorial_provenance`).
- Testy: `test_cv_generator_legacy_v7.py` (sekcja „Silnik bez wypełniacza”),
  `test_cv_role_title.py`, `test_money_text.py`,
  `test_cv_screening_source_integrity.py`, `test_cv_factual_verification.py`.
