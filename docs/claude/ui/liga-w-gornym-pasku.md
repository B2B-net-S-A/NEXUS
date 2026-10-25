# Liga Mistrzów w górnym pasku (13.10.2026)
<!-- indeks: przycisk ligi przed licznikiem celów, `/api/competitions/my-league`, stany przycisku, menu „Wygląd” -->

Artur 13.10.2026: „na górze na tych statach pokazuj też punkty, jakie się liczą
do Ligi Mistrzów, żeby każdy widział, ile ma punktów i na jakim miejscu jest”.
Wybrany wariant A z makiet (https://claude.ai/artifact/TYZEqnmPUY4qazVLpbhuwc)
i rekomendacje D1–D6. Raport: `docs/league-topbar-completion-report.md`.

- **Co widać:** przycisk przed licznikiem celów (`components/v2/league/`).
  Kółko z numerem miejsca (złote, srebrne, brązowe dla 1–3, tokeny
  `medal-*` w `globals.css`), nad wynikiem liga i stan, pod spodem sam wynik:
  „Liga · Q4” / „385 pkt”. Poniżej 1024 px samo kółko. Bez emoji.
- **Jedna forma na każdą szerokość.** Zmierzone na `/preview/kpi-topbar`
  13.10.2026: dopiski w dolnej linii („· bez miejsca”, punkty lidera) zabierały
  okruszkom do 105 px przy 1280 px, a forma pełna od 1536 px (222–238 px)
  spychała cele do jednego segmentu. Stan idzie do górnej linii
  („Liga · bez miejsca”, „Liga DL · bez miejsca”, „Liga · remis”), dystans —
  do panelu i nazwy dla czytnika ekranu. Nowy dopisek w przycisku = najpierw
  pomiar na harnessie.
- **Kto widzi którą ligę — z ról, nie z zakresu pulpitu**
  (`services/league_standing.league_kind`): rola Delivery Leada (główna albo
  dodatkowa) → liga DL; rola rekrutera → liga rekruterów; reszta (HoR i TCM
  bez tych ról, admin, Finanse, rola podglądu) widzi prowadzącego ligę
  rekruterów. Zakres pulpitu stawia HoR/TCM przed DL, więc HoR z rolą DL
  wychodziłby „widzem”, choć gra w lidze DL. Osoba z rolą rekrutera i DL
  widzi ligę DL — jedna liga na osobę — ale tylko wtedy, gdy ma w kwartale
  portfel DL (zamkniętą rekrutację albo placement w `dl_portfolio_counts`).
  Bez niego `my_league` pokazuje jej Ligę rekruterów (15.10.2026: trzy osoby
  z obiema rolami grały wyłącznie w lidze rekruterów, jedna była na 2. miejscu,
  a pasek mówił im „Liga DL · poza ligą”).
- **Liczby z jednego źródła:** `GET /api/competitions/my-league` czyta ten sam
  ranking co podium na „Rywalizacji” (`_cached_current` → `award_order` →
  `award_ranked_rows`), więc pasek, Insights i zamrożenie kwartału mają jedną
  numerację. Trasa stoi za bramką Insights (trainee jej nie ma — front nie
  pyta bez `hasSectionAccess(user, "insights")`).
- **Cache paska 5 minut.** Jedno przeliczenie Ligi to ok. 3 s Postgresa, a pasek
  wisi na każdej stronie. Ranking dla paska ma własny klucz
  `competitions:topbar:{typ}` (TTL 300 s, nakładany na 60-sekundowy `/current`),
  liczby DL — jeden wpis dla całej firmy `competitions:dl-counts:{okres}`.
  Zamrożenie i remis czyszczą je razem z prefiksem `competitions:`. Front pyta
  co 5 minut, bez odświeżania przy powrocie do karty.
- **Okres w kluczu = okres w wartości (14.10.2026).** Klucz paska to
  `competitions:topbar:{typ}:{kwartał}`, a wartość brała wpis `/current` bez
  okresu, który żyje 60 s — audyt 13.10 pokazał, że tuż po starcie kwartału
  pod kluczem nowego kwartału zostawał na 5 minut ranking starego. `my_league`
  bierze teraz wpis `/current` tylko wtedy, gdy ma okres z klucza; inaczej
  liczy ranking dla tego kwartału. Test zamrożenia woła trasy `freeze`
  i `resolve-tie`, nie samo czyszczenie cache (`test_competitions_my_league.py`).
- **Dystans liczy się z całej listy** (`league_standing`): miejsce 1 — przewaga
  nad 2.; miejsca 2–3 — do miejsca wyżej; od 4. i bez miejsca — do wyniku
  3. miejsca, nigdy ujemny. `/my-position` oddaje tylko ±2 sąsiadów i od
  6. miejsca podium nie widzi — nie licz dystansu z niego.
- **Stany i ich teksty liczy `buildLeagueTopbarModel`** (czysta funkcja z testami):
  - bez miejsca (próg placementów niespełniony, `rank: null`) — punkty widać,
    numeru nie, panel podaje próg i pozycję po samych punktach;
  - 0 pkt (`me: null`) — „0 pkt” i skąd biorą się punkty; awaria zapytania —
    „—” z „Ponów”, nigdy „0 pkt”;
  - remis o płatne miejsce (`tied`) — „Liga · remis”, w panelu, że rozstrzygnie
    admin;
  - Delivery Lead (od 25.10.2026 liga po hit ratio, bez nagród —
    sekcja „Liga DL po hit ratio” niżej): wynikiem jest hit
    ratio („36,4%”), dystanse w punktach procentowych; bez miejsca (mniej niż
    3 placementy albo 5 zamkniętych rekrutacji) — „Liga DL · bez miejsca”,
    panel mówi, czego brakuje; bez portfela — „Jeszcze bez wyniku”; bez
    zamkniętych rekrutacji hit ratio jest niepoliczone („—”), nie zerowe.
    Stanów „poza ligą” i „poza 10.” już nie ma.
- **Dystans przeliczony na pracę** (`workToClose`): najwyżej dwie drogi z wag
  ligi, „To 1 placement albo 6 rozmów u klienta.” Rozmów powyżej 20 nie podajemy.
- **Awans, nie spadek** (D5): strzałka „↑ z 6.” do końca dnia, liczona od
  pierwszego widoku dnia w tej przeglądarce (`league-rank-memory`, localStorage
  w try/catch). Bez dzwonka i bez komunikatów o spadku.
- **„Wygląd” zamiast trzech przełączników** (D2): motyw koloru, styl interfejsu,
  tryb gry i tryb ciemny w jednym menu (`shell/AppearanceMenu.tsx`). Pozycje
  palety są wspólne z `PaletteSwitcher` (`PaletteMenuItems`), tryb gry z jednym
  powitaniem (`useKidsModeToggle`). Na telefonie przełączniki zostają osobno
  w szufladzie nawigacji (`SidebarV2`).
- **Ile to kosztuje paska** (harness, replika z pigułką „Do wysłania” i menu
  przypiętym, porównanie z układem sprzed zmiany): przy 1280 px rekruter
  zachowuje segmenty celów, okruszki na ekranie rekrutacji 177 → 128 px;
  Head of Recruitment i Delivery Lead na pulpicie 2 → 1 segment; przy 1536 px
  liczba segmentów bez zmian. Przycisk: 117 px rekruter, 147 px lider u widza,
  178 px DL bez miejsca (25.10.2026, było 163 px „poza ligą”; wyszukiwarka dalej 220 px przy 1280, 1366 i 1536 px). W najgorszym zestawie (HoR z rolą DL, „Do wysłania”,
  pigułka po rozmowie, długie okruszki, 1280 px) okruszki zostają skrótem
  10 px (było 105) — ustępują ostatnie, jak przed zmianą. Pilnuje tego e2e
  „górny pasek — licznik celów” (najciaśniejszy pasek ma najszerszy przycisk).
- Harness: `/preview/kpi-topbar` (paski, sekcja „Liga Mistrzów — stany
  przycisku”, panele), dane fikcyjne w `league/league-fixtures.ts`.

## Liga DL po hit ratio, bez nagród (od Q4 2026)

Decyzja Artura z 25.10.2026, po makietach trzech wariantów (punkty, hit ratio,
dwa puchary): liga DL szereguje po hit ratio, liczy się już od Q4 2026
i „dla Delivery Leadów nie robimy żadnych nagród — sama statystyka”.

Powód zmiany (staging, kopia produkcji z 22.10.2026): w Q4 nikt z siedmiu DL-i
nie spełniał starego progu (hit ratio ≥ 30% i 3 placementy), więc karta była
pusta, a pasek każdemu mówił „poza ligą”. W Q1–Q3 na podium stała ta sama
trójka, bo ranking po samych placementach wygrywa wielkość portfela.

- **Ranking:** hit ratio = placementy w portfelu ÷ rekrutacje zamknięte
  w kwartale (`dl_portfolio_counts`, przegrana tylko z konkurencją, zamknięcia
  „nie liczy się” poza mianownikiem). Przy równym procencie wyżej więcej
  placementów (`dl_hit_ratio_key`). `metric_value` to dalej placementy —
  zamrożenie trzyma je w kolumnie całkowitej; procent jest w `hit_ratio`.
- **Miejsce w klasyfikacji** od 3 placementów i 5 zamkniętych rekrutacji
  (`DL_LEAGUE_MIN_PLACEMENTS`, `DL_LEAGUE_MIN_CLOSED_REQUESTS`). Próg
  zamkniętych chroni przed „2 z 2 = 100%”. Kto go nie spełnia, zostaje na
  liście bez numeru, z powodami (`MIN_PLACEMENTS_NOT_MET`,
  `MIN_CLOSED_REQUESTS_NOT_MET`) — jak w Lidze rekruterów. Lista nie jest
  ucinana do dziesięciu; jest na niej każdy DL z portfelem w kwartale.
- **Bez nagród od Q4 2026:** `dl_league_pays(period)` jest prawdziwe tylko dla
  kwartałów do Q3 2026. Od Q4 `paid_slots` = 0 (remis nie czeka na admina),
  `_prize_for` = 0, `/current` oddaje `prize_pool_pln` i `quarterly_prizes_pln`
  = `null`, `/my-league` — `prizes_pln: {}`. Zamrożenie zapisuje podium
  z kwotą 0, a płace biorą tylko wiersze z `prize_pln > 0`, więc premii nie ma.
- **Kwartały do Q3 2026 zostają, jak je rozliczono** (z wpisów DL
  DynaReportera, placementy, 5000 / 3000 / 2000 zł). Kwoty i remisy liczą się
  po okresie (`period` w `paid_slots`, `_prize_for`, `AwardOrder.period`),
  więc rozstrzygnięcie dawnego remisu dalej wypłaca dawną kwotę. Front
  przełącza kartę po okresie (`dlLeagueByHitRatio`): wcześniejszy kwartał
  pokazuje placementy i kwoty.
- **Cel DL 30% hit ratio zostaje** (`kpi_goals`, licznik celów). To cel, nie
  próg ligi; `/my-league` oddaje go jako `hit_ratio_target` do odniesienia.
- **Pasek:** wynik DL to hit ratio („36,4%”), dystanse w punktach
  procentowych (`league_standing(value_key="hit_ratio")`), stany „Liga DL · Q4”,
  „Liga DL · bez miejsca” i „Jeszcze bez wyniku”. Warunek miejsca w panelu
  mówi, ile brakuje placementów i zamkniętych rekrutacji (stany wyżej).
- Testy: `backend/tests/test_dl_league_hit_ratio.py`,
  `test_competitions_my_league.py`, `test_league_standing.py`; front
  `insights-champions.test.tsx`, `league-topbar-model.test.ts`.
