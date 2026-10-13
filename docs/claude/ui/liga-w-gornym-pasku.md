# Liga Mistrzów w górnym pasku (13.10.2026)
<!-- indeks: przycisk ligi przed licznikiem celów (miejsce i punkty rekrutera, placementy DL, lider u osób, które nie grają), `/api/competitions/my-league` z cache paska 5 min, jedna forma przycisku, stany (bez miejsca, poza ligą, remis, awans), menu „Wygląd” zamiast trzech przełączników -->

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
  („Liga · bez miejsca”, „Liga DL · poza ligą”, „Liga · remis”), dystans —
  do panelu i nazwy dla czytnika ekranu. Nowy dopisek w przycisku = najpierw
  pomiar na harnessie.
- **Kto widzi którą ligę — z ról, nie z zakresu pulpitu**
  (`services/league_standing.league_kind`): rola Delivery Leada (główna albo
  dodatkowa) → liga DL; rola rekrutera → liga rekruterów; reszta (HoR i TCM
  bez tych ról, admin, Finanse, rola podglądu) widzi prowadzącego ligę
  rekruterów. Zakres pulpitu stawia HoR/TCM przed DL, więc HoR z rolą DL
  wychodziłby „widzem”, choć gra w lidze DL. Osoba z rolą rekrutera i DL
  widzi ligę DL — jedna liga na osobę.
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
  - DL poza ligą — próg (≥3 placementy i hit ratio ≥30%) i ile brakuje; DL
    spełniający próg, ale spoza listy 10 (`_rank_dls_by_placements` tnie do
    dziesięciu) — „poza 10.”, nie „poza ligą”; bez zamkniętych rekrutacji hit
    ratio jest niepoliczone, nie zerowe.
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
  163 px DL poza ligą. W najgorszym zestawie (HoR z rolą DL, „Do wysłania”,
  pigułka po rozmowie, długie okruszki, 1280 px) okruszki zostają skrótem
  10 px (było 105) — ustępują ostatnie, jak przed zmianą. Pilnuje tego e2e
  „górny pasek — licznik celów” (najciaśniejszy pasek ma najszerszy przycisk).
- Harness: `/preview/kpi-topbar` (paski, sekcja „Liga Mistrzów — stany
  przycisku”, panele), dane fikcyjne w `league/league-fixtures.ts`.
