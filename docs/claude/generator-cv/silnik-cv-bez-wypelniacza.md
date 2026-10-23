# Silnik CV bez wypełniacza (13.10.2026, D1–D3)
<!-- indeks: bez punktu MUST, pytanie ≠ fakt, `cv_role_title`, lata, notatki bez stawek -->

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
  klienta) i `legacy_v7.pipeline` (wzorce bez bazy, dla uploadu). Rekrutacja
  z bazy idzie zawsze przez `cv_role_title_for_job(db, job)` — to samo
  wejście ma kopia CV etapu (`detached_copy_settings`: nazwa pliku i nagłówek
  kopii z innej rekrutacji). Do 15.10.2026 kopia brała surowy `jobs.title`
  i u PKO nazwa pliku miała numer dwa razy („ZOB-2949_… (ZOB-2949)_….docx”).
  Przy
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
  `test_cv_screening_source_integrity.py`, `test_cv_factual_verification.py`,
  `test_fix48_ws04_*.py` (poprawki z 14.10.2026).

## Poprawki po audycie 13.10.2026 (14.10.2026)

Audyt pokazał, że stawki dalej docierały do modelu, strażnik wycinał
prawdziwe umiejętności, a kontrola po edycji czytała pytania jak fakty.
Obowiązuje:

- **Kwota bez waluty to też stawka** (`money_text`): liczba zaraz po słowie
  o pieniądzach („stawka 150 B2B”, „o stawce 150-160”, „rate 140”,
  „Wynagrodzenie: 18 000”, „zarabia 18k”, „Widełki 20-25k”), kwota, której
  kandydat chce („chce 22k”, „chce 150 na B2B”), i liczba przy formie umowy
  („150 B2B”). `is_rate_text` liczy je jako stawkę (licznik w karcie „CV do
  klienta”). `MONEY_RE` i `RATE_WORD_RE` dla QC bez zmian. Zostają: „success
  rate 95%”, „rate limiting 1000 req/s”, „Pracuje od 3 lat na B2B”.
- **Dostępność tylko z czasem albo z kandydatem jako podmiotem**: „dostępny
  od zaraz / od 1.11 / za 2 tygodnie / 06.03.2023”, „Kandydat jest dostępny”,
  „Notice: 1 month”, „1 month notice”, „Can start in 2 weeks”, „Start: od
  1.11”, „start ASAP”, „Gotowy do startu od listopada”, „Może zacząć…”.
  Gołe „jest dostępny” i liczba bez daty już nie wystarczają, więc zostają
  fakty o systemach: „dostępność 99,95%”, „System jest dostępny 24/7”,
  „API … jest dostępne publicznie”. „Prowadził projekt wart 5 mln PLN” to
  wartość projektu, jak budżet.
- **Filtr stoi na każdej drodze do modelu**: odpowiedzi ze screeningu
  (`_format_candidate_answers` — odpowiedź pusta po filtrze znika razem
  z pytaniem), notatka ze screeningu (`_format_screening_note`, pole po
  polu, więc „Kafka (senior)” zostaje bez „rate 140”), a w
  `legacy_v7.pipeline` jeszcze raz cały tekst notatek — notatki wpisane
  w formularzu generacji (upload, CV bez procesu) nie przechodzą przez
  kolektor. Hash notatek w migawce i `editorial_provenance` liczy się
  z wejścia.
- **Pytanie z zapisanej treści**: `P:` przy odpowiedzi bierze
  `question_text` zapisane przy odpowiedzi (jak przegląd DL), bo `q1…qN` są
  pozycyjne i po edycji profilu Championa wskazują inne pytanie. Bieżący
  profil tylko dla arkuszy sprzed 02.10.2026, które tej treści nie mają.
- **Strażnik terminów — skrót = pełna nazwa** (`_PHRASE_ALIASES`): AWS ↔
  Amazon Web Services, GCP ↔ Google Cloud (Platform), CI/CD ↔ continuous
  integration/delivery i „ciągła integracja/wdrażanie”, TDD, OOP
  („programowanie obiektowe”), ML („uczenie maszynowe”), AI, IaC, DDD, BDD,
  NLP, LLM — w obie strony.
