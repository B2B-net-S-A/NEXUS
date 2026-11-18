# Porcja dnia: szczegół powodu, kwota przy „Za drogi” i porządki osobno
<!-- indeks: `autofill_feedback.detail`, `clean_detail`, `role_kind` (profession / level / specialty), `role_wanted`, `availability` (not_looking / notice / from_date), powód `cleanup` (duplicate / stale_process / cv_broken), `OTHER_NOTE_MIN_LETTERS`, `otherNoteHasWords`, `autofill_detail`, „Ile chce?” w porcji, migracja 0717 -->

Decyzja Artura z 16.11.2026 („wszystko” z propozycji A–D). Raport z feedbacku
porcji po R1–R6 i makiety na stagingu:
https://claude.ai/artifact/2TiEpPVCj6k42o2xkegDKv. Na 13.11 (238 odrzuceń)
„Brak umiejętności” spadł z 34% do 24%, bo system uczy się z klikniętych braków,
a urosły trzy powody, z których nie wyciągał nic: „Inna rola” (21%, 49 odrzuceń,
żadne z opisem), „Inne” (19%) i „Za drogi” (11%, żadne z kwotą).

## Reguły

- **„Inna rola” (klawisz 7) pyta, co nie pasuje:** „Inny zawód”, „Za wysoki
  poziom / za senior”, „Inna specjalizacja w tym zawodzie” i opcjonalnie „Kogo
  szukamy zamiast?”, obok roli osoby z profilu. Kliknięcie jest opcjonalne, żeby
  powód dalej szedł jednym klawiszem. Zapis: `autofill_feedback.detail`
  (`role_kind`, `role_wanted`), do historii procesu idzie to samo słowami.
  Od 16.11.2026 wieczorem 8 odpowiedzi z klawiszami 1–8, „Osoba to:” i lista
  „Nie proponujemy”: `porcja-kogo-szukamy.md` (ta sekcja w tym punkcie jest starsza).
- **„Za drogi” (4) ma pole „Ile chce?”** (opcjonalne). Kwota idzie jako
  `autofill_rate_hourly`, a serwer zapisuje ją w „Stawce od” tą samą drogą co
  okno odrzucenia na Tablicy. Do 16.11 porcja wysyłała `rateHourly: null`.
- **„Nie szuka / niedostępny” (8):** „Nie szuka” (jak dotąd, 3 miesiące),
  „Okres wypowiedzenia” (1–3 mies.) albo „Dostępny od” z datą. Każdy wariant
  ustawia „Nie szuka do” (`autofill_not_looking_until`), a silnik pomija osobę
  do tej daty. Wariant w `detail.availability`.
- **„Inne” (0):** opis musi mieć choć 3 litery (serwer i front, 11 z 45 „Inne”
  13.11 to była sama kropka). Pod powodem „Nie ocena osoby”: Duplikat,
  Nieaktualny proces / porządki, CV się nie otwiera. Wybrany = powód `cleanup`
  z `detail.cleanup`, bez wymaganego opisu, w historii „Porządki (nie ocena
  osoby). Duplikat”.
- **`cleanup` nie liczy się w raporcie jakości** (`autofill_quality._ASSESSMENT`:
  najgorsze rekrutacje, kosze, opisy do modelu). Reguła R1 i tak czyta tylko
  braki przy „Brak umiejętności”.
- **`detail` sprawdza serwer** (`clean_detail`): klucze tylko przy swoim powodzie,
  wartości z listy, inaczej 422. Okno odrzucenia na Tablicy nie ma „Porządków”
  (na liście wyboru go nie ma, etykieta jest dla historii).

## Czego świadomie nie zrobiono (pomiar 16.11.2026)

- **Reguły „nie proponuj tej rodziny ról” z odrzuceń.** 73 z 95 odrzuceń
  „Inna rola” od 09.11 było w rekrutacjach, których tytułu `role_family` nie
  rozpoznaje (np. „Senior IT Analyst” 25× w jeden dzień). Reguła jak R1 (≥ 3
  odrzucenia osób z tej samej rodziny) wycięłaby 36 z 64 osób, które w tych
  rekrutacjach dostały „Pasuje”, w tym 3, które doszły do CV albo rozmowy.
  Ta sama rodzina bywa dobra i zła; decyduje poziom albo specjalizacja, stąd
  dopytanie. Decyzja o regule po dwóch tygodniach danych z `role_kind`.
- **Nowych wzorców tytułów w `role_family`** („Programme Management Office”,
  „Project lead”, „Analityczka”, CI/CD). Na danych 09–13.11 oznaczyłyby 3
  odrzucenia „Inna rola” i 5 osób z „Pasuje” (3 w jednej rekrutacji).
- **Progu 65%.** Karty 65–69% to 49% decyzji, z nich 46% dostaje „Pasuje”
  (70–74%: 54%, 75–79%: 66%); próg 70% zabrałby ok. 190 przyjęć z czterech dni.

Testy: `backend/tests/test_autofill_feedback.py` (sekcja „Runda 5”),
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchCard.test.tsx`
(„szczegół powodu (runda 5)”).
