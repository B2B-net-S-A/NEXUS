# Delivery Lead przesuwa bez blokad pól (22.10.2026)
<!-- indeks: `skips_fill_gates`, `requirements_skipped`, odznaka „Przesunął DL”, premia rekrutera, rekruter dalej uzupełnia -->

Zgłoszenie Artura 22.10.2026: Delivery Lead czasem widzi, że kandydat pasuje też na
inny request, a rekruter go tam nie wysyła — wtedy DL robi to sam. Bramki pól
(arkusz, stawka, minimum dla DL z 21.10) zatrzymywały go jak rekrutera. Makiety:
https://claude.ai/artifact/9iX3u3Kxx1Lo951a2qqdri.

Decyzje Artura 22.10.2026 (wszystkie rekomendowane warianty):

- **D1 — wszystkie bramki pól zdjęte dla DL-a.** Osoba z uprawnieniem
  `recruitment_manage` (domyślnie DL i admin — to samo, które decyduje o wysyłce CV)
  przechodzi bez arkusza screeningu (albo „Dlaczego” w rekrutacji bez pytań), stawki
  kandydata, minimum (lokalizacja, tryb, dostępność, „Dlaczego”, pola klienta), CV
  firmowego przed „QC CV” i debriefu przed „Umową”. Jedna reguła:
  `pipeline_move_rules.skips_fill_gates(user)`, wyłącznik `DL_SKIPS_FILL_GATES`
  (w testach domyślnie wyłączony w `conftest.py`, włącza go `dl_skips_on`).
  `assert_verified_requirements` i `assert_debrief_before_contract` zwracają wtedy
  listę braków zamiast 409, a `/move` zapisuje `Activity(requirements_skipped)`
  z `missing` na nowym wierszu etapu. Okno „Przesuń dalej” pokazuje te braki jako
  nieblokujące („nie blokuje — przesuwasz jako Delivery Lead”,
  `move_requirements._skip_fill_gates`).
- **Zostaje dla wszystkich:** QC CV przed wysyłką (DL ma „Przepuść mimo QC”), stawka
  do klienta przy „CV wysłane”, sposób podpisu przy „Zatrudniony”, umowa w podpisie
  w NEXUSIE, ostrzeżenie o czarnej liście i wecie HM, rezerwacja 12 h (DL i tak ją
  omija). Ruch zbiorczy (`/bulk-move`) i API integracji (konto serwisowe bez
  uprawnień) bramek nie omijają.
- **D2 — bez okna, z „Cofnij”.** Na Tablicy strzałka DL-a nie jest szara przez
  braki pól (`knownForwardGap(…, { skipsFillGates })` zna mu tylko QC), okno
  minimum się nie otwiera, a „Zweryfikowany” bez stawki idzie bez okna stawki
  (`usePipelineMove`: `canSendToClient`). Komunikat strzałki wymienia braki
  („Imię Nazwisko → Zweryfikowany · bez: arkusza screeningu, stawki kandydata”,
  `fillGapsText`). Karta od „Zweryfikowanego” do końca procesu ma odznakę
  „Przesunął DL · bez arkusza i stawki” z kanban payloadu
  `requirements_skipped` / `requirements_skipped_by_name`
  (`requirementsSkippedBadge`). Odznaka pokazuje tylko braki, których dalej brakuje
  (`pipeline._still_missing`: arkusz, stawka etapu albo profilu, `minimum_missing`;
  debrief zostaje) — uzupełnione ją gaszą. Formularz screeningu DL-a przekazuje dalej bez
  odpowiedzi i minimum; stopka dalej mówi, czego brakuje.
- **Dodanie od razu na „Zweryfikowany”.** W oknie „Dodaj do rekrutacji” osoba
  z tym uprawnieniem przy jednej osobie wybiera „Na etap: Nowi / Zweryfikowany”
  (`AddToRecruitmentDialog`). Dodanie idzie jak zawsze (`proposals/bulk`), a drugi
  krok to zwykły ruch karty przez `usePipelineMoveCore`. „CV wysłane” z makiety
  odpadło: wysyłka wymaga przeglądu DL ze stawką do klienta i QC, więc DL wysyła
  z „Zweryfikowanego” zwykłą drogą.
- **Dzwonek do prowadzącego.** Wejście DL-a na „Zweryfikowany” mimo braków dzwoni do
  `jobs.recruiter_id` (gdy to ktoś inny niż DL): „<DL> przesunął(-ęła) <osoba> na
  „Zweryfikowany”” z listą braków (`pipeline._notify_recruiter_of_skip`, typ
  `stage_changed`). Sam przeskok debriefu nie dzwoni. Decyzja Artura 22.10.2026
  (audyt, F58): dzwoni każde przejście DL-a przez „Zweryfikowany” od lewej, także
  przeskok z Nowych/Screeningu od razu na „QC CV” czy dalej — wtedy tytuł wymienia
  kolumnę docelową. Warunek to niepusta lista braków z
  `assert_verified_requirements` (zwraca je tylko przy wejściu z Nowych/Screeningu),
  nie `target_column == "verified"`.
- **Rekruter bez zmian.** Każda bramka z `kanban-bez-bramek.md` i
  `minimum-dla-dl-przed-zweryfikowany.md` dalej go zatrzymuje.
- **D4 — jedna premia.** Gdy pierwszym weryfikującym jest Delivery Lead kontraktu,
  premii rekrutera nie ma — DL dostaje premię DL-a
  (`placement_bonuses.PlacementContext.people`). Nieruszone propozycje sprzed zmiany
  automat anuluje przy uzgodnieniu (`rule_no_longer_applies`).

Statystyki: proces zalicza się temu, kto pierwszy przesunął na „Zweryfikowany”
(`credit_user_id`) — więc DL, który sam zweryfikował, już dziś ma go w Insights →
Zespół. Liga Mistrzów i cele zostają dla rekruterów (filtr roli w `competitions.py`,
`KPI_BEARING_ROLES`). Licznik „Sam przekazał” u DL-a (D3) to osobny PR tej decyzji.
