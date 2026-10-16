# QC CV mówi prawdę (13.10.2026)
<!-- indeks: `found_in`, odpowiedzi jako źródło, zdanie w roli tylko przy opisie, „Szukałem w” -->

Zespół mówił, że QC „proponuje głupoty”. Pomiar z 13.10.2026 (121 par
z 3 dni, tylko odczyt): średnio 8–9 uwag na CV, około połowa fałszywa albo
bezużyteczna. Przyczyny: QC nie czytało odpowiedzi ze screeningu, nie znało
innego zapisu ani tłumaczenia tej samej rzeczy (49% par ma CV w innym języku
niż oryginał), porównywało nagłówek z tytułem rekrutacji z kodami klienta,
żądało pogrubień w CV, które ich nie miały, i żądało zdania w każdej roli,
w której oryginał tylko wymieniał technologię. Makiety:
https://claude.ai/artifact/BZZRshjBDC4CMEGGP6m4Wr

Ten sam pomiar kodem z tej zmiany (te same pary): 8,13 → 4,72 uwag na CV,
tytuł 97 → 21 (dalej spada po słowniku słów ról), pogrubienia bez pokrycia
145 → 9, zdanie w roli 111 → 14, krytyczne 38 → 13. Pozostałe blokady
„spoza oryginału” sprawdzone ręcznie: w większości tej rzeczy nie ma
w żadnym źródle.

## Reguły

- **Te same źródła co generator.** `cv_qc.answers_text(stage, job)` —
  odpowiedzi kandydata ze screeningu (`_format_candidate_answers`) bez linii
  pytań i bez zdań przeczących (`must_text_evidence.drop_negative_sentences`
  ocenia ZDANIA, nie całą odpowiedź: „Używała Grafany. Nie zna Iceberga.”
  zostaje dowodem Grafany). Notatki przez `evidence_note_text` i
  `ai_readable_clause` (bez automatów, wycofanych odpowiedzi karty, follow-upu).
- **Dwa dopasowania, `dz_review.found_in(text, req, mode=…)`.** `_found`
  zostaje dosłowne — czytają je też przegląd DZ, AI w edytorze i przegląd DL.
  - `mode="support"` (blokada `no_unsupported`): dosłownie z aliasami
    i odmianą, oboczność („Kafce”, „Jirze”), forma zbita z sąsiednich słów
    („EntraID” = „Entra ID”, „RestAssured” = „REST-assured”) i kuratorowany
    słownik `data/cv_term_translations.json`. Nic luźniejszego —
    przepuszczałoby zmyślenia.
  - `mode="presence"` (czy jest w CV albo w źródłach; must w CV, krytyczne,
    tytuł): dodatkowo grupy wyszukiwarki, fraza słowo po słowie OBOK SIEBIE
    w odmianie z zamkniętej listy końcówek („bankowości” ↔ „bankowość”,
    „aplikacji webowych” ↔ „aplikacje webowe”), liczba mnoga skrótu z wielkich
    liter („APIs” ↔ „API”) i wybór „A/B” z członami ≥ 4 znaków („Python/Perl”;
    „PL/SQL” to jedna nazwa). Nigdy prefiks: rdzeń z 4 liter przepuszczał
    krytyczną „Spring” przy „sprint planning”, „Excel” przy „excellent”,
    „Google Cloud” przy „Google Analytics, Oracle Cloud” (przegląd PR 2).
  - Granica słowa zostaje: Java ≠ JavaScript, Go ≠ Google.
- **Słownik `cv_term_translations.json` prowadzi człowiek.** Tylko dokładne
  odpowiedniki, bez gwiazdek; każde słowo przechodzi `parse_keyword`
  (`tests/test_qc_term_matching.py`). Słowa nazw ról (inżynier/engineer,
  badacz/researcher, analityk/analyst…) służą porównaniu tytułu CV sprzed D2.
- **Nagłówek to nie twierdzenie.** `claim_blocks` pomija h1, linię
  „Rozważany na stanowisko” (`considered`) i klauzulę RODO — w nagłówku stoi
  rola od klienta, nie umiejętność kandydata.
- **Tytuł** (`title_matches_role`, uwaga): nagłówek CV porównany
  z `cv_role_title(job)` (ta sama funkcja co generator, D2) i z nagłówkiem
  zapisanym w migawce generatora (`presentation_position`). Dosłownie
  w pierwszych blokach albo słowami z odpowiednikami tylko w h1 (≥ 75% słów,
  bez seniority). Tytuł z kodami klienta nie jest już oczekiwany.
