# „W drodze” bez złączeń CTE ze sobą, `GET /api/jobs?compact=true` dla podglądu na telefonie
<!-- indeks: in-flight/me 2 s na każde wywołanie przez złe szacunki planera, okna zamiast złączeń, weryfikujący raz na parę, porównanie starego i nowego SQL na kopii, _COMPACT_ROW_FIELDS -->

Pomiar z 05.11.2026 na kopii produkcji. Definicje liczb bez zmian.

## `insights_in_flight._pairs_now`

- `in-flight/me?scope=mine` odpowiadało 1,5–2 s na każde wywołanie, także dla konta bez
  par, bo planer szacował 1 wiersz ze złączeń CTE i liczył pierwszego weryfikującego
  w każdym obrocie pętli: 681 394 razy, 3,8 mln bloków. Ścieżka bez właściciela (cała
  firma) tego nie miała, więc po czasie `/in-flight` problemu nie widać.
- Teraz kolumna i wejście do niej liczą się oknami w jednym przejściu, a weryfikujący raz
  na parę w `pairs AS MATERIALIZED`. Po zmianie 0,09–0,13 s. Nie wracaj do złączeń `columned`
  z `latest` ani do podzapytania o weryfikującego w `WHERE`.
- `_resolved_acceptances` nie liczy klucza dla całej historii (ok. 227 tys. wierszy), tylko
  dla par z akceptacją w oknie: 0,14 s → 0,02 s.
- Zmiana tych zapytań wymaga porównania starego i nowego SQL na kopii, na jednej migawce
  (`REPEATABLE READ READ ONLY`): cała firma i każdy właściciel. 05.11: 36 właścicieli,
  0 różnic. Małe dane z testów nie pokażą złego planu.

## `GET /api/jobs?compact=true`

- Pełny wiersz listy ma 111 pól, 21–24 KB po kompresji na 10–12 rekrutacji. `compact`
  zostawia `_COMPACT_ROW_FIELDS` (`api/jobs.py`): 0,6–1,7 KB. Filtry, sortowanie, `total`
  i `stage_columns` są te same, a wycinek powstaje po zdjęciu pól wrażliwych.
- Lista `/jobs` i kafelek „Moje rekrutacje” nie wysyłają `compact`, bo potrzebują zespołu,
  `can_open` i liczników.
- Nowe pole na liście w podglądzie (`components/phone-preview/RecruitmentsSection.tsx`) =
  wpis w `_COMPACT_ROW_FIELDS`, inaczej przyjdzie puste bez błędu.
