# Generator CV — naprawa parsera Profilu Championa

**Data:** 2026-07-20
**Branch:** `claude/cv-generator-champion-profile-d3c6b6`
**Punkt wyjścia:** zgłoszenie Piotra Chmielewskiego — „jak wsadzam profil championa, generator nie generuje CV; bez championa generuje".

## 1. Co się okazało

Zgłoszenie Piotra i faktyczny błąd w generatorze to **dwie różne rzeczy**. Diagnostyka na produkcji rozdzieliła je jednoznacznie.

### 1.1 Zgłoszenie Piotra — walidacja po stronie przeglądarki

Wiersz „processing" na liście „Wygenerowane CV" powstaje w [cv_generator_b2b.py:639](../backend/app/api/cv_generator_b2b.py) **zanim** cokolwiek zostanie zwalidowane — przed sprawdzeniem rozszerzenia, przed parsowaniem DOCX, przed wywołaniem Claude. Każda awaria serwerowa zostawia więc wiersz ze statusem `failed` i komunikatem.

Po próbach Piotra z championem nie było **żadnego** wiersza — ani udanego, ani nieudanego:

| kiedy | status | champion podpięty? |
|---|---|---|
| 17.07 11:43 | ready | tak (146 keywordów) |
| 20.07 14:08 | ready | **nie** |
| 20.07 14:46 | ready | **nie** |

Wniosek: request nigdy nie opuścił przeglądarki. Plik odbijał się na `fileValidationError` po stronie klienta, a `handleChampionFile` pokazywał wtedy tylko znikający toast i robił `return` **bez ustawienia stanu** — dropzone renderowała dalej swój pusty stan. Po zniknięciu toastu nie zostawał żaden ślad, więc kliknięcie „Generuj" produkowało CV bez championa. Dokładnie to widać w jego dwóch wpisach z 20.07.

### 1.2 Prawdziwy błąd — parser połykał cały dokument

Niezależnie od tego, parser DOCX championa miał w każdym z 7 regexów lookahead zakończony `|$` (bez `re.MULTILINE`, więc `$` = koniec pliku). Wystarczyło, że dokument nie zawierał dokładnie tego jednego nagłówka-terminatora, którego regex oczekiwał, i sekcja połykała całą resztę pliku.

Skala z bazy produkcyjnej:

```
klasa                rows   avg_keywords
overrun (5+ prozy)    738            177
clean (0 prozy)         1              1
```

**738 z 739** generacji z championem miało ten overrun. Do `MUST-HAVE` trafiały pytania screeningowe, strategia sourcingu, adresy biur i wewnętrzne notatki rekrutacyjne — i szły do Claude jako wymagania klienta:

```
"Nie blokujemy kandydatów! Po 24 godzinach bez żadnych działań i notatek…"   480×
"czy AI nie namieszało przy tworzeniu pliku – porównujcie z oryginalnym CV"  488×
"Podstawowy sprzęt (laptop) jest zapewniany konsultantom przez bank Nordea"  362×
"OFFLIMIT - TAK"                                                            372×
```

Odtworzenie układu prawdziwego szablonu z 739 zapisanych `render_payload` (średnia pozycja względna nagłówka w tablicy) pokazało, że **prawdziwe MUST-HAVE kończy się ok. 28% blobu** — reszta to inne sekcje:

| poz. | nagłówek | wystąpień |
|---|---|---|
| 28% | Co przekona kandydata do oferty? | 637 |
| 36% | Pytanie 1: | 286 |
| 56% | INSIGHT OD KONSULTANTA WEWNĘTRZNEGO | 882 |
| 61% | Firmy docelowe (gdzie szukać): | 612 |
| 77% | Lokalizacja biur: | 350 |
| 98% | OFFLIMIT – TAK | 372 |

Parser był napisany pod pierwotny szablon external CV-Generatora (`PODSTAWY` / `3. KONTEKST` / `4. SCREENING`), a rekruterzy używają szablonu Delivery Leada z zupełnie innymi nagłówkami. Efektywnie **nigdy** nie działał poprawnie na produkcyjnych dokumentach.

