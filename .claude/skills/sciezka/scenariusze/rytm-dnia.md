# Scenariusz: Insights → Aktywność („Rytm dnia”)

Reguła: `docs/claude/finanse-insights/rytm-dnia-intensywnosc-rekruterow.md`.

Kto → co robi → co widzi następny:

1. **Head of Recruitment** otwiera `/insights?tab=rytm&widok=dzien`. Widzi
   wiersz każdej osoby z rolą rekrutera i każdego Delivery Leada (także bez
   roli rekrutera), bez siebie i adminów; osoby na urlopie na dole
   z dopiskiem „Urlop”. Klik w osobę otwiera rozkład dnia.
2. **Head of Recruitment** przełącza Wzorce, Trend, 2 tygodnie — te same
   osoby w każdym widoku.
3. **Delivery Lead** (rola, która ma nie widzieć) otwiera ten sam adres:
   zakładki „Aktywność” nie ma, strona przechodzi na Rywalizację,
   a `GET /api/insights/work-rhythm` jego tokenem zwraca 403.

Porównanie listy osób: ten sam `GET /api/insights/work-rhythm` tokenem HoR na
wspólnym stagingu (8100, kod z maina) i na backendzie gałęzi.
