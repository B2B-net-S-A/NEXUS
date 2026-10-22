# „Dodaj do rekrutacji”: zamknięta karta to nie „już w rekrutacji” (12.10.2026)

<!-- indeks: powód `closed_in_job`, „Przywróć” ruchem karty -->

Zgłoszenie 12.10.2026: rekruterka i Delivery Lead nie mogły dodać osoby do
rekrutacji. Osoba miała w niej kartę „Odrzucony” sprzed czterech dni (historia
z Traffita), a `POST /api/jobs/{id}/proposals/bulk` pomijał jako `already_in_job`
każdego, kto ma w rekrutacji jakikolwiek wiersz etapu. Okno znikało, ekran
pokazywał zielone „Nikogo nie dodano… Pominięto: 1”. W 185 otwartych
rekrutacjach było wtedy 6 596 par osoba–rekrutacja z samą zamkniętą historią.

- **Dwa powody zamiast jednego** (`api/proposals_bulk.py`): `already_in_job`
  zostaje dla osoby w toku i zatrudnionej; `closed_in_job` dostaje osoba, której
  bieżąca karta stoi w „Zamkniętych” — ta sama reguła kolumny co Tablica
  (`board_stage_badges.board_column_for(...) == "closed"`: odrzucony, wycofany,
  rezerwa). Etykieta mówi etap, dzień w kalendarzu firmy i osobę, która kartę
  zamknęła.
- **Dodanie nadal samo nie przywraca.** Odrzucenie sprzed kilku dni ma autora
  i powód; rekruter ma je zobaczyć, zanim osoba wróci na Tablicę. Wiersz niesie
  `closed` z celem ruchu (`restore_stage`, `restore_stage_def_id` = etap, na
  który trafiłoby to dodanie) i `state_version` procesu.
- **„Przywróć” to ruch karty, nie drugie dodanie.** Okno
  (`AddToRecruitmentDialog`) woła `usePipelineMoveCore` — ten sam ruch co
  przeciągnięcie z „Zamkniętych”: nowe podejście (`attempt_no + 1`), anulowany
  czekający mail odmowy, okno „Przenieś mimo to” przy czarnej liście, konflikt
  wersji. Własna ścieżka zapisu w `proposals/bulk` zgubiłaby anulowanie maila.
  Jak na Tablicy: weto hiring managera ostrzega dopiero przy ruchu w stronę
  klienta, a przywrócona karta nie dostaje blokady 12 h ani źródła wejścia —
  to powrót, nie nowe dodanie. Przywracanie idzie po jednej osobie (hak ma
  jedno okno ostrzeżenia), a okna nie da się zamknąć w trakcie ruchu.
- **Okno zostaje otwarte tylko wtedy, gdy jest co zrobić albo nic się nie
  dodało.** Zamknięta karta albo zero dodanych → powód z serwera w oknie
  i brak zielonego toastu. „18 dodanych, 2 już były” zamyka okno jak dotąd,
  a toast wymienia powody (`addToRecruitmentSummary`).
- **Nowy powód dostaje tylko człowiek** (`claim=True` w `add_candidates_to_job`).
  Integracja i automat dopasowań dalej widzą `already_in_job`: nie mają jak
  przywrócić karty, a etykieta z imieniem osoby, która ją zamknęła, nie trafia
  do ich odpowiedzi ani do dziennika decyzji automatu.
- **„Przypisz do rekrutacji” odmawia przy zamkniętej karcie (13.10.2026).**
  `POST /api/candidates/{id}/assign-to-job/{job_id}` odpowiadał 200
  `already_in_pipeline` dla każdej osoby z jakimkolwiek wierszem etapu,
  a trzy ekrany czytały to jako sukces („Przypisano”). Człowiek dostaje teraz
  409 `{code: "closed_in_job", message, closed}` — to samo zdanie i ten sam cel
  ruchu co w oknie dodawania (`proposals_bulk.closed_card_skip`). Okno
  „Przypisz do rekrutacji” (`QuickAssignV2`) pokazuje je i przywraca kartę
  przez `recruitment/ClosedCardRestore`; widżet dopasowań i karta
  kontraktora pokazują zdanie z serwera jako błąd. Karta w toku i integracja
  dostają jak dotąd 200 `already_in_pipeline`.
- **Ekrany, które po `already_in_job` chowają wiersz** („Szukaj ręcznie”
  w rekrutacji, propozycje, kafel propozycji na pulpicie), przy `closed_in_job`
  zostawiają osobę na liście z komunikatem — badge „Dodano do „Nowych”” przy
  odrzuconej osobie był nieprawdą.

Czego ta zmiana nie rusza: pozostałe wejścia z regułą „jakikolwiek wiersz”
(promocja z shortlisty, „Dodaj championa”, wtyczka LinkedIn) i filtry, które
chowają takie osoby w wyszukiwaniu w rekrutacji. Od 13.10.2026 okno „Dodaj
kandydatów do pipeline” pokazuje przy frazie dosłownej osoby z kartą w tej
rekrutacji w sekcji „Już w tej rekrutacji” i przywraca zamkniętą kartą tym
samym ruchem (`imiennicy-w-oknie-dodawania.md`); filtr wyników się nie zmienił.
