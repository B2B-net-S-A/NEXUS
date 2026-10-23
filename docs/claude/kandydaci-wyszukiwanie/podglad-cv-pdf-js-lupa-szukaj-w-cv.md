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

## „Szukaj w CV” przy wymaganiu szuka słów, nie etykiety (16.10.2026)

Do tej daty przycisk wklejał do lupy całą etykietę („.NET lub C#”, „Java 17”,
„SQL (bardzo dobra znajomość)”) i lupa szukała jej jako jednej frazy — w CV
takiego zdania nie ma, więc „Brak wyników”, choć C# stał w CV.

- Słowa liczy serwer: `requirement_find_words` w odpowiedzi
  `GET /api/jobs/{id}/champion-profile` (`champion_intake.requirement_find_words_payload`)
  — etykieta → słowa dla KAŻDEGO wymagania („Musi mieć” i „Mile widziane”,
  z profilu i z kolumn rekrutacji). Reguła ta sama co bramka i „Szukaj ręcznie”
  (`keyword_suggest.requirement_find_words`: opcje jak `gate_requirement`, warianty
  nazw ze Słownika umiejętności), a krytyczna z wyboru DL dostaje też słowa
  swojego wiersza (rdzeń `kolejk*` bez gwiazdki — w lupie to fragment słowa).
  Jedyna różnica wobec wiersza słów kluczowych: opcja jednoliterowa tylko odpada
  („C lub C++” → „C++”), bo lupa podświetla, a nie wycina.
- Nie liczyć słów w przeglądarce: kliencki `labelOptions` jest uproszczony
  („OWASP Top 10” → „OWASP Top”, nawias zostaje w całości).
- Pole pokazuje nazwę wymagania, lupa szuka listy (pdf.js przyjmuje `query`
  jako tablicę, DOCX — `findMatchOffsets` z listą, dłuższe słowo wygrywa).
  Pod paskiem linia „Szukam: …”, bez trafień „Szukałem: … — tej nazwy nie ma
  w CV” (`DocumentSearchTerms`). Ręczna zmiana pola = zwykła fraza, linia znika.
  Cytat z edytora CV („Pokaż w oryginale”) zostaje frazą — zlecenie bez `terms`.
- Brak słowa w słowniku („Unit Tests” vs „unit testing”, „OWASP Top 10” vs
  „OWASP”) naprawia alias w Ustawienia → Słownik umiejętności, nie kod.

## Okno CV listy: kolejna osoba, „Przypisz”, ślad „✓ CV” (23.10.2026)

Prośba rekruterów: przegląda się CV z listy kandydatów, zamyka okno i potem
nie wiadomo, czyje to było; do tego każde kolejne CV to zamknij–znajdź–otwórz.
Decyzja Artura: przycisk w oknie + ślad + przejście między osobami.

- Okno CV listy żyje na poziomie listy (`CandidateCvBrowser`), nie w komórce.
  `CandidateCvCell` tylko je otwiera (`onOpen`). Nie wracaj do okna w komórce:
  nie przejdzie wtedy do następnego wiersza.
- „‹ Poprzednia · Osoba 3 z 50 · Następna ›” chodzi po osobach z CV z bieżącej
  strony listy, w jej kolejności; Shift + ←/→ to samo z klawiatury (same
  strzałki przełączają pliki CV jednej osoby, dlatego `FilePreviewModal`
  ignoruje strzałki z Shiftem). Napisy przy strzałkach są celowe — obok stoją
  strzałki plików. Osoba bez pliku: komunikat, zostaje poprzednia.
- Przejście przewija listę do wiersza tej osoby; po zamknięciu fokus i pasek
  są na ostatnio oglądanej, nie na tej, od której się zaczęło (Radix wracałby
  na przycisk „CV” pierwszej osoby — `onCloseAutoFocus`).
- W nagłówku „Przypisz do rekrutacji” przed „Pobierz” i imię osoby pod nazwą
  pliku. Przycisk otwiera ten sam panel co „Rekrutacja” w wierszu
  (`QuickAssignV2`) i zamyka okno CV, bo panel to Sheet (z-50), a okno to
  Dialog (z-110) — panel byłby pod spodem. W oknie rekrutacji („Szukaj
  ręcznie”) przycisku nie ma — tam wiersz ma własne „Dodaj”.
- Obejrzane CV ma w wierszu ✓ (godzina w dymku), ostatnio oglądany wiersz pasek
  z lewej. Pamięć karty (`readCvSeen` / `markCvSeen` w `lib/search-memory.ts`,
  sessionStorage), nie serwer. Bez plakietki z napisem: przy 1280 px ścinała
  nazwisko. Otwarcie CV nie zapisuje `lastOpenedId` listy (plakietka „Ostatnio
  otwarta” zostaje dla powrotu z profilu).
