# Podział projektów (aktywne/zamknięte) + wyszukiwarka w zakładce „Projekty"

> Ścieżka: **Klienci → [klient] → Projekty**. Zmiana dotyczy widoku Projekty u
> wszystkich klientów. Frontend-only — bez zmian w backendzie i bez migracji DB.

## Co się zmieniło

Zakładka „Projekty" pokazywała wszystkie oferty (Job) klienta jedną płaską listą,
bez podziału na status i bez wyszukiwania. Teraz:

1. **Dwie sekcje z osobnymi nagłówkami** — „Aktywne projekty" i „Zamknięte
   projekty", każda z licznikiem widocznym również po zwinięciu (użytkownik od
   razu widzi, ile jest w toku, a ile zamkniętych).
2. **Wyszukiwarka** nad listą — filtruje po nazwie projektu (tytuł oferty).
3. **Segregacja istniejących danych** — automatyczna, na podstawie bieżącego
   `status` każdej oferty. **Nie wymaga migracji** (patrz niżej).

## Kluczowe decyzje

### „Projekt" = Job (oferta / zapytanie rekrutacyjne)
Zakładka Projekty pobiera `/api/jobs?client_id=…`. Status oferty (`JobStatus`)
ma trzy wartości: `draft`, `published`, `closed`.

### Podział aktywne vs zamknięte
Binarny, na istniejącym `status`:
- **Zamknięte** = `status == closed`
- **Aktywne** = wszystko poza `closed` (`draft` + `published`, tj. „w toku")

Realizowane **dwoma zapytaniami do serwera** (nie filtrem po pobranej stronie):
- aktywne → `GET /api/jobs?client_id=…&open_only=true`
- zamknięte → `GET /api/jobs?client_id=…&status=closed`

Osobne zapytanie na aktywne gwarantuje kompletność sekcji podstawowej — długa
historia zamkniętych ofert nigdy nie wypycha aktywnych poza stronę.

### Brak migracji danych
Każda oferta ma już `status` w bazie. „Segregacja istniejących danych" to czyste
**grupowanie po istniejącym statusie** w warstwie prezentacji — zero DDL, zero
backfillu, zero ryzyka na produkcji. Wszystkie obecne oferty automatycznie trafią
do właściwej sekcji przy pierwszym otwarciu zakładki.

### Wyszukiwarka — server-side + debounce 300 ms
Zgodnie z istniejącym wzorcem w repo (rejestr umów B2B): parametr `q` na serwerze
(`Job.title ilike %q%`), `useDebouncedValue(search, 300)`. W odróżnieniu od filtra
po stronie klienta przeszukuje **pełny zbiór**, nie tylko pobrane 100 wierszy.
300 ms daje odczucie „w czasie rzeczywistym" bez strzału na każdą literę.

### Rozwijanie sekcji (decyzja produktowa — łatwo odwracalna)
Wymóg zostawiał „obie rozwinięte vs zwijane" do ustalenia z produktem. Wybrano:
- **Aktywne — rozwinięte domyślnie** (spełnia „domyślnie widoczna sekcja Aktywne").
- **Zamknięte — zwinięte domyślnie** (odciąża widok; licznik i tak widoczny).
- **Aktywne wyszukiwanie wymusza rozwinięcie obu sekcji** — inaczej trafienie w
  zwiniętej sekcji zamkniętych byłoby niewidoczne.

Użyto natywnego `<details>/<summary>` — ten sam idiom, co pozostałe collapsible na
stronie klienta. Flip na „obie rozwinięte" = zmiana dwóch wartości domyślnych stanu.

### Pustka po wyszukaniu ≠ brak projektów
Osobny komunikat „Brak projektów pasujących do wyszukiwania" vs „Brak aktywnych/
zamkniętych projektów" — pustka wyszukiwania nie może czytać się jak utrata danych
(ten sam wzorzec co w rejestrze umów B2B).

## Zmienione / dodane pliki

| Plik | Zmiana |
|---|---|
| `frontend/src/app/clients/[id]/ProjectsTab.tsx` | **Nowy** — komponent zakładki (podział + wyszukiwarka). Sibling-tab pattern jak `ProfileTab`/`OwnersTab`. |
| `frontend/src/app/clients/[id]/page.tsx` | Usunięto inline `ProjectsTab` (płaska lista), dodano import wyodrębnionego komponentu, usunięto nieużywany import `ExternalLink`. |
| `frontend/src/app/clients/[id]/__tests__/ProjectsTab.test.tsx` | **Nowy** — 7 testów (Vitest + RTL). |

## Weryfikacja

Worktree z własnym `node_modules` (`npm ci --legacy-peer-deps` — deps różnią się
majorami od głównego repo: Tailwind 4 vs 3, więc pożyczenie node_modules dałoby
fałszywe wyniki).

- `npx tsc --noEmit` → **exit 0** (czysto)
- `npm run lint` → **exit 0** (jedyne ostrzeżenia pre-existing w innych plikach;
  moje pliki bez ostrzeżeń)
- `npm run test` (plik ProjectsTab) → **7/7 pass**
- `npm run build` → **exit 0** (`✓ Compiled successfully`, 79/79 stron)

Testy pokrywają: segregację po statusie do właściwych sekcji, osobne zapytania
(`open_only` vs `status=closed`), liczniki w nagłówkach, domyślny stan rozwinięcia
(aktywne otwarte, zamknięte zwinięte), wywołanie serwera z `q` (debounced),
wymuszone rozwinięcie sekcji zamkniętych przy wyszukiwaniu, oraz rozróżnienie
pustki wyszukiwania od braku danych.

## Znane ograniczenia / możliwe następne kroki

- **Sufit 100 na sekcję** (`page_size=100`). Dla widoku pojedynczego klienta to
  praktycznie zawsze pełen zbiór; gdy zamknięta historia przekroczy 100, sekcja
  pokazuje delikatny hint „Pokazano N z M — zawęź wyszukiwaniem" (bez cichego
  ucięcia). Ewentualny paginator/infinite-scroll = przyszłe rozszerzenie.
- **Wyszukiwanie po tytule** (jak w całym app-wide job search). Rozszerzenie `q` o
  lokalizację itp. wymagałoby zmiany backendu (dotyka wszystkich callerów) — poza
  zakresem „po nazwie (i ewentualnie…)".
- **Weryfikacja wizualna przez Chrome**: ekran jest za auth (JWT middleware), a w
  tym worktree nie ma uruchomionego backendu/DB, więc pełny smoke przez przeglądarkę
  nie był wykonany. Zachowanie DOM/UX pokryte testami jednostkowymi (jsdom).
  Do sprawdzenia na środowisku z pełnym stackiem po deployu.
