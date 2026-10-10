# Nowa rekrutacja: jeden ekran, przecinek = kolejne wymaganie — raport

Data: 11.10.2026. Decyzje Artura D1–D4 z 10.10.2026 („tak jak zalecasz, wdrażaj”).
Makiety i audyt: https://claude.ai/artifact/DehYwkrVBK498hCbyRUdie.

## Problem

Audyt strony `/jobs/new` z 10.10.2026 (potwierdzony na produkcji):

| Co | Przed zmianą |
|---|---|
| Przecinek w wierszu wymagań | robił wariant „lub”: `Java , Spring ,` dawało JEDEN wiersz „Java lub Spring”, a nie dwa must-have |
| Trzy tryby (wklej, plik, ręcznie) | trzy różne ekrany; ręczny — pusty prostokąt na 40% szerokości, braki podświetlone dopiero po odczycie AI |
| Zmiana źródła | kasowała wpisane pola bez pytania (odczyt podmieniał cały formularz) |
| Plik Profilu Championa | czytał go ten sam model co mail, z tabeli Worda spłaszczonej do tekstu; sekcje bez pola w formularzu przepadały |

## Co zrobiono

**D1 — wpisywanie wymagań** (`/jobs/new` i `stack.rows` w Profilu Championa)

- Pusty wiersz przyjmuje Enter, przecinek, średnik i wklejoną listę jako OSOBNE
  wymagania (`parseRequirementEntry`, `enterRequirements` w `lib/requirement-rows.ts`).
  „A / B”, „A lub B”, „A or B” to nadal warianty jednego wymagania; „CI/CD”
  i przecinek w otwartym nawiasie („Spring (Boot, Data)”) zostają jednym słowem.
- Wypełniony wiersz pokazuje słowa i przycisk „+ lub” — dopiero on otwiera pole
  wariantu. Limity 10 obowiązkowych / 20 „mile widziane” / 20 słów w wierszu
  i pomijanie duplikatów działają też dla wklejonej listy.
- `ChipField` dostał opcjonalne `onCommitText`, `hideInput`, `trailing`; bez nich
  zachowuje się jak dotąd (filtry listy kandydatów, pole „Wyklucz”).

**D2 — jeden ekran**

- Kroków nie ma. Formularz sześciu sekcji stoi na stronie od wejścia, nad nim
  pasek: klient i „Wypełnij z: Wklej treść · Wgraj plik · Inna rekrutacja”
  (`NewJobSourceBar`, `TemplateJobPicker`). Źródła można użyć w dowolnej chwili
  i wiele razy. `NewJobSourceStep` usunięty.
- Treść requestu stoi obok formularza tylko, gdy jest; inaczej formularz ma całą
  szerokość.
- Braki są podświetlane w każdym trybie tak samo: po odczycie, przy szablonie
  i po kliknięciu „Utwórz i opublikuj” (przycisk przy brakach jest aktywny —
  kliknięcie podświetla pola i niczego nie wysyła).

**D3 — odczyt wypełnia tylko puste pola** (`lib/job-intake-fill.ts`)

- Nietknięty formularz bierze odczyt w całości. W formularzu z wpisanymi polami:
  puste pole się wypełnia, takie samo zostaje, a inne dostaje propozycję przy
  polu „W mailu / W pliku / W szablonie: … [Użyj] [Zostaw]”.
- Pola, które mają sens tylko razem, idą razem (budżet od–do, tryb + dni,
  termin + godzina, hiring manager + „Klient nie podał”). Wymagania i pytania
  to jedna propozycja „jeszcze N … [Dodaj]”.
- „Cofnij wypełnienie” zdejmuje tylko to, co wpisał odczyt i czego nikt potem
  nie zmienił. Pasek pod źródłami mówi „wypełniono N pól · M propozycji czeka”.

**D4 — plik Profilu Championa**

- Wypełniony wzór Worda czyta kod, bez modelu
  (`backend/app/services/job_intake_champion_file.py`); `POST /api/job-intake/read-file`
  oddaje wtedy `reader: "champion_form"` i `champion_extras` (sekcje wzoru bez
  pola w formularzu: frazy i plan searchu, insight konsultanta, pytania klienta
  z poprzednich rozmów, branże, „Wiedza z rozmów”).
- Formularz pokazuje źródło „z dokumentu”, notkę „przepisany bez AI” i niesie
  dodatkowe sekcje do zapisu profilu (`IntakeForm.championExtras` →
  `buildChampionPayload`).
- Pusty wzór = 422 po polsku. Plik, którego nie da się odczytać jako wzoru,
  idzie starą ścieżką z modelem.
- Skrypt pomiaru na plikach z produkcji (tylko odczyt, same liczby):
  `backend/scripts/eval_champion_file_read.py`.

Bez migracji. Reguły: `docs/claude/rekrutacja-tworzenie/jobs-new-jeden-ekran-i-odczyt-pustych-pol.md`
(nowy plik w indeksie `CLAUDE.md`), poprawione pięć istniejących plików reguł.

## Stan i dowody

