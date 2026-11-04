# Panel osoby: stały pasek zakładek, kontakt pod nazwiskiem, „Warunki” nad pytaniami — raport

Gałąź `claude/candidate-profile-layout-36ebf0`, 09.10.2026. Makiety zaakceptowane przez Artura:
https://claude.ai/artifact/9GE1bRKXawVcGTJmok6dAw. Tylko front — bez API i migracji.

## Skąd zmiana

Zgłoszenie rekruterów z 09.10.2026 (trzy rzeczy w panelu osoby na Tablicy rekrutacji):

1. Po „Rozwiń” pasek zakładek (CV, Screening, Rozmowy, Umowa, Dopasowanie, Notatki) zmieniał położenie zależnie
   od zakładki. W „Screeningu” głowa panelu była krótka. W pozostałych zakładkach wracały do niej „Warunki wobec
   rekrutacji”, „Nie odebrał” i ramka „Następny etap”. Głowa się nie przewija, więc przy oknie 1536 × 780 (laptop
   ze skalowaniem 125%) pasek zjeżdżał na dół, a na treść zakładki zostawało ok. 70 px.
2. W panelu nie było telefonu ani e-maila — trzeba było wejść w profil.
3. W formularzu screeningu „Warunki” (stawka, dostępność, tryb) stały pod pytaniami.

## Co się zmieniło

### Pasek zakładek stoi w miejscu

- `jobs/PipelineCandidateDock.tsx`: po „Rozwiń” (`tabsOpen`) głowa nie renderuje faktów, rzędu „Biorę / Nie
  odebrał” ani ramki „Następny etap”. Zostają: nawigator, nazwisko z kontaktem, plakietki, sprawa zmiany stawki,
  rząd „Inny etap… / Odrzuć z powodem / Zrezygnował / ⋯”, odznaki etapu. Wąski dok bez zmian.
- `jobs/DockStageFold.tsx` (nowy): te same trzy bloki jako jedna zwinięta linia pod paskiem zakładek. Tytuł
  „Warunki i następny etap”, „Warunki wobec rekrutacji” albo „Następny etap” — zależnie od tego, co jest w środku.
  W stanie zwiniętym obok tytułu stoi nazwa następnego etapu i liczba braków („Zweryfikowany · brakuje 4 z 4”).
  Treść montuje się po rozwinięciu. Każda osoba zaczyna od linii zwiniętej.
- `jobs/DockNextStage.tsx`: zapytanie o wymagania wyjęte do `useNextStageRequirements` — ramka i skrót linii
  czytają ten sam klucz react-query, więc liczba braków jest w obu miejscach ta sama.
- `person/WorkbenchBelowTabs.tsx` (nowy) + `person/PersonWorkbenchTabs.tsx`: dok podaje linię przez kontekst,
  zakładki renderują ją między paskiem a treścią zakładki.
- Zakładka z własnym ruchem i własnymi warunkami (Screening w „Nowych”) linii nie ma. Zakładka z własnym ruchem,
  ale bez własnych warunków (CV na „Zweryfikowanym”) ma linię samych „Warunków”.
- Przypięte notatki kandydata są po „Rozwiń” zawsze zwinięte — stoją nad paskiem, więc muszą mieć tę samą
  wysokość w każdej zakładce.

### Telefon i e-mail pod nazwiskiem

- `person/PersonContactLine.tsx` (nowy): numer jest linkiem `tel:`, ikona obok kopiuje; adres jest tekstem
  z ikoną kopiowania. Czego profil nie ma, tego linia nie pokazuje.
- Widoczne w wąskim doku i po „Rozwiń”. Dane z zapytania o profil kandydata, które dok robił już wcześniej.

### Formularz screeningu

- `screening-form/ScreeningFullForm.tsx`: kolejność „Uzupełnij z notatki” → „Warunki” → „Pytania z Profilu
  Championa” → „Ocena”. Pola, zapis i przyciski bez zmian.
- Widok tylko do odczytu trzyma tę samą kolejność: stawka i warunki, odpowiedzi, ocena.

### Pozostałe

- Przewodnik ekranu `jobs.person` (Jarvis) — trzy zdania poprawione, przewodnik przestemplowany.
- Harness `/preview/job-detail` — fikcyjny telefon i adres w zasianym profilu.
- `CLAUDE.md` — trzy punkty w sekcji „Duży podgląd po lewej stronie panelu osoby”.

## Weryfikacja

