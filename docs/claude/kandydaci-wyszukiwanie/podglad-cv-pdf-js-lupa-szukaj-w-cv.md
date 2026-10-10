# Podgląd CV: pdf.js + lupa „Szukaj w CV” (09.2026)

PDF w podglądzie dokumentu (`FilePreviewContent`/`FilePreviewModal`, snapshot
`CVOriginalPreviewModal`) renderuje **pdf.js** (`SearchablePdfPreview` →
`PdfDocumentViewer`), NIE `<iframe>` z natywną przeglądarką Chrome. Do wnętrza
iframe kod strony nie ma dostępu, więc Ctrl+F przeszukiwał stronę POD oknem.

- **Nie wracaj do `<iframe>`** — zabiera wyszukiwanie. Druk = „Pobierz”.
- `pdfjs-dist` przypięty dokładnie (≥ 6.2.108 — CVE-2026-16633: wykonanie JS z PDF-a; CV to niezaufane pliki); `pdf_viewer.mjs` czyta `globalThis.pdfjsLib`
  przy ewaluacji, więc `lib/pdfjs-loader.ts` podpina bibliotekę PRZED importem
  viewera, a worker to jeden współdzielony `new Worker(new URL(…))`.
- CSS to wycinek `pdf_viewer.css` w `files/pdf-viewer.css` (oryginał 266 KB) —
  przy podbiciu wersji porównaj sekcje `.pdfViewer .page` i `.textLayer`.
- Wyszukiwanie: PDF przez `PDFFindController` (bez wielkości liter i polskich
  znaków), DOCX przez `lib/document-text-search.ts` z tą samą regułą (trafienie
  przez runy Worda, nigdy przez granicę akapitu, bez treści `<style>`). Skan
  i obraz = komunikat „brak tekstu”, bez OCR (decyzja Artura).
- Ctrl+F (`use-document-find-shortcut.ts`): w oknie zawsze, w podglądzie
  osadzonym (profil kandydata) tylko przy kursorze/fokusie w podglądzie. Esc
  w polu z tekstem czyści pole — okna podpinają `keepDialogOpenOnDocumentSearchEscape`
  (Radix łapie Esc w capture, `stopPropagation` w polu nie wystarcza).
- Harness: `/preview/cv-search` (pliki fikcyjne w `public/preview/cv-search/`).