- **Strażnik terminów — zwykłe słowa a język CV**: termin ze zwykłych słów
  („Code review”, „Testy automatyczne”, „Project management”; rozpoznany po
  ogonkach, końcówkach i krótkiej liście słów) znika tylko wtedy, gdy CV
  źródłowe, wynikowe CV i termin są w tym samym języku. Inaczej (albo gdy
  języka CV nie da się ustalić) termin zostaje z uwagą „WERYFIKUJ: nie ma
  tego dosłownie w CV… sprawdź, czy kandydat to ma”. Nazwa technologii
  („OpenTelemetry”, „Spring Boot”, „Kafka Connect SMT”) nie ma tłumaczenia,
  więc znika jak dotąd, w każdym języku. Synonimy w tym samym języku
  („automated testing” ↔ „Test automation”) strażnik nadal może usunąć —
  uwaga „usunięto…” to pokazuje.
- **Kontrola po ręcznej edycji bez pytań**: `cv_review_sources` podaje
  recenzentowi zamrożone notatki bez linii `P:` (`screening_text_without_questions`),
  tak samo jak kontrola przy generacji.
- **Lata**: połowa roku w górę (54 miesiące = 5 lat; `round()` dawał 4),
  a ułamek modelu zgodny z datami po zaokrągleniu zostaje („4,5 roku
  doświadczenia”, „4,5 roku w Acme”).

## Polska uczelnia w polskim CV po polsku (15.10.2026)

Zgłoszenie: w CV po polsku kierunek był przetłumaczony („Filologia angielska,
licencjat”), a nazwa uczelni została po angielsku („University of
Białystok”), bo model przepisywał ją ze źródła jak nazwę własną. Pomiar
produkcji (60 dni): w polskich CV 338 z 1437 wpisów wykształcenia miało
angielską nazwę uczelni (część to uczelnie zagraniczne, które tak zostają).

- **Prompt PL (`legacy_v7`, wersja 9, reguła 11):** polską uczelnię model
  podaje w oficjalnym polskim brzmieniu, zagraniczną zostawia w oryginale,
  a gdy nie zna pewnie polskiej nazwy — przepisuje ją ze źródła zamiast
  wymyślać tłumaczenie.
- **Tabela w kodzie (`cv_generator_b2b/university_names.py`):** po
  odpowiedzi modelu `localize_education` podmienia angielskie nazwy
  48 najczęstszych polskich uczelni, więc wynik nie zależy od tego, czy
  model posłuchał. Tylko cała nazwa (z miastem albo skrótem w nawiasie lub
  bez); nazwa z wydziałem, uczelnia spoza tabeli i uczelnie zagraniczne
  zostają bez zmian. Nowy wpis tylko z oficjalną angielską nazwą uczelni.
- **CV po angielsku bez zmian** — kod nie podmienia tam nazw, a prompt EN nie
  ma reguły o uczelniach.
- Ścieżka `v10` (`editorial_prompt`: „Preserve … institutions”) bez zmian.

## Stanowiska od najnowszego liczy kod (16.10.2026)

Zgłoszenie rekruterki: CV z generatora miało doświadczenie nie po kolei.
Prompt `legacy_v7` mówi „uporządkuj doświadczenie od najnowszego”, ale ten
sam prompt pozwala modelowi „zmieniać kolejność” pod wymagania Championa
i reguły klienta („kolejność sekcji i pozycji”), więc rola najbliższa
wymaganiom potrafiła wylądować na górze. Kod nie sprawdzał kolejności wcale.

