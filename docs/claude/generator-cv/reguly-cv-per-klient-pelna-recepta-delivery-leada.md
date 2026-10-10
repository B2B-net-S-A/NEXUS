# Reguły CV per klient — pełna recepta Delivery Leada

`/settings/cv-rules` jest JEDYNYM ekranem polityki CV klienta (od 09.2026).
Warstwy reguły, w kolejności powstania: nazwa pliku i język (`0255`) →
instrukcje dla modelu (`0266`) → blokady dla rekrutera, polityka prezentacji
egzekwowana w kodzie, słownik, wersja + historia + CV próbne (`0267`).
Decyzje Artura z 02.09.2026: reguła per KLIENT (wspólna, nie per rekrutacja),
DL zatwierdza SAM dla DOWOLNEGO klienta, zapis tylko **DL + admin**, blind
bez zmian, jeden szablon DOCX, stawek w CV nigdy, notatka sourcingowa TEŻ idzie
do modelu.

- **`GET /api/settings/cv-rules` zwraca `{rules, unassigned_templates}`** —
  KAŻDĄ regułę w bazie plus szablony Championa bez wiersza. Tych drugich nie
  wolno ukryć: brak reguły wyglądałby identycznie jak jej nieistnienie.
- **Zapis i zatwierdzenie to JEDNO kliknięcie** („Zapisz i zatwierdź",
  `PUT … {confirm: true}`). Domyślny `PUT` zostawia propozycję: nowa reguła
  czeka na zatwierdzenie, a edycja obowiązującej trafia do szkicu
  (`draft_payload`) — obowiązująca wersja działa dalej do „Zatwierdź”
  (stan kodu 09.2026; wcześniej edycja zdejmowała zatwierdzenie). Blokady i polityka
  też czekają na zatwierdzenie — inaczej kopia z innego klienta zaczęłaby
  blokować rekruterów (`test_unconfirmed_recipe_is_invisible_to_the_generator`).
- **Bramka zapisu to `DeliveryLeadPlus`, NIE `TacPlus`.** TAC edytuje kartę
  klienta, reguł nie prowadzi. Front idzie po WŁASNEJ capability
  `cv_rule.manage` (lustro w `capabilities.test.ts`). Okno „Edytuj firmę"
  NIE ma już formularza reguł ani przełącznika interaktywnego CV — odsyła do
  `/settings/cv-rules?client=<id>` (deep link czytany efektem, nie
  inicjalizatorem: miękka nawigacja nie odmontowuje strony). Zapis nie jest
  zawężany do portfela DL — lustro `PATCH /api/clients/{id}`; „Tylko moi
  klienci" to filtr z `data_scope`, nie granica.
- **Wersja i historia.** Każdy zapis zmieniający TREŚĆ bumpuje
  `client_cv_rules.version` i zostawia wpis w `client_cv_rule_events` z diffem
  pól (`saved` / `saved_and_confirmed` / `confirmed` / `deleted` / `copied`).
  Sam ponowny zapis identycznej treści wersji nie zmienia: stempel na CV ma
  mówić o treści, nie o kliknięciach. Nowy wiersz po usunięciu startuje od
  `max(rule_version)+1` z historii, nie od 1 — dwie różne treści pod tym
  samym numerem zamieniłyby stempel w zgadywankę. Wygenerowane CV nosi
  `cv_generated_documents.client_rule_version` — bez tego reklamacja klienta
  jest nie do prześledzenia. FK historii idzie po KLIENCIE, nie po regule:
  usunięcie i ponowne założenie reguły nie kasuje historii.
- **Flagi karty klienta (`cv_content_mode_cap`, `cv_interactive_enabled`)
  są zapisywane NA `clients`, ale prowadzone z edytora reguły** — generator,
  publiczny link i sufit działają bez zmian, a DL ma jeden ekran. Kopia
  z innego klienta ich NIE przenosi (obietnice złożone konkretnemu klientowi).
