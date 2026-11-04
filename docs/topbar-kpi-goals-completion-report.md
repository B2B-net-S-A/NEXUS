# Licznik celów w górnym pasku i porządek w celach KPI (13.10.2026)

Pytanie Artura: co pokazują „trzy statystyki” u góry i jak je zmienić. Odczyt
kodu pokazał trzy pary „znak + wynik/cel” bez nazw, a po drodze dwie decyzje
Artura z 13.10.2026: celu „Nowi kandydaci dziś” już nie ma, a celem Delivery
Leada jest 30% hit ratio (10 zamkniętych rekrutacji = 3 placementy). Makiety
(7 plansz): https://claude.ai/artifact/SDmwSbF8c9wWoqnUtB3KLt. Reguły dla
kolejnych zmian: `docs/claude/ui/licznik-celow-w-gornym-pasku.md`.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Pasek | Do trzech podpisanych segmentów zamiast `🎯 1/4 ↓ 0/5 → 3/15`. Rekruter: Weryfikacje (dziś), Rekomendacje (tydzień), Placementy (miesiąc). Head of Recruitment i TCM: te same trzy jako suma zespołu. Delivery Lead: Placementy do celu, Hit ratio, Zamknięte rekrutacje. |
| Znaczek | Tylko przy wyjątku: kropka = poniżej tempa, zielony znaczek = zrobione, wyszarzona liczba = okres zamknięty. Emoji zniknęły, „powyżej tempa” nie wygląda już jak cel zrobiony. |
| Panel | Otwiera się kliknięciem (wcześniej dymek na najechanie): grupy Dziś / Ten tydzień / Ten miesiąc, pasek z kreską tempa, zdanie o stanie, „co się liczy”, link do Insights. |
| Reguła tempa | „Poniżej tempa” dopiero, gdy brakuje całej sztuki. Placement miesiąca (cel 1) nie ma tempa. |
| Cel Delivery Leada | Cel placementów = 30% rekrutacji zamkniętych w kwartale, w górę (było: stałe 3 z ligi). Oba wiersze mają jeden stan. Liga Mistrzów DL bez zmian. |
| Cel „Nowi kandydaci dziś” | Wycofany z katalogu, licznika, celów zespołu, przypomnień coacha i edytora celów. Liczba „CV do bazy” zostaje jako statystyka. |
| API | `/api/kpis/me/today`: `short_title_pl`, `expected_count`. `/api/kpis/me/goals`: `short_title_pl`, `expected`, `closed_requests`. `/api/kpis/me/panel`: bez `target_cv_added_daily`. |
| Harness | `/preview/kpi-topbar`: repliki paska na całą szerokość okna, stany dnia, panele trzech ról. |

## Pomiar zamiast szacunku

Plan zakładał progi okna (trzy segmenty od 1280 px). Pomiar na harnessie przy
1280 × 720 z przypiętym menu (pasek 1040 px) pokazał, że trzy segmenty
(291 px) przy długich okruszkach zostawiają wyszukiwarce 109 px, czyli samą
lupę i skrót. Dlatego licznik nie ma progów okna, tylko sam oddaje miejsce:
pokazuje tyle całych segmentów, ile się mieści, a wyszukiwarka ma od 1024 px
gwarantowane 220 px.

