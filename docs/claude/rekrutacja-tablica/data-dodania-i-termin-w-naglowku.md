# „Dodana → Termin” w nagłówku rekrutacji (19.11.2026)
<!-- indeks: jedna pigułka „18.11 → 23.11 · za 4 dni” za trybem pracy, po terminie zawsze czerwone, pusty „proces” poniżej 2xl to ikona -->

Decyzja Artura z 19.11.2026 („Dodajmy w rekrutacji Datę Dodania + Deadline,
aby wyświetlało się obok niebieskich okienek”), makieta wariant B ze stagingu
przy 1280 × 720. Cofa część decyzji z 02.10.2026, według której termin
mieszkał tylko w Profilu Championa
(`prostszy-ekran-rekrutacji-fakty-kafle-kandydaci-do.md`).

- **Jedna pigułka za Klient · Budżet · Tryb pracy:** `18.11 → 23.11 · za 4 dni`
  (`components/v2/jobs/JobDatesFact.tsx`, wpięta propem `dates` w
  `JobDetailCompactHeader`). Pełne daty z rokiem i godziną są w dymku
  i w `aria-label`. Godzina terminu stoi w pigułce tylko dziś i jutro.
- **Data dodania** = `opened_effective_at` (`opened_at`, a bez niej
  `created_at`) — ta sama data co kolumna „Otwarta” na liście `/jobs`.
  `created_at` rekrutacji z Traffita to moment importu, nie otwarcia.
- **Termin** = `deadline` + `deadline_time`; bez daty pigułka mówi
  „klient nie podał” (`deadline_not_provided`) albo „nie podano” — nigdy
  pustka.
- **Kolor końcówki:** ≤ 7 dni `text-warning-muted-foreground`, **po terminie
  zawsze czerwone** z liczbą dni (decyzja Artura 19.11.2026, choć na kopii
  z 19.11 było to 53 z 62 otwartych rekrutacji z terminem). Nie wygaszaj
  czerwieni po kilku dniach bez nowej decyzji.
- **Miejsce przy 1280 px:** linia faktów miała 0–155 px wolnego, dwie pełne
  pigułki to ok. 400 px i nachodziły na nazwę klienta. Dlatego jedna pigułka,
  a pusty „proces: nie podano” (`JobClientProcessFact`) poniżej `2xl` to sama
  ikona z dymkiem — jak „Szukamy N osób”, które poniżej `2xl` pokazuje samą
  liczbę. Kolejna pigułka w tej linii wymaga pomiaru na rekrutacji z długim
  trybem pracy (np. „Hybrydowo · 4 dni w tygodniu · Warszawa”).
- **Krótkie teksty poniżej `2xl`** (decyzja Artura 19.11.2026): bez nich na
  BNP tryb pracy ścinał się do „H…”. Tryb pracy „Hybrydowo · 4 dni/tydz. ·
  Warszawa” (`JobHeaderFact.short`, `jobWorkModeShort` z `officeDaysShort`),
  końcówka „po terminie 1 dz.”, słowo „Rekruter” w `JobRecruiterFact` tylko
  od `2xl` (awatary i „Bez rekrutera” zostają, nazwa w `aria-label`); od
  `2xl` i w dymku pełne zdania. Jednowyrazowy tryb („Zdalnie”) ma
  `shrink-0` — ustępuje nazwa klienta. Pomiar na 30 losowych otwartych
  rekrutacjach przy 1280 px: tryb pracy ścięty przed zmianą 18, po 18
  (długie listy miast, pełne w dymku), klient 18 → 19, zero nakładania.
- Zwinięty nagłówek (jedna linia) pigułki nie pokazuje.