| Co | Wynik |
|---|---|
| Vitest: `person/`, `jobs/`, formularz screeningu, Tablica, `lib/help` | 44 pliki, 740 testów — zielone |
| Vitest: sąsiednie zestawy (`recruitment/`, `screening/`, `lib/__tests__`, strażnicy harnessów) | 4313 testów — zielone |
| `tsc --noEmit` | 0 błędów |
| ESLint zmienionych plików | 0 uwag |
| Playwright lokalnie (`preview-chromium`, „panel osoby — duży podgląd…”) | 3 z 3, w tym nowy „pasek zakładek stoi w miejscu” |
| Stemple przewodników (`scripts/check_stamps.py`) | zgodne |
| `tests/test_screen_guides_freshness.py` | niepotwierdzone lokalnie (Python 3.9 nie importuje `conftest`) — sprawdza CI |

Pomiar w przeglądarce, harness `/preview/job-detail`, osoba w „Nowych”:

| Okno | Zakładka | Górna krawędź paska | Miejsce na treść pod paskiem |
|---|---|---|---|
| 1536 × 780 | Screening | 243 px | 449 px |
| 1536 × 780 | Rozmowy | 243 px | 449 px |
| 1536 × 780 | Dopasowanie | 243 px | 449 px |
| 1280 × 720 | Rozmowy | 243 px | 389 px |

Przed zmianą (zrzut ze zgłoszenia, okno 1536 × 780, zakładka „Rozmowy”): ok. 70 px na treść.

Formularz w `/preview/screening-form?state=filled`: sekcje w kolejności „Uzupełnij z notatki”, „Warunki”,
„Pytania z Profilu Championa”, „Ocena”.

## Sprawdzenie na produkcji (#2107, 09.10.2026)

`/api/health` i `version.json` frontendu zwróciły commit `a09df770c` (deploy 13:27 UTC). Rekrutacja `/jobs/5027`,
okno 1920 × 779 (Chrome z zoomem 80% — wysokość jak w zgłoszeniu):

- pasek zakładek 242 px od góry w „Screeningu”, „Rozmowach” i „Dopasowaniu”,
- „Rozmowy” u osoby ze zgłoszenia: 450 px na treść, linia „Warunki i następny etap · Zweryfikowany · brakuje 4 z 4”,
- telefon (link `tel:`) i e-mail pod nazwiskiem, dwie ikony kopiowania,
- formularz: „Uzupełnij z notatki”, „Warunki”, „Pytania z Profilu Championa”, „Ocena”.

## Uzupełnienie: podgląd po lewej w każdej zakładce (09.10.2026)

Po #2107 pasek stał na tej samej wysokości, ale przy przejściu do „Umowy”, „Dopasowania” i „Notatek” przesuwał
się o 240 px w bok: te trzy zakładki miały panel 760 px bez podglądu po lewej. Decyzja Artura: podgląd po lewej
we wszystkich zakładkach.

- `pages/KanbanBoardV2.tsx`: rozwinięty panel ma zawsze rozmiar `split` (`SIDE_SECTIONS` usunięte).
- `person/PersonPanelShell.tsx`: rozmiar `wide` (760 px) usunięty — nie ma już użytkownika.
- `person/PersonWorkbenchTabs.tsx`: jeden wspólny podgląd dla CV, Umowy, Dopasowania i Notatek
  (`SHARED_PREVIEW_SECTIONS`). Zmiana zakładki nie montuje go od nowa. „Rozmowy” i „Screening” zostają przy
  własnych podglądach, więc egzemplarzy jest najwyżej trzy, jak dotąd.
- `pages/B2BContractGeneratorV2.tsx`: formularz umowy układa pola po szerokości kontenera (`@container`,
  `@xl:grid-cols-*`). W kolumnie panelu (460–520 px) jedno pole w rzędzie; do tej zmiany byłyby tam dwa albo trzy
  pola po ok. 120–190 px. Strona Generatora bez zmian (dwie i trzy kolumny).

Pomiar w `/preview/job-detail`:

| Okno | Zakładki | Lewa / górna krawędź paska | Kolumna pracy |
|---|---|---|---|
| 1280 × 720 | Screening, Rozmowy, Umowa, Dopasowanie, Notatki | 837 / 243 px w każdej | 460 px |
| 1536 × 780 | Umowa | 1033 / 243 px | 520 px |

Vitest: `person/`, Tablica, Generator B2B, `pages/` — 70 plików, 776 testów (pierwsze uruchomienie miało 9
przekroczeń czasu przy równolegle kompilującym się serwerze dev; powtórka bez błędów). `tsc` 0 błędów. Playwright
lokalnie: 3 z 3, test paska sprawdza teraz pięć zakładek, obie krawędzie i jeden widoczny podgląd.

## Poza zakresem

- Pasek zakładek przewija się razem z treścią długiej zakładki, jak dotąd.
