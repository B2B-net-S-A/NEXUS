# Edytor CV 3 — PR 2: strony jak u klienta (PDF z pliku Word) (14.10.2026)

Propozycja i makiety: https://claude.ai/artifact/1g1FJJ2TtojTJSFjmZQj5Z (wersja 3).
Decyzja J2 Artura z 14.10.2026: podgląd = prawdziwe strony z serwera. Reguła:
`docs/claude/generator-cv/edytor-cv-pelny-ekran.md`, sekcja „Strony jak
u klienta: PDF z pliku Word”. PR 1 (Montserrat w aplikacji, justowanie,
„Podgląd” w karcie = plik) jest bazą tej zmiany.

## Co było nie tak

- Po PR 1 podgląd miał już litery i układ pliku, ale nadal nie miał stron:
  docx-preview rysuje dokument jednym ciągiem, bez podziału na A4, bez
  przypięcia klauzuli zgody do dołu ostatniej strony i z różnicami zależnymi
  od przeglądarki oglądającego.

## Co weszło

- Backend: `services/cv_pdf_preview.py` zamienia TEN SAM plik Word, który
  pobiera „Pobierz Word”, na PDF (LibreOffice headless). Jedna zamiana naraz,
  limit czasu 45 s, własny profil i osobna grupa procesów na zamianę, pamięć
  wyników po treści pliku Word (32 pozycje, 30 min). Każda awaria = 503 z
  polskim komunikatem; PDF bez Montserrat przy CV pisanym Montserrat też (nie
  pokazujemy stron w zastępczej czcionce).
- Trasy (`api/cv_pdf_preview.py`, limit 20/min na osobę), z bramkami
  odpowiedników DOCX: szkic etapu (`POST …/cv/branded/preview-pdf`), wersja
  zatwierdzona (`GET …/versions/{n}/pdf`), edytor wyniku generatora
  (`POST …/editor/preview-pdf`). Zgoda RODO jak przy DOCX; pobranie z
  `intent=download` zapisuje wpis z formatem `pdf`, podgląd nie zapisuje nic.
- Obraz backendu: `libreoffice-writer-nogui`, `fonts-crosextra-carlito`,
  `fontconfig` + Montserrat z repo (`app/assets/fonts/montserrat/`, statyczne
  wagi z nazwami rodzin z pliku CV, licencja OFL) i `fc-cache`.
- Front: `CvPagesPreview` (pdf.js: strony, „Strona 1 / 2”, powiększenie,
  „Szukaj w CV”) w „Podglądzie” karty, w „Użyj innego CV” i w edytorze —
  przełącznik „Edycja | Jak u klienta” (było „Podgląd Word”). Zapas przy
  każdej awarii: plik Word w przeglądarce (PR 1), a pod nim treść w układzie
  kartki.
- Harnessy `/preview/cv-to-client` i `/preview/cv-editor` pokazują strony
  z `public/preview/cv-to-client/cv-firmowe-przyklad.pdf` (fikcyjne CV,
  LibreOffice z Montserrat, metadane bez autora).

## Testy

- Backend (bez bazy, lokalnie zielone): `tests/test_cv_pdf_preview.py`
  (20: zamiana i pamięć, ten sam szkic złożony od nowa bez drugiej zamiany,
  wygaśnięcie, limit czasu zabija proces, brak LibreOffice, wynik nie-PDF,
  awaria, rozmiar, zajęte miejsce, własny profil bez HOME, czcionka Montserrat
  w PDF-ie, nazwy rodzin w plikach czcionek, kolejka w pętli zdarzeń, OSError,
  środowisko bez sekretów), `tests/test_cv_pdf_preview_routes.py`, strażnicy tras
  (`test_cv_consent_download_gate.py`, `test_cv_download_log.py`,
  `test_public_surface_hardening.py`). Testy z bazą sprawdza CI.
- Frontend: `CvPagesPreview.test.tsx` (strony, zapas po 503, zapas po błędzie
  pdf.js), karta, „Użyj innego CV”, okno edytora (strony najpierw, plik Word
  jako zapas), harnessy (bez sieci), inwentarz funkcji (`cv.editor-pages-preview`).
  `npm run type-check` i eslint zmienionych plików czyste.
- Zrzuty harnessów 1280×720 (Playwright): okno „Podgląd” karty — strona 1 z 2
  w Montserrat z papierem firmowym; edytor „Jak u klienta” — strony 1 i 2.
  Pierwszy zrzut edytora pokazał pudełko stron o wysokości 0 px (kartka jest
  blokiem z przewijaniem) — poprawione (`absolute inset-0`) i sprawdzone ponownie.
- Obraz backendu buduje job „E2E stack” w kolejce merge'ów — on sprawdzi
  instalację LibreOffice przed scaleniem. Na produkcji po wdrożeniu:
  `/api/health` z SHA i PDF wersji zatwierdzonej (odczyt).

## Przeglądy przed PR-em (python, TypeScript, bezpieczeństwo) i co z nich weszło

- Trasa edytora wyniku generatora trzymała blokady `FOR UPDATE` szkicu przez
  czekanie i zamianę (do 75 s) — autozapis tego CV stałby razem z nią.
  Poprawka: `db.commit()` przed zamianą we wszystkich trzech trasach; test
  `tests/test_cv_pdf_preview_routes.py` (kolejność: blokada → commit → zamiana
  → wpis pobrania), na starym kodzie pada.
- Czekanie na miejsce zajmowało wątek wspólnej puli (40 na proces) — kilka
  podglądów naraz mogło zablokować inne trasy. Poprawka: kolejka w pętli
  zdarzeń, najwyżej 4 czekających, wątek tylko na samą zamianę; test pokazuje,
  że pula jest wolna mimo pełnej kolejki.
- `OSError` przy starcie LibreOffice (fork, pełny `/tmp`) dawał 500 — teraz 503
  i zapas. LibreOffice dostaje tylko `PATH`, `LANG`, `LC_*`, `FONTCONFIG_*`.
- Esc w „Szukaj w CV” zamykał okno podglądu — teraz czyści zapytanie (test
  pada bez poprawki).
- Bramki: parytet z trasami DOCX potwierdzony; moduł w kontrakcie zakresu,
  wzorzec `tests/data/authz_golden/cv_pdf_preview.json` z tymi samymi literami.

## Koszt

- Obraz backendu rośnie o LibreOffice Writer bez GUI (szacunkowo 200–300 MB,
  niepotwierdzone — rozmiar pokaże pierwszy build w Coolify).
- Zamiana kosztuje ok. 2 s procesora serwera; jedna naraz, limit 20/min na osobę.

## Świadomie poza zakresem

- Po przerwaniu zamiany (limit 45 s) proces `soffice.bin` może zostać jako
  zombie (PID 1 w kontenerze to uvicorn, który nie zbiera osieroconych
  procesów). Dotyczy tylko przerwań; liczba zajmuje wpis w tablicy procesów,
  nie pamięć. Do rozważenia `tini` w obrazie, jeśli przerwania się zdarzą.

- Panel osoby i przegląd DL (`StageCvPreview`) zostają na docx-preview —
  otwierają się przy każdej osobie; strony PDF tam = osobna decyzja o koszcie.
- Miniatura pierwszej strony i liczba stron na karcie „CV do klienta” — PR 3.
- „Pobierz PDF” jako przycisk — PR 3 (menu „Więcej” i „⋯” karty); trasy już
  przyjmują `intent=download`.
