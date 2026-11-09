# Premia 200% w miesiącu podpisu, stała premia TCM i gwarancja DL (05.11.2026)
<!-- indeks: double_bonus w hr_bonus_rules, wynik raz po końcu miesiąca, miesiąc podpisu = potwierdzenie obu stron, rekruter cel KPI + 4/dzień + 75%, DL średnia marża > 50, system indywidualny i TCM poza programem, TCM stałe 1000 zł, gwarancja tylko DL tego samego placementu < 1 roku -->

Decyzje Artura z 05.11.2026, po porównaniu arkusza Delivery z października
z automatem (39 ze 110 wierszy zgodnych). Kod: `services/hr/double_bonus.py`,
`bonus_rules.DoubleBonusRule`, `FixedRoleAmount`, `placement_bonuses.guarantee_lost_dl`.

## Premia 200% (listopad i grudzień 2026)

- **Ustawienie** `hr_bonus_rules.double_bonus` (Ustawienia → Rozliczenia → Premie):
  miesiące `RRRR-MM`, weryfikacje na dzień (4), precision (75%), marża DL (50 zł/h).
  `null` = program wyłączony. Osób w kodzie nie ma.
- **Miesiąc podpisu** = dzień podpisu umowy przez konsultanta
  (`b2b_generated_contracts.signed_on`, ostatnia umowa kontraktu z `signed_both`),
  a bez niego dzień potwierdzenia podpisu obu stron (`signed_at`). Zmiana
  z 06.11.2026 (decyzja Artura): wcześniej liczył się dzień kliknięcia, a przy
  jednej z umów DL oznaczył podpis 30.10, konsultant podpisał
  02.11 07:32 i premia trafiłaby do października. Skąd jest `signed_on`
  (`signed_on_source`): `pdf` — podpis konsultanta w pliku z okna „Oznacz jako
  podpisaną”, `manual` — data wpisana ręcznie z powodem, `esign` — podpis
  kontraktora w NEXUSIE, NULL — oznaczenie sprzed tej zmiany (data z okna,
  domyślnie dzień kliknięcia). → `kontrakty/data-podpisu-z-podpisu-konsultanta.md`.
  Kontrakt bez umowy z Generatora liczy się od dnia założenia. Data na umowie
  (`signing_date`) się nie liczy: w październiku arkusz mieszał obie i podwoił
  3 kontrakty z podpisem 29–30.09, a pominął 2 z października.
- **Płace poprawiają dzień podpisu** w karcie „Premia 200%”: przy osobie lista
  jej umów z dniem i źródłem („z pliku”, „ręcznie przez …”, „e-podpis”,
  „wpisany przy oznaczeniu … · bez pliku” z plakietką „sprawdź”) i „Popraw
  datę” (`POST /api/hr/payroll/double-bonus/agreements/{id}/signed-on`,
  uprawnienie „Płace”, powód obowiązkowy, wpis `signed_on_corrected` w historii
  umowy z datą przed i po, źródło `manual`). Decyzja miesiąca jest zamrożona
  w `hr_double_bonus_results`, więc po poprawce w miesiącu z zapisanym wynikiem
  trzeba „Przelicz wynik” (odpowiedź podaje te miesiące, komunikat je wymienia).
- **Rekruter** (każdy poziom, te same KPI ilościowe): placementy podpisane
  w miesiącu ≥ cel KPI osoby (junior 1, senior 2, ekspert 3, w proporcji do
  dni pracy, jak Insights → Zespół), weryfikacje na dzień pracy ≥ próg,
  precision ≥ próg (z `insights_team_signals.team_people`). Rekruter to odbiorca
  premii rekrutera (pierwsza weryfikacja albo „Prowadzi”). Zastępstwo liczy się
  rekruterowi do celu.
- **Poza programem:** system indywidualny (`individual_recruiters`), rola ze
  stałą premią (TCM), konto nieaktywne.
- **Delivery Lead:** średnia zwykła marży zł/h placementów podpisanych
  w miesiącu, za które należy mu się premia DL, **większa** niż próg (50,00 nie
  wystarcza). Kontrakt bez stawki = brak wyniku (`missing_margins`), więc
  najpierw uzupełnia się stawkę. Dodatkowa premia DL idzie za wynikiem DL-a.
- **Wynik raz, po końcu miesiąca.** Nocny przebieg automatu (`sync_placements`
  → `settle_due_months`) po ostatnim dniu miesiąca programu zapisuje decyzję
  w `app_settings['hr_double_bonus_results']` (kto dostaje 200%) i uzgadnia
  kontrakty podpisane w tym miesiącu. Płace mogą przeliczyć wynik przyciskiem
  „Przelicz wynik” (`POST /api/hr/payroll/double-bonus/{rok}/{mies}/settle`,
  409 przed końcem miesiąca i w zamkniętym). W trakcie miesiąca ekran pokazuje
  tylko postęp.
