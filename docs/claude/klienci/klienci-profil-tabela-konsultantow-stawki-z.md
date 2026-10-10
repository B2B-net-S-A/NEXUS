# Klienci → Profil: tabela konsultantów + stawki z harmonogramu

Sekcja „Konsultanci" (`app/clients/[id]/ProfileTab.tsx`) renderuje **tabelę**
(`components/client-profile/ConsultantsTable.tsx`), nie karty. Kolumny: `Konsultant`
(nazwisko / tag CC / **rekrutacja**) · `Start date` · `Stawka kosztowa [godz.]` ·
`Stawka przychodowa [godz.]` · `Marża [mc]` (+ `End date` tylko w Archiwum, + `Akcje` w obu).

- **Obie stawki są GODZINOWE i idą Z ZAMÓWIENIA, marża MIESIĘCZNA (ticket 09.2026).**
  Kolumny czytają `hourly_rate_candidate`/`hourly_rate_client` (`clients._order_hourly_leg`
  na `_representative_order` — tym samym, z którego idzie rekrutacja i część umowy;
  w Archiwum na dzień zakończenia). Lustro zakładki „Zamówienia": linia MD/kosztowa
  → `md_rate_*` PLN/MD (waluta obca → `rate_*` linii), zamówienie okresowe → `rate_*`
  w `rate_unit` zamówienia; godzinowa bez przeliczenia, MD ÷ 8. **Nie czytaj tu stawek
  kontraktu jako pierwszych:** na prodzie (14.09.2026, Polkomtel) linie MD nie
  zsynchronizowały stawek do kontraktu (kontrakt 800, zamówienie 750 zł/MD) i profil
  rozjeżdżał się z zakładką Zamówienia. Kontrakt jest wyłącznie zapasem (brak
  zamówienia albo stawki na nim). Typ `GroszePLN` (grosze, `float`), NIE `WholePLN`.
  Marża i kafel „Aktywne MRR" zostają miesięczne z kontraktu (kafel = suma kolumny
  „Marża [mc]") — decyzja Artura; przy rozjechanym kontrakcie marża w wierszu nie
  wynika więc z dwóch stawek obok. Pola godzinowe redagowane razem z miesięcznymi.

- **Stawki idą z HARMONOGRAMÓW, nie z kolumn `contracts.rate_*`.** Kolumna niesie
  wartość zapisaną przy ostatnim ZAPISIE kontraktu, więc stawka progresywna albo
  aneks z datą, która już nadeszła, pokazywały tu STARĄ kwotę — a wraz z nią złą
  marżę i zaniżone „Aktywne MRR". `clients.py` reużywa
  `app.api.contracts._effective_rate_fields` (brak cyklu importów: `contracts.py`
  nie importuje `clients.py`). **Oba zapytania MUSZĄ `selectinload` trzy
  harmonogramy** (`candidate_rate_schedule`, `client_rate_schedule`,
  `framework_rate_schedule`) — bez nich helper robi lazy-load w async i leci
  `MissingGreenlet` 500 bez CORS, w UI „Nie udało się wczytać profilu".
- **Archiwum liczy stawki na DZIEŃ ZAKOŃCZENIA** (`end_date` → `terminated_at` →
  dziś), nie na dziś: to zapis historyczny, a krok harmonogramu zaplanowany po
  zakończeniu projektu nigdy w jego trakcie nie obowiązywał. `total_revenue` i LTV
  dostają tę samą stawkę wstrzykiwaną parametrem — inaczej wiersz pokazywałby sumę
  policzoną z innej kwoty niż ta obok niej.
- **`active_mrr` liczy się z tego samego słownika co wiersze.** Kafel będący sumą
  innych liczb niż widoczne pod nim nie daje się zweryfikować wzrokiem.
- **`HistoricalPlacementItem` dostał `job_id` + trzy kwoty** (`WholePLN`), objęte tą
  samą redakcją `VIEW_FINANCE` co wiersz aktywny — inaczej rola bez uprawnień
  zobaczyłaby w archiwum dokładnie to, co ukrywamy jej w zakładce obok.
- **Brak rekrutacji zostawia PUSTY wiersz**, nie „brak powiązanej rekrutacji" —
  tekst zastępczy w kolumnie danych czyta się jak wartość, a nie jak jej brak.
- **Kwoty renderują się jako „—" (`formatPLN(null)`), nie znikają** — znikająca
  komórka zostawiłaby roli bez `VIEW_FINANCE` trzy puste kolumny bez wyjaśnienia.
- Podzakładki na `ds/TabbedNav` (`role="tab"`/`aria-selected`, liczniki), jak
  w sąsiednim `ProjectsTab`. `ConsultantRow.tsx` i `PlacementRow.tsx` usunięte.
- **Liczby klienta stoją w nagłówku profilu** (02.10.2026): `ClientHeaderStats`
  w `client-profile/SummaryBar.tsx` na `ds/InlineStats`, dane z tego samego
  zapytania co tabela (`useClientProfile`). `components/StatsCard.tsx` usunięty;
  `components/ds/StatCard` to inny komponent (pulpity) i zostaje.
