# Generator CV v3 — jeden ekran od osoby (23.09.2026)

Dane z produkcji (23.09): 99,7% generacji szło trybem „Mam tylko plik CV (bez
procesu)”, a 94% tych osób było już w bazie (88% w procesie). Decyzje Artura
(makiety: https://claude.ai/artifact/E8QeDEyEQdAec4TVbhjPMW):

- **Start od wyboru osoby** (typeahead także po telefonie). Plik z dysku tylko
  dla osoby spoza bazy: `POST /api/cv-generator/identify-upload` (bez modelu,
  e-mail/telefon z nagłówka CV) → „użyj osoby z bazy” / „Dodaj do bazy”
  (`/candidates/from-cv`) / „Generuj bez dodawania” (`/generate-upload`).
- **Klient zawsze wymagany**; z procesu wynika sam. `/generate` przyjmuje
  `stage_id: null` + `client_id` („inny klient (bez procesu)”); wtedy do
  modelu idą tylko notatki bez rekrutacji (`Note.job_id IS NULL`).
- **Champion i notatki z procesu, uzupełniane w miejscu i zapisywane w
  rekrutacji.** Gdy zapis Championa się nie uda, profil z podglądu idzie w
  żądaniu (`champion_profile`) tylko do tego CV — ta sama lekcja co przy
  centralnych regułach (spadek „Pod rekrutację” 49% → 12%).
- **Dwa kafle obróbki** (Redakcja / Pod rekrutację, domyślny z Championa);
  „Przepisanie” zniknęło z UI (backend przyjmuje). **Język PL · EN · Obie**:
  `languages: "both"` wymusza drugą wersję także bez reguły; przy języku
  wymuszonym regułą → 422 przed kwotą. Do snapshotu zadania trafiają tylko
  wartości niedomyślne. Numer projektu PKO serwer bierze z rekrutacji
  (`pko_job_reference`), gdy pole jest puste.
- **Wynik zawsze podpina się do etapu jako szkic „CV do klienta”**, gdy etap
  go nie ma — także u osoby spoza zespołu (świadome poluzowanie reguły
  członkostwa). Podpina worker (`attach_as_stage_draft`), więc przeżywa restart.
- **Jeden formularz we wszystkich miejscach:** strona `/cv-generator`,
  `CvGeneratorDialog` na profilu kandydata (usunięta kopia `CVGeneratorV2`),
  karta `CvToClientCard` w panelu osoby rekrutacji. Kod:
  `components/v2/cv-generator/`. Harness `/preview/cv-generator?state=`.
- **Word CV z rekrutacji ma układ szablonu firmowego** (30.09.2026, zgłoszenie
  „szkic rozjechany”). Szkic, zatwierdzone CV, przegląd DL, kolejka Cpro
  i karta „CV do klienta” robią DOCX z HTML-a edytora
  (`services/cv_approved_docx.py`, `approved-html-2`), bo edycje i poprawki
  QC muszą przetrwać. Do 30.09 był to ogólny konwerter (kropki jako tekst,
  bez linii i tabel), więc do klienta szedł inny wygląd niż z profilu.
  Sekcje rozpoznają znaczniki `data-cv-section` (edytor je zachowuje —
  `lib/cv-editor-section.ts`), a w starszym HTML tytuły sekcji i kształt
  akapitów. Tabela edukacji jest wspólna z generatorem (`add_education_table`,
  `style_education_row`). Tekst i pogrubienia idą z edytora 1:1, dochodzą
  tylko etykiety układu („Nazwa firmy:”, „Stanowisko:”, nagłówek tabeli).
  Nie wracaj do ogólnej konwersji ani nie zdejmuj „Pobierz szkic DOCX” —
  to ten sam plik, który dostaje klient.
- **Wycofane:** stary szablon „CV firmowe / Stwórz brandowane” (HTML z pól
  profilu, bez reguł klienta, z telefonem i e-mailem kandydata —
  `cv_html_renderer.py` usunięty — jego arkusz żyje zamrożony w
  `cv_legacy_template_css.py`, bo publiczny link pokazuje stare CV etapów
  w tym układzie; GET etapu przy `none` nic nie renderuje,
  PATCH szablonu 410, finalize przy `none` 409), pola Must/Nice, checkbox „CV
  poza zleceniem”, CV próbne, osobny krok „Zatwierdź” w edytorze (jeden
  „Zapisz”; zatwierdzenie z kontrolą AI leci w tle, `lib/cv-background-approval.ts`
  — serwerowe `finalize` zostaje, bo od wersji zatwierdzonej zależą pakiet,
  `needs_review` i linki).
- Ostrzeżenia: „Do sprawdzenia” (kontrola AI, BRAK POKRYCIA, WERYFIKUJ) +
  zwinięte „Informacje” (`classifyCvWarnings`, nieznany tekst → do sprawdzenia).