- **`services/cv_role_order.sort_experience`** ustawia `experience` od
  najnowszego zaraz po odczycie odpowiedzi modelu (`legacy_v7.pipeline`
  i ścieżka `v10` w `standalone_service`). Przestawia tylko PEWNE błędy:
  rolę zakończoną, zanim zaczęła się rola stojąca niżej, i rolę zakończoną
  nad trwającą („obecnie”, „present”). Nakładające się, zakończone role
  zostają w kolejności modelu (sortowanie topologiczne, stabilne). Rola bez
  czytelnych dat zostaje na swoim miejscu, reszta układa się na wolnych
  miejscach. Pomiar produkcji 16.10.2026 (810 CV z 30 dni, tylko odczyt):
  107 z 777 CV z datami miało kolejność inną niż „koniec malejąco”, ale 52
  z nich to nakładające się role ułożone po dacie rozpoczęcia — prawdziwych
  błędów było 55 (14 starsza nad całkiem nowszą, 41 zakończona nad trwającą).
  Pierwsza wersja (#2267) poprawiała wszystkie 107 i zmieniałaby wygląd CV
  bez potrzeby.
- Ponad `ROLES_MAX` (100) stanowisk kolejność się nie liczy (koszt
  kwadratowy, a treść z edytora może nieść ich tysiące).
- **Przed regułą klienta „maks. N stanowisk”** (`apply_presentation_policy`
  bierze pierwsze N z listy). Bez tego przy złej kolejności modelu klient
  z limitem dostawał najstarsze role zamiast obecnej.
- **Przed formatem dat klienta** (`apply_date_format`); parser czyta
  `MM.YYYY`, `MM/YYYY`, `MM-YYYY`, `YYYY-MM` i `YYYY`, a przy kilku datach
  w tekście bierze dwie ostatnie (rok w nazwie roli stoi przed okresem).
- Ta sama funkcja liczy „ułóż chronologicznie” w asystencie edytora
  (`reorder_roles`, `edytor-cv-pelny-ekran.md`). Kolejność, którą rekruter
  ustawi ręcznie w edytorze, zostaje — sortuje tylko generator.
- CV wygenerowane wcześniej nie są przestawiane z mocy wstecznej.

## Odpowiedź, która odsyła do pytania (23.10.2026)

Zgłoszenie rekrutera: generator „średnio uwzględnia” odpowiedzi ze screeningu.
Przypadek z produkcji (CV z 23.10.2026, rola sieciowa): odpowiedź „Posiadam takie
doświadczenie, …” na pytanie o architekturę i VLAN-y, a kontrola AI oznaczyła
„VLAN segmentation” jako „NOT IN SOURCE”. Strażnik terminów, bezpieczniki i kontrola AI
czytają odpowiedzi bez linii `P:` (reguła „pytanie ≠ fakt” wyżej), więc
„takie doświadczenie” i samo „Tak” traciły treść.

- `_format_candidate_answers` dopisuje do takiej odpowiedzi „(potwierdza
  pytanie: …)”, więc rzecz z pytania jest w linii `O:` i liczy się jako
  odpowiedź (`_confirms_question`). Dotyczy: samego potwierdzenia („Tak”,
  „Tak, ma doświadczenie”, „Yes, I have”) i odesłania („takie / tego typu
  doświadczenie”, „w tym zakresie”, „such experience”).
- Bez dopisku: odpowiedź z zastrzeżeniem („ale”, „tylko”, „nie”,
  „teoretycznie”), pytanie z alternatywą („albo”, „lub”, „or”) i odpowiedź,
  która sama nazywa rzeczy („Tak, Grafana i Prometheus” nie potwierdza
  OpenTelemetry z pytania).
- Zaślepka zamiast odpowiedzi („x”, „-”, „?”, „n/a”) znika razem z pytaniem.
- Pytanie w linii `P:` też przechodzi przez `strip_rates_and_availability`.
- Formularz screeningu podpowiada wzór odpowiedzi i ostrzega przy samym
  „tak/nie” albo zaślepce (`lib/screening-answer-hint.ts`).
- Testy: `test_cv_generator_b2b_pipeline.py` (sekcja „Odpowiedź, która odsyła
  do pytania”).
