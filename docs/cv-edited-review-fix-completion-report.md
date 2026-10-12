# CV zapisane w edytorze: kontrola AI i lista punktów w QC — raport

Gałąź `fix/cv-edited-review-and-qc-list`, 12.10.2026. Bez migracji bazy, bez zmian frontendu.
PR 0 z planu „Edytor CV 2” (makiety i decyzje D1–D6 z 12.10.2026).

## Skąd zmiana

Przy planowaniu przebudowy edytora CV wyszły dwa błędy, które dotyczą każdego CV zapisanego
w edytorze. Oba są w ścieżkach, na których stanie panel „Do poprawy” (PR 2), więc idą przed nim.

| Pomiar na produkcji (odczyt 12.10.2026, same liczby) | Wynik |
|---|---|
| Zatwierdzenia po edycji od 27.09 do 12.10 | 12 |
| …z wynikiem `unverified / review_protocol_invalid_review` | 12 |
| Ostatnia kontrola, która faktycznie się wykonała | 22.09 (`reviewed`) |
| Poprawki QC nałożone w 30 dni | 27 na 5 CV (21 propozycji AI) |

## Co się zmieniło

### Kontrola AI po edycji

- Przyczyna: `verify_editor_content` podawało wszystkie linie edytora jako `why_points`, a od
  PR #1730 recenzent nie traktuje tej sekcji jako twierdzeń. Zero twierdzeń = błąd protokołu
  przed wywołaniem modelu.
- `verify_final_cv` przyjmuje jawną listę twierdzeń (`claims`); prompt i projekcja generatora
  są bez zmian.
- Edytor podaje jako twierdzenia linie faktów. Kontekstem zostają: sekcja narracyjna, tytuły
  sekcji, klauzula zgody RODO, etykieta obowiązków i linia „Rozważany na stanowisko”.
- `EDITOR_REVIEW_VERSION = 2`, żeby wcześniejsze „niezweryfikowane” wyniki nie wracały
  z ponownego użycia.

### Lista punktów w QC

- Przyczyna: edytor zapisuje punkt jako `<li><p>…</p></li>`; parser bloków zakładał na
  wewnętrznym akapicie blok „p” i porzucał pusty „li”.
- Skutek przed poprawką: „Zastosuj” dopisywało `<ul><li>` wewnątrz ostatniego punktu roli,
  usunięcie technologii zostawiało pusty punkt, a okno QC pokazywało punkty bez punktorów.
- Parser czyta `<li><p>` jako jeden punkt; edycja zna zakres całego `<li>`; nowy punkt
  dostaje kształt sąsiada. Wynik sprawdzeń QC (blokady i uwagi) się nie zmienia — od rodzaju
  bloku zależą tylko dopisanie i usunięcie punktu, prefiks w prompcie i punktor w oknie.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Testy odtwarzające błędy | czerwone przed poprawką | commit `test(cv): …` — 6 testów padało lokalnie (zero twierdzeń u recenzenta; lista w liście) |
| Kontrola AI po edycji | zielone lokalnie | `tests/test_cv_editor_review.py`, `tests/test_cv_final_review_advisory.py`, `tests/test_cv_factual_verification.py`, `tests/test_cv_approval_review.py` |
| Lista punktów w QC | zielone lokalnie (część bez bazy) | `tests/test_cv_qc.py`, `tests/test_dz_review.py` |
| Testy z bazą | tylko CI | m.in. `test_ai_fix_is_proposed_from_sources_and_applied_to_the_draft` |
| Lint i format | zielone | `ruff check`, `ruff format --check` (wersja z CI) na zmienionych plikach |

## Niepotwierdzone

- Na produkcji: pierwsze zatwierdzenie po edycji po wdrożeniu powinno dać wynik inny niż
  `review_protocol_invalid_review`. Zatwierdzenia nie wywołuję sam (to zapis) — sprawdzenie
  odczytem po pierwszym użyciu przez zespół.
- Ile uwag recenzent zgłosi na prawdziwych edytowanych CV: nie zmierzone. Kontrola jest
  doradcza i nie blokuje zatwierdzenia.

## Poza zakresem

- Pokazanie uwag kontroli przy tekście — PR 2 (dziś wynik to dymek z liczbą uwag).
- `qc/apply` nie sprawdza wersji szkicu (`expected_revision`) — warunek wstępny PR 2.
