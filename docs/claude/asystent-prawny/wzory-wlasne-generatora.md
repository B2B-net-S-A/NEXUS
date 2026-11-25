# Wzory własne Generatora Umów B2B (asystent prawny, część B)

Uwaga zespołu (25.11.2026): „żeby się dało stworzyć całkiem nowy wzór umowy —
jak umowa o udziale w rekrutacji pod CeZ albo umowa o poprowadzeniu szkolenia —
zachować go i dodać do wyboru w Generatorze Umów”. Dotąd każdy taki wzór robił
programista (skrypt `backend/scripts/build_*_template.py`, wpis w
`services/b2b_documents/registry.py`, wdrożenie). Decyzja Artura z 25.11.2026:
asystent działa w tle istniejących ekranów, wzór własny zapisuje się w bazie,
zatwierdza go administrator, a dokument z niego **tylko** trafia do rejestru
dokumentów Generatora.

## Gdzie to jest

- Generator Umów B2B → zakładka „Dokumenty”: przycisk „Nowy wzór z asystentem”
  obok „Nowy dokument”, karta „Wzory własne” pod listą dokumentów, sekcja
  „Wzory własne” w kroku rodzaju dokumentu kreatora.
- Backend: `app/services/custom_templates/` (pola, sandbox, wykrywanie pól,
  szkic AI, sprawdzenia, cykl życia), trasy `app/api/custom_document_templates.py`
  pod `/api/b2b-generator/custom-templates`, tabele z migracji
  `0780_custom_document_templates` (DDL w `custom_templates/schema.py`, lustro
  w `entrypoint.sh` przez `hr_schema_bundle`, sondy w `/api/health/deep`).
- Front: `components/v2/b2b-generator/documents/custom-templates/`, logika
  w `lib/custom-templates.ts`, API w `lib/api/customTemplates.ts`, harness
  `/preview/custom-templates`.

## Przepływ i stany

1. **Opis** — start od wzoru z repo (dziś „Umowa B2B — szkolenia”) albo
   zatwierdzonego wzoru własnego, od pliku Word działu, albo od samego opisu
   (ten wariant wymaga modelu).
2. **Szkic i pola** — zmiany akapitów względem bazy (przed/po, powód), lista
   pól z grupą i źródłem (kandydat, CEIDG, lista klientów, ręcznie),
   sprawdzenia. Klucza pola nie zmienia się w formularzu — stoi w treści
   wzoru; nowe pole dodaje Word albo asystent.
3. **Zapis i zatwierdzenie** — nazwa, rodzaj (tylko etykieta), dla jakich
   klientów, kto podpisuje, forma podpisu, wersja.

Wersja: `draft` → `pending` (zgłasza autor z prawem „Generowanie”) →
`approved` (wyłącznie administrator, `AdminUser`) albo z powrotem `draft`
z uwagą; `withdrawn` po wycofaniu wzoru. Jedna wersja robocza na wzór
(unikalny indeks częściowy). Zmiana zatwierdzonego wzoru = „Nowa wersja”
obok działającej. Wydany dokument ma `template_key = custom_v<id wersji>`
i migawkę pól w `render_payload.custom_template` — pobiera się zawsze tą
wersją, którą go wydano (jak `template_revision` typów z rejestru).
Szkic widzi autor i administrator; zatwierdzony wzór — każdy z Generatora.

## Czego nie robić

- **Wzór własny nie ma skutków w kontraktach.** Rodzina `custom` w
  `effects.describe/apply` kończy się od razu: „Oznacz jako podpisany” tylko
  zmienia status dokumentu, nie zakłada kontraktu, zamówienia ani pliku
  w Dokumentach kontraktu. Skutki zostają przy typach z rejestru programisty.
- **Nie poluzowuj sandboxa.** Szablon wzoru to plik od człowieka albo szkic
  modelu. `sandbox.validate` przepuszcza wyłącznie: pola z listy, `if`/`else`,
  porównania, `and`/`or`/`not`, filtry `upper lower capitalize title trim
  default join length` i `for` tylko po polu-liście. Wywołanie, indeks,
  atrybut `_…`, atrybut czegokolwiek poza polem, `set`, `include`, `macro` —
  błąd przy zapisie. Render idzie przez `SandboxedEnvironment` z wyczyszczonymi
  globalami i filtrami, z kontekstem zbudowanym wyłącznie z pól
  (`fields.build_context`), i waliduje jeszcze raz przed renderem. Testy:
  `test_custom_templates_sandbox.py` (m.in. `{{ ''.__class__ }}`).
- **Limity zasobów (przegląd bezpieczeństwa 25.11).** Pętla w pętli jest
  błędem przy zapisie (30 pozycji do potęgi głębokości = setki tysięcy
  akapitów). Render liczy wynik kawałkami i przerywa ponad
  `MAX_RENDER_CHARS` (`RenderTooLarge`, czyli `TemplateInvalid` → 422).
  Każdy Word — upload (`_read_docx`, `detect`), render i walidacja zapisanego
  oryginału — przechodzi najpierw `sandbox.check_package`: liczba części,
  rozmiar części i suma po rozpakowaniu (zip bomb). Podgląd i prefill
  pilnują `offered_to` jak wystawienie (wzór dla wybranych klientów).
- **Model nie pisze kwot słownie, dat ani form Pan/Pani** — robi to kod:
  pole `money` `X` daje `{{ X }}` i `{{ X_words }}`, `date` — „DD.MM.RRRR”,
  pole `gender` — `{{ g.* }}`. Zmiana od modelu z `{% %}` albo polem spoza
  listy jest odrzucana (`draft._text_problem`).
- **Do modelu nie idą dane osób.** Wzór ich nie ma; numery i e-maile i tak są
  maskowane w poleceniu (`draft._mask`), a wykrywanie pól ostrzega, gdy
  wgrany Word ma NIP, PESEL albo e-mail osoby.
- Funkcja AI `legal_template_draft` (F57; plan nazywał ją F20, ten numer jest
  zajęty) jest dodatkiem: bez klucza albo przy awarii szkic zostaje bez zmian,
  ścieżka „wgraj Word → pola → zapis” działa.

## Sprawdzenia (kod, nie model)

`checks.py`: art. 22 § 1 KP (sformułowania etatowe → ostrzeżenie), art. 53
pr. aut. (przeniesienie praw autorskich bez formy „na papierze albo
kwalifikowany” **blokuje** zgłoszenie i zatwierdzenie), art. 13 RODO (wzór
z danymi Partnera bez klauzuli → ostrzeżenie). Stan cytatu daje weryfikator
fundamentu (część A) przez `legal_bridge.py`; bez fundamentu — „do
sprawdzenia”. To podpowiedź, nie porada prawna.

## Wykrywanie pól we wgranym Wordzie

Klocki akapitów (`replace_span`, `doc_to_html`, `scrub_package`) żyją w
`custom_templates/docx_ops.py`; `scripts/build_b2b_document_templates.py` je
importuje. `detect.py`: `____`, `……`, `.....`, `[nr umowy]` → pola z etykietą
z tekstu przed luką (NIP/REGON/firma/adres → CEIDG, e-mail/telefon/imię →
kandydat, „klient” → lista klientów, „w dniu” → data, „kwota … zł” → kwota,
„słownie:” → `{{ kwota_words }}`); akapit z samych kresek pod etykietą →
pole wielowierszowe; kreski przy podpisach zostają; formy „Panem/ią”,
„prowadzącym/cą”, „zwanym/ą” → `{{ g.* }}` i pole płci.
