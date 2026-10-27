# P0 — rekrutacja ultrapilna przez 24 h (27.10.2026)
<!-- indeks: nakładka p0_until nad jobs.priority (nie enum); ustawia HoR i admin z powodem; 24 h / 48 h / do piątku; bez limitu; na górze listy, Daily, requestów; stały panel na pulpicie u każdego; dzwonek + mail obowiązkowy do zespołu -->

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
- **Pulpit**: stały panel „P0 — ultrapilne teraz” nad kafelkami u każdego,
  niezależnie od własnego układu (nie kafelek do usunięcia); znika, gdy nie
  ma żadnego P0.
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
