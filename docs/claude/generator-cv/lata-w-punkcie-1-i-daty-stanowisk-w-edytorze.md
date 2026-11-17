# Lata w punkcie 1 i daty stanowisk w panelu „Do poprawy” (R2–R3, 17.11.2026)

<!-- indeks: `years_breakdown`, `role_dates_reversed`, `role_year_only`, `tenure_split`, `swap_dates`, `show_original`, `kept_years`, `cv_tenure_checks` -->

Pomiar 17.11.2026 na 126 CV zatwierdzonych 09–16.11 (kopia produkcji na
stagingu, raport: https://claude.ai/artifact/K3jm8gcpR3JTajaQW825VY, prywatny):
w 24 CV rekruter podniósł liczbę lat w punkcie 1 „Dlaczego nasz kandydat”,
bo generator liczy tylko role o tej samej nazwie, a rekruter cały staż razem
z rolami pokrewnymi. 25 CV miało role z samym rokiem, w 17 z nich oryginał
podaje miesiące. Jedna rola „08.2021 – 09.2019” zaniżyła staż z 7 do 5 lat.
Artur zatwierdził R1–R4. Generator (prompt 14, „N lat w IT, w tym M lat jako
X”, miesiące ze źródła) zmienia osobny PR; ta reguła dotyczy tylko uwag
w edytorze, bez zmian w prompcie i w `legacy_v7`.

## Trzy uwagi QC (nie blokują)

Kod w `backend/app/services/cv_tenure_checks.py`, sprawdzenia w
`cv_qc.compute_checks` (na końcu `WARNING_KEYS`). Wszystko liczy kod z treści
CV i tekstu oryginału, bez AI. Bez znaczników stanowisk (`data-cv-section="role"`,
CV wklejone) każda z trzech uwag „nie dotyczy”, jak „Daty stanowisk jak
w oryginale”: role są wtedy zgadywane.

- **`years_breakdown` „Lata w punkcie 1 z dat stanowisk”.** Bierze pierwszy
  punkt sekcji `why_points` i pierwszą liczbę lat w nim (`_YEARS_PHRASE_RE`
  z `legacy_v7._helpers`). Rola pasuje, gdy jej nazwa (pogrubiona część linii
  stanowiska) stoi we frazie po liczbie do końca zdania składowego („w rolach
  Cloud Operations Engineer i DevOps Engineer”) albo zawiera stanowisko po
  „jako” / „as”. Pozycja niesie `tenure`: sumę dat ról pasujących, cały staż
  z dat wszystkich ról (miesiące, nakładki raz, „obecnie” do bieżącego
  miesiąca, rok bez miesiąca od stycznia do grudnia) i listę ról z miesiącami.
  Rola bez dat albo z odwróconymi datami stoi na liście bez miesięcy i nie
  wchodzi do żadnej sumy.
  - Cały staż dłuższy o co najmniej 12 miesięcy (`GAP_MONTHS`) → pozycja do
    decyzji z propozycją `proposal` „Ponad N lat w IT, w tym ponad M lat jako X”
    (EN „Over N years in IT, including over M years as X”), liczby jak
    `_tenure_text` (pełne lata w dół, „Ponad” od 3 dodatkowych miesięcy).
    X to stanowisko po „jako”, a bez niego nazwy pasujących ról.
  - Mniejsza różnica, żadna rola z punktu 1 albo punkt już w formie
    „w tym / including” → zaliczone, rozkład w `info`, a „W porządku” pokazuje
    obie sumy. Punkt po PR-ze generatora nie dostaje drugiej propozycji.
  - Rekruter decyduje, bo role spoza obszaru (gastronomia, sklep) też liczą się
    do całego stażu. Dlatego przycisk propozycji nie wchodzi do „Popraw
    wszystkie” (`BULK_ACTIONS`), a „Zostaw N” zapisuje pominięcie z powodem
    `kept_years` (tylko przy tej uwadze, nie „nieprawda”). Klucz pominięcia
    stoi na liczbie z punktu 1 (`term`), nie na zdaniu z miesiącami, które co
    miesiąc rosną.
- **`role_dates_reversed` „Data końca stanowiska po dacie startu”.** Okres
  z linii stanowiska (`cv_source_dates.line_period`, ostatni w linii, także
  odwrócony — `date_ranges` takie pomija, bo w oryginale to zwykle dwa okresy
  z układu kolumn). Rok bez miesiąca nie przeczy dacie z tego samego roku.
  Pozycja ma `term` (okres w CV) i `proposal` (zamienione daty, ten sam łącznik).
- **`role_year_only` „Miesiące w datach stanowisk jak w oryginale”.** Rola
  z samym rokiem na starcie albo końcu, gdy oryginał ma miesiąc przy tym roku:
  najpierw okres tej roli w oryginale (firma albo stanowisko do 400 znaków
  obok), potem każda data z miesiącem w tym roku. To szacunek z góry, więc
  uwaga tylko odsyła do oryginału i niczego nie wpisuje. Bez tekstu oryginału
  „nie dotyczy”.

`QC_VERSION` bez zmian: nowe uwagi nie blokują, zaliczenie jest to samo.

## Przyciski w panelu (`CvEditorIssueRows`)

- „Lata w punkcie 1: Ponad 7 lat (tylko role X)”, pod spodem cały staż, suma
  ról z punktu 1 i lista ról z datami i miesiącami; przycisk z treścią
  propozycji i „Zostaw Ponad 7 lat”. Bez „To nieprawda”.
- „Rola kończy się przed startem: ~~08.2021 – 09.2019~~ 09.2019 – 08.2021”
  z „Odwróć”; w rozwinięciu „Sprawdź w oryginale”.
- „Sam rok w datach: 2015 – 2016” z „Pokaż oryginał” w grupie „Do decyzji”.
  „Pokaż oryginał” to ta sama kolumna co przycisk w nagłówku edytora
  (`CVBrandedEditModal.showOriginal`, na wąskim ekranie zakładka źródeł);
  bez niej przycisku nie ma.
- Obie poprawki idą przez `qc/transform` (treść z edytora, jeden cofalny krok,
  utrwala autozapis): `tenure_split` liczy propozycję na serwerze od nowa
  i podmienia frazę w pierwszym punkcie tylko wtedy, gdy stoi w jednym węźle
  tekstu (pogrubiona liczba = „popraw ręcznie”); `swap_dates` z `role_index`.
  W oknie QC (`qc/apply`) tych poprawek nie ma — jak `years` i `title`.

Harness: `/preview/cv-editor?state=lata` (fikcyjne CV z punktem „jako Java
Developer”, rolą z samym rokiem i rolą z odwróconymi datami).

Testy: `backend/tests/test_cv_tenure_checks.py`, sekcja „R2–R3” w
`CvEditorIssues.test.tsx`.
