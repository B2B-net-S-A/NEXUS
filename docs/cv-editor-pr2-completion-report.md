# Edytor CV 2 — PR 2: panel „Do poprawy” (12–13.10.2026)

Drugi z pięciu PR-ów zatwierdzonych przez Artura 12.10.2026 (decyzje D1–D6,
makiety prywatne). PR 1 dał edytor na cały ekran bez AI; ten dokłada panel,
w którym to, co system już wie o CV, stoi przy tekście i daje się poprawić
jednym kliknięciem. Reguły: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`,
sekcja „Panel »Do poprawy«”.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Panel w edytorze | Po prawej „Do poprawy”: karty QC CV (te same co w oknie QC), uwagi generatora, uwagi kontroli AI ostatniej zatwierdzonej wersji. Licznik „Do poprawy (N)” w pasku, „Blokuje wysyłkę: N” w panelu |
| „Pokaż w CV” | Każda uwaga z miejscem w tekście przewija do niego kartkę i wyróżnia je. Miejsca uwag są zaznaczone w tekście (czerwone zatrzymuje wysyłkę) |
| Poprawka jednym kliknięciem | Serwer liczy poprawkę na treści z edytora (`POST …/qc/transform`, bez zapisu szkicu), edytor nakłada ją jednym krokiem, autozapis ją utrwala. Jedno „Cofnij” zdejmuje poprawkę |
| „Popraw wszystko” | Pogrubienie wymagań, pisownia technologii, zdania AI z cytatem ze źródła. Usunięcie treści i własne poprawki pojedynczo. Wynik z przyciskiem „Cofnij” i listą pominiętych |
| Lista po zmianie | Odświeża się 1,5 s po autozapisie; przebieg QC dla Tablicy zapisuje się raz, przy zamknięciu edytora |
| Okno QC | Poprawka niesie wersję szkicu: gdy edytor obok zapisał zmianę, okno dostaje 409 „odśwież listę” zamiast nadpisać treść. Klauzula zgody jest stała także dla poprawek QC |
| Liczenie ról w QC | Rola kończy się na nagłówku sekcji (h1/h2). Śródtytuł h3/h4 w opisie stanowiska nie zamyka już roli i nie gasi kolejnych stanowisk (`QC_VERSION` podbite — nieudane przebiegi przeliczą się przy starcie) |
| Układ | Laptop 1280: obok kartki jeden panel (źródła albo „Do poprawy”); od 1540 px oba; węziej przełącznik kolumny |

Backend: trasy `GET …/cv/branded/issues` i `POST …/qc/transform`, parametr
`transient` w `GET …/qc`, pole `expected_revision` w `qc/apply`. Bez migracji.

## Odstępstwa od makiet (do wiadomości Artura)

| Makieta | Jest | Dlaczego |
|---|---|---|
| „Popraw wszystko” poprawia też tytuł CV | Bez tytułu | Sprawdzenie `title_matches_role` nie ma w kodzie żadnej poprawki; osobna decyzja, czy QC ma uznawać przetłumaczony tytuł |
| Źródła i „Do poprawy” jednocześnie obok kartki | Przy 1280 px jeden panel naraz | Źródła 440 + kartka 794 + panel 360 = 1594 px; oba mieszczą się od 1540 px |
| „Sprawdź teraz” dla kontroli AI | Brak | Kontrola AI jest płatna i biegnie po „Zapisz”; panel pokazuje wynik ostatniej zatwierdzonej wersji |
| Poprawki zapisywane od razu | Liczone na treści z edytora, zapisuje autozapis | Zapis po stronie serwera dawał edytorowi 409 przy następnym autozapisie |
| Panel także w edytorze wyniku generatora | Tam tylko uwagi generatora | QC czyta CV etapu, nie widzi edycji wyniku generatora |

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Logika panelu | zielone lokalnie | `lib/__tests__/cv-editor-issues.test.ts` (23), `cv-editor-issue-marks.test.ts` (5) — prawdziwy edytor Tiptap |
| Osobny krok historii | odtworzone i naprawione | test „poprawka jest osobnym krokiem historii” pada bez `closeHistory` (sprawdzone), przechodzi z nim |
| Panel | zielone lokalnie | `cv-editor/__tests__/CvEditorIssues.test.tsx` (16): lista, awarie, „Pokaż w CV”, poprawka, „Popraw wszystko” z cofnięciem, treść zmieniona w trakcie liczenia |
| Okno edytora | zielone lokalnie | `CVBrandedEditModal.issues.test.tsx` (9): układ przy 768 / 1280 / 1600, szkic przed poprawką; `CVBrandedEditModal.test.tsx` (16) bez zmian zachowania |
| Okno QC po wyniesieniu kart | zielone lokalnie | 5 plików testów korzystających z `CvQcDialog`: 300 testów |
| Harness | zielone lokalnie | `cv-editor-harness.test.tsx` (7): pełny obieg bez sieci; `harness-seeds.test.ts` |
| Backend bez bazy | zielone lokalnie | `tests/test_cv_qc.py` 89 testów, `test_cv_editor_issues.py` 13, wzorzec uprawnień (`authz_golden`: 2 nowe trasy, ten sam wzorzec co sąsiednie) |
| Backend z bazą | w CI | 3 nowe testy z bazą (`qc/apply` z wersją, `qc/transform`, `…/issues`); lokalnie nie ma Postgresa |
| Przeglądarka | przeklikane | harness `/preview/cv-editor` przy 1280×720, 768×1024, 390×844: lista, znaczniki, „Pokaż w CV”, „Popraw wszystko”, „Cofnij”, zdanie AI, usunięcie terminu, świeża lista po autozapisie, poprawka na zatwierdzonej wersji (zakłada szkic), stany „bez uwag”, „QC niedostępne”, „wynik generatora”; konsola bez błędów, brak poziomego przewijania |

## Świadomie poza zakresem

- „Sprawdź teraz” (kontrola AI na żądanie) i poprawka tytułu — patrz odstępstwa.
- Propozycje AI liczone na treści z edytora: `qc/fixes` czyta zapisany szkic,
  więc propozycja może dotyczyć linii zmienionej po zapisie. Serwer odpowiada
  wtedy „pominięto” z powodem, a panel pokazuje go rekruterowi.
- Usunięcie terminu działa jak w oknie QC — tylko na listach technologii.
  Termin w zdaniu rekruter poprawia ręcznie („Pokaż w CV” wskazuje miejsce).
- Skrót klawiszowy w komunikacie to „Ctrl+Z” (docelowy sprzęt to laptopy
  z Windows); na Macu działa ⌘Z.

## Niepotwierdzone

- Zachowanie na produkcji — do sprawdzenia po wdrożeniu (`/api/health` → SHA
  z maina, otwarcie edytora na prawdziwym CV bez zapisu zmian).
- Wpisy `cv_qc_fix_applied` z `via: "editor"` — pojawią się po pierwszej
  poprawce z panelu.
