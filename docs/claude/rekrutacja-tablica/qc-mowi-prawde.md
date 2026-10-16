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
  historyczne wiersze mają wpisane `tailored`. Przy „nie dotyczy” technologie
  z wymagań, które stoją w CV bez pogrubienia, idą do `check["info"]`
  (`fix: "bold_all"`) — bez uwagi do poprawy, ale „Pogrub wymagania (N)”
  w pasku edytora liczy je i pogrubia (16.10.2026: w CV z Redakcji przycisk
  stał na 0 z dymkiem „już pogrubione”).
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
