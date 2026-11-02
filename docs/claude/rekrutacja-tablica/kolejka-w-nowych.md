# Kolejka w „Nowych” — zespół na górze, potem system od najwyższego wyniku
<!-- indeks: `lib/new-column-queue.ts`, „Zadzwoń najpierw”, numer na karcie, `_newest_first` zostaje na serwerze, analiza 201 wysłanych CV -->

Decyzja Artura z 02.11.2026, makiety i pomiar:
https://claude.ai/artifact/8x6AxqnTihmecy2uw3Dhoh. Serwer układa kartę od
najmłodszego wejścia (`api/pipeline.py`, `_newest_first`, decyzja z 16.10.2026),
a silnik dopełniania dodaje najlepszych jako pierwszych. W każdej paczce kolejność
wychodziła więc odwrotna: najlepsza osoba stała średnio na 16. miejscu (korelacja
z wynikiem −0,80, ujemna w 151 ze 166 rekrutacji). Z 3 231 kart od systemu ruszono
12%, choć z miejsc 1–5 po wyniku do klienta szło 5,2%, a z miejsc 21+ 1,5%.

## Reguły

- **Kolejność liczy front** (`orderNewColumn`), przed filtrem „Kto dodał”, więc
  miejsce karty nie zależy od filtra, a strzałki panelu chodzą tą samą listą.
  `_newest_first` na serwerze zostaje: inne kolumny i inni czytelnicy z niego
  korzystają.
- **Na górze od najmłodszego:** osoby dodane przez zespół i karty od systemu,
  które ktoś wziął („Dzwonię”, „Biorę”, `decided`, aktywna blokada). Tak zostaje
  decyzja z 16.10: osoba dodana ręcznie nie ląduje w środku kolumny.
- **Pod nimi czekające karty od systemu:** od najwyższej sumy wyniku z migawki
  `entry_autofill.score` i punktów `entry_autofill.known.points`; najpierw bez uwag, potem z ostrzeżeniem (`cautions`),
  na końcu z brakiem krytycznej (`criticalGapMap`). Remis rozstrzyga numer osoby.
- **Pierwszych pięć to „Zadzwoń najpierw”** z numerem na karcie
  (`CALL_FIRST_COUNT`). Nagłówki rysują się tylko wtedy, gdy kolejka ma choć
  jedną kartę. Procent na karcie się nie zmienia.

## Znamy tę osobę

Silnik (`services/known_queue_points.py`) dodaje do kolejności +6 za weryfikację
u tego klienta, +8 za notatkę do 30 dni, +2 za notatkę do 90 dni. Wagi dobrane na
178 wysłanych z 01–22.10, sprawdzone z flagami produkcji na 146 wysłanych od 23.10
(bez osób dopisanych do bazy do 7 dni przed dodaniem): top 20 z 32% do 38%, top 40
z 49% do 62%, rekrutacje z trafieniem w top 20 z 45% do 62%. Mocniejsze „musi mieć”
i punkty za umiejętności nic nie dokładały.

- **Tylko kolejność.** `ranked_picks` sortuje po wyniku z punktami, a
  `entry_meta.score` i procent na karcie zostają sam wynik. Nie dodawaj punktów do
  `canonical_fit`.
- **Bez punktów zostaje tylko osoba jawnie odrzucona przez tego klienta**
  (`ended_by = 'client'`). Nie używaj tu warunku z `known_people_signal`: liczy
  też stare wiersze z pustym `ended_by` po wysyłce CV, pod który wpadało 33 z 82
  wysłanych ze zweryfikacją u klienta (top 40 spada wtedy z 62% do 53%, pomiar bez flag).
- **Tablica liczy fakty na żywo** (`entry_autofill.known`, dwa zapytania na odczyt
  Tablicy, tylko gdy są karty od systemu), więc świeża notatka podnosi kartę od razu.
- **Punkty ustawia Head of Recruitment** w „Ranking kandydatów → Wagi”
  (`PUT /api/scoring-weights/panel/known-points`, `app_settings.queue_known_points`).
  Działają od razu, bez szkicu i pomiaru panelu, bo nie zmieniają „Dop.” ani progu.
  Pomiar w tekście suwaka dotyczy wartości +6, +8, +2.

## Wysłani do klienta a system

Sekcja w „Insights → Jakość podpowiedzi systemu” (`services/sent_vs_system.py`,
pole `sent_vs_system` w `GET /api/autofill-quality/summary`). Pierwszy pomiar
z 23.10–02.11: ze 201 osób system pokazał 41%, 17% było spoza bazy, 42% znał i minął.

- **Liczymy z migawki przy dodaniu**, `entry_meta.system_view` (`snapshot_for_add`
  w `add_candidates_to_job`, dodanie przez człowieka). Nie przeliczaj tego przy
  wysyłce: pula jest co noc nadpisywana, a CV i wektor zmieniają się po rozmowie.
- **Migawka nie ma pola `kind`**, więc czytniki plakietek jej nie widzą. Awaria
  zostawia dodanie bez migawki (savepoint), nigdy nie blokuje osoby.
- Kategorie: `outside_base` (dopisana do bazy do 7 dni przed dodaniem), `top20`,
  `r21_40`, `r41_150`, `below_pool`, `hidden_gate`, `cut_rules`, `no_pool`. Źródła
  `system`, `proposal`, `reassign` liczą się jako pokazane, bez patrzenia na migawkę.
- Karty otwarte przed `MEASURED_SINCE` (03.11.2026) i osoby bez migawki to „Sprzed
  pomiaru”, także od systemu: są na pasku, ale procenty ich nie liczą. Inaczej do
  mianownika wchodziłyby dawne karty od systemu, a dawne ręczne nie.
