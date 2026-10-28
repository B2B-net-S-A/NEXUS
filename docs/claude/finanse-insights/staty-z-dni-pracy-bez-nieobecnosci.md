# Staty i cele z dni pracy — nieobecność nie pogarsza wyniku
<!-- indeks: person_workdays (dni robocze minus zatwierdzona nieobecność, pół dnia 0,5), próg i plakietka Wyścigu Rekomendacji per osoba, „Weryf. / dzień” w Zespole, cele KPI i zespołu w proporcji do dni pracy -->

Decyzja Artura z 28.10.2026. Staty liczą się tylko z dni, które osoba mogła
przepracować. Urlop, przerwa w świadczeniu usług albo inna zatwierdzona
nieobecność nie może dawać gorszego wyniku, wyższego progu ani tempa „poniżej
celu”. Wcześniej każdy ekran liczył dni po swojemu: w trwającym miesiącu
Rywalizacja i Zespół dzieliły przez dni kalendarza, a próg nagrody był wspólny
(np. 33 weryfikacje i 5 dni przerwy dawały 1,65/dzień i próg 80 zamiast 2,2
i 60).

## Jedna reguła: `app/services/person_workdays.py`

- **Dzień roboczy** = Pon–Pt bez polskich świąt (jak próg wyścigu
  i `workdays_between`).
- **Dzień pracy** = dzień roboczy minus zatwierdzona nieobecność z
  `leave_request_days` (pół dnia = 0,5). Nieobecność oczekująca, odrzucona
  i anulowana się nie liczy. Weekend i święto niczego nie odejmują.
- **Cel** okresu × dni pracy / dni robocze okresu, w górę do pełnej sztuki
  (`prorated_target`). Okres bez dni roboczych zostawia cel bez zmian, cały
  okres nieobecności = cel 0.
- Nieobecności liczą się tylko przy urlopach NEXUSA
  (`hr_availability_source = local`, stan procesu jak w
  `kpi_engine.personal_days_off`). Przy innym źródle wszystko liczy się jak
  przed zmianą.

Nie dopisuj nowego mianownika „na dzień” ani skali celu obok tej funkcji —
bierz `workdays_by_user`, `prorated_targets` albo `target_for_window`.

## Gdzie działa

- **Wyścig Rekomendacji**: plakietka „X/dzień” (`race_workdays_to_date`,
  źródło `nexus`) i próg `required_verifications_by_user` z tych samych dni.
  Pole `threshold_basis` (`workdays` / `calendar`) zamraża się z wynikiem,
  żeby zamknięty miesiąc podpisywał próg tak, jak go policzono.
  Dopisek „· liczone z N dni pracy” stoi tylko przy osobach, które miały mniej
  dni pracy niż najwięcej w rankingu; rodzaju nieobecności nie widać.
- **Insights → Zespół**: „Weryf. / dzień” per osoba
  (`TeamPeople.workdays_by_user`), cel placementów miesiąca w proporcji do dni
  pracy całego miesiąca (także zaplanowana nieobecność).
- **„Moje KPI”, panel „Jak idzie mi ten miesiąc?” i coach**: cel dnia,
  tygodnia i miesiąca w proporcji do dni pracy całego okresu
  (`kpi_engine.target_on_workdays`, także `kpi_panel.compute_my_panel`); w dniu nieobecności
  cel dnia = 0, więc trasa `/api/kpis/me/today` go nie zwraca i górny pasek nie
  pokazuje „0 / 4 dziś”. Tempo dalej pomija pełne dni nieobecności.
- **Cele zespołu (HoR/TCM)**: suma celów osób po przeliczeniu na ich dni pracy.

Bez zmian: miesiące rozliczone w DynaReporterze (tam `days_worked` z raportu)
i program praktykanta (ukryty od 17.10.2026).
