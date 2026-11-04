# Edytor CV 3 — PR 1: podgląd = plik, Montserrat, justowanie (14.10.2026)

Propozycja i makiety: https://claude.ai/artifact/1g1FJJ2TtojTJSFjmZQj5Z (wersja 3).
Decyzje Artura J1–J3 z 14.10.2026: CV domyślnie wyjustowane (reguła klienta może
zmienić), podgląd = strony z pliku (PR 2), kolejność linii stanowiska w edytorze
bez zmian. Reguła: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`, sekcja
„Podgląd = plik dla klienta i justowanie”.

## Co było nie tak (sprawdzone na fikcyjnym CV złożonym kodem z produkcji)

- „Podgląd” w karcie „CV do klienta” i w „Użyj innego CV” wstawiał surowy HTML
  z edytora w stylu strony aplikacji — bez papieru firmowego, tabeli edukacji
  i etykiet „Stanowisko:”, „Nazwa firmy:”.
- Podgląd pliku Word w przeglądarce (docx-preview) rysował CV w Times New Roman:
  aplikacja nie miała Montserrat, a przeglądarka ignoruje zamiennik Calibri,
  który Word bierze z pliku.
- Edytor nie miał wyrównania tekstu, a konwerter do Worda gubił `text-align`
  we wszystkim poza zwykłymi akapitami (punkty, stanowisko, umiejętności…).

## Co weszło

- Podgląd w karcie i w „Użyj innego CV” = plik (`CvFilePreviewDialog` +
  `CvEditorWordPreview`), bez wpisu pobrania; zapas w układzie kartki edytora,
  gdy pliku nie da się pokazać (brak zgody RODO, prawo tylko do odczytu).
- Montserrat w aplikacji (`@font-face` pod nazwami z pliku, licencja OFL, ok. 190 KB,
  pobierane tylko tam, gdzie użyte) — podgląd pliku i kartka edytora mają litery Worda.
- Justowanie: domyślnie wyjustowane w obu rendererach Worda; reguła klienta
  „Wyrównanie tekstu” (migracja 0441 + lustro w `entrypoint.sh`); przyciski
  „Do lewej” / „Wyjustuj” w pasku edytora; jawne wyrównanie akapitu wygrywa
  w każdym bloku treści; kartka edytora pokazuje domyślne wyrównanie CV.

## Testy

- Backend: `tests/test_cv_approved_docx_align.py` (najpierw czerwony: brak
  wyrównania w punktach), `tests/test_cv_text_align_migration_mirror.py`,
  istniejące testy renderera i generatora (233 bez bazy, zielone lokalnie).
  Testy z bazą (API reguł) sprawdza CI.
- Frontend: pasek narzędzi (wyrównanie, zaznaczenie całego CV omija klauzulę,
  zmiana typu akapitu zachowuje wyrównanie), podgląd karty i okna „Użyj innego
  CV” (plik bez intencji pobrania, zapas), `CvEditorWordPreview` (zapas),
  formularz reguły (wysyła `cv_text_align`), harnessy i strażnicy źródeł.
- Zrzuty harnessów 1280×720 (Playwright): podgląd karty w Montserrat z papierem
  firmowym, kartka edytora z przyciskami wyrównania, „Podgląd Word” w Montserrat.

## Świadomie poza zakresem

- Strony A4 w podglądzie („Strona 1 z 2”) — PR 2 (PDF z serwera).
- „Wyjustuj całe CV” w menu „Więcej” — PR 3 (dziś: zaznacz wszystko + „Wyjustuj”).
- CV zatwierdzone bez zmian przed wdrożeniem mają plik z generatora wyrównany
  do lewej; nowe generacje i każda edycja dostają justowanie.
