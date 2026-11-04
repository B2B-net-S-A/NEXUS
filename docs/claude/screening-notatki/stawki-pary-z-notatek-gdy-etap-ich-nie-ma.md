# Stawki pary z notatek, gdy etap ich nie ma (12.10.2026)
<!-- indeks: stawka z karty i notatki wysyłki tylko jako podpowiedź -->

Zgłoszenie Delivery Leada 12.10.2026: „chcę ponownie wysłać osobę do klienta,
wchodzę w rekrutację z września i nie widzę, za ile ją wysłałam — czy dane się
nie zapisują?”. Dane były, tylko nie tam, gdzie patrzy ekran. W Traffit nie
było pól stawki: rekruter zapisywał oczekiwanie kandydata w notatce-karcie,
a Delivery Lead cenę wysłania w zwykłej notatce, często bez rekrutacji, minutę
po ruchu na „Wysłany do Klienta”. Import przenosi etapy bez kwot
(`services/traffit/importer.py`, `_upsert_stage_row`), a zakładka „Rekrutacje”
profilu i „W tej rekrutacji” w panelu osoby czytały wyłącznie
`candidate_stages.expected_rate_*` / `client_rate_*`.

Pomiar na produkcji 12.10.2026 (tylko odczyt): z 2 208 par wysłanych do
klienta od 07.2026 stawki kandydata na etapie nie ma 2 182, a 1 762 z nich
mają ją w karcie rekomendacji; z 1 531 par bez stawki do klienta 583 mają
notatkę wysyłającego do 30 minut od ruchu (530 do 2 minut).

- **Podpowiedź nie jest stawką.** `services/recruitment_rate_hints.py` niczego
  nie zapisuje. Pola `expected_rate` / `client_rate` zostają puste, obok idą
  `expected_rate_hint` i `client_rate_note`; stawką stają się dopiero po
  „Uzupełnij” i zapisie (zwykłą ścieżką `change_rate` / `client-rate`).
  Źródłem dla zamówień i umów zostają wiersze etapu (`recruitment_rates.py`,
  D7) — nie podpinaj tam podpowiedzi, bo różnica w zamówieniu z maila
  liczyłaby się wobec kwoty, której nikt nie potwierdził.
- **Stawka kandydata** to reguła „W tej rekrutacji” z propozycji
  (`candidate_rate_from._newest_by_job`: najnowsza porównywalna obserwacja
  z tą rekrutacją — karta, wpis „X/Y” Delivery Leada, zgłoszenie). Jedna
  reguła dla `this_job_rates` (wielu kandydatów, jedna rekrutacja)
  i `candidate_job_rates` (jeden kandydat, wszystkie rekrutacje). Widzi ją
  każda rola, jak stawkę kandydata na etapie.
- **Notatka z wysyłki** (`pick_send_notes`): autor = osoba, która przesunęła
  kartę na „CV wysłane”; najwyżej 30 minut przed albo po ruchu; przypięta do
  tej rekrutacji albo do żadnej; rodzaj `dl_rate`, a zwykła notatka tylko od
  Delivery Leada albo admina (ta sama bramka autora co wpis „X/Y”,
  `client_rate_notes.DL_PAIR_AUTHOR_SQL` — rekruter przesuwający na „CV
  wysłane” w Nordei pisze o stawce kandydata); zawiera liczbę 40–400. Tylko
  para bez stawki do klienta na żadnym etapie. Przy kilku wysyłkach liczy się
  najnowsza, która ma notatkę; z kilku notatek — najbliższa ruchowi.
  Od 14.10.2026 godzina („14:50”, „o 14.50”) i numer telefonu (9 cyfr w grupach
  3-3-3 albo 2-3-2-2, jeden rodzaj separatora, opcjonalnie +48) nie są kwotą
  (`has_amount`) — audyt 13.10 pokazał, że taka liczba w notatce bliżej ruchu
  wypychała prawdziwą notatkę z wysyłki. „150 120 130” spacjami czyta się jak
  telefon; DL pisze „150/100-110”. Kryterium autora, okna i rekrutacji to jedna
  funkcja `_belongs_to` dla podpowiedzi i dla zakrycia treści (niżej).
- **Kwoty z notatki nie wpisujemy do pola.** Notatka z trzema liczbami
  („150/100-110”) nie jest jednoznaczna; jednorazowe uzupełnienie
  `client_rate_notes` świadomie takie pomija. Człowiek czyta treść i wpisuje
  stawkę sam, dlatego „Uzupełnij” przy stawce do klienta otwiera puste pole,
  a przy stawce kandydata — pole z kwotą z karty i jednostką „/h”.
- **Notatka bez rekrutacji może stać pod dwiema rekrutacjami** wysłanymi
  w tym samym oknie przez tę samą osobę — nie wiemy, której dotyczy.
- **Widoczność:** notatka z wysyłki niesie cenę dla klienta, więc wychodzi
  wyłącznie do `user_can_view_client_rate` — trasa pary nie woła `send_notes`
  dla innych ról, a `_candidate_history_response_for_user` zeruje
  `client_rate_note` razem z `client_rate`. Nowy czytelnik `send_notes` =
  ta sama bramka.
- **Sama notatka też jest zakryta (decyzja C, 14.10.2026).** Do 14.10 rekruter
  czytał „Wysłany 150/100-110” w Historii profilu i w „Wcześniej u nas”, bo to
  zwykła notatka (`human`). `send_note_ids` rozpoznaje notatki z wysyłki tą samą
  regułą (każdą w oknie, nie tylko wybraną do podpowiedzi, i także przy parze
  ze stawką na etapie), a `GET /api/notes` (lista i pojedyncza, przypięcie)
  zakrywa je jak `dl_rate` — szczegóły w
  `uprawnienia/rekrutacje-i-kandydatow-widza-wszyscy-stawki-do.md`.
- **API:** `/api/candidates/{id}/history` niesie obie podpowiedzi przy każdej
  rekrutacji (awaria odczytu podpowiedzi nie zabiera historii — savepoint
  i wpis w logu); `GET /api/candidates/{id}/recruitment-rate-hints?job_id=`
  dla panelu osoby — jedno zapytanie na OTWARTĄ kartę i tylko wtedy, gdy
  karta nie ma stawki kandydata albo (dla ról ze stawką do klienta) stawki
  do klienta. Nie dokładaj tego do odpowiedzi Tablicy: `collect` na
  kilkaset kart przy każdym odświeżeniu to kilka zapytań na kandydata.
- **Front:** `lib/api/recruitmentRateHints.ts` (typy, opisy źródła z
  `rateSourceLabel` — te same nazwy co w oknie „Historia stawek”),
  `RecruitmentRateRow` (dopisek `*-footnote` pod wartością), dok:
  `dock-rate-hint` w „W tej rekrutacji” i wiersz „Do klienta” z notatką.
  Harnessy: `/preview/candidate-profile` (rekrutacja 503),
  `/preview/job-detail` (karta „Karol”).
- **Poza zakresem:** wiersz stawek w profilu jest tylko przy rekrutacjach
  w toku (`!ended`) — zakończona rekrutacja nie pokazuje ani stawek, ani
  podpowiedzi.
