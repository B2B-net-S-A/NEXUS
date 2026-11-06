# „Ostatnie odrzucenie” na liście kandydatów: kolumna, pigułka i pasek (06.11.2026)
<!-- indeks: zamiast „Ostatniej rozmowy” na szerokim ekranie, filtr r:/t:/none, kto zakończył jak w Insights, pasek liczony bez samego filtra -->

Decyzja Artura 06.11.2026 (makiety: https://claude.ai/artifact/HfjaZy1PzPFEaLNMayNNfx,
wariant C): „zamiast ostatnia rozmowa bym dał tutaj filtry powód odrzucenia
z ostatniej rekrutacji”.

## Co widzi rekruter

- **Kolumna „Ostatnie odrzucenie”** stoi domyślnie na szerokim ekranie
  (≥ 1536 px) w miejscu „Ostatniej rozmowy”, która zostaje do włączenia
  w „Kolumny”. Przy laptopie 1280 × 720 kolumny domyślnie nie ma (decyzja:
  „tylko szeroki ekran”) — działa pigułka i pasek. Kolumna jest dodana po tym,
  jak ludzie zapisali swoje wybory, więc brak jej id na zapisanej liście
  znaczy „bez decyzji”, a włączenie zapisuje znacznik `last_rejection:shown`
  (`addedAfterSavedPrefs` w `candidate-table-columns.ts`). Bez tego każdy
  z zapisanym wyborem dostałby ją na laptopie.
- **Pigułka „Powód odrzucenia”** w rzędzie filtrów, obok „Rekrutacje
  i historia”: Pokaż tylko / Ukryj, okres (kiedykolwiek / 3 / 12 mies.),
  kto zakończył (Klient / My / Kandydat), powody NEXUSA i osobno kategorie
  Traffita. Liczby przy opcjach dotyczą bieżącego wyniku.
- **Pasek „Ostatnie odrzucenie” nad tabelą**: rozkład w całym wyniku, klik =
  pokaż tylko, drugi klik = ukryj, trzeci = zdejmij. Działa od razu, bez
  „Szukaj”, jak zdjęcie chipa.

## Definicje (jedno miejsce: `app/services/candidate_last_rejection.py`)

- **Ostatnie odrzucenie** = najnowszy wiersz `rejected`/`withdrawn`, który
  jest nadal stanem swojej pary (osoba, rekrutacja) — karta przywrócona
  w tej samej rekrutacji się nie liczy. Osoba może mieć po nim nowszy proces
  w innej rekrutacji; decyzja Artura: pokazujemy i filtrujemy ostatnie
  odrzucenie, a komórka dopisuje „potem: w toku”.
- **Klucz**: `r:<etykieta>` (powód ze słownika przez `rejection_reason_label`,
  oba „Inne (…)” to jedno „Inne”), `t:<kategoria>` (import z Traffita bez
  powodu — Traffit trzymał w `rejection_note` kategorię „Po CV”, „Po
  Interview”, „Odrzucenie oferty przez Kandydata”…, a nie powód), `none`.
  Zaślepka `legacy_unknown` to brak powodu.
- **Kto zakończył** = reguła Insights (`insights_stage_breakdown._closed_by`):
  `ended_by`, bez niego rezygnacja albo „… przez Kandydata” = kandydat,
  „… przez Klienta” = klient, reszta = my. Rekruter i DL to jedno „My”
  (w komórce DL ma własną etykietę). SQL i Python przypina test.
- **„Ukryj”** zostawia osoby bez żadnego odrzucenia. Samo „Ukryj” bez
  powodu, osoby i okresu niczego nie zawęża i nie trafia do adresu.

## API i adres

- `GET /api/candidates`: `rejection_key[]`, `rejection_by[]`,
  `rejection_within_months` (3 | 12), `rejection_exclude`;
  `include_last_rejection` (pole `last_rejection` w wierszu),
  `include_rejection_facets` (`rejection_facets` w odpowiedzi, liczone BEZ
  samego filtra odrzucenia — inaczej pasek pokazywałby tylko wybrane).
  Filtr jest tylko na liście (jak blok „Rekrutacje”), nie w wyszukiwarce S.
- Pasek to osobne zapytanie (`page_size=1`, `rejectionFacetsApiParams`),
  bez strony i sortowania w kluczu — zmiana strony go nie przelicza.
- Adres: `rej` (PIPE — etykiety mają przecinki, np. „Forma umowy (UoP, B2B,
  etat)”), `rej_by`, `rej_m`, `rej_x=1`. Flagi `include_*` są na listach
  pomijanych przy zapisie wyszukiwania (front i `saved_search_payload`,
  `saved_search_alerts`).

## Dane (staging, kopia 06.11.2026)

68 230 osób, 15 205 z ostatnim odrzuceniem: Traffit „Po CV” 8 051,
„Odrzucenie oferty przez Kandydata” 1 775, „Po Interview” 1 607, bez powodu
1 103, „Inne” 652, „Brak doświadczenia” 331. Powody ze słownika są dopiero
od startu NEXUSA (12.10.2026), więc dla starszych odrzuceń filtr ma tylko
kategorię Traffita i krótki opis. Filtr 30–40 ms, pasek na całej bazie 49 ms
(`NOT EXISTS` po `ix_analytics_cs_cand_job_moved`).
