# Zakładka Zespół: odpowiedź, soczewka etapu, mapa osób
<!-- indeks: v4 z 05.11.2026, zdanie z odpowiedzią, tempo wobec celu, sześć zakładek etapu, wykresy tygodnie i miesiące, `/recruitment/monthly-trend`, przejścia nie są kohortą, trwający okres poza linią, grupy osób, cele placementów junior 1 senior 2 ekspert 3 przez wpisy osobowe -->

Decyzje Artura z 05.11.2026 (makiety: https://claude.ai/artifact/TU8LBhs8A9UpFSHQBUyWHJ).
Poprzednia wersja miała 3718 px, ponad 5 ekranów przy 1280 × 720, a Artur nie
mógł z niej nic wyczytać. Teraz zakładka odpowiada na trzy pytania po kolei:
czy dowieziemy, gdzie się zatyka, kto.

- **Góra:** zdanie z odpowiedzią zamiast pytania (`teamVerdict`), tempo wobec
  celu z kreską planu na dziś (`tempoRows`) i trzy sprawy z „Najpierw to”
  (`rankedSignals`: im bliżej placementu, tym wyżej). Klik w zdanie o zatorze
  otwiera ten etap. Logika i testy: `lib/insights-team-view.ts`.
- **Soczewka (`TeamStageLens`):** zakładki „Cały lejek” i pięć etapów, wybór
  w `?etap=`. Start na „Całym lejku”: wszystkie wykresy, przełącznik tygodnie
  i miesiące w `?os=miesiac`. Etap pokazuje swoją linię, przejście z poprzedniego
  etapu, osoby i swoje sygnały.
- **Wykresy (`TeamTrendCharts`):** liczby i procenty na osobnych osiach, nigdy
  dwie skale na jednym wykresie. Tygodnie z `/recruitment/weekly-trend`, miesiące
  z `/recruitment/monthly-trend`. Linia przerywana to 12.10.2026, start pracy
  w NEXUSIE.
- **Przejście to nie kohorta.** Liczba etapu dzielona przez liczbę poprzedniego
  w tym samym okresie, bez sufitu 100%. Śledzenie tych samych par da się zrobić
  dopiero od 12.10.2026, bo wpisy DynaReportera nie mają kandydatów. Przejścia
  z akceptacjami liczą się tylko na odcinku od 12.10.2026 (`cutover_counts`).
- **Trwający okres nie idzie na linię.** Cztery dni na końcu linii wyglądają jak
  załamanie. Jest w tabeli „Liczby tydzień po tygodniu”.
- **Porównanie z okresem sprzed 12.10.2026 ukryte, gdy okres trwa**
  (`isFairComparison`). „1–5 października” to tygodniowe wpisy DynaReportera
  z datą raportu, 211 weryfikacji z ponad tygodnia. Od grudnia wraca samo.
- **Bez wniosku „najwięcej odpada między…” z małej próby.** Ramka z 1 z 12 w cztery
  dni alarmowała na początku każdego miesiąca. Procent przy etapie dopiero
  od 30 w mianowniku.
- **Mapa osób:** jedna linia na osobę, ciemniejsza komórka to więcej w kolumnie
  (bez osób bez celu w skali). Grupy z `personGroup` mówią, jak daleko osoba
  doszła w okresie, nie jak ją oceniamy. Osoby z celem 0 są zwinięte z sumami.
  Klik w nagłówek sortuje całą listę bez grup.
- **Licznik firmy i osób z celem to dwie liczby.** Cel sumuje aktywne osoby
  z celem, a lejek liczy całą firmę, także byłych członków zespołu. Gdy się
  różnią, zdanie i tempo pokazują obie, jak `companyPlacementsNote` z 26.10.2026.
- **Rola bez `view_team_kpi`** widzi zdanie, tempo i soczewkę bez nazwisk.
  Nie wysyła zapytań o osoby i sygnały.

## Cele placementów według poziomu

Decyzja Artura z 05.11.2026: junior 1, senior 2, ekspert 3 placementy miesięcznie.
Cel zespołu to suma celów osób. Cele są wpisami osobowymi w „Cele KPI”
(`user_kpi_targets`), bo poziomu nie da się brać ze Ścieżki rozwoju: osoby
nowe w NEXUSIE, które Artur uznaje za ekspertów, mają tam poziom junior.
Domyślne 1 z `kpi_catalog.py` zostaje dla juniorów. Nowy ekspert ma pełny cel od
razu, także wstecz, bo cel osoby nie ma historii (decyzja Artura). Cele
weryfikacji i rekomendacji zostają jednakowe dla każdego (też jego decyzja), mimo
że w październiku wyszło 46% i 54% celu.
