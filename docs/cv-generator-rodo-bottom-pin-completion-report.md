# CV generator — RODO zawsze na dole ostatniej strony (+ diagnoza boldów)

Data: 2026-07-09. Zgłoszenie: (1) klauzula RODO ląduje u góry strony zamiast na
dole ostatniej strony; (2) brak pogrubień technologii championa w CV.

## 1. RODO — zawsze na dole ostatniej strony (naprawione, kod)

### Diagnoza

`render_cv_to_bytes` używał hybrydy sterowanej szacunkiem wysokości treści
(`_estimate_body_height_pt`):

- krótkie CV (`est < 0.62 * strona`) → `add_bottom_pinned_rodo` (pływająca
  ramka przypięta do dolnego marginesu),
- CV blisko pełnej strony → `add_inflow_rodo` (klauzula w normalnym przepływie).

W **pobranym pliku** (Word/PDF, prawdziwa paginacja) gałąź in-flow powodowała
zgłoszony błąd: gdy treść przelewała się tuż za granicę strony, klauzula
(divider + tekst) spływała na **górę** ostatniej strony z pustym miejscem pod
spodem — „RODO na górze strony". Zreprodukowane: CV 1-zadaniowe → 2 strony,
RODO na 37% wysokości strony 2, 63% pustego miejsca poniżej.

Szacunek `_estimate_body_height_pt` okazał się zbyt niedokładny (zaniża liczbę
stron: CV szacowane na 0.9 strony realnie zajmuje 2 strony w LibreOffice), więc
nie dało się nim wiarygodnie sterować decyzją o page-breaku.

### Zmiana

Klauzula jest **zawsze** renderowana jako przypięta do dołu pływająca ramka
(`add_bottom_pinned_rodo`) — hybryda usunięta. Ramka przypina się do dolnego
marginesu strony, na której siedzi jej kotwica, więc niezależnie od długości CV
klauzula ląduje na dole **ostatniej** strony, wyjustowana, raz, z czerwoną
linią nad nią.

Zweryfikowane w LibreOffice (proxy pobranego pliku) na 5 rozmiarach CV +
przypadek repro: RODO na ~84% wysokości ostatniej strony (dół) we wszystkich
przypadkach (było 37% = góra dla repro).

### Świadomy trade-off (znane ograniczenie)

Biblioteka podglądu w aplikacji (`docx-preview`, modal „Podgląd" w
Wygenerowanych CV) **nie renderuje pływających ramek** (`wps:txbx`). Zweryfikowane
w realnym `docx-preview`: klauzula z pływającej ramki nie pojawia się w DOM
podglądu. Dlatego RODO jest widoczne w **pobranym** DOCX/PDF (plik wysyłany do
klienta), ale nie w podglądzie w apce.

Rozważane alternatywy i dlaczego odrzucone:

- **In-flow zawsze** — widoczne w podglądzie, ale w pobranym pliku wciąż spływa
  na górę następnej strony (nie naprawia zgłoszenia).
- **Stopka strony** — widoczna wszędzie i na dole, ALE powtarza klauzulę na
  **każdej** stronie wielostronicowego CV (sprzeczne z „ostatniej strony") oraz
  rezerwuje miejsce na dole każdej strony (może wydłużyć CV o stronę).
- **`w:pageBreakBefore` + float** — LibreOffice honoruje (świeża strona,
  dół), a `docx-preview` ignoruje bezpośredni `pageBreakBefore` (paginuje tylko
  na `pageBreakBefore` ze STYLU) — ale dokłada pustą stronę do CV, które i tak
  miały miejsce na ostatniej stronie.
- **`mc:AlternateContent` (wps Choice + VML Fallback)** — Word bierze Choice
  (float, dół), `docx-preview` bierze Fallback (`supportedNamespaceURIs = []` →
  zawsze Fallback) i renderuje VML `<v:textbox>` jako `foreignObject`. Tekst
  trafia do DOM, ale `docx-preview` pozycjonuje go na górze (ignoruje
  `mso-position-vertical:bottom`) i przycina — nieużywalne.
- **`vAlign=bottom` na sekcji ciągłej** — LibreOffice nie honoruje (RODO dalej
  na górze).

Float wybrany, bo dokładnie realizuje wybór użytkownika („zawsze na dole
ostatniej strony", raz, bez dodatkowych stron). Rzadki minimalny nachodzenie na
ostatnią linię przy CV wypełniającym stronę w ~85%+ jest akceptowalny (RODO i
tak zostaje na dole, nie na górze). **Jeśli widoczność w podglądzie jest ważna
— przełączenie na stopkę to ~10 linii, kosztem powtórzenia na każdej stronie.**

## 2. Boldy technologii — to problem danych, nie kodu

Potwierdzone end-to-end: generator pogrubia technologie z chipów
`Job.must_skills` + `Job.nice_skills` (sekcja „2. Profil kandydata" =
must-have/nice-to-have). Przy wypełnionych chipach **wszystkie** technologie się
boldują (Python, LangChain, Docker, Kubernetes, REST API, SQL, Git, OpenAI API,
RAG, Neo4j — zweryfikowane na wyrenderowanym DOCX). Ścieżka zapisu też jest
spójna: `CriteriaPreviewV2` → `PATCH /api/jobs/{id}` → `must_skills`/`nice_skills`
→ te same kolumny czytane przez generator.

Wniosek (zgodnie z wyborem użytkownika „tylko chipy Must-have/Nice-to-have"):
brak boldów = chipy must/nice są puste/niepełne dla tej rekrutacji, a technologie
trafiły do CV z opisów free-text championa (kontekst projektu / obowiązki), które
świadomie NIE są źródłem boldowania. **Naprawa = uzupełnić „Kryteria AI —
must-have / nice-to-have" i wygenerować CV od nowa** (samo ponowne pobranie nie
zaciągnie świeżo dodanych chipów — re-render idzie z zapisanego `render_payload`).
Jeśli chipy SĄ wypełnione, a boldów nadal brak — to realny bug, potrzebny konkretny
kandydat/oferta do reprodukcji.

## Pliki

- `backend/app/services/cv_generator_b2b/docx_renderer.py` — RODO zawsze
  bottom-pinned; usunięte martwe `add_inflow_rodo`, `_estimate_body_height_pt` i
  nieużywany import `WD_ALIGN_PARAGRAPH`.
- `backend/tests/test_cv_generator_b2b_pipeline.py` — test pełnostronicowego CV
  zaktualizowany: klauzula floatuje na dół (było: in-flow). Test krótkiego CV bez
  zmian (dalej float).

## Bez zmian

Migracje: brak. Endpointy: brak. Frontend: brak. Logika boldowania: brak (kod
poprawny). Sekcja `add_bottom_pinned_rodo`: bez zmian.

## Weryfikacja

- LibreOffice (DOCX→PDF): RODO na dole ostatniej strony na 5 rozmiarach + repro.
- `docx-preview` (realna biblioteka podglądu, headless w Chrome): potwierdzono
  brak renderu pływającej ramki (znane ograniczenie powyżej).
- Boldy: `compile_keyword_patterns` + pełny render — wszystkie techy championa
  boldują się przy wypełnionych chipach.
- Testy RODO (short + full) przechodzą względem zedytowanego renderera.
- Backend pytest w CI (`test_cv_generator_b2b_pipeline.py` na liście).