| Część | Stan | Dowód |
|---|---|---|
| D1 przecinek, Enter, wklejona lista | zrobione | Playwright na lokalnym podglądzie (11.10): „Java, Spring, SQL” + Enter → 3 wiersze; „Kafka / RabbitMQ” → 1 wiersz „Kafka lub RabbitMQ”; „Spring (Boot, Data)” → 1 wiersz; „+ lub” + „JDK” → „Java lub JDK”; wklejone „- Docker / - Kubernetes / - AWS” → 3 wiersze. Testy: `RequirementRowsEditor.test.tsx`, `ChipFieldSuggest.test.tsx`, `requirement-rows.test.ts` |
| D2 jeden ekran | zrobione | `NewJobPage.test.tsx` 98/98; pomiar niżej |
| D3 tylko puste pola | zrobione | `job-intake-fill.test.ts`; w podglądzie stan `offers`: „wypełniono 11 pól · 4 propozycje czekają”, po „Użyj — Rola” zostają 3 |
| D4 czytnik pliku (backend) | zrobione, testy tylko w CI | `ruff check` i `ruff format --check` czyste; `backend/tests/test_job_intake_read_file.py` biegnie w CI (lokalny Python 3.9 nie importuje aplikacji) |
| D4 formularz | zrobione | `job-request-intake.test.ts`, `job-intake-fill.test.ts`, `NewJobPage.test.tsx` (blok „plik Profilu Championa”); podgląd `?state=champion`: chipy „z dokumentu”, notka „przepisany bez AI” |
| Układ na laptopie | zmierzone | pasek sekcji formularza z ramką powłoki (240 + 48 px) przy 1280×720 / 1366×768 / 1536×864: pusty formularz 0,41 / 0,39 / 0,34 wysokości okna; z propozycjami 0,50 / 0,47 / 0,42; po pliku Championa 0,53 / 0,47 / 0,42. Pasek źródeł w jednym rzędzie we wszystkich stanach |
| Telefon i tablet | zmierzone | 0 px poziomego scrolla przy 360 / 390 / 768 / 1024 px w stanach `manual`, `attempted`, `offers`, `champion`, `request` |
| e2e podglądu | zielone lokalnie | `playwright test --project=preview-chromium -g "new-job"`: 10/10 na lokalnym serwerze |
| Testy frontu | zielone | 25 plików, 810 testów (w tym strażnicy harnessów, natywnych okien, `apiErrorMessage`, responsywności); `npm run type-check` i ESLint zmienionych plików czyste. Dwa testy przekroczyły limit czasu tylko przy równoległym biegu z lokalnym serwerem podglądu — każdy z plików osobno przechodzi (98/98 i 48/48) |
| Przegląd kodu | zrobiony, blokery naprawione | python-reviewer (D4): nieosłonięty odczyt tekstu pliku dawał 500 → powrót na starą ścieżkę + test. typescript-reviewer (D1): przecinek w otwartym nawiasie → test + poprawka. typescript-reviewer (D2/D3): fokus klawiatury ginął po zamknięciu panelu źródła, „Użyj” / „Zostaw” i „Cofnij wypełnienie” → 4 testy + poprawka, potwierdzone w przeglądarce (fokus: pole „Rola”, przycisk „Wklej treść”, pasek źródeł) |
| Ryzyka z przeglądu (nieblokujące) | naprawione 4 z 5 | zmiana klienta i „Utwórz” w trakcie odczytu zablokowane; zepsuty zapis propozycji nie wywraca strony; pasek nie obiecuje sekcji drugiego pliku Championa. Zostaje: po usunięciu formularza przy limicie 20 zapis wraca dopiero przy następnej edycji (dane nie przepadają) |
| Reguły | zrobione | `build_claude_index.py --check` 0, `CLAUDE.md` 28 760 B (limit 40 000), `check_stamps.py` 0, `test_claude_md_index.py` 4/4 |

## Niepotwierdzone i poza zakresem

- **Czytnik pliku Championa nie był mierzony na prawdziwych plikach.** Produkcja
  nie ma jeszcze żadnego pliku requestu (`job_files`: 0 wierszy, 11.10.2026)
  ani profilu z wersją wzoru. Sprawdzony na wzorach z obrazu aplikacji:
  2 wypełnione rozpoznane, 2 puste rozpoznane jako puste. Gdy pliki się pojawią:
  `python -m scripts.eval_champion_file_read --limit 200` w kontenerze backendu.
- Otwarty panel „Wklej treść” przesuwa formularz niżej (pasek sekcji na 0,76
  okna przy 1280×720) — to panel otwarty przez użytkownika, po odczycie się zamyka.
- W polu wariantu („+ lub”) średnik nie jest separatorem.
- `champion_document.table_profile`, `document_text` i `_extract_docx` nadal
  czytają `row.cells` (klasa błędu gridSpan z B2B-net-S-A/NEXUS#2119) — osobna poprawka.
- Lista kandydatów (`RequirementRowsField`) zostaje przy dotychczasowym
  przecinku — świadomie, to inny ekran i inne znaczenie wiersza.
- `intake.document_context` i `rate_raw` z pliku Championa nie przechodzą przez
  tworzenie rekrutacji.

## Odstępstwa od projektu

- Pole wypełnionego wiersza jest ukryte do kliknięcia „+ lub”; wklejona lista
  traci znaczniki („- ”, „• ”, „1. ”); podpowiedź wybrana w pustym wierszu to
  całe wymaganie.
- Szablon („Inna rekrutacja”, `?from=`) idzie tą samą drogą co odczyt — też
  wypełnia tylko puste pola i zostawia propozycje „W szablonie: …”.
- Podpowiedź kategorii i autozapis czekają na treść w formularzu (pusta strona
  nie wysyła żadnego POST-a).
- Termin z przeszłości w pliku Championa nie jest wpisywany (uwaga w formularzu);
  notatka „Od klienta” jest cięta do 2000 znaków.