- **Kwota i miesiąc.** Premia roli z wynikiem: kwota z reguły ×2, miesiąc
  wypłaty = miesiąc podpisu (pierwszy otwarty od niego), migawka
  `double_bonus: {month, multiplier}`. Ręcznie zmienione pola (`edited_*`)
  zostają. Termin 20 dni roboczych zostaje w wierszu, ale Płace i tak
  zatwierdzają przed terminem.
- **Konsultant odchodzi przed progiem** po wypłacie 200%: ryzyko firmy. Automat
  nie anuluje takiej premii, ostrzeżenie `bonus_contract_ended_early` jej nie dotyczy.
- **Ekrany:** karta „Premia 200%” nad premiami miesiąca w Płacach
  (`DoubleBonusCard`), „Do 200% w listopadzie” w „Moja współpraca →
  Wynagrodzenie dodatkowe i stawka” (`MyDoubleBonusCard`, `GET /me/double-bonus`,
  tylko o sobie; DL bez podpisanego placementu widzi 0). Wiersz premii ma
  dopisek „200% za cel w …” (`double_bonus_month`).
- Symulacja na październiku (kopia z 04.11): 0 z 13 rekruterów (4 weryfikacje
  dziennie miała 1 osoba) i 0 z 6 DL (max 49,00 zł/h). Artur: progi zostają.

## Stała premia dla roli (TCM)

- `hr_bonus_rules.fixed_role_amounts`: `[{role, amount}]`, w ustawieniach pole
  „Stała premia TCM”. Rola główna weryfikującego = stała kwota zamiast progu marży
  (marża ujemna dalej nic). System indywidualny wygrywa. Migawka `fixed_amount`,
  `rule_amount` czyta ją przy porównaniu z arkuszem.

## Gwarancja: tylko premia DL tego samego placementu

- Zastępstwo (`contracts.is_replacement` + `replaced_contract_id`, obowiązkowe
  w Generatorze od 26.10.2026) zabiera premię DL i dodatkową premię DL tylko
  wtedy, gdy zastępowaną osobę zatrudnił ten sam DL (regułą automatu
  na zastąpionym kontrakcie) i jej kontrakt trwał krócej niż rok (365 dni od
  startu do końca; bez końca liczy się do startu zastępstwa).
- Propozycja anulowana z powodem `guarantee` (automat ją przywróci, gdy dane się
  zmienią). Rekruter gwarancji nie ma: dostaje premię, a zastępstwo liczy mu się
  do celu 200% (decyzja Artura 05.11.2026, zmienia „rekruterzy od 2027” z 26.10).

## Domknięcie po rekruterze, który odszedł (06.11.2026)

- Gdy osobę u tego klienta zweryfikował wcześniej rekruter z wyłączonym kontem,
  premii rekrutera nie dostaje nikt, także rekruter, który ją domknął (przypadek
  z arkusza października, potwierdzone przez Płace i Artura). Taki placement nie liczy się rekruterowi
  do celu 200%. DL dostaje swoją premię DL.

## Kandydat wskazany przez klienta (06.11.2026)

- `contracts.is_client_referral` = „Tak” (pole w Generatorze i w kafelku
  „Szczegóły administracyjne” kontraktu, `kontrakty/szczegoly-administracyjne-umowy.md`): automat nie
  proponuje żadnej premii z placementu (rekruter, DL, dodatkowa premia DL).
  Propozycje `proposed`, także z arkusza i poprawione ręcznie, anuluje
  z powodem `client_referral` (w `AUTO_CANCEL_REASONS`, więc „Nie” je
  przywraca z zachowaniem ręcznych poprawek; wiersz z arkusza wraca też przy
  końcu kontraktu przed terminem). Premii zatwierdzonej nie rusza.
- Premia 200%: kontrakt nie liczy się rekruterowi do celu placementów ani do
  średniej marży DL-a (`double_bonus.month_contracts`). Zapisany już wynik
  miesiąca zmienia dopiero „Przelicz wynik”.
- Prognoza „w drodze” (`my_settlement.bonus_forecast`) go pomija.

## Poza zakresem (nie dopisuj „przy okazji”)

- Następca rekrutera, który odszedł: premia rekrutera nikomu (decyzja 05.11.2026).
- Premia za „dodanie do bazy”: Delivery zapłaciło ją ostatni raz w październiku,
  od listopada jej nie ma (06.11.2026).
