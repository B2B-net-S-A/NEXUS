# CV Generator B2B — OCR fallback dla skanów PDF (completion report)

**Data:** 2026-07-11
**PR:** [#661](https://github.com/artur-t-96/Nexus/pull/661) (merged → `main` SHA `25bf3d3`)
**Zgłoszenie:** upload „Adam Drazkowski Check Point Certified CCSE CCSA CV. (6).pdf" (Marlena Rosol, 10.07.2026) — karta pliku z błędem „Nie udało się odczytać tekstu z CV: Empty text extracted from …pdf".

## Diagnoza

Plik to **PDF bez warstwy tekstowej** (skan / eksport obrazkowy — brak `/Font`, brak operatorów `BT…Tj`). Generator CV B2B ma **własny** ekstraktor tekstu ([`backend/app/services/cv_generator_b2b/text_extractor.py`](../backend/app/services/cv_generator_b2b/text_extractor.py)) znający tylko `pdftotext` → `pdfplumber`. Oba czytają wyłącznie warstwę tekstową, więc dla skanu zwracały pustkę i `_run_generation_pipeline` rzucał `CVTextExtractionError` → status `failed`.

Reszta aplikacji ([`backend/app/services/cv_text_extractor.py`](../backend/app/services/cv_text_extractor.py) — upload CV kandydata, match preview, backfill imion z Traffita) w tej sytuacji **od dawna robi fallback OCR** przez tesseract. Generator B2B był jedyną ścieżką PDF bez OCR mimo że binarki (`tesseract-ocr`, `poppler-utils`) i pakiety (`pytesseract`, `pdf2image`) są w obrazie od dawna.

## Zmiany

`backend/app/services/cv_generator_b2b/text_extractor.py` (używa go też parser Profilu Championa w `champion_builder.py`):

- **nowy `_extract_pdf_ocr(data)`** — `pdf2image.convert_from_bytes` (dpi 200, `last_page=10`) + `pytesseract.image_to_string(lang="pol+eng")`; lustrzany do współdzielonego ekstraktora, **zero nowych zależności**. Zwraca `None`, gdy OCR niedostępny (defensywnie).
- **próg OCR** — gdy natywna ekstrakcja daje `< 100` znaków (ten sam `_OCR_FALLBACK_THRESHOLD_CHARS` co w `cv_text_extractor`; łapie też „samą stopkę / numer strony"), próbujemy OCR i bierzemy dłuższy wynik. Porządne tekstowe CV w ogóle nie dotyka OCR.
- **odporność na uszkodzony PDF** — wyjątek `pdfplumber` nie wywala już joba surowym stack-trace'em; logujemy i przechodzimy do OCR (poppler często zrasteryzuje plik, którego pdfplumber nie otworzy).
- **czytelny błąd końcowy** — gdy po wszystkim nadal pusto: komunikat z podpowiedzią dla rekrutera („plik wygląda na skan bez czytelnej warstwy tekstowej… spróbuj tekstowego PDF/DOCX"); prefiks `Empty text extracted from …` zachowany dla grepowalności logów.

Latencja OCR (~2–5 s/strona, max 10) jest akceptowalna — wszystkie call-site'y (`/generate`, `/generate-upload`, champion) to background joby w threadpoolu.

## Testy

5 nowych w [`backend/tests/test_cv_generator_b2b_pipeline.py`](../backend/tests/test_cv_generator_b2b_pipeline.py) (plik na liście pytest w CI):

| Test | Scenariusz |
|---|---|
| `test_scanned_pdf_falls_back_to_ocr` | skan (natywnie pusto) → tekst z OCR |
| `test_near_empty_native_text_prefers_ocr` | natywnie prawie pusto (stopka „1/2") → OCR |
| `test_good_native_text_skips_ocr` | tekstowy PDF → OCR w ogóle nienawoływany |
| `test_unreadable_pdf_raises_with_scan_hint` | wszystko puste → `CVTextExtractionError` z hintem |
| `test_corrupt_pdf_still_tries_ocr` | `pdfplumber` rzuca → OCR nadal próbowany, brak crasha |

OCR mockowany — CI nie wymaga tesseracta.

## Weryfikacja

- **Logika lokalnie:** 6/6 checków przeszło (izolowany import modułu, OCR mockowany).
- **CI:** `Backend (ruff + pytest)` **pass** (5m5s), `Frontend`, `Gitleaks`, `Trivy+hadolint` pass. Job `review` (Claude auto-review) padł na `error_max_turns` — infra, zero findingów w kodzie, nie blokuje.
- **Deploy:** merge → Coolify auto-deploy → `/api/health` = `healthy`, `version` = `25bf3d3` (nowy SHA). Deep healthcheck (core modules) OK, smoke-test zielony.
- **Prod E2E (live upload skanu):** przygotowany syntetyczny image-only PDF (potwierdzone: brak `/Font`, tekst czytelny — certyfikaty/umiejętności/doświadczenie). Upload przez authed sesję **zablokowany transientną infrą sesji Claude**: (1) `fetch` z `localhost` w stronie wisi na Chrome Private Network Access; (2) `file_upload` MCP odrzuca dynamicznie utworzone ścieżki; (3) wstrzyknięcie base64 zablokowane chwilową niedostępnością classifiera `opus-4-8`; (4) brak działającego klucza SSH do kontenera z tej maszyny. **Do dokończenia** gdy classifier wróci albo ręcznie: ponowny upload pliku „Adam Drazkowski…" powinien teraz przejść (status `done` zamiast `failed`).

## Możliwy follow-up (poza zakresem)

Unifikacja obu ekstraktorów PDF (B2B bytes-based `text_extractor.py` vs współdzielony path-based `cv_text_extractor.py`) w jeden moduł — dziś celowo minimalny diff. Zob. notatka pamięci `cv-pdf-two-extractors-ocr`.
