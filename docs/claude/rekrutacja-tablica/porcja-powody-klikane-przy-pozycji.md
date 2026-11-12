# Porcja dnia: brak klikany przy pozycji, polski i angielski osobno, forma umowy
<!-- indeks: `autofill_feedback.gaps`, `clean_gaps`, `GAP_KINDS`, `autofill_gaps`, „brak” / „tylko wzmianka” / „za mało lat”, `no_polish`, `weak_english`, `contract_form`, `gapRows`, `gapsNote`, klawisze 1–9 i 0, migracja 0686 -->

Decyzja Artura z 12.11.2026 („implementuj wszystko zgodnie z rekomendacjami”),
raport z 323 odrzuceń porcji z 09–12.11 i makiety:
https://claude.ai/artifact/PqmctW9taWS8mXwmGfrFSM (R3, makieta M2). Rekruterzy
w 104 ze 110 odrzuceń „Brak umiejętności” pisali jedną pozycję, która przesądza
(„angular”, „produkty inwestycyjne”), ale w wolnym tekście, więc system nie mógł
się z niej uczyć. 19 z 20 opisów „Język” to było samo słowo „Język”, a 3 „Inne”
to forma umowy.

## Reguły

- **„Brak umiejętności” = kliknięcie przy pozycji.** Pod powodem stoi do 8 pozycji
  wymagań osoby (`gapRows`: najpierw te, których system nie znalazł, potem
  znalezione, bez powtórzeń) i przy każdej „brak”, „tylko wzmianka”, „za mało lat”.
  Pole tekstowe jest na coś spoza listy i jest opcjonalne, gdy kliknięto choć jedną
  pozycję (`rejectMissing`). Opis do historii procesu składa `gapsNote`
  („Brak: bigquery (tylko wzmianka), sql”).
- **Braki idą do serwera jako `autofill_gaps`** i lądują w `autofill_feedback.gaps`
  (`[{label, kind}]`, `clean_gaps`: znane rodzaje, bez pustych i powtórzeń, najwyżej
  10). Braki przy innym powodzie niż „Brak umiejętności” = 422. Z tej kolumny
  korzysta reguła rekrutacji (R1).
- **Nowe powody** (`REASONS`, więz w `REASON_CHECK_DDL`, migracja 0686 i
  `GAPS_DDL` w entrypoincie): „Brak polskiego” (`no_polish`) i „Angielski za
  słaby” (`weak_english`) w koszu „Błąd wyszukiwania”, „Forma umowy (UoP / B2B)”
  (`contract_form`) w „Sprawa osoby”. Szablon procesu nie ma odpowiedników, więc
  idą jako „Inne” z nazwą powodu w opisie, jak dawny „Język”.
- **„Język” zostaje w bazie i w typie** dla starych wpisów, ale nie ma go już na
  liście wyboru ani w porcji, ani w oknie odrzucenia na Tablicy.
- **Klawisze w porcji:** 1 brak umiejętności, 2 za junior, 3 lokalizacja / tryb,
  4 za drogi, 5 brak polskiego, 6 angielski za słaby, 7 inna rola, 8 nie szuka,
  9 forma umowy, 0 inne.

Testy: `backend/tests/test_autofill_feedback.py` (sekcja „Runda 4”),
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchCard.test.tsx`,
`RejectionV2.autofill.test.tsx`.
