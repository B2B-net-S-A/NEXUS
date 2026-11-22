# Lata „jako X” liczone z ról tego samego zawodu (20.11.2026, wariant B)

<!-- indeks: `role_family.same_profession`, `_scoped_roles`, „w tym M lat jako X”, tylko w górę, technologia i stopień z X, „jako X w <Firma>”, uwaga „liczą też role tego samego zawodu”, `years_breakdown` -->

Decyzja Artura z 20.11.2026 po pomiarze na kopii produkcji (`nexus_staging_nightly_20261119`,
tylko odczyt). Prompt 14 (`legacy_v7/prompts.py`, decyzja z 17.11) każe pisać w punkcie 1
„N lat w IT, w tym M lat jako X”, gdzie M to suma dat WSZYSTKICH ról tego zawodu. Kod
(`_fix_scoped_years`, reguła z 13.10) nadpisywał jednak M sumą ról, których nazwa zawiera X
dosłownie. Dowolne M modelu zamieniało się w CV w „w tym ponad 1 rok jako analityk
biznesowo-systemowy” przy 16 latach w rolach analityka („Senior Business Analyst”,
„Analityk systemowy”, „Analityk IT”), a przykład z samego promptu (DevOps Engineer, DevOps
Consultant i Cloud Operations Engineer) dawał „ponad 5 lat” zamiast ponad 8.

Pomiar (60 dni do 18.11.2026, 1874 CV, 913 z liczbą „jako X”): liczba niższa o co najmniej
rok niż staż w rolach tego samego zawodu w 78 CV (49 kandydatów + 13 CV bez kandydata),
o trzy lata i więcej w 31. W 30 dniach 43 z 1115 CV. Prompt 14 (18.11, 32 CV): w 4 CV kod zbił
M do jednej roli (np. 1 rok przy 6 latach testera, ponad 3 lata przy 12 latach projektanta).

## Co liczy kod

- **Rola tego samego zawodu** (`legacy_v7/role_family.same_profession`): rdzeń nazwy ze
  słownika PL↔EN (analityk = analyst, programista = developer, tester = QA / test engineer,
  kierownik projektu = project manager, Cloud Engineer = DevOps), bez przymiotników domeny
  (biznesowy, systemowy, IT) i bez stopnia. „Cash Management Analyst”, „Tax Content
  Analyst” czy „IT Support Engineer” to inne zawody niż analityk IT i DevOps.
- **Technologia i stopień z X zawężają zawód:** „jako Java Developer” liczy tylko role
  z Javą w nazwie albo w technologiach roli (lata w PHP nie wchodzą), „jako Senior Tester”
  tylko role z „Senior” w nazwie.
- **Bez rodziny:** „jako X w <Firma>” / „as X at <Firma>” (liczba mówi o jednej firmie),
  punkt z dwiema liczbami „jako” („7 years as a System Analyst and 2 years as a Business
  Analyst”, liczby rozpisują role) i role bez czytelnych dat.
- **Tylko w górę.** Liczba nie spada poniżej tego, co kod pisał dotąd (suma ról o tej
  nazwie albo liczba modelu, gdy takiej roli nie ma lub ma mniej niż 6 miesięcy), a „ponad”,
  „+” i ułamek modelu („4,5 roku”) nie słabną. W „w tym M lat jako X” M nie przekracza
  liczby obszaru przed „w tym”, a w „N lat doświadczenia jako X” całej kariery. Pomiar
  przed/po na kopii: 146 CV zmienionych, 82 liczby w górę o pełny rok lub więcej, 0 w dół.
- **Uwaga dla rekrutera** przy każdej zmianie przez zawód: „WERYFIKUJ: lata „jako X”
  w podsumowaniu liczą też role tego samego zawodu: … Popraw liczbę, jeśli któraś z nich
  to inny zawód.” (najwyżej cztery role z datami, reszta liczbą). Przegląd ręczny 78 trafień:
  ok. 10 dolicza rolę pokrewną do dyskusji (Agile Coach przy Scrum Masterze, Manager IT
  przy Dyrektorze IT), dlatego uwaga wymienia role.

Zasada z 13.10 „nigdy nie dolicza lat z cudzych ról” zostaje: cudza rola to rola innego
zawodu (kierownik sklepu przy Data Engineerze), nie inna nazwa tego samego zawodu.

## Panel „Do poprawy”

`cv_tenure_checks.tenure` (uwaga `years_breakdown`) liczy przy „jako X” te same role
zawodu co generator (bez technologii roli, których edytor nie ma), więc propozycja
„Ponad N lat w IT, w tym M lat jako X” nie wraca do sumy jednej nazwy.

## Gdzie

- `backend/app/services/cv_generator_b2b/legacy_v7/role_family.py` — słownik i dopasowanie.
- `_helpers._scoped_roles` (role o tej nazwie i dołożone), `_fix_experience_years`,
  `_fix_role_subfigure`, `_fix_scoped_years`; uwagi zbiera `pipeline.py` (`years_notes`).
- Testy: `backend/tests/test_cv_years_role_family.py` (także odmowy i zabezpieczenia
  „tylko w górę” z pomiaru przed/po).
- Ścieżka v10 (`standalone_service`) bez zmian. CV wygenerowane wcześniej nie zmieniają się same.