Liczby po scaleniu z ikoną „Rozmowy” (#2170), która zabrała paskowi kolejne
44 px; menu przypięte, pasek = okno − 240 px:

| Okno | Rekruter, długie okruszki (ekran rekrutacji) | Head, krótkie okruszki | Delivery Lead, krótkie okruszki |
|---|---|---|---|
| 1280 × 720 | 1 segment | 2 segmenty | 3 segmenty |
| 1366 × 768 | 1 segment | 3 segmenty | 3 segmenty |
| 1440 × 800 | 2 segmenty | 3 segmenty | 3 segmenty |
| 1536 × 864 | 3 segmenty, forma pełna | 3 segmenty, forma pełna | 3 segmenty, forma pełna |

W każdej komórce wyszukiwarka ma co najmniej 220 px, pasek się nie przelewa,
a sąsiednie przyciski mają 36 px. Rekruter przy 1280 px widzi trzy segmenty
na pulpicie, dwa na listach („Rekrutacje”, „Kandydaci”) i jeden na ekranie
rekrutacji — reszta celów jest w panelu po kliknięciu. Poniżej 1024 px zostaje
słowo „Cele” (74 px, tyle co dawne „KPI”); strona harnessu nie ma poziomego
przewijania przy 360 px. Najciaśniejszy przypadek (zespół, okruszki na 70
znaków i pigułka „zadzwoń” w ikonie „Rozmowy”, 1280 × 650): jeden segment,
wyszukiwarka 220 px, okruszki przycięte do 169 px.

## Znalezione po drodze

- **Zero było „poniżej tempa” od 9:01.** Uruchomienie `derive_state` na
  przykładowym dniu: 0 z 4 o 9:01 dawało „behind”, placement miesiąca przez
  cały miesiąc, a 1 z 4 o 10:00 dawało „ahead” z tym samym znakiem co cel
  zrobiony. Siedem z jedenastu nowych przypadków testowych pada na starym kodzie.
- **Cel placementów DL nie miał związku z liczbą rekrutacji.** Przy 20
  zamkniętych i 4 placementach licznik pokazywał cel zrobiony (4 z 3), choć
  hit ratio wynosiło 20%.
- **Osierocony wiersz przywróciłby wycofany cel.** Resolver pytał bazę o każde
  id, także spoza katalogu — dostał zaporę i test.
- **Przegląd kodu znalazł dwa błędy pierwszej wersji mechanizmu chowania**
  (potwierdzone na harnessie przy 1280 px): sąsiedni przycisk „Moi ludzie”
  kurczył się z 36 do 22 px, a tekst segmentu łamał się i wystawał z ukrytego
  wiersza. Poprawione regułą grupy („ściska się tylko licznik”)
  i `whitespace-nowrap` na segmencie; test e2e sprawdza oba przypadki.
- **Dymek nie miał cienia** (`shadow-smd` nie istnieje) — zniknął razem z dymkiem.
- **Ułamki z kropką** („24.5%”) — teraz z przecinkiem.

## Weryfikacja

- Backend bez bazy (Python 3.12, lokalnie): `test_kpi_engine.py`,
  `test_kpi_goals_dl_notes.py`, `test_kpi_milestone_snapshot_round7.py`,
  `test_recruitment_activity_round7.py`, `test_kpi_round9.py`,
  `test_kpi_messages.py` i testy katalogu bez bazy — zielone; `ruff check`
  i `ruff format --check` czyste. Testy z bazą biegną w CI.
- Frontend: testy licznika, modelu, paska postępu, harnessu, middleware
  i strażników czytających źródła — zielone; `tsc --noEmit`, ESLint i bramka
  martwych modułów czyste.
- Harness przeklikany w przeglądarce przy 1280 × 720, 1366, 1440, 1536, 1024,
  768 i 360 px: klik i Enter otwierają panel, Escape zamyka i oddaje fokus,
  panel mieści się w oknie; tryb ciemny i tryb Kids sprawdzone (kreska tempa
  nie dostaje tęczy).

## Świadomie poza zakresem

- Kasowanie osieroconych wierszy celu w bazie (bez migracji; resolver ich nie czyta).
- Wiersz „Otwarte teraz” w panelu Delivery Leada (wymaga nowego zapytania).
- Łagodniejsza reguła tempa dla sum zespołu (zespół 0 z 48 o 9:15 nadal jest poniżej tempa).
- Trzy segmenty zawsze przy 1280 px: wymagałoby schowania przełączników
  wyglądu (112 px) pod jeden przycisk — decyzja właściciela (tę samą ulgę
  zaproponował raport okienka „Rozmowy”).
- Kolory `KpiNudgeToaster.tsx` (nadal twarde).

## Niepotwierdzone

- Wygląd licznika na produkcji: konto administratora nie ma celów, więc
  licznika nie widzi — potrzebny zrzut z konta rekrutera albo zgoda na odczyt.
- Czy cel „Nowi kandydaci dziś” był już wyzerowany w edytorze na produkcji
  (nie czytałem bazy produkcyjnej).
- Flagi coacha KPI na produkcji (w kodzie domyślnie wyłączone); przy włączonych
  przypomnień „poniżej tempa” będzie mniej.