### 1.3 Skutek uboczny — fałszywe pogrubienia w wydanym CV

Połknięta proza docierała do renderera jako pojedyncze tokeny. `_is_strong_tech_token` zwracał `True` dla dowolnego tokenu zawierającego `+`, `#`, `/` lub `.` — a każde polskie słowo kończące zdanie ma kropkę. W wydanych CV pogrubiały się więc słowa „kandydata.", „dalej.", „projektami.".

## 2. Co zostało zmienione

| Obszar | Plik | Zmiana |
|---|---|---|
| Parser | `champion_builder.py` | Uporządkowany słownik nagłówków + jedna segmentacja. Sekcja kończy się tam, gdzie zaczyna się następny **znany** nagłówek. |
| Guard | `champion_builder.py` | Odrzucanie wpisów niebędących chipami + twardy limit 40 pozycji + `ChampionParseDiagnostics`. |
| Ostrzeżenie | `standalone_service.py` | `_champion_parse_warnings()` — rekruter widzi na liście CV, że parse wyszedł nieprawdopodobnie. |
| Renderer | `docx_renderer.py` | Obcięcie interpunkcji końcowej przed testem na znaki specjalne. |
| Frontend | `CVGeneratorStandaloneV2.tsx`, `lib/cv-generator.ts` | Trwały Alert zamiast toastu, reset `input.value`, naprawiony `fileValidationError`. |

### Decyzje projektowe warte zapamiętania

- **Słownik nagłówków pokrywa oba szablony.** Nagłówki szablonu Delivery Leada odtworzone z danych produkcyjnych, z liczbami wystąpień w komentarzach przy każdym wpisie.
- **Kotwica tylko na POCZĄTKU linii.** Kotwica końca linii byłaby regresją: układ `MUST-HAVE: Java, Python` (chipy w linii nagłówka) przestałby się dopasowywać, dając pustą listę. Kotwica początku realizuje całą potrzebną ochronę przed odpalaniem terminatora w środku zdania.
- **Dopasowanie po lustrze tekstu** ze złożonymi polskimi znakami i myślnikami — w prod występują oba zapisy (`Główne źródła` / `Glowne zrodla`, `OFFLIMIT - TAK` / `OFFLIMIT – TAK`). Fold jest 1:1 (26 wpisów, zweryfikowane), więc offsety wskazują z powrotem na oryginał.
- **`Pytanie 1:` / `Idealna odpowiedź:` / `Deal breaker:` świadomie NIE są nagłówkami** mimo 286/781/783 wystąpień — to wewnętrzna struktura bloku screeningowego. Uczynienie ich granicami ucięłoby `screening_questions` po pierwszym pytaniu.
- **Progi guarda mają >2× zapasu** nad najdłuższym prawdziwym chipem (`Microsoft Dynamics 365 Business Central` = 39 znaków).
- **Ostrzegamy, nie blokujemy** — `canSubmitOld` bez zmian. Zmiana semantyki przycisku dla 25 rekruterów w trakcie zmiany to osobna decyzja produktowa.

## 3. Weryfikacja

Testy uruchomione w **obrazie produkcyjnym** (`ocgkwcbovpve9wvf9smxl0kx_backend`) w kontenerze jednorazowym, ze zmiennymi jak w CI — lokalnie jest tylko python 3.9 bez `python-docx`.

```
backend:  125 passed  (104 istniejące, bez zmian)
frontend: 502 passed  (50 plików)
ruff check + ruff format: czysto
tsc --noEmit + next lint: czysto
```

Sonda przed/po na kształcie prawdziwego dokumentu:

```
PRZED (kod z main)          PO (fix)
16 pozycji                  3 pozycje
najdłuższa 109 znaków       najdłuższa 39 znaków
wyciekły: OFFLIMIT,         wycieki: BRAK
  "Nie blokujemy",
  "Sprawdzajcie",
  "Kluczowe słowa"
pogrubione: "kandydata."    pogrubienia: BRAK
```

