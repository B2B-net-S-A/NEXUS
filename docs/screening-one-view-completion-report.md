# Jeden widok „Screening” zamiast karty rekomendacji — raport

Data: 09.10.2026. Decyzja Artura: „usuń nazwę wszędzie”.

## Problem

Od 0424 (07.10.2026) rekruter wypełnia jeden formularz screeningu. Do odczytu te
same dane stały jednak w dwóch albo trzech blokach pod różnymi nazwami:

| Ekran | Przed zmianą | Po zmianie |
|---|---|---|
| Dok osoby na Tablicy | sekcje „Screening” i „Karta rekomendacji” | jedna sekcja „Screening” |
| Przegląd Delivery Leada | „Ocena rekrutera”, „Karta rekomendacji”, zwinięty „Arkusz screeningu Championa” | jeden blok „Screening” między wymaganiami a ryzykami |
| Zakończony proces (panel osoby) | zapisany arkusz i osobno karta | jeden widok + historia zmian |
| Profil kandydata, przy notatce | „Karta rekomendacji z tej rozmowy” → okno karty | „Screening tej rekrutacji” → okno „Screening” |

Do tego „brakuje N” liczyło się na dwa sposoby: formularz uznawał stawkę zapisaną
na etapie za wypełnione pole, a plakietka Tablicy, kolejka DL i „Przesuń dalej” — nie.

## Co zrobiono

**Backend (bez migracji, tabele i trasy bez zmian)**

- `GET /api/screening-form` oddaje dwa pola więcej: `questions` (pytania scalone
  przez serwer — odpowiedź z arkusza, a bez niej z notatki; „Odpada, gdy…”,
  trafienie) i `rate_text` (stawka zapisana tekstem, gdy `rate` jest puste).
- Jedna reguła braków: `recommendation_cards.with_stage_rate` i
  `stage_rate_pairs`. Stawka na wierszu etapu to wypełnione pole w formularzu,
  na plakietce Tablicy, w kolejce DL, w „Przesuń dalej” i w
  `GET /api/recommendation-cards`. Para ze stawką na etapie i bez wiersza karty
  ma stan „częściowy”.
- Napisy dla człowieka: „Warunki i ocena”, „jest w screeningu”, „formularz
  screeningu”, „Czytam screening” (Jarvis). Klucze (`recommendation_card`,
  `open_card`, `card`) zostały. Prompt modelu (`llm_prompts.py`) bez zmian.

**Frontend**

- Nowy widok tylko do odczytu `screening-form/ScreeningSummaryView` (warunki →
  pytania → ocena), `ScreeningSummarySection` (ładowanie, błąd, „Ponów”),
  `ScreeningSummaryDialog` (okno w profilu, ładowane leniwie) i lekki
  `lib/screening-summary.ts`.
- `ScreeningAnswersList` zna dwa opcjonalne pola wiersza: `source` („odpowiedź
  z notatki”) i `deal_breaker` („Odpada, gdy: …”). Nadal jedyny renderer odpowiedzi.
- Usunięte: `RecommendationCardSection`, `RecommendationCardView`,
  `RecommendationCardDialog` z testami, `SavedScreeningView`, blok „Ocena
  rekrutera” w środkowej kolumnie przeglądu DL, harness
  `/preview/recommendation-card`.
- „W starym formacie” (tekst do skopiowania) jest zwinięte w widoku i pobiera
  dane dopiero po rozwinięciu.
- Plakietka Tablicy i kolejki DL: „Screening: komplet / brakuje N / puste pola”.
- Rekrutacja bez pytań w profilu: nagłówek „Pytania i odpowiedzi” zamiast
  „Pytania z Profilu Championa”.
- „Zmień” stawkę w panelu osoby (`RateChangeDialog`) odświeża stan formularza
  pary — wiersz „Stawka kandydata” w sekcji „Screening” pokazuje nową kwotę od
  razu (uwaga z przeglądu kodu; test pada bez poprawki).

**Strażniki i dokumenty:** oba inwentarze funkcji (wpisy przeniesione, bez
`removed_reason`), harnessy z zasianym stanem formularza, przewodnik ekranu
i stemple, `docs/screening-form-contract.md`, sekcja w `CLAUDE.md`.

## Weryfikacja

