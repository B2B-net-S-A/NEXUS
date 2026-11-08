# Lata z technologią w wyszukiwaniu („Java · co najmniej 3 lata”, 08.11.2026)
<!-- indeks: `skill_years=Java:3`, `hide_unknown_skill_years`, `candidate_skill_usage.months`, `unknown_fields: skill_years`, pigułka „Lata”, kreska „Bez dat przy technologii w CV” -->

Etap 3b słownika umiejętności. Makiety i liczby: https://claude.ai/artifact/CmAoKVLNtc9GAU8w8Yh5Yn.
Decyzje Artura z 08.11.2026: wariant B (osobna pigułka „Lata z technologią”
obok „Umiejętności”) i lata wyłącznie z dat stanowisk, bez szacunku parsera.

## Skąd są lata

- **Jedyne źródło to oś technologii z odczytu CV**: `cv_extracted_data.skill_timeline`
  → tabela `candidate_skill_usage`, kolumna `months` = suma miesięcy stanowisk
  i projektów, przy których CV wymienia technologię, bez podwójnego liczenia
  nakładek (`profile_projection.build_skill_timeline`). Oś wypełnił masowy
  ponowny odczyt CV (v9, Haiku + Batch, skończony 08.11.2026 00:03 UTC).
- **Fakty z Traffita (`cortex_skill_facts`) nie są źródłem**: wszystkie
  332 150 wierszy mają `years`, `level`, `evidence` i `observed_at` puste
  (staging z 06.11.2026).
- **Szacunek parsera (`candidates.skills[].years`) nie jest źródłem ani
  zapasem**: na próbie 30 osób (94 pary) w 19% par różnił się od dat stanowisk
  o ponad 2 lata, a w 15 z 18 takich par zawyżał. Nie dokładaj go „dla
  pokrycia” bez nowego pomiaru i decyzji Artura.
- **Pokrycie w dniu zmiany** (staging z 07.11.2026 22:45, osoby z technologią
  w profilu, które mają lata z osi): Java 70%, React 66%, Python 53%, SQL 46%.
  „Java ≥ 3 lata”: 6 555 z latami + 4 813 bez dat; „Python ≥ 3”: 6 200 + 10 262.

## Reguła (oba silniki, `candidate_search_predicates`)

- **Na drucie**: lista `skill_years=Java:3` (powtarzany, do 5, lata 1–30)
  i `hide_unknown_skill_years`; wyszukiwarka te same pola w ciele. Zły wiersz =
  422 po polsku (`InvalidSkillYears`). Ta sama technologia dwa razy = wyższy próg.
- **Trzy losy osoby** przy wierszu „X · co najmniej N lat”
  (`skill_years_clauses`):
  1. oś podaje przy X co najmniej N × 12 miesięcy → spełnia, także gdy X nie
     ma w umiejętnościach profilu (CV podaje je przy stanowisku);
  2. oś podaje mniej → odpada (wiemy, że za mało);
  3. X jest w profilu (to samo dopasowanie co „Musi mieć”, `skill_match`), ale
     oś nie ma przy X żadnego okresu z długością → **„bez danych o latach”**:
     zostaje, `unknown_fields: ["skill_years"]`, na liście na końcu (ranga
     braków), chyba że `hide_unknown_skill_years` albo globalne `hide_unknown`.
  Wiersze łączy I. Filtr jest nowy, więc nie ma wariantu v1: ta sama reguła
  w obu wersjach semantyki (`Semantics.skill_years_unknown`).
- **Aliasy**: klucz osi to `canonical_of(nazwa)` z chwili odczytu, więc
  szukamy całej rodziny `skill_name_variants` (MSSQL / SQL Server). Kilka
  wierszy osi w jednej rodzinie → najdłuższy, nigdy suma (te same stanowiska
  stoją pod każdą pisownią).
- **Wiersz odpowiedzi** ma `skill_years: [{skill, years_min, months, source}]`
  (`source` = `cv_roles` albo `manual`), liczone jednym zapytaniem dla strony
  (`skill_years_for_page`). Lista liczy `known_match_count` jak przy stawce.
- **Wyszukiwarka**: grupa `skill_years` w `NULL_POLICY` = `include`.

## Ekran (lista i „Szukaj ręcznie”)

- Pigułka „Lata z technologią” (poniżej 1536 px „Lata”) z samym licznikiem,
  jak „Odrzucenie”: pełny opis przy 1280 spychał „Więcej filtrów” do drugiego
  rzędu. Opis „Java ≥ 3 lata” niesie chip pod paskiem. Przy aktywnym filtrze
  i 1280 px do drugiego rzędu spada sam link „Wyczyść” (zrzut 08.11.2026).
- Okienko: wiersze „technologia · co najmniej N lat”, „+ technologia”, wybór
  „Osoby z technologią, ale bez dat w CV: pokaż na końcu listy / ukryj”
  (`HideUnknownChoice`, jak Stawka). Adres `sky=Java:3|Kafka:2`, `husy=1`.
- W wierszu: „Java 6 lat 8 mies.” (`SkillYearsBadges`), brak dat = plakietka
  „bez dat w CV”; kreska „Bez dat przy technologii w CV”, jej „Ukryj” włącza
  `hideUnknownSkillYears`.

## Wydajność — znany koszt

Gałąź „bez danych o latach” używa `skill_match`, czyli tego samego co „Musi
mieć”: na stagingu „Musi mieć: Java” trwa ok. 10,5 s, „Java ≥ 3 lata” ok. 11 s,
a „Java ≥ 3 lata” z ukrytymi brakami 0,5 s. Koszt to rodzina aliasów
rozwijana na osobne `strpos` po całym zrzucie profilu (Java: 10 pisowni = 20
przejść). Poprawka należy do `skill_match` (oba silniki naraz), nie do tego filtru.

## Testy

`tests/test_skill_years_filter.py` (parser, losy osoby, L = S na własnej
populacji: próg, alias i dwa wiersze osi, technologia tylko na osi, ukrycie,
`known_match_count`, kolejność, 422), `test_candidate_search_predicates.py`
(żaden silnik nie ma prywatnej kopii `CandidateSkillUsage`),
`frontend/src/lib/__tests__/candidate-skill-years.test.ts`,
`components/v2/candidates/__tests__/SkillYearsFilter.test.tsx`.
