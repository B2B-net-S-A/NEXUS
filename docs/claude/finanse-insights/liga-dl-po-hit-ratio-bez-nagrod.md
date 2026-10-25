# Liga Mistrzów DL po hit ratio, bez nagród (od Q4 2026)
<!-- indeks: ranking po hit ratio, miejsce od 3 placementów i 5 zamkniętych rekrutacji, bez kwot od Q4 2026, `dl_league_pays`, Q1–Q3 2026 zostają z nagrodami -->

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
  mówi, ile brakuje placementów i zamkniętych rekrutacji.
  → `ui/liga-w-gornym-pasku.md`
- Testy: `backend/tests/test_dl_league_hit_ratio.py`,
  `test_competitions_my_league.py`, `test_league_standing.py`; front
  `insights-champions.test.tsx`, `league-topbar-model.test.ts`.
