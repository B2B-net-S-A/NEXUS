# Karta dojazdu przy odrzuceniu „Lokalizacja lub tryb pracy” (27.11.2026)
<!-- indeks: work_mode_issue (distance | office_days), residence_city, commute_office_cities, occasional_commute, relocation_willing, relocation_targets, accepts_more_office_days, candidate_commute_changed, preferences.commute_source, „Co nie pasuje?”, wiersze Mieszka / Biuro / Przeprowadzka -->

Prośba rekruterki z 27.11.2026 („przy odrzucaniu z powodu lokalizacji zapisać
miasto kandydata; dziś piszę je w notatce i nie wiem, czy trafia do profilu”).
Makiety ze stagingu i liczby: https://claude.ai/artifact/66p2W5u7cB9oPfC8ZEpoPm.
Artur wybrał wariant D. Na kopii produkcji z 26.11 w 60 dni było 224 takich
odrzuceń; 36 z 53 notatek podawało miasto, którego nie czytało ani wyszukiwanie,
ani dopasowanie, a 141 osób miało na profilu „Tylko zdalnie”, bo okno pytało
wyłącznie o dni w biurze i domyślnie zapisywało zero — także ludziom, którzy
jeżdżą do biura u siebie, tylko nie do innego miasta.

- **Powód w słowniku zostaje jeden** (`work_mode_mismatch`, okno: „Lokalizacja
  lub tryb pracy”). Okno pyta „Co nie pasuje?”: „Za daleko do biura”
  (`work_mode_issue = "distance"`) albo „Chce mniej dni w biurze”
  (`"office_days"`). Bez odpowiedzi „Potwierdź” czeka. Raporty mogą później
  rozdzielić te dwie sytuacje po tym polu, bez nowego powodu.
- **„Za daleko do biura”** (jedna osoba): gdzie mieszka (domyślnie miasto
  z profilu), do jakich biur dojedzie, ile dni w biurze, przeprowadzka, dojazd
  okazjonalny do innego miasta. Wszystko poza „co nie pasuje” jest opcjonalne
  i startuje od „Nie pytałem”, które niczego nie zapisuje. Tryb pracy na
  profilu zmienia się tylko wtedy, gdy rekruter wybrał dni — „za daleko”
  nigdy nie wpisuje samo z siebie „Tylko zdalnie”.
- **„Chce mniej dni w biurze”**: dni jak przed zmianą (obowiązkowe) plus
  zgoda na więcej dni przy wyjątkowym projekcie (`accepts_more_office_days`,
  ta sama kolumna co na karcie telefonu).
- **Kilka osób naraz:** tylko „co nie pasuje” (i dni przy „mniej dni”), bez
  miasta i list miast.
- **Stare wywołania** (formularz screeningu, panel DL, rozmowy, partia QC)
  nie wysyłają `work_mode_issue` i działają jak przed zmianą: dni obowiązkowe.
- **Zapis (ptaszek „Zapisz na profilu”, domyślnie włączony):** miasto jak
  ołówek „Lokalizacja” (blokada przed nadpisaniem z CV, audyt
  `candidate_location_changed` ze źródłem `rejection`; pusty kraj + polskie
  miasto → `PL`); biura → `preferences.office_cities` (te same co z ankiety
  „Twoje warunki”, czyta je bramka „inne miasto”); dojazd okazjonalny →
  `preferences.occasional_commute`; przeprowadzka → `preferences.relocation`
  (jej miasta liczą się w `candidate_office_tokens` jak relokacja z notatek);
  skąd to wiemy → `preferences.commute_source`, audyt `candidate_commute_changed`.
  Każde pole tylko przy powodzie `work_mode_mismatch`, inaczej 422.
- **Opis ruchu:** serwer dokleja przed opisem rekrutera linię „Za daleko do
  biura · mieszka: … · dojedzie do: … · …” albo „Chce mniej dni w biurze ·
  do N dni”, więc historia procesu pokazuje odpowiedź także bez notatki.
- **Profil, karta „Do propozycji”:** wiersze „Mieszka”, „Biuro” (z dopiskiem
  o dojeździe okazjonalnym) i „Przeprowadzka” oraz linia źródła pod nimi.
  Wiersz bez danych się nie pokazuje.
- **Czego nie zmieniamy:** reguła „inne miasto” z 27.09 (hybryda 1–3 dni
  zostaje z plakietką, 4–5 dni ukrywa) i powód „Mieszka poza Polską”
  (`mieszka-poza-polska-system-nie-proponuje.md`).
- **Starsze odrzucenia:** miasta z notatek sprzed zmiany nie wczytują się
  same. 15 osób z miastem tylko w notatce (kopia 26.11) Artur przegląda listą,
  wpis tylko do pustych pól przez UI produkcji.
