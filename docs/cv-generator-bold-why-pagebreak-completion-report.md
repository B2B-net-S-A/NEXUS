# CV Generator — bold wszystkich wymagań + krótsza „Dlaczego" + naturalne łamanie stron

**Data:** 2026-06-16
**PR:** [#503](https://github.com/artur-t-96/Nexus/pull/503) (kontynuacja [#500](https://github.com/artur-t-96/Nexus/pull/500))
**Moduł:** `/cv-generator` (B2B Network branded DOCX)

## Kontekst

Trzy zgłoszenia rekruterów po wdrożeniu #500 (które zawęziło boldowanie i dodało „blokowy" układ stron).

## 1. Boldowanie — wszystkie pokrycia must-have/nice-to-have

**Było:** generator pogrubiał tylko CZĘŚĆ wymagań klienta.
**Jest:** pogrubia wszystkie treści CV pokrywające się z must-have/nice-to-have z Profilu Championa.

**Root cause:** wpisy Profilu Championa są często pisane naturalnie (`Znajomość Java`, `Dobra znajomość Spring Boot`). Po #500 matchowanie było całofrazowe → keyword `Znajomość Java` nigdy nie trafiał w samo `Java` w treści CV, więc bold „znikał".

**Fix** (`docx_renderer.py`):
- nowy `_significant_subphrases()` — runy słów wypełniających/proficiency (`znajomość`, `mile widziane`, `zaawansowana`, `dobra`…) i stop-words działają jako **separatory**; realny termin w środku frazy nadal się pogrubia:
  - `Znajomość Java` → `["Java"]`
  - `Dobra znajomość Spring Boot` → `["Spring Boot"]`
  - `Java i Python` → `["Java", "Python"]`
- termin **bez** wypełniacza zostaje całością → `Design System` pogrubia się jako fraza, ale **nigdy** samo słowo `system` w prozie
- kontrakt z #500 zachowany: `Kubernetes (K8s)` (oba warianty), `Figma (zaawansowana znajomość)` (tylko `Figma`), tolerancja `auto-layout` ↔ `auto layout`

## 2. Sekcja „Dlaczego nasz kandydat" — minimalnie krótsza

**Było:** sekcja minimalnie za długa.
**Jest:** minimalnie krótsza.

**Fix** (`prompts.py`, PL+EN):
- `3-5` punktów → `3-4` zwięzłe punkty (1-2 linijki każdy)
- schemat skrócony z 5 do 4 linii (certyfikaty+metodologie scalone)
- dodana reguła ZWIĘZŁOŚCI w `ZASADY DLA WHY_POINTS` / `RULES FOR WHY_POINTS`

## 3. Łamanie stron (DOCX) — Enter rusza o 1 wiersz, nie o kilka

**Było:** ręczne przeniesienie Edukacji na 2. stronę Enterem nie lądowało na samej górze; Enter przesuwał o kilka wierszy przy zmianie strony.
**Jest:** Enter przesuwa tekst o 1 wiersz, także przy zmianie strony.

**Root cause:** `keep_with_next` (#478) + `keep_together` (#500) sklejały nagłówki sekcji, 4-wierszowe nagłówki ról, bullety i skille w bloki, które przy granicy strony skakały całością — ręczna edycja w Wordzie „walczyła".

**Fix** (`docx_renderer.py`): usunięty `keep_with_next` / `keep_together` z nagłówków sekcji, nagłówków ról, bulletów, skilli i linii `Technologie:`. Dokument płynie wiersz-po-wierszu pod domyślną obsługą sierot Worda. **Świadome odwrócenie** „blokowego" podejścia z #500 — priorytetem jest przewidywalna ręczna edycja (rekruterzy hand-tunują każde CV w Wordzie).

## Pliki

- `backend/app/services/cv_generator_b2b/docx_renderer.py` — `_significant_subphrases` + integracja w `compile_keyword_patterns`; usunięcie keep_*
- `backend/app/services/cv_generator_b2b/prompts.py` — why_points PL+EN
- `backend/tests/test_cv_generator_b2b_pipeline.py` — 3 nowe testy phrase-split

## Weryfikacja

- 35 testów `test_cv_generator_b2b_pipeline.py` + `_headers.py` zielonych (3 nowe)
- `ruff format --check` + `ruff check` czyste (CI ma oba kroki osobno)
- render realnego CV → PDF (LibreOffice `soffice`): bold wszystkich wymagań (`Java`/`Spring Boot`/`Design System`/`Figma`/`auto layout`), zero `keepNext`/`keepLines`, czysty 1-stronicowy układ, generyczne słowa (`znajomość`, `system`) niepogrubione

## Znane ograniczenia

- Concatenowane warianty (`React` vs `ReactJS`/`NodeJS`) wciąż nie są bold — celowo, by uniknąć regresji over-bold (`Git` → `digital`). Word-boundary trzyma granice.
- Bardzo opisowe frazy wymagań (`Doświadczenie w budowie systemów rozproszonych`) bez czystego tech-tokena → bold tylko gdy fraza pojawi się dosłownie (bezpieczny brak over-bold).
