# Mieszka poza Polską: system nie proponuje, powód odrzucenia zapisuje kraj (24.11.2026)
<!-- indeks: residence.py, lives_outside_poland, abroad_ids, system_exclusions, not_proposed_abroad, outside_poland, 0768, residence_country, autofill_withdrawn_abroad, RejectionResidenceField -->

Decyzja Artura 24.11.2026 po prośbie rekrutera („NEXUS podrzuca do nowych
rekrutacji sporo osób, które w CV mają zamieszkanie poza Polską”). Makiety
i liczby: https://claude.ai/artifact/2D23z3c8mpy1dxvBL5ArLp. Artur wybrał
wariant C, a potem zawęził: „w żadnych rekrutacjach masz nie proponować ludzi
z poza Polski”. Na kopii produkcji z 24.11 system w 30 dni dodał do „Nowych”
111 takich osób (z 6913), 44 wciąż stały otwarte; odrzucano je głównie jako
„Inne”, a „Lokalizacja lub tryb pracy” zapisywała im na profilu fałszywe
„Tylko zdalnie”.

- **Reguła (`app/services/residence.py`):** mieszka poza Polską = kraj
  w profilu inny niż `PL` i miasto (`city` albo pierwszy człon `location`)
  spoza słownika `pl_places`. Miasto w Polsce wygrywa z krajem, bo kraj bywa
  obywatelstwem (23 profile typu `BY` + Warszawa). Profil bez kraju przechodzi.
  `lives_outside_poland` (Python) i `abroad_ids` (SQL) to ta sama reguła —
  na kopii z 24.11 obie wskazują te same 2919 osób; pilnuje `test_residence.py`.
- **Gdzie system ich nie proponuje:** `new_column_autofill.system_exclusions`
  (każde dokładanie do „Nowych”: poranna porcja, tempo, „Dodaj kolejnych”,
  dopełnianie, pula jednej listy), lista propozycji i jej liczniki
  (`job_proposals.not_proposed_abroad` w `_pairs_for_job`,
  `open_counts_for_jobs`, `fresh_open_pairs`, `single_candidate_list._pairs`),
  auto-match z nowego CV i nowej rekrutacji, migawka propozycji AI przy
  tworzeniu rekrutacji, podsumowanie dopasowań, powiadomienie o podobnej
  rekrutacji i skan Targu. Wiersze propozycji i puli zostają w bazie — znika
  tylko widok, więc po zmianie kraju na Polskę osoba wraca.
- **Wyjątki:** osoba, która sama zgłosiła się z ogłoszenia (źródło z
  `POSTING_SOURCES`), zostaje na liście — tej nie proponuje system. Ręczne
  wyszukiwanie, Talent Radar, „Moi ludzie” i ręczne dodanie działają jak
  dawniej; wspólnych bramek (`pipeline_eligibility`, `dealbreaker_filters`,
  `candidate_search_predicates`) celowo nie ruszamy, bo obsługują też ludzi.
- **Powód „Mieszka poza Polską” (`outside_poland`, migracja 0768 + lustro
  w `entrypoint.sh`):** grupa Warunki, wybierają „my” i klient, bez weta
  hiring managera; kosz raportu „dane” (system odcina tę osobę sam, więc
  w „Nowych” była tylko przez brak kraju w profilu). Przy jednej osobie okno
  pyta „Gdzie mieszka?” (domyślnie kraj z profilu, „Potwierdź” czeka na
  wybór), a ruch niesie `residence_country`. Serwer zapisuje kraj jak ołówek
  „Lokalizacja” (blokada `_manual_override_*` przed nadpisaniem z CV, audyt
  `candidate_location_changed` ze źródłem `rejection`), zdejmuje polskie
  miasto z profilu i nietknięte karty od systemu z innych rekrutacji
  (`autofill_withdrawn_abroad`, w „Pracy w tle”: „mieszkają poza Polską”).
  `residence_country` przy innym powodzie albo `PL` → 422. Szablon bez wiersza
  `outside_poland` zapisuje „Inne” z nazwą powodu i nie pyta o kraj.
