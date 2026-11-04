# Gotowe CV do klienta czy CV kandydata — pytanie przy pliku z dysku (29.10.2026)
<!-- indeks: „Użyj innego CV” → „Gotowe CV do klienta z dysku (bez AI)”, `b2b_template` z `import-preview`, „Wygeneruj z tego pliku”, znacznik „z pliku Word” w QC -->

Decyzja Artura z 29.10.2026 (wariant B z makiet). Rekruter wgrał świeże CV
kandydatki przez okno „Użyj gotowego CV” → plik z dysku, myśląc, że je
„generuje”. Ta droga (12.10.2026) z założenia zapisuje plik Word jako CV do
klienta 1:1, bez AI — klient dostałby układ kandydatki („Professional
Summary”, pusta kolumna dat w edukacji), a QC tego nie wyłapało, bo znacznik
„z pliku Word” był tylko w karcie.

- **Nazwa sekcji mówi, co robi:** „Gotowe CV do klienta z dysku (bez AI)”,
  pole „Wgraj gotowe CV do klienta (bez AI)” i zdanie, że CV kandydata wgrywa
  się kafelkiem „Wgraj nowe CV” i generuje przyciskiem „Generuj CV”.
- **Plik bez układu szablonu B2B zatrzymuje się na pytaniu w oknie** (nie
  w `useConfirmV2()`: Esc i krzyżyk zwracają tam to samo, co „Użyj tak, jak
  jest”, więc ucieczka zapisałaby CV kandydata jako CV do klienta). „Wygeneruj
  z tego pliku” wysyła plik jak kafelek „Wgraj nowe CV”, ale zawsze jako CV
  kandydata (`…/cv/original/upload`, `mode: "original"`, także dla nazwy
  „B2B_…”), a karta otwiera panel generowania. „Użyj tak, jak jest” to
  dawna ścieżka `…/cv/branded/upload`.
- **Rozpoznanie jest na serwerze**, przed zapisem: okno woła
  `POST …/cv/branded/import-preview` (nic nie zapisuje) i patrzy na
  `b2b_template`. Liczą się tylko linie, które ma sam szablon
  (`cv_docx_import._template_markers`): nagłówek „Dlaczego nasz kandydat?” /
  „WHY OUR CANDIDATE?” i etykiety „Nazwa firmy:”/„Company:”/„Stanowisko:”/
  „Position:” z `docx_renderer.TRANSLATIONS`. „Summary”, „Experience”,
  „Skills” ma też zwykłe CV kandydata, więc się nie liczą. Brak pola
  (starszy serwer) = plik przechodzi bez pytania.
- **QC pokazuje pochodzenie:** szkic z `source: document` w metadanych ma
  w wyniku QC `cv.from_word_file` i nazwę pliku w `cv.filename`; znacznik
  „z pliku Word” (`QcWordFileNote` w `cv-qc-cards.tsx`) stoi w oknie QC CV
  i w panelu „Do poprawy” edytora — tak samo jak w karcie „CV do klienta”.