| Co | Wynik |
|---|---|
| Testy frontu wokół zmienionych ekranów (`vitest`, 392 pliki) | 5548 z 5548 zielone |
| `npm run type-check` | bez błędów |
| ESLint zmienionych plików (`--max-warnings=0`) | bez uwag |
| `ruff check` + `ruff format --check` (11 plików backendu) | bez uwag |
| `scripts/check_stamps.py` | kod wyjścia 0 |
| Przeglądarka 1280×720: `/preview/pipeline-v4` (dok), `/preview/dl-review` i `?layout=panel`, `/preview/screening-form?state=readonly`, `/preview/candidate-profile?tab=activity` (okno + „W starym formacie”), `/preview/job-detail` | jedna sekcja/blok „Screening”, zero wystąpień „karta rekomendacji” w tekście i atrybutach, brak poziomego przewijania; błędy konsoli tylko z odciętej sieci harnessów |
| Stara nazwa w kodzie (`grep`) | tylko komentarze, opisy inwentarza i prompt modelu |
| Testy backendu | niepotwierdzone lokalnie (Python 3.9 nie zbiera testów) — sprawdza CI |
| Po scaleniu maina (#2110, #2112): `vitest run --changed origin/main` | 72 pliki, 1635 z 1635 zielone; strażniki (inwentarze, harnessy, kotwice pomocy) 401 z 401; type-check i ESLint 51 plików bez uwag |
| Dwa przeglądy kodu (front, backend) | bez problemów blokujących merge |

**Pomiar na produkcji (09.10.2026, tylko odczyt).** Widok czyta stan formularza,
który dla arkusza bez odpowiedzi daje `sheet: null`. Policzone: 2843 arkusze
screeningu, wszystkie mają co najmniej jedną odpowiedź; arkuszy z oceną albo
notatką bez żadnej odpowiedzi jest 0. Zapasu z arkusza etapu nie dokładałem.

## Po wdrożeniu (09.10.2026)

PR #2114 scalony jako `8628cff53`; `/api/health` i `version.json` frontu podają
ten SHA. Przeklikane na produkcji (Chrome, okno ok. 1600 × 850, dane testowe QA):

| Ekran | Wynik |
|---|---|
| Dok osoby w „Screeningu” | jedna sekcja „Screening”: ściąga do rozmowy, niżej warunki → pytania (odpowiedź „z notatki”) → ocena, zwinięte „W starym formacie”; „Brakuje pól: 7” zgadza się z listą braków w ramce „Następny etap” |
| Panel po „Rozwiń” | zakładka „Screening” z formularzem, napisy „Z notatek: …” i „Te pola widzi Delivery Lead przed wysłaniem CV.” |
| Przegląd Delivery Leada (osoba w „QC CV”) | jeden blok „Screening” między wymaganiami a ryzykami, bez „Arkusza screeningu Championa” |
| Profil kandydata → Notatki i historia | „Do screeningu trafiło: …” i „Screening tej rekrutacji” otwiera okno „Screening” |
| Stara nazwa w tekście strony i atrybutach | zero wystąpień na każdym z tych ekranów |

Znalezione przy przeklikaniu:

- **Dwa napisy tej samej oceny w przeglądzie DL.** Blok „Screening” mówił
  „Niepewne” (napis z formularza), pasek decyzji „Ocena rekrutera: Nie wiadomo”
  (napis z serwera, `FIT_LABELS`). Poprawione osobnym PR-em: serwer mówi
  „Niepewne”, a test porównuje obie mapy napisów.
- **Wąski dok: głowa zajmuje cały panel (stan sprzed tej zmiany).** Przy oknie
  o wysokości ok. 850 px głowa doku (fakty, przyciski i ramka „Następny etap”
  z listą braków) ma 784 px, a na sekcje zostają 32 px — sekcję „Screening”
  widać dopiero po „Rozwiń”. Przy długim ostrzeżeniu o „Odpada, gdy…” głowa ma
  1098 px. Zmiana tego układu nie należała do zakresu; zgłoszone osobno.
- Za pierwszym razem PR wypadł z kolejki na strażniku profilu
  (`not.toContain("ScreeningSummary")` łapał nowe okno) — strażnik pilnuje teraz
  pełnej nazwy starej karty. Testy backendu przeszły w pełnym biegu kolejki.

## Sprostowanie do planu

Plan mówił, że osoba po nowym formularzu ma plakietkę „brakuje 1”. Formularz
zapisuje stawkę także do pola karty, więc rozjazd dotyczył tylko stawki
wpisanej poza formularzem (okno „Zweryfikowany”, „Zmień” w panelu). Wspólna
reguła zostaje — usuwa ten rozjazd.

## Świadome skutki

- Widok pokazuje bieżącą próbę procesu, jak formularz. Wartości sprzed
  ponownego dodania osoby są podpowiedzią „brak — ostatnio: …”. Do tej zmiany
  karta w przeglądzie DL pokazywała też odpowiedzi z poprzedniej próby.
- Delivery Lead widzi w bloku „Screening” link „Edytuj w screeningu” (jak dotąd
  przy karcie); o prawie zapisu decyduje serwer.

## Poza zakresem

- Nazwy techniczne (`recommendation_cards`, `/api/recommendation-cards`,
  `lib/recommendation-card.ts`, klucze `card`, `open_card`).
- Treść promptów modeli — zmiana wymaga ponownego pomiaru.
- Starsze sekcje `CLAUDE.md` (0413, 0421, 0424, przegląd DL v2) opisują stan
  sprzed 09.10.2026; nowa sekcja mówi to wprost.