- **Pogrubienia** (`must_bolded`, `nice_bolded`): `bold_expected` — `True`, gdy
  migawka ma `highlight_keywords` albo politykę must/must_nice/explicit;
  `False` dla pliku z dysku i CV bez wyróżnień (sprawdzenie „nie dotyczy”);
  `None` (nie wiadomo) — sprawdzamy jak dotąd. Nie według `content_mode`:
  historyczne wiersze mają wpisane `tailored`. Uwaga to wymaganie bez ani
  jednego pogrubienia. Do `check["info"]` (`fix: "bold_all"`, bez uwagi do
  poprawy) idą: wymaganie pogrubione tylko w części miejsc (`_has_unbolded`,
  te same wzorce i miejsca co poprawka `bold_all`) oraz — przy „nie dotyczy” —
  każde niepogrubione. „Pogrub wymagania (N)” w pasku edytora liczy też je
  (16.10.2026: CV .NET z produkcji miało „8/8”, a 12 wystąpień dwóch wymagań
  w punktach bez pogrubienia; przycisk stał na 0 z dymkiem „już pogrubione”).
- **Pogrubienia bez pokrycia** (`bold_unsupported`): tylko technologie ze
  słownika (`_is_tech_term`; bez wczytanego słownika — każda krótka fraza,
  jak przed zmianą), bez edukacji, ostrym dopasowaniem.
- **Zdanie w roli tylko przy opisie roli — także dla krytycznych** (decyzja
  Artura 13.10.2026, zastępuje regułę z 02.10 i 12.10). Pozycję do poprawy
  daje tylko `evidence_kind == "description"`. Technologia tylko na liście
  roli albo w nazwie stanowiska to informacja (`check["info"]`, stan roli
  `listed_only`) — bez blokady i bez propozycji AI. Krytyczna blokuje, gdy
  nie ma jej w całym CV albo brakuje zdania tam, gdzie oryginał ją opisuje.
  Wymaganie opisowe (≥ 4 słowa), którego nie ma nigdzie, to informacja
  („sprawdź ręcznie”), nie „zapytaj kandydata”.
- **Pozycje informacyjne nie są w `items`.** `_tasks`, `summarize`,
  `fixes_material`, `checkTasks` i `roleGaps` liczą tylko `items`; `info`
  pokazuje okno w „Informacje — bez poprawki”.
- **Dowód przy pozycji:** `searched: [{source, found, quote?}]` dla `cv`,
  `original`, `answers`, `notes` — okno pokazuje „Szukałem w: …” i cytat
  ze źródła, w którym QC coś znalazło. Cytaty notatek idą z tekstu bez pól
  handlowych karty.
- **Klucz pozycji** `item["key"] = "<sprawdzenie>|<wymaganie lub termin>|<rola
  z oryginału albo cv>"` (znormalizowany, `#n` przy duplikatach) — z pól
  pozycji, nigdy z `role_index`. Na nim stanie „To nieprawda” (PR 3).
- **Odpowiedzi** czytane wprost z pola odpowiedzi (cała odpowiedź w kilku
  liniach), bez kwot (`strip_rates_and_availability`) i bez zdań przeczących;
  zdanie kończy się znakiem końca i odstępem albo linią — kropka w „.NET 8”
  i „3.5” zdania nie dzieli.
- **Propozycje AI** (`parse_fixes`, `FIXES_PROMPT_VERSION = cv-qc-fixes-v6`):
  - cytat z oryginału musi stać w opisie tej roli, pokrywać go w ≥ 60% słów
    albo stać w części pliku tej firmy (`_quote_in_role`);
  - cytat z odpowiedzi (`source: "answers"`) albo notatek — tylko w zdaniu
    albo linii, która nazywa firmę tej roli całym słowem (D3; „ingestion” to
    nie „ING”);
  - zdanie przeczące w cytacie albo propozycji i wersja niższa niż
    w wymaganiu („Java 8” przy „Java 17”) odpadają („OAuth2” = „OAuth 2.0”,
    „Java 8, 11 i 17” zawiera 17);
  - prompt mówi, w jakim języku jest CV (`cv_language`), odpowiedzi idą
    w znaczniku `<candidate_answers>`.
- **Zmiana reguł przelicza nieudane pary sprzed wysłania**
  (`recompute_outdated`), zaliczonych nie. Nowy przebieg zaliczonej pary
  dostałby dzisiejszą datę, a od niej kolejka Delivery Leada liczy czas
  oczekiwania (`dl_send_queue.readiness_of`) — przegląd PR 2. Bramka ruchu
  liczy QC na żywo. `limit` liczy przeliczone pary, nie pominięte.