## 3a. Co złapał adversarialny przegląd

Pierwsza wersja poprawki przechodziła 119 testów i mimo to miała **regresje**. Przegląd wieloagentowy (4 soczewki × weryfikacja przez wykonanie kodu) wyłapał je, bo fixture'y testowe systematycznie omijały te ścieżki — `_champion_docx(*paragraphs)` zawsze stawiał nagłówek w osobnym akapicie, więc układ jednoakapitowy nie był w ogóle testowany.

| # | Co było zepsute | Skutek |
|---|---|---|
| 1 | Nagłówki prozą kończyły się na `[^\n]*` — zjadały treść zapisaną w tej samej linii | `O projekcie: <opis>` w jednym akapicie Worda → **puste** `project_context`, `responsibilities`, `historical_questions`, `consultant_insight`. Cicho — bez ostrzeżenia. Na `main` te pola miały treść. |
| 2 | `Delivery\s+Lead\b` odrzucało polską odmianę „Delivery **Leada**" | Blok screeningowy przestawał być granicą → `responsibilities` wchłaniało pytania rekrutera i szło z nimi do Claude. |
| 3 | Zachłanne `\s*` po MUST-HAVE przechodziło przez znak nowej linii | Skan wznawiał się w środku linii, `(?m)^` nie mógł już trafić → następny nagłówek pomijany; literalne `"NICE-TO-HAVE: AWS"` lądowało jako chip must-have. |
| 4 | `implausible` nie miało gałęzi „odrzucono wszystko" | Champion z wymaganiami opisanymi zdaniami → puste listy, zero pogrubień, **zero ostrzeżenia**. |
| 5 | Guard traktował skrót jako koniec zdania | Wypadały prawdziwe chipy: `specjalista ds. compliance` (kanoniczna nazwa w `seed_skill_aliases.py`), `j. angielski B2`, `min. 3 lata Kubernetes`. |
| 6 | Test „ostrzegamy, nie blokujemy" był pusty | Asercja `toBeDisabled()` pod nazwą obiecującą odwrotność; żaden test nie podpinał CV, więc przycisk był wyłączony z innego powodu. Mutant `!!cvFile && !championError` przechodził na zielono. |

Wszystkie naprawione, każda z testem regresyjnym. Test frontendowy zweryfikowany mutacją: mutant łapany, czysty kod przechodzi.

## 4. Zakres świadomie pominięty

- **Warstwa naprawy JSON od Claude** — już naprawiona w `48685d5` (2026-07-13 15:09 UTC); ostatni taki fail na prod był 15:10 UTC tego samego dnia, od tego czasu zero. Nie ruszane.
- **Mapowanie sekcji szablonu Delivery Leada do promptu.** Sekcje takie jak „Co przekona kandydata do oferty?" niosą realną wartość pozycjonującą, ale wpuszczenie ich do promptu to decyzja produktowa, nie naprawa błędu.
- **Kolejność `_extract_docx`** — python-docx emituje najpierw wszystkie akapity, potem wszystkie komórki tabel, więc szablon trzymający nagłówki w akapitach a treść w tabelach segmentowałby się w złej kolejności. Nie zweryfikowane na prawdziwym pliku; guard kształtu i tak ogranicza szkodę, a ostrzeżenie czyni ją widoczną. Osobny PR, jeśli telemetria pokaże, że ostrzeżenie odpala się szeroko.

## 5. Do zrobienia po merge

1. Sprawdzić na prod, jak często odpala się ostrzeżenie „nietypowy układ dokumentu" — to miara, ile szablonów wciąż nie jest rozpoznawanych.
2. Zapytać Piotra o rozszerzenie jego pliku championa (musi być `.docx`) — po tej zmianie zobaczy trwały komunikat zamiast znikającego toastu.
3. `tests/test_champion_ai_intake.py` i `tests/test_champion_historical_jobs.py` istnieją na dysku, ale **nigdy nie były w liście CI** w `ci.yml`. Osobny PR — mogą ujawnić niezwiązane, zastane błędy.
