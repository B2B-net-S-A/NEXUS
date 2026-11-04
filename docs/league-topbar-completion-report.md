# Liga Mistrzów w górnym pasku (13.10.2026)

Prośba Artura: „na górze na tych statach pokazuj też punkty, jakie się liczą do
Ligi Mistrzów oprócz KPI, żeby każdy widział, ile ma punktów i na jakim miejscu
jest”. Makiety (warianty A, B, C, panel, stany, role, decyzje D1–D6):
https://claude.ai/artifact/TYZEqnmPUY4qazVLpbhuwc. Artur: „zaplanuj zgodnie
z Twoimi rekomendacjami” — wariant A i D1–D6 zgodnie z rekomendacją. Reguły dla
kolejnych zmian: `docs/claude/ui/liga-w-gornym-pasku.md`.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Pasek | Przycisk ligi przed licznikiem celów: kółko z numerem miejsca (złote, srebrne, brązowe dla 1–3), nad wynikiem liga i stan, pod spodem wynik („Liga · Q4” / „385 pkt”). Poniżej 1024 px samo kółko. Nie ściska się. |
| Kto co widzi | Rekruter — miejsce i punkty ligi rekruterów. Delivery Lead — miejsce i placementy ligi DL (bez punktów, regulamin bez zmian). HoR i TCM bez roli rekrutera lub DL, admin, Finanse, rola podglądu — prowadzący ligę rekruterów. Rodzaj ligi z ról, nie z zakresu pulpitu. |
| Panel | Po kliknięciu: dni do końca kwartału, miejsce i wynik, dystans (do miejsca wyżej, do podium albo przewaga) przeliczony na pracę („To 1 placement albo 6 rozmów u klienta.”), rozbicie punktów, warunek udziału z progiem 1 / 2 / 3, sąsiedzi ±2 z wierszem „Ty”, link „Cała liga” do Rywalizacji. DL: hit ratio i droga do progu. Widz: pierwsza piątka. |
| Stany | Bez miejsca (punkty są, warunek nie), 0 pkt, awaria („—” i „Ponów”, nigdy „0 pkt”), remis o płatne miejsce, DL poza ligą, DL w lidze poza listą 10, DL bez zamkniętych rekrutacji, awans dnia („↑ z 6.” do północy; spadek bez strzałki). |
| „Wygląd” | Motyw koloru, styl interfejsu, tryb gry i tryb ciemny w jednym menu zamiast trzech przycisków (112 → 36 px). Na telefonie przełączniki zostają w szufladzie nawigacji. |
| API | Nowa trasa `GET /api/competitions/my-league` (bramka Insights, golden uprawnień jak `/my-position`). Ranking z tej samej ścieżki co podium na „Rywalizacji”; cache paska 5 min (`competitions:topbar:*`), liczby DL jednym wpisem dla firmy. |
| Tokeny | `medal-gold`, `medal-silver`, `medal-bronze` (+ `-foreground`) w jasnym i ciemnym motywie. |
| Harness | `/preview/kpi-topbar`: przycisk ligi i „Wygląd” w replikach paska, sekcja stanów ligi, cztery panele. |

## Pomiar zmienił projekt

Plan przewidywał formę zwartą z dopiskami w dolnej linii i formę pełną od
1536 px. Pomiar na harnessie (Playwright, 1280 / 1366 / 1536 px, replika
z przypiętym menu i pigułką „Do wysłania”) pokazał dwie rzeczy:

- Dopiski w dolnej linii („· bez miejsca”, „· poza ligą”, punkty lidera)
  robiły z przycisku 187–222 px; w najciaśniejszym pasku przy 1280 px okruszki
  spadały do 0 px.
- Forma pełna od 1536 px (222–238 px) spychała cele do jednego segmentu tam,
  gdzie mieściły się trzy.