- **Pomiar przed podbiciem `QC_VERSION`:** `backend/scripts/qc_truth_audit.py`
  w kontenerze backendu (sesja tylko do odczytu, same liczby). Nowy kod
  można zmierzyć przed merge'em, podając go jako nakładkę w tym samym
  procesie (katalog tymczasowy na początku `sys.path`) — porównaj liczby
  starego i nowego kodu na tych samych parach.

Testy: `tests/test_qc_term_matching.py`, sekcja „QC mówi prawdę” w
`tests/test_cv_qc.py`, `CvQcDialog.test.tsx` („QC mówi, gdzie szukało”).

## „Stanowiska od najnowszego” (16.10.2026, decyzje Artura D1–D7)

Makiety: https://claude.ai/artifact/LEyxJKjJxiEveHG1EFVz1h (prywatne).
Zgłoszenie rekruterki: CV z doświadczeniem nie po kolei; generator od #2267
układa stanowiska sam, ale zostają CV sprzed wdrożenia, wgrane z Worda,
kopie z innej rekrutacji i ręczne przestawienia. Pomiar 16.10.2026 (szkice
etapów z 30 dni, tylko odczyt): 15 z 143 CV z generatora i 2 z 47 pozostałych
miało pewny błąd kolejności.

- **Uwaga, nie blokada** (D2): `role_order` w `WARNING_KEYS`, etykieta
  „Stanowiska od najnowszego”. Jedna pozycja — pierwsze stanowisko, które stoi
  za wysoko: „„X” stoi nad nowszym „Y”.”, `fix: "role_order"`, `role_index`
  (działa „Pokaż w CV”). Reguła ta sama co w generatorze
  (`cv_role_order.newest_first`): tylko pewne błędy, nakładające się
  zakończone stanowiska nie są uwagą.
- **Nie dotyczy** (`skip`): mniej niż dwa stanowiska, CV bez znaczników
  stanowisk (role zgadywane po nazwach firm — D5, bez szumu), żadne stanowisko
  bez czytelnych dat (to mówi uwaga „Każda rola ma daty”), ponad `ROLES_MAX`.
  Rola bez dat zostaje na swoim miejscu (D4).
- **„Ułóż od najnowszego”** (D1): akcja `role_order` w `transform_html`
  (edytor, `qc/transform`) i w `apply_action` (okno QC, `qc/apply`).
  Przestawia całe stanowiska (`cv_rewrite_merge.roles_newest_first` →
  `_role_spans`, lustro `cv_qc.cv_roles`): stanowisko kończy następne
  stanowisko, nagłówek h1/h2 albo klauzula zgody — śródtytuł projektu (h3,
  tak zapisuje import Worda) należy do stanowiska. NIE `_parts` z „Napisz od
  nowa”, który dzieli na h3: przegląd 16.10.2026 pokazał projekt przeniesiony
  pod cudze stanowisko. Opakowania `article`/`div.job` generatora znikają,
  reszta treści zostaje na miejscu. Już ułożone = `nothing_to_do`
  („już są ułożone”); stanowiska nie obok siebie (dwie sekcje
  doświadczenia) = `nothing_to_do` z „Nie umiem bezpiecznie przestawić…
  przestaw ręcznie” — nic nie przenosimy między sekcjami.
  **Nie wchodzi do „Popraw wszystko”** (D3): `_ACTIONS`, nie `BULK_ACTIONS`.
- **„Zostaw tę kolejność”** (D6) zamiast „To nieprawda” przy tej pozycji: jedno
  kliknięcie, pominięcie z powodem `kept_order` („Kolejność stanowisk celowo
  inna”, nie liczy się do trafności QC). Powód działa tylko przy `role_order`
  (`cv_finding_dismissals.REASON_CHECKS`, inaczej 422); w formularzu „To
  nieprawda” go nie ma. Klucz pozycji niesie zdanie z dwoma stanowiskami, więc
  inna zła kolejność to nowa uwaga. Lista „Pominięte” mówi „nie liczą się do
  uwag” bez „nieprawda”.
- `QC_VERSION` bez zmian: nowa uwaga nie zmienia zaliczenia, a zapisane
  przebiegi dostaną ją przy następnym liczeniu QC.

Testy: sekcja „Kolejność stanowisk” w `tests/test_cv_qc.py` (także koszt na
12 tys. stanowisk), `CvQcDialog.test.tsx` („Stanowiska od najnowszego”),
reguła w `tests/test_cv_generator_legacy_v7.py`.