- **Do promptu trafiają DWA bloki w wiadomości użytkownika, nie w systemowym
  prompcie** (ten jest jednym cache'owanym blokiem i musi zostać bajt w bajt
  ten sam): `<client_presentation_rules>` = klocki zrenderowane w języku
  dokumentu + wolny tekst (`generator_instructions`, dla EN wariant
  `generator_instructions_en`, gdy wpisany) oraz `<client_notes>` = notatka DL.
  Oba prompty systemowe (PL/EN) definiują semantykę i granicę: dobór i forma
  faktów obecnych w `<cv>`/`<screening_notes>`, NIGDY nowe fakty; „klient ceni
  bankowość" znaczy „pokaż bankowe projekty wyżej, jeśli są", nie „napisz, że
  są". Pominiętą instrukcję model zgłasza w `warnings` („Pominięto instrukcję
  klienta: …"). `<`/`>` neutralizowane, sufit 2000 znaków na pole. Test:
  `test_cv_generator_client_instructions.py` (system prompt identyczny
  z instrukcjami i bez).
- **Klocki są domykane W KODZIE, nie tylko proszone** (`apply_presentation_policy`
  PO bezpiecznikach, tuż przed snapshotem `render_payload`): `omit_sections`
  (education | certifications | languages | skills — `why_points` i
  `experience` celowo poza katalogiem), `max_roles`, `max_bullets_per_role`,
  `max_bullet_chars` (cięcie na granicy słowa + „…"), `why_points_max`,
  `glossary` (całe słowa, bez `\b`, który przy polskich znakach nie działa;
  `re.sub` z lambdą, bo `\` w celu wywalałby `re.error`). **Kolejność jest
  load-bearing:** `_fix_experience_years` i `_derivable_years` liczą lata
  z PEŁNEJ listy stanowisk — obcięcie do `max_roles` przed nimi zaniżało
  nagłówek „N lat doświadczenia" i flagowało poprawną liczbę jako brak
  pokrycia; słownik przed bezpiecznikiem podmieniał nazewnictwo, którego
  ten nie znajdował w źródle. **Format dat NIE idzie do promptu** — model
  posłuszny prośbie o `MM/YYYY` gubiłby miesiące bezpiecznikom, które parsują
  wyłącznie `MM.YYYY`; format nakłada kod na końcu (`apply_date_format`).
  Domknięcie czegokolwiek = ostrzeżenie „domknięto politykę prezentacji
  klienta w kodzie" — posłuszny model nie generuje żadnej uwagi. Testy:
  `test_cv_rule_presentation_policy.py` (klocki w izolacji) i
  `test_cv_generator_client_instructions.py::test_policy_runs_after_year_guards…`
  (kolejność w prawdziwym pipeline'ie).
- **Blokady.** `content_mode` + `content_mode_locked`: zablokowany tryb
  NADPISUJE żądanie na serwerze (`resolve_content_mode` PRZED sufitem, sufit
  nadal wygrywa); kafelki w generatorze wyłączone; tryb bez blokady = domyślny,
  zaznaczany RAZ przy zmianie klienta. Wymagane wejścia (`require_*`) dają 422
  z listą braków PRZED naliczeniem kwoty, tym samym kanałem co zrzut zgody
  u PKO BP; front pokazuje te same zdania przed kliknięciem (`notes_chars`
  w readiness rekrutacji). `auto_second_language`: druga wersja generowana
  w tle po pierwszej, jako OSOBNY wiersz z osobną kwotą — tylko przy
  „obie wersje" i bez wymuszonego języka; odmowa kwoty dopisuje uwagę do
  pierwszego wiersza zamiast padać. Drugi wiersz jest pełnoprawny: własny wpis
  `Activity` i mapa wymagań interaktywnego CV, a `rule_reminders` NIE każe
  wtedy „pamiętać o drugiej wersji".
- **Klient jest zawsze wymagany** (generator v3, 23.09.2026 — sekcja „Generator
  CV v3”). Checkbox „CV poza zleceniem” usunięty: bez klienta nie działa ŻADNA
  reguła, a tak powstawała ⅓ CV.
- **Lint instrukcji (`POST …/cv-rule/lint`)** — tani model
  (`CLAUDE_MODEL_CV_BULK`), osobny klucz kwoty `aifeaturekey.cv_rule_lint`
  (enum + seed + lustro w entrypoincie; pilnuje
  `test_ai_feature_enum_entrypoint_mirror.py`). Opinia, nie bramka: pokazuje
  wcześniej granicę, której prompt generatora i tak pilnuje. Linie, których
  model nie ocenił, wracają jako `unclear`, nigdy jako `ok`.
- **CV próbne (`POST …/cv-rule/preview`) USUNIĘTE 23.09.2026** (0 użyć na
  produkcji; reguły są centralne). Tabela `client_cv_rule_previews`, model
  i retencja zostają (historia, `candidate_id` z CASCADE); retencja 7 dni biegnie
  w pętli `cv_source_cleanup` TYLKO przy `CV_JOB_INPUT_RETENTION_ENABLED=true`
  (od 23.09.2026 domyślnie wyłączona — CV nie znikają same). Zadanie kolejki
  rodzaju `preview` sprzed wdrożenia jest oznaczane jako nieudane zamiast
  wołać usunięty worker.
- **Sygnał zwrotny (`GET …/cv-rule/feedback`)** liczy z ostrzeżeń
  wygenerowanych CV pominięte instrukcje per tekst i domknięcia polityki;
  instrukcja pomijana w co drugim CV to instrukcja do przepisania.
- **Usuwanie bez `window.confirm`** — dwustopniowe potwierdzenie w edytorze
  i modal na liście. Natywny dialog zamraża automatyzację przeglądarki.

### Centralne reguły CV (`CV_CENTRAL_POLICIES_ENABLED`, 21.09.2026)

Katalog `backend/app/data/cv_policies.json` + `central_policies.py`, opis:
`docs/delivery/central-cv-policies.md`. Reguły, które łatwo cofnąć:

- **Tryb treści NIE jest blokowany.** Każdy klient (także Nordea) i polityka
  standardowa mają domyślnie „Pod rekrutację" (`content_mode` w katalogu —
  pole zostaje, żeby dało się przełączyć pojedynczego klienta). Rekruter może
  zmienić tryb; serwer honoruje żądanie (`resolve_mode`) w `/generate`
  i `/generate-upload`. `GET /api/cv-generator/policy` zwraca `default_mode`,
  `content_mode_locked=false` i `content_mode_notice`.
- **„Pod rekrutację" bez Championa = Redakcja + komunikat, nigdy 422.**
  Champion to kompletny profil rekrutacji (`job_supports_tailored` — JEDEN
  predykat dla domyślnego trybu i kontroli w ścieżce rekrutacji) albo
  WGRANY plik/podgląd Championa w uploadzie. Komunikat trafia do ostrzeżeń
  dokumentu (`source_warnings`). Sufit `cv_content_mode_cap` wygrywa zawsze.
- **Upload znowu używa wgranego Championa.** Pierwsza wersja centralnych
  reguł wyrzucała plik (`champion_bytes = None`) — udział CV „Pod rekrutację"
  spadł z 49% do 12%. Ręczne pola MUST/NICE (zasilały tylko kafelki
  interaktywnego CV) NIE są Championem.
- **Recepta centralna nie ustawia `why_points_max`.** „Najwyżej cztery
  punkty" jest w prompcie systemowym (`presentation_title.instructions`);
  powtórzone jako instrukcja klienta dawało fałszywe „Pominięto instrukcję
  klienta" w co trzecim CV.
- **Zmiana treści katalogu = podbij `version` wpisu.** `synchronize()`
  publikuje ponownie, gdy `managed_policy` (metadane wpisu) albo recepta się
  różni; `resolve()` do tego czasu daje 503 dla klienta. Klient niezgodny
  z katalogiem (inny `external_id`, ukryty, scalony) jest POMIJANY z logiem,
  a błąd synchronizacji nie zatrzymuje startu backendu (`main.py`).
- **Stary dokument drukuje „Rozważany na stanowisko" tylko, gdy różni się od
  nagłówka** (`considered_for_line`, porównanie bez wielkości liter i białych
  znaków) — DOCX, widok publiczny i eksport HTML.
