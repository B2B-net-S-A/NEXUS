# P0 — rekrutacja ultrapilna przez 24 h (27.10.2026)
<!-- indeks: nakładka p0_until nad jobs.priority (nie enum); ustawia HoR i admin z powodem, DL tej rekrutacji prosi (od 28.10); 24 h / 48 h / do piątku; bez limitu; na górze listy, Daily, requestów; panel na pulpicie i pasek tylko dla zespołu rekrutacji (od 28.10), wiersze jak Daily; dzwonek + mail obowiązkowy do zespołu -->

Prośba Olafa: czerwony przycisk „Omawiane na Daily” na co najmniej 24 h
i lista takich rekrutacji na pulpicie każdej osoby. Artur rozwinął to
w poziom **P0 — ultrapilne przez 24 h**, ponad P1. Powód: P1 przestało
cokolwiek wyróżniać — na kopii produkcji z 22.10 41 z 204 otwartych
rekrutacji miało P1, a nowa rekrutacja dostaje P1 domyślnie.
Makiety: https://claude.ai/artifact/JTKoqosf8yQf61YcrP7dhE.

## Decyzje Artura (27.10.2026)

- **Ustawia Head of Recruitment i administrator** (`job_p0.P0_ROLES`,
  trasy za `HeadOfRecruitmentPlus`). Delivery Lead nie — inaczej P0
  rozlałoby się jak P1.
- **Powód obowiązkowy** (3–300 znaków), widzą go wszyscy.
- **Czas**: 24 h (domyślnie), 48 h albo do piątku 18:00 (Warszawa).
  „Przedłuż o 24 h” liczy od obecnego terminu, nie od teraz.
- **Bez limitu** rekrutacji naraz.
- **Pulpit**: stały panel „P0 — ultrapilne teraz” nad kafelkami,
  niezależnie od własnego układu (nie kafelek do usunięcia); znika, gdy nie
  ma żadnego P0. *(Od 28.10.2026 tylko u zespołu rekrutacji — sekcja niżej.)*
- **Powiadomienie**: dzwonek `job_p0_set` i mail obowiązkowy `job_p0`
  (od razu, z kolejki maili) do rekruterów pracujących nad rekrutacją
  i jej Delivery Leada, bez osoby, która ustawiła P0.

## Jak działa

- **P0 to nakładka z terminem, nie wartość `jobs.priority`** (0525:
  `p0_until`, `p0_reason`, `p0_set_at`, `p0_set_by`). P0 obowiązuje, gdy
  rekrutacja jest otwarta i `p0_until` jest w przyszłości
  (`job_p0.is_active` / `active_clause`). Po terminie po prostu przestaje
  — bez pętli w tle. Priorytet się nie zmienia, więc zespół nie przechodzi
  do „Poprzedni rekruter” (`apply_priority_transition` nie jest wołane).
  Nie zamieniaj tego na czwartą wartość enumu.
- Zamknięcie rekrutacji czyści P0 (`job_lifecycle`), ponowne otwarcie go
  nie przywraca.
- **Kolejność**: `p0_rank_expr()` jest pierwszym kluczem każdego sortowania
  listy `/jobs` i tablicy requestów (Daily), front robi to samo
  w `orderRequests`.
- **Automat przydziału** traktuje aktywne P0 jak P1 (`priority_rank=0`,
  nie „Przyjmujemy”), także na rekrutacji „Bez priorytetu”.
- **Champion nie wstrzymuje P0** — to świadoma decyzja człowieka na krótko.
- Trasy: `GET /api/p0-jobs` (górny pasek i pulpit; własna ścieżka, bo
  `GET /api/jobs/{job_id}` przechwyciłby `/api/jobs/p0`),
  `POST /api/jobs/{id}/p0` `{reason, duration}`,
  `POST /api/jobs/{id}/p0/extend`, `DELETE /api/jobs/{id}/p0`.
  Ślad w Historii zdarzeń: `p0_set`, `p0_extended`, `p0_cleared`.
- Kolumny P0 są w `NEXUS_OWNED` — Traffit ich nie nadpisuje.


## Propozycje Olafa — decyzje Artura (28.10.2026)

Przegląd z zrzutami ze stagingu: https://claude.ai/artifact/TY5MJmR9n8rbFtSBDGgYDT
(sekcje 5 i 6). Na kopii produkcji rekruterka pracująca nad 2 z 5 P0
widziała najpierw trzy cudze, a jej własne chowało się w „I jeszcze 2”.

- **Pulpit i górny pasek: tylko zespół rekrutacji.** `GET /api/p0-jobs`
  oddaje P0 rekrutacji, w których patrzący pracuje jako rekruter (`working`
  z `job_team.recruiters_for_jobs`, bez propozycji automatu), albo jest jej
  Delivery Leadem (`jobs.delivery_lead_id`). Head of Recruitment i admin
  widzą wszystkie (`job_p0.visible_to`, `sees_all`). Filtr jest na serwerze,
  więc licznik w pasku i panel mówią to samo. **Lista `/jobs` i Daily bez
  zmian** — P0 stoi tam na górze u wszystkich. Nie dokładaj „Jeszcze N P0
  w innych rekrutacjach” — Artur wybrał „cudze ukryte”, nie „zwinięte”.
- **Delivery Lead prosi, HoR zatwierdza.** DL tej rekrutacji (nie każdy DL)
  wybiera w menu priorytetu „Poproś o P0…” — to samo okno co „Ustaw P0”
  (`SetP0Dialog mode="request"`), powód i czas obowiązkowe.
  `POST /api/jobs/{id}/p0/request` zapisuje prośbę w `jobs.p0_request_*`
  / `p0_requested_at` / `p0_requested_by` (0610; jedna oczekująca na
  rekrutację, kolejna nadpisuje) i dzwoni `job_p0_requested` do Head of
  Recruitment (bez nich — do adminów), mail obowiązkowy w rodzaju `job_p0`.
  Prośba przy trwającym P0 = 409. Panel na pulpicie pokazuje HoR
  „Prośby o P0” z „Zatwierdź P0” (`POST …/p0/request/approve` = `set_p0`
  z powodem i czasem prośby + zwykły dzwonek P0 do zespołu) i „Odrzuć”
  (`DELETE …/p0/request`); DL widzi swoją prośbę z „Wycofaj” (ta sama
  trasa). Ustawienie P0 przez HoR i zamknięcie rekrutacji czyszczą prośbę.
  Ślad: `p0_requested`, `p0_request_rejected` w Historii zdarzeń. DL dalej
  **nie** ustawia P0 sam — decyzja z 27.10 o rozlewaniu się P0 obowiązuje.
- **Panel = wiersze tablicy requestów z Daily** (`RequestBoard onlyJobIds`
  → `RequestBoardView tableOnly`): numer u klienta, tytuł, termin, Zweryf.,
  QC CV, Wysłani, rekruterzy z „+ osoba”. Od razu najwyżej 3 P0
  (`P0_PANEL_VISIBLE`; 5 wierszy to cały ekran 1280 × 720), reszta pod
  „Pokaż wszystkie”. Powód P0 stoi linijką pod tytułem wiersza (także na
  Daily). P0 spoza tablicy requestów (inny stan niż „Szukamy”) albo gdy jej
  zapytanie nie przyszło — zapasowy wiersz jak przed 28.10, panel nie znika.
