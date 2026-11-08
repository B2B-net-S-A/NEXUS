# Nowi w bazie najpierw — „Nowi” i „Propozycje z bazy”
<!-- indeks: `has_fresh_first`, `new_in_base_picks`, `FRESH_OVER_TARGET`, 5 kart ponad 20, `NEW_COLUMN_FRESH_FIRST_ENABLED`, sekcja „Nowi w bazie”, `entry_meta.fresh_first` -->

Decyzja Artura z 03.11.2026, wariant A i próg 70%, makiety i pomiar:
https://claude.ai/artifact/S5WGhHEWb8WA5wWvKGaBWA. Nexus ma proponować najpierw osoby
niedawno dodane do bazy, jeśli spełniają wymagania rekrutacji. Do tej daty kolejność znała
tylko wynik i historię, a 173 ze 189 rekrutacji miało pełne „Nowe”, więc świeża osoba
czekała poza Tablicą: w piątkach „Zadzwoń najpierw” było 14 takich osób na 822 miejsca.
Osoby do 30 dni to 5,6% bazy, 30% wysłanych od 01.10 i 7,9% kart od systemu.

## Kto ma pierwszeństwo

Wszystkie warunki naraz, te same na Tablicy, w silniku i w skrzynce:

- **Nowa w bazie:** data dokładna i najwyżej 14 dni kalendarzowych Europe/Warsaw
  (`candidate_added_date.is_new_in_base`, `new_in_base_clause`; definicja i próg
  z `screening-notatki/w-bazie-od-data-wejscia-do-bazy.md`). Osoba z importu bez daty
  u źródła się nie liczy.
- **Od progu:** `proposal_threshold`, ten sam co panel „Ranking kandydatów”. Niższego progu
  dla świeżych nie ma: przy 60% to mediana 152 osoby na rekrutację, przy 65% 29, przy 70% 8.
- **Bez uwag:** przechodzi `_by_rules` i nie ma `cautions` (budżet, biuro, miasto).
  Inna rola, pominięta propozycja i pozostałe wyjątki z `ranked_picks` działają jak zawsze.

Przy dodaniu dochodzi bramka kwalifikacji (`_allowed`), tak jak przy każdej karcie od systemu.

„Spełnia wymagania” znaczy tu: krytyczne spełnione i wynik od progu. Pozostałe „musi mieć” liczą się
w wyniku, więc osoba może mieć braki: 293 z 381 osób z pierwszeństwem miało niepuste `missing_must`
(0 brakujących krytycznych, 03.11.2026). Dlatego okno pisze „wynik od 70%, krytyczne spełnione”.

## Reguły

- **Silnik** (`new_column_autofill.fill_job`): nowi w bazie wchodzą pierwsi, także przy
  pełnej kolumnie, do `TARGET + FRESH_OVER_TARGET` (25 kart). Pozostałych dobiera tylko
  do `TARGET`. Kart nie zdejmujemy: wygaszanie nietkniętych kart odrzucone 28.10.2026.
  Migawka `entry_meta.fresh_first` odróżnia karty, które weszły z tej reguły. Na niej
  oprzyj pomiar skutku. Przy `NEW_COLUMN_TEMPO_TARGET_ENABLED` (08.11.2026) nowi w bazie
  nie wchodzą ponad cel, tylko zajmują miejsce kart nietkniętych 7 dni:
  `cel-kart-wg-tempa-i-miejsce-dla-swiezych.md`.
- **Tablica** (`autofill_badge` + `api/pipeline.py`): serwer liczy `entry_autofill.fresh_first`
  na żywo (`has_fresh_first`), więc karta traci pierwszeństwo po 14 dniach i obejmuje też
  karty dodane przed tą zmianą. Front (`orderNewColumn`) stawia je przed pozostałymi bez uwag,
  a brak krytycznej dalej cofa na koniec. Bierze górę nad punktami „znamy tę osobę”: to świadomy
  koszt decyzji, 197 z 729 znanych osób wypada z piątki (pomiar z 03.11.2026). Plakietka to
  istniejące „Nowy · N dni”.
- **Skrzynka** (`GET …/proposal-inbox`): pole `new_in_base_at` przy osobie i `new_in_base_total`,
  kolejność z `list_for_job(first_ids=…)`, stabilna między stronami. Sekcja „Nowi w bazie”
  w oknie tylko w zakładce „Propozycje z bazy” przy sortowaniu „Dopasowanie”; „Najpierw byli
  u tego klienta” to jawny wybór innej kolejności.
- **Bez zmian:** procent na karcie, `canonical_fit`, panel wag, „Szukaj w bazie” i „Szukaj ręcznie”
  (pomiar z 25.09: „najnowsi” 33%, dopasowanie 83%, `kandydaci-wyszukiwanie/kolejnosc-dopasowanie-i-gorne-pole-listy.md`).
  Tamten wniosek dotyczy sortowania całej bazy, a nie pierwszeństwa wśród osób od progu.
  Zgłoszenia z portali (`job_board`) nadal nie dostają karty bez człowieka.
- **Co 5. miejsce dla osoby bez procesu** (`kolejka-w-nowych.md`) działa dalej, za nowymi w bazie.
  To dwie reguły o różnych osobach: tu liczy się data wejścia do bazy, tam brak wiersza etapu w innej
  rekrutacji. Miejsce liczy się w całej kolejce, więc przy trzech nowych w bazie piąte miejsce nadal
  należy do osoby bez procesu.
- **Wyłącznik:** `NEW_COLUMN_FRESH_FIRST_ENABLED=false` (workflow „Coolify set env”) przywraca
  „Nowych” i skrzynkę sprzed zmiany. Karty dodane ponad 20 zostają, silnik po prostu nie dobiera.

## Czego to nie obejmuje

Osób poniżej progu i osób dodanych do bazy pod konkretną rekrutację: 105 z 202 wysłanych do 30 dni
weszło do bazy i rekrutacji w ciągu doby, a z 52 dodanych ręcznie po 2–30 dniach w bazie 20 miało
wynik poniżej 70%. Przy 15 z 25 bez wpisu w dzienniku auto-matcha rekrutację założono po wejściu
osoby do bazy, więc ocenia ją dopiero nocny przegląd (mediana 77 h, `full_base`).

Testy: `backend/tests/test_new_column_autofill.py`, `test_job_proposals.py`,
`frontend/src/lib/__tests__/new-column-queue.test.ts`, `AddCandidatesPanel.test.tsx`.
