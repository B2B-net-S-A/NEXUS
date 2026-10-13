# „Przypisz do rekrutacji” przy zamkniętej karcie i ostrzeżenie przy zamykaniu — raport (13.10.2026)

Ciąg dalszy `docs/add-to-recruitment-closed-card-completion-report.md`: dwie
rzeczy zgłoszone tam jako poza zakresem.

## 1. „Przypisz do rekrutacji”

**Było:** `POST /api/candidates/{id}/assign-to-job/{job_id}` odpowiadał 200
`already_in_pipeline` dla każdej osoby z jakimkolwiek wierszem etapu — także
odrzuconej kilka dni wcześniej. Okno „Przypisz do rekrutacji”, widżet dopasowań
i karta kontraktora pokazywały wtedy sukces („Przypisano”).

**Jest:** dla karty w „Zamkniętych” człowiek dostaje 409 `closed_in_job` z tym
samym zdaniem i celem ruchu co w oknie „Dodaj do rekrutacji”. Okno „Przypisz do
rekrutacji” pokazuje je i przywraca kartę ruchem karty; pozostałe dwa ekrany
pokazują zdanie z serwera jako błąd. Karta w toku i integracja — bez zmian.

## 2. Zamknięcie rekrutacji z osobami w toku

**Było:** zamknięcie zmienia status i nie rusza kart, a okno nic o nich nie
mówiło. 12.10.2026 zamknięto tak duplikat requestu z pięcioma kartami w toku.

**Jest:** `POST /api/jobs/{id}/close` i zamknięcie statusem z okna edycji
(`PATCH /api/jobs/{id}`) bez potwierdzenia odpowiadają 409
`active_cards_warning` z liczbą osób per kolumna Tablicy i dniem ostatniego
ruchu. Trzy okna zamykania („Zamknij rekrutację z powodem”, „Zamknij jako
przegraną”, „Edytuj rekrutację”) pokazują ostrzeżenie i przycisk „…mimo to”.
Ostrzeżenie niczego nie robi z kartami; automaty zamykają jak dotąd.

Trzecią drogę (okno edycji) i panel zamkniętej karty poza widokiem w oknie
„Przypisz do rekrutacji” wskazał przegląd kodu przed otwarciem PR-a.

Reguły: `docs/claude/rekrutacja-tablica/dodaj-do-rekrutacji-zamknieta-karta.md`,
`docs/claude/rekrutacja-tablica/zamkniecie-rekrutacji-osoby-w-toku.md`.

## Weryfikacja przed scaleniem

| Co | Wynik |
|---|---|
| Vitest: trzy okna, harnessy, inwentarze funkcji, `lib/` (bieg seryjny) | 381 plików, 5 242 testy zielone |
| `npm run type-check`, ESLint na zmienionych plikach | czyste |
| Backend bez bazy: testy podsumowania osób w toku, strażnicy źródeł, wzorzec uprawnień tras | zielone |
| `ruff check` / `ruff format --check`, `check_stamps.py`, indeks `CLAUDE.md` | czyste |
| Okno zamykania w harnessie `/preview/job-detail?close=1`, szerokość 1280: ostrzeżenie → „Zamknij mimo to” → zamknięcie | przeklikane |
| Testy z bazą (zamknięcie z osobami w toku, odmowa przypisania przy zamkniętej karcie) | w CI — patrz PR |

Niesprawdzone w przeglądarce: panel zamkniętej karty wewnątrz okna „Przypisz do
rekrutacji” (ten sam komponent co w oknie dodawania, obejrzany 12.10; test okna
zastępuje hak ruchu atrapą; panel przewija się do widoku przy pojawieniu)
oraz ostrzeżenie w oknie „Edytuj rekrutację” (test komponentu, ta sama ramka
co w oknie zamykania).

## Poza zakresem

- Promocja z shortlisty, „Dodaj championa” i wtyczka LinkedIn nadal traktują
  jakikolwiek wiersz etapu jako „już w rekrutacji”.
- Harness strony rekrutacji loguje w konsoli błąd wczytania szablonu etapów
  (sieć jest tam wyłączona) — stan sprzed tej zmiany.