Dlatego przycisk ma jedną formę: stan w górnej linii, w dolnej sam wynik.
Dystans jest w panelu i w nazwie dla czytnika ekranu. Druga różnica wobec
makiety: przełączniki wyglądu mają po 32 px, więc „Wygląd” zwalnia 76 px, nie 88.

| Okno | Pasek (replika) | Segmenty celów przed → po | Okruszki przed → po |
|---|---|---|---|
| 1280 | Rekruter, ekran rekrutacji | 1 → 1 | 177 → 128 px |
| 1280 | HoR, pulpit | 2 → 1 | 38 → 38 px |
| 1280 | HoR z rolą DL, najciaśniej (długie okruszki, „Rozmowy”, przycisk DL poza ligą) | 1 → 1 | 105 → 10 px |
| 1366 | to samo | 1 → 1 | 191 → 96 px |
| 1280 | Delivery Lead, pulpit | 2 → 1 | 38 → 38 px |
| 1366 | Delivery Lead, pulpit | 3 → 2 | 38 → 38 px |
| 1536 | wszystkie cztery | bez zmian | — |

„Przed” to ten sam harness z ukrytym przyciskiem ligi i „Wyglądem” rozciągniętym
do 112 px (szerokość trzech przełączników). Szerokość przycisku: 117 px
rekruter, 147 px lider u widza, 163 px DL poza ligą. Pasek bez przelewu
i wyszukiwarka ≥ 220 px we wszystkich przypadkach. Najciaśniejszy pasek to
celowo najgorszy zestaw naraz (HoR z rolą DL, kolejka „Do wysłania”, pigułka
po rozmowie, długa nazwa rekrutacji, 1280 px): okruszki zostają tam
skrótem — ustępują ostatnie, jak przed zmianą.

## Weryfikacja

- Backend lokalnie (Python 3.12, bez bazy): `test_league_standing.py` (11),
  `test_competitions_my_league.py` (12), `test_audit_r4_competitions.py`,
  `test_competition_rankings_cache.py`, `test_authz_guard_matrix.py` (golden
  wygenerowany), `test_candidate_pipeline_section_contract.py` — zielone poza
  jednym testem wymagającym Postgresa (sprawdza CI). `ruff check` i `ruff format`.
- Front lokalnie: vitest `league-topbar-model`, `league-rank-memory`,
  `MyLeagueWidget`, `AppearanceMenu`, `MyKpiWidget`, `recruitment-feature-parity`;
  `tsc --noEmit` czysty.
- E2E „górny pasek — licznik celów” na lokalnym harnessie: zielone (dodatkowo
  przycisk ligi w każdym pasku, nieprzycięty, „Wygląd” 36 px).
- Zrzuty harnessu: paski przy 1280 / 1366 / 1536, panel rekrutera, menu
  „Wygląd”, stany w jasnym, ciemnym i trybie gry.

## Poza zakresem

- „Mój miesiąc” pokazuje dystans do podium tylko dla miejsc 4–5 (czyta sąsiadów
  ±2 z `/my-position`). Mógłby czytać `gap_to_podium` z `league_standing`.
- Wyścigi miesiąca w panelu ligi.
- Stare etykiety ról: `User.has_role` liczy `tac`/`sourcer` jako rekrutera,
  a SQL ligi (`roles ? 'recruiter'`) nie — taka osoba zobaczyłaby „0 pkt”.
  Istniejący rozjazd ligi.
- Head of Recruitment i Delivery Lead tracą przy 1280 px drugi segment celów na
  pulpicie. Odzyskać go można tylko kosztem okruszków albo wyszukiwarki.
- W najgorszym zestawie (HoR z rolą DL, „Do wysłania”, pigułka po rozmowie,
  długa nazwa rekrutacji, 1280 px) okruszki zostają skrótem 10 px (było 105).
  Gdyby to przeszkadzało: przycisk ligi mógłby chować podpis do samego kółka
  tym samym mechanizmem co segmenty celów — wymaga ustalenia, co ustępuje
  pierwsze, okruszki czy punkty.
